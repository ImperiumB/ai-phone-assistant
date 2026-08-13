import pytest
from ai_assistant.service.metrics import (
    CallTimeline,
    STAGE_SPEECH_END,
    STAGE_STT_DONE,
    STAGE_DIALOG_DONE,
)


class FakeClock:
    """Управляемые часы: значения в секундах, отдаются по очереди."""

    def __init__(self, values):
        self._values = list(values)

    def __call__(self):
        return self._values.pop(0)


def test_durations_between_neighbouring_marks():
    timeline = CallTimeline("call-1", clock=FakeClock([0.0, 0.4, 0.55]))
    timeline.mark(STAGE_SPEECH_END)
    timeline.mark(STAGE_STT_DONE)
    timeline.mark(STAGE_DIALOG_DONE)

    durations = timeline.durations()
    assert durations["speech_end->stt_done"] == pytest.approx(400.0)
    assert durations["stt_done->dialog_done"] == pytest.approx(150.0)


def test_total_is_measured_from_first_to_last_mark():
    timeline = CallTimeline("call-2", clock=FakeClock([1.0, 1.2, 2.5]))
    timeline.mark(STAGE_SPEECH_END)
    timeline.mark(STAGE_STT_DONE)
    timeline.mark(STAGE_DIALOG_DONE)
    assert timeline.total_ms() == pytest.approx(1500.0)


def test_single_mark_gives_no_durations_and_zero_total():
    timeline = CallTimeline("call-3", clock=FakeClock([5.0]))
    timeline.mark(STAGE_SPEECH_END)
    assert timeline.durations() == {}
    assert timeline.total_ms() == pytest.approx(0.0)


def test_as_dict_carries_session_and_stages():
    timeline = CallTimeline("call-4", clock=FakeClock([0.0, 1.0]))
    timeline.mark(STAGE_SPEECH_END)
    timeline.mark(STAGE_STT_DONE)
    payload = timeline.as_dict()
    assert payload["session_id"] == "call-4"
    assert payload["total_ms"] == pytest.approx(1000.0)
    assert payload["durations"]["speech_end->stt_done"] == pytest.approx(1000.0)
