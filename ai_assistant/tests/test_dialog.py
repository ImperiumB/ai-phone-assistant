import pytest

from ai_assistant.service.dialog import (
    ACTION_HANGUP,
    ACTION_RECOGNIZE,
    ACTION_REDIRECT,
    POINT_ASK_QUESTION,
    POINT_CONFIRM,
    POINT_START,
    DialogEngine,
    Phrases,
    dict_to_prms,
    prms_to_dict,
)
from ai_assistant.service.knowledge import KnowledgeRecord


class FakeKnowledge:
    """Отдаёт заранее заданную запись, независимо от текста."""

    def __init__(self, record=None, score=0.9):
        self._record = record
        self._score = score
        self.added = []

    def search(self, text):
        if self._record is None:
            return None
        return self._record, self._score

    def add(self, question):
        record = KnowledgeRecord(id=99, question=question)
        self.added.append(question)
        return record

    def save(self, path):
        pass


PHRASES = Phrases(
    greeting="Здравствуйте, чем могу помочь?",
    misrecognition="Попробуйте переформулировать вопрос, пожалуйста",
    transfer="Минуту, перевожу ваш звонок на специалиста",
    silence="Вы меня слышите?",
)

RECORD = KnowledgeRecord(
    id=1,
    question="стиральная машина не отжимает",
    clarifying_question="Правильно я понял, что вас интересует ремонт стиральной машины?",
    positive_answers=["да", "верно"],
    negative_answers=["нет", "не то"],
    positive_reply="Соединяю вас с отделом продаж",
    scenario="redirect_sales",
    equipment_type="Стиральные машины",
)


def engine(knowledge):
    return DialogEngine(knowledge, PHRASES, support_exten="489", sales_exten="500")


def answer(engine_obj, **kwargs):
    payload = {"linkedId": "call-1", "recognizedText": "", "silenceDetected": "False"}
    payload.update(kwargs)
    return prms_to_dict(engine_obj.handle(payload))


def test_start_point_greets_and_keeps_listening():
    result = answer(engine(FakeKnowledge(RECORD)), conversationPoint=POINT_START)
    assert result["TextToSpeak"] == PHRASES.greeting
    assert result["Action"] == ACTION_RECOGNIZE
    assert result["ConversationPoint"] == POINT_ASK_QUESTION


def test_empty_point_is_treated_as_start():
    result = answer(engine(FakeKnowledge(RECORD)), conversationPoint="")
    assert result["TextToSpeak"] == PHRASES.greeting
    assert result["ConversationPoint"] == POINT_ASK_QUESTION


def test_known_question_leads_to_clarifying_question():
    result = answer(
        engine(FakeKnowledge(RECORD)),
        conversationPoint=POINT_ASK_QUESTION,
        recognizedText="стиралка не крутит",
    )
    assert result["TextToSpeak"] == RECORD.clarifying_question
    assert result["Action"] == ACTION_RECOGNIZE
    assert result["ConversationPoint"] == POINT_CONFIRM


def test_unknown_question_is_stored_and_call_is_transferred_to_support():
    knowledge = FakeKnowledge(None)
    result = answer(
        engine(knowledge),
        conversationPoint=POINT_ASK_QUESTION,
        recognizedText="во сколько вы открываетесь",
    )
    assert knowledge.added == ["во сколько вы открываетесь"]
    assert result["TextToSpeak"] == PHRASES.transfer
    assert result["Action"] == ACTION_REDIRECT
    assert result["RedirectExten"] == "489"


def test_record_without_clarifying_question_is_transferred_to_support():
    bare = KnowledgeRecord(id=5, question="что-то сломалось", clarifying_question="")
    result = answer(
        engine(FakeKnowledge(bare)),
        conversationPoint=POINT_ASK_QUESTION,
        recognizedText="что-то сломалось",
    )
    assert result["Action"] == ACTION_REDIRECT
    assert result["RedirectExten"] == "489"


def test_positive_confirmation_redirects_to_sales_with_equipment_type():
    engine_obj = engine(FakeKnowledge(RECORD))
    answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, recognizedText="стиралка не крутит")
    result = answer(engine_obj, conversationPoint=POINT_CONFIRM, recognizedText="да")
    assert result["TextToSpeak"] == RECORD.positive_reply
    assert result["Action"] == ACTION_REDIRECT
    assert result["RedirectExten"] == "500"
    assert result["EquipmentType"] == "Стиральные машины"


def test_support_scenario_redirects_to_support_exten():
    support_record = KnowledgeRecord(
        id=2,
        question="приезжал мастер",
        clarifying_question="По ранее оформленному заказу?",
        positive_answers=["да"],
        negative_answers=["нет"],
        positive_reply="Соединяю с сопровождением",
        scenario="redirect_support",
    )
    engine_obj = engine(FakeKnowledge(support_record))
    answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, recognizedText="приезжал мастер")
    result = answer(engine_obj, conversationPoint=POINT_CONFIRM, recognizedText="да")
    assert result["RedirectExten"] == "489"


def test_negative_confirmation_asks_to_rephrase_and_returns_to_question():
    engine_obj = engine(FakeKnowledge(RECORD))
    answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, recognizedText="стиралка не крутит")
    result = answer(engine_obj, conversationPoint=POINT_CONFIRM, recognizedText="нет")
    assert result["TextToSpeak"] == PHRASES.misrecognition
    assert result["Action"] == ACTION_RECOGNIZE
    assert result["ConversationPoint"] == POINT_ASK_QUESTION


def test_unrecognized_confirmation_also_asks_to_rephrase():
    engine_obj = engine(FakeKnowledge(RECORD))
    answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, recognizedText="стиралка не крутит")
    result = answer(engine_obj, conversationPoint=POINT_CONFIRM, recognizedText="ну как сказать")
    assert result["TextToSpeak"] == PHRASES.misrecognition
    assert result["ConversationPoint"] == POINT_ASK_QUESTION


def test_first_silence_prompts_the_client():
    result = answer(
        engine(FakeKnowledge(RECORD)),
        conversationPoint=POINT_ASK_QUESTION,
        silenceDetected="True",
    )
    assert result["TextToSpeak"] == PHRASES.silence
    assert result["Action"] == ACTION_RECOGNIZE


def test_second_silence_transfers_the_call():
    engine_obj = engine(FakeKnowledge(RECORD))
    answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, silenceDetected="True")
    result = answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, silenceDetected="True")
    assert result["TextToSpeak"] == PHRASES.transfer
    assert result["Action"] == ACTION_REDIRECT
    assert result["RedirectExten"] == "489"


def test_speech_after_silence_resets_the_silence_counter():
    engine_obj = engine(FakeKnowledge(RECORD))
    answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, silenceDetected="True")
    answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, recognizedText="стиралка не крутит")
    result = answer(engine_obj, conversationPoint=POINT_CONFIRM, silenceDetected="True")
    assert result["Action"] == ACTION_RECOGNIZE


def test_sessions_do_not_share_state():
    engine_obj = engine(FakeKnowledge(RECORD))
    engine_obj.handle({"linkedId": "a", "conversationPoint": POINT_ASK_QUESTION, "silenceDetected": "True"})
    second = prms_to_dict(
        engine_obj.handle({"linkedId": "b", "conversationPoint": POINT_ASK_QUESTION, "silenceDetected": "True"})
    )
    assert second["Action"] == ACTION_RECOGNIZE


def test_every_answer_carries_a_playback_file_name():
    result = answer(engine(FakeKnowledge(RECORD)), conversationPoint=POINT_START)
    assert result["FileToPlayback"]
    assert " " not in result["FileToPlayback"]


def test_prms_conversion_round_trip():
    items = [{"Key": "a", "Value": "1"}, {"Key": "b", "Value": "2"}]
    assert prms_to_dict(items) == {"a": "1", "b": "2"}
    assert dict_to_prms({"a": "1"}) == [{"Key": "a", "Value": "1"}]
