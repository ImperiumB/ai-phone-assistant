"""Тесты генератора досылки в базу знаний (sql/08).

Проверяется то, что ломает досылку молча: экранирование, идемпотентность,
дубли внутри самой посылки и длины текстов. Отдельно — правило отбора
направлений: годится только направление с непустым номером приёма.
"""

import json

import pytest

from tools.expand_knowledge_base import (
    Existing,
    Plan,
    build_plan,
    eligible_direction,
    fold_yo,
    main,
    normalize_phrase,
    normalized_literal,
    render_sql,
    report_lines,
    wrap_comment,
)
from tools.export_knowledge_base import MAX_TEXT_LENGTH


# Слепок боевых справочников в миниатюре.
REFERENCE = {
    "equipment_types": [
        {"id": 119, "name": "Стиральные машины"},
        {"id": 962, "name": "Ремонт форсунок"},
        {"id": 961, "name": "Авто"},
        {"id": 963, "name": "Ремонт фар"},
    ],
    "telephone_directions": [
        {"id": 53, "name": "Стиральные машины", "phone_for_web_req": "7021"},
        # годное направление: номер уникален
        {"id": 92, "name": "Ремонт Форсунок", "phone_for_web_req": "7068"},
        # негодное: номера приёма нет
        {"id": 114, "name": "Видеодомофоны", "phone_for_web_req": None},
        # номер делят два направления
        {"id": 47, "name": "Жалобы СЦ", "phone_for_web_req": "6021"},
        {"id": 49, "name": "НЬЮ. СЦ", "phone_for_web_req": "6021"},
    ],
    "direction_equipment_links": [
        {"telephone_direction_id": 92, "equipment_type_id": 961},
        {"telephone_direction_id": 92, "equipment_type_id": 962},
        {"telephone_direction_id": 92, "equipment_type_id": 963},
        {"telephone_direction_id": 53, "equipment_type_id": 119},
    ],
}

SNAPSHOT = {
    "scenarios": [{"id": 1, "telephone_direction_id": 53, "action_type": 1,
                   "name": "Стиральные машины"}],
    "records": [
        {"id": 1, "scenario_id": 1, "equipment_type_id": 119, "is_from_bot": 0,
         "question": "стиральная машина не отжимает"},
        {"id": 2, "scenario_id": None, "equipment_type_id": None, "is_from_bot": 1,
         "question": "здравствуйте а можно заказать пиццу"},
    ],
    "phrases": [
        {"id": 1, "knowledge_base_id": 1, "is_from_bot": 0, "phrase": "стиралка сломалась"},
        {"id": 2, "knowledge_base_id": 1, "is_from_bot": 0, "phrase": "машинка не сливает воду"},
    ],
}


def make_expansion(**overrides):
    data = {
        "new_topics": [
            {
                "telephone_direction_id": 92,
                "scenario_name": "Ремонт Форсунок",
                "equipment_type": "Ремонт форсунок",
                "question": "нужен ремонт форсунок",
                "clarifying_question": "Правильно я понял? Ответьте да или нет",
                "positive_reply": "Соединяю вас со специалистом",
                "why": "номер приёма уникален",
                "question_variants": ["нужна промывка форсунок"],
            }
        ],
        "extra_phrases": [
            {"question": "стиральная машина не отжимает",
             "phrases": ["стиральная машина не набирает воду"]}
        ],
        "deferred_directions": [],
    }
    data.update(overrides)
    return data


def plan_of(**overrides):
    return build_plan(make_expansion(**overrides), SNAPSHOT, REFERENCE)


# --------------------------------------------------------------------------
# Нормализация: Python и SQL обязаны считать одинаково
# --------------------------------------------------------------------------

def test_normalize_ignores_case_and_spaces():
    assert normalize_phrase("  Стиралка   Сломалась ") == "стиралка сломалась"


def test_normalize_keeps_yo_but_fold_removes_it():
    """SQL «ё» и «е» не путает, поэтому и normalize_phrase не путает."""
    assert normalize_phrase("потёк") != normalize_phrase("потек")
    assert fold_yo(normalize_phrase("потёк")) == normalize_phrase("потек")


def test_normalized_literal_is_lowercase_and_quoted():
    assert normalized_literal("  Форсунки   ЛЬЮТ ") == "'форсунки льют'"


# --------------------------------------------------------------------------
# Отбор направлений: только непустой номер приёма
# --------------------------------------------------------------------------

def test_direction_with_number_is_eligible():
    ok, reason = eligible_direction({"phone_for_web_req": "7068"})
    assert ok and reason is None


def test_direction_without_number_is_rejected():
    ok, reason = eligible_direction({"phone_for_web_req": None})
    assert not ok
    assert "PHONE_FOR_WEB_REQ" in reason


def test_blank_number_is_rejected():
    ok, _ = eligible_direction({"phone_for_web_req": "   "})
    assert not ok


def test_avail_for_redirect_is_ignored():
    """Галка «Доступен для перевода» в переводе не участвует."""
    ok, _ = eligible_direction({"phone_for_web_req": "6021", "avail_for_redirect": 0})
    assert ok


def test_topic_on_direction_without_number_is_skipped():
    topic = dict(make_expansion()["new_topics"][0], telephone_direction_id=114)
    plan = plan_of(new_topics=[topic])
    assert plan.records == []
    assert plan.scenarios == []
    assert any("PHONE_FOR_WEB_REQ" in text for text in plan.issues)


def test_topic_on_unknown_direction_is_skipped():
    topic = dict(make_expansion()["new_topics"][0], telephone_direction_id=777)
    plan = plan_of(new_topics=[topic])
    assert plan.records == []
    assert any("777" in text for text in plan.issues)


def test_shared_number_lands_in_issues_but_topic_is_kept():
    """Номер, поделённый с другим направлением, — повод предупредить, не отказать."""
    topic = dict(
        make_expansion()["new_topics"][0],
        telephone_direction_id=47,
        equipment_type="",
        question="хочу пожаловаться на сервисный центр",
    )
    plan = plan_of(new_topics=[topic])
    assert len(plan.records) == 1
    assert any("6021" in text and "49" in text for text in plan.issues)


# --------------------------------------------------------------------------
# Тип оборудования
# --------------------------------------------------------------------------

def test_equipment_type_taken_by_name_from_direction_tab():
    plan = plan_of()
    assert plan.records[0].equipment_type_id == 962
    assert plan.records[0].equipment_type_name == "Ремонт форсунок"


def test_equipment_type_stays_empty_when_not_given():
    topic = dict(make_expansion()["new_topics"][0], equipment_type="")
    plan = plan_of(new_topics=[topic])
    assert plan.records[0].equipment_type_id is None
    assert plan.records[0].equipment_reason


# --------------------------------------------------------------------------
# Сценарии
# --------------------------------------------------------------------------

def test_scenario_is_created_for_new_direction():
    plan = plan_of()
    assert [(s.name, s.telephone_direction_id) for s in plan.scenarios] == [
        ("Ремонт Форсунок", 92)
    ]


def test_scenario_is_not_created_when_direction_already_has_one():
    """По направлению 53 сценарий уже есть в снимке — второй не заводим."""
    topic = dict(
        make_expansion()["new_topics"][0],
        telephone_direction_id=53,
        equipment_type="Стиральные машины",
        question="стиралка не крутит барабан",
    )
    plan = plan_of(new_topics=[topic])
    assert plan.scenarios == []
    assert len(plan.records) == 1


def test_two_topics_on_one_direction_give_one_scenario():
    base = make_expansion()["new_topics"][0]
    plan = plan_of(
        new_topics=[
            base,
            dict(base, question="почистить форсунки на дизеле", question_variants=[]),
        ]
    )
    assert len(plan.scenarios) == 1
    assert len(plan.records) == 2


# --------------------------------------------------------------------------
# Дубли: внутри посылки и против справочника
# --------------------------------------------------------------------------

def test_phrase_repeated_inside_submission_breaks():
    with pytest.raises(ValueError, match="уже занято"):
        plan_of(
            extra_phrases=[
                {"question": "стиральная машина не отжимает",
                 "phrases": ["стиралка не крутит белье", "стиралка не крутит белье"]}
            ]
        )


def test_phrase_repeated_across_themes_breaks():
    """Одна формулировка не может принадлежать двум темам сразу."""
    topic = dict(make_expansion()["new_topics"][0],
                 question_variants=["стиральная машина не набирает воду"])
    with pytest.raises(ValueError, match="уже занято"):
        plan_of(new_topics=[topic])


def test_phrase_equal_to_existing_phrase_of_another_theme_breaks():
    with pytest.raises(ValueError, match="уже занято"):
        plan_of(
            new_topics=[
                dict(make_expansion()["new_topics"][0],
                     question_variants=["машинка не сливает воду"])
            ]
        )


def test_phrase_equal_to_existing_question_breaks():
    topic = dict(make_expansion()["new_topics"][0],
                 question_variants=["стиральная машина не отжимает"])
    with pytest.raises(ValueError, match="уже занято"):
        plan_of(new_topics=[topic])


def test_new_question_duplicating_existing_question_breaks():
    topic = dict(make_expansion()["new_topics"][0],
                 question="Стиральная  Машина  Не  Отжимает")
    with pytest.raises(ValueError, match="уже занято"):
        plan_of(new_topics=[topic])


def test_yo_only_difference_breaks():
    """«потёк» и «потек» для базы разные, для человека — одно и то же."""
    topic = dict(make_expansion()["new_topics"][0],
                 question_variants=["форсунка потёкла", "форсунка потекла"])
    with pytest.raises(ValueError, match="«ё»"):
        plan_of(new_topics=[topic])


def test_phrase_already_present_at_its_theme_is_not_resent():
    plan = plan_of(
        new_topics=[],
        extra_phrases=[
            {"question": "стиральная машина не отжимает",
             "phrases": ["Стиралка   Сломалась", "стиральная машина не набирает воду"]}
        ],
    )
    assert [p.phrase for p in plan.phrases] == ["стиральная машина не набирает воду"]
    assert plan.already_present == ["запись 1: «Стиралка   Сломалась»"]


def test_phrases_for_unknown_theme_land_in_issues():
    plan = plan_of(
        new_topics=[],
        extra_phrases=[{"question": "такой темы нет", "phrases": ["что-то"]}],
    )
    assert plan.phrases == []
    assert any("такой темы нет" in text for text in plan.issues)


def test_empty_phrase_is_rejected():
    with pytest.raises(ValueError, match="пустая формулировка"):
        plan_of(
            extra_phrases=[
                {"question": "стиральная машина не отжимает", "phrases": ["   "]}
            ]
        )


def test_snapshot_with_duplicate_questions_is_rejected():
    snapshot = {
        "scenarios": [],
        "records": [
            {"id": 1, "question": "одно и то же"},
            {"id": 2, "question": "Одно  И  То  Же"},
        ],
        "phrases": [],
    }
    with pytest.raises(ValueError, match="два вопроса"):
        Existing.from_snapshot(snapshot)


# --------------------------------------------------------------------------
# Экранирование и длины
# --------------------------------------------------------------------------

def test_quote_in_phrase_is_doubled():
    topic = dict(make_expansion()["new_topics"][0],
                 question_variants=["форсунки на 'Бош' льют"])
    sql = render_sql(plan_of(new_topics=[topic]))
    assert "'форсунки на ''Бош'' льют'" in sql


def test_quote_in_question_is_doubled_in_both_value_and_guard():
    """Вопрос едет в INSERT как есть, а в NOT EXISTS — нормализованным.
    Кавычка обязана быть удвоена в обоих."""
    topic = dict(make_expansion()["new_topics"][0],
                 question="ремонт форсунок 'Бош'", question_variants=[])
    sql = render_sql(plan_of(new_topics=[topic], extra_phrases=[]))
    assert "'ремонт форсунок ''Бош'''" in sql       # значение
    assert "'ремонт форсунок ''бош'''" in sql       # сравнение


def test_ampersand_is_rejected():
    """SQL*Plus принял бы & за подстановочную переменную."""
    topic = dict(make_expansion()["new_topics"][0],
                 question_variants=["ремонт & чистка форсунок"])
    with pytest.raises(ValueError, match="&"):
        plan_of(new_topics=[topic])


def test_newline_is_rejected():
    topic = dict(make_expansion()["new_topics"][0],
                 question_variants=["форсунки\nльют"])
    with pytest.raises(ValueError):
        plan_of(new_topics=[topic])


def test_too_long_phrase_is_rejected():
    topic = dict(make_expansion()["new_topics"][0],
                 question_variants=["я" * (MAX_TEXT_LENGTH + 1)])
    with pytest.raises(ValueError, match="длиннее"):
        plan_of(new_topics=[topic])


def test_phrase_of_exactly_max_length_passes():
    topic = dict(make_expansion()["new_topics"][0],
                 question_variants=["я" * MAX_TEXT_LENGTH])
    plan = plan_of(new_topics=[topic], extra_phrases=[])
    assert [len(p.phrase) for p in plan.phrases] == [MAX_TEXT_LENGTH]


# --------------------------------------------------------------------------
# Идемпотентность SQL
# --------------------------------------------------------------------------

def test_every_insert_is_guarded_by_not_exists():
    """Ровно один NOT EXISTS на каждый INSERT. Комментарии не считаем."""
    body = [
        line
        for line in render_sql(plan_of()).splitlines()
        if not line.lstrip().startswith("--")
    ]
    inserts = sum(line.count("INSERT INTO ULTIMA.") for line in body)
    guards = sum(line.count("NOT EXISTS") for line in body)
    assert inserts == 4
    assert guards == inserts


def test_no_insert_values_form_anywhere():
    """VALUES без NOT EXISTS вставил бы дубль при повторном запуске."""
    sql = render_sql(plan_of())
    assert " VALUES (" not in sql


def test_ids_are_taken_as_max_plus_one():
    sql = render_sql(plan_of())
    for table in ("AI_SCENARIOS", "AI_KNOWLEDGE_BASE", "AI_KB_PHRASES"):
        assert f"SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.{table}" in sql


def test_scenario_guard_is_by_direction():
    sql = render_sql(plan_of())
    assert (
        "NOT EXISTS (SELECT 1 FROM ULTIMA.AI_SCENARIOS"
        " WHERE TELEPHONE_DIRECTION_ID = 92)" in sql
    )


def test_record_guard_is_by_normalized_question():
    sql = render_sql(plan_of())
    assert (
        "LOWER(TRIM(REGEXP_REPLACE(QUESTION, '[[:space:]]+', ' ')))"
        " = 'нужен ремонт форсунок'" in sql
    )


def test_phrase_guard_is_scoped_to_its_own_theme():
    sql = render_sql(plan_of())
    assert "WHERE p.KNOWLEDGE_BASE_ID = k.ID" in sql


def test_phrase_attaches_to_theme_by_question_not_by_id():
    """Коды в боевой базе могли разъехаться — цепляемся за текст вопроса."""
    sql = render_sql(plan_of())
    assert "FROM ULTIMA.AI_KNOWLEDGE_BASE k" in sql
    assert "KNOWLEDGE_BASE_ID) VALUES" not in sql


def test_sql_preamble_and_single_commit():
    sql = render_sql(plan_of())
    assert "SET DEFINE OFF" in sql
    assert "WHENEVER SQLERROR EXIT FAILURE ROLLBACK" in sql
    assert sql.count("\nCOMMIT;") == 1


def test_sql_guards_against_duplicate_questions_in_base():
    sql = render_sql(plan_of())
    assert "RAISE_APPLICATION_ERROR(-20002," in sql


def test_inserts_go_scenarios_then_records_then_phrases():
    sql = render_sql(plan_of())
    assert (
        sql.index("INTO ULTIMA.AI_SCENARIOS")
        < sql.index("INTO ULTIMA.AI_KNOWLEDGE_BASE")
        < sql.index("INTO ULTIMA.AI_KB_PHRASES")
    )


def test_empty_plan_renders_without_breaking():
    sql = render_sql(Plan())
    assert "COMMIT;" in sql
    assert "Нерешённого нет." in sql
    assert "INSERT INTO" not in sql


# --------------------------------------------------------------------------
# Шапка скрипта
# --------------------------------------------------------------------------

def test_header_states_counts_and_unresolved():
    plan = plan_of(
        deferred_directions=[
            {"telephone_direction_id": 29, "name": "Саппорт ПНС+Apple",
             "phone_for_web_req": "7082", "reason": "номер делят шесть направлений"}
        ]
    )
    header = "\n".join(
        line for line in render_sql(plan).splitlines() if line.startswith("--")
    )
    assert "тем:          1" in header
    assert "ОТЛОЖЕННЫЕ ОСОЗНАННО (1)" in header
    assert "Саппорт ПНС+Apple" in header
    assert "PHONE_FOR_WEB_REQ" in header


def test_header_explains_idempotency():
    header = render_sql(plan_of())
    assert "ИДЕМПОТЕНТЕН" in header
    assert "ДОБАВЛЯЕТ, А НЕ ПЕРЕСОЗДАЁТ" in header


def test_wrap_comment_never_exceeds_width():
    text = "очень длинное объяснение " * 20
    assert all(len(line) <= 74 for line in wrap_comment(text))


def test_report_lists_every_new_topic():
    lines = "\n".join(report_lines(plan_of()))
    assert "нужен ремонт форсунок" in lines
    assert "7068" in lines


# --------------------------------------------------------------------------
# Запуск целиком
# --------------------------------------------------------------------------

def test_main_writes_file(tmp_path, capsys):
    paths = {}
    for name, data in (
        ("exp", make_expansion()),
        ("snap", SNAPSHOT),
        ("ref", REFERENCE),
    ):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        paths[name] = str(path)
    output = tmp_path / "08.sql"

    assert main(["--expansion", paths["exp"], "--snapshot", paths["snap"],
                 "--reference", paths["ref"], "--output", str(output)]) == 0

    sql = output.read_text(encoding="utf-8")
    assert "INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE" in sql
    assert "Тем:          1" in capsys.readouterr().err


# --------------------------------------------------------------------------
# Настоящие данные
# --------------------------------------------------------------------------

def real_plan():
    from tools.expand_knowledge_base import (
        DEFAULT_EXPANSION_PATH,
        DEFAULT_REFERENCE_PATH,
        DEFAULT_SNAPSHOT_PATH,
    )
    from tools.export_knowledge_base import load_json

    return build_plan(
        load_json(DEFAULT_EXPANSION_PATH),
        load_json(DEFAULT_SNAPSHOT_PATH),
        load_json(DEFAULT_REFERENCE_PATH),
    )


def test_real_expansion_builds():
    """Настоящая посылка: 4 темы, 4 сценария, 156 формулировок."""
    plan = real_plan()
    assert len(plan.records) == 4
    assert len(plan.scenarios) == 4
    assert len(plan.phrases) == 156
    render_sql(plan)  # экранирование проверяется здесь же


def test_real_expansion_covers_only_directions_with_a_number():
    from tools.export_knowledge_base import load_json
    from tools.expand_knowledge_base import DEFAULT_REFERENCE_PATH

    directions = {
        int(r["id"]): r
        for r in load_json(DEFAULT_REFERENCE_PATH)["telephone_directions"]
    }
    for record in real_plan().records:
        assert (directions[record.telephone_direction_id]
                .get("phone_for_web_req") or "").strip()


def test_real_expansion_has_no_duplicate_phrases():
    plan = real_plan()
    keys = [normalize_phrase(p.phrase) for p in plan.phrases]
    keys += [normalize_phrase(r.question) for r in plan.records]
    assert len(keys) == len(set(keys))


def test_real_expansion_texts_fit_the_column():
    plan = real_plan()
    texts = [p.phrase for p in plan.phrases]
    for record in plan.records:
        texts += [record.question, record.clarifying_question, record.positive_reply]
    for scenario in plan.scenarios:
        texts.append(scenario.name)
    assert all(len(text) <= MAX_TEXT_LENGTH for text in texts if text)


def test_real_expansion_brings_every_touched_theme_to_the_target_band():
    """Ориентир — 12–16 формулировок на тему, считая каноничную."""
    from tools.export_knowledge_base import load_json
    from tools.expand_knowledge_base import DEFAULT_SNAPSHOT_PATH

    snapshot = load_json(DEFAULT_SNAPSHOT_PATH)
    existing = Existing.from_snapshot(snapshot)
    plan = real_plan()

    totals: dict[str, int] = {}
    for record in snapshot["records"]:
        totals[normalize_phrase(record["question"])] = 1 + len(
            existing.phrases_by_record.get(int(record["id"]), ())
        )
    for record in plan.records:
        totals[normalize_phrase(record.question)] = 1
    for phrase in plan.phrases:
        totals[normalize_phrase(phrase.question)] += 1

    touched = {normalize_phrase(p.question) for p in plan.phrases}
    touched |= {normalize_phrase(r.question) for r in plan.records}
    for question in touched:
        assert 12 <= totals[question] <= 16, (question, totals[question])


def test_real_expansion_matches_committed_sql():
    """sql/08 порождён генератором и не правился руками."""
    from tools.expand_knowledge_base import REPO_ROOT

    committed = (REPO_ROOT / "sql" / "08_knowledge_base_expansion.sql").read_text(
        encoding="utf-8"
    )

    def without_date(text: str) -> str:
        # в шапке стоит дата генерации, она меняется сама по себе
        return "\n".join(
            line for line in text.splitlines() if not line.startswith("-- Порождён")
        )

    assert without_date(committed) == without_date(render_sql(real_plan()))
