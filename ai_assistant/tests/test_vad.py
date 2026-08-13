import struct

from ai_assistant.service.vad import SegmentEvent, UtteranceSegmenter

FRAME_SAMPLES = 256
FRAME_BYTES = FRAME_SAMPLES * 2


def speech_frame():
    return struct.pack("<{0}h".format(FRAME_SAMPLES), *([5000] * FRAME_SAMPLES))


def silent_frame():
    return struct.pack("<{0}h".format(FRAME_SAMPLES), *([0] * FRAME_SAMPLES))


class AmplitudeDetector:
    """Речь — там, где первый отсчёт ненулевой. Детерминированно и без модели."""

    def is_speech(self, frame):
        first = struct.unpack("<h", frame[:2])[0]
        return first != 0


def segmenter(pause_ms=100, silence_timeout_ms=500):
    return UtteranceSegmenter(
        AmplitudeDetector(), pause_ms=pause_ms, silence_timeout_ms=silence_timeout_ms
    )


def test_silence_alone_produces_no_utterance():
    seg = segmenter()
    events = seg.feed(silent_frame() * 2)
    assert [e for e in events if e.kind == "utterance"] == []


def test_speech_is_not_emitted_until_the_pause_is_long_enough():
    seg = segmenter(pause_ms=100)
    events = seg.feed(speech_frame() * 3)
    assert events == []


def test_utterance_is_emitted_after_the_pause():
    # Кадр = 256 отсчётов при 8000 Гц = 32 мс. Для паузы 100 мс нужно 4 тихих кадра.
    seg = segmenter(pause_ms=100)
    seg.feed(speech_frame() * 3)
    events = seg.feed(silent_frame() * 4)
    utterances = [e for e in events if e.kind == "utterance"]
    assert len(utterances) == 1
    assert len(utterances[0].pcm) == 3 * FRAME_BYTES


def test_two_phrases_are_emitted_separately():
    seg = segmenter(pause_ms=100)
    seg.feed(speech_frame() * 2)
    first = seg.feed(silent_frame() * 4)
    seg.feed(speech_frame() * 5)
    second = seg.feed(silent_frame() * 4)
    assert len([e for e in first if e.kind == "utterance"]) == 1
    assert len([e for e in second if e.kind == "utterance"]) == 1
    assert len([e for e in second if e.kind == "utterance"][0].pcm) == 5 * FRAME_BYTES


def test_long_silence_without_speech_reports_silence_event():
    seg = segmenter(silence_timeout_ms=500)
    # 500 мс тишины = 16 кадров по 32 мс
    events = seg.feed(silent_frame() * 16)
    silences = [e for e in events if e.kind == "silence"]
    assert len(silences) == 1
    assert silences[0].silence_ms >= 500


def test_silence_event_is_reported_only_once():
    seg = segmenter(silence_timeout_ms=500)
    seg.feed(silent_frame() * 16)
    events = seg.feed(silent_frame() * 16)
    assert [e for e in events if e.kind == "silence"] == []


def test_speech_rearms_the_silence_event():
    seg = segmenter(pause_ms=100, silence_timeout_ms=500)
    seg.feed(silent_frame() * 16)
    seg.feed(speech_frame() * 2)
    seg.feed(silent_frame() * 4)
    events = seg.feed(silent_frame() * 16)
    assert len([e for e in events if e.kind == "silence"]) == 1


def test_partial_frames_are_buffered_between_calls():
    seg = segmenter(pause_ms=100)
    half = FRAME_BYTES // 2
    payload = speech_frame() * 3
    seg.feed(payload[:half])
    seg.feed(payload[half:])
    events = seg.feed(silent_frame() * 4)
    utterances = [e for e in events if e.kind == "utterance"]
    assert len(utterances) == 1
    assert len(utterances[0].pcm) == 3 * FRAME_BYTES


def test_reset_drops_accumulated_audio():
    seg = segmenter(pause_ms=100)
    seg.feed(speech_frame() * 3)
    seg.reset()
    events = seg.feed(silent_frame() * 4)
    assert [e for e in events if e.kind == "utterance"] == []


def test_utterance_not_emitted_one_frame_before_pause():
    # Пауза 100 мс = 4 кадра. 3 кадра должны быть недостаточными.
    seg = segmenter(pause_ms=100)
    seg.feed(speech_frame() * 3)
    events = seg.feed(silent_frame() * 3)
    utterances = [e for e in events if e.kind == "utterance"]
    assert utterances == []


def test_silence_event_not_emitted_one_frame_before_timeout():
    # Таймаут 500 мс = 16 кадров. 15 кадров должны быть недостаточными.
    seg = segmenter(silence_timeout_ms=500)
    events = seg.feed(silent_frame() * 15)
    silences = [e for e in events if e.kind == "silence"]
    assert silences == []
