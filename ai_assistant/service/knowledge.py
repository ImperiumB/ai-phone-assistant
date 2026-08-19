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
    #: Как ту же проблему называют живые люди. Все варианты попадают в поиск
    #: наравне с основным вопросом — именно они позволяют держать порог
    #: близости высоким, не отсекая нормальную речь.
    question_variants: List[str] = field(default_factory=list)
    clarifying_question: str = ""
    positive_answers: List[str] = field(default_factory=list)
    negative_answers: List[str] = field(default_factory=list)
    positive_reply: str = ""
    scenario: str = ""
    equipment_type: str = ""
    #: Код записи справочника «Типы оборудования» (ULTIMA.EQUIPMENT_TYPES).
    #: Приходит вместе с базой знаний из ERP. Пока его не было, обработчик,
    #: заводящий обращение по звонку, искал тип оборудования по названию
    #: строкой — с приходом кода поиск по названию отмирает.
    equipment_type_id: int = 0
    #: Код записи справочника «Телефонные направления» (ULTIMA.TELEPHONE_DIRECTIONS).
    telephone_direction_id: int = 0
    #: Номер для приёма переведённого звонка, поле «Номер для приёма
    #: переведённого звонка» того же справочника. Бот переводит именно туда,
    #: а не в захардкоженные отделы: у каждого направления свой приёмник.
    redirect_exten: str = ""
    #: Второй номер того же направления — «Номер для приёма переведённого
    #: звонка для ЧМ». На него уходят звонки с линий частных мастеров: у
    #: направления «ТВ» обычный номер 7048, а для ЧМ 7040 — и 7040 это обычный
    #: номер направления «ЧМ_ТВ», то есть одна и та же тема ведёт частного
    #: мастера в его собственный отдел. Пусто — отдела частных мастеров у
    #: направления нет, и такой звонок уходит на сопровождение.
    redirect_exten_pm: str = ""


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
        # Записи без заполненного уточняющего вопроса — это ещё не
        # размеченные человеком неопознанные реплики (см. add() ниже и
        # финальное ревью): раньше они сразу переиндексировались и начинали
        # участвовать в поиске для следующих реплик и следующих звонков.
        # Ветка обработки отвечает на пустую clarifying_question мгновенным
        # переводом, поэтому дословное совпадение с такой записью на втором
        # движке (та же ошибка распознавания на тех же словах) давало
        # "нашли" без уточняющего вопроса вместо честного промаха — а два
        # движка сравниваются именно на одинаковом материале, и база под
        # ними внезапно становилась разной. self._searchable_records —
        # подмножество self._records, которое реально участвует в поиске;
        # self._records целиком используется только для save() (человек
        # потом вручную заполнит уточняющие вопросы и перезапустит сервис).
        self._searchable_records = self._searchable()
        # В индекс попадает не одна формулировка на запись, а все её варианты:
        # основной вопрос плюс question_variants. Живая речь разнообразна
        # ("стиралка машинка сломалась", "не крутит бельё", "воду не сливает"),
        # и одна каноничная формулировка от них далека — замер 14.08.2026 дал
        # по правильным попаданиям разброс 0.618-0.832, то есть половина живых
        # фраз не дотягивала до разумного порога. Синонимы поднимают близость
        # к своей записи, не трогая близость к чужим, поэтому порог можно
        # держать высоким, а не опускать до уровня, где начинают пролезать
        # посторонние вопросы.
        self._phrases, self._phrase_owners = self._collect_phrases(self._searchable_records)
        self._vectors = self._encode_phrases(self._phrases)

    def _searchable(self) -> List[KnowledgeRecord]:
        return [r for r in self._records if r.clarifying_question]

    @staticmethod
    def _collect_phrases(
        records: List[KnowledgeRecord],
    ) -> Tuple[List[str], List[KnowledgeRecord]]:
        """Все формулировки всех записей и владелец каждой формулировки."""
        phrases: List[str] = []
        owners: List[KnowledgeRecord] = []
        for record in records:
            for phrase in [record.question] + list(record.question_variants):
                phrase = phrase.strip()
                if not phrase:
                    continue
                phrases.append(phrase)
                owners.append(record)
        return phrases, owners

    def _encode_phrases(self, phrases: List[str]) -> Optional[np.ndarray]:
        if not phrases:
            return None
        return self._embedder.encode([DOCUMENT_PREFIX + p for p in phrases])

    @property
    def records(self) -> List[KnowledgeRecord]:
        return list(self._records)

    @property
    def threshold(self) -> float:
        return self._threshold

    def best_match(self, text: str) -> Optional[Tuple[KnowledgeRecord, float]]:
        """Лучшее совпадение независимо от порога.

        Нужен отдельно от search(): вызывающая сторона (DialogEngine) обязана
        логировать меру близости и на промахе тоже (см. финальное ревью —
        порог близости назван главным настроечным параметром прототипа, без
        видимости промахов его невозможно подобрать на живых звонках).
        search() при промахе просто отдаёт None, ничего не сообщая о том,
        насколько близко было ближайшее совпадение.
        """
        if self._vectors is None or not text.strip():
            return None
        query = self._embedder.encode([QUERY_PREFIX + text])[0]
        # Векторы нормированы, поэтому скалярное произведение и есть косинусная близость.
        scores = self._vectors @ query
        best_index = int(np.argmax(scores))
        # Владелец формулировки, а не сама формулировка: клиенту отвечает запись.
        return self._phrase_owners[best_index], float(scores[best_index])

    def search(self, text: str) -> Optional[Tuple[KnowledgeRecord, float]]:
        match = self.best_match(text)
        if match is None or match[1] < self._threshold:
            return None
        return match

    def add(self, question: str) -> KnowledgeRecord:
        # Уточняющий вопрос намеренно пуст: это неопознанная реплика,
        # записанная для последующей ручной разметки (спецификация просит
        # именно дописывать в файл, а не подмешивать в живой поиск). Раз
        # clarifying_question пуст, запись не попадает в
        # self._searchable_records — self._vectors пересчитывать не нужно,
        # она и так не участвует в поиске.
        next_id = max((r.id for r in self._records), default=0) + 1
        record = KnowledgeRecord(id=next_id, question=question)
        self._records.append(record)
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
