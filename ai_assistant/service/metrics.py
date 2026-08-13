"""Тайминги этапов обработки одной реплики. Ради этих цифр делается прототип."""
import time
from typing import Any, Callable, Dict, List, Tuple

STAGE_SPEECH_END = "speech_end"
STAGE_STT_DONE = "stt_done"
STAGE_DIALOG_DONE = "dialog_done"
STAGE_TTS_DONE = "tts_done"
STAGE_PLAYBACK_START = "playback_start"


class CallTimeline:
    def __init__(self, session_id: str, clock: Callable[[], float] = time.perf_counter):
        self.session_id = session_id
        self._clock = clock
        self._marks: List[Tuple[str, float]] = []

    def mark(self, stage: str) -> None:
        self._marks.append((stage, self._clock()))

    def mark_with_offset(self, stage: str, seconds_ago: float) -> None:
        """Помечает этап так, будто он случился `seconds_ago` секунд назад.

        Нужен для конца речи по VAD: сегментатор физически не может отдать
        событие "конец реплики" раньше, чем накопится вся настроенная пауза
        тишины (иначе не отличить финальную паузу от паузы между словами).
        Если помечать этот этап "сейчас", то есть в момент, когда пауза уже
        целиком набралась, честный замер работы движка распознавания
        занижает реальную задержку, которую пережил абонент, — он замолчал
        на всю длительность паузы раньше. Использует тот же `_clock`, что и
        обычный `mark()`, поэтому корректно сочетается с остальными метками
        таймлайна (в т.ч. в тестах с управляемыми часами).
        """
        self._marks.append((stage, self._clock() - seconds_ago))

    def durations(self) -> Dict[str, float]:
        result: Dict[str, float] = {}
        for (prev_stage, prev_at), (stage, at) in zip(self._marks, self._marks[1:]):
            result["{0}->{1}".format(prev_stage, stage)] = (at - prev_at) * 1000.0
        return result

    def total_ms(self) -> float:
        if len(self._marks) < 2:
            return 0.0
        return (self._marks[-1][1] - self._marks[0][1]) * 1000.0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "total_ms": self.total_ms(),
            "durations": self.durations(),
            "stages": [stage for stage, _ in self._marks],
        }
