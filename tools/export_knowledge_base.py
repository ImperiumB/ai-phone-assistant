"""UL-17568, этап 2. Генератор SQL для переноса базы знаний AI-помощника
из файла `ai_assistant/knowledge_base.json` в справочники ERP.

    py -3.12 tools/export_knowledge_base.py > sql/06_seed_knowledge_base.sql

SQL печатается в stdout, отчёт о том, что не разрешилось, — в stderr и
комментарием в шапке SQL.

Справочники ERP читаются из снимка `tools/erp_dictionaries.json`: доступ к
боевой базе только на чтение и только у человека, поэтому генератор не ходит
в базу сам. Снимок обновляется выгрузкой из ULTIMA.EQUIPMENT_TYPES,
ULTIMA.TELEPHONE_DIRECTIONS и ULTIMA.TELDDIR_TO_EQUIPTYPES — вкладки «Типы
оборудования» телефонного направления.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable

# Все текстовые колонки трёх справочников — VARCHAR2(256). База в CL8MSWIN1251,
# однобайтовой, поэтому 256 символов кириллицы помещаются целиком.
MAX_TEXT_LENGTH = 256

# Единственный осмысленный на этом этапе тип действия сценария — перевод звонка.
ACTION_TYPE_REDIRECT = 1

# Направление 0 «Не указан» — это отсутствие направления, а не направление.
# Сценарий по нему не заводится: переводить некуда.
SENTINEL_DIRECTION_ID = 0

# Правила проставления типа оборудования. Применяются по порядку, выигрывает
# первое сработавшее. Третьего правила в коде нет: это просто «оставить пусто».
#
# Вкладка «Типы оборудования» телефонного направления почти всегда содержит
# десятки типов, поэтому сама по себе однозначного ответа не даёт. А если
# направление покрывает два десятка типов и клиент сказал «телек не включается»,
# то бот честно не знает, какой именно тип: в обращении будет «Неизвестное
# оборудование», человек уточнит. Выдумывать тип нельзя.
RULE_ONLY_TYPE = "п.1 единственный тип во вкладке направления"
RULE_NAME_IN_TAB = "п.2 название совпало, тип есть во вкладке направления"

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KNOWLEDGE_PATH = REPO_ROOT / "ai_assistant" / "knowledge_base.json"
DEFAULT_REFERENCE_PATH = REPO_ROOT / "tools" / "erp_dictionaries.json"


# --------------------------------------------------------------------------
# Экранирование и проверка текстов
# --------------------------------------------------------------------------

def sql_string(value: str | None) -> str:
    """Строковый литерал Oracle. Одинарная кавычка удваивается.

    Пустая строка и None дают NULL: пустых текстов в справочнике быть не должно.
    """
    if value is None:
        return "NULL"
    text = value.strip()
    if not text:
        return "NULL"
    check_text(text)
    return "'" + text.replace("'", "''") + "'"


def check_text(text: str) -> None:
    """Ломается на том, что испортит SQL или не влезет в колонку.

    Молча резать или калечить нельзя: скрипт выполняет человек, и тихая
    потеря половины фразы обнаружится только на звонке.
    """
    if len(text) > MAX_TEXT_LENGTH:
        raise ValueError(
            f"текст длиннее {MAX_TEXT_LENGTH} символов ({len(text)}): {text[:60]}..."
        )
    for char in text:
        if char in "\r\n" or ord(char) < 32:
            raise ValueError(f"управляющий символ {char!r} в тексте: {text[:60]}")
    if "&" in text:
        # SQL*Plus принял бы & за подстановочную переменную. В шапке скрипта
        # стоит SET DEFINE OFF, но полагаться на настройку сессии не стоит.
        raise ValueError(f"символ '&' в тексте: {text[:60]}")


def sql_number(value: int | None) -> str:
    return "NULL" if value is None else str(int(value))


# --------------------------------------------------------------------------
# Сопоставление названий со справочниками
# --------------------------------------------------------------------------

def normalize_name(name: str) -> str:
    """Регистр, лишние пробелы и «ё» при сравнении названий не считаются."""
    return " ".join(name.split()).lower().replace("ё", "е")


def build_name_index(rows: Iterable[dict]) -> dict[str, list[int]]:
    """Нормализованное название -> список кодов. Список, а не код: в боевом
    справочнике оборудования есть тёзки, и выбирать за человека нельзя."""
    index: dict[str, list[int]] = {}
    for row in rows:
        index.setdefault(normalize_name(row["name"]), []).append(int(row["id"]))
    return index


@dataclass
class Issue:
    """То, что генератор разрешить не смог. Разбирает человек."""

    subject: str
    reason: str

    def __str__(self) -> str:
        return f"{self.subject} — {self.reason}"


def resolve_name(name: str, index: dict[str, list[int]]) -> tuple[int | None, str | None]:
    """Код по названию. Второй элемент — причина отказа, если кода нет."""
    matches = index.get(normalize_name(name), [])
    if not matches:
        return None, "нет в справочнике"
    if len(matches) > 1:
        codes = ", ".join(str(code) for code in matches)
        return None, f"в справочнике несколько записей с таким названием (коды {codes})"
    return matches[0], None


def build_direction_tabs(links: Iterable[dict]) -> dict[int, list[int]]:
    """Направление -> типы оборудования с его вкладки «Типы оборудования»."""
    tabs: dict[int, list[int]] = {}
    for link in links:
        tabs.setdefault(int(link["telephone_direction_id"]), []).append(
            int(link["equipment_type_id"])
        )
    return tabs


def resolve_equipment_type(
    equipment_name: str,
    direction_id: int | None,
    equipment_index: dict[str, list[int]],
    tabs: dict[int, list[int]],
) -> tuple[int | None, str | None, str | None]:
    """Тип оборудования для записи базы знаний.

    Возвращает (код, правило, причина отказа). Правила по порядку:
      1. на вкладке направления ровно один тип — берём его;
      2. название из базы знаний дословно совпало с типом справочника И этот
         тип есть на вкладке направления — берём его;
      3. иначе пусто.
    """
    tab = tabs.get(direction_id) if direction_id is not None else None

    if tab and len(tab) == 1:
        return tab[0], RULE_ONLY_TYPE, None

    if not equipment_name:
        return None, None, "в базе знаний тип не указан"

    code, reason = resolve_name(equipment_name, equipment_index)
    if code is None:
        return None, None, f"«{equipment_name}»: {reason}"

    if not tab:
        return None, None, (
            f"«{equipment_name}» есть в справочнике (код {code}), но вкладка"
            " направления пуста или направление не указано"
        )

    if code not in tab:
        return None, None, (
            f"«{equipment_name}» есть в справочнике (код {code}), но на вкладке"
            f" направления {direction_id} его нет — направление покрывает"
            f" {len(tab)} других типов"
        )

    return code, RULE_NAME_IN_TAB, None


# --------------------------------------------------------------------------
# План переноса
# --------------------------------------------------------------------------

@dataclass
class Scenario:
    id: int
    name: str
    telephone_direction_id: int


@dataclass
class Record:
    id: int
    question: str
    clarifying_question: str | None
    positive_reply: str | None
    scenario_id: int | None
    equipment_type_id: int | None
    # Чем проставлен тип оборудования (RULE_*) или почему он пуст.
    equipment_type_name: str | None = None
    equipment_rule: str | None = None
    equipment_reason: str | None = None


@dataclass
class Phrase:
    id: int
    knowledge_base_id: int
    phrase: str


@dataclass
class Plan:
    scenarios: list[Scenario] = field(default_factory=list)
    records: list[Record] = field(default_factory=list)
    phrases: list[Phrase] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)


def build_plan(knowledge: list[dict], reference: dict) -> Plan:
    """Раскладывает JSON по трём справочникам.

    Коды записей проставляются числами с единицы. Последовательностей Oracle в
    схеме ULTIMA нет ни одной — коды справочникам раздаёт сама система, а здесь
    таблицы заведомо пустые (это проверяет шапка SQL), поэтому нумерация с
    единицы безопасна. Ноль не берём: в ERP он повсеместно значит «не указано».
    """
    plan = Plan()

    equipment_index = build_name_index(reference["equipment_types"])
    equipment_names = {
        int(row["id"]): row["name"] for row in reference["equipment_types"]
    }
    directions = {int(row["id"]): row for row in reference["telephone_directions"]}
    tabs = build_direction_tabs(reference.get("direction_equipment_links", []))

    # --- сценарии: по одному на каждое направление, встречающееся в базе ---
    scenario_by_direction: dict[int, int] = {}
    for record in knowledge:
        direction_id = record.get("telephone_direction_id")
        if direction_id is None or direction_id in scenario_by_direction:
            continue
        direction_id = int(direction_id)
        if direction_id == SENTINEL_DIRECTION_ID:
            continue
        if direction_id not in directions:
            plan.issues.append(
                Issue(
                    f"телефонное направление {direction_id}",
                    "нет в справочнике, сценарий не заведён",
                )
            )
            continue
        scenario = Scenario(
            id=len(plan.scenarios) + 1,
            name=directions[direction_id]["name"],
            telephone_direction_id=direction_id,
        )
        plan.scenarios.append(scenario)
        scenario_by_direction[direction_id] = scenario.id

    # --- записи базы знаний и их формулировки ---
    for record in knowledge:
        record_id = len(plan.records) + 1
        question = record["question"].strip()
        if not question:
            # QUESTION в справочнике NOT NULL, да и запись без вопроса бесполезна.
            raise ValueError(f"запись {record_id}: пустой вопрос")

        direction_id = record.get("telephone_direction_id")
        direction_id = None if direction_id is None else int(direction_id)
        scenario_id = scenario_by_direction.get(direction_id)
        if scenario_id is None:
            plan.issues.append(
                Issue(
                    f"запись {record_id} «{question}»",
                    "сценарий не проставлен: "
                    + (
                        "телефонное направление не указано"
                        if direction_id in (None, SENTINEL_DIRECTION_ID)
                        else f"направление {direction_id} не разрешилось"
                    ),
                )
            )

        equipment_name = (record.get("equipment_type") or "").strip()
        equipment_id, rule, reason = resolve_equipment_type(
            equipment_name, direction_id, equipment_index, tabs
        )

        plan.records.append(
            Record(
                id=record_id,
                question=question,
                clarifying_question=record.get("clarifying_question"),
                positive_reply=record.get("positive_reply"),
                scenario_id=scenario_id,
                equipment_type_id=equipment_id,
                equipment_type_name=equipment_names.get(equipment_id),
                equipment_rule=rule,
                equipment_reason=reason,
            )
        )

        # Каноничная формулировка едет в поиск наравне с вариантами, но
        # хранится в самой записи — в AI_KB_PHRASES её дублировать не нужно.
        for variant in record.get("question_variants", []):
            phrase = variant.strip()
            if not phrase:
                # PHRASE в справочнике NOT NULL.
                raise ValueError(f"запись {record_id}: пустая формулировка")
            plan.phrases.append(
                Phrase(
                    id=len(plan.phrases) + 1,
                    knowledge_base_id=record_id,
                    phrase=phrase,
                )
            )

    return plan


def unresolved_names(plan: Plan) -> list[str]:
    """Прочее, что генератор разрешить не смог, без повторов."""
    seen: list[str] = []
    for issue in plan.issues:
        text = str(issue)
        if text not in seen:
            seen.append(text)
    return seen


def assigned_types(plan: Plan) -> list[str]:
    """Записи с проставленным типом оборудования и правило, по которому он взят."""
    return [
        f"запись {r.id} «{r.question}» -> тип {r.equipment_type_id}"
        f" «{r.equipment_type_name}» ({r.equipment_rule})"
        for r in plan.records
        if r.equipment_type_id is not None
    ]


def missing_types(plan: Plan) -> list[str]:
    """Записи без типа оборудования. По ним человек проходит руками."""
    return [
        f"запись {r.id} «{r.question}» — {r.equipment_reason}"
        for r in plan.records
        if r.equipment_type_id is None
    ]


# --------------------------------------------------------------------------
# Печать SQL
# --------------------------------------------------------------------------

def render_sql(plan: Plan, reference: dict, generated_on: date | None = None) -> str:
    generated_on = generated_on or date.today()
    phrase_total = len(plan.phrases) + len(plan.records)

    out: list[str] = []
    add = out.append

    add("-- " + "=" * 70)
    add("-- UL-17568, этап 2. Перенос базы знаний виртуального AI-помощника")
    add("-- в справочники ERP: сценарии, записи, формулировки.")
    add("--")
    add("-- Порождён tools/export_knowledge_base.py " + generated_on.strftime("%d.%m.%Y") + ".")
    add("-- Править руками нельзя: правки затрёт следующая генерация.")
    add("--")
    add("-- Источник данных:   ai_assistant/knowledge_base.json")
    add(
        "-- Снимок справочников: tools/erp_dictionaries.json от "
        + str(reference.get("snapshot_date", "неизвестно"))
        + " (" + str(reference.get("source", "")) + ")"
    )
    add("--")
    add("-- Файл в UTF-8 без BOM. Запускать с NLS_LANG=RUSSIAN_CIS.AL32UTF8,")
    add("-- иначе кириллица приедет в справочник мусором.")
    add("--")
    add(f"-- Сценариев:    {len(plan.scenarios)} (по одному на телефонное направление)")
    add(f"-- Записей:      {len(plan.records)}")
    add(
        f"-- Формулировок: {phrase_total} — {len(plan.phrases)} в AI_KB_PHRASES"
        f" плюс {len(plan.records)} каноничных в самих записях"
    )
    add("--")
    add("-- ОДНОРАЗОВЫЙ. Скрипт наполняет только пустые справочники: коды записей")
    add("-- в нём проставлены числами, и досыпать их поверх ручных правок нельзя —")
    add("-- получились бы дубли и чужие ссылки. Первый блок проверяет, что все три")
    add("-- таблицы пусты, и если это не так — останавливает выполнение с ORA-20001,")
    add("-- ничего не вставив. Поэтому повторный запуск безопасен: он не создаёт")
    add("-- дублей, а сообщает, что переносить уже некуда. Вставки идут одной")
    add("-- транзакцией, COMMIT один и в самом конце; на любой ошибке — откат.")

    add("--")
    add("-- Тип оборудования берётся с вкладки «Типы оборудования» телефонного")
    add("-- направления (ULTIMA.TELDDIR_TO_EQUIPTYPES). Правила по порядку:")
    add("--   " + RULE_ONLY_TYPE + ";")
    add("--   " + RULE_NAME_IN_TAB + ";")
    add("--   п.3 иначе пусто.")
    add("-- Пусто — это решение, а не недоработка: если направление покрывает два")
    add("-- десятка типов, бот не знает, о каком именно речь. В обращении будет")
    add("-- «Неизвестное оборудование», человек уточнит.")

    assigned = assigned_types(plan)
    add("--")
    add(f"-- ТИП ПРОСТАВЛЕН ({len(assigned)}):")
    for text in assigned:
        add("--   " + text)

    missing = missing_types(plan)
    add("--")
    if missing:
        add(f"-- БЕЗ ТИПА ОБОРУДОВАНИЯ ({len(missing)}) — пройти руками:")
        for text in missing:
            add("--   " + text)
    else:
        add("-- Тип оборудования проставлен во всех записях.")

    issues = unresolved_names(plan)
    if issues:
        add("--")
        add(f"-- ПРОЧЕЕ, РАЗБИРАЕТ ЧЕЛОВЕК ({len(issues)}):")
        for text in issues:
            add("--   " + text)
    add("-- " + "=" * 70)
    add("")
    add("SET DEFINE OFF")
    add("WHENEVER SQLERROR EXIT FAILURE ROLLBACK")
    add("")
    add("")
    add("-- Проверка: переносим только в пустые справочники.")
    add("DECLARE")
    add("  v_rows NUMBER;")
    add("BEGIN")
    add("  SELECT (SELECT COUNT(*) FROM ULTIMA.AI_SCENARIOS)")
    add("       + (SELECT COUNT(*) FROM ULTIMA.AI_KNOWLEDGE_BASE)")
    add("       + (SELECT COUNT(*) FROM ULTIMA.AI_KB_PHRASES)")
    add("    INTO v_rows FROM DUAL;")
    add("  IF v_rows > 0 THEN")
    add("    RAISE_APPLICATION_ERROR(-20001,")
    add("      'Справочники AI-помощника не пусты: перенос уже выполнен или записи'")
    add("      || ' заведены руками. Скрипт ничего не менял.');")
    add("  END IF;")
    add("END;")
    add("/")
    add("")
    add("")
    add("-- " + "-" * 70)
    add("-- Сценарии. Тип действия 1 — перевод звонка.")
    add("-- Номер для перевода здесь не хранится: он берётся из направления.")
    add("-- " + "-" * 70)
    for scenario in plan.scenarios:
        add(
            "INSERT INTO ULTIMA.AI_SCENARIOS (ID, NAME, ACTION_TYPE, TELEPHONE_DIRECTION_ID, NOT_ACTIVE)"
            f" VALUES ({scenario.id}, {sql_string(scenario.name)}, {ACTION_TYPE_REDIRECT},"
            f" {scenario.telephone_direction_id}, 0);"
        )

    add("")
    add("")
    add("-- " + "-" * 70)
    add("-- Записи базы знаний.")
    add("-- " + "-" * 70)
    for record in plan.records:
        add(
            "INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION,"
            " POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE)"
            f" VALUES ({record.id}, {sql_string(record.question)},"
            f" {sql_string(record.clarifying_question)}, {sql_string(record.positive_reply)},"
            f" {sql_number(record.scenario_id)}, {sql_number(record.equipment_type_id)}, 0, 0);"
        )

    add("")
    add("")
    add("-- " + "-" * 70)
    add("-- Формулировки. Каноничной формулировки здесь нет — она в самой записи.")
    add("-- " + "-" * 70)
    current_record: int | None = None
    for phrase in plan.phrases:
        if phrase.knowledge_base_id != current_record:
            current_record = phrase.knowledge_base_id
            question = plan.records[current_record - 1].question
            add(f"-- запись {current_record}: {question}")
        add(
            "INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)"
            f" VALUES ({phrase.id}, {phrase.knowledge_base_id}, {sql_string(phrase.phrase)}, 0);"
        )

    add("")
    add("")
    add("COMMIT;")
    add("")
    add("")
    add("-- " + "-" * 70)
    add(
        f"-- Проверка: должно получиться {len(plan.scenarios)} / {len(plan.records)}"
        f" / {len(plan.phrases)}."
    )
    add("-- " + "-" * 70)
    add("SELECT (SELECT COUNT(*) FROM ULTIMA.AI_SCENARIOS)      AS SCENARIOS,")
    add("       (SELECT COUNT(*) FROM ULTIMA.AI_KNOWLEDGE_BASE) AS RECORDS,")
    add("       (SELECT COUNT(*) FROM ULTIMA.AI_KB_PHRASES)     AS PHRASES")
    add("  FROM DUAL;")
    add("")

    return "\n".join(out)


# --------------------------------------------------------------------------
# Запуск
# --------------------------------------------------------------------------

def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--knowledge", type=Path, default=DEFAULT_KNOWLEDGE_PATH)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE_PATH)
    parser.add_argument(
        "--output", type=Path, default=None, help="куда писать SQL; по умолчанию stdout"
    )
    args = parser.parse_args(argv)

    knowledge = load_json(args.knowledge)
    reference = load_json(args.reference)

    plan = build_plan(knowledge, reference)
    sql = render_sql(plan, reference)

    if args.output:
        args.output.write_text(sql, encoding="utf-8", newline="\n")
    else:
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
        sys.stdout.write(sql)

    report = [
        f"Сценариев:    {len(plan.scenarios)}",
        f"Записей:      {len(plan.records)}",
        f"Формулировок: {len(plan.phrases) + len(plan.records)}"
        f" ({len(plan.phrases)} в AI_KB_PHRASES + {len(plan.records)} каноничных)",
    ]
    assigned = assigned_types(plan)
    report.append(f"Тип оборудования проставлен: {len(assigned)}")
    report.extend("  " + text for text in assigned)

    missing = missing_types(plan)
    report.append(f"Без типа оборудования: {len(missing)}")
    report.extend("  " + text for text in missing)

    issues = unresolved_names(plan)
    if issues:
        report.append(f"Прочее, разбирает человек ({len(issues)}):")
        report.extend("  " + text for text in issues)
    sys.stderr.reconfigure(encoding="utf-8")
    sys.stderr.write("\n".join(report) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
