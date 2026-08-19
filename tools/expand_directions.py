"""UL-18819. Генератор SQL по актуальному списку телефонных направлений заказчика.

    py -3.12 tools/expand_directions.py --output sql/12_knowledge_base_directions.sql

Зачем третий генератор, а не правка второго
-------------------------------------------
06 наполняет пустые справочники, 08 досылает в непустые. 12 — тоже досылка, и
сами INSERT'ы у него ровно те же: он берёт их у 08 через render_body(), чтобы
экранирование и защита от дублей жили в одном месте и были покрыты одними
тестами. Отдельный файл нужен из-за трёх вещей, которых у 08 нет:

* шапка отчитывается по списку направлений из тикета — что покрыто, что нет;
* сверка номеров частного мастера PHONE_MISSED_RQ_SNGL_MSTR (см. ниже);
* снимки справочников свежие. Снимки 08 править нельзя: тест
  test_real_expansion_matches_committed_sql держит sql/08 байт в байт, и
  подмена снимка под ним развалила бы уже отданный на исполнение файл.

Почему нет тем «ЧМ_*»
---------------------
У обычного направления два номера: обычный PHONE_FOR_WEB_REQ и для частного
мастера PHONE_MISSED_RQ_SNGL_MSTR. Второй равен обычному номеру парного
направления «ЧМ_*»: у направления 25 «ТВ» номер частного мастера 7040, и ровно
7040 — обычный номер направления 73 «ЧМ_ТВ». Звонок с линии частного мастера
уходит в его отдел сам — сервис выбирает номер по признаку линии, а не по
отдельной теме. Клиент голосом не говорит «я от частного мастера», поэтому
темы «ЧМ_*» не только не нужны, но и вредны: они перехватывали бы звонки у
обычных тем. Вместо тем генератор сверяет номера и складывает расхождения в
шапку — это работа заказчика, а не наша.

Источники данных
----------------
* tools/knowledge_base_directions.json — что досылаем и что пропускаем;
* tools/ai_kb_snapshot_18819.json      — что уже лежит в боевых справочниках;
* tools/erp_dictionaries_18819.json    — справочники ERP, включая номер ЧМ.

Генератор не ходит в базу сам: доступ к боевой базе только на чтение и только
у человека. Снимки обновляются выгрузкой.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from tools.export_knowledge_base import load_json
from tools.expand_knowledge_base import (
    Existing,
    Plan,
    build_plan,
    render_body,
    wrap_comment,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PAYLOAD_PATH = REPO_ROOT / "tools" / "knowledge_base_directions.json"
DEFAULT_SNAPSHOT_PATH = REPO_ROOT / "tools" / "ai_kb_snapshot_18819.json"
DEFAULT_REFERENCE_PATH = REPO_ROOT / "tools" / "erp_dictionaries_18819.json"


# --------------------------------------------------------------------------
# Сверка номеров частного мастера
# --------------------------------------------------------------------------

@dataclass
class ChmAudit:
    """Результат сверки PHONE_MISSED_RQ_SNGL_MSTR по списку заказчика.

    paired    — номер ЧМ заполнен и совпал с обычным номером ЧМ-направления;
    dangling  — номер заполнен, но парного ЧМ-направления с таким обычным
                номером в справочнике нет;
    empty     — номер ЧМ не заполнен вовсе;
    orphans   — ЧМ-направление, на обычный номер которого не ссылается ни
                одно обычное направление.
    """

    paired: list[tuple[int, str, list[int]]] = field(default_factory=list)
    dangling: list[tuple[int, str, str]] = field(default_factory=list)
    empty: list[tuple[int, str | None]] = field(default_factory=list)
    orphans: list[tuple[int, str]] = field(default_factory=list)


def is_single_master(direction: dict) -> bool:
    """Направление частного мастера. Признак справочника, а не догадка по имени."""
    return int(direction.get("is_single_master") or 0) == 1


def audit_single_master_numbers(wanted: list[int], reference: dict) -> ChmAudit:
    directions = {int(r["id"]): r for r in reference["telephone_directions"]}
    audit = ChmAudit()

    # обычный номер ЧМ-направления -> сами ЧМ-направления. Берём по всему
    # справочнику, а не только по списку: пара могла остаться за его пределами.
    chm_by_number: dict[str, list[int]] = {}
    for row in reference["telephone_directions"]:
        number = (row.get("phone_for_web_req") or "").strip()
        if is_single_master(row) and number:
            chm_by_number.setdefault(number, []).append(int(row["id"]))

    # номер ЧМ обычного направления -> сами обычные направления
    users_by_number: dict[str, list[int]] = {}
    for row in reference["telephone_directions"]:
        number = (row.get("phone_missed_rq_sngl_mstr") or "").strip()
        if number and not is_single_master(row):
            users_by_number.setdefault(number, []).append(int(row["id"]))

    for direction_id in wanted:
        row = directions.get(direction_id)
        if row is None or is_single_master(row):
            continue
        number = (row.get("phone_missed_rq_sngl_mstr") or "").strip()
        own = (row.get("phone_for_web_req") or "").strip()
        if not number:
            audit.empty.append((direction_id, own or None))
        elif number in chm_by_number:
            audit.paired.append((direction_id, number, sorted(chm_by_number[number])))
        elif number == own:
            audit.dangling.append((
                direction_id, number,
                "равен своему же обычному номеру — отдельной линии ЧМ у направления нет",
            ))
        else:
            audit.dangling.append((
                direction_id, number,
                "ни одно ЧМ-направление не имеет такого обычного номера —"
                " звонок частного мастера уйдёт на номер без направления в ERP",
            ))

    for direction_id in wanted:
        row = directions.get(direction_id)
        if row is None or not is_single_master(row):
            continue
        number = (row.get("phone_for_web_req") or "").strip()
        if not users_by_number.get(number):
            audit.orphans.append((
                direction_id, number or "не заполнен",
            ))

    return audit


# --------------------------------------------------------------------------
# План досылки
# --------------------------------------------------------------------------

@dataclass
class DirectionsPlan:
    """План 08 плюс то, о чём отчитывается только 12."""

    base: Plan
    audit: ChmAudit
    # направление -> почему темы не будет
    skipped: list[tuple[int, str]] = field(default_factory=list)
    # ЧМ-направления, пропущенные все сразу по одной причине
    chm_skipped: list[int] = field(default_factory=list)
    chm_reason: str = ""
    # направления, отменённые заказчиком: (было, стало)
    excluded: list[tuple[int, str, int, str]] = field(default_factory=list)
    excluded_note: str = ""
    # сколько направлений списка закрыто темами после этой досылки
    covered: list[int] = field(default_factory=list)
    uncovered: list[tuple[int, str]] = field(default_factory=list)


def build_directions_plan(payload: dict, snapshot: dict, reference: dict) -> DirectionsPlan:
    directions = {int(r["id"]): r for r in reference["telephone_directions"]}
    wanted = [int(i) for i in payload["customer_directions"]]

    # Тема на направление частного мастера — прямой запрет, а не предупреждение:
    # клиент голосом не сообщает, что звонит от частного мастера, поэтому такая
    # тема неотличима от обычной и будет перехватывать её звонки. Ломаемся до
    # генерации, чтобы это нельзя было случайно дослать в боевой справочник.
    for topic in payload.get("new_topics", []):
        direction_id = int(topic["telephone_direction_id"])
        row = directions.get(direction_id)
        if row is not None and is_single_master(row):
            raise ValueError(
                f"тема «{topic['question']}» заведена на направление частного"
                f" мастера {direction_id} «{row['name'].strip()}»."
                " Так нельзя: звонок с линии частного мастера уходит в его отдел"
                " сам, по номеру PHONE_MISSED_RQ_SNGL_MSTR обычного направления."
            )

    base = build_plan(payload, snapshot, reference)
    audit = audit_single_master_numbers(wanted, reference)

    def name(direction_id: int) -> str:
        row = directions.get(direction_id)
        return (row["name"].strip() if row else "нет в справочнике")

    skipped = [
        (int(row["telephone_direction_id"]), row["reason"])
        for row in payload.get("skipped_directions", [])
    ]
    chm_skipped = [i for i in wanted if i in directions and is_single_master(directions[i])]

    excluded = [
        (int(row["was"]), row["name"], int(row["now"]), row["now_name"])
        for row in payload.get("excluded_directions", [])
    ]

    # Что из списка закрыто темами: уже заведённые сценарии плюс новые темы.
    existing = Existing.from_snapshot(snapshot)
    covered_directions = set(existing.scenario_by_direction)
    covered_directions |= {r.telephone_direction_id for r in base.records}

    skipped_ids = {i for i, _ in skipped} | set(chm_skipped)
    covered, uncovered = [], []
    for direction_id in wanted:
        if direction_id in covered_directions:
            covered.append(direction_id)
        elif direction_id in skipped_ids:
            continue
        else:
            uncovered.append((direction_id, name(direction_id)))

    return DirectionsPlan(
        base=base,
        audit=audit,
        skipped=skipped,
        chm_skipped=chm_skipped,
        chm_reason=payload.get("chm_skip_reason", ""),
        excluded=excluded,
        excluded_note=payload.get("excluded_directions_note", ""),
        covered=covered,
        uncovered=uncovered,
    )


# --------------------------------------------------------------------------
# Печать SQL
# --------------------------------------------------------------------------

def render_sql(plan: DirectionsPlan, reference: dict, generated_on: date | None = None) -> str:
    generated_on = generated_on or date.today()
    directions = {int(r["id"]): r for r in reference["telephone_directions"]}
    base = plan.base
    out: list[str] = []
    add = out.append

    def name(direction_id: int) -> str:
        row = directions.get(direction_id)
        return (row["name"].strip() if row else "нет в справочнике")

    def block(text: str, indent: str = "--   ", cont: str = "--     ") -> None:
        lines = wrap_comment(text, 70)
        add(indent + lines[0])
        for line in lines[1:]:
            add(cont + line)

    phrase_total = len(base.phrases) + len(base.records)
    wanted_total = len(plan.covered) + len(plan.chm_skipped) + len(plan.skipped) + len(plan.uncovered)

    add("-- " + "=" * 70)
    add("-- UL-18819 (подзадача UL-17568). Темы базы знаний по актуальному списку")
    add("-- телефонных направлений заказчика.")
    add("--")
    add("-- Порождён tools/expand_directions.py " + generated_on.strftime("%d.%m.%Y") + ".")
    add("-- Править руками нельзя: правки затрёт следующая генерация.")
    add("--")
    add("-- Файл в UTF-8 без BOM. Запускать с NLS_LANG=RUSSIAN_CIS.AL32UTF8,")
    add("-- иначе кириллица приедет в справочник мусором.")
    add("--")
    add("-- ЧТО ДОБАВЛЯЕТСЯ")
    add(f"--   сценариев:    {len(base.scenarios)}")
    add(f"--   тем:          {len(base.records)}")
    add(
        f"--   формулировок: {phrase_total} — {len(base.phrases)} в AI_KB_PHRASES"
        f" плюс {len(base.records)} каноничных в самих темах"
    )
    add("--")
    add("-- ДОБАВЛЯЕТ, А НЕ ПЕРЕСОЗДАЁТ. Существующие записи скрипт не трогает и не")
    add("-- удаляет. Коды новых записей берутся как MAX(ID)+1 по каждой таблице:")
    add("-- последовательностей и триггеров у этих трёх таблиц нет.")
    add("--")
    add("-- ИДЕМПОТЕНТЕН. Каждая вставка обёрнута в NOT EXISTS, поэтому повторный")
    add("-- запуск не создаёт дублей:")
    add("--   сценарий     — если по этому направлению его ещё нет;")
    add("--   тема         — если такой же вопрос ещё не заведён;")
    add("--   формулировка — если такой же у этой темы ещё нет.")
    add("-- Сравнение с точностью до регистра и пробелов. Темы ищутся по тексту")
    add("-- вопроса, а не по коду: коды в боевой базе могли разъехаться.")
    add("--")
    add("-- Вставки идут одной транзакцией, COMMIT один и в самом конце;")
    add("-- на любой ошибке — откат.")

    add("--")
    add("-- НОВЫЕ ТЕМЫ")
    for record in base.records:
        add(
            f"--   «{record.question}»"
            f" -> направление {record.telephone_direction_id}"
            f" «{name(record.telephone_direction_id)}», номер приёма"
            f" {record.phone_for_web_req}"
        )
        if record.equipment_type_id is not None:
            add(
                f"--     тип оборудования {record.equipment_type_id}"
                f" «{record.equipment_type_name}» ({record.equipment_rule})"
            )
        else:
            add(f"--     тип оборудования не проставлен — {record.equipment_reason}")
        for line in wrap_comment(record.why, 70):
            add("--     " + line)

    if plan.excluded:
        add("--")
        add(f"-- НАПРАВЛЕНИЯ, ОТМЕНЁННЫЕ ЗАКАЗЧИКОМ ({len(plan.excluded)}):")
        if plan.excluded_note:
            block(plan.excluded_note, "--   ", "--   ")
        for was, was_name, now, now_name in plan.excluded:
            add(f"--   {was} «{was_name}» -> обслуживает направление {now} «{now_name}»")

    add("--")
    add("-- НАПРАВЛЕНИЯ СПИСКА, ЗАКРЫТЫЕ ТЕМАМИ"
        f" ({len(plan.covered)} из {wanted_total}):")
    add("--   " + ", ".join(str(i) for i in plan.covered))

    if plan.chm_skipped:
        add("--")
        add(f"-- НАПРАВЛЕНИЯ ЧАСТНОГО МАСТЕРА, ТЕМ НЕ ЗАВОДИМ ({len(plan.chm_skipped)}):")
        add("--   " + ", ".join(str(i) for i in plan.chm_skipped))
        if plan.chm_reason:
            block(plan.chm_reason, "--   ", "--   ")

    if plan.skipped:
        add("--")
        add(f"-- НАПРАВЛЕНИЯ, ПРОПУЩЕННЫЕ ОСОЗНАННО ({len(plan.skipped)}):")
        for direction_id, reason in plan.skipped:
            add(f"--   направление {direction_id} «{name(direction_id)}»")
            block(reason, "--     ", "--     ")

    if plan.uncovered:
        add("--")
        add(f"-- НАПРАВЛЕНИЯ СПИСКА БЕЗ ТЕМЫ И БЕЗ ОБЪЯСНЕНИЯ ({len(plan.uncovered)}):")
        for direction_id, direction_name in plan.uncovered:
            add(f"--   {direction_id} «{direction_name}»")

    add("--")
    add("-- " + "-" * 67)
    add("-- СВЕРКА НОМЕРОВ ЧАСТНОГО МАСТЕРА. Ничего не меняет, только отчёт.")
    add("-- Скрипт сверяет PHONE_MISSED_RQ_SNGL_MSTR обычного направления с обычным")
    add("-- номером PHONE_FOR_WEB_REQ парного направления «ЧМ_*». Расхождения и")
    add("-- пустые номера разбирает заказчик: сервис берёт номер по признаку линии,")
    add("-- и если номер пуст, звонок частного мастера уйдёт на сопровождение.")
    add("-- " + "-" * 67)

    audit = plan.audit
    add(f"-- Номер ЧМ заполнен и пара нашлась ({len(audit.paired)}). Что пара найдена,")
    add("-- ещё не значит, что она осмысленна: справочник не мешает увести пылесосы")
    add("-- на линию ТВ. Список приведён целиком, смысл проверяет заказчик.")
    for direction_id, number, pairs in audit.paired:
        names = ", ".join(f"{p} «{name(p)}»" for p in pairs)
        add(f"--   {direction_id} «{name(direction_id)}» -> {number} -> {names}")

    add("--")
    if audit.dangling:
        add(f"-- Номер ЧМ заполнен, а пары нет ({len(audit.dangling)}):")
        for direction_id, number, why in audit.dangling:
            add(f"--   {direction_id} «{name(direction_id)}» -> {number}")
            block(why, "--     ", "--     ")
    else:
        add("-- Заполненных номеров ЧМ без пары нет.")

    add("--")
    if audit.empty:
        add(f"-- Номер ЧМ не заполнен ({len(audit.empty)}) — звонок частного мастера")
        add("-- по этим направлениям уйдёт на сопровождение:")
        for direction_id, own in audit.empty:
            add(
                f"--   {direction_id} «{name(direction_id)}»"
                f" (обычный номер: {own or 'тоже не заполнен'})"
            )
    else:
        add("-- Незаполненных номеров ЧМ нет.")

    add("--")
    if audit.orphans:
        add(f"-- ЧМ-направления, на которые никто не ссылается ({len(audit.orphans)}) —")
        add("-- ни одно обычное направление не указало их номер как свой номер ЧМ:")
        for direction_id, number in audit.orphans:
            add(f"--   {direction_id} «{name(direction_id)}», номер {number}")
    else:
        add("-- ЧМ-направлений без обратной ссылки нет.")

    if base.issues:
        add("--")
        add(f"-- ОСТАЛОСЬ НЕРЕШЁННЫМ, РАЗБИРАЕТ ЧЕЛОВЕК ({len(base.issues)}):")
        for text in base.issues:
            block(text, "--   ", "--     ")

    if base.already_present:
        add("--")
        add(
            f"-- УЖЕ БЫЛО В СПРАВОЧНИКЕ, НЕ ДОСЫЛАЕТСЯ ({len(base.already_present)}):"
        )
        for text in base.already_present:
            add("--   " + text)

    add("-- " + "=" * 70)
    out.extend(render_body(base))
    return "\n".join(out)


# --------------------------------------------------------------------------
# Запуск
# --------------------------------------------------------------------------

def report_lines(plan: DirectionsPlan, reference: dict) -> list[str]:
    directions = {int(r["id"]): r for r in reference["telephone_directions"]}
    base = plan.base
    lines = [
        f"Сценариев:    {len(base.scenarios)}",
        f"Тем:          {len(base.records)}",
        f"Формулировок: {len(base.phrases)} в AI_KB_PHRASES"
        f" + {len(base.records)} каноничных",
    ]
    for record in base.records:
        row = directions.get(record.telephone_direction_id)
        lines.append(
            f"  тема «{record.question}» -> направление"
            f" {record.telephone_direction_id}"
            f" «{row['name'].strip() if row else '?'}»"
            f" (номер {record.phone_for_web_req})"
        )
    lines.append(f"Закрыто направлений списка: {len(plan.covered)}")
    lines.append(f"ЧМ пропущено: {len(plan.chm_skipped)}")
    lines.append(f"Пропущено осознанно: {len(plan.skipped)}")
    lines.append(f"Отменено заказчиком: {len(plan.excluded)}")
    lines.append(
        f"Сверка ЧМ: пар {len(plan.audit.paired)},"
        f" без пары {len(plan.audit.dangling)},"
        f" пусто {len(plan.audit.empty)},"
        f" ЧМ без ссылки {len(plan.audit.orphans)}"
    )
    if plan.uncovered:
        lines.append(f"Без темы и без объяснения: {len(plan.uncovered)}")
        lines.extend(f"  {i} «{n}»" for i, n in plan.uncovered)
    if base.issues:
        lines.append(f"Осталось нерешённым: {len(base.issues)}")
        lines.extend("  " + text for text in base.issues)
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", type=Path, default=DEFAULT_PAYLOAD_PATH)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT_PATH)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE_PATH)
    parser.add_argument(
        "--output", type=Path, default=None, help="куда писать SQL; по умолчанию stdout"
    )
    args = parser.parse_args(argv)

    reference = load_json(args.reference)
    plan = build_directions_plan(
        load_json(args.payload),
        load_json(args.snapshot),
        reference,
    )
    sql = render_sql(plan, reference)

    if args.output:
        args.output.write_text(sql, encoding="utf-8", newline="\n")
    else:
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
        sys.stdout.write(sql)

    sys.stderr.reconfigure(encoding="utf-8")
    sys.stderr.write("\n".join(report_lines(plan, reference)) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
