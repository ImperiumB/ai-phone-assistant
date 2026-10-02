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


def test_studio_synthesis_keeps_the_model_rate_untouched():
    """Образцы голосов для формы ERP слушает человек через колонки, а не через
    телефонную линию: понижать частоту там нечего и незачем. Боевой путь
    (synthesize) от этого не меняется — он по-прежнему ресемплит в 8000 Гц,
    см. тест выше."""
    from ai_assistant.service.tts import MODEL_SAMPLE_RATE_HZ, SileroSynthesizer

    num_samples_48k = 48000
    fake_model = _RecordingHighRateModel(num_samples_48k)
    synth = SileroSynthesizer.__new__(SileroSynthesizer)
    synth._model = fake_model

    audio = synth.synthesize_at_model_rate("здравствуйте", "eugene")

    assert fake_model.calls == [
        {"text": "здравствуйте", "speaker": "eugene", "sample_rate": MODEL_SAMPLE_RATE_HZ}
    ]
    assert len(audio) == num_samples_48k  # ни одного отсчёта не потеряно


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


# --- Громкость фразы -------------------------------------------------------
#
# Замер кэша 31.08.2026 (196 фраз): пики разъезжались от -4.6 до 0.0 дБFS, у
# десяти фраз отсчёты упирались в потолок. Обрезка бралась не из синтеза: у
# полифазного фильтра есть выброс за пределы диапазона, и прежний код срезал
# его жёстко — верхушки волны у громких фраз становились плоскими.


class _LevelModel:
    """Модель, отдающая синус заданной амплитуды."""

    def __init__(self, amplitude, num_samples=48000):
        self._amplitude = amplitude
        self._num_samples = num_samples

    def apply_tts(self, text, speaker, sample_rate):
        import torch

        t = torch.arange(self._num_samples, dtype=torch.float32)
        return torch.sin(t * 0.05) * self._amplitude


def _peak_of(pcm):
    import numpy as np

    return float(np.max(np.abs(np.frombuffer(pcm, dtype=np.int16)))) / 32768.0


def test_loud_phrase_is_scaled_down_instead_of_being_clipped():
    from ai_assistant.service.tts import TARGET_PEAK, SileroSynthesizer

    synth = SileroSynthesizer.__new__(SileroSynthesizer)
    synth._model = _LevelModel(amplitude=1.0)

    pcm = synth.synthesize("громко", "baya")

    assert _peak_of(pcm) == pytest.approx(TARGET_PEAK, abs=0.01)


def test_quiet_phrase_is_raised_to_the_same_peak():
    """Фразы не должны отличаться друг от друга по громкости только потому,
    что так вышло у модели."""
    from ai_assistant.service.tts import TARGET_PEAK, SileroSynthesizer

    synth = SileroSynthesizer.__new__(SileroSynthesizer)
    synth._model = _LevelModel(amplitude=0.2)

    pcm = synth.synthesize("тихо", "baya")

    assert _peak_of(pcm) == pytest.approx(TARGET_PEAK, abs=0.01)


def test_normalised_phrase_has_no_flat_topped_samples():
    """Прямая проверка на ту самую поломку: обрезанные по потолку отсчёты."""
    import numpy as np

    from ai_assistant.service.tts import SileroSynthesizer

    synth = SileroSynthesizer.__new__(SileroSynthesizer)
    synth._model = _LevelModel(amplitude=1.0)

    samples = np.frombuffer(synth.synthesize("громко", "baya"), dtype=np.int16)

    assert np.sum(np.abs(samples) >= 32700) == 0


def test_silence_does_not_break_normalisation():
    """Деление на ноль на пустой или молчащей фразе."""
    from ai_assistant.service.tts import SileroSynthesizer

    synth = SileroSynthesizer.__new__(SileroSynthesizer)
    synth._model = _LevelModel(amplitude=0.0)

    assert _peak_of(synth.synthesize("тишина", "baya")) == 0.0


def test_audio_pipeline_version_is_part_of_the_station_signature():
    """Правка звука обязана менять имена файлов, иначе станция продолжит играть
    прежние — так уже вышло 13.08.2026 при смене модели синтеза."""
    from ai_assistant.service.main import audio_signature_for
    from ai_assistant.service.tts import AUDIO_PIPELINE_VERSION

    signature = audio_signature_for("v5_ru", "kseniya")

    assert "v5_ru" in signature and "kseniya" in signature
    assert AUDIO_PIPELINE_VERSION in signature


# --- Эквализация под телефонную полосу -------------------------------------
#
# Замер 31.08.2026 (tools/measure_voice_quality.py, 5 голосов, 8 фраз, шум
# 12/6/0 дБ, судья vosk): доля неразобранных слов падает у всех пяти голосов,
# сильнее всего у baya — 84.6% до и 56.8% после. Энергия ниже 300 Гц, которую
# канал всё равно не пропускает, уходит с 48-71% до 8-34%.


def _band_share(pcm, low, high, rate=8000):
    import numpy as np

    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float64) / 32768.0
    spectrum = np.abs(np.fft.rfft(x)) ** 2
    freqs = np.fft.rfftfreq(len(x), 1.0 / rate)
    total = spectrum.sum()
    return spectrum[(freqs >= low) & (freqs < high)].sum() / total if total else 0.0


class _LowRumbleModel:
    """Речеподобный сигнал с большой долей низов — как настоящий синтез."""

    def apply_tts(self, text, speaker, sample_rate):
        import numpy as np
        import torch

        t = np.arange(sample_rate, dtype=np.float64) / sample_rate
        rumble = 0.7 * np.sin(2 * np.pi * 90 * t)     # ниже телефонной полосы
        voice = 0.3 * np.sin(2 * np.pi * 2500 * t)    # там, где разборчивость
        return torch.from_numpy((rumble + voice).astype("float32"))


def test_telephony_eq_removes_what_the_line_will_not_carry():
    from ai_assistant.service.tts import SileroSynthesizer

    synth = SileroSynthesizer.__new__(SileroSynthesizer)
    synth._model = _LowRumbleModel()

    pcm = synth.synthesize("проверка", "baya")

    # 90 Гц — заведомо ниже полосы канала, после среза от него почти ничего
    # не должно остаться.
    assert _band_share(pcm, 0, 300) < 0.05


def test_telephony_eq_keeps_the_intelligibility_band():
    from ai_assistant.service.tts import SileroSynthesizer

    synth = SileroSynthesizer.__new__(SileroSynthesizer)
    synth._model = _LowRumbleModel()

    pcm = synth.synthesize("проверка", "baya")

    assert _band_share(pcm, 1500, 3400) > 0.8


def test_telephony_eq_does_not_change_the_length():
    """Фраза не должна ни укоротиться, ни удлиниться: длительность уходит в
    расчёт глухоты скрипта станции, пока бот говорит."""
    import numpy as np

    from ai_assistant.service.tts import MODEL_SAMPLE_RATE_HZ, telephony_eq

    audio = np.sin(np.arange(48000) * 0.01).astype("float32")

    assert telephony_eq(audio, MODEL_SAMPLE_RATE_HZ).shape == audio.shape


def test_telephony_eq_survives_an_empty_phrase():
    import numpy as np

    from ai_assistant.service.tts import MODEL_SAMPLE_RATE_HZ, telephony_eq

    assert telephony_eq(np.array([], dtype="float32"), MODEL_SAMPLE_RATE_HZ).size == 0


def test_cache_key_includes_the_audio_pipeline_version(tmp_path, monkeypatch):
    """31.08.2026: версию обработки добавили только в подпись для станции.
    Станция скачала файлы под новыми именами, а сервис отдал ей старый звук из
    своего кэша — правки громкости и эквализации не доехали до трубки вовсе.
    Кэшей два, и версия обязана быть в обоих ключах."""
    import ai_assistant.service.tts as tts_module

    cache = tts_module.TtsCache(FakeSynthesizer(), str(tmp_path))
    before = cache._path_for("здравствуйте", "baya")

    monkeypatch.setattr(tts_module, "AUDIO_PIPELINE_VERSION", "проверочная-версия")
    after = cache._path_for("здравствуйте", "baya")

    assert before != after


# --- Vosk-TTS --------------------------------------------------------------
#
# Боевой движок с 04.09.2026. Пришёл на смену Silero не по качеству, а по
# лицензии: v5_ru опубликована как CC BY-NC, то есть некоммерческая, а бот
# работает на боевой линии коммерческой компании (UL-17568, разбор
# 03.09.2026). Заодно диктор s3 оказался разборчивее прежнего боевого голоса
# (49% против 44%).


class _FakeVoskSynth:
    """Отдаёт int16 на 22050 Гц, как настоящий vosk_tts.Synth.synth_audio."""

    def __init__(self, num_samples=22050, amplitude=8000):
        self.calls = []
        self._num_samples = num_samples
        self._amplitude = amplitude

    def synth_audio(self, text, speaker_id=0):
        import numpy as np

        self.calls.append({"text": text, "speaker_id": speaker_id})
        t = np.arange(self._num_samples, dtype=np.float64)
        return (np.sin(t * 0.05) * self._amplitude).astype("int16")


def _vosk_with(fake_synth):
    """Синтезатор без загрузки модели: 236 МБ в тестах не поднимаем."""
    from ai_assistant.service.tts import VoskSynthesizer

    synth = VoskSynthesizer.__new__(VoskSynthesizer)
    synth._synth = fake_synth
    return synth


def test_resample_ratio_is_reduced_to_whole_numbers():
    """22050 -> 8000 не делится нацело, и отношение обязано быть сокращённым.

    Без сокращения resample_poly строит фильтр на 22050 точек вместо 441 —
    это секунды на фразу вместо миллисекунд.
    """
    from ai_assistant.service.tts import resample_ratio

    assert resample_ratio(48000) == (1, 6)     # Silero, целое деление
    assert resample_ratio(22050) == (160, 441)  # Vosk, дробное отношение


def test_vosk_voice_name_maps_to_speaker_id():
    from ai_assistant.service.tts import VoskSynthesizer

    assert VoskSynthesizer.speaker_id_of("s3") == 3
    assert VoskSynthesizer.speaker_id_of("s0") == 0
    assert VoskSynthesizer.speaker_id_of(" S4 ") == 4  # пробелы и регистр не важны


def test_vosk_falls_back_to_default_voice_instead_of_dropping_the_call():
    """В AI_VOICE группы линий могли остаться имена голосов Silero.

    Группу заводили до смены движка, а значение перенести забыли. Падать на
    этом нельзя: клиент в этот момент уже в трубке.
    """
    from ai_assistant.service.tts import VoskSynthesizer

    assert VoskSynthesizer.speaker_id_of("kseniya") == 3
    assert VoskSynthesizer.speaker_id_of("") == 3


def test_vosk_synthesizes_with_the_requested_speaker():
    fake = _FakeVoskSynth()
    _vosk_with(fake).synthesize("здравствуйте", "s4")

    assert fake.calls == [{"text": "здравствуйте", "speaker_id": 4}]


def test_vosk_downsamples_its_22050_to_telephony_8000():
    """Asterisk играет только 8000 Гц, а модель отдаёт 22050 — и другой
    частоты у неё попросту нет, в отличие от Silero."""
    from ai_assistant.service.tts import TELEPHONY_SAMPLE_RATE_HZ, VOSK_SAMPLE_RATE_HZ

    assert VOSK_SAMPLE_RATE_HZ == 22050

    fake = _FakeVoskSynth(num_samples=VOSK_SAMPLE_RATE_HZ)  # ровно секунда
    pcm = _vosk_with(fake).synthesize("здравствуйте", "s3")

    # Секунда звука на телефонной частоте, с точностью до краевого отсчёта
    # полифазного фильтра.
    assert abs(len(pcm) // 2 - TELEPHONY_SAMPLE_RATE_HZ) <= 1


def test_vosk_phrase_is_normalised_to_the_same_peak_as_silero():
    """Обработка звука у движков общая, иначе голоса разъедутся по громкости
    и сравнить их на слух станет невозможно."""
    from ai_assistant.service.tts import TARGET_PEAK

    quiet = _vosk_with(_FakeVoskSynth(amplitude=800)).synthesize("тихо", "s3")
    loud = _vosk_with(_FakeVoskSynth(amplitude=32000)).synthesize("громко", "s3")

    assert _peak_of(quiet) == pytest.approx(TARGET_PEAK, abs=0.01)
    assert _peak_of(loud) == pytest.approx(TARGET_PEAK, abs=0.01)


def test_vosk_silence_does_not_break_normalisation():
    assert _peak_of(_vosk_with(_FakeVoskSynth(amplitude=0)).synthesize("тишина", "s3")) == 0.0


def test_vosk_model_id_names_the_model_folder():
    """Кэш обесценивается сменой модели. Возьми мы тут константу «vosk» —
    следующая версия модели молча доиграла бы звук предыдущей."""
    from ai_assistant.service.tts import VoskSynthesizer

    model_id = VoskSynthesizer.model_id_for(
        r"C:\AiAssistant\models\vosk-model-tts-ru-0.7-multi"
    )

    assert model_id == "vosk:vosk-model-tts-ru-0.7-multi"
    # Хвостовой разделитель не должен превращать имя в пустую строку.
    assert VoskSynthesizer.model_id_for("/opt/models/ru-0.7-multi/") == "vosk:ru-0.7-multi"


def test_unknown_engine_is_refused_loudly():
    from ai_assistant.service.tts import create_synthesizer

    with pytest.raises(ValueError, match="vosk"):
        create_synthesizer("яндекс")


def test_vosk_without_model_path_says_what_is_missing():
    """Пустой путь не должен уходить в библиотеку: та полезет качать модель с
    GitHub, который со станции недоступен, и настройка выяснится только по
    сетевому таймауту."""
    from ai_assistant.service.tts import create_synthesizer

    with pytest.raises(ValueError, match="AIA_VOSK_TTS_MODEL_PATH"):
        create_synthesizer("vosk", vosk_model_path="")


# --- Латиница, цифры и символы ---------------------------------------------
#
# Преобразователь букв в звуки у Vosk знает только кириллицу и на первой же
# латинской букве или цифре падает с KeyError — не «звучит плохо», а роняет
# синтез посреди живого звонка. Поймано 16.09.2026 при переезде: прогрев на
# боевой базе знаний дал «60 из 62 фраз», обе потерянные — про Samsung.


def test_latin_brand_is_read_the_way_people_say_it():
    """Побуквенно эти марки не прочитаешь: Dyson вышел бы «дысоном»."""
    from ai_assistant.service.tts import normalize_for_vosk

    assert "самсунг" in normalize_for_vosk("ремонт Samsung")
    assert "дайсон" in normalize_for_vosk("техника Dyson")
    assert "кэрхер" in normalize_for_vosk("техника Karcher")
    assert "ви пи эн" in normalize_for_vosk("настройка VPN")


def test_word_the_model_knows_is_left_alone():
    """Своё произношение модели лучше любой нашей транслитерации."""
    from ai_assistant.service.tts import normalize_for_vosk

    assert normalize_for_vosk("техника Bosch", {"bosch"}) == "техника Bosch"


def test_unknown_latin_word_is_transliterated_instead_of_crashing():
    from ai_assistant.service.tts import normalize_for_vosk

    spoken = normalize_for_vosk("модель Zanussi")

    assert "Zanussi" not in spoken
    assert all(not ("a" <= c.lower() <= "z") for c in spoken)


def test_numbers_are_spoken_as_numbers_not_as_separate_digits():
    """«один пять ноль ноль» звучит как считалка, а не как цена."""
    from ai_assistant.service.tts import normalize_for_vosk, number_to_words

    assert number_to_words("0") == "ноль"
    assert number_to_words("15") == "пятнадцать"
    assert number_to_words("1500") == "одна тысяча пятьсот"
    assert number_to_words("2000") == "две тысячи"
    assert number_to_words("5000") == "пять тысяч"
    assert number_to_words("21") == "двадцать один"
    assert number_to_words("101") == "сто один"
    assert normalize_for_vosk("цена 1500 рублей") == "цена одна тысяча пятьсот рублей"


def test_very_long_number_is_read_digit_by_digit():
    """Одиннадцать цифр — это телефон или номер заказа, а не количество."""
    from ai_assistant.service.tts import number_to_words

    assert number_to_words("89261234567").startswith("восемь девять два")


def test_symbols_that_mean_something_are_spoken():
    from ai_assistant.service.tts import normalize_for_vosk

    assert "процентов" in normalize_for_vosk("скидка 20%")
    assert "номер" in normalize_for_vosk("заказ №15")


def test_punctuation_is_kept_because_pauses_live_on_it():
    from ai_assistant.service.tts import normalize_for_vosk

    assert normalize_for_vosk("Да, конечно. Что случилось?") == "Да, конечно. Что случилось?"


def test_unknown_symbol_is_dropped_rather_than_crashing():
    from ai_assistant.service.tts import normalize_for_vosk

    assert normalize_for_vosk("цена ₽") == "цена "


def test_stress_mark_survives_normalisation():
    """`+` — знак ударения самой модели, а не мусор."""
    from ai_assistant.service.tts import normalize_for_vosk

    assert normalize_for_vosk("к+ошка") == "к+ошка"


def test_every_live_knowledge_base_phrase_with_latin_survives():
    """Ровно те четыре записи боевой базы знаний, на которых синтез падал
    (проверено запросом к AI_KNOWLEDGE_BASE 16.09.2026)."""
    from ai_assistant.service.tts import normalize_for_vosk

    live = [
        "Правильно я понял, что вас интересует ремонт устройства Samsung?",
        "Правильно я понял, что вас интересует ремонт техники Karcher?",
        "Правильно я понял, что вас интересует ремонт техники Dyson?",
        "Правильно я понял, что вас интересует установка и настройка VPN?",
    ]
    for phrase in live:
        spoken = normalize_for_vosk(phrase)
        assert all(not ("a" <= c.lower() <= "z") for c in spoken), spoken


def test_normalisation_is_applied_before_synthesis():
    """Главное: до g2p латиница доходить не должна вовсе."""
    fake = _FakeVoskSynth()
    synth = _vosk_with(fake)
    synth._known_words = frozenset()

    synth.synthesize("ремонт Samsung", "s3")

    assert fake.calls[0]["text"] == "ремонт самсунг"


# --- Ударения ---------------------------------------------------------------
#
# Vosk ставит ударение сам и на части слов мажет. Разбор записей 17.09.2026
# (аналитик КЦ): «ремонт печей» звучало как «п+ечей», «ноутбуков» — «ноутбук+ов».


def test_stress_is_put_where_the_model_gets_it_wrong():
    from ai_assistant.service.tts import normalize_for_vosk

    assert "печ+ей" in normalize_for_vosk("ремонт печей")
    assert "ноутб+уков" in normalize_for_vosk("ремонт ноутбуков")


def test_stress_works_regardless_of_case():
    """Регистр не важен: g2p модели всё равно приводит текст к нижнему."""
    from ai_assistant.service.tts import put_stress_marks

    assert put_stress_marks("Окон не видно") == "+окон не видно"


def test_words_without_stress_rules_are_untouched():
    from ai_assistant.service.tts import put_stress_marks

    assert put_stress_marks("ремонт холодильника") == "ремонт холодильника"


def test_stress_mark_survives_the_rest_of_normalisation():
    """`+` — знак ударения модели, нормализатор не имеет права его выбросить."""
    from ai_assistant.service.tts import normalize_for_vosk

    spoken = normalize_for_vosk("ремонт печей Samsung за 1500")
    assert "печ+ей" in spoken and "самсунг" in spoken and "тысяча" in spoken


# --- библиотека записанных голосов (CosyVoice на видеокарте, 24.09.2026) --------------

def _library(tmp_path, voices):
    """voices: {голос: [тексты]} — кладём файлы и index.tsv, как build_voice_library."""
    from ai_assistant.service.tts import library_key

    root = tmp_path / "voices"
    for voice, texts in voices.items():
        folder = root / voice
        folder.mkdir(parents=True)
        with open(folder / "index.tsv", "w", encoding="utf-8") as index:
            for text in texts:
                key = library_key(text)
                write_wav_8k(str(folder / (key + ".wav")), struct.pack("<8h", *([7] * 8)))
                index.write("%s\t%s\n" % (key, text))
    return str(root)


def test_library_key_ignores_spacing_and_case_but_not_punctuation():
    from ai_assistant.service.tts import library_key

    assert library_key("Здравствуйте,  чем могу помочь?") == library_key("здравствуйте, чем могу помочь?")
    assert library_key("да, или нет") != library_key("да... или нет")


def test_library_knows_its_voices_and_missing_phrases(tmp_path):
    from ai_assistant.service.tts import VoiceLibrary

    library = VoiceLibrary(_library(tmp_path, {"voice-a": ["Здравствуйте, чем могу помочь?"]}))

    assert library.voices == ["voice-a"]
    assert library.phrase_count("voice-a") == 1
    assert library.missing("voice-a", ["здравствуйте, чем могу помочь?", "Вы меня слышите?"]) == ["Вы меня слышите?"]
    assert library.path("Вы меня слышите?", "voice-a") is None


def test_library_fingerprint_changes_when_phrases_change(tmp_path):
    from ai_assistant.service.tts import VoiceLibrary

    one = VoiceLibrary(_library(tmp_path / "a", {"v": ["раз"]})).fingerprint
    two = VoiceLibrary(_library(tmp_path / "b", {"v": ["раз", "два"]})).fingerprint

    assert one != two


def test_recorded_synthesizer_serves_the_file_and_falls_back_otherwise(tmp_path):
    from ai_assistant.service.tts import RecordedSynthesizer, VoiceLibrary

    library = VoiceLibrary(_library(tmp_path, {"voice-a": ["Вы меня слышите?"]}))
    fallback = FakeSynthesizer()
    fallback.model_id = "vosk-x"
    synthesizer = RecordedSynthesizer(library, fallback)

    recorded = synthesizer.synthesize("вы меня слышите?", "voice-a")
    missing = synthesizer.synthesize("Что случилось?", "voice-a")
    other = synthesizer.synthesize("Вы меня слышите?", "s3")

    assert recorded == struct.pack("<8h", *([7] * 8))
    assert fallback.calls == [("Что случилось?", "voice-a"), ("Вы меня слышите?", "s3")]
    assert missing == other == struct.pack("<800h", *([1000] * 800))
    assert synthesizer.model_id.startswith("recorded-") and synthesizer.model_id.endswith("+vosk-x")


def test_missing_library_folder_means_no_voices(tmp_path):
    from ai_assistant.service.tts import VoiceLibrary

    assert VoiceLibrary(str(tmp_path / "nope")).voices == []
