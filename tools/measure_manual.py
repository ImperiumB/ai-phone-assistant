# coding=utf8
r"""Замер бота на вручную размеченной тысяче реплик (dataset/manual_labels.tsv).

    py -3.12 tools/measure_manual.py [--corpus-threshold 0.50] [--rehome 33:35]

Разметка — по намерению, а не по типу оборудования документа:
  N  новый заказ, колонка scenario — куда его вести;
  R  повторное обращение по уже оформленному заказу — должно уйти на оператора;
  X  не реплика клиента (говорит оператор/мастер), обрывок, не наш профиль.
«?» в note — разметчик не уверен; строгий счёт такие строки не учитывает.

Корпус для соседей строится без реплик из тысячи — иначе реплика нашла бы саму
себя. Считаются два варианта: как сервис решает сейчас (корпус + формулировки)
и как решал до корпуса (только формулировки).
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import io
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))

from ai_assistant.service.corpus_knn import OPERATOR_DIRECTION, CorpusIndex  # noqa: E402
from ai_assistant.service.knowledge import content_words  # noqa: E402
from build_corpus_index import intent_model, labeled_by_direction, load_manual, relabel  # noqa: E402
from measure_corpus import (  # noqa: E402
    DATASET_DIR, OPERATOR_SCENARIOS, load_records_from_db_export, load_refs, lower_priority)
from train_classifier import embeddings_for  # noqa: E402


def judge(intent, want, answer_name, trusted):
    """Один вердикт на реплику."""
    if not trusted:
        return "молчит"
    if intent == "R":
        return "верно (оператор)" if answer_name in OPERATOR_SCENARIOS else "не туда (вопрос не по делу)"
    if intent == "N":
        if answer_name == want:
            return "верно (сценарий)"
        if answer_name in OPERATOR_SCENARIOS:
            return "на оператора (мягкий промах)"
        return "не туда"
    return "ответил"  # X: не клиент — любой ответ тут лишний, но и не ошибка маршрутизации


def run(knowledge, vectors, rows, record_scenario, sc, title, strict):
    tally = collections.defaultdict(collections.Counter)
    confusion = collections.Counter()
    for r, vec in zip(rows, vectors):
        if strict and r["unsure"]:
            continue
        res = knowledge.resolve_vector(vec, content_words=len(content_words(r["phrase"])))
        trusted = res is not None and res.trusted and res.record is not None
        answer = sc.get(record_scenario.get(res.record.id), {}).get("name") if trusted else None
        verdict = judge(r["intent"], r["scenario"], answer, trusted)
        tally[r["intent"]][verdict] += 1
        if verdict.startswith("не туда"):
            confusion[(r["intent"], r["scenario"] or "повторное", answer)] += 1
    out = ["", "== %s%s ==" % (title, " (строго: без «?»)" if strict else "")]
    for intent, name in (("N", "новый заказ"), ("R", "повторное обращение"), ("X", "не клиент / мимо")):
        total = sum(tally[intent].values())
        out.append("  %s — %d реплик:" % (name, total))
        for verdict, v in tally[intent].most_common():
            out.append("      %-32s %4d  %5.1f%%" % (verdict, v, 100 * v / max(1, total)))
    n_total = sum(tally["N"].values()) + sum(tally["R"].values())
    answered = sum(v for i in ("N", "R") for k, v in tally[i].items() if k != "молчит")
    right = tally["N"]["верно (сценарий)"] + tally["R"]["верно (оператор)"]
    soft = tally["N"]["на оператора (мягкий промах)"]
    wrong = answered - right - soft
    out.append("  ИТОГ по клиентским (N+R, %d): ответил %.1f%%, из ответивших верно %.1f%% "
               "(+%.1f%% мягких на оператора), не туда %.1f%%"
               % (n_total, 100 * answered / n_total, 100 * right / max(1, answered),
                  100 * soft / max(1, answered), 100 * wrong / max(1, answered)))
    if confusion:
        out.append("  не туда чаще всего:")
        for (intent, want, got), v in confusion.most_common(8):
            out.append("      %3d  %s: %s -> %s" % (v, intent, want[:26], (got or "?")[:26]))
    return out, tally


def run_relabeled(rows, test_vectors, corpus_rows, corpus_vectors, knowledge, record_scenario, sc, args):
    """Два фолда: намерение учится на одной половине тысячи, корпус перемечается
    этой моделью, бот проверяется на другой половине — реплика ни разу не видит
    свою же разметку."""
    from sklearn.model_selection import StratifiedKFold

    intents = np.array([r["intent"] for r in rows])
    out = []
    merged = collections.Counter()
    for train, test in StratifiedKFold(2, shuffle=True, random_state=7).split(test_vectors, intents):
        model = intent_model(test_vectors[train], intents[train])
        keep, directions = relabel(corpus_rows, corpus_vectors, model, args.repeat_prob)
        keep_idx = {uid for uid, _ in keep}
        vecs = corpus_vectors[[i for i, (uid, _, _) in enumerate(corpus_rows) if uid in keep_idx]]
        index = CorpusIndex(vecs, directions, [p for _, p in keep], k=args.corpus_k, threshold=args.corpus_threshold,
                            operator_threshold=args.operator_threshold, min_words=args.min_words)
        knowledge._corpus = index
        merged["выкинуто как не-клиент"] += len(corpus_rows) - len(keep)
        merged["повторных в индексе"] += int((directions == OPERATOR_DIRECTION).sum())
        _, part = run(knowledge, test_vectors[test], [rows[i] for i in test], record_scenario, sc, "фолд", False)
        out.append(part)
    knowledge._corpus = None
    # Складываем два фолда в один отчёт: те же вердикты, суммы по всем репликам.
    names = {"N": "новый заказ", "R": "повторное обращение", "X": "не клиент / мимо"}
    tally = collections.defaultdict(collections.Counter)
    for part in out:
        for intent, counter in part.items():
            tally[names[intent]].update(counter)
    lines = ["", "== корпус, перемеченный по намерению (2 фолда, порог повторного %.2f) ==" % args.repeat_prob,
             "  из индекса выкинуто как не-клиент: %d, повторных теперь: %d (в среднем по фолдам)"
             % (merged["выкинуто как не-клиент"] // 2, merged["повторных в индексе"] // 2)]
    right = soft = answered = n_total = 0
    for intent in ("новый заказ", "повторное обращение", "не клиент / мимо"):
        total = sum(tally[intent].values())
        lines.append("  %s — %d реплик:" % (intent, total))
        for verdict, v in tally[intent].most_common():
            lines.append("      %-32s %4d  %5.1f%%" % (verdict, v, 100 * v / max(1, total)))
        if intent != "не клиент / мимо":
            n_total += total
            answered += sum(v for k, v in tally[intent].items() if k != "молчит")
            right += tally[intent]["верно (сценарий)"] + tally[intent]["верно (оператор)"]
            soft += tally[intent]["на оператора (мягкий промах)"]
    lines.append("  ИТОГ по клиентским (N+R, %d): ответил %.1f%%, из ответивших верно %.1f%% "
                 "(+%.1f%% мягких на оператора), не туда %.1f%%"
                 % (n_total, 100 * answered / n_total, 100 * right / max(1, answered),
                    100 * soft / max(1, answered), 100 * (answered - right - soft) / max(1, answered)))
    return lines


def main():
    lower_priority()
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus-threshold", type=float, default=0.50)
    ap.add_argument("--corpus-k", type=int, default=15)
    ap.add_argument("--operator-threshold", type=float, default=0.72)
    ap.add_argument("--min-words", type=int, default=2)
    ap.add_argument("--rehome", default="33:35")
    ap.add_argument("--repeat-prob", type=float, default=0.5,
                    help="вероятность «повторное», от которой реплика корпуса уходит на оператора")
    ap.add_argument("--relabel", action="store_true",
                    help="перемечать корпус классификатором намерения, обученным на ручной тысяче (2 фолда)")
    args = ap.parse_args()
    rehome = {int(a): int(b) for a, b in (x.split(":") for x in args.rehome.split(",") if x.strip())}

    rows = load_manual()
    test_uids = {r["uid"] for r in rows}
    et, kb, sc = load_refs()
    corpus_rows, _, _ = labeled_by_direction()
    corpus_rows = [r for r in corpus_rows if r[0] not in test_uids]
    corpus_vectors = embeddings_for(corpus_rows)
    test_vectors = embeddings_for([(r["uid"], r["phrase"], None) for r in rows])
    index = CorpusIndex(corpus_vectors, [d for _, _, d in corpus_rows], [p for _, p, _ in corpus_rows],
                        k=args.corpus_k, threshold=args.corpus_threshold,
                        operator_threshold=args.operator_threshold, min_words=args.min_words)

    from ai_assistant.service.config import load_config
    from ai_assistant.service.knowledge import KnowledgeBase, SentenceTransformerEmbedder

    cfg = load_config()
    records, record_scenario = load_records_from_db_export(
        os.path.join(DATASET_DIR, "kb_now.tsv"), os.path.join(DATASET_DIR, "kb_phrases_now.tsv"), sc, set(), rehome)
    knowledge = KnowledgeBase(records, SentenceTransformerEmbedder(cfg.embedder_model), cfg.similarity_threshold)

    counts = collections.Counter(r["intent"] for r in rows)
    out = ["РУЧНАЯ ТЫСЯЧА %s" % dt.datetime.now().isoformat(timespec="seconds"),
           "разметка: N %d, R %d, X %d, с «?» %d | корпус без тысячи: %d реплик, k=%d, порог %.2f | пересажены %s"
           % (counts["N"], counts["R"], counts["X"], sum(r["unsure"] for r in rows), len(index),
              args.corpus_k, args.corpus_threshold, rehome)]
    for strict in (False, True):
        knowledge._corpus = index
        out += run(knowledge, test_vectors, rows, record_scenario, sc, "корпус + формулировки", strict)[0]
        knowledge._corpus = None
        out += run(knowledge, test_vectors, rows, record_scenario, sc, "только формулировки", strict)[0]
    if args.relabel:
        out += run_relabeled(rows, test_vectors, corpus_rows, corpus_vectors, knowledge, record_scenario, sc, args)
    text = "\n".join(out)
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M")
    io.open(os.path.join(DATASET_DIR, "measure_manual_%s.txt" % stamp), "w", encoding="utf-8").write(text)
    print(text, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
