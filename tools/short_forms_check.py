# coding=utf8
r"""Короткие формы живой речи по каждой записи базы знаний: находят ли они свою тему.

    py -3.12 tools/short_forms_check.py [--feed ai_assistant/knowledge_feed_cache.json] [--sql out.sql]

Из уточняющего вопроса записи берётся именная группа («ремонт холодильника»,
«услуги электрика», «установка бытовой техники») и к ней примеряются типовые
обёртки клиента. Форма, которая уходит не в свою запись (или никуда), печатается;
с --sql для таких форм генерируется вставка формулировок — дословное совпадение
решает без эмбеддера.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from ai_assistant.service.config import load_config  # noqa: E402
from ai_assistant.service.knowledge import KnowledgeBase, SentenceTransformerEmbedder  # noqa: E402
from ai_assistant.service.knowledge_feed import parse_feed  # noqa: E402
from ai_assistant.service.main import load_corpus_index  # noqa: E402

PREFIXES = ("правильно понимаю, что вас интересует ", "правильно понимаю, что вам нужны ", "правильно понимаю, что вам нужна ",
            "правильно понимаю, что вам нужно ", "правильно понимаю, что вас интересует запись ")
WRAPS = ["{np}", "здравствуйте {np}", "мне нужен {np}", "нужно {np}", "по поводу {np}", "скажите вы занимаетесь {np}",
         "а {np} вы делаете", "здравствуйте скажите пожалуйста {np} делаете", "у меня вопрос по {np}"]


def noun_phrase(question: str) -> str:
    q = re.sub(r"\s+", " ", question.strip().lower()).rstrip("?").strip()
    for p in PREFIXES:
        if q.startswith(p):
            return q[len(p):].strip()
    return ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--feed", default=os.path.join(REPO, "ai_assistant", "knowledge_feed_cache.json"))
    ap.add_argument("--sql", default="")
    args = ap.parse_args()
    cfg = load_config()
    feed = parse_feed(json.load(io.open(args.feed, encoding="utf-8")))
    kb = KnowledgeBase(feed.records, SentenceTransformerEmbedder(cfg.embedder_model), cfg.similarity_threshold,
                       corpus=load_corpus_index(cfg))
    failures = {}
    total = 0
    for record in feed.records:
        np_ = noun_phrase(record.clarifying_question or "")
        if not np_:
            continue
        for wrap in WRAPS:
            text = wrap.format(np=np_)
            total += 1
            res = kb.resolve(text)
            ok = res is not None and res.trusted and res.record is not None and (
                res.record.id == record.id or (res.record.telephone_direction_id == record.telephone_direction_id
                                               and (res.record.clarifying_question or "").lower() == (record.clarifying_question or "").lower()))
            if not ok:
                got = "%s kb%s %.2f" % (res.source, res.record.id, res.score) if res and res.record else (res.source if res else "none")
                failures.setdefault(record.id, []).append((text, got))
                print("kb%-3s %-70r -> %s" % (record.id, text[:68], got))
    print("\nформ проверено %d, мимо %d у %d записей" % (total, sum(len(v) for v in failures.values()), len(failures)))
    if args.sql and failures:
        with io.open(args.sql, "w", encoding="utf-8", newline="\n") as out:
            out.write("-- Короткие формы живой речи, не находящие свою запись (tools/short_forms_check.py)\nSET DEFINE OFF;\n\n")
            for kb_id, items in failures.items():
                phrases = sorted({t for t, _ in items})
                out.write("INSERT INTO ULTIMA.AI_KB_TO_PHRASES (KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)\n"
                          "SELECT %d, v.PHRASE, 0\n  FROM (\n" % kb_id)
                out.write(" UNION ALL\n".join("    SELECT '%s'%s FROM DUAL" % (p.replace("'", "''"), " AS PHRASE" if i == 0 else "")
                                              for i, p in enumerate(phrases)))
                out.write("\n  ) v\n WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_TO_PHRASES p\n"
                          "                    WHERE p.KNOWLEDGE_BASE_ID = %d\n"
                          "                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = v.PHRASE);\n\n" % kb_id)
            out.write("COMMIT;\n")
        print("SQL:", args.sql)


if __name__ == "__main__":
    main()
