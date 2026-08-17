#!/usr/bin/python3
# coding=utf8
"""Последняя воля виртуального AI-помощника (UL-18797).

Астериск запускает этот скрипт на `exten => h`, то есть уже после того, как
канал разорван. Он сообщает в ERP, что клиент положил трубку, и обращение
уходит в ПЦК — иначе человек, который до нас не дозвонился, останется без
ответа.

Отдельный скрипт нужен не для красоты: основной `ai_assistant.py` при обрыве
канала умирает мгновенно (SIGHUP переведён на SIG_DFL, и это сделано
намеренно — зомби-процессы копились и роняли станцию целиком). Сказать
что-либо об обрыве он поэтому не может физически, и всё, что нужно знать
последней воле, он заранее кладёт в переменные канала: `documentId`,
`ScriptFinished`, `LastRecognizedText`.

Скрипт намеренно самодостаточен: ничего не импортирует из `ai_assistant.py`,
чтобы не тянуть за собой grpc и сгенерированные заглушки protobuf. На станции
на них уже спотыкались при развёртывании, а последняя воля обязана
подниматься даже тогда, когда основной скрипт не поднимается вовсе.

ВНИМАНИЕ: исполняется под Python 3.9.2. Синтаксис 3.10+ не использовать.
"""
import traceback
from typing import Any, Dict, List

import requests

# Те же значения, что в ai_assistant.py. Продублированы, а не импортированы:
# см. про самодостаточность в шапке файла.
DEFAULT_ASTER2_SERVICE_ADDRESS = "10.20.0.12:3511/Aster2ServiceWebHttp"
ERP_ENDPOINT = "ReturnConversationIntermediateResult3"
ERP_TIMEOUT_S = 5

EVENT_HANGUP = "AiAssistantHangup"


def erp_url(service_address):
    # type: (str) -> str
    return "http://{0}/{1}".format(service_address.rstrip("/"), ERP_ENDPOINT)


def build_hangup_request(document_id, linked_id, recognized_text, script_finished):
    # type: (Any, str, str, Any) -> Dict[str, Any]
    """Тело запроса об оборванном звонке.

    `documentId` может не приехать вовсе: трубку бросают и на первой секунде,
    когда обращение ещё не создано. Поэтому `linkedId` отправляется всегда —
    по нему ERP находит обращение сама. Ноль и пустая строка — это одно и то
    же «кода нет»: невыставленная переменная канала приезжает то так, то так.
    """
    values = [
        ("documentId", document_id),
        ("linkedId", linked_id),
        ("recognizedText", recognized_text),
        ("scriptFinished", script_finished),
    ]
    prms = [{"Key": "eventType", "Value": EVENT_HANGUP}]
    for key, value in values:
        text = "" if value is None else str(value)
        if key == "documentId" and text in ("0", "None"):
            text = ""
        if text:
            prms.append({"Key": key, "Value": text})
    return {"prms": prms}


def should_report_hangup(script_finished, document_id, linked_id):
    # type: (str, str, str) -> bool
    """Был ли это именно обрыв, а не нормальный конец разговора.

    Расширение `h` Астериск исполняет на любом завершении канала, в том числе
    когда бот сам довёл разговор до перевода и положил трубку. Обработчик ERP
    на событие обрыва уводит обращение в ПЦК и признака завершённости не
    смотрит — значит отличать одно от другого обязаны мы, иначе каждый
    успешно переведённый звонок попадёт ещё и в «Перезвонить целевому
    клиенту», и оператор будет перезванивать тому, с кем уже поговорили.

    `ScriptFinished` основной скрипт выставляет в True ровно там, где сам
    решил закончить: перевод, отбой по решению диалога, аварийный перевод при
    отказе речевого сервиса. Если он оборвался или умер от SIGHUP, значение
    так и останется False — это и есть брошенная трубка.
    """
    if str(script_finished).strip().lower() in ("true", "1", "yes"):
        return False
    if document_id.strip() in ("", "0") and not linked_id.strip():
        return False  # сообщать не о чем: ни обращения, ни канала
    return True


def parse_erp_response(items):
    # type: (Any) -> List[str]
    """Ответ ERP строками для лога станции. Разбор не имеет права падать."""
    lines = []
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                lines.append("{0} = {1}".format(item.get("Key", ""), item.get("Value", "")))
    return lines


def send_last_will(service_address, body, post=None, log=None):
    # type: (str, Dict[str, Any], Any, Any) -> bool
    """Отправить сообщение об обрыве. Никогда не бросает.

    Канала уже нет, ругаться некому и незачем: любой отказ — строка в лог
    станции. Возвращает True, только если ERP ответила успехом.
    """
    if post is None:
        post = requests.post
    url = erp_url(service_address)
    try:
        response = post(url, json=body, timeout=ERP_TIMEOUT_S)
        if response.status_code != 200:
            if log:
                log("ERP: статус ответа {0} на {1}".format(response.status_code, url))
            return False
        if log:
            for line in parse_erp_response(response.json()):
                log("ERP: " + line)
        return True
    except Exception as error:
        if log:
            log("ERP ERROR ({0}): {1}".format(url, error))
        return False


# --- Дальше идёт часть, работающая только внутри Asterisk ---------------------


def _main():  # pragma: no cover - требует живого канала Asterisk
    import asterisk.agi

    agi = asterisk.agi.AGI()

    def log_it(message):
        try:
            agi.verbose(str(message).replace("\n", " | ").replace('"', "'"))
        except Exception:
            pass

    def get_var(name, default=""):
        try:
            value = agi.get_variable(name)
            return value if value else default
        except Exception:
            return default

    linked_id = agi.env.get("agi_uniqueid", "")
    document_id = get_var("documentId")
    script_finished = get_var("ScriptFinished")
    recognized_text = get_var("LastRecognizedText")
    aster2_address = get_var("Aster2ServiceAddress", DEFAULT_ASTER2_SERVICE_ADDRESS)

    log_it("=== AI ASSISTANT LAST WILL {0} (обращение {1}, ScriptFinished={2}) ===".format(
        linked_id, document_id or "не создано", script_finished))

    if not should_report_hangup(script_finished, document_id, linked_id):
        log_it("LAST WILL: разговор завершён самим ботом, обрыва не было")
    else:
        try:
            send_last_will(
                aster2_address,
                build_hangup_request(document_id, linked_id, recognized_text, script_finished),
                log=log_it,
            )
        except Exception:
            # send_last_will и так ничего не бросает, но этот скрипт
            # запускается на уже разорванном канале: падение здесь ушло бы в
            # лог станции трассировкой питона, а не понятной строкой.
            log_it("LAST WILL FATAL: {0}".format(traceback.format_exc()))

    log_it("=== AI ASSISTANT LAST WILL FINISH ===")


def main():  # pragma: no cover - тонкая обёртка над _main для точки входа
    _main()


if __name__ == "__main__":  # pragma: no cover
    main()
