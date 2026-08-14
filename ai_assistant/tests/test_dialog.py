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
