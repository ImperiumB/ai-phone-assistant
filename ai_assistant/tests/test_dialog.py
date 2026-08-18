import logging
import sys
import threading

import numpy as np
import pytest

from ai_assistant.service.dialog import (
    ACTION_HANGUP,
    ACTION_RECOGNIZE,
    ACTION_REDIRECT,
    POINT_ASK_QUESTION,
    POINT_CONFIRM,
    POINT_FINISHED,
    POINT_START,
    DialogEngine,
    LineProfile,
    Phrases,
    dict_to_prms,
    prms_to_dict,
)
from ai_assistant.service.knowledge import KnowledgeRecord


class FakeKnowledge:
    """Отдаёт заранее заданную запись, независимо от текста.

    best_match()/search()/threshold воспроизводят ту же связь, что и
    настоящая KnowledgeBase (см. knowledge.py): best_match всегда отдаёт
    record/score (или None, если record is None — имитирует пустую базу),
    search() дополнительно проверяет score >= threshold. Это позволяет тестам
    независимо воспроизвести и промах по порогу (record задан, score ниже
    threshold), и пустую базу (record is None).
    """

    def __init__(self, record=None, score=0.9, threshold=0.75):
        self._record = record
        self._score = score
        self.threshold = threshold
        self.added = []

    def best_match(self, text):
        if self._record is None:
            return None
        return self._record, self._score

    def search(self, text):
        match = self.best_match(text)
        if match is None or match[1] < self.threshold:
            return None
        return match

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


def test_negative_confirmation_returns_to_question():
    """На «нет» разговор возвращается к вопросу клиента.

    Формулировка при этом своя: бот не угадал тему, а не «не расслышал» —
    см. test_explicit_no_asks_what_the_client_needs. Замечание с показа
    руководству 14.08.2026: «надо его на второй круг возвращать, какой-то
    фразой вроде „Что вас интересует?“».
    """
    engine_obj = engine(FakeKnowledge(RECORD))
    answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, recognizedText="стиралка не крутит")
    result = answer(engine_obj, conversationPoint=POINT_CONFIRM, recognizedText="нет")
    assert result["TextToSpeak"] == PHRASES.wrong_guess
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


def test_confirmation_with_trailing_punctuation_matches():
    engine_obj = engine(FakeKnowledge(RECORD))
    answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, recognizedText="стиралка не крутит")
    result = answer(engine_obj, conversationPoint=POINT_CONFIRM, recognizedText="да.")
    assert result["Action"] == ACTION_REDIRECT
    assert result["RedirectExten"] == "500"


def test_confirmation_with_comma_and_extra_words_matches():
    engine_obj = engine(FakeKnowledge(RECORD))
    answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, recognizedText="стиралка не крутит")
    result = answer(engine_obj, conversationPoint=POINT_CONFIRM, recognizedText="да, верно")
    assert result["Action"] == ACTION_REDIRECT
    assert result["RedirectExten"] == "500"


def test_word_containing_positive_answer_as_prefix_is_not_a_confirmation():
    engine_obj = engine(FakeKnowledge(RECORD))
    answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, recognizedText="стиралка не крутит")
    result = answer(engine_obj, conversationPoint=POINT_CONFIRM, recognizedText="даже не знаю")
    assert result["Action"] == ACTION_RECOGNIZE
    assert result["ConversationPoint"] == POINT_ASK_QUESTION
    assert result["TextToSpeak"] == PHRASES.misrecognition


def test_word_containing_positive_answer_as_substring_is_not_a_confirmation():
    engine_obj = engine(FakeKnowledge(RECORD))
    answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, recognizedText="стиралка не крутит")
    result = answer(engine_obj, conversationPoint=POINT_CONFIRM, recognizedText="неправда")
    assert result["Action"] == ACTION_RECOGNIZE
    assert result["TextToSpeak"] == PHRASES.misrecognition


def test_multiword_variant_matches_only_when_words_are_contiguous():
    multi_record = KnowledgeRecord(
        id=3,
        question="можно доставить сегодня",
        clarifying_question="Вам подходит доставка сегодня?",
        positive_answers=["да все верно"],
        negative_answers=["нет"],
        positive_reply="Записываю доставку",
        scenario="redirect_sales",
        equipment_type="Доставка",
    )

    contiguous_engine = engine(FakeKnowledge(multi_record))
    answer(contiguous_engine, conversationPoint=POINT_ASK_QUESTION, recognizedText="можно доставить сегодня")
    contiguous_result = answer(
        contiguous_engine, conversationPoint=POINT_CONFIRM, recognizedText="да, все верно, привозите"
    )
    assert contiguous_result["Action"] == ACTION_REDIRECT
    assert contiguous_result["RedirectExten"] == "500"

    scattered_engine = engine(FakeKnowledge(multi_record))
    answer(scattered_engine, conversationPoint=POINT_ASK_QUESTION, recognizedText="можно доставить сегодня")
    scattered_result = answer(scattered_engine, conversationPoint=POINT_CONFIRM, recognizedText="все да верно")
    assert scattered_result["Action"] == ACTION_RECOGNIZE
    assert scattered_result["ConversationPoint"] == POINT_ASK_QUESTION


def test_similarity_is_logged_on_a_hit(caplog):
    """Item 6 финального ревью: порог близости — главный настроечный
    параметр прототипа, подбирается на живых звонках. Лучшая мера близости,
    текст-победитель и вердикт обязаны попадать в лог при попадании."""
    with caplog.at_level(logging.INFO, logger="aia.dialog"):
        answer(
            engine(FakeKnowledge(RECORD, score=0.91, threshold=0.75)),
            conversationPoint=POINT_ASK_QUESTION,
            recognizedText="стиралка не крутит",
        )
    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "SIMILARITY" in messages
    assert "0.9100" in messages
    assert "above threshold" in messages
    assert RECORD.question in messages


def test_similarity_is_logged_on_a_miss_too(caplog):
    """Тот же лог обязателен и на промахе — иначе после звонка видно только
    "перевели на сопровождение" без понимания, было это чуть ниже порога
    или модель вообще не поняла вопрос (см. финальное ревью)."""
    with caplog.at_level(logging.INFO, logger="aia.dialog"):
        answer(
            engine(FakeKnowledge(RECORD, score=0.5, threshold=0.75)),
            conversationPoint=POINT_ASK_QUESTION,
            recognizedText="что-то непонятное",
        )
    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "SIMILARITY" in messages
    assert "0.5000" in messages
    assert "below threshold" in messages
    assert RECORD.question in messages


def test_similarity_is_logged_even_when_the_knowledge_base_is_empty(caplog):
    with caplog.at_level(logging.INFO, logger="aia.dialog"):
        answer(
            engine(FakeKnowledge(None)),
            conversationPoint=POINT_ASK_QUESTION,
            recognizedText="во сколько вы открываетесь",
        )
    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "SIMILARITY" in messages


def test_handling_a_question_encodes_the_query_exactly_once():
    """Important из повторного ревью: _handle_question раньше звал
    best_match() дважды за одну обработку вопроса — один раз для лога и
    вердикта, второй раз внутри search() для решения. Каждый вызов
    best_match() кодирует запрос эмбеддером заново, поэтому именно тот
    отрезок, ради измерения которого делается прототип
    (speech_end->dialog_done), оказывался завышен примерно вдвое. Считаем
    через настоящую KnowledgeBase со счётчиком кодирований запроса — их
    должно быть ровно одно на одну обработку вопроса."""
    from ai_assistant.service.knowledge import KnowledgeBase, KnowledgeRecord

    class CountingEmbedder:
        """Считает только кодирования запроса (search_query:) — документы
        (search_document:) кодируются один раз при построении базы и сюда
        не относятся."""

        def __init__(self):
            self.query_calls = 0

        def encode(self, texts):
            for text in texts:
                if text.startswith("search_query: "):
                    self.query_calls += 1
            return np.vstack([[1.0, 0.0, 0.0] for _ in texts]).astype(np.float32)

    embedder = CountingEmbedder()
    record = KnowledgeRecord(
        id=1,
        question="стиральная машина не отжимает",
        clarifying_question="Правильно я понял, что вас интересует ремонт?",
        positive_answers=["да"],
        negative_answers=["нет"],
        positive_reply="Соединяю",
        scenario="redirect_sales",
        equipment_type="Стиральные машины",
    )
    knowledge = KnowledgeBase([record], embedder, threshold=0.5)
    engine_obj = engine(knowledge)

    answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, recognizedText="стиралка не крутит")

    assert embedder.query_calls == 1


def test_below_threshold_match_is_still_stored_and_transferred_to_support():
    """Промах по порогу (best_match нашёл что-то, но ниже threshold) должен
    вести себя так же, как и полное отсутствие совпадений — вопрос
    записывается для последующей ручной разметки, звонок переводится."""
    knowledge = FakeKnowledge(RECORD, score=0.5, threshold=0.75)
    result = answer(
        engine(knowledge),
        conversationPoint=POINT_ASK_QUESTION,
        recognizedText="что-то непонятное",
    )
    assert knowledge.added == ["что-то непонятное"]
    assert result["Action"] == ACTION_REDIRECT
    assert result["RedirectExten"] == "489"


def test_finished_call_via_redirect_drops_its_session_state():
    """Important 4 из ревью Task 9: демон живёт постоянно, состояние
    разговора не должно копиться бесконечно — оно обязано удаляться, когда
    разговор доходит до POINT_FINISHED."""
    engine_obj = engine(FakeKnowledge(RECORD))
    answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, recognizedText="стиралка не крутит")
    result = answer(engine_obj, conversationPoint=POINT_CONFIRM, recognizedText="да")
    assert result["ConversationPoint"] == POINT_FINISHED
    assert "call-1" not in engine_obj._sessions


def test_finished_call_via_second_silence_drops_its_session_state():
    engine_obj = engine(FakeKnowledge(RECORD))
    answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, silenceDetected="True")
    result = answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, silenceDetected="True")
    assert result["ConversationPoint"] == POINT_FINISHED
    assert "call-1" not in engine_obj._sessions


def test_unfinished_call_keeps_its_session_state():
    engine_obj = engine(FakeKnowledge(RECORD))
    answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, recognizedText="стиралка не крутит")
    assert "call-1" in engine_obj._sessions


def test_oldest_session_is_evicted_when_the_limit_is_reached():
    """Подстраховка на звонки, которые никогда явно не завершаются
    (POINT_FINISHED не наступает) — самая старая сессия должна вытесняться,
    чтобы не расти бесконечно даже в этом случае."""
    engine_obj = DialogEngine(
        FakeKnowledge(RECORD), PHRASES, support_exten="489", sales_exten="500", max_sessions=2
    )
    engine_obj.handle({"linkedId": "a", "conversationPoint": POINT_ASK_QUESTION, "silenceDetected": "True"})
    engine_obj.handle({"linkedId": "b", "conversationPoint": POINT_ASK_QUESTION, "silenceDetected": "True"})
    assert set(engine_obj._sessions) == {"a", "b"}

    engine_obj.handle({"linkedId": "c", "conversationPoint": POINT_ASK_QUESTION, "silenceDetected": "True"})
    assert set(engine_obj._sessions) == {"b", "c"}  # "a" — самая старая, вытеснена


def test_concurrent_session_creation_at_the_limit_does_not_crash_or_overflow():
    """Повторное ревью Task 9: вытеснение самой старой сессии в _session() —
    это последовательность "проверить длину -> взять первый ключ итератором
    -> удалить -> вставить" без какой-либо защиты от одновременного доступа.
    `/dialog` — обычная функция FastAPI, конкурентные звонки реально
    выполняют handle() в разных потоках. Когда несколько потоков одновременно
    упираются в потолок сессий, возможны RuntimeError ("dictionary changed
    size during iteration") и KeyError на повторном удалении одного и того
    же "самого старого" ключа — оба валят конкретный звонок необработанным
    исключением.

    Окно гонки очень узкое (весь конфликт — внутри пары строк кода), поэтому
    здесь два усилителя: `threading.Barrier`, чтобы все потоки вошли в
    handle() как можно синхроннее, и предельно частое переключение контекста
    интерпретатора (`sys.setswitchinterval`). Без обоих усилителей сразу
    гонка на этой машине не ловится за разумное время (проверено: с одним
    только уменьшенным интервалом переключения — 0 падений за 10 прогонов;
    с обоими усилителями и снятой блокировкой в коде — падения были в каждом
    из 10 прогонов, 8-16 из 64 вызовов). Предыдущее значение интервала
    переключения обязательно возвращается в finally, иначе весь остальной
    набор тестов после этого теста станет заметно медленнее."""
    max_sessions = 20
    engine_obj = DialogEngine(
        FakeKnowledge(RECORD), PHRASES, support_exten="489", sales_exten="500", max_sessions=max_sessions
    )
    for i in range(max_sessions):
        engine_obj.handle(
            {"linkedId": "seed-{0}".format(i), "conversationPoint": POINT_ASK_QUESTION, "silenceDetected": "True"}
        )
    assert len(engine_obj._sessions) == max_sessions

    worker_count = 64
    errors = []
    errors_lock = threading.Lock()
    barrier = threading.Barrier(worker_count)

    def worker(i):
        barrier.wait()  # выровнять старт всех потоков как можно точнее
        try:
            engine_obj.handle(
                {
                    "linkedId": "new-{0}".format(i),
                    "conversationPoint": POINT_ASK_QUESTION,
                    "silenceDetected": "True",
                }
            )
        except Exception as exc:  # noqa: BLE001 — тест должен увидеть любое падение
            with errors_lock:
                errors.append(exc)

    previous_switch_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(worker_count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    finally:
        sys.setswitchinterval(previous_switch_interval)

    assert errors == []
    assert len(engine_obj._sessions) <= max_sessions


def test_playback_name_changes_with_audio_signature():
    """Имя файла обязано зависеть от модели и голоса.

    Файлы с этим именем кэшируются на самой телефонной станции. Без подписи
    смена голоса там не замечается: станция продолжает играть старые файлы
    прежним голосом — на это напоролись при первом живом звонке 13.08.2026.
    """
    from ai_assistant.service.dialog import _playback_name

    old = _playback_name("здравствуйте", "v4_ru|baya")
    new_voice = _playback_name("здравствуйте", "v4_ru|eugene")
    new_model = _playback_name("здравствуйте", "v5_ru|baya")

    assert len({old, new_voice, new_model}) == 3
    for name in (old, new_voice, new_model):
        assert name.startswith("aia_")
        assert " " not in name


def test_playback_name_is_stable_for_the_same_signature():
    from ai_assistant.service.dialog import _playback_name

    assert _playback_name("привет", "v5_ru|eugene") == _playback_name("привет", "v5_ru|eugene")


def test_engine_puts_audio_signature_into_playback_name():
    engine_obj = DialogEngine(
        FakeKnowledge(RECORD), PHRASES, support_exten="489", sales_exten="500",
        audio_signature="v5_ru|eugene",
    )
    other = DialogEngine(
        FakeKnowledge(RECORD), PHRASES, support_exten="489", sales_exten="500",
        audio_signature="v4_ru|baya",
    )
    first = answer(engine_obj, conversationPoint=POINT_START)
    second = answer(other, conversationPoint=POINT_START)

    assert first["TextToSpeak"] == second["TextToSpeak"]
    assert first["FileToPlayback"] != second["FileToPlayback"]


def test_empty_recognition_keeps_listening_instead_of_transferring():
    """Шум в линии не должен обрывать разговор переводом на специалиста.

    Живой звонок 13.08.2026: клиент включил громкую связь, щелчок дал отрезок
    короче порога распознавания, движок вернул пустую строку — и бот немедленно
    перевёл звонок, не дав человеку сказать ни слова.
    """
    engine_obj = engine(FakeKnowledge(RECORD))
    result = answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, recognizedText="")

    assert result["Action"] == ACTION_RECOGNIZE
    assert result["RedirectExten"] == ""
    assert result["TextToSpeak"] == ""
    assert result["ConversationPoint"] == POINT_ASK_QUESTION


def test_empty_recognition_does_not_pollute_the_knowledge_base():
    knowledge = FakeKnowledge(None)
    answer(engine(knowledge), conversationPoint=POINT_ASK_QUESTION, recognizedText="")
    assert knowledge.added == []


def test_empty_recognition_on_confirmation_keeps_the_found_record():
    """Шум во время уточняющего вопроса не должен сбрасывать найденную запись."""
    engine_obj = engine(FakeKnowledge(RECORD))
    answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, recognizedText="стиралка не крутит")
    noise = answer(engine_obj, conversationPoint=POINT_CONFIRM, recognizedText="   ")
    assert noise["Action"] == ACTION_RECOGNIZE
    assert noise["ConversationPoint"] == POINT_CONFIRM

    # Клиент всё-таки ответил — запись не потерялась, перевод в продажи состоялся
    result = answer(engine_obj, conversationPoint=POINT_CONFIRM, recognizedText="да")
    assert result["Action"] == ACTION_REDIRECT
    assert result["RedirectExten"] == "500"


def test_real_question_still_reaches_the_knowledge_base():
    """Защита от пустого текста не должна ломать обычный путь."""
    result = answer(
        engine(FakeKnowledge(RECORD)),
        conversationPoint=POINT_ASK_QUESTION,
        recognizedText="стиралка не крутит",
    )
    assert result["TextToSpeak"] == RECORD.clarifying_question


DIRECTION_RECORD = KnowledgeRecord(
    id=10,
    question="не морозит холодильник",
    clarifying_question="Речь о холодильнике?",
    positive_answers=["да"],
    negative_answers=["нет"],
    positive_reply="Соединяю со специалистом по холодильникам",
    scenario="redirect_direction",
    equipment_type="Холодильники",
    equipment_type_id=31,
    telephone_direction_id=52,
    redirect_exten="7104",
)


def test_direction_scenario_transfers_to_its_own_extension():
    """Перевод идёт на номер телефонного направления, а не в захардкоженный отдел."""
    engine_obj = engine(FakeKnowledge(DIRECTION_RECORD))
    answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, recognizedText="холодильник не морозит")
    result = answer(engine_obj, conversationPoint=POINT_CONFIRM, recognizedText="да")

    assert result["Action"] == ACTION_REDIRECT
    assert result["RedirectExten"] == "7104"
    assert result["EquipmentType"] == "Холодильники"
    assert result["TelephoneDirectionId"] == "52"


def test_old_sales_scenario_still_works():
    """Прежние записи без направления продолжают работать по старым сценариям."""
    engine_obj = engine(FakeKnowledge(RECORD))
    answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, recognizedText="стиралка не крутит")
    result = answer(engine_obj, conversationPoint=POINT_CONFIRM, recognizedText="да")
    assert result["RedirectExten"] == "500"


def test_direction_extension_wins_over_scenario():
    """Если у записи есть номер направления — он важнее старого сценария."""
    mixed = KnowledgeRecord(
        id=11,
        question="течёт посудомойка",
        clarifying_question="Речь о посудомоечной машине?",
        positive_answers=["да"],
        negative_answers=["нет"],
        positive_reply="Соединяю",
        scenario="redirect_sales",
        redirect_exten="7112",
    )
    engine_obj = engine(FakeKnowledge(mixed))
    answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, recognizedText="течёт посудомойка")
    result = answer(engine_obj, conversationPoint=POINT_CONFIRM, recognizedText="да")
    assert result["RedirectExten"] == "7112"


def test_explicit_no_asks_what_the_client_needs():
    """На «нет» бот не угадал тему — надо спросить, что нужно, а не просить переформулировать."""
    engine_obj = engine(FakeKnowledge(RECORD))
    answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, recognizedText="стиралка не крутит")
    result = answer(engine_obj, conversationPoint=POINT_CONFIRM, recognizedText="нет")

    assert result["TextToSpeak"] == PHRASES.wrong_guess
    assert result["Action"] == ACTION_RECOGNIZE
    assert result["ConversationPoint"] == POINT_ASK_QUESTION


def test_unrecognized_answer_still_asks_to_rephrase():
    """Нераспознанный ответ — другой случай: бот не понял, а не ошибся темой."""
    engine_obj = engine(FakeKnowledge(RECORD))
    answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, recognizedText="стиралка не крутит")
    result = answer(engine_obj, conversationPoint=POINT_CONFIRM, recognizedText="ну как сказать")

    assert result["TextToSpeak"] == PHRASES.misrecognition
    assert result["ConversationPoint"] == POINT_ASK_QUESTION


def test_second_round_after_no_leads_to_a_new_direction():
    """Второй круг рабочий: после «нет» клиент называет другую тему и попадает куда надо."""
    holodilnik = KnowledgeRecord(
        id=3,
        question="не морозит холодильник",
        clarifying_question="Речь о холодильнике?",
        positive_answers=["да"],
        negative_answers=["нет"],
        positive_reply="Соединяю со специалистом по холодильникам",
        scenario="redirect_direction",
        redirect_exten="7104",
    )

    class SwitchingKnowledge(FakeKnowledge):
        """Первый раз отдаёт стиралку, после «нет» — холодильник."""

        def __init__(self):
            super().__init__(RECORD)
            self._calls = 0

        def search(self, text):
            self._calls += 1
            return (RECORD, 0.9) if self._calls == 1 else (holodilnik, 0.9)

        def best_match(self, text):
            return self.search(text)

    engine_obj = DialogEngine(
        SwitchingKnowledge(), PHRASES, support_exten="489", sales_exten="500"
    )
    answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, recognizedText="что-то сломалось")
    after_no = answer(engine_obj, conversationPoint=POINT_CONFIRM, recognizedText="нет")
    assert after_no["TextToSpeak"] == PHRASES.wrong_guess

    second = answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, recognizedText="холодильник")
    assert second["TextToSpeak"] == holodilnik.clarifying_question
    confirmed = answer(engine_obj, conversationPoint=POINT_CONFIRM, recognizedText="да")
    assert confirmed["RedirectExten"] == "7104"


def test_real_knowledge_base_accepts_common_mishearings():
    """Согласие клиента должно ловиться и при ошибке распознавания.

    Живой звонок 14.08.2026: клиент сказал «да», GigaAM разобрал «так»,
    в списке согласий такого слова не было — бот попросил переформулировать
    вопрос, хотя человек ответил чётко. Односложное «да» на телефонном
    канале движок путает регулярно.
    """
    import json
    import pathlib

    path = pathlib.Path(__file__).resolve().parents[1] / "knowledge_base.json"
    records = json.loads(path.read_text(encoding="utf-8"))

    must_accept = ["да", "так", "ага", "угу", "верно", "точно", "конечно", "хорошо"]
    must_reject = ["нет", "не то", "неверно", "не совсем"]

    for record in records:
        positive = record["positive_answers"]
        negative = record["negative_answers"]
        for word in must_accept:
            assert word in positive, (
                "запись %s не принимает согласие %r" % (record["id"], word)
            )
        for word in must_reject:
            assert word in negative, (
                "запись %s не принимает отказ %r" % (record["id"], word)
            )
        assert not set(positive) & set(negative), (
            "запись %s: слово есть и в согласиях, и в отказах" % record["id"]
        )


def test_mishearing_of_yes_leads_to_transfer():
    """«так» вместо «да» должно приводить к переводу, а не к просьбе переформулировать."""
    record = KnowledgeRecord(
        id=1,
        question="стиральная машина не отжимает",
        clarifying_question="Речь о стиральной машине?",
        positive_answers=["да", "так", "ага", "верно"],
        negative_answers=["нет", "не то"],
        positive_reply="Соединяю со специалистом",
        scenario="redirect_direction",
        redirect_exten="7105",
    )
    for heard in ("да", "так", "ага", "верно"):
        engine_obj = engine(FakeKnowledge(record))
        answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, recognizedText="стиралка сломалась")
        result = answer(engine_obj, conversationPoint=POINT_CONFIRM, recognizedText=heard)
        assert result["Action"] == ACTION_REDIRECT, "ответ %r не принят как согласие" % heard
        assert result["RedirectExten"] == "7105"


# --- Контекст найденной записи для обращения в ERP (UL-18797) -----------------


def test_confirmation_carries_the_match_context_for_erp():
    """Найденная запись, её вопрос и мера близости обязаны доходить до AGI-скрипта.

    Раньше они оставались внутри сервиса: наружу уходил голый RedirectExten,
    и обращение в ERP заполнять было нечем.
    """
    engine_obj = engine(FakeKnowledge(DIRECTION_RECORD, score=0.83))
    answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, recognizedText="холодильник не морозит")
    result = answer(engine_obj, conversationPoint=POINT_CONFIRM, recognizedText="да")

    assert result["KnowledgeRecordId"] == "10"
    assert result["MatchedQuestion"] == DIRECTION_RECORD.question
    assert float(result["Similarity"]) == pytest.approx(0.83)
    assert result["EquipmentType"] == "Холодильники"
    assert result["TelephoneDirectionId"] == "52"
    assert result["Scenario"] == "redirect_direction"


def test_transfer_of_a_record_without_clarifying_question_carries_equipment():
    """Самый частый путь — перевод из _transfer, а не из ветки подтверждения.

    Запись нашлась выше порога, уточнять нечего — тип оборудования известен
    и обязан уйти в обращение так же, как и после подтверждения.
    """
    record = KnowledgeRecord(
        id=7,
        question="нужен мастер по кофемашине",
        clarifying_question="",
        scenario="redirect_direction",
        equipment_type="Кофемашины",
        telephone_direction_id=24,
        redirect_exten="7097",
    )
    result = answer(
        engine(FakeKnowledge(record, score=0.91)),
        conversationPoint=POINT_ASK_QUESTION,
        recognizedText="нужен мастер по кофемашине",
    )

    assert result["Action"] == ACTION_REDIRECT
    assert result["EquipmentType"] == "Кофемашины"
    assert result["TelephoneDirectionId"] == "24"
    assert result["KnowledgeRecordId"] == "7"
    assert float(result["Similarity"]) == pytest.approx(0.91)


def test_transfer_after_a_miss_reports_similarity_but_no_equipment():
    """Промах по порогу — мера близости нужна для разбора, тип оборудования нет.

    Проставить в обращении оборудование по совпадению, которому сами не
    поверили, значит соврать оператору: пусть остаётся «Неизвестное».
    """
    result = answer(
        engine(FakeKnowledge(DIRECTION_RECORD, score=0.4, threshold=0.75)),
        conversationPoint=POINT_ASK_QUESTION,
        recognizedText="а вы вообще чем занимаетесь",
    )

    assert result["Action"] == ACTION_REDIRECT
    assert float(result["Similarity"]) == pytest.approx(0.4)
    assert result["MatchedQuestion"] == DIRECTION_RECORD.question
    assert "EquipmentType" not in result
    assert "TelephoneDirectionId" not in result


def test_transfer_on_silence_has_no_match_context():
    """Клиент вообще ничего не сказал — сравнивать было не с чем."""
    engine_obj = engine(FakeKnowledge(DIRECTION_RECORD))
    answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, silenceDetected="True")
    result = answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, silenceDetected="True")

    assert result["Action"] == ACTION_REDIRECT
    assert "KnowledgeRecordId" not in result
    assert "EquipmentType" not in result


def test_empty_knowledge_base_transfer_has_no_match_context():
    result = answer(
        engine(FakeKnowledge(None)),
        conversationPoint=POINT_ASK_QUESTION,
        recognizedText="во сколько вы открываетесь",
    )

    assert result["Action"] == ACTION_REDIRECT
    assert "MatchedQuestion" not in result
    assert "Similarity" not in result


def test_clarifying_question_does_not_claim_equipment_yet():
    """Догадка ещё не подтверждена клиентом — в обращение её писать рано."""
    result = answer(
        engine(FakeKnowledge(DIRECTION_RECORD, score=0.8)),
        conversationPoint=POINT_ASK_QUESTION,
        recognizedText="холодильник не морозит",
    )

    assert result["Action"] == ACTION_RECOGNIZE
    assert "EquipmentType" not in result


def test_confirmation_carries_the_equipment_type_code():
    """Код типа оборудования уходит наружу вместе с названием.

    По названию обработчик ERP искал тип строкой — единственное место всей
    цепочки, где связь держалась на совпадении текста. С приходом кода из
    справочника поиск по названию отмирает.
    """
    engine_obj = engine(FakeKnowledge(DIRECTION_RECORD, score=0.83))
    answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, recognizedText="холодильник не морозит")
    result = answer(engine_obj, conversationPoint=POINT_CONFIRM, recognizedText="да")

    assert result["EquipmentTypeId"] == "31"


def test_transfer_without_clarifying_question_carries_the_equipment_type_code():
    record = KnowledgeRecord(
        id=7,
        question="нужен мастер по кофемашине",
        clarifying_question="",
        scenario="redirect_direction",
        equipment_type="Кофемашины",
        equipment_type_id=24,
        telephone_direction_id=24,
        redirect_exten="7097",
    )
    result = answer(
        engine(FakeKnowledge(record, score=0.91)),
        conversationPoint=POINT_ASK_QUESTION,
        recognizedText="нужен мастер по кофемашине",
    )

    assert result["EquipmentTypeId"] == "24"


def test_record_without_the_equipment_type_code_sends_an_empty_one():
    """Тема не про технику — кода нет, и подставлять вместо него нечего."""
    record = KnowledgeRecord(
        id=8,
        question="хочу оставить жалобу",
        clarifying_question="",
        scenario="redirect_direction",
        telephone_direction_id=12,
        redirect_exten="7001",
    )
    result = answer(
        engine(FakeKnowledge(record, score=0.9)),
        conversationPoint=POINT_ASK_QUESTION,
        recognizedText="хочу оставить жалобу",
    )

    assert result["EquipmentTypeId"] == ""


def test_transfer_after_a_miss_does_not_report_the_equipment_type_code():
    """Совпадению ниже порога не поверили сами — технику в обращение не пишем."""
    result = answer(
        engine(FakeKnowledge(DIRECTION_RECORD, score=0.4, threshold=0.75)),
        conversationPoint=POINT_ASK_QUESTION,
        recognizedText="а вы вообще чем занимаетесь",
    )

    assert "EquipmentTypeId" not in result


# --- Признак неопознанного вопроса для базы знаний ERP (UL-17568) -------------


def test_miss_below_threshold_is_marked_as_an_unrecognized_question():
    """Промах по порогу — единственный случай, который годится в базу знаний.

    Только сервис знает про порог близости, поэтому он и обязан назвать этот
    перевод своим именем: у AGI-скрипта порога нет и вывести признак из
    пустого типа оборудования он не может (у записи «жалоба» техники тоже
    нет).
    """
    result = answer(
        engine(FakeKnowledge(DIRECTION_RECORD, score=0.4, threshold=0.75)),
        conversationPoint=POINT_ASK_QUESTION,
        recognizedText="а вы вообще чем занимаетесь",
    )

    assert result["Action"] == ACTION_REDIRECT
    assert result["UnknownQuestion"] == "True"


def test_question_to_an_empty_knowledge_base_is_also_unrecognized():
    """Пустая база — это когда автонаполнение нужнее всего, а сравнивать не с чем."""
    result = answer(
        engine(FakeKnowledge(None)),
        conversationPoint=POINT_ASK_QUESTION,
        recognizedText="во сколько вы открываетесь",
    )

    assert result["UnknownQuestion"] == "True"


def test_found_answer_is_not_an_unrecognized_question():
    record = KnowledgeRecord(
        id=7,
        question="нужен мастер по кофемашине",
        clarifying_question="",
        scenario="redirect_direction",
        equipment_type="Кофемашины",
        redirect_exten="7097",
    )
    result = answer(
        engine(FakeKnowledge(record, score=0.91)),
        conversationPoint=POINT_ASK_QUESTION,
        recognizedText="нужен мастер по кофемашине",
    )

    assert result["Action"] == ACTION_REDIRECT
    assert "UnknownQuestion" not in result


def test_transfer_on_silence_is_not_an_unrecognized_question():
    """Вопроса не прозвучало вовсе — записывать в справочник нечего."""
    engine_obj = engine(FakeKnowledge(DIRECTION_RECORD))
    answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, silenceDetected="True")
    result = answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, silenceDetected="True")

    assert result["Action"] == ACTION_REDIRECT
    assert "UnknownQuestion" not in result


def test_confirmed_topic_is_not_an_unrecognized_question():
    engine_obj = engine(FakeKnowledge(DIRECTION_RECORD, score=0.83))
    answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, recognizedText="холодильник не морозит")
    result = answer(engine_obj, conversationPoint=POINT_CONFIRM, recognizedText="да")

    assert "UnknownQuestion" not in result


def test_wrong_guess_is_not_reported_as_an_unrecognized_question_yet():
    """Клиент ответил «нет»: бот не угадал тему, но вопрос ещё в работе.

    Разговор здесь не заканчивается — бот спрашивает, что нужно клиенту, и
    следующая же реплика либо найдётся в базе, либо честно уйдёт туда как
    промах по порогу. Отправлять исходный вопрос уже сейчас значит записать
    в справочник две строки об одном звонке.
    """
    engine_obj = engine(FakeKnowledge(DIRECTION_RECORD, score=0.83))
    answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, recognizedText="холодильник не морозит")
    result = answer(engine_obj, conversationPoint=POINT_CONFIRM, recognizedText="нет")

    assert result["Action"] == ACTION_RECOGNIZE
    assert "UnknownQuestion" not in result


# --- Переспрос в точке подтверждения (живой звонок 18.08.2026) -------------
#
# Клиент дважды ответил «нет» на уточняющий вопрос, распознавание оба раза
# вернуло пустую строку, бот промолчал — клиент решил, что бот сломался, и
# положил трубку. Молчать на пустой результат правильно в открытом вопросе
# (щелчок громкой связи легко принять за речь), но не там, где бот только что
# спросил «да или нет».


def test_first_empty_confirmation_stays_silent():
    """Первая пустая попытка по-прежнему проглатывается молча — это щелчки."""
    engine_obj = engine(FakeKnowledge(RECORD))
    answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, recognizedText="стиралка не крутит")
    result = answer(engine_obj, conversationPoint=POINT_CONFIRM, recognizedText="")

    assert result["TextToSpeak"] == ""
    assert result["Action"] == ACTION_RECOGNIZE
    assert result["ConversationPoint"] == POINT_CONFIRM


def test_second_empty_confirmation_asks_again():
    engine_obj = engine(FakeKnowledge(RECORD))
    answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, recognizedText="стиралка не крутит")
    answer(engine_obj, conversationPoint=POINT_CONFIRM, recognizedText="")
    result = answer(engine_obj, conversationPoint=POINT_CONFIRM, recognizedText="")

    assert result["TextToSpeak"] == PHRASES.confirm_not_heard
    assert result["Action"] == ACTION_RECOGNIZE
    assert result["ConversationPoint"] == POINT_CONFIRM
    assert result["RedirectExten"] == ""
    assert result["FileToPlayback"]


def test_empty_counter_resets_after_something_was_recognized():
    """Распозналось — счётчик пустых попыток обнуляется.

    Полный круг: пустая попытка в подтверждении, затем внятный ответ, затем
    разговор снова доходит до подтверждения. Первая пустая попытка на втором
    круге обязана снова быть молчаливой, а не сразу переспрашивать.
    """
    engine_obj = engine(FakeKnowledge(RECORD))
    answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, recognizedText="стиралка не крутит")
    answer(engine_obj, conversationPoint=POINT_CONFIRM, recognizedText="")
    answer(engine_obj, conversationPoint=POINT_CONFIRM, recognizedText="ну как сказать")
    answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, recognizedText="стиралка не крутит")
    result = answer(engine_obj, conversationPoint=POINT_CONFIRM, recognizedText="")

    assert result["TextToSpeak"] == ""


def test_open_question_keeps_silent_on_every_empty_recognition():
    """В открытом вопросе поведение прежнее: молчим сколько угодно раз.

    Там пустой результат — это шум в линии, а не потерянный ответ клиента:
    переспрашивать на каждый щелчок значит вернуть ровно ту поломку, ради
    которой молчание и вводили.
    """
    engine_obj = engine(FakeKnowledge(RECORD))
    for _ in range(3):
        result = answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, recognizedText="")
        assert result["TextToSpeak"] == ""
        assert result["ConversationPoint"] == POINT_ASK_QUESTION


def test_empty_confirmation_does_not_lose_the_found_record():
    """Переспрос не должен стирать найденную тему: клиент отвечает «да» после
    переспроса, и перевод обязан уйти по своей записи, а не на общий номер."""
    engine_obj = engine(FakeKnowledge(RECORD))
    answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, recognizedText="стиралка не крутит")
    answer(engine_obj, conversationPoint=POINT_CONFIRM, recognizedText="")
    answer(engine_obj, conversationPoint=POINT_CONFIRM, recognizedText="")
    result = answer(engine_obj, conversationPoint=POINT_CONFIRM, recognizedText="да")

    assert result["Action"] == ACTION_REDIRECT
    assert result["EquipmentType"] == "Стиральные машины"


def test_empty_confirmation_does_not_pollute_the_knowledge_base():
    knowledge = FakeKnowledge(RECORD)
    engine_obj = engine(knowledge)
    answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, recognizedText="стиралка не крутит")
    answer(engine_obj, conversationPoint=POINT_CONFIRM, recognizedText="")
    answer(engine_obj, conversationPoint=POINT_CONFIRM, recognizedText="")

    assert knowledge.added == []


def test_confirm_not_heard_phrase_has_no_grammatical_gender():
    """Отдельное требование заказчика: от рода в репликах уходим совсем.

    Голос выбирается в справочнике группы линий и может быть мужским
    (eugene, aidar) или женским (kseniya, baya, xenia) — одна и та же фраза
    звучит обоими, поэтому «не расслышала» и «не расслышал» одинаково не
    годятся.
    """
    from ai_assistant.service.dialog import DEFAULT_CONFIRM_NOT_HEARD

    gendered = (
        "расслышал", "расслышала", "поняла", "понял", "услышал", "услышала",
        "слышал", "слышала", "готова", "готов", "сказала", "сказал",
    )
    lowered = DEFAULT_CONFIRM_NOT_HEARD.lower()
    assert not [word for word in gendered if word in lowered]
    # Переспрос обязан назвать ожидаемый ответ, иначе он бесполезен.
    assert "да" in lowered and "нет" in lowered


# --- Обрывки не должны уходить в поиск по смыслу ---------------------------
#
# Живой звонок 18.08.2026: клиент сказал «не» (разговорное «нет», распознано
# точно), а поиск по смыслу выдал на него близость 0.6523 к теме «нужен ремонт
# мелкой бытовой техники» — выше порога 0.64. Бот принял междометие за
# название темы и повёл разговор не туда.
#
# Замер на боевой базе (32 темы, 508 формулировок, порог 0.64): выше порога
# оказались 12 обрывков из 76 — «алло» 0.7446, «хм» 0.6852, «угу» 0.6643,
# «ага» 0.6592, «алё» 0.6581, «а то» 0.6577, «не то» 0.6576, «не» 0.6523,
# «эээ» 0.6461, «да нет» 0.6447, «ну да» 0.6411, «ну вот» 0.6402. Липнут к
# произвольным темам: телевизор, холодильник, керхер, мелкая бытовая техника.


class RecordingKnowledge(FakeKnowledge):
    """Помнит, о чём её спрашивали: обрывок не должен доходить до поиска."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.queries = []

    def best_match(self, text):
        self.queries.append(text)
        return super().best_match(text)


def test_scrap_never_reaches_the_semantic_search():
    knowledge = RecordingKnowledge(RECORD)
    result = answer(engine(knowledge), conversationPoint=POINT_ASK_QUESTION, recognizedText="не")

    assert knowledge.queries == []
    assert result["TextToSpeak"] == ""
    assert result["Action"] == ACTION_RECOGNIZE
    assert result["ConversationPoint"] == POINT_ASK_QUESTION
    assert result["RedirectExten"] == ""


@pytest.mark.parametrize("scrap", ["не", "да", "ага", "угу", "хм", "не то", "ну да", "а то", "эээ", "алё"])
def test_measured_scraps_are_all_cut_off(scrap):
    knowledge = RecordingKnowledge(RECORD)
    answer(engine(knowledge), conversationPoint=POINT_ASK_QUESTION, recognizedText=scrap)
    assert knowledge.queries == []


@pytest.mark.parametrize("topic", ["утюг", "печь", "духовка", "стиралка", "холодильник",
                                   "не морозит", "не греет", "стиралка не крутит"])
def test_real_topics_still_reach_the_search(topic):
    """Правило режет обрывки, а не короткую речь.

    Замер: у всех этих реплик есть слово от четырёх букв, и все они
    попадали в свою тему выше порога.
    """
    knowledge = RecordingKnowledge(RECORD)
    answer(engine(knowledge), conversationPoint=POINT_ASK_QUESTION, recognizedText=topic)
    assert knowledge.queries == [topic]


def test_scrap_does_not_pollute_the_knowledge_base():
    """Обрывок не вопрос клиента — в справочник на разметку ему не место."""
    knowledge = RecordingKnowledge(None)
    answer(engine(knowledge), conversationPoint=POINT_ASK_QUESTION, recognizedText="не")
    assert knowledge.added == []


def test_short_negative_answer_still_works_at_confirmation():
    """Одно и то же «не» — в подтверждении отказ, в поиске мусор.

    Различаем по точке разговора, а не по самому слову: заказчик подтвердил,
    что «не» — законное разговорное «нет», и в список отрицательных ответов
    оно заводится отдельно.
    """
    record = KnowledgeRecord(
        id=1,
        question="стиральная машина не отжимает",
        clarifying_question="Правильно понимаю, что вас интересует ремонт стиральной машины?",
        positive_answers=["да"],
        negative_answers=["нет", "не"],
        positive_reply="Соединяю",
    )
    knowledge = RecordingKnowledge(record)
    engine_obj = engine(knowledge)
    answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, recognizedText="стиралка не крутит")
    result = answer(engine_obj, conversationPoint=POINT_CONFIRM, recognizedText="не")

    assert result["TextToSpeak"] == PHRASES.wrong_guess
    assert result["ConversationPoint"] == POINT_ASK_QUESTION


def test_short_positive_answer_still_works_at_confirmation():
    engine_obj = engine(FakeKnowledge(RECORD))
    answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, recognizedText="стиралка не крутит")
    result = answer(engine_obj, conversationPoint=POINT_CONFIRM, recognizedText="да")

    assert result["Action"] == ACTION_REDIRECT


def test_scrap_counts_as_an_unheard_attempt_like_an_empty_result():
    """Счётчик попыток общий: обрывок — тот же «бот не понял, что сказали».

    Наблюдать его снаружи негде — переспрос живёт только в точке
    подтверждения, куда обрывок не попадает по построению, — поэтому
    смотрим прямо в состояние сессии.
    """
    engine_obj = engine(FakeKnowledge(RECORD))
    answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, recognizedText="")
    answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, recognizedText="не")

    assert engine_obj._session("call-1").empty_count == 2


def test_recognized_topic_resets_the_counter_after_a_scrap():
    engine_obj = engine(FakeKnowledge(RECORD))
    answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, recognizedText="не")
    answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, recognizedText="стиралка не крутит")

    assert engine_obj._session("call-1").empty_count == 0


def test_scrap_rule_counts_letters_not_characters():
    """Правило считает буквы в слове, а не длину строки целиком.

    «не то» — две частицы по две буквы, строка из пяти знаков: считать длину
    строки значило бы пропустить её в поиск, где она даёт 0.6576 к теме
    «телевизор не включается».
    """
    from ai_assistant.service.dialog import MIN_SEARCHABLE_WORD_LETTERS

    assert MIN_SEARCHABLE_WORD_LETTERS == 4
    knowledge = RecordingKnowledge(RECORD)
    answer(engine(knowledge), conversationPoint=POINT_ASK_QUESTION, recognizedText="не то")
    assert knowledge.queries == []


# --- Наборы фраз по группам линий (UL-17568) ----------------------------------
#
# Галочка «Виртуальный AI помощник» стоит на номерах из разных групп линий, и у
# каждой группы свои фразы, свой голос и свои записанные аудио. База знаний,
# порог и логика разговора при этом общие — дробить их заказчик не просил.

MASTER_PHRASES = Phrases(
    greeting="Здравствуйте, это частный мастер",
    misrecognition="Повторите, пожалуйста",
    transfer="Соединяю с мастером",
    silence="Алло, вы здесь?",
    wrong_guess="А что тогда вас интересует?",
    confirm_not_heard="Скажите да или нет, пожалуйста",
)


def master_profile(**overrides):
    fields = dict(
        phrases=MASTER_PHRASES,
        voice="kseniya",
        audio_signature="v5_ru|kseniya",
        phones=["74951468847"],
        line_group_id=9060,
    )
    fields.update(overrides)
    return LineProfile(**fields)


def engine_with_groups(*profiles, **kwargs):
    knowledge = kwargs.pop("knowledge", None) or FakeKnowledge(RECORD)
    fields = dict(
        support_exten="489", sales_exten="500",
        audio_signature="v5_ru|eugene", voice="eugene",
        line_profiles=list(profiles),
    )
    fields.update(kwargs)
    return DialogEngine(knowledge, PHRASES, **fields)


@pytest.mark.parametrize(
    "dialed", ["74951468847", "84951468847", "4951468847", "+7 (495) 146-88-47"]
)
def test_dialed_number_picks_the_phrases_of_its_line_group(dialed):
    """Номер приезжает от Астериска то с восьмёркой, то с семёркой, то без кода
    страны — сравниваем по последним десяти цифрам, как и обработчик обращений."""
    result = answer(
        engine_with_groups(master_profile()),
        conversationPoint=POINT_START,
        dialedNumber=dialed,
    )

    assert result["TextToSpeak"] == MASTER_PHRASES.greeting


def test_unknown_dialed_number_gets_the_default_set():
    """Лучше поздороваться чужой фразой, чем молчать в трубку."""
    result = answer(
        engine_with_groups(master_profile()),
        conversationPoint=POINT_START,
        dialedNumber="74959999999",
    )

    assert result["TextToSpeak"] == PHRASES.greeting


def test_call_without_a_dialed_number_gets_the_default_set():
    """Скрипт прежней сборки набранный номер не присылает вовсе."""
    result = answer(engine_with_groups(master_profile()), conversationPoint=POINT_START)

    assert result["TextToSpeak"] == PHRASES.greeting


def test_engine_without_line_groups_answers_as_before():
    result = answer(
        engine(FakeKnowledge(RECORD)),
        conversationPoint=POINT_START,
        dialedNumber="74951468847",
    )

    assert result["TextToSpeak"] == PHRASES.greeting


def test_every_service_phrase_comes_from_the_group_of_the_dialed_number():
    """Не только приветствие: молчание, перевод и «не угадал тему» тоже свои."""
    dialed = {"dialedNumber": "74951468847"}
    engine_obj = engine_with_groups(master_profile())

    silence = answer(engine_obj, conversationPoint=POINT_ASK_QUESTION,
                     silenceDetected="True", **dialed)
    assert silence["TextToSpeak"] == MASTER_PHRASES.silence

    answer(engine_obj, conversationPoint=POINT_ASK_QUESTION,
           recognizedText="стиралка не крутит", **dialed)
    wrong = answer(engine_obj, conversationPoint=POINT_CONFIRM, recognizedText="нет", **dialed)
    assert wrong["TextToSpeak"] == MASTER_PHRASES.wrong_guess

    lost = engine_with_groups(master_profile(), knowledge=FakeKnowledge(None))
    transfer = answer(lost, conversationPoint=POINT_ASK_QUESTION,
                      recognizedText="во сколько вы открываетесь", **dialed)
    assert transfer["TextToSpeak"] == MASTER_PHRASES.transfer


def test_each_group_speaks_with_its_own_voice():
    """Голос уходит в ответ: скрипт передаёт его в /tts, иначе фразу второй
    группы синтезировали бы голосом первой и закэшировали на станции навсегда."""
    engine_obj = engine_with_groups(master_profile())

    theirs = answer(engine_obj, conversationPoint=POINT_START, dialedNumber="74951468847")
    default = answer(engine_obj, conversationPoint=POINT_START, dialedNumber="74959999999")

    assert theirs["Voice"] == "kseniya"
    assert default["Voice"] == "eugene"


def test_the_same_phrase_of_two_groups_gets_different_file_names():
    """Имя файла кэшируется на самой станции: без своей подписи звука вторая
    группа заиграла бы уже скачанным файлом первой, чужим голосом."""
    twin = master_profile(phrases=PHRASES)
    engine_obj = engine_with_groups(twin)

    theirs = answer(engine_obj, conversationPoint=POINT_START, dialedNumber="74951468847")
    default = answer(engine_obj, conversationPoint=POINT_START, dialedNumber="74959999999")

    assert theirs["TextToSpeak"] == default["TextToSpeak"]
    assert theirs["FileToPlayback"] != default["FileToPlayback"]


def test_group_answer_variants_win_over_the_ones_of_the_record():
    dialed = {"dialedNumber": "74951468847"}
    engine_obj = engine_with_groups(master_profile(positive_answers=["именно"]))

    answer(engine_obj, conversationPoint=POINT_ASK_QUESTION,
           recognizedText="стиралка не крутит", **dialed)
    result = answer(engine_obj, conversationPoint=POINT_CONFIRM, recognizedText="именно", **dialed)

    assert result["Action"] == ACTION_REDIRECT


def test_record_answer_variants_are_used_while_the_group_has_none():
    """Прежний движок на базе из файла: своих списков у него нет вовсе."""
    engine_obj = engine(FakeKnowledge(RECORD))
    answer(engine_obj, conversationPoint=POINT_ASK_QUESTION, recognizedText="стиралка не крутит")
    result = answer(engine_obj, conversationPoint=POINT_CONFIRM, recognizedText="верно")

    assert result["Action"] == ACTION_REDIRECT


# --- Заранее записанные аудио (UL-17568) --------------------------------------
#
# Записанный файл уже лежит на станции, скачивать его неоткуда: скрипт обязан
# отличить его от имени файла кэша, который он тянет из /tts.


def test_recorded_file_is_played_instead_of_synthesis():
    engine_obj = engine_with_groups(master_profile(
        audio_files={"greeting": "VoicesOKK\\voice-a\\2_spich.wav"}
    ))

    result = answer(engine_obj, conversationPoint=POINT_START, dialedNumber="74951468847")

    assert result["FileToPlayback"] == "VoicesOKK\\voice-a\\2_spich.wav"
    assert result["FileIsOnStation"] == "True"
    # Текст остаётся: он уходит в лог станции и подсказывает, что именно
    # прозвучало, даже когда синтеза не было.
    assert result["TextToSpeak"] == MASTER_PHRASES.greeting


def test_phrase_without_a_recorded_file_is_still_synthesized():
    """Галочка включена, а путь у фразы не заполнен — это не поломка."""
    engine_obj = engine_with_groups(master_profile(
        audio_files={"greeting": "VoicesOKK\\voice-a\\2_spich.wav"}
    ))

    result = answer(engine_obj, conversationPoint=POINT_ASK_QUESTION,
                    silenceDetected="True", dialedNumber="74951468847")

    assert result["TextToSpeak"] == MASTER_PHRASES.silence
    assert result["FileToPlayback"].startswith("aia_")
    assert result.get("FileIsOnStation", "") == ""


def test_recorded_files_of_one_group_do_not_leak_into_another():
    engine_obj = engine_with_groups(master_profile(
        audio_files={"greeting": "VoicesOKK\\voice-a\\2_spich.wav"}
    ))

    result = answer(engine_obj, conversationPoint=POINT_START, dialedNumber="74959999999")

    assert result["FileToPlayback"].startswith("aia_")
    assert result.get("FileIsOnStation", "") == ""


def test_knowledge_phrases_are_never_played_from_a_file():
    """Записанные аудио есть только у служебных фраз: уточняющих вопросов в
    справочнике группы линий нет вовсе."""
    from ai_assistant.service.dialog import PHRASE_SLOTS

    engine_obj = engine_with_groups(master_profile(
        audio_files={slot: "AsterBotGL\\Actual.wav" for slot in PHRASE_SLOTS}
    ))

    result = answer(engine_obj, conversationPoint=POINT_ASK_QUESTION,
                    recognizedText="стиралка не крутит", dialedNumber="74951468847")

    assert result["TextToSpeak"] == RECORD.clarifying_question
    assert result["FileToPlayback"].startswith("aia_")
    assert result.get("FileIsOnStation", "") == ""


def test_answer_of_a_service_without_recorded_audio_has_no_such_key():
    """Признак появляется только там, где он что-то значит: ответ без него
    старый скрипт читает ровно как раньше."""
    result = answer(engine(FakeKnowledge(RECORD)), conversationPoint=POINT_START)

    assert "FileIsOnStation" not in result
