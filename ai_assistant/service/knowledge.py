"""База знаний и поиск похожего по смыслу вопроса.

Поиск делается эмбеддингами, а не LLM: он детерминирован, быстр и ничего не выдумывает.
"""
import json
import os
from dataclasses import asdict, dataclass, field
from typing import List, Optional, Tuple

import numpy as np

# Префиксы нужны моделям семейства E5/RoSBERTa: они обучались различать запрос и документ.
QUERY_PREFIX = "search_query: "
DOCUMENT_PREFIX = "search_document: "


@dataclass
class KnowledgeRecord:
    id: int
    question: str
    clarifying_question: str = ""
    positive_answers: List[str] = field(default_factory=list)
    negative_answers: List[str] = field(default_factory=list)
    positive_reply: str = ""
    scenario: str = ""
    equipment_type: str = ""


class SentenceTransformerEmbedder:
    """Боевая реализация. В юнит-тестах не используется — модель весит сотни мегабайт."""

    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name)

    def encode(self, texts: List[str]) -> np.ndarray:
        return self._model.encode(texts, normalize_embeddings=True)


class KnowledgeBase:
    def __init__(self, records: List[KnowledgeRecord], embedder, threshold: float):
        self._records = list(records)
        self._embedder = embedder
        self._threshold = threshold
        self._vectors = self._encode_questions()

    def _encode_questions(self) -> Optional[np.ndarray]:
        if not self._records:
            return None
        texts = [DOCUMENT_PREFIX + r.question for r in self._records]
        return self._embedder.encode(texts)

    @property
    def records(self) -> List[KnowledgeRecord]:
        return list(self._records)

    def search(self, text: str) -> Optional[Tuple[KnowledgeRecord, float]]:
        if self._vectors is None or not text.strip():
            return None
        query = self._embedder.encode([QUERY_PREFIX + text])[0]
        # Векторы нормированы, поэтому скалярное произведение и есть косинусная близость.
        scores = self._vectors @ query
        best_index = int(np.argmax(scores))
        best_score = float(scores[best_index])
        if best_score < self._threshold:
            return None
        return self._records[best_index], best_score

    def add(self, question: str) -> KnowledgeRecord:
        next_id = max((r.id for r in self._records), default=0) + 1
        record = KnowledgeRecord(id=next_id, question=question)
        self._records.append(record)
        self._vectors = self._encode_questions()
        return record

    def save(self, path: str) -> None:
        payload = [asdict(r) for r in self._records]
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)


def load_knowledge_base(path: str, embedder, threshold: float) -> KnowledgeBase:
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    records = [KnowledgeRecord(**item) for item in payload]
    return KnowledgeBase(records, embedder, threshold)
