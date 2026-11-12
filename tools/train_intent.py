# coding=utf8
r"""Обучить и сохранить классификатор намерения реплики (новый заказ / повторное / не клиент).

    set OMP_NUM_THREADS=4 & set MKL_NUM_THREADS=4
    py -3.12 tools/train_intent.py [--out ai_assistant/intent_model.json] [--folds 5]

Зачем. Повторное обращение («мне мастер звонил», «я у вас заказывал») должно
уходить к человеку без уточняющего вопроса про прибор. Сейчас это решает корпус,
и он ошибается: по замеру линейкой 181 повторная реплика из 2469 получает вопрос
про прибор, из них 112 по решению корпуса (64 из них с уверенностью ниже 0,70) и
36 через гейты категорий. Отдельно есть хрупкий список слов-маркеров
(knowledge.REPEAT_MARKERS), который ломает соседние случаи.

Классификатор намерения в проекте уже был, но только офлайн: им перемечается
корпус при сборке индекса (build_corpus_index.intent_model и relabel). Этот
скрипт обучает ту же модель на той же ручной разметке и СОХРАНЯЕТ её, чтобы
сервис мог спросить вероятность повторного обращения прямо на звонке за
десятые доли миллисекунды.

Что на входе. dataset/manual_labels.tsv: 4000 реплик живых звонков, размеченных
вручную по намерению (N новый заказ, R повторное обращение, X не реплика
клиента). Эмбеддинги берутся из кэша dataset/corpus_emb.npz тем же способом, что
в tools/train_classifier.py, то есть модель учится ровно на тех векторах, с
которыми работает сервис.

Что на выходе. JSON с коэффициентами логистической регрессии (веса, смещения,
список классов), версиями sklearn и numpy, именем модели эмбеддера и отчётом
кросс-валидации. JSON, а не pickle: файл читается сервисом без sklearn, его
видно глазами, и он не ломается от смены версии библиотеки. Предсказание это
одно умножение матрицы на вектор, оно живёт в ai_assistant/service/intent.py.

Печатает кросс-валидацию по фолдам: точность и полноту класса «повторное» при
разных порогах, чтобы порог в сервисе выбирался по замеру, а не на глаз.
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from build_corpus_index import load_manual  # noqa: E402
from train_classifier import embeddings_for  # noqa: E402


def wilson(k: int, n: int) -> str:
    """Интервал Уилсона 95 % в процентах; без него доли на малых классах обманывают."""
    if n == 0:
        return "нет данных"
    p = k / n
    z = 1.96
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return "%.1f %% [%.1f; %.1f]" % (100 * p, 100 * max(0.0, centre - half), 100 * min(1.0, centre + half))


def fit(vectors: np.ndarray, intents: list):
    from sklearn.linear_model import LogisticRegression

    # Те же параметры, что у офлайн-перемечивания корпуса
    # (build_corpus_index.intent_model): class_weight="balanced" обязателен,
    # классы перекошены (в разметке 62 % повторных против 17 % не клиентов).
    model = LogisticRegression(C=2.0, max_iter=3000, class_weight="balanced")
    model.fit(vectors, intents)
    return model


def cross_validate(vectors: np.ndarray, intents: np.ndarray, folds: int) -> list:
    """Точность и полнота класса «повторное» по порогам, честно вне фолда."""
    from sklearn.model_selection import StratifiedKFold

    lines = []
    # random_state тот же, что в measure_live и build_corpus_index: фолды
    # должны совпадать между инструментами, иначе цифры несравнимы.
    # random_state=7 тот же, что в build_corpus_index и measure_live, но число
    # фолдов здесь другое (5 против 2): цифры кросс-валидации и цифры линейки
    # считаются на разных разбиениях и сравнивать их напрямую нельзя.
    splitter = StratifiedKFold(n_splits=folds, shuffle=True, random_state=7)
    thresholds = (0.50, 0.60, 0.70, 0.80, 0.90)
    hits = {t: [0, 0, 0] for t in thresholds}  # верно R, всего предсказано R, всего R
    for train_idx, test_idx in splitter.split(vectors, intents):
        model = fit(vectors[train_idx], list(intents[train_idx]))
        classes = list(model.classes_)
        if "R" not in classes:
            continue
        p_repeat = model.predict_proba(vectors[test_idx])[:, classes.index("R")]
        truth = intents[test_idx]
        for t in thresholds:
            picked = p_repeat >= t
            hits[t][0] += int(((truth == "R") & picked).sum())
            hits[t][1] += int(picked.sum())
            hits[t][2] += int((truth == "R").sum())
    for t in thresholds:
        correct, picked, total = hits[t]
        lines.append(
            "порог %.2f: отобрано %d, из них повторных %s, полнота %s"
            % (t, picked, wilson(correct, picked), wilson(correct, total))
        )
    return lines


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join("ai_assistant", "intent_model.json"))
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--embedder", default=os.environ.get("AIA_EMBEDDER_MODEL", "ai-forever/ru-en-RoSBERTa"))
    args = ap.parse_args()

    rows = load_manual()
    print("реплик в разметке: %d" % len(rows))
    # embeddings_for ждёт кортежи (uid, текст, метка), как в measure_manual:
    # метка ему не нужна, он только берёт вектор из кэша по uid.
    vectors = embeddings_for([(r["uid"], r["phrase"], None) for r in rows])
    intents = np.array([r["intent"] for r in rows])
    counts = {k: int((intents == k).sum()) for k in sorted(set(intents))}
    print("намерения: %s" % counts)

    print("кросс-валидация на %d фолдах:" % args.folds)
    report = cross_validate(vectors, intents, args.folds)
    for line in report:
        print("   " + line)

    model = fit(vectors, list(intents))
    import sklearn

    payload = {
        "kind": "intent-logreg",
        "trained_at": dt.datetime.now().isoformat(timespec="seconds"),
        "classes": [str(c) for c in model.classes_],
        "coef": [[float(x) for x in row] for row in model.coef_],
        "intercept": [float(x) for x in model.intercept_],
        "dim": int(model.coef_.shape[1]),
        "embedder": args.embedder,
        # Чем кодировался текст: целиком или только содержательными словами
        # (AIA_EMB_CONTENT_ONLY в tools/train_classifier.py). Модель, обученная
        # на одном варианте и применённая к другому, даёт мусорные вероятности,
        # а по файлу этого было не видно.
        "content_only": bool(os.environ.get("AIA_EMB_CONTENT_ONLY") == "1"),
        "sklearn": sklearn.__version__,
        "numpy": np.__version__,
        "rows": len(rows),
        "intent_counts": counts,
        "cv": report,
    }
    out = args.out if os.path.isabs(args.out) else os.path.join(ROOT, args.out)
    with io.open(out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=1)
    print("модель записана: %s (%.0f КБ)" % (out, os.path.getsize(out) / 1024.0))
    print("классы: %s, размерность: %d" % (payload["classes"], payload["dim"]))


if __name__ == "__main__":
    main()
