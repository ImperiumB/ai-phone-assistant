"""Логика диалога прототипа.

Формат запроса и ответа повторяет ReturnConversationIntermediateResult3 из ERP:
список пар Key/Value. Когда логика переедет в обработчик, в AGI-скрипте
поменяется только адрес.
"""
import hashlib
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

_WORD_RE = re.compile(r"\w+")

POINT_START = "Start"
POINT_ASK_QUESTION = "AskQuestion"
POINT_CONFIRM = "Confirm"
POINT_FINISHED = "Finished"

ACTION_RECOGNIZE = "Recognize"
ACTION_REDIRECT = "Redirect"
ACTION_HANGUP = "Hangup"

SCENARIO_SUPPORT = "redirect_support"
SCENARIO_SALES = "redirect_sales"


@dataclass
class Phrases:
    greeting: str
    misrecognition: str
    transfer: str
    silence: str


def prms_to_dict(items: List[Dict[str, Any]]) -> Dict[str, str]:
    return {str(item["Key"]): str(item["Value"]) for item in items}


def dict_to_prms(data: Dict[str, str]) -> List[Dict[str, str]]:
    return [{"Key": key, "Value": value} for key, value in data.items()]


def _playback_name(text: str) -> str:
    """Имя файла кэша: устойчивый хеш от текста. Пробелов быть не должно."""
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
    return "aia_" + digest


class _SessionState:
    def __init__(self) -> None:
        self.record = None
        self.silence_count = 0


class DialogEngine:
    def __init__(self, knowledge, phrases: Phrases, support_exten: str, sales_exten: str):
        self._knowledge = knowledge
        self._phrases = phrases
        self._support_exten = support_exten
        self._sales_exten = sales_exten
        self._sessions: Dict[str, _SessionState] = {}

    def _session(self, linked_id: str) -> _SessionState:
        if linked_id not in self._sessions:
            self._sessions[linked_id] = _SessionState()
        return self._sessions[linked_id]

    def handle(self, prms: Dict[str, str]) -> List[Dict[str, str]]:
        linked_id = prms.get("linkedId", "")
        point = prms.get("conversationPoint") or POINT_START
        text = (prms.get("recognizedText") or "").strip().lower()
        silence = str(prms.get("silenceDetected", "")).lower() == "true"
        state = self._session(linked_id)

        if point == POINT_START:
            return self._speak(self._phrases.greeting, ACTION_RECOGNIZE, POINT_ASK_QUESTION)

        if silence:
            state.silence_count += 1
            if state.silence_count >= 2:
                return self._transfer(self._support_exten)
            return self._speak(self._phrases.silence, ACTION_RECOGNIZE, point)

        state.silence_count = 0

        if point == POINT_CONFIRM:
            return self._handle_confirmation(state, text)
        return self._handle_question(state, text)

    def _handle_question(self, state: _SessionState, text: str) -> List[Dict[str, str]]:
        found = self._knowledge.search(text) if text else None
        if found is None:
            if text:
                self._knowledge.add(text)
            return self._transfer(self._support_exten)

        record, _score = found
        if not record.clarifying_question:
            return self._transfer(self._support_exten)

        state.record = record
        return self._speak(record.clarifying_question, ACTION_RECOGNIZE, POINT_CONFIRM)

    def _handle_confirmation(self, state: _SessionState, text: str) -> List[Dict[str, str]]:
        record = state.record
        if record is None:
            return self._transfer(self._support_exten)

        if self._matches(text, record.positive_answers):
            exten = self._sales_exten if record.scenario == SCENARIO_SALES else self._support_exten
            extra = {"EquipmentType": record.equipment_type, "Scenario": record.scenario}
            return self._speak(
                record.positive_reply, ACTION_REDIRECT, POINT_FINISHED, exten=exten, extra=extra
            )

        # И отрицательный, и нераспознанный ответ ведут в одну ветку: просим переформулировать.
        state.record = None
        return self._speak(self._phrases.misrecognition, ACTION_RECOGNIZE, POINT_ASK_QUESTION)

    @staticmethod
    def _matches(text: str, variants: List[str]) -> bool:
        if not text:
            return False
        words = _WORD_RE.findall(text.lower())
        if not words:
            return False
        for variant in variants:
            variant_words = _WORD_RE.findall(variant.lower())
            if not variant_words:
                continue
            if len(variant_words) == 1:
                # Однословный вариант — точное совпадение слова, без учёта пунктуации.
                if variant_words[0] in words:
                    return True
                continue
            # Многословный вариант — его слова должны идти в ответе подряд, в том же порядке.
            span = len(variant_words)
            for start in range(len(words) - span + 1):
                if words[start:start + span] == variant_words:
                    return True
        return False

    def _transfer(self, exten: str) -> List[Dict[str, str]]:
        return self._speak(self._phrases.transfer, ACTION_REDIRECT, POINT_FINISHED, exten=exten)

    def _speak(
        self,
        text: str,
        action: str,
        point: str,
        exten: str = "",
        extra: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, str]]:
        payload = {
            "Action": action,
            "TextToSpeak": text,
            "FileToPlayback": _playback_name(text),
            "ConversationPoint": point,
            "ConversationScenario": "AiAssistantPrototype",
            "RedirectExten": exten,
        }
        if extra:
            payload.update(extra)
        return dict_to_prms(payload)
