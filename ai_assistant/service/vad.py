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


@dataclass
class SegmentEvent:
    kind: str  # "utterance" | "silence"
    pcm: bytes = b""
    silence_ms: int = 0


class SileroVoiceDetector:
    """Боевая реализация. Модель качается через torch.hub при первом обращении."""

    def __init__(self, threshold: float = 0.5):
        import torch

        self._torch = torch
        model, _ = torch.hub.load(
            repo_or_dir="snakers4/silero-vad", model="silero_vad", onnx=False
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


class UtteranceSegmenter:
    def __init__(self, detector: VoiceDetector, pause_ms: int, silence_timeout_ms: int, sample_rate: int = 8000):
        self._detector = detector
        self._frame_ms = int(FRAME_SAMPLES * 1000 / sample_rate)
        # Округление вверх: иначе накопленная тишина оказывается КОРОЧЕ заданного порога
        # (500 мс при кадре 32 мс дали бы 15 кадров = 480 мс).
        self._pause_frames = max(1, math.ceil(pause_ms / self._frame_ms))
        self._silence_timeout_frames = max(1, math.ceil(silence_timeout_ms / self._frame_ms))
        self.reset()

    def reset(self) -> None:
        self._tail = b""
        self._speech = b""
        self._silence_frames = 0
        self._silence_reported = False

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
