import os
import struct
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
    assert not (tmp_path / "phrase.wav.tmp").exists()


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
