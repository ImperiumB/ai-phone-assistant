"""База знаний и поиск похожего по смыслу вопроса.

Поиск делается эмбеддингами, а не LLM: он детерминирован, быстр и ничего не выдумывает.
"""
import json
import re
import os
from dataclasses import asdict, dataclass, field
from typing import List, Optional, Tuple

import numpy as np

from ai_assistant.service.corpus_knn import OPERATOR_DIRECTION, CorpusIndex, Vote

# Префиксы нужны моделям семейства E5/RoSBERTa: они обучались различать запрос и документ.
QUERY_PREFIX = "search_query: "
DOCUMENT_PREFIX = "search_document: "

_WORD_RE = re.compile(r"[а-яёa-z0-9]+")
#: Слова, по которым тему не понять: приветствия, междометия, обращения,
#: связки. «Угу здравствуйте», «да алло здрасьте», «они знаешь» состоят из них
#: целиком — такие реплики бот переспрашивает, а не отдаёт корпусу на голосование.
FILLER_WORDS = frozenset("""
здравствуйте здрасьте здрасте здравствуй привет алло але добрый доброе день утро вечер
да нет угу ага ну вот это то же ли бы и а но или что как так там тут вон
я мы вы ты он она они мне нам вам мой моя моё наш ваш вас нас меня тебя его её их
пожалуйста скажите подскажите извините простите спасибо девушка молодой человек
значит вообще просто короче слушайте смотрите знаете понимаете такое самое ещё еще
у в на с к по за о об от из до для при про
""".split())


def content_words(text: str) -> List[str]:
    """Слова реплики, несущие тему, — без приветствий, междометий и связок."""
    return [w for w in _WORD_RE.findall(text.lower().replace("ё", "е")) if w not in FILLER_WORDS]


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


@dataclass
class Resolution:
    """Что бот решил по реплике клиента.

    record/score — запись базы знаний и близость к её формулировке; trusted —
    решению верят (порог пройден) и по записи можно вести разговор дальше;
    source — кто решил: «corpus» (соседи по корпусу живых реплик), «phrases»
    (ближайшая рукописная формулировка) или «none» (сравнивать не с чем);
    vote — как проголосовал корпус, для лога, даже если решала не он.
    """
    record: Optional[KnowledgeRecord]
    score: float
    trusted: bool
    source: str
    vote: Optional[Vote] = None


class KnowledgeBase:
    def __init__(self, records: List[KnowledgeRecord], embedder, threshold: float,
                 corpus: Optional[CorpusIndex] = None):
        self._records = list(records)
        self._embedder = embedder
        self._threshold = threshold
        # Корпус живых реплик — второе мнение (corpus_knn.py). Пусто — решает
        # только база формулировок, как до 20.09.2026.
        self._corpus = corpus
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
        # Пустой уточняющий вопрос бывает двух сортов. Реплика, которую add()
        # записал на разметку, — у неё нет ни сценария, ни направления, в
        # поиск её пускать нельзя. И тема, которую уточнять не надо («соедините
        # с оператором», UL-19020): она приезжает из ERP с готовым сценарием,
        # и её ветка в DialogEngine — мгновенный перевод. До 18.09.2026 второй
        # сорт тоже выпадал из индекса, и записи сценария 35 не находились
        # никогда, хотя посылка их принимала.
        return [r for r in self._records if r.clarifying_question or r.scenario]

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

    @property
    def corpus(self) -> Optional[CorpusIndex]:
        return self._corpus

    def resolve(self, text: str) -> Optional[Resolution]:
        """Решение по реплике: корпус, если он уверен, иначе формулировки.

        Запрос кодируется один раз — и для соседей по корпусу, и для
        формулировок (кодирование — самая дорогая часть, см. best_match).
        """
        if not text.strip() or (self._vectors is None and self._corpus is None):
            return None
        query = self._embedder.encode([QUERY_PREFIX + text])[0]
        return self.resolve_vector(query, content_words=len(content_words(text)))

    def _corpus_trusts(self, vote: Vote, content_words_count: Optional[int]) -> bool:
        """Можно ли верить голосу корпуса на этой реплике.

        Три условия, и все — из разбора звонков 21–22.09.2026 (второй этап
        теста, UL-19020): «угу здравствуйте», «установка», «они знаешь»
        уходили на оператора, потому что соседи у пустых реплик — такие же
        пустые начала повторных звонков. Реплика без содержания корпусу не
        показывается вовсе (бот переспросит). Оператор — отдельный порог:
        перевод на сопровождение без вопроса дорог, «вызвать мастера на дом»
        (0.70) должно спрашивать «что вас интересует?», а не переводить.
        """
        if vote.confidence < self._corpus.threshold:
            return False
        if content_words_count is not None and content_words_count < self._corpus.min_words:
            return False
        if vote.direction_id == OPERATOR_DIRECTION and vote.confidence < self._corpus.operator_threshold:
            return False
        return True

    def resolve_vector(self, query: np.ndarray, content_words: Optional[int] = None) -> Optional[Resolution]:
        vote = self._corpus.vote(query) if self._corpus is not None else None
        scores = self._vectors @ query if self._vectors is not None else None
        if scores is None and vote is None:
            return None
        if vote is not None and self._corpus_trusts(vote, content_words):
            record, score = self._record_for_direction(vote.direction_id, scores)
            if record is not None:
                return Resolution(record, score, True, "corpus", vote)
            # Корпус уверен, а записи с таким направлением в базе нет —
            # переводить некуда, решают формулировки.
        elif (vote is not None and vote.direction_id == OPERATOR_DIRECTION
              and vote.confidence >= self._corpus.threshold
              and (content_words is None or content_words >= self._corpus.min_words)):
            # Корпус видит повторное обращение, но не настолько уверенно,
            # чтобы переводить без вопроса. Формулировкам такую реплику не
            # отдаём: «жду мастера по стиралке» они ведут в стиральные машины и
            # задают вопрос не по делу (замер на ручной тысяче 24.09.2026:
            # +6.5% таких вопросов). Лучше переспросить — на повторе клиент
            # скажет то же самое, и корпус решит увереннее.
            return Resolution(None, 0.0, False, "corpus-unsure", vote)
        if scores is None:
            return Resolution(None, 0.0, False, "none", vote)
        best_index = int(np.argmax(scores))
        score = float(scores[best_index])
        return Resolution(self._phrase_owners[best_index], score, score >= self._threshold, "phrases", vote)

    def _record_for_direction(
        self, direction_id: int, scores: Optional[np.ndarray]
    ) -> Tuple[Optional[KnowledgeRecord], float]:
        """Запись базы знаний, по которой вести разговор, если корпус назвал направление.

        У направления бывает несколько записей (стиральные и сушильные машины
        — одно направление, но разные уточняющие вопросы): берём ту, чья
        формулировка ближе к реплике. Для сопровождения — наоборот, запись
        без уточняющего вопроса: повторное обращение уходит на оператора
        сразу, а не через вопрос про жалобу (правило заказчик, 20.09.2026).
        """
        best_by_record = {}
        if scores is not None:
            for index, owner in enumerate(self._phrase_owners):
                if owner.telephone_direction_id == direction_id:
                    best_by_record[owner.id] = max(best_by_record.get(owner.id, -1.0), float(scores[index]))
        candidates = [r for r in self._searchable_records if r.telephone_direction_id == direction_id]
        if not candidates:
            return None, 0.0
        if direction_id == OPERATOR_DIRECTION:
            direct = [r for r in candidates if not r.clarifying_question]
            candidates = direct or candidates
        record = max(candidates, key=lambda r: best_by_record.get(r.id, -1.0))
        return record, max(best_by_record.get(record.id, 0.0), 0.0)

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


def load_knowledge_base(path: str, embedder, threshold: float,
                        corpus: Optional[CorpusIndex] = None) -> KnowledgeBase:
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    records = [KnowledgeRecord(**item) for item in payload]
    return KnowledgeBase(records, embedder, threshold, corpus=corpus)
