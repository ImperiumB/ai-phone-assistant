"""Тесты второй метрики линейки: сменилось ли то, что бот произносит (С1).

Главный вердикт линейки сравнивает направление звонка, поэтому правку данных
внутри одного отдела он не видит вовсе. Трижды за два дня мы говорили
«регресса нет», опираясь на цифру, которая этот класс правок не замечает.
Метрика закрывает именно эту дыру.

Полный прогон линейки тут не запускается: он требует кэша эмбеддингов, корпуса
из 56 тысяч реплик и пяти минут. Проверяются чистые функции сводки плюс одна
связка с НАСТОЯЩИМ движком диалога: именно на ней метрика и может разойтись с
ботом, а разойдясь, замолчать.
"""

import io

from tools.measure_live import (
    CHANGE_OTHER_DESK,
    CHANGE_POSITIVE,
    CHANGE_RECORD,
    CHANGE_SAME_DESK,
    compare_runs,
    dialog_action,
    spoken_changes,
    spoken_positive,
    spoken_question,
)


class _Record:
    def __init__(self, clarifying_question, positive_reply=""):
        self.clarifying_question = clarifying_question
        self.positive_reply = positive_reply


class _Resolution:
    def __init__(self, clarifying_question, positive_reply=""):
        self.record = _Record(clarifying_question, positive_reply)


def test_spoken_question_only_on_a_question_action():
    """На переводе и на сдаче бот говорит служебную фразу, не текст записи."""
    res = _Resolution("Правильно понимаю, ремонт газового котла?")
    assert spoken_question(res, "вопрос: Сантехника") == "Правильно понимаю, ремонт газового котла?"
    assert spoken_question(res, "перевод: Сантехника") == ""
    assert spoken_question(res, "Борец: не нашёл") == ""
    assert spoken_question(res, "развилка") == ""
    assert spoken_question(res, "переспрос: не понял") == ""


def test_spoken_question_collapses_whitespace():
    """Перевод строки внутри ячейки ломает TSV, а на слух он равен пробелу."""
    res = _Resolution("Правильно понимаю,\n  установка\tкарниза?")
    assert spoken_question(res, "вопрос: Карнизы") == "Правильно понимаю, установка карниза?"


def test_spoken_question_without_a_record():
    assert spoken_question(None, "вопрос: Сантехника") == ""


def test_spoken_positive_is_read_from_the_record_too():
    """Ответ на согласие это второе произносимое поле записи, и самое весомое.

    В посылке на 64 записи всего два разных текста, один стоит у 49 записей.
    Правку такого текста слышит каждый, кто дошёл до согласия.
    """
    res = _Resolution("Правильно понимаю, ремонт плиты?", "Соединяю вас со специалистом")
    assert spoken_positive(res, "вопрос: Плиты") == "Соединяю вас со специалистом"
    # Без заданного вопроса согласия не бывает, значит и текст не звучит.
    assert spoken_positive(res, "перевод: Плиты") == ""
    assert spoken_positive(None, "вопрос: Плиты") == ""
    # Пустое поле не должно превращаться в None и ломать сравнение.
    assert spoken_positive(_Resolution("вопрос?"), "вопрос: Плиты") == ""


def test_spoken_texts_survive_a_record_without_the_fields():
    """Поля может не оказаться вовсе: разборщик посылки менялся не раз."""

    class _Bare:
        pass

    class _Res:
        record = _Bare()

    assert spoken_positive(_Res(), "вопрос: Плиты") == ""


def _row(n, phrase, spoken, desk, record, spoken_yes=""):
    return {"n": n, "phrase": phrase, "D_full_spoken": spoken,
            "D_full_spoken_yes": spoken_yes,
            "D_full_answer": desk, "D_full_record": record}


def _prev(rows):
    return {str(r["n"]): r for r in rows}


def test_spoken_changes_catches_a_new_question_inside_the_same_desk(tmp_path):
    """Слепая зона вердикта: текст сменился, отдел тот же.

    Ровно этот случай вердикт не видит: он сравнивает ярлык отдела, а он не
    менялся. Клиент спрашивает про смеситель, бот прежде отвечал про
    смеситель, а после правки данных отвечает про карниз, и оба раза это
    сантехника.
    """
    out = tmp_path / "exp_spoken_changes.tsv"
    prev = _prev([_row(1, "смеситель течёт", "Правильно понимаю, ремонт смесителя?", "Сантехника", "7")])
    rows = [_row(1, "смеситель течёт", "Правильно понимаю, установка карниза?", "Сантехника", "132")]
    lines = spoken_changes(rows, prev, "D_full_", "D", str(out))
    text = "\n".join(lines)
    assert "решений, где бот говорит текст записи: 1" in text
    assert "сменилось хоть что-то: 1" in text
    assert CHANGE_SAME_DESK in text
    # Порепличный список: обе формулировки и обе записи видны целиком.
    saved = io.open(str(out), encoding="utf-8").read()
    assert "ремонт смесителя" in saved and "установка карниза" in saved
    assert "\t7\t132\t" in saved


def test_spoken_changes_splits_the_desk_and_counts_the_unchanged(tmp_path):
    """Разбивка по отделу и знаменатель: строки без текста записи не считаются."""
    out = tmp_path / "changes.tsv"
    prev = _prev([
        _row(1, "котёл не греет", "Правильно понимаю, ремонт котла?", "Сантехника", "101"),
        _row(2, "стиралка не сливает", "Правильно понимаю, ремонт стиральной машины?", "Бытовая техника", "12"),
        _row(3, "мастер не приехал", "", "", ""),
    ])
    rows = [
        # тот же вопрос
        _row(1, "котёл не греет", "Правильно понимаю, ремонт котла?", "Сантехника", "101"),
        # вопрос и отдел сменились вместе
        _row(2, "стиралка не сливает", "Правильно понимаю, ремонт карниза?", "Карнизы", "132"),
        # оба раза бот только переводил: в знаменатель не идёт
        _row(3, "мастер не приехал", "", "", ""),
    ]
    text = "\n".join(spoken_changes(rows, prev, "D_full_", "D", str(out)))
    assert "решений, где бот говорит текст записи: 2" in text
    assert "сменилось хоть что-то: 1" in text
    assert CHANGE_OTHER_DESK in text
    assert CHANGE_SAME_DESK not in text


def test_the_other_desk_bucket_does_not_promise_the_verdict_sees_it():
    """Вердикт сравнивает ярлык с ОЖИДАЕМЫМ, а не «сменился ли отдел».

    Переезд записи между двумя неверными отделами, как и любая смена на
    реплике «не клиент», вердикт показывает как «совпал». В прогоне 09.11
    таких строк 308 из 850, больше трети знаменателя. Поэтому название второй
    корзины не имеет права утверждать, что вердикт смену видит: прочитавший
    сводку решит, что эти строки под контролем.
    """
    assert "вердикт не шевельнётся" in CHANGE_SAME_DESK
    assert "может и не увидеть" in CHANGE_OTHER_DESK


def test_spoken_changes_sees_a_changed_answer_to_yes(tmp_path):
    """Правка ответа на согласие: вопрос тот же, отдел тот же, текст другой."""
    out = tmp_path / "changes.tsv"
    prev = _prev([_row(1, "плита не греет", "Правильно понимаю, ремонт плиты?", "Плиты", "82",
                       spoken_yes="Соединяю вас со специалистом по приему заказов")])
    rows = [_row(1, "плита не греет", "Правильно понимаю, ремонт плиты?", "Плиты", "82",
                 spoken_yes="Перевожу на мастера, не кладите трубку")]
    text = "\n".join(spoken_changes(rows, prev, "D_full_", "D", str(out)))
    assert "сменилось хоть что-то: 1" in text
    assert CHANGE_POSITIVE in text
    assert CHANGE_SAME_DESK not in text
    saved = io.open(str(out), encoding="utf-8").read()
    assert "не кладите трубку" in saved


def test_spoken_changes_sees_a_different_record_behind_the_same_text(tmp_path):
    """Текст тот же, запись другая: в ERP уедет другой тип оборудования.

    В посылке пять записей делят текст вопроса с соседкой при разных типах
    оборудования (7 и 131, 26 и 177 и 178). Передвинули формулировку с одной на
    другую: клиент слышит то же самое, вердикт тот же, а мастера подберут по
    другому справочнику.
    """
    out = tmp_path / "changes.tsv"
    same_text = "Правильно понимаю, ремонт водонагревателя?"
    prev = _prev([_row(1, "бойлер не греет", same_text, "Сантехника", "7", spoken_yes="Соединяю")])
    rows = [_row(1, "бойлер не греет", same_text, "Сантехника", "131", spoken_yes="Соединяю")]
    text = "\n".join(spoken_changes(rows, prev, "D_full_", "D", str(out)))
    assert CHANGE_RECORD in text
    assert "сменилось хоть что-то: 1" in text


def test_spoken_changes_marks_a_question_that_appeared_or_vanished(tmp_path):
    out = tmp_path / "changes.tsv"
    prev = _prev([
        _row(1, "течёт труба", "", "Сантехника", "7"),
        _row(2, "не работает плита", "Правильно понимаю, ремонт плиты?", "Бытовая техника", "82"),
    ])
    rows = [
        _row(1, "течёт труба", "Правильно понимаю, ремонт трубы?", "Сантехника", "7"),
        _row(2, "не работает плита", "", "Бытовая техника", "82"),
    ]
    text = "\n".join(spoken_changes(rows, prev, "D_full_", "D", str(out)))
    assert "вопрос появился" in text
    assert "вопрос пропал" in text


def test_spoken_changes_says_it_cannot_compare_with_an_old_table(tmp_path):
    """Прежняя таблица снята до появления столбцов: молчать об этом нельзя."""
    out = tmp_path / "changes.tsv"
    prev = {"1": {"n": "1", "D_full_answer": "Сантехника"}}
    rows = [_row(1, "течёт труба", "Правильно понимаю, ремонт трубы?", "Сантехника", "7")]
    text = "\n".join(spoken_changes(rows, prev, "D_full_", "D", str(out)))
    assert "нет столбцов D_full_spoken, D_full_spoken_yes" in text
    assert not out.exists()


def test_spoken_changes_without_a_previous_run(tmp_path):
    out = tmp_path / "changes.tsv"
    text = "\n".join(spoken_changes([], {}, "D_full_", "D", str(out)))
    assert "сравнивать не с чем" in text
    assert not out.exists()


def test_spoken_changes_counts_replies_missing_from_the_previous_run(tmp_path):
    """Реплики, которой в прежнем прогоне нет, в знаменатель не попадают."""
    out = tmp_path / "changes.tsv"
    prev = _prev([_row(1, "котёл не греет", "Правильно понимаю, ремонт котла?", "Сантехника", "101")])
    rows = [
        _row(1, "котёл не греет", "Правильно понимаю, ремонт котла?", "Сантехника", "101"),
        _row(2, "новая реплика", "Правильно понимаю, ремонт плиты?", "Бытовая техника", "82"),
    ]
    text = "\n".join(spoken_changes(rows, prev, "D_full_", "D", str(out)))
    assert "решений, где бот говорит текст записи: 1" in text
    assert "реплики нет в прежнем прогоне" in text


def test_compare_runs_survives_a_variant_that_was_not_counted():
    """С --only-live столбцов варианта A в строке нет, и это не повод падать.

    Прежде сверка валилась здесь с KeyError, а общий try уносил вместе с ней и
    метрику С1: в сводке не оставалось ни секции С1, ни страховочного «НЕ
    СЧИТАНО». Документированный способ запуска попадал в эту ветку ВСЕГДА, то
    есть у метрики не было ни одного живого прогона, и узналось это случайно.
    """
    rows = [{"n": 1, "D_full_verdict": "верно", "D_full_stage": "corpus",
             "D_full_dialog_verdict": "верно (вопрос)"}]
    prev = {"1": {"n": "1", "A_full_verdict": "верно", "D_full_verdict": "верно",
                  "D_full_stage": "corpus", "D_full_dialog_verdict": "верно (вопрос)"}}
    text = "\n".join(compare_runs(rows, prev, "прежняя.tsv"))
    assert "A_full_verdict не считан в этом прогоне 1" in text
    assert "D_full_verdict совпал" in text
    assert "РАЗОШЁЛСЯ" not in text


def test_compare_runs_reports_a_divergence_and_a_missing_reply():
    rows = [{"n": 1, "D_full_verdict": "не туда", "D_full_stage": "phrases",
             "D_full_dialog_verdict": "не туда (вопрос)"},
            {"n": 2, "D_full_verdict": "верно", "D_full_stage": "corpus",
             "D_full_dialog_verdict": "верно (вопрос)"}]
    prev = {"1": {"n": "1", "D_full_verdict": "верно", "D_full_stage": "phrases",
                  "D_full_dialog_verdict": "верно (вопрос)"}}
    lines = [" ".join(line.split()) for line in compare_runs(rows, prev, "прежняя.tsv")]
    assert "D_full_verdict РАЗОШЁЛСЯ 1" in lines
    assert "нет в прежней 1" in lines


# --------------------------------------------------- связка с живым диалогом


class _OneRecordKnowledge:
    """База из одной записи: ровно столько, сколько нужно и движку, и линейке."""

    threshold = 0.74

    def __init__(self, record, score=0.9):
        self._record = record
        self._score = score
        self.added = []

    def best_match(self, text):
        return (self._record, self._score)

    def search(self, text):
        return (self._record, self._score) if self._score >= self.threshold else None

    def resolve(self, text, query=None):
        from ai_assistant.service.knowledge import Resolution

        return Resolution(self._record, self._score, self._score >= self.threshold, "phrases")

    def resolve_phrases(self, text):
        return self.resolve(text)

    def exact(self, text):
        return None

    def add(self, question):
        self.added.append(question)
        return self._record

    def save(self, path):
        pass


def test_the_ruler_speaks_exactly_what_the_real_dialog_speaks():
    """Главное допущение метрики, проверенное НАСТОЯЩИМ движком диалога.

    Метрика верит, что бот произносит текст записи ровно там, где действие
    начинается с «вопрос: », и что произносит он именно эти два поля. Проверять
    это заглушкой бессмысленно: так тестируется `startswith`, а не бот. Если
    движок когда-нибудь начнёт озвучивать третье поле записи или скажет вопрос
    в другой ветке, метрика смолчит, а молчание здесь читается как «правка
    ничего не изменила». Ровно этим способом нас уже трижды обмануло, поэтому
    связка прибита тестом.
    """
    from ai_assistant.service.dialog import (
        ACTION_RECOGNIZE, ACTION_REDIRECT, POINT_ASK_QUESTION, POINT_CONFIRM,
        DialogEngine, Phrases, prms_to_dict,
    )
    from ai_assistant.service.knowledge import KnowledgeRecord

    record = KnowledgeRecord(
        id=1,
        question="стиральная машина не отжимает",
        clarifying_question="Правильно понимаю, что вас интересует ремонт стиральной машины?",
        positive_answers=["да", "верно"],
        negative_answers=["нет"],
        positive_reply="Соединяю вас со специалистом по приему заказов, оставайтесь на линии",
        scenario="Стиральные машины",
        equipment_type="Стиральные машины",
    )
    phrases = Phrases(
        greeting="Здравствуйте, чем могу помочь?",
        misrecognition="Попробуйте переформулировать свой вопрос, пожалуйста",
        transfer="Минуту, перевожу ваш звонок на специалиста",
        silence="Вы меня слышите?",
    )
    kb = _OneRecordKnowledge(record)
    engine_obj = DialogEngine(kb, phrases, support_exten="489", sales_exten="500")
    text = "стиралка не крутит бельё"

    # То же решение, что получает линейка, и то же действие.
    res = kb.resolve(text)
    action, _name = dialog_action(kb, text, res, lambda r: r.scenario if r is not None else None)
    assert action.startswith("вопрос: ")

    asked = prms_to_dict(engine_obj.handle(
        {"linkedId": "call-1", "conversationPoint": POINT_ASK_QUESTION,
         "recognizedText": text, "silenceDetected": "False"}))
    assert asked["Action"] == ACTION_RECOGNIZE
    assert asked["ConversationPoint"] == POINT_CONFIRM
    # Вот она, связка: что произнёс движок, то и записала линейка.
    assert asked["TextToSpeak"] == spoken_question(res, action)

    agreed = prms_to_dict(engine_obj.handle(
        {"linkedId": "call-1", "conversationPoint": POINT_CONFIRM,
         "recognizedText": "да", "silenceDetected": "False"}))
    assert agreed["Action"] == ACTION_REDIRECT
    assert agreed["TextToSpeak"] == spoken_positive(res, action)


def test_the_ruler_marks_the_grey_zone_as_a_reask_not_as_giving_up():
    """В серой зоне корпуса бот переспрашивает, а не сдаётся на сопровождение.

    Прежде линейка метила эти строки как «Борец: не нашёл», и 106 строк из 4000
    попадали в сводку как «сдался», хотя разговор продолжался. Это была ложь
    разметки, а линейка существует ровно для того, чтобы не лгать.
    """
    from ai_assistant.service.knowledge import Resolution

    grey = Resolution(None, 0.55, False, "corpus-grey")
    action, name = dialog_action(_OneRecordKnowledge(None), "что-то непонятное", grey, lambda r: None)
    assert action == "переспрос: не понял"
    assert name is None
    # И в вердикте это не «сдался»: разговор не закончен.
    from tools.measure_live import dialog_verdict

    assert dialog_verdict("N", "Сантехника", action, None) == "переспрос (разговор продолжается)"


def test_the_ruler_marks_a_phrase_near_miss_as_giving_up():
    """Промах формулировки это сдача на сопровождение, а не переспрос.

    09.11.2026 я расширил переспрос с серой зоны корпуса на любой провал поиска
    темы, и линейку поправил вслед. заказчик правку отменил: «07.11 аналитик КЦ решил,
    что переспросов больше не будет». Тест сторожит, чтобы линейка не осталась
    со старой разметкой и не показывала продолжение разговора там, где бот
    уходит к человеку.
    """
    from ai_assistant.service.knowledge import Resolution
    from tools.measure_live import DIRECT_TRANSFER, dialog_verdict

    kb = _OneRecordKnowledge(None)
    near = Resolution(_Record("Правильно понимаю, ремонт микроволновки?"), 0.72, True, "phrases")
    action, name = dialog_action(kb, "в микроволновке", near, lambda r: "Бытовая техника")
    assert action == "Борец: фраза<%.2f" % DIRECT_TRANSFER
    assert name is None
    assert dialog_verdict("N", "Бытовая техника", action, None) == "сдался: сопровождение"

    nothing = Resolution(None, 0.0, False, "phrases")
    action, _ = dialog_action(kb, "ремонт мотоцикла", nothing, lambda r: None)
    assert action == "Борец: не нашёл"


def test_a_numeric_cell_from_the_tsv_is_not_a_change(tmp_path):
    """Код записи в прежней таблице строка, в свежей строке число.

    Прямое сравнение «83» и 83 всегда даёт «разные», и на контрольном прогоне
    09.11 это дало 738 ложных «запись другая» из 850 при нулевой реальной
    смене. Поймал контрольный прогон, а не тест, поэтому тест появился.
    """
    out = tmp_path / "changes.tsv"
    same_text = "Правильно понимаю, ремонт сантехники?"
    # Прежний прогон: как его читает csv.DictReader, то есть строками.
    prev = {"1": {"n": "1", "phrase": "течёт труба", "D_full_spoken": same_text,
                  "D_full_spoken_yes": "Соединяю", "D_full_answer": "Сантехника",
                  "D_full_record": "83"}}
    # Свежая строка: как её кладёт прогон, то есть числом.
    rows = [{"n": 1, "phrase": "течёт труба", "D_full_spoken": same_text,
             "D_full_spoken_yes": "Соединяю", "D_full_answer": "Сантехника",
             "D_full_record": 83}]
    text = "\n".join(spoken_changes(rows, prev, "D_full_", "D", str(out)))
    assert "сменилось хоть что-то: 0" in text
    assert CHANGE_RECORD not in text
    assert not out.exists()


def test_a_really_different_record_is_still_caught(tmp_path):
    """Защита от перегиба: настоящую смену записи глушить нельзя."""
    out = tmp_path / "changes.tsv"
    same_text = "Правильно понимаю, ремонт водонагревателя?"
    prev = {"1": {"n": "1", "phrase": "бойлер не греет", "D_full_spoken": same_text,
                  "D_full_spoken_yes": "Соединяю", "D_full_answer": "Водонагреватели",
                  "D_full_record": "7"}}
    rows = [{"n": 1, "phrase": "бойлер не греет", "D_full_spoken": same_text,
             "D_full_spoken_yes": "Соединяю", "D_full_answer": "Водонагреватели",
             "D_full_record": 131}]
    text = "\n".join(spoken_changes(rows, prev, "D_full_", "D", str(out)))
    assert CHANGE_RECORD in text
    assert "сменилось хоть что-то: 1" in text
