"""Второе мнение по живым репликам: k ближайших соседей по корпусу звонков.

База формулировок (knowledge.py) отвечает по одной ближайшей рукописной
фразе из нескольких сотен. Корпус — это тысячи реплик реальных клиентов с
известным исходом звонка (направление, куда его в итоге отдал оператор).
Для новой реплики берём k самых близких реплик корпуса и смотрим, куда ушли
они: если соседи в основном об одном — это и есть ответ.

Кросс-валидация 20.09.2026 на 13 691 реплике (tools/train_classifier.py):
при уверенности >= 0.60 верно 90% (бот берёт 60% звонков), при >= 0.51 —
85% на 70% звонков. База формулировок на тех же репликах — 77% при 70%.

Индекс собирается заранее (tools/build_corpus_index.py) и лежит рядом с
сервисом файлом .npz: векторы реплик тем же эмбеддером, что и в поиске по
формулировкам, код направления и сама реплика — чтобы по любому решению можно
было показать, из-за каких соседей оно принято.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np

#: Направление «Сопровождение (redirect)» — туда уходят повторные обращения
#: по уже оформленному заказу. В индексе это отдельный класс.
OPERATOR_DIRECTION = 17

#: Сколько соседей голосует. 15 — по кросс-валидации, меньше шумит, больше
#: размывает редкие направления.
DEFAULT_K = 15
#: Доля голосов победителя, начиная с которой решению верят (обоснование
#: цифры — в config.py, там же переменная окружения).
DEFAULT_THRESHOLD = 0.50
#: Для перевода на оператора без вопроса — порог выше: цена ошибки другая.
DEFAULT_OPERATOR_THRESHOLD = 0.72
#: Меньше содержательных слов в реплике — корпус не голосует, бот переспрашивает.
DEFAULT_MIN_WORDS = 2
#: Близость возводится в эту степень: сосед на 0.9 весит в 2.5 раза больше
#: соседа на 0.7, а не на четверть. Далёкие соседи почти не голосуют.
WEIGHT_POWER = 4


@dataclass
class Neighbour:
    phrase: str
    direction_id: int
    score: float


@dataclass
class Vote:
    direction_id: int
    #: Взвешенная доля голосов за победителя, 0..1.
    confidence: float
    #: Соседи по убыванию близости — для лога и разбора звонка.
    neighbours: List[Neighbour]


class CorpusIndex:
    def __init__(self, vectors, directions, phrases, k: int = DEFAULT_K,
                 threshold: float = DEFAULT_THRESHOLD,
                 operator_threshold: float = DEFAULT_OPERATOR_THRESHOLD,
                 min_words: int = DEFAULT_MIN_WORDS):
        vectors = np.asarray(vectors, dtype=np.float32)
        if vectors.ndim != 2:
            vectors = vectors.reshape(0, 0)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True) if len(vectors) else None
        self._vectors = vectors / np.maximum(norms, 1e-9) if len(vectors) else vectors
        self._directions = np.asarray(directions, dtype=np.int64)
        self._phrases = [str(p) for p in phrases]
        if not (len(self._vectors) == len(self._directions) == len(self._phrases)):
            raise ValueError("индекс корпуса рассыпался: %d векторов, %d направлений, %d реплик"
                             % (len(self._vectors), len(self._directions), len(self._phrases)))
        self.k = int(k)
        self.threshold = float(threshold)
        self.operator_threshold = float(operator_threshold)
        self.min_words = int(min_words)

    def __len__(self) -> int:
        return len(self._phrases)

    @property
    def directions(self) -> np.ndarray:
        return self._directions

    @classmethod
    def load(cls, path: str, k: int = DEFAULT_K, threshold: float = DEFAULT_THRESHOLD,
             operator_threshold: float = DEFAULT_OPERATOR_THRESHOLD,
             min_words: int = DEFAULT_MIN_WORDS) -> "CorpusIndex":
        with np.load(path, allow_pickle=False) as payload:
            return cls(payload["vectors"], payload["directions"], payload["phrases"], k, threshold,
                       operator_threshold, min_words)

    @staticmethod
    def save(path: str, vectors, directions, phrases, uids) -> None:
        np.savez(path, vectors=np.asarray(vectors, dtype=np.float32),
                 directions=np.asarray(directions, dtype=np.int64),
                 phrases=np.asarray(list(phrases), dtype=str),
                 uids=np.asarray(list(uids), dtype=str))

    def vote(self, query: np.ndarray) -> Optional[Vote]:
        """Куда голосуют соседи реплики. query — нормированный вектор запроса."""
        if not len(self):
            return None
        scores = self._vectors @ np.asarray(query, dtype=np.float32)
        k = min(self.k, len(scores))
        top = np.argpartition(-scores, k - 1)[:k]
        top = top[np.argsort(-scores[top])]
        weights = {}
        for j in top:
            weight = max(float(scores[j]), 0.0) ** WEIGHT_POWER
            direction = int(self._directions[j])
            weights[direction] = weights.get(direction, 0.0) + weight
        total = sum(weights.values())
        if total <= 0.0:
            return None
        best = max(weights, key=weights.get)
        neighbours = [Neighbour(self._phrases[j], int(self._directions[j]), float(scores[j])) for j in top]
        return Vote(best, weights[best] / total, neighbours)
