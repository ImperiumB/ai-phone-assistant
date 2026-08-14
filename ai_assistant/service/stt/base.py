"""Интерфейс движка распознавания.

Движки сменные: телефонный канал 8 кГц может по-разному даваться разным моделям,
и прототип обязан сравнить как минимум Vosk и GigaAM на одном материале.
"""
from abc import ABC, abstractmethod

import numpy as np
from scipy.signal import resample_poly


class SttEngine(ABC):
    #: Частота, которую движок ожидает на входе.
    target_sample_rate = 8000

    @abstractmethod
    def transcribe(self, pcm: bytes) -> str:
        """Распознать одну реплику целиком. PCM 16 бит моно в target_sample_rate."""


def resample_8k_to_16k(pcm: bytes) -> bytes:
    samples = np.frombuffer(pcm, dtype=np.int16)
    upsampled = resample_poly(samples.astype(np.float32), up=2, down=1)
    clipped = np.clip(upsampled, -32768, 32767)
    return clipped.astype(np.int16).tobytes()


def prepare_audio(pcm8k: bytes, target_sample_rate: int) -> bytes:
    if target_sample_rate == 8000:
        return pcm8k
    if target_sample_rate == 16000:
        return resample_8k_to_16k(pcm8k)
    raise ValueError("Неподдерживаемая частота дискретизации: {0}".format(target_sample_rate))


def create_engine(name: str, **kwargs) -> SttEngine:
    if name == "vosk":
        from ai_assistant.service.stt.vosk_engine import VoskEngine

        return VoskEngine(kwargs["model_path"])
    if name == "gigaam":
        from ai_assistant.service.stt.gigaam_engine import GigaamEngine

        return GigaamEngine(kwargs.get("model_name", "v3_rnnt"))
    raise ValueError("Неизвестный движок распознавания: {0}".format(name))
