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


def exact_key(text: str) -> str:
    """Реплика как ключ дословного совпадения: слова через пробел, без регистра, «ё» и знаков."""
    return " ".join(_WORD_RE.findall(text.lower().replace("ё", "е")))


#: Записи-бренды: по названию сценария → как бренд звучит в реплике. Такая
#: запись берётся, только если клиент бренд назвал. Без этого «ремонт техники
#: дайсон»/«керхер не включается» притягивают любое «ремонт техники …»:
#: 8-я волна 12.10.2026 — «хотел узнать по ремонту» → Dyson (0.73), «блендер
#: марка браун» → Karcher (0.67), «ремонт техники эпл» → Dyson (0.72).
#: Ключ — подстрока названия типа оборудования записи (ULTIMA.EQUIPMENT_TYPES,
#: «Dyson», «Karcher», «Смартфон Samsung», «iPhone…», «iPad») или её
#: основного вопроса («керхер не включается») в нижнем регистре; слова —
#: начала слов реплики («дайсона», «керхером» подходят).
#: Варианты с ошибками распознавания («дальсон», «перфер») — из тестовых
#: звонков 13.10.2026: бренд в трубке звучит нечётко, модель пишет похожее.
BRAND_GATES = {
    "dyson": ("дайс", "дальсон", "dyson"),
    "дайсон": ("дайс", "дальсон", "dyson"),
    "karcher": ("керхер", "кархер", "кэрхер", "керхир", "перфер", "керфер", "кехер", "karcher"),
    "керхер": ("керхер", "кархер", "кэрхер", "керхир", "перфер", "керфер", "кехер", "karcher"),
    "samsung": ("самсунг", "samsung"),
    "самсунг": ("самсунг", "samsung"),
    "iphone": ("айфон", "iphone", "эпл", "эппл", "апл", "аппл", "apple"),
    "айфон": ("айфон", "iphone", "эпл", "эппл", "апл", "аппл", "apple"),
    "ipad": ("айпад", "ipad", "эпл", "эппл", "апл", "аппл", "apple"),
    "айпад": ("айпад", "ipad", "эпл", "эппл", "апл", "аппл", "apple"),
}

#: Замок категории: слова, которые однозначно называют тему, и корпусу
#: перебивать их нельзя. 22.10.2026: «крысы завелись» корпус уводил в электрику
#: (0.53) по соседу «вызвать врача на крысу», «тараканы завелись» — в
#: сопровождение; на редких темах корпус уверенно мажет и глушит точные
#: формулировки. Эти слова говорит сам клиент, и значат они обработку. Ключ —
#: код типа оборудования целевой записи (стабильный код ERP): 320 «грызуны»,
#: 915 «дезинсекция/насекомые». Нет такой записи в посылке — замок молчит.
CATEGORY_GATES = (
    # Ветеринар ПЕРВЫМ: животные (собака, кошка, питомец), «вылечить собаку»,
    # «вызвать ветеринара», даже «крыса у ветеринара» это всё ветеринарные услуги
    # (800), мимо корпуса, который уводил животных в сантехнику и электрику
    # (звонок 02.11.2026). Стоит до крыс, поэтому «крыса плюс ветеринар» идёт к врачу.
    (re.compile(r"\bсобак|\bкошк|\bкотен|\bщен|\bпитом|\bживотн|\bпсин|\bпопуга|\bхомяк|\bветеринар|\bврач", re.I), 800),
    # Граница слова \b обязательна: без неё «клоп» ловится в «стеклопакет», и окна
    # улетали в дезинсекцию со score 1.00 (замер по волнам 22.10.2026).
    (re.compile(r"\bкрыс|\bмыш|\bгрызун|\bдератизац", re.I), 320),
    (re.compile(r"\bтаракан|\bклоп|\bблох|\bклещ|\bмуравь|\bнасеком|\bдезинсекц", re.I), 915),
    # Водонагреватель/бойлер: «мастер по водонагревательному аппарату» (волна 12,
    # 270976008) матчил запись водонагревателя на 0.70, но порог перевода 0.72 ронял
    # его к Борцу. Слово однозначно наше (eq 219, записи есть), ведём гейтом мимо
    # порога. глобальный порог не трогаем, его бережём под гитару/проектор.
    (re.compile(r"\bводонагрев|\bбойлер", re.I), 219),
    # Электрика (eq 90): «электротехнические работы» (волна 12, 270972561) фраза-матч
    # увёл в оргтехнику/принтер, хотя корпус уверенно звал электрику; «проверка
    # электросчётчика» (270975204) уходила в сантехнику. Ведём гейтом. Узко, без
    # электроплиты/электродуховки/электрочайника, это свои приборы.
    (re.compile(r"\bэлектросчетчик|\bэлектротехническ|\bэлектропроводк|\bэлектромонтаж", re.I), 90),
    # Интернет/провайдер/подключение: клиент явно просит услугу интернета, а корпус мажет
    # в сопровождение (напр. 17, 0.52) и бот спрашивает развилку «по оформленному заказу?»
    # (волна 12, 270982595). Гейт ведёт на запись интернета (eq 656), мимо развилки. «в
    # интернете»/«по интернету» (нашёл онлайн) не ловим: нужен «провайдер» или «подключить интернет».
    (re.compile(r"\bпровайдер|подключ\w*\s+(?:к\s+)?интернет|интернет\w*\s+провайдер|интернет\w*\s+на\s+дач|подключени\w*\s+интернет", re.I), 656),
    # Духовка/духовой шкаф: «мастер духовку» (волна 12, 270961918) уходило в развилку, а та
    # предлагала микроволновку. Ведём гейтом на духовые шкафы (eq 356, направление 2).
    # Газовая и электрическая духовка. одна команда (dir 2), разница лишь в тексте уточняющего.
    # Газовый котёл это отдельная тема (eq 747), сюда не попадает: там «котёл» без «духов».
    (re.compile(r"\bдухов", re.I), 356),
)

#: Одно слово, которым просят человека: встретилось в реплике — запись без
#: вопроса (сопровождение) берётся сразу, что бы ни стояло рядом. «Оператора
#: мне» (8-я волна, 13:33) по близости давало 0.71 и упиралось в порог 0.72.
#: Слова берутся из односложных формулировок записей без вопроса и не короче
#: этого: «мастер», «человек» слишком многозначны.
DIRECT_KEYWORD_MIN_LETTERS = 8
#: Сколько первых букв ключевого слова сравнивать: «оператор», «оператора», «оператором» — одно слово.
DIRECT_KEYWORD_STEM_LETTERS = 7

#: При такой и большей уверенности корпуса формулировка его не перебивает:
#: «здравствуйте вопрос по заказу» — корпус 1.0 за сопровождение, а свежая
#: формулировка клининга «у меня вопрос по заказ клининговых услуг» дала 0.75
#: (14.10.2026, 1791965278) — и бот спросил про уборку.
PHRASE_OVERRIDE_MAX_CORPUS = 0.9

#: Просьба позвать человека, сказанная любыми словами: глагол связи рядом с
#: тем, кого просят. «Свяжите меня с мастером, вот это надо, а я сейчас как раз
#: пропылесосик…» (9-я волна, 270058388) — формулировка пылесоса перебила голос
#: корпуса за сопровождение, и бот спросил про пылесос. Такая просьба решает
#: до всякого поиска по смыслу, как и слово-ключ.
OPERATOR_REQUEST_RE = re.compile(
    r"\b(свяж\w*|соедин\w*|переключ\w*|перевед\w*|позов\w*|позвать|дайте|передайте|подключ\w*)\b"
    r"(?:\s+\w+){0,3}?\s+(?:с\s+|со\s+|на\s+|к\s+)?(мастер\w*|оператор\w*|человек\w*|менеджер\w*|специалист\w*|девушк\w*|сотрудник\w*)\b"
    r"|\b(оператор\w*|менеджер\w*|специалист\w*)\s+(позов\w*|дайте|нужен|нужна|надо|можно)\b",
    re.I,
)
# «Мастер нужен по холодильнику» — новый заказ, не просьба позвать человека: во
# второй ветке «мастера» нет намеренно; с глаголами связи («свяжите с мастером») — есть.

#: Вопрос «вы робот/живой человек?»: это не заявка, человек хочет человека. Корпус
#: на нём мажет в прибор («живой человек или авто» → «машина» → стиралка, звонок
#: 270945135, волна 12), поэтому решаем до поиска. «робот» ловим только рядом с
#: «вы/это/или человек», чтобы не задеть робот-пылесос.
OPERATOR_META_RE = re.compile(
    r"живой человек|вы\s+человек|человек\s+или\s+робот|робот\s+или\s+человек"
    r"|\bвы\s+робот|\bэто\s+робот|\bавтоответчик\b",
    re.I,
)

#: Явно не наша услуга: автомагнитола, химчистка/клининг/ковёр, продажа запчастей.
#: Корпус уводил их в ближайший прибор (магнитола → ТВ, химчистка → стиралка, волна
#: 12), поэтому сразу на оператора, а не предлагаем ремонт. Ремонт этих тем у нас не
#: заводится, ложных срабатываний на реальных заявках нет (проверка регрессом по волнам).
NOT_OUR_SERVICE_RE = re.compile(
    r"\bмагнитол|\bхимчистк|\bклининг|\bковер|\bковр|\bзапчаст|\bкомплектующ",
    re.I,
)

#: Близость к рукописной формулировке, при которой формулировка перебивает
#: уверенный голос корпуса за другое направление (см. resolve_vector).
#: Обычные попадания живут в 0.66–0.75; 0.80 — почти дословный повтор.
#: Дословный повтор формулировки у этой модели даёт лишь 0.72–0.76 (запрос и
#: документ кодируются с разными префиксами), так что планка ниже 0.80.
#: Переменная окружения — для замера на ручной разметке (tools/measure_manual.py).
PHRASE_OVERRIDE_SIMILARITY = float(os.environ.get("AIA_PHRASE_OVERRIDE", "0.74"))

#: Ближайший сосед по корпусу должен быть не дальше этого, иначе голос корпуса
#: не в счёт (см. _corpus_trusts). 0 = выключено, так и оставлено. Порог соседа пробовали 22.10.2026: он рубит законное спасение мятой речи корпусом (у верных мятых реплик сосед тоже ~0.6, как у мусора), не разделяя их, и срезал 6 пунктов охвата в 5 фолдах. Промах формулировок (гитара к проектору) лечит порог близости в dialog, а не здесь. Переменная окружения — для замера.
CORPUS_MIN_TOP_SIMILARITY = float(os.environ.get("AIA_CORPUS_MIN_TOP", "0.0"))


#: Записи о повторном обращении без вопроса («вопрос по оформленному заказу на
#: кофемашину или оргтехнику», «ко мне приезжал мастер…») берутся по
#: формулировкам, только если клиент говорит о существующем заказе: без этого
#: их формулировки с «кофемашиной» и «оргтехникой» притягивают новые заказы
#: («мне нужен ремонт кофемашины» → запись 33, 0.76; проверка коротких форм
#: 13.10.2026). Начала слов.
REPEAT_MARKERS = ("заказ", "заяв", "оформл", "статус", "срок", "сдал", "сдава", "уже", "приезжа", "приход",
                  "звонил", "жд", "гарант", "повторн", "снова", "опять", "вчера", "позавчера", "недел", "отмен",
                  "перенес", "когда", "обещал", "договор", "мастер", "ремонтировал", "чинил", "починил", "делал")
_REPEAT_RECORD_RE = re.compile(r"заказ|заяв|приезжал|оформл|мастер", re.I)


def repeat_gate(record: "KnowledgeRecord") -> bool:
    """Запись повторного обращения: без вопроса, направление сопровождения, вопрос про заказ/мастера."""
    return (not record.clarifying_question and record.telephone_direction_id == OPERATOR_DIRECTION
            and bool(_REPEAT_RECORD_RE.search(record.question or "")))


def brand_gate(record: "KnowledgeRecord") -> Optional[Tuple[str, ...]]:
    """Слова бренда, без которых запись брать нельзя; None — запись обычная."""
    name = ((record.equipment_type or "") + " " + (record.question or "")).lower()
    for key, words in BRAND_GATES.items():
        if key in name:
            return words
    return None


def record_allowed(record: "KnowledgeRecord", words: List[str]) -> bool:
    gate = brand_gate(record)
    if gate is not None and not any(w.startswith(g) for w in words for g in gate):
        return False
    if repeat_gate(record) and not any(w.startswith(m) for w in words for m in REPEAT_MARKERS):
        return False
    return True


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
    source — кто решил: «exact» (реплика слово в слово совпала с формулировкой),
    «corpus» (соседи по корпусу живых реплик), «phrases» (ближайшая рукописная
    формулировка) или «none» (сравнивать не с чем);
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
        # Дословное совпадение с формулировкой решается без эмбеддингов. Запрос
        # и документ кодируются с разными префиксами (RoSBERTa), и одно и то же
        # слово «оператор» против формулировки «оператор» даёт лишь 0.67
        # (замер 08.10.2026, 6-я волна: 269460604, 269464771) — ниже порога
        # перевода без вопроса, и клиента, сказавшего ровно то, что написал
        # аналитик, бот просил переформулировать. Формулировка, записанная у
        # двух разных записей, двусмысленна и дословно не решает.
        self._exact = self._collect_exact(self._phrases, self._phrase_owners)
        self._direct_keywords = self._collect_direct_keywords(self._phrases, self._phrase_owners)
        self._category_records = self._collect_category_records()

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

    @staticmethod
    def _collect_exact(
        phrases: List[str], owners: List[KnowledgeRecord]
    ) -> dict:
        """Ключ дословного совпадения → запись; None — формулировка есть у двух записей."""
        exact: dict = {}
        for phrase, owner in zip(phrases, owners):
            key = exact_key(phrase)
            if not key:
                continue
            if key in exact and exact[key] is not owner:
                exact[key] = None
            else:
                exact[key] = owner
        return exact

    def exact(self, text: str) -> Optional[KnowledgeRecord]:
        """Запись, одна из формулировок которой совпадает с репликой слово в слово."""
        return self._exact.get(exact_key(text))

    @staticmethod
    def _collect_direct_keywords(
        phrases: List[str], owners: List[KnowledgeRecord]
    ) -> dict:
        """Слово → запись без вопроса, у которой это слово — целая формулировка."""
        keywords: dict = {}
        for phrase, owner in zip(phrases, owners):
            if owner.clarifying_question:
                continue
            words = exact_key(phrase).split()
            if len(words) != 1 or len(words[0]) < DIRECT_KEYWORD_MIN_LETTERS:
                continue
            # Основа слова: «оператором», «операторов» — тот же оператор
            # (14.10.2026, 1791965238: «оператором» дважды уходило в переспрос).
            stem = words[0][:DIRECT_KEYWORD_STEM_LETTERS]
            if stem in keywords and keywords[stem] is not owner:
                keywords[stem] = None
            else:
                keywords[stem] = owner
        return keywords

    def direct_by_keyword(self, text: str) -> Optional[KnowledgeRecord]:
        """Запись без вопроса, чьё ключевое слово («оператора», «оператором») есть в реплике."""
        for word in exact_key(text).split():
            if len(word) < DIRECT_KEYWORD_STEM_LETTERS:
                continue
            record = self._direct_keywords.get(word[:DIRECT_KEYWORD_STEM_LETTERS])
            if record is not None:
                return record
        return None

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

    def resolve_phrases(self, text: str) -> Optional[Resolution]:
        """Решение только по формулировкам, без корпуса — для развилки «новый заказ»
        (dialog.POINT_INTENT): корпус на этой реплике уже засомневался, а клиент
        сказал, что заказ новый. Дословное совпадение и ворота брендов действуют."""
        if not text.strip() or self._vectors is None:
            return None
        record = self.exact(text)
        if record is not None:
            return Resolution(record, 1.0, True, "exact")
        query = self._embedder.encode([QUERY_PREFIX + text])[0]
        scores = self._vectors @ query
        words = exact_key(text).split()
        allowed = np.array([record_allowed(owner, words) for owner in self._phrase_owners])
        scores = np.where(allowed, scores, -1.0)
        best_index = int(np.argmax(scores))
        score = float(scores[best_index])
        return Resolution(self._phrase_owners[best_index], score, score >= self._threshold, "phrases")

    def _strong_phrase(self, scores: Optional[np.ndarray]) -> Optional[Tuple[KnowledgeRecord, float]]:
        """Формулировка, почти дословно совпавшая с репликой (PHRASE_OVERRIDE_SIMILARITY)."""
        if scores is None or not len(scores):
            return None
        best_index = int(np.argmax(scores))
        score = float(scores[best_index])
        if score < PHRASE_OVERRIDE_SIMILARITY:
            return None
        return self._phrase_owners[best_index], score

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

    def _collect_category_records(self) -> dict:
        """Запись на каждый код типа оборудования из CATEGORY_GATES (первая найденная)."""
        wanted = {eq for _, eq in CATEGORY_GATES}
        found: dict = {}
        for record in self._searchable_records:
            eq = record.equipment_type_id
            if eq in wanted and eq not in found:
                found[eq] = record
        return found

    def category_request(self, text: str) -> Optional[KnowledgeRecord]:
        """Однозначная категория (крысы/тараканы и т.п.) → её запись, мимо корпуса."""
        low = text.lower().replace("ё", "е")
        for pattern, eq_id in CATEGORY_GATES:
            if pattern.search(low):
                return self._category_records.get(eq_id)
        return None

    def resolve(self, text: str) -> Optional[Resolution]:
        """Решение по реплике: корпус, если он уверен, иначе формулировки.

        Запрос кодируется один раз — и для соседей по корпусу, и для
        формулировок (кодирование — самая дорогая часть, см. best_match).
        """
        if not text.strip() or (self._vectors is None and self._corpus is None):
            return None
        record = self.exact(text)
        if record is not None:
            return Resolution(record, 1.0, True, "exact")
        record = self.direct_by_keyword(text) or self.operator_request(text)
        if record is not None:
            return Resolution(record, 1.0, True, "keyword")
        record = self.category_request(text)
        if record is not None:
            return Resolution(record, 1.0, True, "category")
        query = self._embedder.encode([QUERY_PREFIX + text])[0]
        return self.resolve_vector(query, content_words=len(content_words(text)), text=text)

    def operator_request(self, text: str) -> Optional[KnowledgeRecord]:
        """На оператора без поиска по смыслу: просьба позвать человека (OPERATOR_REQUEST_RE),
        вопрос «вы робот/живой человек?» (OPERATOR_META_RE) и явно не наша услуга
        (NOT_OUR_SERVICE_RE: автомагнитола, химчистка, продажа запчастей). корпус их мажет
        в ближайший прибор, поэтому решаем до поиска. Все три на существующую запись оператора."""
        low = text.lower().replace("ё", "е")
        if not (OPERATOR_REQUEST_RE.search(low) or OPERATOR_META_RE.search(low)
                or NOT_OUR_SERVICE_RE.search(low)):
            return None
        return self._direct_keywords.get("оператор"[:DIRECT_KEYWORD_STEM_LETTERS])

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
        # Соседи далеко — голос ненадёжен: редкие услуги (ветеринар, МРТ,
        # клининг, форсунки) корпус отдаёт электрику/водонагревателям с
        # уверенностью 0.5–0.6 по соседям с близостью 0.6–0.7, тогда как
        # настоящие попадания живут на 0.85–0.95 (проверка коротких форм 13.10.2026).
        if vote.neighbours and vote.neighbours[0].score < CORPUS_MIN_TOP_SIMILARITY:
            return False
        if vote.direction_id == OPERATOR_DIRECTION and vote.confidence < self._corpus.operator_threshold:
            return False
        return True

    def resolve_vector(self, query: np.ndarray, content_words: Optional[int] = None,
                       text: Optional[str] = None) -> Optional[Resolution]:
        vote = self._corpus.vote(query) if self._corpus is not None else None
        scores = self._vectors @ query if self._vectors is not None else None
        if scores is None and vote is None:
            return None
        # Записи-бренды без названного бренда из поиска выбывают (BRAND_GATES).
        # Без текста (замер по готовым векторам) ворота не действуют.
        allowed = None
        if text is not None and scores is not None:
            words = exact_key(text).split()
            allowed = [record_allowed(owner, words) for owner in self._phrase_owners]
            if not all(allowed):
                scores = np.where(np.array(allowed), scores, -1.0)
        if vote is not None and self._corpus_trusts(vote, content_words):
            record, score = self._record_for_direction(vote.direction_id, scores, allowed)
            if record is not None:
                strong = self._strong_phrase(scores)
                if (strong is not None and strong[0].telephone_direction_id != vote.direction_id
                        and vote.confidence < PHRASE_OVERRIDE_MAX_CORPUS
                        # Голос за сопровождение формулировкой не перебиваем: «свяжите
                        # меня с мастером… пропылесосик» ушло в пылесосы (270058388).
                        and vote.direction_id != OPERATOR_DIRECTION):
                    # Реплика почти дословно повторяет рукописную формулировку
                    # другой темы — аналитик написал её осознанно, а корпус
                    # голосует по похожим словам: «утюги ремонтируете» →
                    # микроволновки, «ремонт масляного обогревателя» →
                    # водонагреватели (6-я волна 06.10.2026; в корпусе утюгов 4
                    # реплики на 56 тысяч). Порог — PHRASE_OVERRIDE_SIMILARITY.
                    return Resolution(strong[0], strong[1], True, "phrases", vote)
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
        self, direction_id: int, scores: Optional[np.ndarray], allowed: Optional[List[bool]] = None
    ) -> Tuple[Optional[KnowledgeRecord], float]:
        """Запись базы знаний, по которой вести разговор, если корпус назвал направление.

        У направления бывает несколько записей (стиральные и сушильные машины
        — одно направление, но разные уточняющие вопросы): берём ту, чья
        формулировка ближе к реплике. Для сопровождения — наоборот, запись
        без уточняющего вопроса: повторное обращение уходит на оператора
        сразу, а не через вопрос про жалобу (правило заказчика, 20.09.2026).
        """
        best_by_record = {}
        if scores is not None:
            for index, owner in enumerate(self._phrase_owners):
                if owner.telephone_direction_id == direction_id:
                    best_by_record[owner.id] = max(best_by_record.get(owner.id, -1.0), float(scores[index]))
        candidates = [r for r in self._searchable_records if r.telephone_direction_id == direction_id]
        if allowed is not None:
            barred = {owner.id for owner, ok in zip(self._phrase_owners, allowed) if not ok}
            candidates = [r for r in candidates if r.id not in barred]
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
