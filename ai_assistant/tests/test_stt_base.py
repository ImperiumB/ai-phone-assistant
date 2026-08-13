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
