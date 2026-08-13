"""Нарезка потока на реплики. Заменяет EOU-классификатор Яндекса."""
import math
from dataclasses import dataclass
from typing import List, Protocol

FRAME_SAMPLES = 256  # Silero VAD на 8000 Гц работает окном 256 отсчётов
FRAME_BYTES = FRAME_SAMPLES * 2


class VoiceDetector(Protocol):
    """Протокол детектора речи.

    Кадр — 256 отсчётов (512 байт) при 8000 Гц, что равно 32 миллисекундам.
    """

    def is_speech(self, frame: bytes) -> bool:
        """Определить, содержит ли кадр речь.

        Args:
            frame: 512 байт (256 int16 отсчётов) при 8000 Гц.

        Returns:
            True если обнаружена речь, False если молчание.
        """
        ...

    def reset(self) -> None:
        """Сбросить внутреннее состояние детектора перед новым потоком аудио.

        Обязателен для рекуррентных моделей (Silero VAD хранит скрытое
        состояние между вызовами): без сброса кадры чужого звонка,
        обработанные тем же детектором раньше, продолжают влиять на решение.
        """
        ...


@dataclass
class SegmentEvent:
    kind: str  # "utterance" | "silence"
    pcm: bytes = b""
    silence_ms: int = 0


class SileroVoiceDetector:
    """Боевая реализация. Модель качается через torch.hub при первом обращении.

    Рекуррентная: хранит скрытое состояние между вызовами `is_speech`. Это
    смертельно опасно при нескольких одновременных звонках через общий
    экземпляр — кадры разных абонентов перемешиваются в одном состоянии, и
    сегментация речи ломается у всех сразу (см. ревью Task 9, Critical 1).

    Правильный способ пользоваться этим классом в многозвонковом сервисе:
    один раз создать "эталонный" экземпляр при старте процесса, а на каждый
    звонок брать `clone()` — глубокую копию уже загруженной модели. Это
    единственный вариант, который реально проверен на этой модели:
      - создать новый экземпляр через `torch.hub.load` заново на каждый
        звонок — на этой машине ~650-700 мс (сеть/диск/валидация репозитория
        даже из локального кэша), неприемлемо на старте каждого звонка;
      - `copy.deepcopy(model)` — измерено ~7-12 мс, и подтверждено, что для
        этой JIT-скомпилированной модели копия действительно независима
        (после копии состояния `model._state` у оригинала и копии расходятся
        при дальнейших вызовах — проверено вручную);
      - сброс состояния + блокировка на время обращения — тоже рабочий
        вариант (одиночный inference ~0.77 мс), но сериализует распознавание
        речи между всеми одновременными звонками без необходимости, когда
        `clone()` даёт полную изоляцию почти бесплатно.
    """

    def __init__(self, threshold: float = 0.5):
        import torch

        self._torch = torch
        model, _ = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            onnx=False,
            trust_repo=True,
        )
        self._model = model
        self._threshold = threshold

    def is_speech(self, frame: bytes) -> bool:
        import numpy as np

        samples = np.frombuffer(frame, dtype=np.int16).astype("float32") / 32768.0
        tensor = self._torch.from_numpy(samples)
        with self._torch.no_grad():
            probability = self._model(tensor, 8000).item()
        return probability >= self._threshold

    def reset(self) -> None:
        self._model.reset_states()

    def clone(self) -> "SileroVoiceDetector":
        """Дать независимую копию для нового звонка без повторной загрузки модели.

        Обходит `__init__` (а значит и сетевой/дисковый `torch.hub.load`) —
        глубоко копируется только уже загруженная модель. См. обоснование
        выбора в docstring класса.
        """
        import copy

        clone = SileroVoiceDetector.__new__(SileroVoiceDetector)
        clone._torch = self._torch
        clone._model = copy.deepcopy(self._model)
        clone._threshold = self._threshold
        return clone


class UtteranceSegmenter:
    def __init__(self, detector: VoiceDetector, pause_ms: int, silence_timeout_ms: int, sample_rate: int = 8000):
        self._detector = detector
        self._frame_ms = int(FRAME_SAMPLES * 1000 / sample_rate)
        # Округление вверх: иначе накопленная тишина оказывается КОРОЧЕ заданного порога
        # (500 мс при кадре 32 мс дали бы 15 кадров = 480 мс).
        self._pause_frames = max(1, math.ceil(pause_ms / self._frame_ms))
        self._silence_timeout_frames = max(1, math.ceil(silence_timeout_ms / self._frame_ms))
        # Фактическая (округлённая вверх до целого кадра) длительность паузы
        # в секундах — используется вызывающей стороной (main.py), чтобы
        # честно сдвинуть метку конца речи назад на длительность этой паузы
        # (см. CallTimeline.mark_with_offset): реплика физически заканчивается
        # в момент начала паузы, а не в момент, когда сегментатор наконец
        # набрал её целиком и отдал событие.
        self.pause_seconds = self._pause_frames * self._frame_ms / 1000.0
        self.reset()

    def reset(self) -> None:
        self._tail = b""
        self._speech = b""
        self._silence_frames = 0
        self._silence_reported = False
        self._detector.reset()

    def feed(self, pcm: bytes) -> List[SegmentEvent]:
        events: List[SegmentEvent] = []
        buffer = self._tail + pcm
        offset = 0

        while offset + FRAME_BYTES <= len(buffer):
            frame = buffer[offset:offset + FRAME_BYTES]
            offset += FRAME_BYTES
            events.extend(self._consume_frame(frame))

        self._tail = buffer[offset:]
        return events

    def _consume_frame(self, frame: bytes) -> List[SegmentEvent]:
        if self._detector.is_speech(frame):
            self._speech += frame
            self._silence_frames = 0
            self._silence_reported = False
            return []

        self._silence_frames += 1

        if self._speech:
            if self._silence_frames >= self._pause_frames:
                utterance = SegmentEvent(kind="utterance", pcm=self._speech)
                self._speech = b""
                self._silence_frames = 0
                return [utterance]
            return []

        if not self._silence_reported and self._silence_frames >= self._silence_timeout_frames:
            self._silence_reported = True
            return [
                SegmentEvent(
                    kind="silence", silence_ms=self._silence_frames * self._frame_ms
                )
            ]
        return []
