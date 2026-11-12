import struct

import pytest

from ai_assistant.service.stt.base import (
    SttEngine,
    prepare_audio,
    resample_8k_to_16k,
)


def tone_8k(samples=800):
    return struct.pack("<{0}h".format(samples), *([1000, -1000] * (samples // 2)))


def test_resampling_doubles_the_number_of_samples():
    source = tone_8k(800)
    result = resample_8k_to_16k(source)
    assert len(result) == len(source) * 2


def test_resampling_keeps_16bit_alignment():
    result = resample_8k_to_16k(tone_8k(400))
    assert len(result) % 2 == 0


def test_prepare_audio_passes_8k_through_untouched():
    source = tone_8k(400)
    assert prepare_audio(source, 8000) is source


def test_prepare_audio_resamples_for_16k_engines():
    source = tone_8k(400)
    assert len(prepare_audio(source, 16000)) == len(source) * 2


def test_prepare_audio_rejects_unsupported_rate():
    with pytest.raises(ValueError):
        prepare_audio(tone_8k(400), 44100)


def test_engine_subclass_must_implement_transcribe():
    class Incomplete(SttEngine):
        target_sample_rate = 8000

    with pytest.raises(TypeError):
        Incomplete()


def test_engine_subclass_works_when_transcribe_is_implemented():
    class Stub(SttEngine):
        target_sample_rate = 8000

        def transcribe(self, pcm):
            return "готово"

    assert Stub().transcribe(b"") == "готово"


@pytest.mark.integration
def test_vosk_recognises_speech_from_a_wav_file():
    """Требует скачанной модели Vosk. Путь задаётся AIA_VOSK_MODEL_PATH."""
    import os
    import wave

    from ai_assistant.service.stt.base import prepare_audio
    from ai_assistant.service.stt.vosk_engine import VoskEngine

    model_path = os.environ.get("AIA_VOSK_MODEL_PATH")
    if not model_path:
        pytest.skip("AIA_VOSK_MODEL_PATH не задан")
    sample = os.environ.get("AIA_TEST_WAV")
    if not sample:
        pytest.skip("AIA_TEST_WAV не задан")

    with wave.open(sample, "rb") as handle:
        assert handle.getframerate() == 8000
        pcm8k = handle.readframes(handle.getnframes())

    engine = VoskEngine(model_path)
    assert engine.target_sample_rate == 16000
    text = engine.transcribe(prepare_audio(pcm8k, engine.target_sample_rate))
    assert isinstance(text, str)
    assert text.strip()


@pytest.mark.integration
def test_gigaam_recognises_speech_from_a_wav_file():
    """Требует установленного пакета gigaam и скачанных весов."""
    import os
    import wave

    from ai_assistant.service.stt.base import prepare_audio
    from ai_assistant.service.stt.gigaam_engine import GigaamEngine

    sample = os.environ.get("AIA_TEST_WAV")
    if not sample:
        pytest.skip("AIA_TEST_WAV не задан")

    with wave.open(sample, "rb") as handle:
        assert handle.getframerate() == 8000
        pcm8k = handle.readframes(handle.getnframes())

    engine = GigaamEngine()
    assert engine.target_sample_rate == 16000
    text = engine.transcribe(prepare_audio(pcm8k, engine.target_sample_rate))
    assert isinstance(text, str)
    assert text.strip()


def _gigaam_engine_without_model():
    """GigaamEngine с пропущенным __init__: без тяжёлого импорта gigaam и без
    загрузки весов. Годится только для проверки защитной ветки transcribe()
    на вырожденном входе — до модели там дело не доходит.
    """
    from ai_assistant.service.stt.gigaam_engine import GigaamEngine

    return object.__new__(GigaamEngine)


def test_gigaam_empty_input_returns_empty_string_without_touching_the_model():
    engine = _gigaam_engine_without_model()
    assert engine.transcribe(b"") == ""


def test_gigaam_audio_shorter_than_threshold_returns_empty_string():
    from ai_assistant.service.stt.gigaam_engine import MIN_TRANSCRIBABLE_SECONDS

    engine = _gigaam_engine_without_model()
    short_samples = int(engine.target_sample_rate * MIN_TRANSCRIBABLE_SECONDS) - 1
    assert short_samples > 0
    pcm = struct.pack("<{0}h".format(short_samples), *([0] * short_samples))
    assert engine.transcribe(pcm) == ""


def test_gigaam_odd_length_input_returns_empty_string():
    engine = _gigaam_engine_without_model()
    # 2401 байт не делится на 2 (16 бит на отсчёт) — заведомо битый обрывок.
    assert engine.transcribe(b"\x00" * 2401) == ""


def test_gigaam_matches_vosks_empty_input_behaviour():
    """Суть замечания ревью: два движка, вызываемые через общий интерфейс
    SttEngine, обязаны одинаково молчать на пустом входе, а не только один
    из них. VoskEngine.transcribe() читает self._model/self._recognizer_class,
    которые расставляет только __init__ (там же живёт загрузка модели), так
    что через object.__new__ его без реальной модели не проверить — здесь
    фиксируем поведение GigaamEngine, а идентичное поведение VoskEngine на
    этом же входе проверено вручную на реальной модели (см. task-8-report.md).
    """
    engine = _gigaam_engine_without_model()
    assert engine.transcribe(b"") == ""


def test_engine_factory_passes_model_name_to_gigaam(monkeypatch):
    """Модель GigaAM должна приходить из настроек, а не быть зашитой в код."""
    import ai_assistant.service.stt.gigaam_engine as gigaam_module

    captured = {}

    class FakeGigaam:
        target_sample_rate = 16000

        def __init__(self, model_name="v3_rnnt"):
            captured["model_name"] = model_name

        def transcribe(self, pcm):
            return ""

    monkeypatch.setattr(gigaam_module, "GigaamEngine", FakeGigaam)
    from ai_assistant.service.stt.base import create_engine

    create_engine("gigaam", model_name="v3_e2e_rnnt")
    assert captured["model_name"] == "v3_e2e_rnnt"


def test_engine_factory_defaults_gigaam_to_third_version(monkeypatch):
    import ai_assistant.service.stt.gigaam_engine as gigaam_module

    captured = {}

    class FakeGigaam:
        target_sample_rate = 16000

        def __init__(self, model_name="v3_rnnt"):
            captured["model_name"] = model_name

        def transcribe(self, pcm):
            return ""

    monkeypatch.setattr(gigaam_module, "GigaamEngine", FakeGigaam)
    from ai_assistant.service.stt.base import create_engine

    create_engine("gigaam")
    assert captured["model_name"] == "v3_rnnt"


# --- Подмешивание тишины к коротким отрезкам --------------------------------
#
# Замер 18.08.2026 на синтезе пяти голосов, приведённом к телефонному виду
# (полоса 300-3400 Гц, A-law, шум линии), отрезки 110-250 мс, 320 попыток на
# каждую величину добавки, два независимых прогона с разными посевами шума:
#
#   добавка     0 мс   100 мс   200 мс   300 мс   500 мс   700 мс   1000 мс
#   прогон 1   89.1%    53.1%    70.9%    87.2%    97.8%        -         -
#   прогон 2   89.1%        -        -    85.9%    97.2%    98.1%     96.6%
#
# Отсюда и величина: 300 мс, с которых начинали, В ОБОИХ прогонах оказались
# ХУЖЕ, чем совсем без добавки, а 100-200 мс — заметно хуже. Помогает только
# добавка от 500 мс; 700 мс лучше на десятую долю процента, 1000 мс снова
# хуже. Проверять на глаз тут нечего: зависимость немонотонная.


def test_short_utterance_is_padded_with_silence_on_both_sides():
    from ai_assistant.service.stt.base import (
        SILENCE_PAD_SECONDS,
        pad_short_utterance,
    )

    source = tone_8k(4000)  # 0.5 с — короткая реплика вроде «да» или «нет»
    result = pad_short_utterance(source)

    pad_bytes = int(8000 * SILENCE_PAD_SECONDS) * 2
    assert len(result) == len(source) + 2 * pad_bytes
    assert result[pad_bytes:pad_bytes + len(source)] == source


def test_padding_added_is_actual_silence():
    from ai_assistant.service.stt.base import (
        SILENCE_PAD_SECONDS,
        pad_short_utterance,
    )

    pad_bytes = int(8000 * SILENCE_PAD_SECONDS) * 2
    result = pad_short_utterance(tone_8k(4000))

    assert result[:pad_bytes] == b"\x00" * pad_bytes
    assert result[-pad_bytes:] == b"\x00" * pad_bytes


def test_long_utterance_is_left_alone():
    """Длинная речь и так распознаётся, а добавка стоит ~250 мс на реплику.

    Замер 18.08.2026 на фразах по 3-4 секунды: без добавки медиана 771 мс,
    с 500 мс тишины — 1015 мс, при одинаковом (полном) результате 10/10.
    """
    from ai_assistant.service.stt.base import pad_short_utterance

    source = tone_8k(16000)  # 2 с
    assert pad_short_utterance(source) is source


def test_utterance_exactly_at_the_cutoff_is_left_alone():
    from ai_assistant.service.stt.base import PAD_BELOW_SECONDS, pad_short_utterance

    source = tone_8k(int(8000 * PAD_BELOW_SECONDS))
    assert pad_short_utterance(source) is source


def test_degenerate_scrap_is_not_padded():
    """Обрывок короче порога распознавания дополнять незачем.

    GigaamEngine.transcribe() отвергает такое до обращения к модели и стоит
    0.0 мс (замер 18.08.2026), а дополненный до секунды щелчок дошёл бы до
    модели и стоил бы ~450 мс на каждый посторонний звук в линии.
    """
    from ai_assistant.service.stt.base import pad_short_utterance

    scrap = tone_8k(400)  # 0.05 с
    assert pad_short_utterance(scrap) is scrap
    assert pad_short_utterance(b"") is not None
    assert pad_short_utterance(b"") == b""


def test_padding_keeps_16bit_alignment():
    from ai_assistant.service.stt.base import pad_short_utterance

    assert len(pad_short_utterance(tone_8k(2000))) % 2 == 0


def test_padding_is_shared_by_every_engine():
    """Правка общая для обоих движков, а не особенность GigaAM.

    Она живёт в base.py рядом с prepare_audio() и применяется в единственном
    месте, где вызывается transcribe(), — до выбора движка.
    """
    import inspect

    from ai_assistant.service.stt import base

    assert callable(base.pad_short_utterance)
    source = inspect.getsource(base.pad_short_utterance)
    assert "gigaam" not in source.lower()
    assert "vosk" not in source.lower()


def test_gigaam_falls_back_to_the_file_path_when_the_tensor_path_breaks():
    """Распознавание из массива идёт в обход публичного метода библиотеки.

    Оно опирается на её внутренности (forward, _decode, _device, _dtype), и
    обновление пакета может их переименовать. Тогда распознавание обязано
    продолжить работать штатным путём через файл, а не умереть: один раз
    записать ошибку в лог, поднять флаг и больше не пробовать.
    """
    engine = _gigaam_engine_without_model()
    calls = {"tensor": 0, "file": 0}

    def broken_tensor(pcm):
        calls["tensor"] += 1
        raise AttributeError("'Model' object has no attribute '_decode'")

    def working_file(pcm):
        calls["file"] += 1
        return "ремонт холодильника"

    engine._transcribe_tensor = broken_tensor
    engine._transcribe_via_file = working_file

    pcm = struct.pack("<{0}h".format(16000), *([1000] * 16000))
    assert engine.transcribe(pcm) == "ремонт холодильника"
    # Второй раз тензорный путь уже не пробуется: флаг поднят.
    assert engine.transcribe(pcm) == "ремонт холодильника"
    assert calls == {"tensor": 1, "file": 2}


def test_gigaam_uses_the_tensor_path_while_it_works():
    engine = _gigaam_engine_without_model()
    calls = {"tensor": 0, "file": 0}

    def tensor(pcm):
        calls["tensor"] += 1
        return "сантехник нужен"

    def via_file(pcm):
        calls["file"] += 1
        return "через файл"

    engine._transcribe_tensor = tensor
    engine._transcribe_via_file = via_file

    pcm = struct.pack("<{0}h".format(16000), *([1000] * 16000))
    assert engine.transcribe(pcm) == "сантехник нужен"
    assert calls == {"tensor": 1, "file": 0}


def test_gigaam_tensor_path_matches_the_file_path_on_real_audio():
    """Тексты обоих путей обязаны совпадать до символа.

    Замер 07.11.2026 на 12 живых репликах: 368 мс через файл против 281 мс из
    массива (минус 88 мс, 24 %), расхождений текста ноль. Тест повторяет сверку
    на записях, если они есть под рукой: без них смысла в нём нет и он
    пропускается.
    """
    import glob
    import os
    import wave

    pytest.importorskip("gigaam")
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    files = [p for p in sorted(glob.glob(os.path.join(repo, "debug_audio", "*.wav")))
             if "ПОТОК" not in p]
    if not files:
        pytest.skip("нет записей реплик в debug_audio")

    from ai_assistant.service.stt.gigaam_engine import GigaamEngine

    engine = GigaamEngine("v3_rnnt")
    checked = 0
    for path in files:
        with wave.open(path, "rb") as reader:
            if reader.getframerate() != engine.target_sample_rate:
                continue
            pcm = reader.readframes(reader.getnframes())
        if len(pcm) < engine.target_sample_rate:
            continue
        assert engine._transcribe_tensor(pcm).strip() == engine._transcribe_via_file(pcm).strip()
        checked += 1
        if checked >= 3:
            break
    if not checked:
        pytest.skip("подходящих записей не нашлось")


# --- Тихая реплика: вторая попытка по громкости (F9) -------------------------


def _quiet_pcm(peak=200, samples=4000):
    """Отрезок заданной тихой громкости: 4000 отсчётов 16 кГц это 0,25 с."""
    import struct

    body = []
    for i in range(samples):
        body.append(peak if i % 2 else -peak)
    return struct.pack("<%dh" % samples, *body)


def _loud_pcm(peak=20000, samples=4000):
    return _quiet_pcm(peak, samples)


class _Counting:
    """Движок, который первый раз молчит, а на громком входе отвечает."""

    def __init__(self, threshold=3000):
        self.threshold = threshold
        self.calls = []

    def __call__(self, pcm):
        import struct

        values = struct.unpack("<%dh" % (len(pcm) // 2), pcm)
        peak = max(abs(v) for v in values) if values else 0
        self.calls.append(peak)
        return "да" if peak >= self.threshold else ""


def test_quiet_utterance_gets_a_second_try_with_gain(monkeypatch):
    """Тихий ответ теряется, и это главная потеря распознавания.

    Речевой аудит (F9): 3,1 % коротких «да» и «нет» тише минус 30 дБ, один
    случай на минус 39,7 дБ. Замер 09.11.2026 на 277 записанных живых репликах:
    тише минус 30 дБ оказалось 10, подъём уровня вытащил из пустоты 3 из них и
    не сломал ни одной.
    """
    from ai_assistant.service.stt import gigaam_engine

    engine = object.__new__(gigaam_engine.GigaamEngine)
    counting = _Counting()
    monkeypatch.setattr(engine, "_transcribe_once", counting, raising=False)

    assert engine.transcribe(_quiet_pcm(peak=200)) == "да"
    # Две попытки: тихая и поднятая.
    assert len(counting.calls) == 2
    assert counting.calls[0] < counting.calls[1]


def test_a_loud_utterance_is_recognised_in_one_go(monkeypatch):
    """Вторая попытка не должна стоить времени там, где и так всё узналось."""
    from ai_assistant.service.stt import gigaam_engine

    engine = object.__new__(gigaam_engine.GigaamEngine)
    counting = _Counting()
    monkeypatch.setattr(engine, "_transcribe_once", counting, raising=False)

    assert engine.transcribe(_loud_pcm()) == "да"
    assert len(counting.calls) == 1


def test_a_loud_but_empty_utterance_is_not_retried(monkeypatch):
    """Громкая пустота это не тихая реплика: поднимать нечего.

    Для громкой пустоты есть своя ветка в диалоге («Слушаю вас» вместо
    молчания), и вторая попытка распознавания ей не нужна.
    """
    from ai_assistant.service.stt import gigaam_engine

    engine = object.__new__(gigaam_engine.GigaamEngine)
    calls = []

    def never_hears(pcm):
        calls.append(len(pcm))
        return ""

    monkeypatch.setattr(engine, "_transcribe_once", never_hears, raising=False)
    assert engine.transcribe(_loud_pcm()) == ""
    assert len(calls) == 1


def test_quiet_retry_can_be_switched_off(monkeypatch):
    """Ноль в настройке возвращает прежнее поведение без выкладки кода."""
    from ai_assistant.service.stt import gigaam_engine

    monkeypatch.setattr(gigaam_engine, "QUIET_RETRY_DBFS", 0.0)
    engine = object.__new__(gigaam_engine.GigaamEngine)
    counting = _Counting()
    monkeypatch.setattr(engine, "_transcribe_once", counting, raising=False)

    assert engine.transcribe(_quiet_pcm(peak=200)) == ""
    assert len(counting.calls) == 1


def test_normalize_peak_never_makes_it_quieter():
    """Подъём только вверх: тише делать нельзя, это потеря сигнала."""
    from ai_assistant.service.stt import gigaam_engine

    loud = _loud_pcm(peak=30000)
    assert gigaam_engine._normalize_peak(loud, -6.0) is loud
    quiet = _quiet_pcm(peak=200)
    lifted = gigaam_engine._normalize_peak(quiet, -6.0)
    assert lifted is not quiet
    assert gigaam_engine._peak_dbfs(lifted) > gigaam_engine._peak_dbfs(quiet)


def test_the_quiet_retry_threshold_covers_what_the_measurement_found():
    """Порог второй попытки стоит на -15 дБ, а не на -30.

    Прежние -30 дБ были взяты по ХВОСТУ распределения громкости, а не по тому,
    где теряется текст, и оказались вдвое строже нужного. Поймалось это на живом
    прозвоне 09.11.2026: заказчик сказал «да», бот ответил «Слушаю вас». У той
    реплики пик -15,8 дБ, первый проход вернул пустоту, подъём уровня даёт «да»,
    но вторая попытка не сработала, потому что -15,8 это ГРОМЧЕ порога -30.

    Замер по всем 251 записанной реплике: пустыми первый проход вернул 14,
    подъём вытаскивает 6, и все шесть достаются порогом -15 дБ; при -30 дБ
    доставалось три. Тест сторожит само число: вернут -30, и половина тихих
    ответов опять потеряется молча.
    """
    from ai_assistant.service.stt import gigaam_engine

    assert gigaam_engine.QUIET_RETRY_DBFS == -15.0
    # Реплика с пика -15,8 дБ обязана попадать под вторую попытку.
    assert -15.8 < gigaam_engine.QUIET_RETRY_DBFS


def test_an_utterance_at_minus_sixteen_db_is_retried(monkeypatch):
    """Ровно тот случай с прозвона: не самая тихая реплика, но текст теряется."""
    from ai_assistant.service.stt import gigaam_engine

    # Пик -15,8 дБ это примерно 0,162 полной шкалы, то есть около 5300.
    pcm = _quiet_pcm(peak=5300)
    assert -16.0 < gigaam_engine._peak_dbfs(pcm) < -15.0

    engine = object.__new__(gigaam_engine.GigaamEngine)
    # Планка пустышки выше исходного пика и ниже поднятого: так движок молчит на
    # исходной реплике и отвечает на поднятой, как было на живом прозвоне.
    counting = _Counting(threshold=10000)
    monkeypatch.setattr(engine, "_transcribe_once", counting, raising=False)

    assert engine.transcribe(pcm) == "да"
    # Две попытки: исходная и поднятая. При прежнем пороге -30 была бы одна.
    assert len(counting.calls) == 2
    assert counting.calls[0] < counting.calls[1]
