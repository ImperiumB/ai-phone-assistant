"""Логика диалога прототипа.

Формат запроса и ответа повторяет ReturnConversationIntermediateResult3 из ERP:
список пар Key/Value. Когда логика переедет в обработчик, в AGI-скрипте
поменяется только адрес.
"""
import hashlib
import logging
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger("aia.dialog")

_WORD_RE = re.compile(r"\w+")

POINT_START = "Start"
POINT_ASK_QUESTION = "AskQuestion"
POINT_CONFIRM = "Confirm"
POINT_FINISHED = "Finished"

ACTION_RECOGNIZE = "Recognize"
ACTION_REDIRECT = "Redirect"
ACTION_HANGUP = "Hangup"

SCENARIO_SUPPORT = "redirect_support"
SCENARIO_SALES = "redirect_sales"
# Перевод по телефонному направлению из справочника ULTIMA.TELEPHONE_DIRECTIONS.
# У каждого направления своё поле «Номер для приёма переведённого звонка», и
# бот переводит именно туда — вместо двух захардкоженных отделов. Это же
# закрывает пункт ТЗ про справочник сценариев: вариантами дальнейших действий
# становятся сами направления, а не самописный перечень.
SCENARIO_DIRECTION = "redirect_direction"

# Демон живёт постоянно, а состояние разговора копится по ключу звонка
# (linkedId) и раньше не удалялось вообще — это неограниченный рост памяти
# (Important 4 из ревью Task 9). Оба предела ниже — константы с одной целью:
# сессия штатно удаляется, когда разговор доходит до POINT_FINISHED (звонок
# завершён явно), а лимит ниже — подстраховка на случай звонков, которые
# никогда явно не завершаются (клиент бросил трубку без финального
# коллбэка, обрыв AGI-скрипта и т. п.): самая старая по времени создания
# сессия вытесняется, чтобы не расти бесконечно даже в этом случае.
DEFAULT_MAX_SESSIONS = 1000

# Сколько пустых распознаваний подряд в точке подтверждения бот проглатывает
# молча, прежде чем переспросить. Первая пустая попытка — почти всегда щелчок
# в линии (включение громкой связи), и переспрашивать на неё значит вернуть
# поломку, ради которой молчание вводили. Вторая подряд — это уже потерянный
# ответ живого человека.
CONFIRM_SILENT_EMPTY_ATTEMPTS = 1

# Сколько раз подряд непонятный ответ на уточняющий вопрос («техник», «ну как
# сказать») переспрашивается «да или нет», прежде чем бот забудет тему и
# попросит переформулировать. Ровно один: второй непонятный ответ значит,
# что вопрос клиенту не подходит, и держать его в этой точке невежливо.
CONFIRM_UNCLEAR_ATTEMPTS = 1

# То же самое для точки, где клиент называет тему, — но только для реплик,
# которые всё-таки распознались. Первую проглатываем молча, со второй подряд
# бот обязан заговорить.
#
# Живой звонок 20.08.2026, 17:16: клиент сказал «кто», потом «да» — обе реплики
# короче порога поиска, обе проглочены молча, — и следующей его фразой было
# «слышу я вас и что». До этой правки предела молчанию тут не было вовсе:
# в точке подтверждения бот переспрашивал, а здесь мог молчать бесконечно.
#
# На пустое распознавание (щелчок, кашель, хлопок двери) правило не
# распространяется: там клиент мог вообще ничего не говорить, и отвечать на
# каждый шорох значит вернуть поломку 13.08.2026, ради которой молчание и
# вводили. Молчащего клиента подберёт ветка silence по своему таймауту.
ASK_SILENT_EMPTY_ATTEMPTS = 1

# Сколько раз за звонок бот просит переформулировать вопрос, не найдя темы.
# Клиент называет поломку своими словами, и в базе знаний этих слов может не
# оказаться — на живом звонке 20.08.2026 «здравствуйте меня интересует ремонт
# пиццы» дало близость 0.6277 при пороге 0.64. До перевода на человека честно
# попросить сказать иначе: часто со второй попытки тема находится, и звонок
# заканчивается там же, где и должен, — на нужном отделе.
#
# Ровно один переспрос: вторая просьба переформулировать подряд читается уже
# как издевательство над человеком, который дважды объяснил свою проблему.
QUESTION_REASK_ATTEMPTS = 1

# Переспрос в точке подтверждения. Формулировка намеренно без грамматического
# рода: голос выбирается в справочнике группы линий и может быть как мужским
# (eugene, aidar), так и женским (kseniya, baya, xenia), а фраза одна на оба
# случая. Поэтому не «не расслышала» и не «не расслышал» — отдельное
# требование заказчика, от рода в репликах уходим совсем. Настоящее время от
# первого лица рода не имеет — тот же приём, что и в уточняющих вопросах базы
# знаний («Правильно понимаю, что...» вместо «Правильно я понял, что...»,
# sql/09_clarifying_question_genderless.sql).
# Многоточие перед «или» — не украшение: Vosk проглатывает запятую и произносит
# выбор слитно, а на многоточии делает нужную заминку (прослушивание 17.09.2026).
# Три точки, а не символ «…»: одиночный символ синтез не знает, и
# normalize_for_vosk выбросит его молча. Значение обязано совпадать с
# DefaultConfirmNotHeard в обработчике 15424 — оно присылается в посылке.
DEFAULT_CONFIRM_NOT_HEARD = "Простите, не слышу вас. Скажите, пожалуйста, да... или нет"

# Реплика уходит в поиск по смыслу, только если в ней есть слово хотя бы такой
# длины. Эмбеддинг двух-трёх букв — шум: близость у него к какой-нибудь теме
# получается случайно, и «выше порога» там ничего не значит.
#
# Живой звонок 18.08.2026: клиент сказал «не», поиск дал 0.6523 к теме «нужен
# ремонт мелкой бытовой техники» при пороге 0.64, и бот повёл разговор не туда.
#
# Величина подобрана замером на боевой базе (32 темы, 508 формулировок,
# порог 0.64). Выше порога оказались 12 обрывков из 76 — «алло» 0.7446,
# «хм» 0.6852, «угу» 0.6643, «ага» 0.6592, «алё» 0.6581, «а то» 0.6577,
# «не то» 0.6576, «не» 0.6523, «эээ» 0.6461, «да нет» 0.6447, «ну да» 0.6411,
# «ну вот» 0.6402 — и липли к произвольным темам (телевизор, холодильник,
# керхер, мелкая бытовая техника).
#
#   правило                    отсекает обрывков   теряет настоящих коротких
#   слово >= 3 букв                   5 из 12       0
#   слово >= 4 букв                  11 из 12       0 жалоб, 2 из 15 названий
#   слово >= 5 букв                  12 из 12       0 жалоб, 4 из 15 названий
#
# Считаются буквы в САМОМ ДЛИННОМ слове, а не длина строки: «не то» и «ну да»
# — это пять знаков, но два коротких слова, и по длине строки они бы прошли.
#
# Порог 5 отсекал бы ещё и «алло», но ценой «печь» и «утюг», а смысла в этом
# нет: «алло» — не короткая реплика, а приветствие, и приветствия проходят
# любое правило по длине («здравствуйте» 0.6894 -> «нужен ветеринар на дом»,
# «извините» 0.7215, «добрый день» 0.7069). Их надо закрывать отдельно и
# целым классом, а не подкручивать сюда одну заметную строчку.
#
# Отдельный, более высокий порог близости и требование отрыва от второй темы
# замерены и отвергнуты: «хм» (0.6852) обходит настоящие «печь» (0.6475) и
# «тв» (0.6546), а отрыв у законных фраз бывает нулевым («хочу вызвать
# мастера» — 0.0002).
MIN_SEARCHABLE_WORD_LETTERS = 4

# Тот самый «целый класс» из записки выше: вежливые зачины, в которых нет ни
# слова о деле. По длине они проходят любое правило — «подскажите пожалуйста»
# это два длинных слова, — а темы в них нет вовсе.
#
# Живой звонок 03.09.2026: «подскажите пожалуйста» дало 0.7054 и увело клиента
# к теме «нужна обработка от тараканов». Бот с полной уверенностью спросил про
# дезинсекцию у человека, который ещё ничего не успел сказать. Пороги тут
# бессильны: 0.7054 выше, чем у законного «сколько стоит починить стиральную
# машину» (0.6625), и любой порог, который отсечёт первое, убьёт второе.
#
# Правило простое: если ВСЕ слова реплики из этого списка, искать в ней нечего.
# Одно содержательное слово — и реплика идёт в поиск как обычно, поэтому
# «подскажите ремонт холодильника» правилом не задевается.
#
# Проверено на боевой базе 03.09.2026: из 676 формулировок под правило не
# попадает ни одна. Список расширять можно, но каждый раз перепроверяя этим же
# способом — иначе однажды выкинем настоящую тему.
FILLER_WORDS = frozenset([
    "алло", "але", "аллё", "здравствуйте", "здрасте", "здрасьте", "привет",
    "добрый", "доброе", "день", "утро", "вечер",
    "подскажите", "скажите", "пожалуйста", "можно", "вопрос", "спросить",
    "хотел", "хотела", "бы", "узнать",
    "вас", "вы", "мне", "меня", "я", "у", "а", "тут", "вот", "это", "ну", "так",
    "есть", "ли", "короче", "значит",
    "девушка", "молодой", "человек", "будьте", "добры", "извините", "простите",
    "слушайте",
])

# Буквы, без цифр и подчёркиваний: правило меряет именно слово.
_LETTERS_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


@dataclass
class Phrases:
    greeting: str
    misrecognition: str
    transfer: str
    silence: str
    #: Клиент явно ответил «нет» на уточняющий вопрос — бот не угадал тему.
    #: Это не то же самое, что misrecognition: там бот не понял ответ, здесь
    #: понял прекрасно и ошибся сам. Просить «переформулировать» в этом случае
    #: невежливо и сбивает с толку — надо просто спросить, что нужно клиенту.
    wrong_guess: str = "Тогда подскажите, пожалуйста, что вас интересует?"
    #: Переспрос, когда распознавание в точке подтверждения второй раз подряд
    #: вернуло пустоту. Значение по умолчанию — на то время, пока в справочнике
    #: группы линий нет своего поля: посылка без него применяется как обычно.
    confirm_not_heard: str = DEFAULT_CONFIRM_NOT_HEARD


# Сколько последних цифр номера участвуют в сравнении. Набранный номер
# приезжает от Астериска то с восьмёркой, то с семёркой, то без кода страны —
# точное сравнение строк не совпало бы почти никогда. Столько же цифр
# сравнивает обработчик обращений в ERP, когда ищет линию по набранному номеру.
PHONE_KEY_DIGITS = 10

# Служебные фразы бота — те, что правятся в справочнике группы линий и только у
# которых бывает заранее записанный аудиофайл. Порядок и имена совпадают с
# полями Phrases: по этим именам разложены и пути к записанным файлам.
PHRASE_SLOTS = (
    "greeting",
    "misrecognition",
    "transfer",
    "silence",
    "wrong_guess",
    "confirm_not_heard",
)


@dataclass
class LineProfile:
    """Как бот звучит на номерах одной группы линий.

    Галочка «Виртуальный AI помощник» стоит на номерах из разных групп, и у
    каждой группы свои фразы, свой голос и свои записанные аудио. База знаний
    при этом общая — темы про ремонт техники не зависят от того, на какой номер
    позвонили.
    """

    phrases: Phrases
    voice: str = ""
    #: Модель синтеза плюс голос: входит в имя файла кэша станции, поэтому у
    #: каждой группы оно своё и одна и та же фраза не звучит чужим голосом.
    audio_signature: str = ""
    #: Заранее записанные файлы по именам фраз (PHRASE_SLOTS). Пусто, пока
    #: галочка «использовать записанные аудиофайлы» в группе выключена.
    audio_files: Dict[str, str] = field(default_factory=dict)
    #: Свои варианты согласия и отказа. Пусто — берутся из записи базы знаний,
    #: как было до разделения по группам.
    positive_answers: List[str] = field(default_factory=list)
    negative_answers: List[str] = field(default_factory=list)
    #: Номера линий с галочкой. По ним набор и выбирается.
    phones: List[str] = field(default_factory=list)
    line_group_id: int = 0
    #: Группа линий частных мастеров. Признак принадлежит линии, а не теме:
    #: база знаний общая, а куда уйдёт звонок — зависит от того, на какой номер
    #: позвонили. Звонок с такой линии уходит на второй номер того же
    #: направления, в отдел частных мастеров (см. redirect_exten_pm записи).
    is_private_master: bool = False


def phone_key(number: str) -> str:
    """По чему номера сравниваются между собой — последние PHONE_KEY_DIGITS цифр."""
    digits = "".join(symbol for symbol in str(number or "") if symbol.isdigit())
    return digits[-PHONE_KEY_DIGITS:]


def prms_to_dict(items: List[Dict[str, Any]]) -> Dict[str, str]:
    return {str(item["Key"]): str(item["Value"]) for item in items}


def dict_to_prms(data: Dict[str, str]) -> List[Dict[str, str]]:
    return [{"Key": key, "Value": value} for key, value in data.items()]


def _playback_name(text: str, audio_signature: str = "") -> str:
    """Имя файла кэша: устойчивый хеш от текста. Пробелов быть не должно.

    В хеш входит и подпись звука (модель синтеза плюс голос). Файлы с этим
    именем кэшируются на самой телефонной станции, и без подписи смена голоса
    или модели там не замечается: станция продолжает играть старые файлы
    прежним голосом. Ровно на это напоролись 13.08.2026 при первом живом
    звонке — переключили модель, а в трубке звучала прежняя.
    """
    key = "{0}|{1}".format(audio_signature, text).encode("utf-8")
    digest = hashlib.sha1(key).hexdigest()[:16]
    return "aia_" + digest


class _SessionState:
    def __init__(self) -> None:
        self.record = None
        #: Мера близости, с которой нашлась record. Нужна не только логу: она
        #: уходит в ответ и дальше в обращение ERP, по ней потом видно,
        #: насколько уверенно бот определил тему.
        self.score = 0.0
        self.silence_count = 0
        #: Сколько распознаваний подряд вернуло пустоту. Обнуляется, как только
        #: что-то распозналось: считать надо именно подряд идущие промахи, иначе
        #: разговор с парой щелчков в разных местах доберётся до переспроса на
        #: ровном месте.
        self.empty_count = 0
        #: Сколько раз за этот звонок бот уже просил переформулировать вопрос,
        #: не найдя темы. Счётчик именно на звонок, а не «подряд»: клиент,
        #: которого один раз попросили сказать иначе, не должен услышать ту же
        #: просьбу ещё раз где-то в конце разговора.
        self.reask_count = 0
        #: Реплика клиента, по которой нашлась record, — чтобы при «нет» на
        #: уточняющий вопрос было что отправить на разметку.
        self.question_text = ""
        #: Тема, которую бот угадал не так: (реплика клиента, вопрос записи).
        #: Заполняется при явном «нет» и уезжает в ERP вместе с итоговым
        #: переводом — куда бы разговор ни пришёл потом (аналитик КЦ, 24.09.2026:
        #: уверенные промахи в справочник не попадали, только честные «не знаю»).
        self.wrong_guess = None
        #: Сколько раз подряд ответ на уточняющий вопрос не был ни «да», ни
        #: «нет» и не назвал тему. Первый такой ответ переспрашивается, тема
        #: при этом не теряется (4-я волна 01.10.2026: «техник» → переспрос по
        #: теме → «да» ушло в пустоту, 269164694).
        self.confirm_unclear = 0


class DialogEngine:
    def __init__(
        self,
        knowledge,
        phrases: Phrases,
        support_exten: str,
        sales_exten: str,
        max_sessions: int = DEFAULT_MAX_SESSIONS,
        audio_signature: str = "",
        voice: str = "",
        audio_files: Optional[Dict[str, str]] = None,
        line_profiles: Optional[List[LineProfile]] = None,
        is_private_master: bool = False,
    ):
        self._knowledge = knowledge
        self._support_exten = support_exten
        self._sales_exten = sales_exten
        self._max_sessions = max_sessions
        # Набор по умолчанию. Он же — единственный, пока групп линий нет:
        # посылка прежней сборки их не присылает, и разговор идёт как раньше.
        # Модель синтеза и голос в подписи звука попадают в имя файла, чтобы
        # кэш на станции обновился сам при их смене.
        self._default_profile = LineProfile(
            phrases=phrases,
            voice=voice,
            audio_signature=audio_signature,
            audio_files=dict(audio_files or {}),
            # Набор по умолчанию — это раздел settings посылки, то есть такая же
            # группа линий из справочника, и она тоже может оказаться группой
            # частных мастеров.
            is_private_master=is_private_master,
        )
        self._line_profiles = list(line_profiles or [])
        # Раскладка «номер -> набор» считается один раз при сборке движка:
        # выбор набора случается на каждой реплике каждого звонка.
        self._profile_by_phone: Dict[str, LineProfile] = {}
        for profile in self._line_profiles:
            for phone in profile.phones:
                key = phone_key(phone)
                if not key:
                    continue
                claimed = self._profile_by_phone.get(key)
                if claimed is not None:
                    # Один номер в двух группах — ошибка в справочнике, и
                    # молча выбирать из них наугад нельзя: разговор шёл бы
                    # разными фразами в зависимости от порядка строк в БД.
                    log.warning(
                        "Номер %s числится и в группе линий %s, и в %s — оставлен первый",
                        phone, claimed.line_group_id, profile.line_group_id,
                    )
                    continue
                self._profile_by_phone[key] = profile
        self._sessions: Dict[str, _SessionState] = {}
        # /dialog — обычная функция FastAPI, конкурентные звонки реально
        # выполняют handle() в разных потоках одновременно. Без этой
        # блокировки связка "проверить длину -> взять первый ключ итератором
        # -> удалить -> вставить" не атомарна: два потока, упирающихся в
        # потолок сессий одновременно, могут словить RuntimeError
        # ("dictionary changed size during iteration") или KeyError на
        # повторном удалении одного и того же "самого старого" ключа —
        # оба валят конкретный звонок необработанным исключением (см.
        # повторное ревью Task 9). Блокировка — только вокруг операций со
        # словарём, без обращений к базе знаний или вычисления эмбеддингов.
        self._sessions_lock = threading.Lock()

    @property
    def profiles(self) -> List[LineProfile]:
        """Все наборы, которыми движок способен говорить. Нужны прогреву синтеза:
        греть надо каждый голос, а не только голос набора по умолчанию."""
        return [self._default_profile] + self._line_profiles

    def _profile_for(self, dialed_number: str) -> LineProfile:
        """Чьими фразами и голосом отвечать на этот звонок.

        Номер не сопоставился ни с одной группой (звонок на номер без галочки,
        скрипт прежней сборки, не присылающий номер вовсе) — набор по
        умолчанию: лучше поздороваться чужой фразой, чем молчать в трубку.
        """
        return self._profile_by_phone.get(phone_key(dialed_number), self._default_profile)

    def _session(self, linked_id: str) -> _SessionState:
        with self._sessions_lock:
            if linked_id not in self._sessions:
                if len(self._sessions) >= self._max_sessions:
                    # Словарь в Python 3.7+ хранит порядок вставки — первый
                    # ключ и есть самая старая живая сессия.
                    oldest_linked_id = next(iter(self._sessions))
                    del self._sessions[oldest_linked_id]
                self._sessions[linked_id] = _SessionState()
            return self._sessions[linked_id]

    def adopt_sessions(self, other: Optional["DialogEngine"]) -> None:
        """Перенять разговоры, идущие прямо сейчас, у прежнего движка.

        База знаний приезжает из ERP посреди рабочего дня, и подмена движка
        приходится ровно на чей-нибудь разговор. Бот задал уточняющий вопрос
        по прежней базе, клиент отвечает «да» уже новому движку — а тот про
        этот звонок ничего не знает и вместо перевода по своей теме увёз бы
        клиента на общий номер сопровождения.

        Найденная запись лежит в состоянии сессии снимком, а не ссылкой на
        базу знаний, поэтому разговор честно доигрывается по той теме, о
        которой бот спрашивал.
        """
        if other is None or other is self:
            return
        with other._sessions_lock:
            sessions = dict(other._sessions)
        with self._sessions_lock:
            self._sessions.update(sessions)

    def handle(self, prms: Dict[str, str]) -> List[Dict[str, str]]:
        linked_id = prms.get("linkedId", "")
        point = prms.get("conversationPoint") or POINT_START
        text = (prms.get("recognizedText") or "").strip().lower()
        silence = str(prms.get("silenceDetected", "")).lower() == "true"
        state = self._session(linked_id)
        # Набор выбирается на каждой реплике заново, а не запоминается в
        # сессии: набранный номер приезжает в каждом запросе, и лишнее
        # состояние тут ничего не даёт.
        profile = self._profile_for(prms.get("dialedNumber", ""))

        if point == POINT_START:
            result = self._say(profile, "greeting", ACTION_RECOGNIZE, POINT_ASK_QUESTION)
        elif silence:
            state.silence_count += 1
            if state.silence_count >= 2:
                result = self._transfer(profile, self._support_exten, state=state)
            else:
                result = self._say(profile, "silence", ACTION_RECOGNIZE, point)
        elif not text or self._is_scrap_for_search(text, point):
            # Пустой результат распознавания — это не вопрос клиента, а обрывок:
            # щелчок в линии, шорох, кашель, хлопок двери. Отрезок оказался
            # короче порога распознавания, и движок вернул пустую строку.
            #
            # Раньше такое доходило до _handle_question и трактовалось как
            # "вопроса нет в базе знаний" — бот немедленно переводил звонок на
            # специалиста. На живом звонке 13.08.2026 клиент не успел раскрыть
            # рта: включённая громкая связь дала щелчок, и разговор кончился.
            # В бою это срабатывало бы от любого постороннего звука.
            #
            # Правильное поведение — молча продолжать слушать, оставаясь в той
            # же точке разговора. Если клиент действительно молчит, это отработает
            # ветка silence по своему таймауту, а не подмена вопроса шумом.
            #
            # Но только в открытом вопросе. В точке подтверждения бот секунду
            # назад спросил «да или нет», и молчание в ответ на ответ клиент
            # читает как поломку бота: живой звонок 18.08.2026 — два «нет»
            # подряд дали пустое распознавание, бот промолчал оба раза, клиент
            # положил трубку. Начиная со второй подряд пустой попытки в этой
            # точке переспрашиваем вслух.
            #
            # Сюда же приходит распознанный, но слишком короткий обрывок
            # ("не", "ага", "хм"): по смыслу это то же самое — бот не понял,
            # что сказали, — и вести себя должен так же, включая счётчик.
            # Отличается только запись в логе: обрывок надо видеть отдельно
            # от пустоты, иначе не понять, режет правило лишнее или нет.
            if text:
                log.info(
                    "Реплика %r в точке %s слишком коротка для поиска по смыслу", text, point
                )
            state.empty_count += 1
            if point == POINT_CONFIRM and state.empty_count > CONFIRM_SILENT_EMPTY_ATTEMPTS:
                log.info(
                    "Пустой результат распознавания в точке %s подряд %s раз — переспрашиваем",
                    point, state.empty_count,
                )
                result = self._say(
                    profile, "confirm_not_heard", ACTION_RECOGNIZE, POINT_CONFIRM
                )
            elif point != POINT_CONFIRM and text and state.empty_count > ASK_SILENT_EMPTY_ATTEMPTS:
                # Клиент говорит, а бот молчит — для человека это поломка, и
                # неважно, что его слова не дотянули до порога поиска. Просим
                # сказать иначе тем же набором фраз, что и при промахе по
                # смыслу: по сути случай тот же — бот не понял, что сказали.
                #
                # Условие `text` тут главное. Пустое распознавание — это шум в
                # линии: клиент, возможно, вообще ничего не говорил, и на щелчки
                # бот по-прежнему молчит сколько угодно (для по-настоящему
                # молчащего клиента есть ветка silence со своим таймаутом).
                # А вот распознанное слово значит, что человек точно говорил, —
                # и не ответить ему нельзя.
                log.info(
                    "Обрывок в точке %s подряд %s раз — просим сказать иначе",
                    point, state.empty_count,
                )
                result = self._say(profile, "misrecognition", ACTION_RECOGNIZE, point)
            else:
                log.info("Пустой результат распознавания в точке %s — продолжаем слушать", point)
                result = self._keep_listening(point)
        elif self._is_filler_only(text, point):
            # Клиент поздоровался или вежливо начал, но о деле ещё ничего не
            # сказал. В поиск такую реплику пускать нельзя: тема найдётся
            # обязательно, просто случайная. Отвечаем сразу и молчать тут
            # нельзя — в отличие от обрывка, это заведомо живой человек,
            # который к нам обратился.
            #
            # Промахом это не считается: переспрос по теме (reask_count) не
            # тратится, иначе вежливый клиент оказался бы наказан за вежливость.
            log.info("Реплика %r — вежливый зачин без темы, в поиск не идёт", text)
            state.silence_count = 0
            state.empty_count = 0
            result = self._say(profile, "misrecognition", ACTION_RECOGNIZE, point)
        else:
            state.silence_count = 0
            state.empty_count = 0
            if point == POINT_CONFIRM:
                result = self._handle_confirmation(state, text, profile)
            else:
                result = self._handle_question(state, text, profile)

        # Разговор дошёл до конца (перевод на специалиста или на продажи) —
        # его состояние больше не понадобится, держать его в памяти дальше
        # незачем. Та же блокировка, что и в _session(): удаление должно
        # быть взаимно исключено с проверкой-вытеснением-вставкой оттуда,
        # иначе смысла в блокировке там нет.
        if self._reaches(result, POINT_FINISHED):
            with self._sessions_lock:
                self._sessions.pop(linked_id, None)
        return result

    @staticmethod
    def _is_scrap_for_search(text: str, point: str) -> bool:
        """Обрывок, которым тему не называют.

        Правило касается только пути «клиент назвал тему». В точке
        подтверждения оно не действует вовсе: там та же самая реплика — не
        название темы, а ответ на вопрос бота, и «не» обязано и дальше
        означать отказ (заказчик подтвердил, что это разговорное «нет», а не
        ошибка распознавания). Одно слово в одной точке разговора осмысленно,
        в другой — шум, и различать их можно только по точке.
        """
        if point == POINT_CONFIRM:
            return False
        return not any(
            len(word) >= MIN_SEARCHABLE_WORD_LETTERS for word in _LETTERS_RE.findall(text)
        )

    @staticmethod
    def _is_filler_only(text: str, point: str) -> bool:
        """Вежливый зачин без единого слова о деле.

        В точке подтверждения не действует по той же причине, что и правило об
        обрывках: там та же реплика — не название темы, а ответ на вопрос бота.
        """
        if point == POINT_CONFIRM:
            return False
        words = _LETTERS_RE.findall(text.lower().replace("ё", "е"))
        return bool(words) and all(word in FILLER_WORDS for word in words)

    @staticmethod
    def _reaches(result: List[Dict[str, str]], point: str) -> bool:
        return any(item.get("Key") == "ConversationPoint" and item.get("Value") == point for item in result)

    def _handle_question(
        self, state: _SessionState, text: str, profile: LineProfile
    ) -> List[Dict[str, str]]:
        # best_match() кодирует запрос эмбеддером — дорогая операция,
        # которую нельзя звать дважды на одну реплику (Important из
        # повторного ревью: раньше здесь звался search() ПОСЛЕ отдельного
        # вызова best_match() для лога — то же самое кодирование запроса
        # считалось заново, и speech_end->dialog_done оказывался завышен
        # примерно вдвое, хотя измеряется именно ради честной цифры этого
        # отрезка). Получаем лучшее совпадение один раз, логируем его и на
        # нём же принимаем решение — повторного обращения к поиску нет.
        resolution = self._knowledge.resolve(text) if text else None
        match = (resolution.record, resolution.score) if resolution and resolution.record else None
        self._log_similarity(text, match)
        self._log_vote(resolution)

        # Кому верить, решает база знаний (KnowledgeBase.resolve): соседям по
        # корпусу живых реплик, если они уверены, иначе порогу по формулировке.
        found = match if resolution is not None and resolution.trusted else None
        if found is None:
            # Промах по порогу — ещё не повод звать человека. Сначала просим
            # сказать иначе и слушаем дальше, оставаясь в той же точке
            # разговора. Вопрос при этом никуда не записываем: если клиент
            # переформулирует и тема найдётся, писать в справочник нечего —
            # бот справился сам.
            if state.reask_count < QUESTION_REASK_ATTEMPTS:
                state.reask_count += 1
                log.info(
                    "Тема не найдена — просим переформулировать вопрос (переспрос %s из %s)",
                    state.reask_count, QUESTION_REASK_ATTEMPTS,
                )
                # Запись найденной темы сбрасываем: клиент сейчас назовёт
                # поломку заново, и старое совпадение к его новым словам
                # отношения не имеет.
                state.record = None
                return self._say(profile, "misrecognition", ACTION_RECOGNIZE, POINT_ASK_QUESTION)

            if text:
                self._knowledge.add(text)
            # Совпадение ниже порога всё равно отдаём наружу: по нему потом
            # разбирают, промахнулись мы чуть-чуть или не поняли вопрос вовсе.
            # Но только как справку — тип оборудования по нему не проставляется.
            return self._transfer(
                profile, self._support_exten, match=match, trusted=False, unknown_question=True, state=state
            )

        record, score = found
        if not record.clarifying_question:
            # Уточнять нечего, переводим сразу и туда же, куда и раньше — но
            # тема разговора известна, и обращение в ERP должно её получить.
            return self._transfer(profile, self._support_exten, match=found, trusted=True, state=state)

        state.record = record
        state.score = score
        state.question_text = text
        # Уточняющий вопрос всегда синтезируется: он живёт в базе знаний, а
        # записанные аудио есть только у служебных фраз группы линий.
        return self._speak(profile, record.clarifying_question, ACTION_RECOGNIZE, POINT_CONFIRM)

    def _log_similarity(self, text: str, match: Optional[Any]) -> None:
        # Порог близости — главный настроечный параметр прототипа, который
        # подбирается на живых звонках (см. финальное ревью). Раньше мера
        # близости при промахе просто терялась, а при попадании не
        # логировалась — после звонка было видно только "перевели на
        # сопровождение", без понимания, был ли это промах чуть ниже порога
        # или модель вообще не поняла вопрос. Логируем обязательно в обеих
        # ветках, независимо от порога. match вычисляется вызывающей
        # стороной один раз (best_match()) и передаётся сюда готовым — эта
        # функция сама эмбеддер не дёргает.
        if not text:
            return
        if match is None:
            log.info("SIMILARITY: база знаний пуста, сравнивать не с чем | question=%r", text)
            return
        record, score = match
        threshold = self._knowledge.threshold
        verdict = "above threshold" if score >= threshold else "below threshold"
        log.info(
            "SIMILARITY %.4f (threshold=%.4f, %s) | question=%r | matched=%r",
            score, threshold, verdict, text, record.question,
        )

    @staticmethod
    def _log_vote(resolution: Optional[Any]) -> None:
        # Голос корпуса пишем всегда, когда он есть: по нему разбирают, кто
        # решил и почему — соседи или формулировка, — и подбирают порог
        # уверенности так же, как порог близости.
        vote = getattr(resolution, "vote", None)
        if vote is None:
            return
        top = vote.neighbours[:3]
        log.info(
            "CORPUS direction=%s confidence=%.3f decided_by=%s | neighbours=%s",
            vote.direction_id, vote.confidence, resolution.source,
            "; ".join("%.3f %s [%s]" % (n.score, n.phrase, n.direction_id) for n in top),
        )

    def _exten_for(self, record, profile: LineProfile) -> str:
        """Куда переводить звонок по этой записи базы знаний.

        Основной путь — номер приёма самого телефонного направления. Их у
        направления два, и выбор между ними делает линия, а не тема: звонок с
        линии частного мастера уходит на номер для ЧМ, в отдел частных
        мастеров. Так же поступает боевой обработчик 13161
        (GoTo_OperatorRedirect): PMRForSingleMaster против PWR.

        Пустой номер для ЧМ — сопровождение, а не обычный номер направления.
        Подстановка увела бы клиента частного мастера в чужой отдел, и 13161
        её тоже не делает.

        Два старых сценария (продажи/сопровождение) оставлены ради обратной
        совместимости: на них написаны прежние записи и тесты.
        """
        if profile.is_private_master:
            return record.redirect_exten_pm or self._support_exten
        if record.redirect_exten:
            return record.redirect_exten
        if record.scenario == SCENARIO_SALES:
            return self._sales_exten
        return self._support_exten

    def _handle_confirmation(
        self, state: _SessionState, text: str, profile: LineProfile
    ) -> List[Dict[str, str]]:
        record = state.record
        if record is None:
            return self._transfer(profile, self._support_exten, state=state)

        # Варианты согласия и отказа правятся в той же группе линий, что и
        # фразы. Списки записи — то, чем живёт прежняя база из файла: своих
        # списков у неё нет вовсе.
        positive = profile.positive_answers or record.positive_answers
        negative = profile.negative_answers or record.negative_answers

        # Отказ проверяется первым. В списке согласий живут одиночные «нужно»,
        # «надо», «хочу», «ну» — и ответ «нет, мне нужно ремонт мясорубки»
        # засчитывался как «да» (обращения 268480915 и 268488949, 21.09.2026:
        # клиент сказал «нет», а бот соединил с холодильниками и клинингом).
        # Явное «нет» перевешивает любое попутное слово согласия.
        if self._matches(text, negative):
            if state.question_text and state.wrong_guess is None:
                state.wrong_guess = (state.question_text, record.question)
            state.record = None
            return self._say(profile, "wrong_guess", ACTION_RECOGNIZE, POINT_ASK_QUESTION)

        if self._matches(text, positive):
            exten = self._exten_for(record, profile)
            extra = self._with_wrong_guess(state, self._match_extra((record, state.score), trusted=True))
            return self._speak(
                profile, record.positive_reply, ACTION_REDIRECT, POINT_FINISHED,
                exten=exten, extra=extra,
            )

        # Ни «да», ни «нет». Раньше бот тут сразу просил переформулировать и
        # забывал тему — и следующее «да» клиента падало в пустоту (4-я волна
        # 01.10.2026: «вызвать сантехника» → вопрос → «техник» → «да» → бот
        # снова спрашивает, что интересует, клиент бросает трубку, 269164694;
        # «собрать мебель» → вопрос → «сборка мебели» → тот же вопрос по
        # второму кругу, 269162457). Теперь сначала смотрим, не назвал ли
        # клиент тему ещё раз: та же запись — это согласие, другая — задаём её
        # вопрос. Иначе один раз переспрашиваем «да или нет», не теряя темы.
        # Обрывок и вежливый зачин темой быть не могут — в поиск их не пускаем,
        # иначе случайная тема нашлась бы обязательно (см. _is_filler_only).
        resolution = None
        if text and not self._is_scrap_for_search(text, POINT_ASK_QUESTION) \
                and not self._is_filler_only(text, POINT_ASK_QUESTION):
            resolution = self._knowledge.resolve(text)
            self._log_vote(resolution)
        if resolution is not None and resolution.trusted and resolution.record is not None:
            if resolution.record.id == record.id:
                log.info("Ответ %r на подтверждение называет ту же тему — считаем согласием", text)
                exten = self._exten_for(record, profile)
                extra = self._with_wrong_guess(state, self._match_extra((record, state.score), trusted=True))
                return self._speak(
                    profile, record.positive_reply, ACTION_REDIRECT, POINT_FINISHED,
                    exten=exten, extra=extra,
                )
            if resolution.record.clarifying_question:
                log.info("Ответ %r на подтверждение называет другую тему — спрашиваем её", text)
                if state.question_text and state.wrong_guess is None:
                    state.wrong_guess = (state.question_text, record.question)
                state.record = resolution.record
                state.score = resolution.score
                state.question_text = text
                state.confirm_unclear = 0
                return self._speak(
                    profile, resolution.record.clarifying_question, ACTION_RECOGNIZE, POINT_CONFIRM
                )

        if state.confirm_unclear < CONFIRM_UNCLEAR_ATTEMPTS:
            state.confirm_unclear += 1
            log.info(
                "Ответ %r на подтверждение не понят — переспрашиваем да/нет (%s из %s)",
                text, state.confirm_unclear, CONFIRM_UNCLEAR_ATTEMPTS,
            )
            return self._say(profile, "confirm_not_heard", ACTION_RECOGNIZE, POINT_CONFIRM)

        # Второй непонятный ответ подряд: просим сказать иначе и возвращаем
        # разговор на второй круг, к вопросу клиента.
        state.record = None
        state.confirm_unclear = 0
        return self._say(profile, "misrecognition", ACTION_RECOGNIZE, POINT_ASK_QUESTION)

    @staticmethod
    def _matches(text: str, variants: List[str]) -> bool:
        if not text:
            return False
        words = _WORD_RE.findall(text.lower())
        if not words:
            return False
        for variant in variants:
            variant_words = _WORD_RE.findall(variant.lower())
            if not variant_words:
                continue
            if len(variant_words) == 1:
                # Однословный вариант — точное совпадение слова, без учёта пунктуации.
                if variant_words[0] in words:
                    return True
                continue
            # Многословный вариант — его слова должны идти в ответе подряд, в том же порядке.
            span = len(variant_words)
            for start in range(len(words) - span + 1):
                if words[start:start + span] == variant_words:
                    return True
        return False

    @staticmethod
    def _match_extra(
        match: Optional[Any], trusted: bool
    ) -> Optional[Dict[str, str]]:
        """Что известно про найденную запись — для обращения в ERP.

        AGI-скрипт заводит обращение на время звонка и заполняет его из
        ответа сервиса; всё, чего здесь нет, до ERP не доедет вообще.

        `trusted` разделяет два разных случая. Совпадение выше порога
        (или подтверждённое клиентом) — тема разговора определена, тип
        оборудования и направление можно проставлять в обращении.
        Совпадение ниже порога — справочные сведения для разбора звонков:
        код записи, её вопрос и мера близости уходят, а оборудование нет,
        иначе оператор увидит в обращении тему, в которую бот сам не
        поверил.
        """
        if match is None:
            return None
        record, score = match
        extra = {
            "KnowledgeRecordId": str(record.id or ""),
            "MatchedQuestion": record.question,
            "Similarity": "{0:.4f}".format(score),
        }
        if trusted:
            extra.update({
                "EquipmentType": record.equipment_type,
                # Код типа оборудования из справочника ERP. Пока его не было,
                # обработчик искал тип по названию строкой — единственное место
                # цепочки, где связь держалась на совпадении текста. Название
                # уходит по-прежнему: обработчик предпочитает код, а по названию
                # ищет только там, где кода нет (записи не про технику).
                "EquipmentTypeId": str(record.equipment_type_id or ""),
                "Scenario": record.scenario,
                # Код направления обработчик ERP кладёт в историю обращения.
                "TelephoneDirectionId": str(record.telephone_direction_id or ""),
            })
        return extra

    @staticmethod
    def _with_wrong_guess(state: Optional["_SessionState"], extra: Optional[Dict[str, str]]) -> Optional[Dict[str, str]]:
        """Дописать в ответ тему, которую бот угадал не так.

        Уходит с любым переводом: клиент после «нет» мог согласиться на другую
        тему, промолчать или так и не найтись — промах от этого промахом быть не
        перестаёт. AGI-скрипт по UnknownQuestionText шлёт в справочник именно
        эту реплику, а не последнюю услышанную.
        """
        if state is None or state.wrong_guess is None:
            return extra
        question, guessed = state.wrong_guess
        extra = dict(extra or {})
        extra["UnknownQuestion"] = "True"
        extra["UnknownQuestionText"] = question
        extra["WrongGuess"] = guessed
        return extra

    def _transfer(
        self,
        profile: LineProfile,
        exten: str,
        match: Optional[Any] = None,
        trusted: bool = False,
        unknown_question: bool = False,
        state: Optional["_SessionState"] = None,
    ) -> List[Dict[str, str]]:
        extra = self._with_wrong_guess(state, self._match_extra(match, trusted))
        if unknown_question:
            # Клиент задал вопрос, а подходящей записи не нашлось — этот вопрос
            # надо занести в справочник ERP на ручную разметку (UL-17568).
            # Признак ставит сервис, а не AGI-скрипт: только здесь известен
            # порог близости, и только отсюда видно, что перевод случился
            # именно из-за промаха, а не из-за молчания клиента. По пустому
            # типу оборудования это не вывести — у записей вроде «жалоба»
            # техники нет и без всякого промаха.
            extra = dict(extra or {})
            extra["UnknownQuestion"] = "True"
        return self._say(
            profile,
            "transfer",
            ACTION_REDIRECT,
            POINT_FINISHED,
            exten=exten,
            extra=extra,
        )

    def _keep_listening(self, point: str) -> List[Dict[str, str]]:
        """Ничего не произносить и остаться в той же точке разговора.

        Телефонный скрипт на пустой текст озвучки ничего не проигрывает и
        просто продолжает слушать — клиент даже не заметит, что бот на что-то
        среагировал.
        """
        return [
            {"Key": "Action", "Value": ACTION_RECOGNIZE},
            {"Key": "TextToSpeak", "Value": ""},
            {"Key": "FileToPlayback", "Value": ""},
            {"Key": "ConversationPoint", "Value": point},
            {"Key": "ConversationScenario", "Value": "AiAssistantPrototype"},
            {"Key": "RedirectExten", "Value": ""},
        ]

    def _say(
        self,
        profile: LineProfile,
        slot: str,
        action: str,
        point: str,
        exten: str = "",
        extra: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, str]]:
        """Произнести служебную фразу набора — ту, у которой бывает записанный файл."""
        return self._speak(
            profile,
            getattr(profile.phrases, slot),
            action,
            point,
            exten=exten,
            extra=extra,
            slot=slot,
        )

    def _speak(
        self,
        profile: LineProfile,
        text: str,
        action: str,
        point: str,
        exten: str = "",
        extra: Optional[Dict[str, str]] = None,
        slot: str = "",
    ) -> List[Dict[str, str]]:
        # Заранее записанный файл уже лежит на станции, и скачивать его
        # неоткуда — в отличие от имени файла кэша, которое скрипт тянет из
        # /tts. Различить их можно только явным признаком: ответ без него
        # старый скрипт читает ровно как раньше.
        station_file = profile.audio_files.get(slot, "") if slot else ""
        payload = {
            "Action": action,
            "TextToSpeak": text,
            "FileToPlayback": station_file or _playback_name(text, profile.audio_signature),
            "ConversationPoint": point,
            "ConversationScenario": "AiAssistantPrototype",
            "RedirectExten": exten,
            # Голос группы: скрипт передаёт его в /tts. Без этого фразу второй
            # группы синтезировали бы голосом первой, а закэшировалась бы она
            # на станции под именем со своей подписью — то есть навсегда.
            "Voice": profile.voice,
        }
        if station_file:
            payload["FileIsOnStation"] = "True"
        if extra:
            payload.update(extra)
        return dict_to_prms(payload)
