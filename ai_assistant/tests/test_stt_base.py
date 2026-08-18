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
