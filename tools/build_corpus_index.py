# coding=utf8
r"""Собрать индекс корпуса живых реплик для сервиса (corpus_knn.py).

    py -3.12 tools/build_corpus_index.py [--out ai_assistant/corpus_index.npz]

Берёт реплики из dataset/corpus.jsonl, у которых известен исход звонка,
и превращает их в направление, куда бот должен переводить:
  - повторное обращение (по маркерам: «заявка», «мастер звонил», «сдал в
    ремонт»…) — направление 17 «Сопровождение», то есть оператор;
  - остальные — тип оборудования документа → сценарий бота → его направление
    (сведение то же, что в measure_corpus.py); что не свелось — не берём.
Векторы считаются тем же эмбеддером, что и в сервисе, через кэш
dataset/corpus_emb.npz — после ночного сбора добавляются только новые.

Если есть ручная разметка dataset/manual_labels.tsv (намерение N/R/X, см.
measure_manual.py), по ней учится классификатор намерения и перемечает весь
корпус: повторные — на оператора, не-клиенты (говорит оператор/мастер) — вон
из индекса. Замер 21.09.2026 на 2000 размеченных реплик (2 фолда): без этого
повторные уходили на оператора в 65% случаев, с этим — в 94%; точность
переводов 72% → 87% при ответе на 98% звонков. Порог «повторного» 0.5
(REPEAT_PROB) — выше хуже: 0.65 → 84%, 0.80 → 81%.

Готовый файл кладётся рядом с сервисом (AIA_CORPUS_INDEX_PATH) и подхватывается
при перезапуске. Обновлять после каждой ночи сбора корпуса и после каждой
порции ручной разметки.
"""
from __future__ import annotations

import argparse
import collections
import io
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))

from ai_assistant.service.corpus_knn import OPERATOR_DIRECTION, CorpusIndex  # noqa: E402
from ai_assistant.service.knowledge import content_words  # noqa: E402
from measure_corpus import (  # noqa: E402
    DATASET_DIR, build_equipment_to_scenario, is_repeat, load_examples, load_refs, lower_priority,
    name_to_scenario)
from train_classifier import embeddings_for  # noqa: E402

DEFAULT_OUT = os.path.join(REPO, "ai_assistant", "corpus_index.npz")
MANUAL_LABELS = os.path.join(DATASET_DIR, "manual_labels.tsv")
MANUAL_SAMPLE = os.path.join(DATASET_DIR, "manual_sample.tsv")


def load_manual():
    """Ручная разметка тысячи: uid, реплика, намерение N/R/X, сценарий, «?»."""
    sample = {}
    for line in io.open(MANUAL_SAMPLE, encoding="utf-8"):
        p = line.rstrip("\n").split("\t")
        if p[0].isdigit():
            sample[int(p[0])] = {"uid": p[1], "equipment": p[2], "erp_label": p[3], "phrase": p[4]}
    rows = []
    for line in io.open(MANUAL_LABELS, encoding="utf-8"):
        p = line.rstrip("\n").split("\t")
        if not p[0].isdigit():
            continue
        r = dict(sample[int(p[0])])
        r.update(n=int(p[0]), intent=p[1], scenario=p[2] if len(p) > 2 else "",
                 unsure=(len(p) > 3 and p[3] == "?"))
        rows.append(r)
    return rows


def intent_model(vectors, intents):
    """Классификатор намерения (N/R/X) по ручной разметке — им перемечается корпус."""
    from sklearn.linear_model import LogisticRegression

    model = LogisticRegression(C=2.0, max_iter=3000, class_weight="balanced")
    model.fit(vectors, intents)
    return model


#: Реплика считается повторным обращением, если модель даёт ей такую
#: вероятность. 0.5 — просто «самый вероятный класс».
REPEAT_PROB = 0.5


def relabel(corpus_rows, corpus_vectors, model, repeat_prob=REPEAT_PROB):
    """Направление реплики корпуса с учётом намерения: повторное — оператор,
    не клиент — вон из индекса, новый заказ — по типу оборудования как раньше."""
    proba = model.predict_proba(corpus_vectors)
    classes = list(model.classes_)
    predicted = model.classes_[proba.argmax(axis=1)]
    p_repeat = proba[:, classes.index("R")] if "R" in classes else np.zeros(len(corpus_rows))
    keep, directions = [], []
    for (uid, phrase, direction), intent, pr in zip(corpus_rows, predicted, p_repeat):
        if intent == "X":
            continue
        keep.append((uid, phrase))
        directions.append(OPERATOR_DIRECTION if pr >= repeat_prob else direction)
    return keep, np.array(directions)


def labeled_by_direction():
    et, kb, sc = load_refs()
    mapping, _ = build_equipment_to_scenario(et, kb, sc)
    names, _ = name_to_scenario(et, mapping)
    rows, skipped = [], 0
    for r in load_examples():
        # «Угу здравствуйте», «установка», «они знаешь» — темы не несут, а как
        # соседи тянут любую такую же пустую реплику к оператору (разбор
        # второго этапа теста 24.09.2026). В индекс не берём.
        if len(content_words(r["phrase"])) < 2:
            skipped += 1
            continue
        if is_repeat(r["phrase"]):
            rows.append((r["uid"], r["phrase"], OPERATOR_DIRECTION))
            continue
        sid = names.get(r["equipment"])
        direction = sc[sid]["direction"] if sid is not None else None
        if direction is None:
            skipped += 1
            continue
        rows.append((r["uid"], r["phrase"], direction))
    return rows, skipped, sc


def main():
    lower_priority()
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()

    rows, skipped, sc = labeled_by_direction()
    print("реплик с направлением: %d | без направления пропущено: %d" % (len(rows), skipped), flush=True)
    vectors = embeddings_for(rows)
    if os.path.exists(MANUAL_LABELS):
        manual = load_manual()
        model = intent_model(embeddings_for([(r["uid"], r["phrase"], None) for r in manual]),
                             [r["intent"] for r in manual])
        keep, directions = relabel(rows, vectors, model)
        keep_uids = {uid for uid, _ in keep}
        vectors = vectors[[i for i, (uid, _, _) in enumerate(rows) if uid in keep_uids]]
        print("намерение по ручной разметке (%d реплик): выкинуто не-клиентов %d, повторных теперь %d"
              % (len(manual), len(rows) - len(keep), int((directions == OPERATOR_DIRECTION).sum())), flush=True)
        rows = [(uid, phrase, int(d)) for (uid, phrase), d in zip(keep, directions)]
    CorpusIndex.save(args.out, vectors, [d for _, _, d in rows], [p for _, p, _ in rows], [u for u, _, _ in rows])

    names = {s["direction"]: s["name"] for s in sc.values() if s["direction"] != OPERATOR_DIRECTION}
    names[OPERATOR_DIRECTION] = "Сопровождение (оператор)"
    counts = collections.Counter(d for _, _, d in rows)
    print("записано %s (%.1f МБ)" % (args.out, os.path.getsize(args.out) / 1e6))
    for d, n in counts.most_common():
        print("  %5d  ТН %-3d %s" % (n, d, names.get(d, "?")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
