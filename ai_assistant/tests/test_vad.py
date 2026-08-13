import struct

import pytest

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

    def reset(self):
        pass


class CountingDetector:
    """Стоит на месте настоящей рекуррентной модели: считает свои вызовы и
    сбросы, чтобы можно было доказать, что два сегментатора с разными
    экземплярами детектора не делят между собой никакое состояние."""

    def __init__(self):
        self.speech_calls = 0
        self.reset_calls = 0

    def is_speech(self, frame):
        self.speech_calls += 1
        first = struct.unpack("<h", frame[:2])[0]
        return first != 0

    def reset(self):
        self.reset_calls += 1


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


def test_reset_resets_the_detector_too():
    """UtteranceSegmenter.reset() обязан сбрасывать не только свой буфер, но
    и состояние детектора речи (Critical 1 из ревью Task 9): у рекуррентной
    модели вроде Silero VAD своя внутренняя память между вызовами."""
    detector = CountingDetector()
    seg = UtteranceSegmenter(detector, pause_ms=100, silence_timeout_ms=500)
    # Конструктор сам вызывает reset() один раз.
    assert detector.reset_calls == 1
    seg.reset()
    assert detector.reset_calls == 2


def test_two_segmenters_with_independent_detectors_do_not_affect_each_other():
    """Ровно то, что просил ревьюер: два одновременных звонка, каждый со
    своим детектором, не должны видеть активность друг друга."""
    detector_a = CountingDetector()
    detector_b = CountingDetector()
    seg_a = UtteranceSegmenter(detector_a, pause_ms=100, silence_timeout_ms=500)
    seg_b = UtteranceSegmenter(detector_b, pause_ms=100, silence_timeout_ms=500)

    seg_a.feed(speech_frame() * 3)
    seg_a.feed(silent_frame() * 4)

    # Детектор второго звонка не должен был увидеть ни одного кадра первого.
    assert detector_b.speech_calls == 0
    assert detector_a.speech_calls > 0

    seg_b.reset()
    assert detector_b.reset_calls == 2  # свой конструктор + явный reset()
    assert detector_a.reset_calls == 1  # только свой конструктор, чужой reset() его не задел


def test_clone_produces_an_independent_detector_without_reloading_the_model():
    """Клон не должен трогать __init__ (а значит и torch.hub.load): проверяем
    заглушкой рекуррентной модели, что после клонирования состояния
    оригинала и копии расходятся независимо, а не делят один объект."""
    from ai_assistant.service.vad import SileroVoiceDetector

    class _FakeRecurrentModel:
        """Стоит на месте настоящего Silero VAD: тоже копит внутреннее
        состояние между вызовами и умеет его сбрасывать."""

        def __init__(self):
            self.state = 0

        def __call__(self, tensor, sr):
            import torch

            self.state += 1
            return torch.tensor(self.state / 10.0)

        def reset_states(self):
            self.state = 0

    import torch

    base = SileroVoiceDetector.__new__(SileroVoiceDetector)  # без сети и torch.hub.load
    base._torch = torch
    base._model = _FakeRecurrentModel()
    base._threshold = 0.5

    call_a = base.clone()
    call_b = base.clone()

    frame = speech_frame()
    call_a.is_speech(frame)
    call_a.is_speech(frame)
    call_a.is_speech(frame)

    # call_b — независимая копия: три вызова call_a не должны были её задеть.
    assert call_b._model.state == 0
    call_b.is_speech(frame)
    assert call_b._model.state == 1
    assert call_a._model.state == 3

    # И это не тот же объект модели, что у оригинала.
    assert base._model is not call_a._model
    assert call_a._model is not call_b._model


@pytest.mark.integration
def test_real_silero_clone_diverges_from_the_original_after_use():
    """Требует загрузки настоящей модели Silero VAD. Запускать отдельно:
    pytest -m integration.

    Подтверждает то же самое, но на настоящей JIT-скомпилированной модели:
    ревьюер прямо предупреждал, что deepcopy может не сработать для
    скомпилированных моделей — здесь это проверено не на заглушке."""
    import torch

    from ai_assistant.service.vad import SileroVoiceDetector

    base = SileroVoiceDetector()
    clone = base.clone()

    speech = speech_frame()
    for _ in range(5):
        base.is_speech(speech)

    base_state = base._model._state.clone()
    clone_state = clone._model._state.clone()
    assert not torch.equal(base_state, clone_state)
