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
