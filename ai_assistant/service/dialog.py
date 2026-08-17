"""Логика диалога прототипа.

Формат запроса и ответа повторяет ReturnConversationIntermediateResult3 из ERP:
список пар Key/Value. Когда логика переедет в обработчик, в AGI-скрипте
поменяется только адрес.
"""
import hashlib
import logging
import re
import threading
from dataclasses import dataclass
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


class DialogEngine:
    def __init__(
        self,
        knowledge,
        phrases: Phrases,
        support_exten: str,
        sales_exten: str,
        max_sessions: int = DEFAULT_MAX_SESSIONS,
        audio_signature: str = "",
    ):
        self._knowledge = knowledge
        self._phrases = phrases
        self._support_exten = support_exten
        self._sales_exten = sales_exten
        self._max_sessions = max_sessions
        # Модель синтеза и голос: попадают в имя файла, чтобы кэш на станции
        # обновился сам при их смене.
        self._audio_signature = audio_signature
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

        if point == POINT_START:
            result = self._speak(self._phrases.greeting, ACTION_RECOGNIZE, POINT_ASK_QUESTION)
        elif silence:
            state.silence_count += 1
            if state.silence_count >= 2:
                result = self._transfer(self._support_exten)
            else:
                result = self._speak(self._phrases.silence, ACTION_RECOGNIZE, point)
        elif not text:
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
            log.info("Пустой результат распознавания в точке %s — продолжаем слушать", point)
            result = self._keep_listening(point)
        else:
            state.silence_count = 0
            if point == POINT_CONFIRM:
                result = self._handle_confirmation(state, text)
            else:
                result = self._handle_question(state, text)

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
    def _reaches(result: List[Dict[str, str]], point: str) -> bool:
        return any(item.get("Key") == "ConversationPoint" and item.get("Value") == point for item in result)

    def _handle_question(self, state: _SessionState, text: str) -> List[Dict[str, str]]:
        # best_match() кодирует запрос эмбеддером — дорогая операция,
        # которую нельзя звать дважды на одну реплику (Important из
        # повторного ревью: раньше здесь звался search() ПОСЛЕ отдельного
        # вызова best_match() для лога — то же самое кодирование запроса
        # считалось заново, и speech_end->dialog_done оказывался завышен
        # примерно вдвое, хотя измеряется именно ради честной цифры этого
        # отрезка). Получаем лучшее совпадение один раз, логируем его и на
        # нём же принимаем решение — повторного обращения к поиску нет.
        match = self._knowledge.best_match(text) if text else None
        self._log_similarity(text, match)

        found = match if match is not None and match[1] >= self._knowledge.threshold else None
        if found is None:
            if text:
                self._knowledge.add(text)
            # Совпадение ниже порога всё равно отдаём наружу: по нему потом
            # разбирают, промахнулись мы чуть-чуть или не поняли вопрос вовсе.
            # Но только как справку — тип оборудования по нему не проставляется.
            return self._transfer(
                self._support_exten, match=match, trusted=False, unknown_question=True
            )

        record, score = found
        if not record.clarifying_question:
            # Уточнять нечего, переводим сразу и туда же, куда и раньше — но
            # тема разговора известна, и обращение в ERP должно её получить.
            return self._transfer(self._support_exten, match=found, trusted=True)

        state.record = record
        state.score = score
        return self._speak(record.clarifying_question, ACTION_RECOGNIZE, POINT_CONFIRM)

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

    def _exten_for(self, record) -> str:
        """Куда переводить звонок по этой записи базы знаний.

        Основной путь — номер приёма самого телефонного направления. Два
        старых сценария (продажи/сопровождение) оставлены ради обратной
        совместимости: на них написаны прежние записи и тесты.
        """
        if record.scenario == SCENARIO_DIRECTION and record.redirect_exten:
            return record.redirect_exten
        if record.redirect_exten:
            return record.redirect_exten
        if record.scenario == SCENARIO_SALES:
            return self._sales_exten
        return self._support_exten

    def _handle_confirmation(self, state: _SessionState, text: str) -> List[Dict[str, str]]:
        record = state.record
        if record is None:
            return self._transfer(self._support_exten)

        if self._matches(text, record.positive_answers):
            exten = self._exten_for(record)
            extra = self._match_extra((record, state.score), trusted=True)
            return self._speak(
                record.positive_reply, ACTION_REDIRECT, POINT_FINISHED, exten=exten, extra=extra
            )

        # Явное «нет» и нераспознанный ответ — разные случаи, и звучать должны
        # по-разному. При «нет» бот всё расслышал, но не угадал тему: логично
        # спросить, что нужно клиенту, а не просить его переформулировать.
        # Оба пути возвращают разговор на второй круг, к вопросу клиента.
        state.record = None
        if self._matches(text, record.negative_answers):
            return self._speak(self._phrases.wrong_guess, ACTION_RECOGNIZE, POINT_ASK_QUESTION)
        return self._speak(self._phrases.misrecognition, ACTION_RECOGNIZE, POINT_ASK_QUESTION)

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

    def _transfer(
        self,
        exten: str,
        match: Optional[Any] = None,
        trusted: bool = False,
        unknown_question: bool = False,
    ) -> List[Dict[str, str]]:
        extra = self._match_extra(match, trusted)
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
        return self._speak(
            self._phrases.transfer,
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

    def _speak(
        self,
        text: str,
        action: str,
        point: str,
        exten: str = "",
        extra: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, str]]:
        payload = {
            "Action": action,
            "TextToSpeak": text,
            "FileToPlayback": _playback_name(text, self._audio_signature),
            "ConversationPoint": point,
            "ConversationScenario": "AiAssistantPrototype",
            "RedirectExten": exten,
        }
        if extra:
            payload.update(extra)
        return dict_to_prms(payload)
