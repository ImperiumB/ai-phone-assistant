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
REAL_REDIRECT = False

CHUNK_SIZE = 8000  # 4000 отсчётов = 0,5 секунды при 8000 Гц
CALL_TIMEOUT_S = 120
AUDIO_CACHE_DIR = "/var/lib/asterisk/sounds/ai_bot/cache"

# Аварийный путь на случай, если речевой сервис недоступен целиком: заранее
# записанная фраза (не синтезируется на лету — сервис же и лежит) и перевод
# на отдел сопровождения, чтобы клиент услышал обычный перевод, а не тишину.
SERVICE_UNAVAILABLE_SOUND = "/var/lib/asterisk/sounds/ai_bot/service_unavailable"
SUPPORT_FALLBACK_EXTEN = "489"

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

    service_host = get_var("SpeechServiceHost", "10.20.0.10")
    grpc_port = get_var("SpeechServiceGrpcPort", "50051")
    http_port = get_var("SpeechServiceHttpPort", "8080")
    linked_id = agi.env.get("agi_uniqueid", "")
    http_base = "http://{0}:{1}".format(service_host, http_port)

    state = {"point": "Start"}

    def fetch_audio(text, file_name):
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
        response = requests.get(http_base + "/tts", params={"text": text}, timeout=30)
        response.raise_for_status()
        tmp_target = target + ".tmp"
        with open(tmp_target, "wb") as handle:
            handle.write(response.content)
        os.replace(tmp_target, target)
        download_done = time.time()
        log_it(
            "TIMING download_done {0:.3f} ({1:.1f} ms)".format(
                download_done, (download_done - download_start) * 1000.0
            )
        )
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
        log_it("TIMING playback_start {0:.3f}".format(time.time()))
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
            if REAL_REDIRECT:
                log_it("REDIRECT -> {0}".format(answer.redirect_exten))
                with _agi_lock:
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
        try:
            if os.path.exists(SERVICE_UNAVAILABLE_SOUND + ".wav"):
                with _agi_lock:
                    agi.appexec("Playback", SERVICE_UNAVAILABLE_SOUND)
        except Exception as playback_error:
            log_it("FAILOVER PLAYBACK ERROR: {0}".format(playback_error))
        if REAL_REDIRECT:
            try:
                with _agi_lock:
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
        func_timeout(timeout=CALL_TIMEOUT_S, func=run, args=())
    except FunctionTimedOut:
        log_it("Завершено по таймауту {0} сек".format(CALL_TIMEOUT_S))
    except Exception:
        log_it("FATAL: {0}".format(traceback.format_exc()))
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
