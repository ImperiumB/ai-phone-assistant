"""Ярус намерения: новый это заказ, повторное обращение или вообще не клиент.

Зачем отдельный ярус. Повторное обращение («мне мастер звонил», «я у вас
заказывал в пятницу») должно уходить к человеку без уточняющего вопроса про
прибор: спрашивать «правильно понимаю, ремонт стиральной машины?» у человека,
который звонит по уже оформленному заказу, бессмысленно. До 07.11.2026 это
решал корпус живых реплик, и он промахивался: замер линейкой на 4000
размеченных реплик дал 181 повторную реплику с вопросом про прибор, из них 112
по решению корпуса (64 с уверенностью ниже 0,70) и 36 через гейты категорий.
Рядом жил хрупкий список слов-маркеров (knowledge.REPEAT_MARKERS), который на
той же области давал 26 исправлений ценой 4 поломок.

Модель это логистическая регрессия поверх того же эмбеддинга, который сервис
уже считает для корпуса и формулировок, поэтому ярус не добавляет ни одного
обращения к нейросети: одно умножение матрицы 3 на 1024, десятые доли
миллисекунды. Обучение и выбор порога в tools/train_intent.py; кросс-валидация
на 5 фолдах при пороге 0,70 даёт точность отбора повторных 98,4 % при полноте
71,6 %, то есть из 1795 отобранных реплик только 29 оказались не повторными.

Формат модели это JSON с коэффициентами, а не pickle: читается без sklearn, не
ломается от смены версии библиотеки и виден глазами.
"""
import io
import json
import logging
import os
from typing import List, Optional

import numpy as np

log = logging.getLogger("aia")

#: Класс «повторное обращение» в разметке (N новый заказ, R повторное,
#: X не реплика клиента).
REPEAT_CLASS = "R"


class IntentModel:
    """Вероятности намерения по вектору реплики."""

    def __init__(self, classes: List[str], coef: np.ndarray, intercept: np.ndarray,
                 embedder: str = "", trained_at: str = "", source: str = ""):
        self.classes = list(classes)
        self._coef = np.asarray(coef, dtype=np.float32)
        self._intercept = np.asarray(intercept, dtype=np.float32)
        self.embedder = embedder
        self.trained_at = trained_at
        self.source = source
        if self._coef.ndim != 2 or self._coef.shape[0] != len(self.classes):
            raise ValueError("коэффициенты модели намерения не совпадают с числом классов")
        if self._intercept.shape[0] != len(self.classes):
            raise ValueError("смещения модели намерения не совпадают с числом классов")

    @property
    def dim(self) -> int:
        return int(self._coef.shape[1])

    def probabilities(self, vector: np.ndarray) -> np.ndarray:
        """Softmax по классам. Порядок тот же, что в self.classes."""
        scores = self._coef.dot(np.asarray(vector, dtype=np.float32)) + self._intercept
        scores = scores - scores.max()
        weights = np.exp(scores)
        return weights / weights.sum()

    def repeat_probability(self, vector: np.ndarray) -> float:
        """Вероятность того, что реплика это повторное обращение."""
        if REPEAT_CLASS not in self.classes:
            return 0.0
        return float(self.probabilities(vector)[self.classes.index(REPEAT_CLASS)])


def load_intent_model(path: str, expected_dim: Optional[int] = None,
                      expected_embedder: str = "") -> Optional[IntentModel]:
    """Модель намерения с диска; None, если файла нет или он не читается.

    Отсутствие файла это не ошибка, а обычное состояние установки, где ярус не
    используется: модель обучается отдельно (tools/train_intent.py) и кладётся
    рядом с сервисом. Любая беда с файлом тоже не должна мешать принимать
    звонки, поэтому ошибки логируются и возвращается None: сервис продолжит
    работать так, как работал до яруса.
    """
    if not path:
        return None
    if not os.path.exists(path):
        log.info("Ярус намерения не подключён: файла %s нет", path)
        return None
    try:
        with io.open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        model = IntentModel(
            classes=payload["classes"],
            coef=payload["coef"],
            intercept=payload["intercept"],
            embedder=payload.get("embedder", ""),
            trained_at=payload.get("trained_at", ""),
            source=path,
        )
    except Exception:
        log.exception("Модель намерения %s не читается, ярус выключен", path)
        return None
    if expected_dim is not None and model.dim != expected_dim:
        log.error("Модель намерения обучена на векторах длины %d, а эмбеддер даёт %d: ярус выключен",
                  model.dim, expected_dim)
        return None
    if expected_embedder and model.embedder and model.embedder != expected_embedder:
        # Не отказ: имя модели эмбеддера могли поменять местами или дописать
        # ревизию. Но знать об этом надо, потому что векторы разных эмбеддеров
        # несравнимы, и ярус начнёт отбирать не то.
        log.warning("Модель намерения обучена на эмбеддере %s, а сервис работает на %s",
                    model.embedder, expected_embedder)
    log.info("Ярус намерения: %s, классы %s, обучена %s", path, model.classes, model.trained_at or "неизвестно")
    return model
