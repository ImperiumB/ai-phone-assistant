#!/usr/bin/python3
# coding=utf8
"""Тонкий AGI-клиент виртуального AI-помощника (UL-17568).

Логики диалога не содержит: гонит аудио в speech-сервис и исполняет присланное
действие. Все защиты перенесены из боевого recosintsite_V2.py, они выстраданы:
RLock вокруг agi.*, неблокирующая озвучка через background-команду самой
станции (собственных потоков озвучки скрипт не заводит), os._exit в
фатальном обработчике с попыткой взять agi-блокировку не дольше секунды,
Playback для синхронной озвучки против background для асинхронной, аварийный
перевод звонка на сопровождение при отказе речевого сервиса.

Реальные переводы (Goto) заперты за REAL_REDIRECT (по умолчанию False) —
прототип не должен дёргать живых операторов, см. РАЗВЁРТЫВАНИЕ.md.

ВНИМАНИЕ: исполняется под Python 3.9.2. Синтаксис 3.10+ не использовать.
"""
import os
import sys
import time
import traceback
import uuid
from dataclasses import dataclass
from threading import RLock
from typing import Any, Dict, List

import grpc
import requests

ACTION_RECOGNIZE = "Recognize"
ACTION_REDIRECT = "Redirect"
ACTION_HANGUP = "Hangup"

# Спецификация ("Сценарий звонка") прямо требует: реального перевода в
# очередь в прототипе нет — только запись в лог, иначе пока человек
# отлаживает бота, отделы продаж и сопровождения получают поток тестовых
# звонков. Выключатель — единственное место в скрипте, которое решает, идёт
# ли команда перехода Goto реально или только пишется в лог станции.
# Включать только после успешных замеров задержки/качества/нагрузки и
# предупреждения смен (описано в РАЗВЁРТЫВАНИЕ.md).
REAL_REDIRECT = True

# Заводить ли обращение в ERP на время звонка (UL-18797). Выключатель нужен для
# отладки самого разговора: с ним звонок идёт полностью мимо ERP, и в базе не
# копятся обращения от проб. Выключать только осознанно — при выключенном
# флаге ни обращения, ни истории, ни ухода в ПЦК при обрыве не будет.
ERP_INTEGRATION = True

# Адрес службы Aster2Service по умолчанию. Диалплан может задать свой через
# переменную канала.
#
# Значение снято с боевого лога станции (17.08.2026): именно по нему ходит
# recosintsite_V2 на каждом звонке. Брать его из запасного значения самого
# recosintsite_V2 нельзя — там "10.20.0.15:65", перепутанные куски двух
# разных адресов (хост .65 и порт 10001). В бою это не стреляет, потому что
# адрес всегда приезжает из ERP переменной канала, и опечатку никто не замечал.
#
# В ERP адрес не константа: обработчик 12818 собирает его как
# Server.GetServerIP() + ":3511/Aster2ServiceWebHttp". Переедет сервер —
# поменять здесь и в диалплане.
DEFAULT_ASTER2_SERVICE_ADDRESS = "10.20.0.12:3511/Aster2ServiceWebHttp"
ERP_ENDPOINT = "ReturnConversationIntermediateResult3"

# Пять секунд — это не «сколько не жалко», а предел, после которого молчание в
# трубке становится заметным. Обращение важно, но клиент важнее: не ответила
# ERP за это время — едем дальше без неё.
ERP_TIMEOUT_S = 5

# Точка разговора, в которой клиент отвечает на уточняющий вопрос бота
# («да», «нет»). Имя приходит от сервиса в ConversationPoint.
POINT_CONFIRM = "Confirm"

EVENT_CALL_START = "AiAssistantCallStart"
EVENT_EQUIPMENT = "AiAssistantEquipment"
EVENT_TRANSFER = "AiAssistantTransfer"
EVENT_UNKNOWN = "AiAssistantUnknown"

# Причина, по которой клиент остался без ответа по НАШЕЙ вине (UL-18797).
# Только за неё положен обратный звонок: клиент, который сам передумал и бросил
# трубку, догонять себя звонком не просил, а перезванивай мы за любой сброс —
# достаточно насбрасывать сотню звонков, чтобы получить сотню обращений и сотню
# исходящих от операторов. Нашу вину снаружи не подделать, спамить сбросами
# бессмысленно.
#
# Причину кладём в переменную канала: скрипт последней воли поднимается
# отдельным процессом и нашей памяти не видит, а при обрыве канала мы умираем
# мгновенно (SIGHUP, SIG_DFL). Он же передаёт её в ERP ключом `failureReason`,
# и по заполненному ключу обращение уходит в ПЦК. Пусто — в ПЦК не уводим.
FAILURE_REASON_VAR = "AiFailureReason"

# Тексты попадают в историю обращения, их читает оператор: коротко и по-русски,
# без кодов и английских слов.
REASON_SERVICE_UNAVAILABLE = "отказал речевой сервис"
REASON_SCRIPT_ERROR = "ошибка в скрипте"
REASON_CALL_TIMEOUT = "превышена длительность разговора"
REASON_SPEECH_FAILED = "не удалось озвучить ответ"

CHUNK_SIZE = 8000  # 4000 отсчётов = 0,5 секунды при 8000 Гц
CALL_TIMEOUT_S = 120
AUDIO_CACHE_DIR = "/var/lib/asterisk/sounds/ai_bot/cache"

# Папка, где на станции лежат заранее записанные аудиофайлы. В справочнике ERP
# путь хранится относительным, и эту папку к нему приклеивает сам скрипт —
# ровно так же делает боевой бот (recosintsite_V2.py, audio_path_rec).
RECORDED_AUDIO_DIR = "/var/lib/asterisk/sounds/audioivr20/"

# Аварийный путь на случай, если речевой сервис недоступен целиком: заранее
# записанная фраза (не синтезируется на лету — сервис же и лежит) и перевод
# на отдел сопровождения, чтобы клиент услышал обычный перевод, а не тишину.
SERVICE_UNAVAILABLE_SOUND = "/var/lib/asterisk/sounds/ai_bot/service_unavailable"
# Номер приёма ТН 17 «Сопровождение». Тот же номер сервис берёт из посылки
# полем support_exten и переводит на него все непонятные звонки. Здесь он
# продублирован намеренно: этот путь работает ровно тогда, когда сервис не
# отвечает, — прочитать посылку неоткуда, а спросить не у кого. Если номер ТН
# 17 в справочнике поменяют, править придётся оба места.
SUPPORT_FALLBACK_EXTEN = "7082"

# Сколько ждать agi-блокировку на вежливый отбой при завершении процесса.
# Если не получилось за это время — канал занят зависшим потоком озвучки,
# и вежливый hangup пропускается в пользу немедленного os._exit.
LOCK_ACQUIRE_TIMEOUT_S = 1.0

_agi_lock = RLock()  # AGI — построчный протокол над stdin/stdout, не потокобезопасен
_redirect_done = False


@dataclass
class DialogAnswer:
    action: str
    text_to_speak: str
    file_to_playback: str
    conversation_point: str
    redirect_exten: str
    # Ниже — то, что нужно только обращению в ERP. Поля со значениями по
    # умолчанию: ответ сервиса старой сборки (без этих ключей) обязан
    # разбираться без ошибок, разговор от них не зависит.
    equipment_type: str = ""
    #: Код типа оборудования в справочнике ERP. Строкой, как и всё остальное:
    #: значения уходят в Hashtable ERP как есть, число там всё равно станет
    #: текстом. Пустой — у записи кода нет (тема не про технику).
    equipment_type_id: str = ""
    scenario: str = ""
    telephone_direction_id: str = ""
    knowledge_record_id: str = ""
    matched_question: str = ""
    similarity: str = ""
    #: Сервис не нашёл подходящей записи: мера близости ниже порога либо база
    #: пуста. Единственное поле ответа не строкой — это признак, а не значение,
    #: и решение по нему принимается прямо здесь, в скрипте.
    unknown_question: bool = False
    #: Заранее записанный аудиофайл вместо синтеза: `file_to_playback` — это не
    #: имя файла кэша, а путь к уже лежащему на станции файлу. Скачивать его
    #: неоткуда, играется как есть. Признака нет — поведение прежнее, поэтому
    #: новый скрипт работает и со старым сервисом.
    file_is_on_station: bool = False
    #: Голос группы линий. Уходит в /tts: у каждой группы он свой, а сервис по
    #: одному тексту не поймёт, чью фразу у него просят. Пусто — синтезируем
    #: тем, что настроено на самом сервисе (в том числе со старым сервисом,
    #: который голос не присылает вовсе).
    voice: str = ""


def parse_dialog_response(items: List[Dict[str, Any]]) -> DialogAnswer:
    pairs = {}
    for item in items:
        pairs[str(item.get("Key", ""))] = str(item.get("Value", ""))
    return DialogAnswer(
        action=pairs.get("Action", ""),
        text_to_speak=pairs.get("TextToSpeak", ""),
        file_to_playback=pairs.get("FileToPlayback", ""),
        conversation_point=pairs.get("ConversationPoint", ""),
        redirect_exten=pairs.get("RedirectExten", ""),
        equipment_type=pairs.get("EquipmentType", ""),
        equipment_type_id=pairs.get("EquipmentTypeId", ""),
        scenario=pairs.get("Scenario", ""),
        telephone_direction_id=pairs.get("TelephoneDirectionId", ""),
        knowledge_record_id=pairs.get("KnowledgeRecordId", ""),
        matched_question=pairs.get("MatchedQuestion", ""),
        similarity=pairs.get("Similarity", ""),
        unknown_question=pairs.get("UnknownQuestion", "").strip().lower() in ("true", "1", "yes"),
        file_is_on_station=pairs.get("FileIsOnStation", "").strip().lower() in ("true", "1", "yes"),
        voice=pairs.get("Voice", ""),
    )


def build_dialog_request(linked_id, point, text, silence, dialed_number=""):
    # type: (str, str, str, bool, str) -> Dict[str, Any]
    """Запрос к сервису. Набранный номер — тем же ключом, что и в событиях ERP:
    по нему сервис выбирает фразы, голос и записанные аудио группы линий."""
    return {
        "prms": [
            {"Key": "linkedId", "Value": linked_id},
            {"Key": "conversationPoint", "Value": point},
            {"Key": "recognizedText", "Value": text},
            {"Key": "silenceDetected", "Value": "True" if silence else "False"},
            {"Key": "dialedNumber", "Value": dialed_number},
        ]
    }


def plays_from_station(answer):
    # type: (DialogAnswer) -> bool
    """Файл уже лежит на станции и скачивать его не надо.

    Пустой путь при поднятом признаке — не поломка, а ненастроенная фраза:
    синтезируем её как обычно.
    """
    return bool(answer.file_is_on_station and answer.file_to_playback)


def station_playback_path(raw):
    # type: (str) -> str
    """Путь записанного файла в том виде, в каком его ждёт Астериск.

    В справочнике ERP путь хранится относительным
    (`VoicesOKK\\voice-a\\2_spich.wav`) и сам по себе станции ничего
    не говорит: файлы лежат в отдельной папке, и боевой бот приклеивает её
    точно так же (recosintsite_V2.py, `audio_path_rec`). Без этой склейки
    Астериск файл не найдёт, а клиент услышит тишину вместо приветствия —
    молча, потому что ненайденный файл не считается ошибкой воспроизведения.

    Разделители в справочнике обратные, их надо развернуть; расширение
    Астериск подставляет сам и с ним искал бы «Actual.wav.wav».
    """
    path = str(raw or "").strip().replace("\\", "/")
    if path.lower().endswith(".wav"):
        path = path[:-4]
    if not path:
        return ""
    # Абсолютный путь оставляем как есть: значит его задали осознанно.
    if path.startswith("/"):
        return path
    return RECORDED_AUDIO_DIR + path.lstrip("/")


def tts_params(text, voice):
    # type: (str, str) -> Dict[str, str]
    """Чем просить сервис синтезировать фразу.

    Голос называем явно: у каждой группы линий он свой, а сервис по одному
    тексту не поймёт, чью фразу у него просят, и синтезировал бы голосом
    набора по умолчанию. Пусто — решает сам сервис, как и раньше.
    """
    params = {"text": text}
    if voice:
        params["voice_name"] = voice
    return params


def decide_next_step(answer: DialogAnswer) -> str:
    if answer.action == ACTION_RECOGNIZE:
        return "listen"
    if answer.action == ACTION_REDIRECT:
        return "redirect"
    if answer.action == ACTION_HANGUP:
        return "hangup"
    raise ValueError("Неизвестное действие: {0}".format(answer.action))


def decide_failure_step(error):
    # type: (BaseException) -> str
    """Различает отказ связи с речевым сервисом от программной ошибки.

    Обрыв HTTP-запроса к /dialog или /tts (requests) и обрыв gRPC-стрима
    распознавания — это отказ сервиса, клиент не должен слышать тишину и
    обрыв: ведём на аварийный перевод ("failover"). Любая другая ошибка —
    баг в нашем коде, её маскировать нельзя, она должна уйти в общий
    перехват ("reraise").
    """
    if isinstance(error, (requests.exceptions.RequestException, grpc.RpcError)):
        return "failover"
    return "reraise"


# --- Обращение в ERP (UL-18797) ----------------------------------------------
#
# Своей двери из телефонии в ERP у сервиса нет: запрос уходит в Aster2Service,
# та без разбора перекладывает пары Key/Value в Hashtable и отдаёт обработчику
# 13161, а он по префиксу eventType переправляет всё в 15422. Поэтому формат
# тела ровно такой же, как у /dialog, и поэтому же ключи можно слать любые
# свои — служба ничего не фильтрует.


@dataclass
class ErpAnswer:
    result: str
    document_id: str
    message: str
    #: Готовое имя звонящего для канала — по нему у оператора открывается
    #: карточка обращения (UL-18819). Собирает его ERP целиком, вместе с
    #: константой подмены; здесь оно только хранится. Значение по умолчанию
    #: обязательно: ответ обработчика старой сборки этого ключа не содержит.
    caller_id_name: str = ""

    @property
    def ok(self):
        # type: () -> bool
        return self.result.upper() == "OK"


def erp_url(service_address):
    # type: (str) -> str
    return "http://{0}/{1}".format(service_address.rstrip("/"), ERP_ENDPOINT)


def build_erp_request(event_type, values):
    # type: (str, List[Any]) -> Dict[str, Any]
    """Тело запроса к ERP из пар «ключ-значение».

    Значения всегда строками: на той стороне они попадают в Hashtable как
    есть, а числа из JSON приезжают дробными и потом разбираются вручную.
    Пустые значения не отправляются вовсе — обработчику они ничего не
    сообщают, а в логе станции мешают читать.
    """
    prms = [{"Key": "eventType", "Value": event_type}]
    for key, value in values:
        text = "" if value is None else str(value)
        if text:
            prms.append({"Key": key, "Value": text})
    return {"prms": prms}


def build_call_start_request(linked_id, dialed_number, caller_phone):
    # type: (str, str, str) -> Dict[str, Any]
    """Звонок принят. dialedNumber обязателен: по нему ERP ищет телефон линии,
    без него обращение не создастся вовсе."""
    return build_erp_request(EVENT_CALL_START, [
        ("linkedId", linked_id),
        ("dialedNumber", dialed_number),
        ("callerPhone", caller_phone),
    ])


def build_equipment_request(document_id, recognized_text, equipment_type_name, direction_name,
                            equipment_type_id=""):
    # type: (Any, str, str, str, Any) -> Dict[str, Any]
    """Бот понял тему разговора.

    Код типа оборудования приходит из справочника ERP вместе с базой знаний.
    Название отправляем по-прежнему: обработчик предпочитает код, а по
    названию ищет тип строкой только там, где кода нет — это единственное
    место всей цепочки, где связь держится на совпадении текста, и с приходом
    кода оно отмирает.
    """
    return build_erp_request(EVENT_EQUIPMENT, [
        ("documentId", document_id),
        ("recognizedText", recognized_text),
        ("equipmentTypeId", equipment_type_id),
        ("equipmentTypeName", equipment_type_name),
        ("directionName", direction_name),
    ])


def build_transfer_request(document_id, redirect_exten, direction_name, recognized_text):
    # type: (Any, str, str, str) -> Dict[str, Any]
    return build_erp_request(EVENT_TRANSFER, [
        ("documentId", document_id),
        ("redirectExten", redirect_exten),
        ("directionName", direction_name),
        ("recognizedText", recognized_text),
    ])


def build_unknown_request(document_id, recognized_text):
    # type: (Any, str) -> Dict[str, Any]
    """Бот не нашёл ответа — вопрос клиента едет в справочник ERP.

    Отсекать короткие тексты и точные повторы не нужно: этим занимается сам
    обработчик, и делает это по всей базе, а не по одному звонку.
    """
    return build_erp_request(EVENT_UNKNOWN, [
        ("documentId", document_id),
        ("recognizedText", recognized_text),
    ])


def parse_erp_response(items):
    # type: (Any) -> ErpAnswer
    """Ответ ERP — такой же список пар. Разбор не имеет права падать: что бы
    ни пришло, разговор продолжается."""
    pairs = {}
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                pairs[str(item.get("Key", ""))] = str(item.get("Value", ""))
    document_id = pairs.get("documentId", "")
    if document_id in ("0", "None"):
        document_id = ""  # нулевой код — это отсутствие обращения, а не его номер
    return ErpAnswer(
        result=pairs.get("Result", ""),
        document_id=document_id,
        message=pairs.get("Message", ""),
        caller_id_name=pairs.get("callerIdName", ""),
    )


def caller_id_name_command(caller_id_name):
    # type: (Any) -> str
    """Аргумент команды Set, подставляющей имя звонящего в канал (UL-18819).

    Имя — единственное, по чему у оператора открывается карточка обращения:
    клиент оператора (AsterModule, WorkForm) вырезает из полученного имени
    константу «Текстовая подмена звонка» и берёт остаток вида DOC<код> за код
    обращения. Поэтому имя не чистим и не досуживаем — что прислала ERP, то и
    ставим: любое искажение (лишний strip, свои пробелы вместо табов) карточку
    не откроет.

    Имени нет — команды нет: перевод важнее карточки, и звонок в этом случае
    уходит оператору ровно так же, как уходил раньше.
    """
    if not caller_id_name or not str(caller_id_name).strip():
        return ""
    return "CALLERID(name)={0}".format(caller_id_name)


def remember_recognized_text(previous, point, text):
    # type: (str, str, str) -> str
    """Какую реплику показывать оператору как вопрос клиента.

    В обращение и в ПЦК уходит одна реплика, и это должен быть вопрос, а не
    «да» в ответ на уточнение бота: оператор, которому досталось обращение с
    текстом «да», не узнает из него ничего. Поэтому ответ в точке
    подтверждения запомненный вопрос не затирает.
    """
    if not text:
        return previous
    if point == POINT_CONFIRM:
        return previous
    return text


def direction_name_of(answer):
    # type: (DialogAnswer) -> str
    """Название телефонного направления для истории обращения.

    Отдельного поля с названием направления у сервиса нет: в записи базы
    знаний лежит название типа оборудования, и оно дословно совпадает с
    названием направления в справочнике ERP — сверено по всем 27 записям
    боевой базы, у которых направление проставлено (53 «Стиральные машины»,
    27 «БТ-МБТ (ХД/Кофе/УБТ/Пылесосы/Швейки)» и так далее, расхождений нет).
    Когда база знаний переедет в справочники ERP, название направления
    начнёт приходить своим ключом, и менять придётся только эту функцию.
    """
    return answer.equipment_type


def should_send_equipment(answer, already_sent):
    # type: (DialogAnswer, bool) -> bool
    """Тема разговора стала известна и в ERP ещё не уходила.

    Признак — появление в ответе сервиса оборудования или направления: до
    подтверждения клиентом сервис их не присылает.
    """
    if already_sent:
        return False
    return bool(answer.equipment_type or answer.equipment_type_id or answer.telephone_direction_id)


def should_send_unknown_question(answer, point, recognized_text, silence):
    # type: (Any, str, str, bool) -> bool
    """Стоит ли записывать эту реплику в базу знаний ERP как неопознанный вопрос.

    На сопровождение звонок уходит по нескольким разным поводам, и только один
    из них годится для справочника: клиент произнёс осмысленную фразу, а
    подходящей записи под неё не нашлось. Остальные поводы — не он, и каждый
    отсекается здесь своим условием:

    * `answer is None` — речевой сервис не ответил вовсе, звонок уводит
      аварийный перевод (failover_to_support). Вопроса никто не расслышал.
    * `silence` — клиент промолчал дважды. Реплики не было.
    * пустой `recognized_text` — распозналось пусто: щелчок в линии, шорох,
      кашель. Вопроса опять же не прозвучало.
    * точка `Confirm` — клиент отвечает «да»/«нет» на уточняющий вопрос бота.
      Сам вопрос прозвучал раньше и тогда же был найден в базе; ответ «нет»
      разговор не заканчивает — бот переспрашивает, и следующая реплика
      клиента либо найдётся, либо честно уедет сюда промахом по порогу.
    * действие не `Redirect` — разговор ещё идёт, итог не известен.
    * `unknown_question` — это уже слово самого сервиса: перевод случился
      из-за промаха по порогу. Порог знает только он.
    """
    if answer is None:
        return False
    if silence or not recognized_text.strip():
        return False
    if point == POINT_CONFIRM:
        return False
    if answer.action != ACTION_REDIRECT:
        return False
    return bool(answer.unknown_question)


def send_to_erp(service_address, body, post=None, log=None):
    # type: (str, Dict[str, Any], Any, Any) -> Any
    """Отправить событие в ERP и разобрать ответ. Никогда не бросает.

    Ровно та же логика, что у боевого скрипта: обращение — вещь полезная, но
    ради него нельзя ни уронить разговор, ни заставить клиента слушать
    тишину. Любой отказ — строка в лог станции и едем дальше.
    """
    if not ERP_INTEGRATION:
        return None
    if post is None:
        post = requests.post
    url = erp_url(service_address)
    try:
        response = post(url, json=body, timeout=ERP_TIMEOUT_S)
        if response.status_code != 200:
            if log:
                log("ERP: статус ответа {0} на {1}".format(response.status_code, url))
            return None
        return parse_erp_response(response.json())
    except Exception as error:
        if log:
            log("ERP ERROR ({0}): {1}".format(url, error))
        return None


def _atomic_write(path, content):
    # type: (str, bytes) -> None
    """Атомарная запись с уникальным именем временного файла.

    Та же гонка, что уже была найдена и починена на сервере
    (ai_assistant/service/tts.py, write_wav_8k): временный файл раньше
    назывался одинаково для всех звонков ("<путь>.tmp"). Два одновременных
    звонка, обоим нужна ещё не закэшированная фраза — первый переименовывает
    файл, второй получает ошибку на открытии/записи чужого ".tmp", которая
    молча проглатывалась в speak() — один из абонентов ничего не слышал.
    Параллельные звонки — обязательный сценарий: без них не снять метрику
    нагрузки (третья цифра прототипа).

    Уникальное имя убирает коллизию на самом временном файле, но не решает
    всё целиком: если два потока одновременно делают os.replace(...,
    <тот же итоговый путь>), один из них иногда всё равно получает
    PermissionError на Windows — такую ошибку на os.replace не считаем
    падением: если итоговый файл на месте, значит другой поток уже успел
    его туда положить, это нормальный исход гонки, а не ошибка.
    """
    tmp_path = "{0}.{1}.tmp".format(path, uuid.uuid4().hex)
    try:
        with open(tmp_path, "wb") as handle:
            handle.write(content)
        try:
            os.replace(tmp_path, path)
        except OSError:
            if not os.path.exists(path):
                raise  # не гонка с другим писателем, а настоящая ошибка
    finally:
        try:
            os.remove(tmp_path)
        except FileNotFoundError:
            pass  # обычный случай: файл уже переименован


# --- Дальше идёт часть, работающая только внутри Asterisk ---------------------


def _main():  # pragma: no cover - требует живого канала Asterisk
    import asterisk.agi
    from func_timeout import FunctionTimedOut, func_timeout

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import speech_pb2
    import speech_pb2_grpc

    agi = asterisk.agi.AGI()

    import signal
    # pyst2 ставит свой обработчик SIGHUP, который не срабатывает при блокировке
    # в C-вызове. SIG_DFL: на hangup канала умираем мгновенно.
    signal.signal(signal.SIGHUP, signal.SIG_DFL)

    def log_it(message):
        try:
            with _agi_lock:
                agi.verbose(str(message).replace("\n", " | ").replace('"', "'"))
        except Exception:
            pass

    def get_var(name, default=""):
        try:
            with _agi_lock:
                value = agi.get_variable(name)
            return value if value else default
        except Exception:
            return default

    def set_var(name, value):
        try:
            with _agi_lock:
                agi.set_variable(name, value)
        except Exception as error:
            log_it("SET VAR {0} ERROR: {1}".format(name, error))

    def set_failure_reason(reason):
        """Назвать причину, по которой клиент остался без ответа по нашей вине.

        Вызывается только на путях отказа нашей стороны: по заполненной причине
        обращение уходит в ПЦК и оператор перезванивает. Брошенная клиентом
        трубка причиной не является — там переменная так и остаётся пустой.
        """
        log_it("FAILURE REASON: {0}".format(reason))
        set_var(FAILURE_REASON_VAR, reason)

    def clear_failure_reason():
        set_var(FAILURE_REASON_VAR, "")

    service_host = get_var("SpeechServiceHost", "10.20.0.10")
    grpc_port = get_var("SpeechServiceGrpcPort", "50051")
    http_port = get_var("SpeechServiceHttpPort", "8080")
    linked_id = agi.env.get("agi_uniqueid", "")
    # Набранный номер: по нему ERP ищет телефон линии, поэтому без него
    # обращение не создастся вовсе. По нему же речевой сервис выбирает фразы,
    # голос и записанные аудио — галочка «Виртуальный AI помощник» стоит на
    # номерах из разных групп линий, и у каждой группы они свои.
    dialed_number = agi.env.get("agi_extension", "")
    caller_phone = agi.env.get("agi_callerid", "")
    aster2_address = get_var("Aster2ServiceAddress", DEFAULT_ASTER2_SERVICE_ADDRESS)
    http_base = "http://{0}:{1}".format(service_host, http_port)

    state = {
        "point": "Start",
        # Код созданного обращения и то, что уже успели про него сообщить.
        "document_id": "",
        # Готовое имя звонящего от ERP: по нему у оператора открывается
        # карточка обращения, ставится в канал перед переводом (UL-18819).
        "caller_id_name": "",
        "equipment_sent": False,
        "last_text": "",
        # Точка, реплика и признак молчания того шага, ответ на который сейчас
        # разбирается. Ответ сервиса уводит разговор в следующую точку, а
        # решение по неопознанному вопросу принимается по той, в которой
        # клиент говорил.
        "asked_point": "Start",
        "asked_text": "",
        "asked_silence": False,
    }

    def fetch_audio(text, file_name, voice=""):
        target = os.path.join(AUDIO_CACHE_DIR, file_name + ".wav")
        if os.path.exists(target):
            return target
        if not os.path.isdir(AUDIO_CACHE_DIR):
            os.makedirs(AUDIO_CACHE_DIR)
        # Сквозная разбивка задержки (речевой сервис не знает linkedId в
        # /tts — контракт не меняем, см. РАЗВЁРТЫВАНИЕ.md), поэтому метки
        # вокруг скачивания звука пишем здесь, в логе станции: человек
        # сложит итог из этих меток и лога сервиса вручную.
        download_start = time.time()
        log_it("TIMING download_start {0:.3f}".format(download_start))
        response = requests.get(
            http_base + "/tts", params=tts_params(text, voice), timeout=30
        )
        response.raise_for_status()
        _atomic_write(target, response.content)
        download_done = time.time()
        log_it(
            "TIMING download_done {0:.3f} ({1:.1f} ms)".format(
                download_done, (download_done - download_start) * 1000.0
            )
        )
        return target

    def speak(answer, blocking):
        # Записанный файл озвучивается и без текста: текст к нему приезжает
        # только ради лога станции.
        if not answer.text_to_speak and not plays_from_station(answer):
            return
        if plays_from_station(answer):
            # Файл уже лежит на станции — скачивать его неоткуда и незачем.
            path = station_playback_path(answer.file_to_playback)
        else:
            try:
                fetch_audio(answer.text_to_speak, answer.file_to_playback, answer.voice)
            except Exception as error:
                log_it("TTS ERROR: {0}".format(error))
                # Ответ у бота был, но клиент его не услышал — вместо ответа
                # тишина, и виноваты в этом мы, а не он.
                set_failure_reason(REASON_SPEECH_FAILED)
                return
            path = os.path.join(AUDIO_CACHE_DIR, answer.file_to_playback)
        # Playback блокирует до конца фразы — обязателен перед Goto и Hangup.
        application = "Playback" if blocking else "background"
        log_it("TIMING playback_start {0:.3f}".format(time.time()))
        with _agi_lock:
            agi.appexec(application, path)
        # Фраза пошла в трубку — сорвавшийся ранее синтез перестал быть
        # причиной: иначе один промах в середине разговора увёл бы в ПЦК
        # звонок, в котором клиент всё-таки получил ответ.
        clear_failure_reason()

    def ask_dialog(text, silence):
        remembered = remember_recognized_text(state["last_text"], state["point"], text)
        if remembered != state["last_text"]:
            state["last_text"] = remembered
            # Скрипт последней воли поднимается отдельным процессом и нашей
            # памяти не видит: вопрос клиента он возьмёт только отсюда.
            set_var("LastRecognizedText", remembered)
        state["asked_point"] = state["point"]
        state["asked_text"] = text
        state["asked_silence"] = silence
        payload = build_dialog_request(linked_id, state["point"], text, silence, dialed_number)
        response = requests.post(http_base + "/dialog", json=payload, timeout=15)
        response.raise_for_status()
        answer = parse_dialog_response(response.json())
        if answer.conversation_point:
            state["point"] = answer.conversation_point
        return answer

    def open_erp_case():
        """Завести обращение в ERP. Звонок при любом отказе идёт дальше."""
        if not ERP_INTEGRATION:
            # Иначе дальше в лог уйдёт «обращение не создано», и человек,
            # отлаживающий разговор, будет искать поломку там, где её нет.
            log_it("ERP: интеграция выключена (ERP_INTEGRATION=False)")
            return
        erp_answer = send_to_erp(
            aster2_address,
            build_call_start_request(linked_id, dialed_number, caller_phone),
            log=log_it,
        )
        if erp_answer is None or not erp_answer.document_id:
            log_it("ERP: обращение не создано ({0})".format(
                erp_answer.message if erp_answer else "нет ответа"))
            return
        state["document_id"] = erp_answer.document_id
        state["caller_id_name"] = erp_answer.caller_id_name
        # Имя ставим сразу, а не только перед переводом. У боевого бота оно
        # живёт на канале с первой секунды: там звонок исходящий, и ERP создаёт
        # канал уже с именем. У нас звонок входящий, ERP видит канал с самого
        # начала под настоящим именем клиента и вполне может его запомнить —
        # подмена за секунду до перевода тогда опаздывает. Ставим сейчас, а
        # перед Goto повторяем: лишний Set ничего не стоит, а пропущенный
        # оставляет оператора без карточки.
        with _agi_lock:
            push_caller_id_name()
        # Тем же способом код обращения достаётся скрипту последней воли:
        # своей памяти основного скрипта он не видит, а при обрыве канала
        # основной скрипт умирает мгновенно и сообщить ничего не успевает.
        set_var("documentId", erp_answer.document_id)
        log_it("ERP: обращение {0} создано".format(erp_answer.document_id))

    def report_equipment(answer):
        if not state["document_id"] or not should_send_equipment(answer, state["equipment_sent"]):
            return
        send_to_erp(
            aster2_address,
            build_equipment_request(
                state["document_id"],
                state["last_text"],
                answer.equipment_type,
                direction_name_of(answer),
                answer.equipment_type_id,
            ),
            log=log_it,
        )
        # Отметку ставим независимо от успеха: повторять на каждой реплике
        # звонок, которому и так не ответили, смысла нет.
        state["equipment_sent"] = True

    def report_unknown_question(answer):
        """Бот не нашёл ответа — вопрос клиента едет в справочник ERP.

        Обращение обязано существовать: событие цепляется именно к нему.
        """
        if not state["document_id"]:
            return
        if not should_send_unknown_question(
            answer, state["asked_point"], state["asked_text"], state["asked_silence"]
        ):
            return
        send_to_erp(
            aster2_address,
            # Запомненный вопрос, а не сырая реплика этого шага: источник
            # текста для ERP в скрипте один на все события. В этой точке
            # разговора они совпадают — в точке подтверждения, где они
            # расходятся, событие не отправляется вовсе.
            build_unknown_request(state["document_id"], state["last_text"]),
            log=log_it,
        )

    def report_transfer(redirect_exten, direction_name):
        if not state["document_id"]:
            return
        send_to_erp(
            aster2_address,
            build_transfer_request(
                state["document_id"], redirect_exten, direction_name, state["last_text"]
            ),
            log=log_it,
        )

    def push_caller_id_name():
        """Подставить в канал имя звонящего, по которому откроется карточка.

        Вызывать только внутри уже взятого `_agi_lock` и непосредственно перед
        Goto: имя должно уехать вместе с самим переводом, а после Goto нас в
        канале уже нет. Ровно так же устроен боевой recosintsite_V2 — Set и
        Goto в одном захвате блокировки.

        Номер звонящего (`CALLERID(num)`) при этом не трогаем: боевой бот его
        подменяет, потому что у него звонок исходящий, а у нас входящий — там
        лежит настоящий телефон клиента, и он оператору нужен.
        """
        command = caller_id_name_command(state["caller_id_name"])
        if not command:
            return
        try:
            agi.appexec("Set", command)
        except Exception as error:
            # Карточка — удобство, перевод — обязанность: сорвавшаяся
            # подстановка имени не имеет права отменить сам перевод.
            log_it("CALLERID NAME ERROR: {0}".format(error))

    def apply(answer):
        global _redirect_done
        step = decide_next_step(answer)
        # Про тему разговора сообщаем до озвучки, а не после: фраза о переводе
        # длится пару секунд, и если клиент бросит трубку на ней, скрипт умрёт
        # мгновенно (SIGHUP, см. ниже) — в обращении так и останется
        # «Неизвестное оборудование», хотя бот тему уже понял.
        report_equipment(answer)
        # По той же причине, что и тема: одно из двух событий, взаимно
        # исключающих друг друга — либо тему узнали, либо вопрос остался
        # неопознанным. Лишней задержки перед озвучкой это не добавляет.
        report_unknown_question(answer)
        speak(answer, blocking=(step != "listen"))
        if step == "listen":
            return True
        if step == "redirect":
            report_transfer(answer.redirect_exten, direction_name_of(answer))
            if REAL_REDIRECT:
                log_it("REDIRECT -> {0}".format(answer.redirect_exten))
                with _agi_lock:
                    push_caller_id_name()
                    agi.appexec("Goto", "pstn-out,{0},1".format(answer.redirect_exten))
                    agi.set_variable("ScriptFinished", True)
                _redirect_done = True
            else:
                # REAL_REDIRECT выключен: прототип не должен дёргать живых
                # операторов. Пишем в лог станции, куда бы перевели звонок и
                # почему, и корректно завершаем разговор сами вместо Goto.
                log_it(
                    "REDIRECT (dry-run, REAL_REDIRECT=False) -> would go to "
                    "exten {0}, reason: dialog decided Redirect".format(answer.redirect_exten)
                )
                with _agi_lock:
                    agi.set_variable("ScriptFinished", True)
                    agi.hangup()
                _redirect_done = True
            return False
        with _agi_lock:
            agi.set_variable("ScriptFinished", True)
            agi.hangup()
        return False

    def failover_to_support(error):
        # Речевой сервис недоступен целиком (не отвечает /dialog, оборвался
        # gRPC-стрим). Синтезировать нечего — сервис же и лежит, поэтому
        # играем заранее записанную фразу и переводим на сопровождение, а не
        # молчим и не кладём трубку сразу.
        global _redirect_done
        log_it("SERVICE FAILOVER ({0}) -> exten {1}".format(error, SUPPORT_FALLBACK_EXTEN))
        # Клиента сюда привёл наш отказ, а не его решение: сервис не ответил
        # или оборвался поток распознавания. Обратный звонок ему положен —
        # причину выставляем до перевода, потому что дальше клиент в любой
        # момент может положить трубку и скрипт умрёт мгновенно.
        set_failure_reason(REASON_SERVICE_UNAVAILABLE)
        # Обращение уже создано, и оператор должен увидеть, что бот довёл
        # звонок до перевода, а не бросил клиента. Направление здесь пустое:
        # речевой сервис лёг, темы разговора мы так и не узнали.
        report_transfer(SUPPORT_FALLBACK_EXTEN, "")
        try:
            if os.path.exists(SERVICE_UNAVAILABLE_SOUND + ".wav"):
                with _agi_lock:
                    agi.appexec("Playback", SERVICE_UNAVAILABLE_SOUND)
        except Exception as playback_error:
            log_it("FAILOVER PLAYBACK ERROR: {0}".format(playback_error))
        if REAL_REDIRECT:
            try:
                with _agi_lock:
                    # Обращение к этому моменту создано, и оператору аварийного
                    # перевода карточка нужна не меньше: он единственный, кто
                    # узнает, о чём был звонок.
                    push_caller_id_name()
                    agi.appexec("Goto", "pstn-out,{0},1".format(SUPPORT_FALLBACK_EXTEN))
                    agi.set_variable("ScriptFinished", True)
                _redirect_done = True
            except Exception as redirect_error:
                log_it("FAILOVER REDIRECT ERROR: {0}".format(redirect_error))
        else:
            # То же правило "не дёргать живых операторов" действует и на
            # аварийный путь: клиент уже услышал фразу про перевод, реального
            # Goto на сопровождение не делаем — только запись в лог и
            # корректное завершение разговора.
            log_it(
                "FAILOVER (dry-run, REAL_REDIRECT=False) -> would go to "
                "exten {0}".format(SUPPORT_FALLBACK_EXTEN)
            )
            try:
                with _agi_lock:
                    agi.set_variable("ScriptFinished", True)
                    agi.hangup()
                _redirect_done = True
            except Exception as hangup_error:
                log_it("FAILOVER HANGUP ERROR: {0}".format(hangup_error))

    def audio_stream(audio_source):
        yield speech_pb2.StreamRequest(session_id=linked_id)
        while True:
            data = audio_source.read(CHUNK_SIZE)
            if not data:
                return
            yield speech_pb2.StreamRequest(audio_chunk=data)

    def run():
        # Дескриптор 3 открывается СНАРУЖИ генератора: иначе при обрыве потока
        # его нельзя переоткрыть, и ретрай невозможен.
        audio_source = os.fdopen(3, "rb")
        channel = grpc.insecure_channel("{0}:{1}".format(service_host, grpc_port))
        try:
            try:
                # Обращение заводится в момент приёма звонка, а не при переводе:
                # трубку бросают и на первой секунде, а чтобы обращение ушло в
                # ПЦК при обрыве, к этому моменту оно должно существовать.
                open_erp_case()
                if not apply(ask_dialog("", False)):
                    return
                stub = speech_pb2_grpc.SpeechStub(channel)
                responses = stub.Recognize(audio_stream(audio_source), timeout=CALL_TIMEOUT_S * 3)
                for response in responses:
                    if response.type == speech_pb2.StreamResponse.SILENCE:
                        if not apply(ask_dialog("", True)):
                            return
                    elif response.type == speech_pb2.StreamResponse.FINAL:
                        log_it("FINAL: {0}".format(response.text))
                        if not apply(ask_dialog(response.text, False)):
                            return
            except Exception as error:
                # Отказ связи с речевым сервисом (обрыв /dialog, обрыв
                # gRPC-стрима) не должен проваливаться в общий FATAL-перехват
                # молча: клиент услышит тишину и обрыв. Программные ошибки
                # маскировать нельзя — они летят дальше как раньше.
                if decide_failure_step(error) == "failover":
                    failover_to_support(error)
                    return
                raise
        finally:
            channel.close()
            try:
                audio_source.close()
            except Exception:
                pass

    try:
        log_it("=== AI ASSISTANT START {0} ===".format(linked_id))
        with _agi_lock:
            agi.set_variable("ScriptFinished", False)
            # Время старта нужно скрипту последней воли: он считает по нему
            # длительность разговора для ERP. Кладём именно `time.time()` —
            # `perf_counter()` у отдельного процесса отсчитывается от своей
            # точки, и разница вышла бы бессмысленной.
            agi.set_variable("conversation_start_time", time.time())
        func_timeout(timeout=CALL_TIMEOUT_S, func=run, args=())
    except FunctionTimedOut:
        log_it("Завершено по таймауту {0} сек".format(CALL_TIMEOUT_S))
        # Разговор оборвали мы, а не клиент: он ещё говорил, когда упёрлись в
        # предел длительности.
        set_failure_reason(REASON_CALL_TIMEOUT)
    except Exception:
        log_it("FATAL: {0}".format(traceback.format_exc()))
        set_failure_reason(REASON_SCRIPT_ERROR)
    finally:
        # Блокировку на вежливый отбой берём НЕ безусловно: если её всё ещё
        # держит зависший поток озвучки (например, застрял в блокирующем
        # Playback на мёртвом канале), безусловный with here заблокировал бы
        # os._exit тоже — а он ради этого случая и существует. Поэтому ждём
        # блокировку не дольше LOCK_ACQUIRE_TIMEOUT_S; не получилось — просто
        # пропускаем вежливый hangup, станция закроет канал сама.
        if not _redirect_done:
            acquired = _agi_lock.acquire(timeout=LOCK_ACQUIRE_TIMEOUT_S)
            if acquired:
                try:
                    agi.hangup()
                except Exception:
                    pass
                finally:
                    _agi_lock.release()
            else:
                sys.stderr.write(
                    "AI ASSISTANT: agi-канал занят, вежливый hangup пропущен\n"
                )
        # Немедленный выход при любом исходе: не ждём застрявшие потоки, иначе
        # процесс не реапится и на Астериске копятся зомби до падения (уже
        # ловили).
        os._exit(0)


def main():  # pragma: no cover - тонкая обёртка над _main для точки входа
    _main()


if __name__ == "__main__":  # pragma: no cover
    main()
