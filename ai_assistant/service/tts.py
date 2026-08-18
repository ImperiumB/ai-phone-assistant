"""Синтез речи и кэш готовых WAV.

Asterisk (format_wav) играет только PCM 16 бит / моно / 8000 Гц. Любой другой
формат он молча отвергает, и клиент слышит тишину — так уже ловили UL-18592.
"""
import contextlib
import hashlib
import os
import uuid
import wave
from typing import Iterator, Tuple

# Модель Silero просят синтезировать на 48000 Гц, а не сразу на телефонных
# 8000 Гц, и понижают частоту сами через scipy.signal.resample_poly. Прямой
# синтез в 8000 Гц звучит заметно "деревянно" — эксперимент показал на 4-70%
# больше энергии в полосе 3400-4000 Гц (там оседают артефакты грубого
# понижения частоты) на всех пяти голосах модели по сравнению с обходным
# путём через 48 кГц. Плата — около 40-90 мс на фразу (по факту заметно
# больше первоначальной прикидки в 18 мс), что всё равно незаметно на фоне
# кэша готовых WAV (TtsCache). НЕ УПРОЩАТЬ обратно на прямой синтез в
# TELEPHONY_SAMPLE_RATE_HZ — это вернёт деревянный звук.
MODEL_SAMPLE_RATE_HZ = 48000
TELEPHONY_SAMPLE_RATE_HZ = 8000
# 48000 / 8000 = 6 — целое соотношение, идеальный случай для resample_poly
# (полифазный передискретизатор без промежуточной дробной интерполяции).
_DOWNSAMPLE_FACTOR = MODEL_SAMPLE_RATE_HZ // TELEPHONY_SAMPLE_RATE_HZ


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

    Имя временного файла уникально для каждого вызова (случайный суффикс), а
    не просто `путь + ".tmp"`. FastAPI-ручка `/tts` выполняет обработчики в
    разных потоках, и если демон перезапустили и несколько звонков разом
    просят одну и ту же ещё не закэшированную фразу, несколько потоков
    одновременно попадали бы этим же самым именем — на Windows это кладёт
    запись ошибкой доступа к файлу (см. ревью Task 9, Critical 2: так падали
    все восемь потоков в воспроизведённом сценарии). Уникальное имя убирает
    коллизию на самом временном файле, но не решает всё целиком: если два
    потока одновременно делают `os.replace(..., <тот же итоговый путь>)`,
    Windows у одного из них временами всё равно отвечает
    `PermissionError`/`WinError 5` — это подтверждено эмпирически, а не
    домысел из документации. Поэтому такую ошибку на `os.replace` не считаем
    падением: если итоговый файл на месте, значит другой поток уже успел его
    туда положить — это нормальный исход гонки, а не ошибка, и наша попытка
    просто не нужна.
    """
    tmp_path = "{0}.{1}.tmp".format(path, uuid.uuid4().hex)
    try:
        with wave.open(tmp_path, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(8000)
            handle.writeframes(pcm)
        try:
            os.replace(tmp_path, path)
        except OSError:
            if not os.path.exists(path):
                raise  # это не гонка с другим писателем, а настоящая ошибка
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
        #: Читается кэшем: при смене модели старые файлы обязаны стать недействительными.
        self.model_id = model_id

    def synthesize_at_model_rate(self, text: str, voice: str):
        """Звук прямо с модели, на её собственной частоте, без понижения.

        Телефонии это не нужно (Asterisk играет только 8000 Гц), но нужно
        генератору образцов голосов: там звук слушает человек через колонки, а
        не через телефонную линию. Отдельный метод — чтобы генератор не лез в
        приватную модель и не повторял загрузку через torch.hub со всей
        вознёй вокруг сертификатов.
        """
        return self._model.apply_tts(
            text=text, speaker=voice, sample_rate=MODEL_SAMPLE_RATE_HZ
        )

    def synthesize(self, text: str, voice: str) -> bytes:
        import numpy as np
        from scipy.signal import resample_poly

        audio_48k = self.synthesize_at_model_rate(text, voice)
        audio_8k = resample_poly(audio_48k.numpy(), up=1, down=_DOWNSAMPLE_FACTOR)
        # Обрезаем по краям диапазона после понижения частоты, а не до: у
        # полифазного фильтра есть небольшой выброс за пределы [-1, 1],
        # обрезка до ресемплинга превратила бы этот выброс в искажение.
        clipped = np.clip(audio_8k, -1.0, 1.0)
        return (clipped * 32767).astype(np.int16).tobytes()


class TtsCache:
    def __init__(self, synthesizer, cache_dir: str):
        self._synthesizer = synthesizer
        self._cache_dir = cache_dir
        self.misses = 0
        os.makedirs(cache_dir, exist_ok=True)

    def _path_for(self, text: str, voice: str) -> str:
        # В ключ входит и модель синтеза, а не только голос с текстом: иначе после
        # смены модели (v4_ru -> v5_ru) кэш продолжает отдавать старый звук, и
        # проверить новую модель на слух попросту невозможно — ровно на это
        # напоролись 13.08.2026 при первом живом звонке.
        model_id = getattr(self._synthesizer, "model_id", "")
        key = "{0}|{1}|{2}".format(model_id, voice, text).encode("utf-8")
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
