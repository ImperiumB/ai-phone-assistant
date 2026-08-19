"""UL-17568, этап 3. Генератор SQL, который ДОСЫЛАЕТ данные в уже наполненные
справочники базы знаний AI-помощника.

    py -3.12 tools/expand_knowledge_base.py --output sql/08_knowledge_base_expansion.sql

Почему отдельный скрипт, а не правка tools/export_knowledge_base.py
------------------------------------------------------------------
У 06 и 08 разная задача, и объединять их — значит сломать оба.

06 одноразовый: он наполняет ПУСТЫЕ справочники, проставляет коды числами с
единицы и падает с ORA-20001, если в таблицах уже что-то есть. Его тесты
прибиты к боевым числам (28 записей, 348 формулировок, 27 сценариев), а сам
файл sql/06 уже отдан на исполнение и должен воспроизводиться байт в байт.

08 — прямая противоположность: он досылает в НЕПУСТЫЕ справочники, коды берёт
как MAX(ID)+1 прямо в запросе и обязан быть идемпотентным. Общего у них ровно
одно — экранирование текстов, и оно переиспользуется импортом, а не копией.
Так рискованная часть остаётся в одном месте и покрыта тестами обоих этапов.

Источники данных
----------------
* tools/knowledge_base_expansion.json — что досылаем (темы и формулировки);
* tools/ai_kb_snapshot.json          — что уже лежит в боевых справочниках;
* tools/erp_dictionaries.json        — справочники ERP (направления, оборудование).

Генератор не ходит в базу сам: доступ к боевой базе только на чтение и только
у человека. Снимки обновляются выгрузкой.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable

from tools.export_knowledge_base import (
    ACTION_TYPE_REDIRECT,
    MAX_TEXT_LENGTH,
    build_direction_tabs,
    build_name_index,
    check_text,
    load_json,
    resolve_equipment_type,
    sql_number,
    sql_string,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXPANSION_PATH = REPO_ROOT / "tools" / "knowledge_base_expansion.json"
DEFAULT_SNAPSHOT_PATH = REPO_ROOT / "tools" / "ai_kb_snapshot.json"
DEFAULT_REFERENCE_PATH = REPO_ROOT / "tools" / "erp_dictionaries.json"

# Нормализация текста при сравнении: регистр и пробелы не считаются. Ровно то же
# самое делает SQL-выражение SQL_NORMALIZE ниже — иначе Python и база разошлись бы
# во мнении, что считать дублем, и скрипт то досылал бы лишнее, то молчал.
SQL_NORMALIZE = "LOWER(TRIM(REGEXP_REPLACE({0}, '[[:space:]]+', ' ')))"


def normalize_phrase(text: str) -> str:
    """Регистр и пробелы при сравнении формулировок не считаются."""
    return " ".join(text.split()).lower()


def fold_yo(text: str) -> str:
    """«ё» -> «е». Для сравнения формулировок, не для вставки.

    База не считает «потёк» и «потек» одним и тем же, а живой человек считает.
    Такие пары — не дубль для SQL, но почти наверняка авторская оплошность,
    поэтому генератор на них останавливается.
    """
    return text.replace("ё", "е")


# --------------------------------------------------------------------------
# Что уже лежит в справочниках
# --------------------------------------------------------------------------

@dataclass
class Existing:
    """Снимок боевых справочников AI-помощника."""

    # нормализованный вопрос -> код записи
    questions: dict[str, int]
    # код записи -> нормализованные формулировки
    phrases_by_record: dict[int, set[str]]
    # нормализованная формулировка -> код записи, у которой она уже есть
    phrase_owner: dict[str, int]
    # телефонное направление -> код сценария
    scenario_by_direction: dict[int, int]
    # код записи -> вопрос как есть, для сообщений
    question_text: dict[int, str]

    @classmethod
    def from_snapshot(cls, snapshot: dict) -> "Existing":
        questions: dict[str, int] = {}
        question_text: dict[int, str] = {}
        for row in snapshot["records"]:
            key = normalize_phrase(row["question"])
            if key in questions:
                raise ValueError(
                    f"в снимке два вопроса «{row['question']}»:"
                    f" записи {questions[key]} и {row['id']}"
                )
            questions[key] = int(row["id"])
            question_text[int(row["id"])] = row["question"]

        phrases_by_record: dict[int, set[str]] = {}
        phrase_owner: dict[str, int] = {}
        for row in snapshot["phrases"]:
            record_id = int(row["knowledge_base_id"])
            key = normalize_phrase(row["phrase"])
            phrases_by_record.setdefault(record_id, set()).add(key)
            phrase_owner.setdefault(key, record_id)

        scenario_by_direction = {
            int(row["telephone_direction_id"]): int(row["id"])
            for row in snapshot["scenarios"]
        }
        return cls(
            questions=questions,
            phrases_by_record=phrases_by_record,
            phrase_owner=phrase_owner,
            scenario_by_direction=scenario_by_direction,
            question_text=question_text,
        )


# --------------------------------------------------------------------------
# План досылки
# --------------------------------------------------------------------------

@dataclass
class NewScenario:
    name: str
    telephone_direction_id: int


@dataclass
class NewRecord:
    question: str
    clarifying_question: str | None
    positive_reply: str | None
    telephone_direction_id: int
    equipment_type_id: int | None
    equipment_type_name: str | None
    equipment_rule: str | None
    equipment_reason: str | None
    phone_for_web_req: str
    why: str


@dataclass
class NewPhrase:
    """Формулировка и тема, к которой она цепляется (по тексту вопроса)."""

    question: str
    phrase: str
    # тема заводится этим же скриптом, а не лежит в базе
    to_new_record: bool = False


@dataclass
class Plan:
    scenarios: list[NewScenario] = field(default_factory=list)
    records: list[NewRecord] = field(default_factory=list)
    phrases: list[NewPhrase] = field(default_factory=list)
    # формулировки, которых досылать не нужно: они уже есть у своей темы
    already_present: list[str] = field(default_factory=list)
    # то, что генератор решить не смог
    issues: list[str] = field(default_factory=list)
    # направления, отложенные осознанно
    deferred: list[str] = field(default_factory=list)


def eligible_direction(direction: dict) -> tuple[bool, str | None]:
    """Годится ли направление под перевод звонка.

    Единственный признак — непустой номер приёма PHONE_FOR_WEB_REQ: именно его
    боевой астербот подставляет в перевод (обработчик 13161, redirectExten =
    telDir[0].PWR). Ни AVAIL_FOR_REDIRECT, ни EXTEN_FOR_REDIRECT_ID в переводе
    не участвуют, смотреть на них нельзя.
    """
    number = (direction.get("phone_for_web_req") or "").strip()
    if not number:
        return False, "не заполнен номер приёма PHONE_FOR_WEB_REQ, переводить некуда"
    return True, None


def build_plan(expansion: dict, snapshot: dict, reference: dict) -> Plan:
    plan = Plan()
    existing = Existing.from_snapshot(snapshot)

    directions = {int(row["id"]): row for row in reference["telephone_directions"]}
    equipment_index = build_name_index(reference["equipment_types"])
    equipment_names = {int(r["id"]): r["name"] for r in reference["equipment_types"]}
    tabs = build_direction_tabs(reference.get("direction_equipment_links", []))

    # Номера приёма, которые делят несколько направлений. Перевод по такому
    # номеру приведёт в одно и то же место независимо от выбранной темы.
    shared_numbers: dict[str, list[int]] = {}
    for row in reference["telephone_directions"]:
        number = (row.get("phone_for_web_req") or "").strip()
        if number:
            shared_numbers.setdefault(number, []).append(int(row["id"]))

    # Всё, что тема-владелец уже заняла: вопросы и формулировки. Пополняется по
    # мере разбора посылки, чтобы ловить дубли и внутри неё самой.
    taken: dict[str, str] = {}
    for key, record_id in existing.questions.items():
        taken[key] = f"вопрос записи {record_id}"
    for key, record_id in existing.phrase_owner.items():
        taken.setdefault(key, f"формулировка записи {record_id}")

    def claim(text: str, owner: str) -> None:
        """Занимает формулировку за темой или ломается, если её уже заняли."""
        check_text(text)
        key = normalize_phrase(text)
        if key in taken:
            raise ValueError(f"«{text}» ({owner}) уже занято: {taken[key]}")
        folded = fold_yo(key)
        for other in taken:
            if fold_yo(other) == folded:
                raise ValueError(
                    f"«{text}» ({owner}) отличается от «{other}» только буквой «ё»"
                )
        taken[key] = owner

    # --- новые темы ---
    for topic in expansion.get("new_topics", []):
        direction_id = int(topic["telephone_direction_id"])
        direction = directions.get(direction_id)
        if direction is None:
            plan.issues.append(
                f"направление {direction_id}: нет в справочнике, тема не заведена"
            )
            continue

        ok, reason = eligible_direction(direction)
        if not ok:
            plan.issues.append(f"направление {direction_id} «{direction['name']}»: {reason}")
            continue

        number = (direction.get("phone_for_web_req") or "").strip()
        sharers = [d for d in shared_numbers.get(number, []) if d != direction_id]
        if sharers:
            plan.issues.append(
                f"направление {direction_id} «{direction['name']}»: номер приёма"
                f" {number} делят также направления "
                + ", ".join(str(d) for d in sorted(sharers))
                + " — перевод придёт в одно место, тему проверить руками"
            )

        question = topic["question"].strip()
        claim(question, f"вопрос новой темы «{question}»")

        if direction_id not in existing.scenario_by_direction:
            already_planned = any(
                s.telephone_direction_id == direction_id for s in plan.scenarios
            )
            if not already_planned:
                plan.scenarios.append(
                    NewScenario(
                        name=topic.get("scenario_name") or direction["name"],
                        telephone_direction_id=direction_id,
                    )
                )

        equipment_name = (topic.get("equipment_type") or "").strip()
        equipment_id, rule, eq_reason = resolve_equipment_type(
            equipment_name, direction_id, equipment_index, tabs
        )

        plan.records.append(
            NewRecord(
                question=question,
                clarifying_question=topic.get("clarifying_question"),
                positive_reply=topic.get("positive_reply"),
                telephone_direction_id=direction_id,
                equipment_type_id=equipment_id,
                equipment_type_name=equipment_names.get(equipment_id),
                equipment_rule=rule,
                equipment_reason=eq_reason,
                phone_for_web_req=number,
                why=topic.get("why", ""),
            )
        )

        for variant in topic.get("question_variants", []):
            phrase = variant.strip()
            if not phrase:
                raise ValueError(f"тема «{question}»: пустая формулировка")
            claim(phrase, f"формулировка новой темы «{question}»")
            plan.phrases.append(
                NewPhrase(question=question, phrase=phrase, to_new_record=True)
            )

    # --- формулировки к существующим темам ---
    for block in expansion.get("extra_phrases", []):
        question = block["question"].strip()
        record_id = existing.questions.get(normalize_phrase(question))
        if record_id is None:
            plan.issues.append(
                f"тема «{question}»: такого вопроса нет в снимке справочника,"
                " формулировки не досылаются"
            )
            continue

        present = existing.phrases_by_record.get(record_id, set())
        for variant in block.get("phrases", []):
            phrase = variant.strip()
            if not phrase:
                raise ValueError(f"тема «{question}»: пустая формулировка")
            if normalize_phrase(phrase) in present:
                plan.already_present.append(f"запись {record_id}: «{phrase}»")
                continue
            claim(phrase, f"формулировка записи {record_id}")
            plan.phrases.append(NewPhrase(question=question, phrase=phrase))

    for row in expansion.get("deferred_directions", []):
        plan.deferred.append(
            f"направление {row['telephone_direction_id']} «{row['name']}»"
            f" (номер приёма {row.get('phone_for_web_req') or 'нет'}) — {row['reason']}"
        )

    return plan


# --------------------------------------------------------------------------
# Печать SQL
# --------------------------------------------------------------------------

def normalized_literal(text: str) -> str:
    """Литерал для сравнения с нормализованной колонкой."""
    return sql_string(normalize_phrase(text))


def wrap_comment(text: str, width: int = 74) -> list[str]:
    """Длинный текст — в несколько строк комментария."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def render_sql(plan: Plan, generated_on: date | None = None) -> str:
    generated_on = generated_on or date.today()
    out: list[str] = []
    add = out.append

    phrase_total = len(plan.phrases) + len(plan.records)
    to_new = sum(1 for p in plan.phrases if p.to_new_record)
    to_old = len(plan.phrases) - to_new

    add("-- " + "=" * 70)
    add("-- UL-17568, этап 3. Расширение базы знаний виртуального AI-помощника.")
    add("--")
    add("-- Порождён tools/expand_knowledge_base.py " + generated_on.strftime("%d.%m.%Y") + ".")
    add("-- Править руками нельзя: правки затрёт следующая генерация.")
    add("--")
    add("-- Файл в UTF-8 без BOM. Запускать с NLS_LANG=RUSSIAN_CIS.AL32UTF8,")
    add("-- иначе кириллица приедет в справочник мусором.")
    add("--")
    add("-- ЧТО ДОБАВЛЯЕТСЯ")
    add(f"--   сценариев:    {len(plan.scenarios)}")
    add(f"--   тем:          {len(plan.records)}")
    add(
        f"--   формулировок: {phrase_total} — {len(plan.phrases)} в AI_KB_PHRASES"
        f" плюс {len(plan.records)} каноничных в самих темах"
    )
    add(f"--     из них к новым темам:        {to_new}")
    add(f"--     из них к существующим темам: {to_old}")
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
    for record in plan.records:
        add(
            f"--   «{record.question}»"
            f" -> направление {record.telephone_direction_id}, номер приёма"
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

    add("--")
    add("-- Направление годится под перевод по одному признаку: непустой номер приёма")
    add("-- PHONE_FOR_WEB_REQ. Именно его подставляет боевой астербот (обработчик")
    add("-- 13161: redirectExten = telDir[0].PWR). Признак AVAIL_FOR_REDIRECT и поле")
    add("-- EXTEN_FOR_REDIRECT_ID в переводе не участвуют — на них не смотрим.")

    add("--")
    if plan.issues:
        add(f"-- ОСТАЛОСЬ НЕРЕШЁННЫМ, РАЗБИРАЕТ ЧЕЛОВЕК ({len(plan.issues)}):")
        for text in plan.issues:
            lines = wrap_comment(text, 70)
            add("--   " + lines[0])
            for line in lines[1:]:
                add("--     " + line)
    else:
        add("-- Нерешённого нет.")

    if plan.deferred:
        add("--")
        add(f"-- НАПРАВЛЕНИЯ, ОТЛОЖЕННЫЕ ОСОЗНАННО ({len(plan.deferred)}):")
        for text in plan.deferred:
            lines = wrap_comment(text, 70)
            add("--   " + lines[0])
            for line in lines[1:]:
                add("--     " + line)

    if plan.already_present:
        add("--")
        add(
            f"-- УЖЕ БЫЛО В СПРАВОЧНИКЕ, НЕ ДОСЫЛАЕТСЯ ({len(plan.already_present)}):"
        )
        for text in plan.already_present:
            add("--   " + text)

    add("-- " + "=" * 70)
    out.extend(render_body(plan))
    return "\n".join(out)


def render_body(plan: Plan) -> list[str]:
    """Всё после шапки: преамбула, вставки, COMMIT, проверка.

    Вынесено из render_sql, чтобы следующие досылки (sql/12 и дальше) писали
    свою шапку, но не переписывали заново сами INSERT'ы. Экранирование и
    защита от дублей — самая рискованная часть скрипта, у неё должно быть
    одно место и одни тесты.
    """
    out: list[str] = []
    add = out.append

    add("")
    add("SET DEFINE OFF")
    add("WHENEVER SQLERROR EXIT FAILURE ROLLBACK")
    add("")
    add("")
    add("-- Проверка: темы ищутся по тексту вопроса, поэтому вопросы обязаны быть")
    add("-- уникальными. Если это не так — досылать нельзя, формулировки уедут не туда.")
    add("DECLARE")
    add("  v_dups NUMBER;")
    add("BEGIN")
    # В списке выборки намеренно константа, а не то же выражение, что в
    # GROUP BY. Считаем мы строки, само значение не нужно, а повтор выражения
    # хоть и допустим, но подводит: SQL Developer на нём падает с ORA-00979,
    # тогда как SQL*Plus тот же текст исполняет без вопросов. Разбираться,
    # чем именно клиент искажает запрос, дороже, чем убрать повтор.
    add("  SELECT COUNT(*) INTO v_dups FROM (")
    add("    SELECT 1")
    add("      FROM ULTIMA.AI_KNOWLEDGE_BASE")
    add("     GROUP BY " + SQL_NORMALIZE.format("QUESTION"))
    add("    HAVING COUNT(*) > 1")
    add("  );")
    add("  IF v_dups > 0 THEN")
    add("    RAISE_APPLICATION_ERROR(-20002,")
    add("      'В ULTIMA.AI_KNOWLEDGE_BASE есть повторяющиеся вопросы (' || v_dups ||")
    add("      ' шт). Досылка отменена, скрипт ничего не менял.');")
    add("  END IF;")
    add("END;")
    add("/")

    if plan.scenarios:
        add("")
        add("")
        add("-- " + "-" * 70)
        add("-- Сценарии. Тип действия 1 — перевод звонка.")
        add("-- Номер для перевода здесь не хранится: он берётся из направления.")
        add("-- " + "-" * 70)
        for scenario in plan.scenarios:
            add(
                "INSERT INTO ULTIMA.AI_SCENARIOS (ID, NAME, ACTION_TYPE,"
                " TELEPHONE_DIRECTION_ID, NOT_ACTIVE)"
            )
            add(
                "SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_SCENARIOS),"
                f" {sql_string(scenario.name)}, {ACTION_TYPE_REDIRECT},"
                f" {scenario.telephone_direction_id}, 0"
            )
            add("  FROM DUAL")
            add(
                " WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_SCENARIOS"
                f" WHERE TELEPHONE_DIRECTION_ID = {scenario.telephone_direction_id});"
            )
            add("")

    if plan.records:
        add("")
        add("-- " + "-" * 70)
        add("-- Новые темы базы знаний.")
        add("-- " + "-" * 70)
        for record in plan.records:
            add(f"-- {record.question}")
            add(
                "INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION,"
                " POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE)"
            )
            add("SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KNOWLEDGE_BASE),")
            add(f"       {sql_string(record.question)},")
            add(f"       {sql_string(record.clarifying_question)},")
            add(f"       {sql_string(record.positive_reply)},")
            add(
                "       (SELECT MIN(ID) FROM ULTIMA.AI_SCENARIOS"
                f" WHERE TELEPHONE_DIRECTION_ID = {record.telephone_direction_id}),"
            )
            add(f"       {sql_number(record.equipment_type_id)}, 0, 0")
            add("  FROM DUAL")
            add(" WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KNOWLEDGE_BASE")
            add(
                "                     WHERE "
                + SQL_NORMALIZE.format("QUESTION")
                + " = "
                + normalized_literal(record.question)
                + ");"
            )
            add("")

    if plan.phrases:
        add("")
        add("-- " + "-" * 70)
        add("-- Формулировки. Тема ищется по тексту вопроса: если её нет, вставка")
        add("-- просто не найдёт строку и ничего не добавит.")
        add("-- " + "-" * 70)
        current: str | None = None
        for phrase in plan.phrases:
            if phrase.question != current:
                current = phrase.question
                add("")
                add(f"-- тема: {current}")
            add(
                "INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)"
            )
            add(
                "SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID,"
                f" {sql_string(phrase.phrase)}, 0"
            )
            add("  FROM ULTIMA.AI_KNOWLEDGE_BASE k")
            add(
                " WHERE "
                + SQL_NORMALIZE.format("k.QUESTION")
                + " = "
                + normalized_literal(phrase.question)
            )
            add("   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p")
            add("                    WHERE p.KNOWLEDGE_BASE_ID = k.ID")
            add(
                "                      AND "
                + SQL_NORMALIZE.format("p.PHRASE")
                + " = "
                + normalized_literal(phrase.phrase)
                + ");"
            )

    add("")
    add("")
    add("COMMIT;")
    add("")
    add("")
    add("-- " + "-" * 70)
    add("-- Проверка после заливки.")
    add("-- " + "-" * 70)
    add("SELECT (SELECT COUNT(*) FROM ULTIMA.AI_SCENARIOS)      AS SCENARIOS,")
    add("       (SELECT COUNT(*) FROM ULTIMA.AI_KNOWLEDGE_BASE) AS RECORDS,")
    add("       (SELECT COUNT(*) FROM ULTIMA.AI_KB_PHRASES)     AS PHRASES")
    add("  FROM DUAL;")
    add("")

    return out


# --------------------------------------------------------------------------
# Запуск
# --------------------------------------------------------------------------

def report_lines(plan: Plan) -> list[str]:
    lines = [
        f"Сценариев:    {len(plan.scenarios)}",
        f"Тем:          {len(plan.records)}",
        f"Формулировок: {len(plan.phrases)} в AI_KB_PHRASES"
        f" + {len(plan.records)} каноничных",
    ]
    for record in plan.records:
        lines.append(
            f"  тема «{record.question}» -> направление"
            f" {record.telephone_direction_id} (номер {record.phone_for_web_req})"
        )
    if plan.already_present:
        lines.append(f"Уже было, не досылается: {len(plan.already_present)}")
        lines.extend("  " + text for text in plan.already_present)
    if plan.issues:
        lines.append(f"Осталось нерешённым: {len(plan.issues)}")
        lines.extend("  " + text for text in plan.issues)
    if plan.deferred:
        lines.append(f"Отложено осознанно: {len(plan.deferred)}")
        lines.extend("  " + text for text in plan.deferred)
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expansion", type=Path, default=DEFAULT_EXPANSION_PATH)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT_PATH)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE_PATH)
    parser.add_argument(
        "--output", type=Path, default=None, help="куда писать SQL; по умолчанию stdout"
    )
    args = parser.parse_args(argv)

    plan = build_plan(
        load_json(args.expansion),
        load_json(args.snapshot),
        load_json(args.reference),
    )
    sql = render_sql(plan)

    if args.output:
        args.output.write_text(sql, encoding="utf-8", newline="\n")
    else:
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
        sys.stdout.write(sql)

    sys.stderr.reconfigure(encoding="utf-8")
    sys.stderr.write("\n".join(report_lines(plan)) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
