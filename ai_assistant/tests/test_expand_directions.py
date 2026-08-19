"""Тесты генератора досылки по списку направлений заказчика (sql/12).

Сами INSERT'ы генератор берёт у sql/08 через render_body — они покрыты
test_expand_knowledge_base.py и здесь не дублируются. Проверяется то, что есть
только у 12: сверка номеров частного мастера, отказ заводить темы «ЧМ_*» и
отчёт по списку направлений из тикета.
"""

import json

import pytest

from tools.expand_directions import (
    ChmAudit,
    audit_single_master_numbers,
    build_directions_plan,
    is_single_master,
    main,
    render_sql,
    report_lines,
)
from tools.export_knowledge_base import MAX_TEXT_LENGTH
from tools.expand_knowledge_base import normalize_phrase


def direction(id_, name, pwr=None, psm=None, single=0):
    return {
        "id": id_,
        "name": name,
        "phone_for_web_req": pwr,
        "phone_missed_rq_sngl_mstr": psm,
        "is_single_master": single,
    }


REFERENCE = {
    "equipment_types": [
        {"id": 1, "name": "Телевизоры"},
        {"id": 2, "name": "Стиральные машины"},
        {"id": 3, "name": "Сушильная машина"},
    ],
    "telephone_directions": [
        direction(25, "ТВ", "7048", "7040"),
        direction(53, "Стиральные машины", "7021", "7057"),
        direction(67, "Ремонт окон", "7076", "7084"),
        direction(73, "ЧМ_ТВ", "7040", single=1),
        direction(82, "ЧМ (СМА/ПМА/СУШ)", "7057", "7057", single=1),
        direction(97, "ЧМ (Ремонт окон)", "7078", single=1),
        direction(98, "Ветуслуги", "7119", "7119"),
        direction(106, "Ветцентр МРТ", "7209"),
    ],
    "direction_equipment_links": [
        {"telephone_direction_id": 53, "equipment_type_id": 2},
        {"telephone_direction_id": 53, "equipment_type_id": 3},
    ],
}

SNAPSHOT = {
    "scenarios": [{"id": 1, "telephone_direction_id": 53, "action_type": 1,
                   "name": "Стиральные машины"}],
    "records": [{"id": 1, "scenario_id": 1, "equipment_type_id": 2,
                 "is_from_bot": 0, "question": "стиральная машина не отжимает"}],
    "phrases": [{"id": 1, "knowledge_base_id": 1, "is_from_bot": 0,
                 "phrase": "стиралка сломалась"}],
}

WANTED = [25, 53, 67, 73, 82, 97, 98, 106]


def make_payload(**overrides):
    payload = {
        "customer_directions": list(WANTED),
        "new_topics": [],
        "skipped_directions": [],
        "excluded_directions": [],
        "chm_skip_reason": "частные мастера темами не заводятся",
    }
    payload.update(overrides)
    return payload


def topic(**overrides):
    base = {
        "telephone_direction_id": 106,
        "scenario_name": "Ветцентр МРТ",
        "question": "нужно сделать мрт животному",
        "clarifying_question": "Правильно понимаю, что вас интересует МРТ?"
                              " Ответьте, пожалуйста, да или нет",
        "positive_reply": "Соединяю вас со специалистом, оставайтесь на линии",
        "equipment_type": "",
        "why": "почему",
        "question_variants": ["нужно мрт собаке"],
    }
    base.update(overrides)
    return base


def plan_for(**overrides):
    return build_directions_plan(make_payload(**overrides), SNAPSHOT, REFERENCE)


# --------------------------------------------------------------------------
# Признак частного мастера
# --------------------------------------------------------------------------

def test_single_master_is_read_from_the_flag_not_from_the_name():
    """Имя «ЧМ_ТВ» ни при чём: смотреть надо на IS_SINGLE_MASTER."""
    assert is_single_master(direction(73, "ЧМ_ТВ", "7040", single=1))
    assert not is_single_master(direction(9, "ЧМ_ТВ", "7040", single=0))
    assert is_single_master(direction(9, "Без ЧМ в названии", "1", single=1))


def test_missing_flag_means_not_single_master():
    assert not is_single_master({"id": 1, "name": "х"})


# --------------------------------------------------------------------------
# Сверка номеров
# --------------------------------------------------------------------------

def test_number_matching_a_chm_direction_is_paired():
    audit = audit_single_master_numbers([25], REFERENCE)
    assert audit.paired == [(25, "7040", [73])]
    assert not audit.dangling and not audit.empty


def test_number_without_any_chm_direction_is_dangling():
    """67 «Ремонт окон» ждёт 7084, а у ЧМ (Ремонт окон) номер 7078."""
    audit = audit_single_master_numbers([67], REFERENCE)
    assert [(d, n) for d, n, _ in audit.dangling] == [(67, "7084")]
    assert not audit.paired


def test_number_equal_to_own_number_is_reported_separately():
    audit = audit_single_master_numbers([98], REFERENCE)
    assert len(audit.dangling) == 1
    assert "своему же обычному номеру" in audit.dangling[0][2]


def test_empty_number_is_reported_with_the_regular_one():
    audit = audit_single_master_numbers([106], REFERENCE)
    assert audit.empty == [(106, "7209")]


def test_chm_direction_itself_is_not_audited_as_a_regular_one():
    """У ЧМ-направления свой номер ЧМ проверять бессмысленно."""
    audit = audit_single_master_numbers([82], REFERENCE)
    assert not audit.paired and not audit.dangling and not audit.empty


def test_chm_direction_nobody_points_to_is_an_orphan():
    audit = audit_single_master_numbers([73, 97], REFERENCE)
    assert [d for d, _ in audit.orphans] == [97]


def test_unknown_direction_is_skipped_silently():
    audit = audit_single_master_numbers([9999], REFERENCE)
    assert audit == ChmAudit()


def test_pair_is_looked_up_across_the_whole_reference():
    """Пара может лежать вне списка заказчика — искать надо по справочнику."""
    audit = audit_single_master_numbers([53], REFERENCE)
    assert audit.paired == [(53, "7057", [82])]


# --------------------------------------------------------------------------
# План
# --------------------------------------------------------------------------

def test_chm_directions_from_the_list_are_skipped_wholesale():
    plan = plan_for()
    assert plan.chm_skipped == [73, 82, 97]
    assert plan.chm_reason == "частные мастера темами не заводятся"


def test_topic_on_a_chm_direction_breaks_the_generator():
    """Тема на ЧМ-направление — прямой запрет, ломаемся до генерации SQL."""
    with pytest.raises(ValueError, match="частного"):
        plan_for(new_topics=[topic(telephone_direction_id=73)])


def test_topic_on_a_regular_direction_passes():
    plan = plan_for(new_topics=[topic(telephone_direction_id=25)])
    assert [r.telephone_direction_id for r in plan.base.records] == [25]


def test_direction_with_an_existing_scenario_counts_as_covered():
    plan = plan_for()
    assert 53 in plan.covered


def test_direction_getting_a_new_topic_counts_as_covered():
    plan = plan_for(new_topics=[topic()])
    assert 106 in plan.covered
    assert 106 not in [i for i, _ in plan.uncovered]


def test_direction_without_topic_and_without_reason_is_reported():
    plan = plan_for()
    assert (25, "ТВ") in plan.uncovered
    assert (106, "Ветцентр МРТ") in plan.uncovered


def test_explicitly_skipped_direction_leaves_the_uncovered_list():
    plan = plan_for(skipped_directions=[
        {"telephone_direction_id": 25, "reason": "служебное"}])
    assert plan.skipped == [(25, "служебное")]
    assert 25 not in [i for i, _ in plan.uncovered]


def test_every_wanted_direction_is_accounted_for_exactly_once():
    plan = plan_for(
        new_topics=[topic()],
        skipped_directions=[{"telephone_direction_id": 25, "reason": "служебное"},
                            {"telephone_direction_id": 67, "reason": "потом"},
                            {"telephone_direction_id": 98, "reason": "потом"}],
    )
    total = (len(plan.covered) + len(plan.chm_skipped)
             + len(plan.skipped) + len(plan.uncovered))
    assert total == len(WANTED)


def test_excluded_directions_are_carried_into_the_plan():
    plan = plan_for(excluded_directions=[
        {"was": 66, "name": "Сушильные машины", "now": 53,
         "now_name": "Стиральные машины"}])
    assert plan.excluded == [(66, "Сушильные машины", 53, "Стиральные машины")]


# --------------------------------------------------------------------------
# Печать
# --------------------------------------------------------------------------

def test_header_reports_counts_and_the_audit():
    sql = render_sql(plan_for(new_topics=[topic()]), REFERENCE)
    head = sql.split("SET DEFINE OFF")[0]
    assert "тем:          1" in head
    assert "СВЕРКА НОМЕРОВ ЧАСТНОГО МАСТЕРА" in head
    assert "25 «ТВ» -> 7040 -> 73 «ЧМ_ТВ»" in head
    assert "67 «Ремонт окон» -> 7084" in head
    assert "97 «ЧМ (Ремонт окон)», номер 7078" in head


def test_header_lists_chm_directions_and_the_reason():
    head = render_sql(plan_for(), REFERENCE).split("SET DEFINE OFF")[0]
    assert "НАПРАВЛЕНИЯ ЧАСТНОГО МАСТЕРА, ТЕМ НЕ ЗАВОДИМ (3)" in head
    assert "частные мастера темами не заводятся" in head


def test_header_lists_directions_cancelled_by_the_customer():
    plan = plan_for(excluded_directions=[
        {"was": 115, "name": "Установка VPN", "now": 21, "now_name": "ПК и нотбуки"}])
    head = render_sql(plan, REFERENCE).split("SET DEFINE OFF")[0]
    assert "115 «Установка VPN» -> обслуживает направление 21 «ПК и нотбуки»" in head


def test_body_is_the_same_one_as_in_sql_08():
    """INSERT'ы не переписаны заново: преамбула, вставки и один COMMIT."""
    sql = render_sql(plan_for(new_topics=[topic()]), REFERENCE)
    assert "SET DEFINE OFF" in sql
    assert "WHENEVER SQLERROR EXIT FAILURE ROLLBACK" in sql
    assert sql.count("COMMIT;") == 1
    assert "NVL(MAX(ID), 0) + 1" in sql
    assert " VALUES (" not in sql  # только INSERT ... SELECT ... WHERE NOT EXISTS


def test_every_insert_is_guarded():
    sql = render_sql(plan_for(new_topics=[topic()]), REFERENCE)
    inserts = sql.count("INSERT INTO ULTIMA.")
    assert inserts == sql.count("NOT EXISTS") - 1  # минус проверка на дубли вопросов
    assert inserts == 3  # сценарий + тема + одна формулировка


def test_empty_plan_renders_without_breaking():
    sql = render_sql(plan_for(), REFERENCE)
    assert "тем:          0" in sql
    assert "COMMIT;" in sql


def test_report_lists_new_topics_and_the_audit():
    lines = report_lines(plan_for(new_topics=[topic()]), REFERENCE)
    text = "\n".join(lines)
    assert "нужно сделать мрт животному" in text
    assert "Сверка ЧМ:" in text


def test_main_writes_file(tmp_path):
    paths = {}
    for name, data in (("payload", make_payload(new_topics=[topic()])),
                       ("snap", SNAPSHOT), ("ref", REFERENCE)):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        paths[name] = str(path)
    output = tmp_path / "out.sql"
    assert main(["--payload", paths["payload"], "--snapshot", paths["snap"],
                 "--reference", paths["ref"], "--output", str(output)]) == 0
    assert "COMMIT;" in output.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# Настоящие данные
# --------------------------------------------------------------------------

def real():
    from tools.expand_directions import (
        DEFAULT_PAYLOAD_PATH,
        DEFAULT_REFERENCE_PATH,
        DEFAULT_SNAPSHOT_PATH,
    )
    from tools.export_knowledge_base import load_json

    reference = load_json(DEFAULT_REFERENCE_PATH)
    plan = build_directions_plan(
        load_json(DEFAULT_PAYLOAD_PATH),
        load_json(DEFAULT_SNAPSHOT_PATH),
        reference,
    )
    return plan, reference


def test_real_payload_builds():
    """Настоящая посылка: 8 тем, 3 сценария, 112 формулировок."""
    plan, reference = real()
    assert len(plan.base.records) == 8
    assert len(plan.base.scenarios) == 3
    assert len(plan.base.phrases) == 112
    render_sql(plan, reference)


def test_real_payload_has_no_topic_on_a_chm_direction():
    plan, reference = real()
    directions = {int(r["id"]): r for r in reference["telephone_directions"]}
    for record in plan.base.records:
        assert not is_single_master(directions[record.telephone_direction_id])


def test_real_payload_covers_only_directions_with_a_number():
    plan, reference = real()
    directions = {int(r["id"]): r for r in reference["telephone_directions"]}
    for record in plan.base.records:
        number = directions[record.telephone_direction_id].get("phone_for_web_req")
        assert (number or "").strip(), record.question


def test_real_payload_leaves_nothing_unexplained():
    """Каждое направление списка либо покрыто, либо объяснено."""
    plan, _ = real()
    assert plan.uncovered == []


def test_real_payload_does_not_touch_cancelled_directions():
    """66, 68, 69, 114, 115 исключены полностью: ни сценариев, ни привязок."""
    plan, _ = real()
    cancelled = {was for was, _, _, _ in plan.excluded}
    assert cancelled == {66, 68, 69, 114, 115}
    touched = {r.telephone_direction_id for r in plan.base.records}
    touched |= {s.telephone_direction_id for s in plan.base.scenarios}
    assert not (touched & cancelled)


def test_real_payload_has_no_duplicate_phrases():
    plan, _ = real()
    keys = [normalize_phrase(p.phrase) for p in plan.base.phrases]
    keys += [normalize_phrase(r.question) for r in plan.base.records]
    assert len(keys) == len(set(keys))


def test_real_payload_texts_fit_the_column():
    plan, _ = real()
    texts = [p.phrase for p in plan.base.phrases]
    for record in plan.base.records:
        texts += [record.question, record.clarifying_question, record.positive_reply]
    for scenario in plan.base.scenarios:
        texts.append(scenario.name)
    assert all(len(text) <= MAX_TEXT_LENGTH for text in texts if text)


def test_real_payload_keeps_every_new_theme_in_the_target_band():
    """Ориентир — 12–16 формулировок на тему, считая каноничную."""
    plan, _ = real()
    totals = {normalize_phrase(r.question): 1 for r in plan.base.records}
    for phrase in plan.base.phrases:
        totals[normalize_phrase(phrase.question)] += 1
    for question, count in totals.items():
        assert 12 <= count <= 16, (question, count)


def test_real_clarifying_questions_have_no_gender():
    """«Я правильно понял» в базе больше нет и возвращаться не должно."""
    plan, _ = real()
    for record in plan.base.records:
        assert record.clarifying_question.startswith("Правильно понимаю, что")
        assert "понял" not in record.clarifying_question.lower()


def test_real_payload_matches_committed_sql():
    """sql/12 порождён генератором и не правился руками."""
    from tools.expand_directions import REPO_ROOT

    plan, reference = real()
    committed = (REPO_ROOT / "sql" / "12_knowledge_base_directions.sql").read_text(
        encoding="utf-8"
    )
    generated_on = None
    for line in committed.splitlines():
        if line.startswith("-- Порождён tools/expand_directions.py "):
            import datetime

            generated_on = datetime.datetime.strptime(
                line.split()[-1].rstrip("."), "%d.%m.%Y"
            ).date()
    assert generated_on is not None
    assert render_sql(plan, reference, generated_on) == committed
