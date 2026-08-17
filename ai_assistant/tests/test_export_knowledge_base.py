"""Тесты генератора переноса базы знаний в справочники ERP.

Проверяется то, что ломает перенос молча: экранирование, сопоставление
названий со справочниками и поведение при неразрешённых названиях.
"""

import json

import pytest

from tools.export_knowledge_base import (
    ACTION_TYPE_REDIRECT,
    MAX_TEXT_LENGTH,
    RULE_NAME_IN_TAB,
    RULE_ONLY_TYPE,
    Plan,
    assigned_types,
    build_direction_tabs,
    build_name_index,
    build_plan,
    check_text,
    main,
    missing_types,
    normalize_name,
    render_sql,
    resolve_name,
    sql_number,
    sql_string,
    unresolved_names,
)


# Слепок боевых данных в миниатюре: направление с одним типом на вкладке (67),
# направление с несколькими (53), и случай «Samsung» — название совпадает
# с типом справочника, но на вкладке направления этого типа нет.
REFERENCE = {
    "snapshot_date": "2026-08-17",
    "source": "ULTIMA.EQUIPMENT_TYPES, ULTIMA.TELEPHONE_DIRECTIONS, ULTIMA.TELDDIR_TO_EQUIPTYPES",
    "equipment_types": [
        {"id": 119, "name": "Стиральные машины"},
        {"id": 405, "name": "Сушильная машина"},
        {"id": 116, "name": "Холодильники"},
        {"id": 300, "name": "Промышленные холодильники"},
        {"id": 52, "name": "iPad"},
        {"id": 265, "name": "Часы"},
        {"id": 326, "name": "Часы"},
        {"id": 392, "name": "Samsung"},
        {"id": 450, "name": "Планшеты Samsung"},
        {"id": 812, "name": "Смартфон Samsung"},
        {"id": 721, "name": "Ремонт окон (разовые)"},
    ],
    "telephone_directions": [
        {"id": 0, "name": "Не указан", "avail_for_redirect": 0},
        {"id": 52, "name": "Холодильники", "avail_for_redirect": 1},
        {"id": 53, "name": "Стиральные машины", "avail_for_redirect": 1},
        {"id": 67, "name": "Ремонт окон", "avail_for_redirect": 1},
        {"id": 100, "name": "Samsung", "avail_for_redirect": 1},
        {"id": 111, "name": "Направление без вкладки", "avail_for_redirect": 1},
    ],
    "direction_equipment_links": [
        {"telephone_direction_id": 53, "equipment_type_id": 119},
        {"telephone_direction_id": 53, "equipment_type_id": 405},
        {"telephone_direction_id": 52, "equipment_type_id": 116},
        {"telephone_direction_id": 52, "equipment_type_id": 300},
        {"telephone_direction_id": 67, "equipment_type_id": 721},
        {"telephone_direction_id": 100, "equipment_type_id": 450},
        {"telephone_direction_id": 100, "equipment_type_id": 812},
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


# --------------------------------------------------------------------------
# Тип оборудования: вкладка направления, три правила по порядку
# --------------------------------------------------------------------------

def test_tabs_are_grouped_by_direction():
    tabs = build_direction_tabs(REFERENCE["direction_equipment_links"])
    assert tabs[53] == [119, 405]
    assert tabs[67] == [721]
    assert 111 not in tabs


def test_rule_1_single_type_on_tab_wins_even_without_name_match():
    """п.1: на вкладке ровно один тип — берём его, название неважно."""
    plan = build_plan(
        [make_record(telephone_direction_id=67, equipment_type="Ремонт окон")], REFERENCE
    )
    record = plan.records[0]
    assert record.equipment_type_id == 721
    assert record.equipment_rule == RULE_ONLY_TYPE


def test_rule_1_beats_rule_2():
    """Порядок правил: первое сработавшее выигрывает."""
    plan = build_plan(
        [make_record(telephone_direction_id=67, equipment_type="Холодильники")], REFERENCE
    )
    assert plan.records[0].equipment_type_id == 721


def test_rule_2_name_match_inside_tab():
    """п.2: название совпало дословно и тип есть на вкладке направления."""
    plan = build_plan([make_record()], REFERENCE)
    record = plan.records[0]
    assert record.equipment_type_id == 119
    assert record.equipment_rule == RULE_NAME_IN_TAB


def test_rule_3_name_matches_but_type_is_not_on_tab():
    """Случай Samsung: тип 392 в справочнике есть, а на вкладке направления нет."""
    plan = build_plan(
        [make_record(telephone_direction_id=100, equipment_type="Samsung")], REFERENCE
    )
    record = plan.records[0]
    assert record.equipment_type_id is None
    assert record.equipment_rule is None
    assert "392" in record.equipment_reason
    assert "вкладке" in record.equipment_reason


def test_rule_3_name_is_not_in_dictionary():
    plan = build_plan([make_record(equipment_type="Гидроцикл")], REFERENCE)
    assert plan.records[0].equipment_type_id is None
    assert "нет в справочнике" in plan.records[0].equipment_reason


def test_rule_3_similar_name_is_not_invented():
    """Похожее название в справочнике не считается совпадением."""
    plan = build_plan([make_record(equipment_type="Стиральная машина")], REFERENCE)
    assert plan.records[0].equipment_type_id is None


def test_rule_3_direction_without_tab():
    plan = build_plan(
        [make_record(telephone_direction_id=111, equipment_type="Холодильники")], REFERENCE
    )
    assert plan.records[0].equipment_type_id is None
    assert "вкладка" in plan.records[0].equipment_reason


def test_rule_3_empty_name_and_multi_type_tab():
    plan = build_plan([make_record(equipment_type="")], REFERENCE)
    record = plan.records[0]
    assert len(plan.records) == 1
    assert record.equipment_type_id is None
    assert record.equipment_reason == "в базе знаний тип не указан"


def test_report_splits_assigned_and_missing():
    records = [
        make_record(id=1),
        make_record(id=2, telephone_direction_id=100, equipment_type="Samsung"),
    ]
    plan = build_plan(records, REFERENCE)
    assert len(assigned_types(plan)) == 1
    assert len(missing_types(plan)) == 1
    assert RULE_NAME_IN_TAB in assigned_types(plan)[0]
    assert "Samsung" in missing_types(plan)[0]


def test_sql_header_lists_rule_for_every_assigned_type():
    records = [
        make_record(id=1),
        make_record(id=2, telephone_direction_id=67, equipment_type="Ремонт окон"),
        make_record(id=3, telephone_direction_id=100, equipment_type="Samsung"),
    ]
    plan = build_plan(records, REFERENCE)
    header = "\n".join(
        line for line in render_sql(plan, REFERENCE).splitlines() if line.startswith("--")
    )
    assert "ТИП ПРОСТАВЛЕН (2)" in header
    assert "БЕЗ ТИПА ОБОРУДОВАНИЯ (1)" in header
    assert RULE_ONLY_TYPE in header
    assert RULE_NAME_IN_TAB in header
    assert "«Ремонт окон (разовые)»" in header


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
    assert "Тип оборудования проставлен во всех записях." in sql


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


def real_plan():
    from tools.export_knowledge_base import (
        DEFAULT_KNOWLEDGE_PATH,
        DEFAULT_REFERENCE_PATH,
        load_json,
    )

    reference = load_json(DEFAULT_REFERENCE_PATH)
    return build_plan(load_json(DEFAULT_KNOWLEDGE_PATH), reference), reference


def test_real_knowledge_base_converts_without_errors():
    """Настоящий файл: 28 записей, 348 формулировок, 27 сценариев."""
    plan, reference = real_plan()

    assert len(plan.records) == 28
    assert len(plan.phrases) + len(plan.records) == 348
    assert len(plan.scenarios) == 27
    render_sql(plan, reference)  # экранирование проверяется здесь же


def test_real_knowledge_base_equipment_types():
    """15 записей с типом, 13 без. Samsung — без: типа нет на вкладке."""
    plan, _ = real_plan()

    assert len(assigned_types(plan)) == 15
    assert len(missing_types(plan)) == 13

    samsung = next(r for r in plan.records if r.question == "телефон самсунг не включается")
    assert samsung.equipment_type_id is None
    assert "392" in samsung.equipment_reason

    by_rule = [r.equipment_rule for r in plan.records if r.equipment_type_id is not None]
    assert by_rule.count(RULE_ONLY_TYPE) == 3
    assert by_rule.count(RULE_NAME_IN_TAB) == 12
