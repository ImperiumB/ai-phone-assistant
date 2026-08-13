import os
import struct
import sys
import threading
import time
from concurrent import futures

import grpc
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "proto"))
import speech_pb2  # noqa: E402
import speech_pb2_grpc  # noqa: E402

from ai_assistant.service.dialog import DialogEngine, Phrases
from ai_assistant.service.knowledge import KnowledgeRecord
from ai_assistant.service.main import GRPC_SHUTDOWN_GRACE_SECONDS, SpeechServicer, build_http_app
from ai_assistant.service.vad import SegmentEvent

FRAME_SAMPLES = 256


class FakeSegmenter:
    """Отдаёт заранее заготовленные события, игнорируя аудио."""

    def __init__(self, script):
        self._script = list(script)

    def feed(self, pcm):
        if not self._script:
            return []
        return self._script.pop(0)

    def reset(self):
        pass


class FakeEngine:
    target_sample_rate = 8000

    def transcribe(self, pcm):
        return "стиральная машина не отжимает"


class FakeKnowledge:
    threshold = 0.75

    def _record(self):
        return KnowledgeRecord(
            id=1,
            question="стиральная машина не отжимает",
            clarifying_question="Речь о стиральной машине?",
            positive_answers=["да"],
            negative_answers=["нет"],
            positive_reply="Соединяю",
            scenario="redirect_sales",
            equipment_type="Стиральные машины",
        )

    def search(self, text):
        return self._record(), 0.9

    def best_match(self, text):
        return self._record(), 0.9

    def add(self, question):
        return KnowledgeRecord(id=2, question=question)

    def save(self, path):
        pass


class FakeTtsCache:
    def __init__(self, tmp_path):
        self._tmp_path = tmp_path

    def get(self, text, voice):
        target = self._tmp_path / "out.wav"
        import wave

        with wave.open(str(target), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(8000)
            handle.writeframes(struct.pack("<400h", *([0] * 400)))
        return str(target)


class FakeRequestIterator:
    def __init__(self, session_id, chunks):
        self._items = []
        for chunk in chunks:
            self._items.append(_Request(session_id, chunk))

    def __iter__(self):
        return iter(self._items)


class _Request:
    def __init__(self, session_id, audio_chunk):
        self.session_id = session_id
        self.audio_chunk = audio_chunk


def pcm(samples):
    return struct.pack("<{0}h".format(samples), *([100] * samples))


def test_utterance_event_becomes_final_response():
    script = [[], [SegmentEvent(kind="utterance", pcm=pcm(800))]]
    servicer = SpeechServicer(lambda: FakeSegmenter(script), FakeEngine(), timeline_sink=[])
    requests = FakeRequestIterator("call-1", [pcm(400), pcm(400)])

    responses = list(servicer.Recognize(requests, context=None))
    finals = [r for r in responses if r.type == speech_pb2.StreamResponse.FINAL]
    assert len(finals) == 1
    assert finals[0].text == "стиральная машина не отжимает"


def test_silence_event_becomes_silence_response():
    script = [[SegmentEvent(kind="silence", silence_ms=15000)]]
    servicer = SpeechServicer(lambda: FakeSegmenter(script), FakeEngine(), timeline_sink=[])
    requests = FakeRequestIterator("call-2", [pcm(400)])

    responses = list(servicer.Recognize(requests, context=None))
    silences = [r for r in responses if r.type == speech_pb2.StreamResponse.SILENCE]
    assert len(silences) == 1
    assert silences[0].silence_ms == 15000


def test_timeline_is_recorded_for_every_utterance():
    script = [[SegmentEvent(kind="utterance", pcm=pcm(800))]]
    sink = []
    servicer = SpeechServicer(lambda: FakeSegmenter(script), FakeEngine(), timeline_sink=sink)
    list(servicer.Recognize(FakeRequestIterator("call-3", [pcm(400)]), context=None))
    assert len(sink) == 1
    assert sink[0]["session_id"] == "call-3"
    assert "speech_end->stt_done" in sink[0]["durations"]


class FailingThenWorkingEngine:
    """Падает на первой реплике, дальше работает — воспроизводит Important 3
    из ревью Task 9: движок споткнулся, но звонок должен идти дальше."""

    target_sample_rate = 8000

    def __init__(self):
        self.calls = 0

    def transcribe(self, pcm):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("движок упал на этом фрагменте")
        return "восстановились"


def test_engine_failure_on_one_utterance_does_not_break_the_stream():
    script = [[
        SegmentEvent(kind="utterance", pcm=pcm(800)),
        SegmentEvent(kind="utterance", pcm=pcm(800)),
    ]]
    engine = FailingThenWorkingEngine()
    sink = []
    servicer = SpeechServicer(lambda: FakeSegmenter(script), engine, timeline_sink=sink)

    # Раньше исключение из transcribe() вышло бы из генератора и gRPC закрыл
    # бы поток целиком — list(...) здесь как раз и обходит все события до конца.
    responses = list(servicer.Recognize(FakeRequestIterator("call-5", [pcm(400)]), context=None))

    finals = [r for r in responses if r.type == speech_pb2.StreamResponse.FINAL]
    assert len(finals) == 1
    assert finals[0].text == "восстановились"
    assert engine.calls == 2  # обе реплики дошли до движка, первая просто не долетела до клиента
    assert len(sink) == 1  # в таймлайн попала только успешная реплика


def test_timeline_sink_bounded_by_a_deque_does_not_grow_without_limit():
    """Important 4 из ревью Task 9: главный код передаёт в SpeechServicer не
    голый список, а deque(maxlen=...) — здесь проверяем, что SpeechServicer
    одинаково хорошо работает с любым объектом, у которого есть .append(), и
    что переполнение действительно вытесняет самые старые записи."""
    from collections import deque

    sink = deque(maxlen=3)
    script = [[SegmentEvent(kind="utterance", pcm=pcm(800))] for _ in range(5)]
    servicer = SpeechServicer(lambda: FakeSegmenter(script), FakeEngine(), timeline_sink=sink)
    requests = FakeRequestIterator("call-6", [pcm(400)] * 5)

    list(servicer.Recognize(requests, context=None))

    assert len(sink) == 3


@pytest.fixture
def client(tmp_path):
    phrases = Phrases(
        greeting="Здравствуйте, чем могу помочь?",
        misrecognition="Переформулируйте, пожалуйста",
        transfer="Перевожу звонок",
        silence="Вы меня слышите?",
    )
    dialog = DialogEngine(FakeKnowledge(), phrases, support_exten="489", sales_exten="500")
    app = build_http_app(dialog, FakeTtsCache(tmp_path), voice="baya")
    return TestClient(app)


def test_dialog_endpoint_answers_in_erp_contract(client):
    response = client.post(
        "/dialog",
        json={"prms": [
            {"Key": "linkedId", "Value": "call-1"},
            {"Key": "conversationPoint", "Value": "Start"},
            {"Key": "recognizedText", "Value": ""},
        ]},
    )
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    keys = {item["Key"] for item in payload}
    assert {"Action", "TextToSpeak", "FileToPlayback", "ConversationPoint"} <= keys


def test_dialog_endpoint_greets_on_start(client):
    response = client.post(
        "/dialog",
        json={"prms": [
            {"Key": "linkedId", "Value": "call-2"},
            {"Key": "conversationPoint", "Value": "Start"},
        ]},
    )
    values = {item["Key"]: item["Value"] for item in response.json()}
    assert values["TextToSpeak"] == "Здравствуйте, чем могу помочь?"
    assert values["Action"] == "Recognize"


def test_tts_endpoint_returns_playable_wav(client):
    response = client.get("/tts", params={"text": "здравствуйте"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content[:4] == b"RIFF"
    assert response.content[8:12] == b"WAVE"


def test_tts_endpoint_rejects_empty_text(client):
    response = client.get("/tts", params={"text": "   "})
    assert response.status_code == 400


class _StuckSegmenter:
    """Никогда не отдаёт события — имитирует активный звонок, который ещё
    не завершился (абонент продолжает говорить), пока сервер выключают."""

    def feed(self, pcm):
        time.sleep(0.01)
        return []


def _endless_requests(session_id):
    while True:
        yield _Request(session_id, pcm(400))
        time.sleep(0.01)


def test_grpc_server_stop_bounds_shutdown_even_with_an_active_call():
    """Important 5 из ревью Task 9: `server.stop()` нигде не вызывался, а
    рабочие потоки пула не демоны — без явной остановки процесс при выходе
    ждал бы завершения активных звонков неограниченно долго. Здесь проверяем
    именно тот механизм, который main() зовёт в finally (server.stop(grace)
    + wait), на настоящем grpc.server() с настоящим активным звонком,
    который никогда сам не закончится."""
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    speech_pb2_grpc.add_SpeechServicer_to_server(
        SpeechServicer(lambda: _StuckSegmenter(), FakeEngine(), timeline_sink=[]), server
    )
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()

    channel = grpc.insecure_channel("127.0.0.1:{0}".format(port))
    stub = speech_pb2_grpc.SpeechStub(channel)
    call = stub.Recognize(_endless_requests("stuck-call"))
    time.sleep(0.1)  # дать звонку реально стартовать перед остановкой сервера

    grace = 0.3
    start = time.perf_counter()
    stopped = server.stop(grace)
    stopped.wait(grace + 1)
    elapsed = time.perf_counter() - start

    assert elapsed < grace + 1  # не хуже, а не "рано или поздно когда-нибудь"
    with pytest.raises(grpc.RpcError):
        list(call)
    channel.close()


def test_main_defines_a_positive_bounded_grpc_shutdown_grace_period():
    assert 0 < GRPC_SHUTDOWN_GRACE_SECONDS <= 30


def test_speech_end_mark_is_shifted_back_by_the_segmenter_pause():
    """Item 4 финального ревью: раньше метка конца речи ставилась в момент,
    когда сегментатор заметил паузу ("сейчас"), а не в момент, когда клиент
    реально замолчал ("сейчас минус пауза"). С реальным UtteranceSegmenter
    (без FakeSegmenter) и почти мгновенным FakeEngine speech_end->stt_done
    должно быть не меньше самой паузы VAD — иначе поправка не применяется."""
    from ai_assistant.service.vad import UtteranceSegmenter

    class InstantAmplitudeDetector:
        def is_speech(self, frame):
            first = struct.unpack("<h", frame[:2])[0]
            return first != 0

        def reset(self):
            pass

    pause_ms = 100
    real_segmenter = UtteranceSegmenter(
        InstantAmplitudeDetector(), pause_ms=pause_ms, silence_timeout_ms=5000
    )

    sink = []
    servicer = SpeechServicer(lambda: real_segmenter, FakeEngine(), timeline_sink=sink)

    speech = pcm(256) * 3
    silence = struct.pack("<{0}h".format(256), *([0] * 256)) * 4
    requests = FakeRequestIterator("call-pause", [speech, silence])

    list(servicer.Recognize(requests, context=None))

    assert len(sink) == 1
    duration = sink[0]["durations"]["speech_end->stt_done"]
    # pause_ms=100 округляется вверх до 128 мс (4 кадра по 32 мс) —
    # см. test_vad.py::test_pause_seconds_matches_the_rounded_up_pause_in_frames.
    assert duration >= pause_ms * 0.9


def test_active_timelines_registry_evicts_the_oldest_entry_when_full():
    """Minor из повторного ревью: реестр активных таймлайнов наполняется в
    Recognize() и вычищается только при обращении к /dialog. Если звонок
    оборвался между этими моментами (сброс трубки, общий таймаут звонка,
    падение AGI-скрипта на станции), запись оставалась бы в реестре навсегда
    — демон живёт постоянно. Тот же приём, что и для DEFAULT_MAX_SESSIONS в
    dialog.py: самая старая запись вытесняется при превышении предела."""
    active_timelines = {}
    timelines_lock = threading.Lock()
    sink = []

    def recognize_one(call_id):
        script = [[SegmentEvent(kind="utterance", pcm=pcm(800))]]
        servicer = SpeechServicer(
            lambda: FakeSegmenter(script),
            FakeEngine(),
            timeline_sink=sink,
            active_timelines=active_timelines,
            timelines_lock=timelines_lock,
            max_active_timelines=2,
        )
        list(servicer.Recognize(FakeRequestIterator(call_id, [pcm(400)]), context=None))

    recognize_one("a")
    recognize_one("b")
    assert set(active_timelines) == {"a", "b"}

    recognize_one("c")
    assert set(active_timelines) == {"b", "c"}  # "a" — самая старая, вытеснена


def test_active_timelines_registry_does_not_evict_on_repeated_calls_for_the_same_id():
    """Повторная запись для ТОГО ЖЕ звонка (следующая реплика в разговоре)
    не должна считаться новой записью и запускать вытеснение на ровном
    месте — предел не должен мешать многоходовым разговорам."""
    active_timelines = {}
    timelines_lock = threading.Lock()
    sink = []

    def recognize_one(call_id):
        script = [[SegmentEvent(kind="utterance", pcm=pcm(800))]]
        servicer = SpeechServicer(
            lambda: FakeSegmenter(script),
            FakeEngine(),
            timeline_sink=sink,
            active_timelines=active_timelines,
            timelines_lock=timelines_lock,
            max_active_timelines=2,
        )
        list(servicer.Recognize(FakeRequestIterator(call_id, [pcm(400)]), context=None))

    recognize_one("a")
    recognize_one("b")
    recognize_one("a")  # вторая реплика того же звонка "a"
    assert set(active_timelines) == {"a", "b"}


def test_speech_servicer_default_active_timelines_limit_is_sane():
    from ai_assistant.service.main import MAX_ACTIVE_TIMELINES

    assert 0 < MAX_ACTIVE_TIMELINES <= 100_000


def test_dialog_stage_is_marked_on_the_shared_timeline_for_matching_call(tmp_path):
    """Item 3 финального ревью: STAGE_DIALOG_DONE нигде не помечался, хотя
    объявлен в metrics.py. Проверяем, что /dialog находит таймлайн,
    оставленный Recognize() для того же звонка (session_id == linkedId), и
    дописывает в него завершение решения диалога — на том же объекте,
    который уже лежит в /metrics."""
    from ai_assistant.service.metrics import STAGE_DIALOG_DONE

    sink = []
    active_timelines = {}
    timelines_lock = threading.Lock()

    script = [[SegmentEvent(kind="utterance", pcm=pcm(800))]]
    servicer = SpeechServicer(
        lambda: FakeSegmenter(script),
        FakeEngine(),
        timeline_sink=sink,
        active_timelines=active_timelines,
        timelines_lock=timelines_lock,
    )
    list(servicer.Recognize(FakeRequestIterator("call-7", [pcm(400)]), context=None))

    assert "call-7" in active_timelines
    assert STAGE_DIALOG_DONE not in sink[0]["stages"]

    phrases = Phrases(
        greeting="Здравствуйте", misrecognition="?", transfer="Перевожу", silence="?"
    )
    dialog_engine = DialogEngine(FakeKnowledge(), phrases, support_exten="489", sales_exten="500")
    app = build_http_app(
        dialog_engine,
        FakeTtsCache(tmp_path),
        voice="baya",
        active_timelines=active_timelines,
        timelines_lock=timelines_lock,
    )
    client = TestClient(app)
    response = client.post(
        "/dialog",
        json={
            "prms": [
                {"Key": "linkedId", "Value": "call-7"},
                {"Key": "conversationPoint", "Value": "AskQuestion"},
                {"Key": "recognizedText", "Value": "стиральная машина не отжимает"},
            ]
        },
    )
    assert response.status_code == 200

    # Запись потребляется /dialog — второй раз для того же хвоста разговора
    # найти нечего, случайная реплика тишины не должна помечать чужой замер.
    assert "call-7" not in active_timelines
    assert STAGE_DIALOG_DONE in sink[0]["stages"]
    assert "stt_done->dialog_done" in sink[0]["durations"]


def test_dialog_endpoint_without_shared_timelines_still_works(client):
    """build_http_app без active_timelines (как в старом fixture `client`
    этого файла и в проде до этой правки) не должен падать — новые параметры
    опциональны."""
    response = client.post(
        "/dialog",
        json={"prms": [
            {"Key": "linkedId", "Value": "call-8"},
            {"Key": "conversationPoint", "Value": "Start"},
        ]},
    )
    assert response.status_code == 200


def test_tts_endpoint_logs_synthesis_duration(client, caplog):
    """Item 3 финального ревью: ручка синтеза обязана мерить длительность и
    писать её в лог — /tts не получает linkedId (контракт не меняем), так
    что сопоставить с конкретным звонком это можно только по времени
    вручную, но сам факт замера должен появиться."""
    with caplog.at_level("INFO", logger="aia"):
        response = client.get("/tts", params={"text": "здравствуйте"})
    assert response.status_code == 200
    assert any("TTS" in record.message for record in caplog.records)
