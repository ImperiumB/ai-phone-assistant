"""Тесты генератора переноса базы знаний в справочники ERP.

Проверяется то, что ломает перенос молча: экранирование, сопоставление
названий со справочниками и поведение при неразрешённых названиях.
"""

import json

import pytest

from tools.export_knowledge_base import (
    ACTION_TYPE_REDIRECT,
    MAX_TEXT_LENGTH,
    Plan,
    build_name_index,
    build_plan,
    check_text,
    main,
    normalize_name,
    render_sql,
    resolve_name,
    sql_number,
    sql_string,
    unresolved_names,
)


REFERENCE = {
    "snapshot_date": "2026-08-17",
    "source": "ULTIMA.EQUIPMENT_TYPES, ULTIMA.TELEPHONE_DIRECTIONS",
    "equipment_types": [
        {"id": 119, "name": "Стиральные машины"},
        {"id": 116, "name": "Холодильники"},
        {"id": 52, "name": "iPad"},
        {"id": 265, "name": "Часы"},
        {"id": 326, "name": "Часы"},
    ],
    "telephone_directions": [
        {"id": 0, "name": "Не указан", "avail_for_redirect": 0},
        {"id": 52, "name": "Холодильники", "avail_for_redirect": 1},
        {"id": 53, "name": "Стиральные машины", "avail_for_redirect": 1},
    ],
}


def make_record(**overrides):
    record = {
        "id": 1,
        "telephone_direction_id": 53,
        "question": "стиральная машина не отжимает",
        "question_variants": ["стиралка сломалась"],
        "clarifying_question": "Правильно я понял?",
        "positive_reply": "Соединяю вас со специалистом",
        "equipment_type": "Стиральные машины",
    }
    record.update(overrides)
    return record


# --------------------------------------------------------------------------
# Экранирование
# --------------------------------------------------------------------------

def test_sql_string_wraps_in_quotes():
    assert sql_string("стиралка") == "'стиралка'"


def test_sql_string_doubles_single_quote():
    assert sql_string("мастер'ская") == "'мастер''ская'"


def test_sql_string_doubles_every_quote():
    assert sql_string("'''") == "''''''''"


def test_sql_string_empty_and_none_give_null():
    assert sql_string("") == "NULL"
    assert sql_string("   ") == "NULL"
    assert sql_string(None) == "NULL"


def test_sql_string_trims_edges():
    assert sql_string("  стиралка  ") == "'стиралка'"


def test_sql_number_passes_none_as_null():
    assert sql_number(None) == "NULL"
    assert sql_number(53) == "53"


def test_check_text_rejects_too_long():
    with pytest.raises(ValueError):
        check_text("я" * (MAX_TEXT_LENGTH + 1))


def test_check_text_allows_exactly_max_length():
    check_text("я" * MAX_TEXT_LENGTH)


def test_check_text_rejects_newline():
    """Перенос строки внутри литерала разъедет построчный скрипт."""
    with pytest.raises(ValueError):
        check_text("стиралка\nсломалась")


def test_check_text_rejects_ampersand():
    """SQL*Plus принял бы & за подстановочную переменную."""
    with pytest.raises(ValueError):
        check_text("ремонт & настройка")


def test_generated_record_with_quote_is_escaped():
    plan = build_plan([make_record(question="стиралка 'Бош' не греет")], REFERENCE)
    sql = render_sql(plan, REFERENCE)
    assert "'стиралка ''Бош'' не греет'" in sql


# --------------------------------------------------------------------------
# Сопоставление названий
# --------------------------------------------------------------------------

def test_normalize_ignores_case_spaces_and_yo():
    assert normalize_name("  Стиральные   Машины ") == normalize_name("стиральные машины")
    assert normalize_name("Приёмка") == normalize_name("приемка")


def test_resolve_name_finds_by_exact_name():
    index = build_name_index(REFERENCE["equipment_types"])
    code, reason = resolve_name("СТИРАЛЬНЫЕ  машины", index)
    assert code == 119
    assert reason is None


def test_resolve_name_reports_missing():
    index = build_name_index(REFERENCE["equipment_types"])
    code, reason = resolve_name("Гидроцикл", index)
    assert code is None
    assert "нет в справочнике" in reason


def test_resolve_name_refuses_to_choose_between_twins():
    """В боевом справочнике есть тёзки — выбирать за человека нельзя."""
    index = build_name_index(REFERENCE["equipment_types"])
    code, reason = resolve_name("Часы", index)
    assert code is None
    assert "265" in reason and "326" in reason


def test_equipment_type_resolved_into_reference():
    plan = build_plan([make_record()], REFERENCE)
    assert plan.records[0].equipment_type_id == 119


def test_unresolved_equipment_leaves_null_and_lands_in_report():
    plan = build_plan([make_record(equipment_type="Гидроцикл")], REFERENCE)
    assert plan.records[0].equipment_type_id is None
    assert any("Гидроцикл" in text for text in unresolved_names(plan))
    sql = render_sql(plan, REFERENCE)
    assert "Гидроцикл" in sql.splitlines()[0] or any(
        "Гидроцикл" in line for line in sql.splitlines() if line.startswith("--")
    )


def test_unresolved_equipment_name_is_not_invented():
    """Похожее название в справочнике не считается совпадением."""
    plan = build_plan([make_record(equipment_type="Стиральная машина")], REFERENCE)
    assert plan.records[0].equipment_type_id is None


def test_unresolved_names_are_not_repeated():
    records = [
        make_record(id=1, equipment_type="Гидроцикл"),
        make_record(id=2, equipment_type="Гидроцикл"),
    ]
    plan = build_plan(records, REFERENCE)
    assert sum("Гидроцикл" in text for text in unresolved_names(plan)) == 1


def test_empty_equipment_type_is_reported_but_record_survives():
    plan = build_plan([make_record(equipment_type="")], REFERENCE)
    assert len(plan.records) == 1
    assert plan.records[0].equipment_type_id is None
    assert any("тип оборудования не указан" in text for text in unresolved_names(plan))


# --------------------------------------------------------------------------
# Сценарии и телефонные направления
# --------------------------------------------------------------------------

def test_one_scenario_per_direction():
    records = [
        make_record(id=1, telephone_direction_id=53),
        make_record(id=2, telephone_direction_id=52, equipment_type="Холодильники"),
        make_record(id=3, telephone_direction_id=53),
    ]
    plan = build_plan(records, REFERENCE)
    assert [(s.id, s.name, s.telephone_direction_id) for s in plan.scenarios] == [
        (1, "Стиральные машины", 53),
        (2, "Холодильники", 52),
    ]
    assert [r.scenario_id for r in plan.records] == [1, 2, 1]


def test_scenario_action_type_is_redirect():
    plan = build_plan([make_record()], REFERENCE)
    sql = render_sql(plan, REFERENCE)
    assert f"VALUES (1, 'Стиральные машины', {ACTION_TYPE_REDIRECT}, 53, 0)" in sql


def test_missing_direction_gives_no_scenario_and_lands_in_report():
    plan = build_plan([make_record(telephone_direction_id=777)], REFERENCE)
    assert plan.scenarios == []
    assert plan.records[0].scenario_id is None
    assert any("777" in text for text in unresolved_names(plan))


def test_sentinel_direction_zero_gives_no_scenario():
    """Направление 0 «Не указан» — это отсутствие направления, переводить некуда."""
    plan = build_plan([make_record(telephone_direction_id=0, equipment_type="")], REFERENCE)
    assert plan.scenarios == []
    assert plan.records[0].scenario_id is None
    assert any("не указано" in text for text in unresolved_names(plan))


# --------------------------------------------------------------------------
# Формулировки
# --------------------------------------------------------------------------

def test_phrases_are_linked_to_their_record():
    records = [
        make_record(id=1, question_variants=["а", "б"]),
        make_record(id=2, telephone_direction_id=52, equipment_type="Холодильники",
                    question="холодильник не морозит", question_variants=["в"]),
    ]
    plan = build_plan(records, REFERENCE)
    assert [(p.id, p.knowledge_base_id, p.phrase) for p in plan.phrases] == [
        (1, 1, "а"),
        (2, 1, "б"),
        (3, 2, "в"),
    ]


def test_canonical_question_is_not_duplicated_into_phrases():
    plan = build_plan([make_record(question_variants=["стиралка сломалась"])], REFERENCE)
    assert [p.phrase for p in plan.phrases] == ["стиралка сломалась"]


def test_empty_phrase_is_rejected():
    with pytest.raises(ValueError):
        build_plan([make_record(question_variants=["  "])], REFERENCE)


def test_empty_question_is_rejected():
    with pytest.raises(ValueError):
        build_plan([make_record(question="  ")], REFERENCE)


# --------------------------------------------------------------------------
# Печать SQL
# --------------------------------------------------------------------------

def test_sql_has_guard_and_single_commit():
    plan = build_plan([make_record()], REFERENCE)
    sql = render_sql(plan, REFERENCE)
    assert "ORA-20001" in sql or "RAISE_APPLICATION_ERROR(-20001," in sql
    assert "SET DEFINE OFF" in sql
    assert "WHENEVER SQLERROR EXIT FAILURE ROLLBACK" in sql
    assert sql.count("\nCOMMIT;") == 1


def test_sql_header_states_counts():
    records = [
        make_record(id=1, question_variants=["а", "б"]),
        make_record(id=2, telephone_direction_id=52, equipment_type="Холодильники",
                    question="холодильник не морозит", question_variants=["в"]),
    ]
    plan = build_plan(records, REFERENCE)
    header = [line for line in render_sql(plan, REFERENCE).splitlines() if line.startswith("--")]
    header_text = "\n".join(header)
    assert "Записей:      2" in header_text
    assert "Формулировок: 5" in header_text  # 3 варианта + 2 каноничных
    assert "Сценариев:    2" in header_text


def test_sql_inserts_go_scenarios_then_records_then_phrases():
    plan = build_plan([make_record()], REFERENCE)
    sql = render_sql(plan, REFERENCE)
    assert (
        sql.index("INTO ULTIMA.AI_SCENARIOS")
        < sql.index("INTO ULTIMA.AI_KNOWLEDGE_BASE")
        < sql.index("INTO ULTIMA.AI_KB_PHRASES")
    )


def test_sql_never_uses_id_zero():
    """Ноль в ERP означает «не указано» — коды начинаются с единицы."""
    plan = build_plan([make_record()], REFERENCE)
    sql = render_sql(plan, REFERENCE)
    assert "VALUES (0," not in sql


def test_render_of_empty_plan_does_not_break():
    sql = render_sql(Plan(), REFERENCE)
    assert "COMMIT;" in sql
    assert "Всё разрешилось" in sql


# --------------------------------------------------------------------------
# Запуск целиком на настоящей базе знаний
# --------------------------------------------------------------------------

def test_main_writes_file_and_reports(tmp_path, capsys):
    knowledge = tmp_path / "kb.json"
    knowledge.write_text(json.dumps([make_record()], ensure_ascii=False), encoding="utf-8")
    reference = tmp_path / "ref.json"
    reference.write_text(json.dumps(REFERENCE, ensure_ascii=False), encoding="utf-8")
    output = tmp_path / "seed.sql"

    assert main(
        [
            "--knowledge", str(knowledge),
            "--reference", str(reference),
            "--output", str(output),
        ]
    ) == 0

    sql = output.read_text(encoding="utf-8")
    assert "INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE" in sql
    assert "Записей:      1" in capsys.readouterr().err


def test_real_knowledge_base_converts_without_errors():
    """Настоящий файл: 28 записей, 348 формулировок, 27 сценариев."""
    from tools.export_knowledge_base import (
        DEFAULT_KNOWLEDGE_PATH,
        DEFAULT_REFERENCE_PATH,
        load_json,
    )

    knowledge = load_json(DEFAULT_KNOWLEDGE_PATH)
    reference = load_json(DEFAULT_REFERENCE_PATH)
    plan = build_plan(knowledge, reference)

    assert len(plan.records) == 28
    assert len(plan.phrases) + len(plan.records) == 348
    assert len(plan.scenarios) == 27
    render_sql(plan, reference)  # экранирование проверяется здесь же
