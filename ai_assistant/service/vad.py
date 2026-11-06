"""Нарезка потока на реплики. Заменяет EOU-классификатор Яндекса."""
import math
from collections import deque
from dataclasses import dataclass
from typing import Deque, List, Protocol

FRAME_SAMPLES = 256  # Silero VAD на 8000 Гц работает окном 256 отсчётов
FRAME_BYTES = FRAME_SAMPLES * 2

# Сегментатор раньше резал речь только по паузе, без потолка длины. GigaAM
# жёстко отказывается распознавать реплику длиннее 25 секунд (бросает
# исключение — см. main.py: SpeechServicer.Recognize перехватывает его и
# молча пропускает реплику целиком). Живой человек, рассказывающий о поломке
# без трёхсекундных пауз, — обычное дело: без потолка абонент не получил бы
# ответа вообще и сидел бы в тишине до silence_timeout_ms. Значение меньше
# фактического лимита GigaAM (25 с) — запас на округление кадров и на то,
# что решение "хватит" принимается ПОСЛЕ очередного кадра, а не строго в
# момент достижения предела.
#
# 20 → 10 с (08.10.2026, 6-я волна, 269469843): клиент сказал «соедините с
# кем-нибудь оператором», дальше фон и громкое «алло-алло» без паузы в
# секунду — детектор держал реплику открытой 13 секунд до самого сброса, бот
# молчал. На записи речь после просьбы кончилась через 2–3 с, остальное шум.
# В логах за неделю реплик длиннее 10 с нет (самая длинная — ~10 с описания
# розетки, 269464554), так что потолок режет только такие зависания. Цена:
# монолог длиннее 10 с уйдёт в разговор двумя кусками.
MAX_UTTERANCE_SECONDS = 10

# Реплика — это весь звук от начала речи до паузы, а не только кадры, которые
# детектор признал речью. До 12.10.2026 сегментатор склеивал одни «речевые»
# кадры: начало слова до срабатывания детектора («с» в «сборка», «ре» в
# «ремонт») и тихие согласные внутри выбрасывались, и распознавание получало
# «орка», «от холодильника», «экспек» (тестовые звонки 12.10, 269648881 и
# 269643565 из 7-й волны). Запас перед речью — сколько тишины до первого
# речевого кадра отдать вместе с репликой; хвост — сколько тишины после.
PRE_ROLL_MS = 300
TAIL_KEEP_MS = 200


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
    # True — реплика выдана принудительно по потолку MAX_UTTERANCE_SECONDS,
    # без единой миллисекунды паузы после неё. False (обычный случай) —
    # реплика закончилась естественной паузой. Разница важна вызывающей
    # стороне (main.py): смещать метку конца речи назад на pause_seconds
    # можно только для False — при принудительной выдаче никакой паузы не
    # было, и вычитание добавило бы к замеру несуществующие секунды.
    forced: bool = False


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
        self._max_speech_frames = max(1, math.ceil((MAX_UTTERANCE_SECONDS * 1000) / self._frame_ms))
        # Фактическая (округлённая вверх до целого кадра) длительность паузы
        # в секундах — используется вызывающей стороной (main.py), чтобы
        # честно сдвинуть метку конца речи назад на длительность этой паузы
        # (см. CallTimeline.mark_with_offset): реплика физически заканчивается
        # в момент начала паузы, а не в момент, когда сегментатор наконец
        # набрал её целиком и отдал событие.
        self.pause_seconds = self._pause_frames * self._frame_ms / 1000.0
        self._pre_roll_frames = max(1, math.ceil(PRE_ROLL_MS / self._frame_ms))
        self._tail_keep_frames = max(1, math.ceil(TAIL_KEEP_MS / self._frame_ms))
        self.reset()

    def reset(self) -> None:
        self._tail = b""
        self._speech = b""
        self._silence_frames = 0
        self._silence_reported = False
        # Последние кадры тишины перед речью — уходят в реплику её началом.
        self._pre_roll: Deque[bytes] = deque(maxlen=self._pre_roll_frames)
        self._detector.reset()

    @property
    def in_utterance(self) -> bool:
        """Реплика уже началась и ещё не закрыта паузой."""
        return bool(self._speech)

    def reset_detector(self) -> None:
        """Сбросить только память детектора, не трогая накопленную реплику и запас.

        Silero VAD держит состояние между кадрами, и после разрыва потока
        (фраза бота: Asterisk на это время звук в AGI не пишет) короткое слово
        сразу за разрывом он не замечает: 13.10.2026, звонок 1791894785 —
        «новый» есть в потоке, распознаётся, свежий детектор даёт 0.85, а
        детектор с накопленным состоянием — 0 на тех же кадрах. Сброс по
        факту разрыва (main.py) ставит детектор в то же положение, что и
        свежий. Внутри реплики не сбрасываем: холодный старт режет начало слова.
        """
        if not self._speech:
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
        is_speech = self._detector.is_speech(frame)
        if is_speech:
            if not self._speech:
                # Начало реплики: сначала запас тишины перед первым речевым
                # кадром — в нём начало слова, которое детектор ещё не признал.
                self._speech = b"".join(self._pre_roll)
                self._pre_roll.clear()
            self._speech += frame
            self._silence_frames = 0
            self._silence_reported = False
            if len(self._speech) // FRAME_BYTES >= self._max_speech_frames:
                # Потолок длины реплики: не дожидаемся паузы, отдаём то, что
                # накопили, принудительно. Без этого длинная речь без пауз
                # (обычное дело у живого человека) либо молча теряет ответ на
                # движках с жёстким лимитом (GigaAM: 25 с), либо на движках
                # без лимита даёт десятки секунд счёта — то есть движки
                # оказываются в неравных условиях именно на реалистичном
                # входе, который и должен их сравнивать.
                utterance = SegmentEvent(kind="utterance", pcm=self._speech, forced=True)
                self._speech = b""
                self._silence_frames = 0
                return [utterance]
            return []

        self._silence_frames += 1

        if self._speech:
            # Тишина внутри реплики — её часть: паузы между словами и тихие
            # согласные нужны распознаванию не меньше гласных.
            self._speech += frame
            if self._silence_frames >= self._pause_frames:
                # Хвост паузы сверх нужного движку обрезаем: он только
                # удлиняет распознавание.
                drop = max(0, self._silence_frames - self._tail_keep_frames) * FRAME_BYTES
                pcm = self._speech[:len(self._speech) - drop] if drop else self._speech
                utterance = SegmentEvent(kind="utterance", pcm=pcm)
                self._speech = b""
                self._silence_frames = 0
                return [utterance]
            if len(self._speech) // FRAME_BYTES >= self._max_speech_frames:
                utterance = SegmentEvent(kind="utterance", pcm=self._speech, forced=True)
                self._speech = b""
                self._silence_frames = 0
                return [utterance]
            return []

        self._pre_roll.append(frame)

        if not self._silence_reported and self._silence_frames >= self._silence_timeout_frames:
            self._silence_reported = True
            return [
                SegmentEvent(
                    kind="silence", silence_ms=self._silence_frames * self._frame_ms
                )
            ]
        return []
