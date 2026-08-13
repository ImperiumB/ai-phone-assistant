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


def test_mark_with_offset_places_the_stage_earlier_than_the_current_clock_value():
    """Item 4 финального ревью: реплика рождается только после pause_ms
    тишины, а метка конца речи раньше ставилась в этот же момент — замер
    честно показывал работу движка, но не реальное ожидание абонента.
    mark_with_offset("сейчас минус пауза") должен сдвинуть метку назад."""
    timeline = CallTimeline("call-5", clock=FakeClock([10.0, 10.2]))
    timeline.mark_with_offset(STAGE_SPEECH_END, seconds_ago=3.0)
    timeline.mark(STAGE_STT_DONE)
    durations = timeline.durations()
    # (10.2) - (10.0 - 3.0) = 3.2 с = 3200 мс — включает и "виртуальный"
    # сдвиг назад на паузу, и реальное время между вызовами mark().
    assert durations["speech_end->stt_done"] == pytest.approx(3200.0)


def test_mark_with_offset_of_zero_behaves_like_a_plain_mark():
    timeline_offset = CallTimeline("call-6", clock=FakeClock([5.0, 5.5]))
    timeline_offset.mark_with_offset(STAGE_SPEECH_END, seconds_ago=0.0)
    timeline_offset.mark(STAGE_STT_DONE)

    timeline_plain = CallTimeline("call-6", clock=FakeClock([5.0, 5.5]))
    timeline_plain.mark(STAGE_SPEECH_END)
    timeline_plain.mark(STAGE_STT_DONE)

    assert timeline_offset.durations() == timeline_plain.durations()
