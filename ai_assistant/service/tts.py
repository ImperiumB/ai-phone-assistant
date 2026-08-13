"""Синтез речи и кэш готовых WAV.

Asterisk (format_wav) играет только PCM 16 бит / моно / 8000 Гц. Любой другой
формат он молча отвергает, и клиент слышит тишину — так уже ловили UL-18592.
"""
import contextlib
import hashlib
import os
import wave
from typing import Iterator, Tuple


@contextlib.contextmanager
def _temporary_ssl_cert_file(path: str) -> Iterator[None]:
    """Выставляет SSL_CERT_FILE только на время блока и возвращает как было.

    Нужно исключительно на время torch.hub.load: gRPC-сервер и HTTP-сервис
    живут в этом же процессе и могут ходить по TLS к своим адресам (например,
    к внутреннему CA компании), поэтому подменять доверенные корни для всего
    процесса навсегда нельзя — такие соединения начнут молча падать.
    """
    had_value = "SSL_CERT_FILE" in os.environ
    previous_value = os.environ.get("SSL_CERT_FILE")
    os.environ["SSL_CERT_FILE"] = path
    try:
        yield
    finally:
        if had_value:
            os.environ["SSL_CERT_FILE"] = previous_value
        else:
            del os.environ["SSL_CERT_FILE"]


def write_wav_8k(path: str, pcm: bytes) -> None:
    """Атомарная запись: сначала .tmp, потом переименование.

    Без этого оборванный синтез оставляет в кэше битый файл, который потом
    воспроизводится тишиной при каждом звонке.
    """
    tmp_path = path + ".tmp"
    try:
        with wave.open(tmp_path, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(8000)
            handle.writeframes(pcm)
        os.replace(tmp_path, path)
    finally:
        try:
            os.remove(tmp_path)
        except FileNotFoundError:
            pass  # обычный случай: файл уже переименован


def read_wav_format(path: str) -> Tuple[int, int, int]:
    with wave.open(path, "rb") as handle:
        return handle.getnchannels(), handle.getsampwidth() * 8, handle.getframerate()


class SileroSynthesizer:
    """Боевая реализация. Модель качается через torch.hub при первом обращении."""

    def __init__(self, model_id: str = "v4_ru"):
        import certifi
        import torch

        self._torch = torch
        # На части Windows-машин системное хранилище сертификатов не доверяет
        # цепочке models.silero.ai (сертификат в порядке, но сертификат
        # издателя туда не попал), из-за чего загрузка падает с
        # CERTIFICATE_VERIFY_FAILED. Актуальный набор корневых сертификатов
        # certifi решает это без отключения проверки. Действует только на
        # время загрузки модели, см. _temporary_ssl_cert_file.
        with _temporary_ssl_cert_file(certifi.where()):
            model, _ = torch.hub.load(
                repo_or_dir="snakers4/silero-models",
                model="silero_tts",
                language="ru",
                speaker=model_id,
                trust_repo=True,
            )
        model.to(torch.device("cpu"))
        self._model = model

    def synthesize(self, text: str, voice: str) -> bytes:
        audio = self._model.apply_tts(text=text, speaker=voice, sample_rate=8000)
        clipped = self._torch.clamp(audio, -1.0, 1.0)
        return (clipped * 32767).to(self._torch.int16).numpy().tobytes()


class TtsCache:
    def __init__(self, synthesizer, cache_dir: str):
        self._synthesizer = synthesizer
        self._cache_dir = cache_dir
        self.misses = 0
        os.makedirs(cache_dir, exist_ok=True)

    def _path_for(self, text: str, voice: str) -> str:
        key = "{0}|{1}".format(voice, text).encode("utf-8")
        digest = hashlib.sha1(key).hexdigest()[:16]
        return os.path.join(self._cache_dir, "aia_{0}.wav".format(digest))

    def get(self, text: str, voice: str) -> str:
        path = self._path_for(text, voice)
        if os.path.exists(path):
            return path
        pcm = self._synthesizer.synthesize(text, voice)
        write_wav_8k(path, pcm)
        self.misses += 1
        return path
