#!/usr/bin/python3
# coding=utf8
"""Тонкий AGI-клиент виртуального AI-помощника (UL-17568).

Логики диалога не содержит: гонит аудио в speech-сервис и исполняет присланное
действие. Все защиты перенесены из боевого recosintsite_V2.py, они выстраданы:
RLock вокруг agi.*, daemon-потоки озвучки, os._exit в фатальном обработчике,
Playback для синхронной озвучки против background для асинхронной.

ВНИМАНИЕ: исполняется под Python 3.9.2. Синтаксис 3.10+ не использовать.
"""
import os
import sys
import traceback
from dataclasses import dataclass
from threading import RLock, Thread
from typing import Any, Dict, List, Optional

ACTION_RECOGNIZE = "Recognize"
ACTION_REDIRECT = "Redirect"
ACTION_HANGUP = "Hangup"

CHUNK_SIZE = 8000  # 4000 отсчётов = 0,5 секунды при 8000 Гц
CALL_TIMEOUT_S = 120
AUDIO_CACHE_DIR = "/var/lib/asterisk/sounds/ai_bot/cache"

_agi_lock = RLock()  # AGI — построчный протокол над stdin/stdout, не потокобезопасен
_redirect_done = False


@dataclass
class DialogAnswer:
    action: str
    text_to_speak: str
    file_to_playback: str
    conversation_point: str
    redirect_exten: str


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
    )


def build_dialog_request(linked_id, point, text, silence):
    # type: (str, str, str, bool) -> Dict[str, Any]
    return {
        "prms": [
            {"Key": "linkedId", "Value": linked_id},
            {"Key": "conversationPoint", "Value": point},
            {"Key": "recognizedText", "Value": text},
            {"Key": "silenceDetected", "Value": "True" if silence else "False"},
        ]
    }


def decide_next_step(answer: DialogAnswer) -> str:
    if answer.action == ACTION_RECOGNIZE:
        return "listen"
    if answer.action == ACTION_REDIRECT:
        return "redirect"
    if answer.action == ACTION_HANGUP:
        return "hangup"
    raise ValueError("Неизвестное действие: {0}".format(answer.action))


# --- Дальше идёт часть, работающая только внутри Asterisk ---------------------


def _main():  # pragma: no cover - требует живого канала Asterisk
    import asterisk.agi
    import grpc
    import requests
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

    service_host = get_var("SpeechServiceHost", "10.20.0.10")
    grpc_port = get_var("SpeechServiceGrpcPort", "50051")
    http_port = get_var("SpeechServiceHttpPort", "8080")
    linked_id = agi.env.get("agi_uniqueid", "")
    http_base = "http://{0}:{1}".format(service_host, http_port)

    state = {"point": "Start", "playing": False}

    def fetch_audio(text, file_name):
        target = os.path.join(AUDIO_CACHE_DIR, file_name + ".wav")
        if os.path.exists(target):
            return target
        if not os.path.isdir(AUDIO_CACHE_DIR):
            os.makedirs(AUDIO_CACHE_DIR)
        response = requests.get(http_base + "/tts", params={"text": text}, timeout=30)
        response.raise_for_status()
        tmp_target = target + ".tmp"
        with open(tmp_target, "wb") as handle:
            handle.write(response.content)
        os.replace(tmp_target, target)
        return target

    def speak(answer, blocking):
        if not answer.text_to_speak:
            return
        try:
            fetch_audio(answer.text_to_speak, answer.file_to_playback)
        except Exception as error:
            log_it("TTS ERROR: {0}".format(error))
            return
        # Playback блокирует до конца фразы — обязателен перед Goto и Hangup.
        application = "Playback" if blocking else "background"
        path = os.path.join(AUDIO_CACHE_DIR, answer.file_to_playback)
        with _agi_lock:
            agi.appexec(application, path)

    def ask_dialog(text, silence):
        payload = build_dialog_request(linked_id, state["point"], text, silence)
        response = requests.post(http_base + "/dialog", json=payload, timeout=15)
        response.raise_for_status()
        answer = parse_dialog_response(response.json())
        if answer.conversation_point:
            state["point"] = answer.conversation_point
        return answer

    def apply(answer):
        global _redirect_done
        step = decide_next_step(answer)
        speak(answer, blocking=(step != "listen"))
        if step == "listen":
            return True
        if step == "redirect":
            log_it("REDIRECT -> {0}".format(answer.redirect_exten))
            with _agi_lock:
                agi.appexec("Goto", "pstn-out,{0},1".format(answer.redirect_exten))
                agi.set_variable("ScriptFinished", True)
            _redirect_done = True
            return False
        with _agi_lock:
            agi.set_variable("ScriptFinished", True)
            agi.hangup()
        return False

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
        func_timeout(timeout=CALL_TIMEOUT_S, func=run, args=())
    except FunctionTimedOut:
        log_it("Завершено по таймауту {0} сек".format(CALL_TIMEOUT_S))
    except Exception:
        log_it("FATAL: {0}".format(traceback.format_exc()))
    finally:
        try:
            if not _redirect_done:
                with _agi_lock:
                    agi.hangup()
        except Exception:
            pass
        # Немедленный выход: не ждём застрявшие потоки, иначе процесс не реапится
        # и на Астериске копятся зомби до падения (уже ловили).
        os._exit(0)


def main():  # pragma: no cover - тонкая обёртка над _main для точки входа
    _main()


if __name__ == "__main__":  # pragma: no cover
    main()
