import os
import struct
import threading
import wave

import pytest

from ai_assistant.service.tts import TtsCache, read_wav_format, write_wav_8k


class FakeSynthesizer:
    """Возвращает короткий тон, считая количество вызовов."""

    def __init__(self):
        self.calls = []

    def synthesize(self, text, voice):
        self.calls.append((text, voice))
        return struct.pack("<800h", *([1000] * 800))


def test_written_wav_has_format_asterisk_can_play(tmp_path):
    target = tmp_path / "phrase.wav"
    write_wav_8k(str(target), struct.pack("<400h", *([0] * 400)))
    channels, sample_width_bits, sample_rate = read_wav_format(str(target))
    assert channels == 1
    assert sample_width_bits == 16
    assert sample_rate == 8000


def test_written_wav_keeps_all_samples(tmp_path):
    target = tmp_path / "phrase.wav"
    payload = struct.pack("<400h", *(list(range(400))))
    write_wav_8k(str(target), payload)
    with wave.open(str(target), "rb") as handle:
        assert handle.getnframes() == 400


def test_no_temporary_file_is_left_behind(tmp_path):
    target = tmp_path / "phrase.wav"
    write_wav_8k(str(target), struct.pack("<10h", *([0] * 10)))
    # Имя временного файла теперь включает случайный суффикс (Critical 2 из
    # ревью Task 9), поэтому ищем по маске, а не по одному фиксированному имени.
    assert list(tmp_path.glob("*.tmp")) == []


def test_cache_synthesizes_once_for_the_same_text(tmp_path):
    synth = FakeSynthesizer()
    cache = TtsCache(synth, str(tmp_path))
    first = cache.get("здравствуйте", "baya")
    second = cache.get("здравствуйте", "baya")
    assert first == second
    assert len(synth.calls) == 1
    assert cache.misses == 1


def test_different_voices_get_different_files(tmp_path):
    synth = FakeSynthesizer()
    cache = TtsCache(synth, str(tmp_path))
    first = cache.get("здравствуйте", "baya")
    second = cache.get("здравствуйте", "aidar")
    assert first != second
    assert len(synth.calls) == 2


def test_cached_file_is_playable_wav(tmp_path):
    cache = TtsCache(FakeSynthesizer(), str(tmp_path))
    path = cache.get("здравствуйте", "baya")
    assert os.path.exists(path)
    assert read_wav_format(path) == (1, 16, 8000)


def test_cache_directory_is_created_when_missing(tmp_path):
    target_dir = tmp_path / "deep" / "cache"
    cache = TtsCache(FakeSynthesizer(), str(target_dir))
    path = cache.get("привет", "baya")
    assert os.path.exists(path)


def test_concurrent_requests_for_the_same_uncached_text_all_succeed(tmp_path):
    """Воспроизводит боевой сценарий из ревью Task 9 (Critical 2): демон
    перезапустили, кэш пуст, несколько звонков одновременно просят одну и ту
    же ещё не закэшированную фразу (например, приветствие). Раньше все
    писали во временный файл с одинаковым именем и падали с ошибкой доступа
    к файлу — ревьюер воспроизвёл восемь потоков, упали все восемь."""
    synth = FakeSynthesizer()
    cache = TtsCache(synth, str(tmp_path))

    results = []
    errors = []
    lock = threading.Lock()

    def worker():
        try:
            path = cache.get("здравствуйте", "baya")
            with lock:
                results.append(path)
        except Exception as exc:  # noqa: BLE001 — тест должен увидеть любое падение
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(results) == 8
    assert all(os.path.exists(path) for path in results)
    assert len(set(results)) == 1  # все получили путь к одному и тому же итоговому файлу
    assert read_wav_format(results[0]) == (1, 16, 8000)


class _FakeSileroModel:
    """Достаточно .to(), чтобы SileroSynthesizer.__init__ отработал без сети."""

    def to(self, device):
        return self


def _patch_torch_hub_load(monkeypatch, recorder):
    import torch

    def fake_load(*args, **kwargs):
        recorder["value_during_load"] = os.environ.get("SSL_CERT_FILE")
        return _FakeSileroModel(), None

    monkeypatch.setattr(torch.hub, "load", fake_load)


def test_ssl_cert_file_is_removed_after_init_when_it_was_absent(monkeypatch):
    """SSL_CERT_FILE нужен только на время torch.hub.load, не на весь процесс.

    Если его выставить и забыть снять, любой другой TLS-клиент в этом же
    процессе (gRPC-сервер, HTTP-сервис из задачи 9) начнёт ходить с чужим
    набором корневых сертификатов вместо системного.
    """
    from ai_assistant.service.tts import SileroSynthesizer

    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    recorder = {}
    _patch_torch_hub_load(monkeypatch, recorder)

    SileroSynthesizer("v4_ru")

    assert recorder["value_during_load"] is not None  # был выставлен во время загрузки
    assert "SSL_CERT_FILE" not in os.environ  # и снят после


def test_ssl_cert_file_is_restored_when_it_was_already_set(monkeypatch):
    """Если переменная уже стояла (например, задана оператором), её нельзя затирать."""
    from ai_assistant.service.tts import SileroSynthesizer

    monkeypatch.setenv("SSL_CERT_FILE", "C:\\custom\\ca-bundle.pem")
    recorder = {}
    _patch_torch_hub_load(monkeypatch, recorder)

    SileroSynthesizer("v4_ru")

    assert recorder["value_during_load"] is not None
    assert os.environ["SSL_CERT_FILE"] == "C:\\custom\\ca-bundle.pem"


class _RecordingHighRateModel:
    """Заглушка модели, которая помнит переданную частоту и отдаёт тензор
    известной длины на этой частоте — без загрузки настоящего Silero."""

    def __init__(self, num_samples):
        self.calls = []
        self._num_samples = num_samples

    def apply_tts(self, text, speaker, sample_rate):
        import torch

        self.calls.append({"text": text, "speaker": speaker, "sample_rate": sample_rate})
        # Значения в пределах [-1, 1], как отдаёт настоящая модель.
        return torch.linspace(-0.5, 0.5, steps=self._num_samples)


def test_synthesize_asks_model_for_48k_and_downsamples_exactly_sixfold():
    """Деревянный звук из прямого синтеза в 8000 Гц — так уже было и не
    понравилось на слух (эксперимент: 4-70% больше энергии в полосе
    3400-4000 Гц). Модель должны просить синтезировать на 48000 Гц, а
    понижать частоту до телефонных 8000 Гц должен уже наш код через
    scipy.signal.resample_poly. Этот тест обязан упасть, если кто-то
    "упростит" synthesize обратно на прямой синтез в 8000 Гц."""
    from ai_assistant.service.tts import (
        MODEL_SAMPLE_RATE_HZ,
        TELEPHONY_SAMPLE_RATE_HZ,
        SileroSynthesizer,
    )

    assert MODEL_SAMPLE_RATE_HZ == 48000
    assert TELEPHONY_SAMPLE_RATE_HZ == 8000

    num_samples_48k = 48000  # ровно секунда звука на модельной частоте
    fake_model = _RecordingHighRateModel(num_samples_48k)
    synth = SileroSynthesizer.__new__(SileroSynthesizer)  # без сети и torch.hub.load
    synth._model = fake_model

    pcm = synth.synthesize("здравствуйте", "baya")

    assert fake_model.calls == [
        {"text": "здравствуйте", "speaker": "baya", "sample_rate": MODEL_SAMPLE_RATE_HZ}
    ]
    downsample_factor = MODEL_SAMPLE_RATE_HZ // TELEPHONY_SAMPLE_RATE_HZ
    assert downsample_factor == 6
    expected_samples = num_samples_48k // downsample_factor
    assert len(pcm) == expected_samples * 2  # 16 бит = 2 байта на отсчёт


class VersionedSynthesizer(FakeSynthesizer):
    """Подставной синтезатор, у которого есть модель — как у боевого."""

    def __init__(self, model_id):
        super().__init__()
        self.model_id = model_id


def test_cache_distinguishes_models_for_the_same_text_and_voice(tmp_path):
    """Смена модели обязана обесценивать кэш.

    Иначе после переключения v4_ru -> v5_ru сервис отдаёт старый звук, и
    проверить новую модель на слух невозможно — на этом сгорел первый живой
    звонок 13.08.2026.
    """
    old = TtsCache(VersionedSynthesizer("v4_ru"), str(tmp_path))
    new = TtsCache(VersionedSynthesizer("v5_ru"), str(tmp_path))

    old_path = old.get("здравствуйте", "eugene")
    new_path = new.get("здравствуйте", "eugene")

    assert old_path != new_path
    assert os.path.exists(old_path)
    assert os.path.exists(new_path)


def test_cache_still_reuses_files_within_one_model(tmp_path):
    synth = VersionedSynthesizer("v5_ru")
    cache = TtsCache(synth, str(tmp_path))
    first = cache.get("здравствуйте", "eugene")
    second = cache.get("здравствуйте", "eugene")
    assert first == second
    assert len(synth.calls) == 1


def test_synthesizer_without_model_attribute_still_works(tmp_path):
    """Подставные синтезаторы в тестах модели не объявляют — падать нельзя."""
    cache = TtsCache(FakeSynthesizer(), str(tmp_path))
    assert os.path.exists(cache.get("привет", "eugene"))


@pytest.mark.integration
def test_silero_produces_audible_speech(tmp_path):
    """Требует загрузки модели Silero. Запускать отдельно: pytest -m integration"""
    from ai_assistant.service.tts import SileroSynthesizer

    synth = SileroSynthesizer("v4_ru")
    pcm = synth.synthesize("Здравствуйте, чем могу помочь?", "baya")
    assert len(pcm) > 8000  # больше половины секунды звука
    target = tmp_path / "silero.wav"
    write_wav_8k(str(target), pcm)
    assert read_wav_format(str(target)) == (1, 16, 8000)
