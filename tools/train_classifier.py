# coding=utf8
r"""Сколько точности можно выжать из корпуса, если решать «куда переводить»
не по рукописным формулировкам, а по классификатору на живых репликах (UL-19020).

    py -3.12 tools/train_classifier.py

Берёт реплики из dataset/corpus.jsonl с меткой сценария (сведение — то же, что в
measure_corpus.py), реплики с признаками повторного обращения кладёт в отдельный
класс «Оператор (повторное)», считает эмбеддинги тем же RoSBERTa, что в сервисе,
и гоняет 5-кратную кросс-валидацию двух простых моделей поверх эмбеддингов:
ближайшие соседи и логистическая регрессия. Печатает, какая точность выходит при
каком покрытии (когда модель не уверена — «молчит», как сейчас при пороге).

Эмбеддинги кэшируются в dataset/corpus_emb.npz — второй запуск за секунды.
"""
from __future__ import annotations

import collections
import datetime as dt
import io
import json
import os
import sys
import time

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))

from measure_corpus import (  # noqa: E402
    DATASET_DIR, build_equipment_to_scenario, is_repeat, load_examples, load_refs,
    lower_priority, name_to_scenario)

EMB_CACHE = os.path.join(DATASET_DIR, "corpus_emb.npz")

# Эксперимент 01.10.2026 (разбор 3-й волны): кодировать только содержательные
# слова реплики — без «здравствуйте», «по поводу», «мне нужен мастер», которые
# у коротких реплик перевешивают тему («по поводу сборки кухни» → соседи
# «по поводу ремонта посудомойки»). Отдельный кэш, чтобы не смешать с обычным.
CONTENT_ONLY = os.environ.get("AIA_EMB_CONTENT_ONLY") == "1"
if CONTENT_ONLY:
    EMB_CACHE = os.path.join(DATASET_DIR, "corpus_emb_content.npz")


def text_for_embedding(phrase):
    """Что именно кодируем: всю реплику или только её содержательные слова."""
    if not CONTENT_ONLY:
        return phrase
    from ai_assistant.service.knowledge import content_words

    words = content_words(phrase)
    return " ".join(words) if words else phrase
OPERATOR_CLASS = "Оператор (повторное)"
MIN_CLASS = 20          # классы меньше — в кросс-валидацию не берём, нечему учиться
FOLDS = 5
COVERAGES = (1.0, 0.9, 0.8, 0.7, 0.6, 0.5)


def labeled_examples():
    et, kb, sc = load_refs()
    mapping, _ = build_equipment_to_scenario(et, kb, sc)
    names, _ = name_to_scenario(et, mapping)
    rows = []
    for r in load_examples():
        if is_repeat(r["phrase"]):
            rows.append((r["uid"], r["phrase"], OPERATOR_CLASS))
            continue
        sid = names.get(r["equipment"])
        if sid is not None:
            rows.append((r["uid"], r["phrase"], sc[sid]["name"]))
    return rows


def embeddings_for(rows):
    """Эмбеддинги реплик; что уже считали — берём из кэша по uid."""
    cached = {}
    if os.path.exists(EMB_CACHE):
        z = np.load(EMB_CACHE, allow_pickle=False)
        cached = dict(zip(z["uids"].tolist(), z["vectors"]))
    missing = [(u, p) for u, p, _ in rows if u not in cached]
    if missing:
        from ai_assistant.service.config import load_config
        from ai_assistant.service.knowledge import QUERY_PREFIX, SentenceTransformerEmbedder

        embedder = SentenceTransformerEmbedder(load_config().embedder_model)
        t0 = time.time()
        for i in range(0, len(missing), 256):
            chunk = missing[i:i + 256]
            vecs = embedder.encode([QUERY_PREFIX + text_for_embedding(p) for _, p in chunk])
            for (u, _), v in zip(chunk, vecs):
                cached[u] = v.astype(np.float32)
            if (i // 256) % 10 == 0:
                print("  эмбеддинги %d/%d" % (min(i + 256, len(missing)), len(missing)), flush=True)
        print("посчитано %d новых за %.0f с" % (len(missing), time.time() - t0), flush=True)
        uids = list(cached)
        np.savez(EMB_CACHE, uids=np.array(uids), vectors=np.stack([cached[u] for u in uids]))
    x = np.stack([cached[u] for u, _, _ in rows])
    x /= np.linalg.norm(x, axis=1, keepdims=True) + 1e-9
    return x


def evaluate(name, predict_proba, x, y, classes):
    """Кросс-валидация: возвращает предсказание и уверенность для каждой реплики."""
    from sklearn.model_selection import StratifiedKFold

    pred = np.empty(len(y), dtype=object)
    conf = np.zeros(len(y))
    for k, (tr, te) in enumerate(StratifiedKFold(FOLDS, shuffle=True, random_state=1).split(x, y)):
        p = predict_proba(x[tr], y[tr], x[te])
        best = p.argmax(axis=1)
        pred[te] = classes[best]
        conf[te] = p[np.arange(len(te)), best]
        print("  %s: фолд %d/%d" % (name, k + 1, FOLDS), flush=True)
    return pred, conf


def knn_proba(k):
    def run(xtr, ytr, xte):
        classes = np.unique(ytr)
        idx = {c: i for i, c in enumerate(classes)}
        out = np.zeros((len(xte), len(classes)))
        for i in range(0, len(xte), 512):
            s = xte[i:i + 512] @ xtr.T
            top = np.argpartition(-s, k, axis=1)[:, :k]
            for row, cols in enumerate(top):
                for j in cols:
                    out[i + row, idx[ytr[j]]] += max(s[row, j], 0.0) ** 4  # ближние весят сильнее
        out /= out.sum(axis=1, keepdims=True) + 1e-9
        return out
    return run


def logreg_proba(xtr, ytr, xte):
    from sklearn.linear_model import LogisticRegression

    model = LogisticRegression(C=4.0, max_iter=3000, class_weight="balanced")
    model.fit(xtr, ytr)
    p = model.predict_proba(xte)
    # столбцы — в порядке model.classes_, он совпадает с np.unique(ytr)
    return p


def report(name, pred, conf, y, classes_all):
    lines = ["", "%s" % name, "  покрытие   точность   порог уверенности   (верно / ответил)"]
    order = np.argsort(-conf)
    for cov in COVERAGES:
        n = int(len(y) * cov)
        sel = order[:n]
        correct = int((pred[sel] == y[sel]).sum())
        lines.append("   %4.0f%%     %5.1f%%        %.2f            (%d / %d)" % (
            100 * cov, 100 * correct / max(1, n), conf[sel[-1]] if n else 0, correct, n))
    # по классам — при покрытии 80%
    n = int(len(y) * 0.8)
    sel = set(order[:n].tolist())
    per = collections.defaultdict(lambda: [0, 0, 0])  # всего, ответил, верно
    for i in range(len(y)):
        p = per[y[i]]
        p[0] += 1
        if i in sel:
            p[1] += 1
            p[2] += int(pred[i] == y[i])
    lines.append("  по классам при покрытии 80%%: всего / ответил / верно из ответивших")
    for c, (tot, ans, ok) in sorted(per.items(), key=lambda kv: -kv[1][0]):
        lines.append("    %-34s %5d  %4.0f%%  %4.0f%%" % (c[:34], tot, 100 * ans / tot, 100 * ok / max(1, ans)))
    confusion = collections.Counter((y[i], pred[i]) for i in sel if pred[i] != y[i])
    lines.append("  путает чаще всего:")
    for (a, b), v in confusion.most_common(8):
        lines.append("    %4d  %-28s -> %s" % (v, a[:28], b[:28]))
    return lines


def main():
    lower_priority()
    started = time.time()
    rows = labeled_examples()
    counts = collections.Counter(c for _, _, c in rows)
    rows = [r for r in rows if counts[r[2]] >= MIN_CLASS]
    print("реплик: %d | классов (>= %d): %d" % (len(rows), MIN_CLASS, len(set(c for _, _, c in rows))), flush=True)

    x = embeddings_for(rows)
    y = np.array([c for _, _, c in rows], dtype=object)
    classes = np.unique(y)

    out = ["КРОСС-ВАЛИДАЦИЯ %s" % dt.datetime.now().isoformat(timespec="seconds"),
           "реплик %d, классов %d, %d фолдов; класс «%s» — по маркерам повторного обращения"
           % (len(rows), len(classes), FOLDS, OPERATOR_CLASS),
           "для сравнения: нынешняя база (660 формулировок) — точность ~77%% при покрытии ~70%%"]
    for name, fn in (("kNN (15 соседей, косинус)", knn_proba(15)),
                     ("Логистическая регрессия", logreg_proba)):
        pred, conf = evaluate(name, fn, x, y, classes)
        out += report(name, pred, conf, y, classes)
    out.append("")
    out.append("время: %.0f с" % (time.time() - started))
    text = "\n".join(out)
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M")
    io.open(os.path.join(DATASET_DIR, "classifier_cv_%s.txt" % stamp), "w", encoding="utf-8").write(text)
    print(text, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
