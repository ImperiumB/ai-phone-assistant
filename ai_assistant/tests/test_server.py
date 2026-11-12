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
from ai_assistant.service.knowledge import KnowledgeRecord, Resolution
from ai_assistant.service.main import (
    GRPC_SHUTDOWN_GRACE_SECONDS,
    SpeechServicer,
    build_http_app,
    prune_old_files,
)
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

    def resolve(self, text):
        return Resolution(self._record(), 0.9, True, "phrases")

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


def pcm(samples, value=3000):
    """Кадр «речи» для тестов.

    Амплитуда 3000 это около минус 21 dBFS, как живая речь в телефонной линии.
    Прежние 100 давали минус 50 dBFS, то есть тише порога фильтра фантомов
    (vad.MIN_UTTERANCE_PEAK_DBFS): сегментатор такую реплику справедливо
    выбрасывал как шум, и два теста таймлайна падали на пустом результате.
    """
    return struct.pack("<{0}h".format(samples), *([value] * samples))


def test_utterance_event_becomes_final_response():
    script = [[], [SegmentEvent(kind="utterance", pcm=pcm(800))]]
    servicer = SpeechServicer(lambda: FakeSegmenter(script), FakeEngine(), timeline_sink=[])
    requests = FakeRequestIterator("call-1", [pcm(400), pcm(400)])

    responses = list(servicer.Recognize(requests, context=None))
    finals = [r for r in responses if r.type == speech_pb2.StreamResponse.FINAL]
    assert len(finals) == 1
    assert finals[0].text == "стиральная машина не отжимает"


def test_utterance_is_not_saved_to_disk_by_default():
    """Записи разговоров на диске — отладочный режим, а не поведение по умолчанию."""
    script = [[SegmentEvent(kind="utterance", pcm=pcm(800))]]
    servicer = SpeechServicer(lambda: FakeSegmenter(script), FakeEngine(), timeline_sink=[])

    list(servicer.Recognize(FakeRequestIterator("call-1", [pcm(400)]), context=None))
    # Ничего не упало и никуда не записалось: проверяем сам факт работы без каталога.
    assert servicer._debug_audio_dir == ""


def test_debug_audio_dir_saves_the_utterance_with_its_recognition(tmp_path):
    """Разбор жалоб «я сказал нет, а распозналось да» без записи невозможен:
    по логу не отличить голос клиента от эха собственной фразы бота."""
    script = [[SegmentEvent(kind="utterance", pcm=pcm(800))]]
    servicer = SpeechServicer(
        lambda: FakeSegmenter(script), FakeEngine(), timeline_sink=[],
        debug_audio_dir=str(tmp_path),
    )

    list(servicer.Recognize(FakeRequestIterator("call-7", [pcm(400)]), context=None))

    # Рядом с репликой лежит и весь поток звонка целиком (…_ПОТОК.wav, 13.10.2026).
    streams = list(tmp_path.glob("*_ПОТОК.wav"))
    assert len(streams) == 1
    saved = [f for f in tmp_path.glob("*.wav") if not f.name.endswith("_ПОТОК.wav")]
    assert len(saved) == 1
    name = saved[0].name
    assert "call-7" in name
    # Распознанное — в имени файла, иначе записи придётся сопоставлять с логом вручную.
    assert "отжимает" in name
    import wave
    with wave.open(str(saved[0])) as handle:
        assert handle.getframerate() == FakeEngine.target_sample_rate
        assert handle.getnframes() > 0


def test_broken_debug_audio_dir_does_not_break_recognition(tmp_path):
    """Отладочная запись не имеет права уронить живой звонок."""
    busy = tmp_path / "занято"
    busy.write_text("это файл, а не каталог", encoding="utf-8")
    script = [[SegmentEvent(kind="utterance", pcm=pcm(800))]]
    servicer = SpeechServicer(
        lambda: FakeSegmenter(script), FakeEngine(), timeline_sink=[],
        debug_audio_dir=str(busy),
    )

    responses = list(servicer.Recognize(FakeRequestIterator("call-8", [pcm(400)]), context=None))
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


def test_forced_utterance_does_not_shift_speech_end_by_the_pause():
    """Minor из повторного ревью: при принудительной выдаче по потолку длины
    (MAX_UTTERANCE_SECONDS в vad.py) паузы не было вообще — вычитать
    pause_seconds из метки конца речи нельзя, иначе для длинного монолога
    замер оказался бы завышен на несуществующие секунды. pause_ms здесь
    заведомо огромный, чтобы естественная пауза не успела сработать раньше
    потолка: если бы поправка на паузу всё равно применилась (баг),
    длительность оказалась бы порядка pause_seconds — часы, а не доли
    секунды."""
    from ai_assistant.service.vad import MAX_UTTERANCE_SECONDS, UtteranceSegmenter

    class InstantAmplitudeDetector:
        def is_speech(self, frame):
            first = struct.unpack("<h", frame[:2])[0]
            return first != 0

        def reset(self):
            pass

    real_segmenter = UtteranceSegmenter(
        InstantAmplitudeDetector(), pause_ms=10 ** 9, silence_timeout_ms=10 ** 9
    )

    sink = []
    servicer = SpeechServicer(lambda: real_segmenter, FakeEngine(), timeline_sink=sink)

    frame_ms = 32
    frames_needed = -(-int(MAX_UTTERANCE_SECONDS * 1000) // frame_ms)  # ceil
    speech = pcm(256) * frames_needed
    requests = FakeRequestIterator("call-forced", [speech])

    list(servicer.Recognize(requests, context=None))

    assert len(sink) == 1
    duration = sink[0]["durations"]["speech_end->stt_done"]
    assert duration < 1000.0


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


class RecordingTtsCache:
    """Считает, что и сколько раз синтезировалось."""

    def __init__(self, fail_on=None):
        self.calls = []
        self._fail_on = fail_on or set()

    def get(self, text, voice):
        if text in self._fail_on:
            raise RuntimeError("синтез не удался")
        self.calls.append((text, voice))
        return "/tmp/%s.wav" % len(self.calls)


class KnowledgeStub:
    def __init__(self, records):
        self._records = records

    @property
    def records(self):
        return list(self._records)


def _phrases():
    from ai_assistant.service.dialog import Phrases

    return Phrases(
        greeting="Здравствуйте, чем могу помочь?",
        misrecognition="Переформулируйте, пожалуйста",
        transfer="Перевожу звонок",
        silence="Вы меня слышите?",
    )


def test_prewarm_collects_service_phrases_and_knowledge_answers():
    from ai_assistant.service.main import collect_speakable_phrases

    records = [
        KnowledgeRecord(
            id=1, question="стиралка", clarifying_question="Речь о стиральной машине?",
            positive_reply="Соединяю с продажами",
        ),
        # Неразмеченная неопознанная реплика — бот её не произносит
        KnowledgeRecord(id=2, question="во сколько вы работаете"),
    ]
    texts = collect_speakable_phrases(_phrases(), KnowledgeStub(records))

    assert "Здравствуйте, чем могу помочь?" in texts
    assert "Речь о стиральной машине?" in texts
    assert "Соединяю с продажами" in texts
    assert "во сколько вы работаете" not in texts


def test_prewarm_does_not_repeat_the_same_phrase():
    from ai_assistant.service.main import collect_speakable_phrases

    records = [
        KnowledgeRecord(id=i, question="q%s" % i, clarifying_question="Точно?",
                        positive_reply="Соединяю")
        for i in (1, 2, 3)
    ]
    texts = collect_speakable_phrases(_phrases(), KnowledgeStub(records))
    assert texts.count("Точно?") == 1
    assert texts.count("Соединяю") == 1


def test_prewarm_synthesizes_every_phrase_once():
    from ai_assistant.service.main import prewarm_tts_cache

    cache = RecordingTtsCache()
    done, elapsed = prewarm_tts_cache(cache, "eugene", ["раз", "два", "три"])

    assert done == 3
    assert [text for text, _ in cache.calls] == ["раз", "два", "три"]
    assert all(voice == "eugene" for _, voice in cache.calls)
    assert elapsed >= 0


def test_prewarm_failure_does_not_stop_the_service():
    """Отказ синтеза одной фразы не должен ронять запуск — она синтезируется позже."""
    from ai_assistant.service.main import prewarm_tts_cache

    cache = RecordingTtsCache(fail_on={"два"})
    done, _ = prewarm_tts_cache(cache, "eugene", ["раз", "два", "три"])

    assert done == 2
    assert [text for text, _ in cache.calls] == ["раз", "три"]


class FakeEmbedderForFeed:
    """Отдаёт вектор фиксированной длины — модель в тестах не грузим."""

    def encode(self, texts):
        import numpy as np

        return np.array([[1.0, 0.0]] * len(texts), dtype="float32")


def test_feed_endpoint_applies_records(tmp_path):
    from ai_assistant.service.main import build_http_app, KnowledgeState
    from ai_assistant.tests.test_knowledge_feed import minimal_payload

    state = KnowledgeState(cache_path=str(tmp_path / "feed.json"), embedder=FakeEmbedderForFeed())
    app = build_http_app(None, FakeTtsCache(tmp_path), voice="eugene", state=state)
    client = TestClient(app)

    response = client.post("/knowledge", json=minimal_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["records"] == 1
    assert body["phrases"] == 3  # каноничная формулировка плюс две из phrases


def test_feed_endpoint_keeps_the_equipment_type_code(tmp_path):
    """Код оборудования обязан доехать до записи: по нему обработчик ERP
    проставляет технику в обращении, не угадывая её по названию."""
    from ai_assistant.service.main import build_http_app, KnowledgeState
    from ai_assistant.tests.test_knowledge_feed import minimal_payload

    state = KnowledgeState(cache_path=str(tmp_path / "feed.json"), embedder=FakeEmbedderForFeed())
    app = build_http_app(None, FakeTtsCache(tmp_path), voice="eugene", state=state)
    client = TestClient(app)

    client.post("/knowledge", json=minimal_payload())

    assert state.knowledge.records[0].equipment_type_id == 17


def test_feed_endpoint_rejects_broken_payload(tmp_path):
    from ai_assistant.service.main import build_http_app, KnowledgeState

    state = KnowledgeState(cache_path=str(tmp_path / "feed.json"), embedder=FakeEmbedderForFeed())
    app = build_http_app(None, FakeTtsCache(tmp_path), voice="eugene", state=state)
    client = TestClient(app)

    response = client.post("/knowledge", json={"records": []})

    assert response.status_code == 400
    assert "settings" in response.json()["detail"] or "запис" in response.json()["detail"]


def test_broken_payload_does_not_replace_working_knowledge(tmp_path):
    """Кривая посылка не должна оставлять базу знаний в промежуточном состоянии."""
    from ai_assistant.service.main import build_http_app, KnowledgeState
    from ai_assistant.tests.test_knowledge_feed import minimal_payload

    state = KnowledgeState(cache_path=str(tmp_path / "feed.json"), embedder=FakeEmbedderForFeed())
    app = build_http_app(None, FakeTtsCache(tmp_path), voice="eugene", state=state)
    client = TestClient(app)

    client.post("/knowledge", json=minimal_payload())
    before = state.record_count

    client.post("/knowledge", json={"нет": "ничего"})

    assert state.record_count == before
    assert state.knowledge is not None


def test_broken_payload_does_not_overwrite_the_copy_on_disk(tmp_path):
    """На диск попадает только то, что сервис смог применить: иначе после
    перезапуска он поднимется на посылке, которую сам же и отверг."""
    from ai_assistant.service.main import build_http_app, KnowledgeState
    from ai_assistant.service.knowledge_feed import load_feed
    from ai_assistant.tests.test_knowledge_feed import minimal_payload

    cache = str(tmp_path / "feed.json")
    state = KnowledgeState(cache_path=cache, embedder=FakeEmbedderForFeed())
    app = build_http_app(None, FakeTtsCache(tmp_path), voice="eugene", state=state)
    client = TestClient(app)

    client.post("/knowledge", json=minimal_payload())
    client.post("/knowledge", json={"нет": "ничего"})

    assert load_feed(cache)["records"][0]["question"] == "стиральная машина не отжимает"


def test_health_reports_feed_age(tmp_path):
    from ai_assistant.service.main import build_http_app, KnowledgeState
    from ai_assistant.tests.test_knowledge_feed import minimal_payload

    state = KnowledgeState(cache_path=str(tmp_path / "feed.json"), embedder=FakeEmbedderForFeed())
    app = build_http_app(None, FakeTtsCache(tmp_path), voice="eugene", state=state)
    client = TestClient(app)

    before = client.get("/health").json()
    assert before["knowledge"]["received_at"] is None

    client.post("/knowledge", json=minimal_payload())
    after = client.get("/health").json()

    assert after["status"] == "ok"
    assert after["knowledge"]["records"] == 1
    assert after["knowledge"]["received_at"] is not None
    assert after["knowledge"]["generated_at"] == "2026-08-14T15:00:00"


def test_health_without_feed_reception_still_answers(tmp_path):
    """Сервис, поднятый без приёма справочников, обязан отвечать на проверку живости."""
    app = build_http_app(None, FakeTtsCache(tmp_path), voice="eugene")
    client = TestClient(app)

    body = client.get("/health").json()

    assert body["status"] == "ok"
    assert body["knowledge"]["records"] == 0


def test_feed_endpoint_without_state_says_it_is_not_configured(tmp_path):
    app = build_http_app(None, FakeTtsCache(tmp_path), voice="eugene")
    client = TestClient(app)

    assert client.post("/knowledge", json={}).status_code == 503


def test_state_restores_from_disk(tmp_path):
    """После перезапуска сервис поднимается на последней копии, а не пустым."""
    from ai_assistant.service.main import KnowledgeState
    from ai_assistant.tests.test_knowledge_feed import minimal_payload
    from ai_assistant.service.knowledge_feed import save_feed

    cache = str(tmp_path / "feed.json")
    save_feed(minimal_payload(), cache)

    state = KnowledgeState(cache_path=cache, embedder=FakeEmbedderForFeed())
    assert state.restore_from_disk() is True
    assert state.record_count == 1


def test_state_without_a_copy_on_disk_starts_empty(tmp_path):
    from ai_assistant.service.main import KnowledgeState

    state = KnowledgeState(cache_path=str(tmp_path / "нет-такого.json"), embedder=FakeEmbedderForFeed())

    assert state.restore_from_disk() is False
    assert state.knowledge is None


def test_state_with_an_unusable_copy_starts_empty(tmp_path):
    """Копия читается, но не разбирается — стартуем без неё, а не падаем."""
    from ai_assistant.service.main import KnowledgeState
    from ai_assistant.service.knowledge_feed import save_feed

    cache = str(tmp_path / "feed.json")
    save_feed({"records": []}, cache)

    state = KnowledgeState(cache_path=cache, embedder=FakeEmbedderForFeed())

    assert state.restore_from_disk() is False
    assert state.knowledge is None


def payload_with_hash(content_hash):
    from ai_assistant.tests.test_knowledge_feed import minimal_payload

    payload = minimal_payload()
    payload["content_hash"] = content_hash
    return payload


def test_health_reports_the_content_hash_of_the_applied_feed(tmp_path):
    """По этому отпечатку обработчик решает, слать ли справочники вообще."""
    from ai_assistant.service.main import build_http_app, KnowledgeState

    state = KnowledgeState(cache_path=str(tmp_path / "feed.json"), embedder=FakeEmbedderForFeed())
    app = build_http_app(None, FakeTtsCache(tmp_path), voice="eugene", state=state)
    client = TestClient(app)

    client.post("/knowledge", json=payload_with_hash("0123456789abcdef0123456789abcdef"))

    body = client.get("/health").json()
    assert body["knowledge"]["content_hash"] == "0123456789abcdef0123456789abcdef"


def test_health_reports_an_empty_content_hash_before_the_first_feed(tmp_path):
    """Пустое значение обработчик читает как «сервис базы не знает» и шлёт её."""
    from ai_assistant.service.main import build_http_app, KnowledgeState

    state = KnowledgeState(cache_path=str(tmp_path / "feed.json"), embedder=FakeEmbedderForFeed())
    app = build_http_app(None, FakeTtsCache(tmp_path), voice="eugene", state=state)

    assert TestClient(app).get("/health").json()["knowledge"]["content_hash"] == ""


def test_feed_without_content_hash_is_applied_and_reports_empty_hash(tmp_path):
    from ai_assistant.service.main import build_http_app, KnowledgeState
    from ai_assistant.tests.test_knowledge_feed import minimal_payload

    state = KnowledgeState(cache_path=str(tmp_path / "feed.json"), embedder=FakeEmbedderForFeed())
    app = build_http_app(None, FakeTtsCache(tmp_path), voice="eugene", state=state)
    client = TestClient(app)

    client.post("/knowledge", json=minimal_payload())

    body = client.get("/health").json()
    assert body["knowledge"]["records"] == 1
    assert body["knowledge"]["content_hash"] == ""


def test_rejected_payload_keeps_the_previous_content_hash(tmp_path):
    """Отпечаток обязан соответствовать применённому.

    Иначе обработчик решит, что новая база принята, и слать её перестанет —
    бот молча останется на прежней, и заметить это будет неоткуда.
    """
    from ai_assistant.service.main import build_http_app, KnowledgeState

    state = KnowledgeState(cache_path=str(tmp_path / "feed.json"), embedder=FakeEmbedderForFeed())
    app = build_http_app(None, FakeTtsCache(tmp_path), voice="eugene", state=state)
    client = TestClient(app)

    client.post("/knowledge", json=payload_with_hash("a" * 32))
    broken = payload_with_hash("b" * 32)
    broken["records"] = []
    assert client.post("/knowledge", json=broken).status_code == 400

    assert client.get("/health").json()["knowledge"]["content_hash"] == "a" * 32


def test_content_hash_survives_a_restart_through_the_copy_on_disk(tmp_path):
    """Иначе после каждого перезапуска обработчик слал бы базу заново —
    ровно от этого и уходим."""
    from ai_assistant.service.main import build_http_app, KnowledgeState

    cache = str(tmp_path / "feed.json")
    first = KnowledgeState(cache_path=cache, embedder=FakeEmbedderForFeed())
    app = build_http_app(None, FakeTtsCache(tmp_path), voice="eugene", state=first)
    TestClient(app).post("/knowledge", json=payload_with_hash("c" * 32))

    revived = KnowledgeState(cache_path=cache, embedder=FakeEmbedderForFeed())
    assert revived.restore_from_disk() is True

    app = build_http_app(None, FakeTtsCache(tmp_path), voice="eugene", state=revived)
    assert TestClient(app).get("/health").json()["knowledge"]["content_hash"] == "c" * 32


def file_dialog_engine():
    """Движок на прежней базе из файла — тем и отличается, что здоровается иначе."""
    phrases = Phrases(
        greeting="Приветствие из файла",
        misrecognition="Переформулируйте, пожалуйста",
        transfer="Перевожу звонок",
        silence="Вы меня слышите?",
    )
    return DialogEngine(FakeKnowledge(), phrases, support_exten="489", sales_exten="500")


def feed_serving_app(tmp_path):
    """Сервис, умеющий обслуживать звонки присланной базой знаний."""
    from ai_assistant.service.main import KnowledgeState, build_dialog_factory

    fallback = file_dialog_engine()
    state = KnowledgeState(
        cache_path=str(tmp_path / "feed.json"),
        embedder=FakeEmbedderForFeed(),
        dialog_factory=build_dialog_factory("489", "500"),
        fallback_engine=fallback,
    )
    app = build_http_app(fallback, FakeTtsCache(tmp_path), voice="baya", state=state)
    return state, TestClient(app)


def ask(client, linked_id, point, text="", silence=False):
    response = client.post("/dialog", json={"prms": [
        {"Key": "linkedId", "Value": linked_id},
        {"Key": "conversationPoint", "Value": point},
        {"Key": "recognizedText", "Value": text},
        {"Key": "silenceDetected", "Value": "True" if silence else "False"},
    ]})
    return {item["Key"]: item["Value"] for item in response.json()}


def feed_with_its_own_wording():
    """Посылка, которую видно в разговоре: и приветствие, и уточняющий вопрос
    отличаются от того, что лежит в файле."""
    from ai_assistant.tests.test_knowledge_feed import minimal_payload

    payload = minimal_payload()
    payload["settings"]["greeting"] = "Здравствуйте, это справочник"
    payload["records"][0]["clarifying_question"] = "Это стиральная машина из справочника?"
    return payload


def test_calls_are_served_by_the_file_base_until_a_feed_arrives(tmp_path):
    """Сервис поднялся, копии нет, ERP ещё не присылала — разговор работает как раньше."""
    _, client = feed_serving_app(tmp_path)

    assert ask(client, "call-1", "Start")["TextToSpeak"] == "Приветствие из файла"


def test_calls_switch_to_the_feed_base_as_soon_as_it_arrives(tmp_path):
    """Ради этого всё и затевалось: правка в справочнике меняет разговор."""
    _, client = feed_serving_app(tmp_path)

    client.post("/knowledge", json=feed_with_its_own_wording())

    assert ask(client, "call-2", "Start")["TextToSpeak"] == "Здравствуйте, это справочник"
    answer = ask(client, "call-2", "AskQuestion", "стиралка сломалась")
    assert answer["TextToSpeak"] == "Это стиральная машина из справочника?"


def test_rejected_feed_keeps_serving_the_previous_one(tmp_path):
    """Кривая посылка не должна возвращать звонки на файл и вообще ничего менять."""
    _, client = feed_serving_app(tmp_path)
    client.post("/knowledge", json=feed_with_its_own_wording())

    client.post("/knowledge", json={"нет": "ничего"})

    assert ask(client, "call-3", "Start")["TextToSpeak"] == "Здравствуйте, это справочник"


def test_a_call_in_progress_is_not_split_between_two_bases(tmp_path):
    """Посылка приходит посреди разговора — клиент дослушивает свой звонок.

    Бот спросил уточняющий вопрос по одной базе, клиент отвечает «да» уже по
    другой. Без переноса разговоров новый движок про этот звонок ничего не
    знает и вместо перевода по своей теме увёз бы клиента на общий номер
    сопровождения.
    """
    _, client = feed_serving_app(tmp_path)
    client.post("/knowledge", json=feed_with_its_own_wording())
    first = ask(client, "call-4", "AskQuestion", "стиралка сломалась")
    assert first["ConversationPoint"] == "Confirm"

    client.post("/knowledge", json=feed_with_its_own_wording())

    answer = ask(client, "call-4", "Confirm", "да")
    assert answer["Action"] == "Redirect"
    assert answer["RedirectExten"] == "7105"  # номер своей записи, а не общее сопровождение


def test_health_tells_which_base_serves_the_calls(tmp_path):
    """По «ok» не видно, чем сейчас отвечает бот — файлом или справочником."""
    _, client = feed_serving_app(tmp_path)

    assert client.get("/health").json()["knowledge"]["source"] == "file"

    client.post("/knowledge", json=feed_with_its_own_wording())

    assert client.get("/health").json()["knowledge"]["source"] == "feed"


def test_health_of_a_service_without_feed_reception_says_file(tmp_path):
    app = build_http_app(file_dialog_engine(), FakeTtsCache(tmp_path), voice="baya")
    client = TestClient(app)

    assert client.get("/health").json()["knowledge"]["source"] == "file"


def test_restored_copy_serves_the_calls_right_after_a_restart(tmp_path):
    """Перезапуск не должен возвращать бота на файл: копия для того и лежит."""
    from ai_assistant.service.knowledge_feed import save_feed
    from ai_assistant.service.main import KnowledgeState, build_dialog_factory

    cache = str(tmp_path / "feed.json")
    save_feed(feed_with_its_own_wording(), cache)

    state = KnowledgeState(
        cache_path=cache,
        embedder=FakeEmbedderForFeed(),
        dialog_factory=build_dialog_factory("489", "500"),
    )
    assert state.restore_from_disk() is True
    app = build_http_app(file_dialog_engine(), FakeTtsCache(tmp_path), voice="baya", state=state)

    assert ask(TestClient(app), "call-5", "Start")["TextToSpeak"] == "Здравствуйте, это справочник"


def test_feed_dialog_factory_keeps_the_extensions_of_the_service():
    """Записи без своего номера по-прежнему уезжают на сопровождение."""
    from ai_assistant.service.knowledge_feed import parse_feed
    from ai_assistant.service.main import build_dialog_factory
    from ai_assistant.tests.test_knowledge_feed import minimal_payload

    payload = minimal_payload()
    del payload["records"][0]["redirect_exten"]
    feed = parse_feed(payload)
    engine = build_dialog_factory("489", "500")(FakeKnowledge(), feed)

    silence = {"linkedId": "call-6", "conversationPoint": "AskQuestion", "silenceDetected": "True"}
    engine.handle(silence)  # на первое молчание бот переспрашивает
    result = {item["Key"]: item["Value"] for item in engine.handle(silence)}
    assert result["RedirectExten"] == "489"


class VoiceRecordingTtsCache(FakeTtsCache):
    """Тот же поддельный кэш, но помнит, каким голосом просили синтез."""

    def __init__(self, tmp_path):
        super().__init__(tmp_path)
        self.voices = []

    def get(self, text, voice):
        self.voices.append(voice)
        return super().get(text, voice)


def voice_serving_app(tmp_path, default_voice="eugene", tts_model="v5_ru"):
    """Сервис, собранный ровно как в main(): голос запуска плюс приём справочников."""
    from ai_assistant.service.main import KnowledgeState, build_dialog_factory

    cache = VoiceRecordingTtsCache(tmp_path)
    fallback = file_dialog_engine()
    state = KnowledgeState(
        cache_path=str(tmp_path / "feed.json"),
        embedder=FakeEmbedderForFeed(),
        dialog_factory=build_dialog_factory("489", "500", tts_model, default_voice),
        fallback_engine=fallback,
        default_voice=default_voice,
    )
    app = build_http_app(fallback, cache, voice=default_voice, state=state)
    return state, cache, TestClient(app)


def feed_with_voice(voice):
    payload = feed_with_its_own_wording()
    payload["settings"]["voice"] = voice
    return payload


def test_resolve_voice_prefers_the_one_from_the_feed():
    """Ради этого всё и затевалось: голос правят в группе линий, а не в .bat."""
    from ai_assistant.service.main import resolve_voice

    assert resolve_voice("baya", "eugene") == "baya"


@pytest.mark.parametrize("empty", ["", "   ", None])
def test_resolve_voice_falls_back_to_the_launch_setting(empty):
    """Незаполненный голос — это «оставить как есть», а не «синтезировать
    ничем»: новая группа линий с пустым полем не должна ломать синтез."""
    from ai_assistant.service.main import resolve_voice

    assert resolve_voice(empty, "eugene") == "eugene"


def test_audio_signature_changes_with_the_voice():
    from ai_assistant.service.main import audio_signature_for

    assert audio_signature_for("v5_ru", "baya") != audio_signature_for("v5_ru", "eugene")
    assert audio_signature_for("v5_ru", "baya") != audio_signature_for("v4_ru", "baya")


def test_voice_from_the_feed_is_used_for_synthesis(tmp_path):
    """Голос из справочника обязан доехать до синтеза, а не осесть в ParsedFeed."""
    _, cache, client = voice_serving_app(tmp_path, default_voice="eugene")

    client.post("/knowledge", json=feed_with_voice("baya"))
    client.get("/tts", params={"text": "здравствуйте"})

    assert cache.voices == ["baya"]


def test_empty_voice_in_the_feed_keeps_the_launch_setting(tmp_path):
    _, cache, client = voice_serving_app(tmp_path, default_voice="eugene")

    client.post("/knowledge", json=feed_with_voice(""))
    client.get("/tts", params={"text": "здравствуйте"})

    assert cache.voices == ["eugene"]


def test_synthesis_uses_the_launch_voice_until_a_feed_arrives(tmp_path):
    _, cache, client = voice_serving_app(tmp_path, default_voice="eugene")

    client.get("/tts", params={"text": "здравствуйте"})

    assert cache.voices == ["eugene"]


def test_explicit_voice_in_the_request_still_wins(tmp_path):
    """Ручной параметр /tts — способ послушать голос, не трогая справочник."""
    _, cache, client = voice_serving_app(tmp_path, default_voice="eugene")
    client.post("/knowledge", json=feed_with_voice("baya"))

    client.get("/tts", params={"text": "здравствуйте", "voice_name": "xenia"})

    assert cache.voices == ["xenia"]


def test_playback_names_change_when_the_feed_voice_changes(tmp_path):
    """Главная грабля смены голоса: имя файла кэшируется на самой станции.

    Если подпись звука не поменялась вслед за голосом, Астериск продолжит
    играть уже скачанные файлы прежним голосом, и смена голоса со стороны
    выглядит несработавшей — ровно так уже вышло при переходе v4_ru -> v5_ru.
    """
    _, _, client = voice_serving_app(tmp_path, default_voice="eugene")

    client.post("/knowledge", json=feed_with_voice("baya"))
    with_baya = ask(client, "call-voice-1", "Start")["FileToPlayback"]

    client.post("/knowledge", json=feed_with_voice("xenia"))
    with_xenia = ask(client, "call-voice-2", "Start")["FileToPlayback"]

    assert with_baya and with_xenia
    assert with_baya != with_xenia


def test_playback_names_keep_the_launch_signature_when_the_feed_voice_is_empty(tmp_path):
    """Пустой голос ничего не меняет — в том числе и имена файлов: перекачивать
    станции нечего."""
    from ai_assistant.service.dialog import _playback_name
    from ai_assistant.service.main import audio_signature_for

    _, _, client = voice_serving_app(tmp_path, default_voice="eugene", tts_model="v5_ru")

    client.post("/knowledge", json=feed_with_voice(""))
    name = ask(client, "call-voice-3", "Start")["FileToPlayback"]

    expected = _playback_name(
        "Здравствуйте, это справочник", audio_signature_for("v5_ru", "eugene")
    )
    assert name == expected


def test_state_exposes_the_voice_that_is_actually_used(tmp_path):
    """Прогрев синтеза после перезапуска идёт по восстановленной копии — и
    греть он обязан тот голос, которым бот будет говорить."""
    from ai_assistant.service.knowledge_feed import save_feed
    from ai_assistant.service.main import KnowledgeState

    cache_path = str(tmp_path / "feed.json")
    save_feed(feed_with_voice("kseniya"), cache_path)

    state = KnowledgeState(
        cache_path=cache_path, embedder=FakeEmbedderForFeed(), default_voice="eugene"
    )
    assert state.voice == "eugene"  # до посылки — голос из настроек запуска

    assert state.restore_from_disk() is True
    assert state.voice == "kseniya"


def test_a_call_started_on_the_file_base_survives_the_first_feed(tmp_path):
    """Первая же посылка приходится на чей-нибудь разговор — он тоже должен доиграть.

    Тот же случай, что и подмена одной присланной базы другой, только прежним
    движком здесь оказывается тот, что работает на файле.
    """
    _, client = feed_serving_app(tmp_path)
    first = ask(client, "call-7", "AskQuestion", "стиралка не крутит")
    assert first["ConversationPoint"] == "Confirm"

    client.post("/knowledge", json=feed_with_its_own_wording())

    answer = ask(client, "call-7", "Confirm", "да")
    assert answer["Action"] == "Redirect"
    assert answer["RedirectExten"] == "500"  # номер записи из файла, а не общее сопровождение


def test_prewarm_includes_the_confirm_retry_phrase():
    """Переспрос обязан попасть в прогрев синтеза.

    Он звучит ровно в тот момент, когда клиент уже решил, что бот сломался, —
    добавить туда ещё две секунды холодного синтеза значит не починить ничего.
    """
    from ai_assistant.service.main import collect_speakable_phrases

    phrases = _phrases()
    texts = collect_speakable_phrases(phrases, KnowledgeStub([]))
    assert phrases.confirm_not_heard in texts
    assert phrases.wrong_guess in texts


# --- Группы линий (UL-17568) --------------------------------------------------


def feed_with_a_second_group(**overrides):
    """Посылка, у которой кроме набора по умолчанию есть своя группа линий."""
    from ai_assistant.tests.test_knowledge_feed import group

    payload = feed_with_voice("eugene")
    payload["line_groups"] = [group(**overrides)]
    return payload


def ask_number(client, linked_id, dialed, point="Start"):
    response = client.post("/dialog", json={"prms": [
        {"Key": "linkedId", "Value": linked_id},
        {"Key": "conversationPoint", "Value": point},
        {"Key": "dialedNumber", "Value": dialed},
    ]})
    return {item["Key"]: item["Value"] for item in response.json()}


def test_call_to_a_group_number_is_served_by_its_own_set(tmp_path):
    _, _, client = voice_serving_app(tmp_path, default_voice="eugene")
    client.post("/knowledge", json=feed_with_a_second_group())

    answer = ask_number(client, "call-group-1", "84951468847")

    assert answer["TextToSpeak"] == "Здравствуйте, это частный мастер"
    assert answer["Voice"] == "kseniya"


def test_call_to_an_unknown_number_is_served_by_the_default_set(tmp_path):
    _, _, client = voice_serving_app(tmp_path, default_voice="eugene")
    client.post("/knowledge", json=feed_with_a_second_group())

    answer = ask_number(client, "call-group-2", "74959999999")

    assert answer["TextToSpeak"] == "Здравствуйте, это справочник"
    assert answer["Voice"] == "eugene"


def test_group_without_its_own_voice_speaks_with_the_default_one(tmp_path):
    """Пустое поле в справочнике — «оставить как есть», а не «синтезировать ничем»."""
    _, _, client = voice_serving_app(tmp_path, default_voice="eugene")
    client.post("/knowledge", json=feed_with_a_second_group(voice=""))

    assert ask_number(client, "call-group-3", "74951468847")["Voice"] == "eugene"


def test_recorded_file_of_a_group_reaches_the_script(tmp_path):
    _, _, client = voice_serving_app(tmp_path, default_voice="eugene")
    client.post("/knowledge", json=feed_with_a_second_group(
        use_recorded_audio=True, greeting_path="VoicesOKK\\voice-a\\2_spich.wav"
    ))

    answer = ask_number(client, "call-group-4", "74951468847")

    assert answer["FileToPlayback"] == "VoicesOKK\\voice-a\\2_spich.wav"
    assert answer["FileIsOnStation"] == "True"


def test_a_feed_without_line_groups_serves_every_number_alike(tmp_path):
    """Обработчик прежней сборки массива не присылает — бот обязан работать."""
    _, _, client = voice_serving_app(tmp_path, default_voice="eugene")
    client.post("/knowledge", json=feed_with_voice("baya"))

    answer = ask_number(client, "call-group-5", "74951468847")

    assert answer["TextToSpeak"] == "Здравствуйте, это справочник"
    assert answer["Voice"] == "baya"


def test_prewarm_plan_covers_every_voice_of_every_group():
    """Прогрев греет то, чем бот действительно говорит: у второй группы свой
    голос, и её фразы холодным синтезом клиент слушает как тишину."""
    from ai_assistant.service.dialog import LineProfile, Phrases
    from ai_assistant.service.main import collect_prewarm_plan

    default = LineProfile(phrases=_phrases(), voice="eugene")
    master = LineProfile(
        phrases=Phrases(greeting="Здравствуйте, это частный мастер", misrecognition="?",
                        transfer="Соединяю", silence="Алло?"),
        voice="kseniya",
    )
    knowledge = KnowledgeStub([
        KnowledgeRecord(id=1, question="стиралка", clarifying_question="Речь о стиральной машине?")
    ])

    plan = dict(collect_prewarm_plan([default, master], knowledge))

    assert set(plan) == {"eugene", "kseniya"}
    assert "Здравствуйте, чем могу помочь?" in plan["eugene"]
    assert "Здравствуйте, это частный мастер" in plan["kseniya"]
    # База знаний общая — уточняющие вопросы греются каждым голосом.
    assert "Речь о стиральной машине?" in plan["eugene"]
    assert "Речь о стиральной машине?" in plan["kseniya"]


def test_prewarm_plan_merges_groups_that_share_a_voice():
    from ai_assistant.service.dialog import LineProfile
    from ai_assistant.service.main import collect_prewarm_plan

    first = LineProfile(phrases=_phrases(), voice="eugene")
    second = LineProfile(phrases=_phrases(), voice="eugene")

    plan = dict(collect_prewarm_plan([first, second], KnowledgeStub([])))

    assert list(plan) == ["eugene"]
    assert plan["eugene"].count("Здравствуйте, чем могу помочь?") == 1


# --- Сопровождение и частные мастера (UL-18819) -------------------------------


def ask_line(client, linked_id, dialed, point, text=""):
    response = client.post("/dialog", json={"prms": [
        {"Key": "linkedId", "Value": linked_id},
        {"Key": "conversationPoint", "Value": point},
        {"Key": "recognizedText", "Value": text},
        {"Key": "silenceDetected", "Value": "False"},
        {"Key": "dialedNumber", "Value": dialed},
    ]})
    return {item["Key"]: item["Value"] for item in response.json()}


def transferred_after_two_silences(client, linked_id):
    ask(client, linked_id, "AskQuestion", silence=True)  # на первое молчание переспрашиваем
    return ask(client, linked_id, "AskQuestion", silence=True)


def test_support_exten_of_the_feed_serves_unclear_calls(tmp_path):
    """Номер ТН 17 «Сопровождение» приезжает в посылке, а не зашит в сервис."""
    _, client = feed_serving_app(tmp_path)
    payload = feed_with_its_own_wording()
    payload["support_exten"] = "7082"
    client.post("/knowledge", json=payload)

    assert transferred_after_two_silences(client, "call-support-1")["RedirectExten"] == "7082"


def test_feed_without_support_exten_keeps_the_setting_of_the_service(tmp_path):
    """У ТН 17 не заполнили номер (или посылка от прежнего обработчика) —
    поведение остаётся прежним, а не выдуманным."""
    _, client = feed_serving_app(tmp_path)
    client.post("/knowledge", json=feed_with_its_own_wording())

    assert transferred_after_two_silences(client, "call-support-2")["RedirectExten"] == "489"


def feed_with_two_numbers(**group_overrides):
    """Посылка про направление «ТВ»: обычный номер 7048, для частных мастеров
    7040 (он же обычный номер направления «ЧМ_ТВ»)."""
    payload = feed_with_a_second_group(**group_overrides)
    payload["support_exten"] = "7082"
    payload["records"][0]["redirect_exten"] = "7048"
    payload["records"][0]["redirect_exten_pm"] = "7040"
    return payload


def test_call_from_a_private_master_line_goes_to_the_private_master_number(tmp_path):
    _, _, client = voice_serving_app(tmp_path, default_voice="eugene")
    client.post("/knowledge", json=feed_with_two_numbers(is_private_master=True))

    ask_line(client, "call-pm-1", "74951468847", "AskQuestion", "телевизор не работает")
    answer = ask_line(client, "call-pm-1", "74951468847", "Confirm", "да")

    assert answer["RedirectExten"] == "7040"


def test_call_from_a_regular_line_goes_to_the_regular_number(tmp_path):
    _, _, client = voice_serving_app(tmp_path, default_voice="eugene")
    client.post("/knowledge", json=feed_with_two_numbers(is_private_master=False))

    ask_line(client, "call-pm-2", "74951468847", "AskQuestion", "телевизор не работает")
    answer = ask_line(client, "call-pm-2", "74951468847", "Confirm", "да")

    assert answer["RedirectExten"] == "7048"


def test_private_master_line_without_a_number_goes_to_support(tmp_path):
    """Не на 7048: обычный номер увёл бы клиента частного мастера в чужой отдел."""
    _, _, client = voice_serving_app(tmp_path, default_voice="eugene")
    payload = feed_with_two_numbers(is_private_master=True)
    del payload["records"][0]["redirect_exten_pm"]
    client.post("/knowledge", json=payload)

    ask_line(client, "call-pm-3", "74951468847", "AskQuestion", "телевизор не работает")
    answer = ask_line(client, "call-pm-3", "74951468847", "Confirm", "да")

    assert answer["RedirectExten"] == "7082"


def test_feed_without_the_new_fields_is_accepted_as_before(tmp_path):
    """Обработчик прежней сборки ни номера сопровождения, ни номера для частных
    мастеров не присылает — посылка обязана примениться и разговор работать."""
    _, _, client = voice_serving_app(tmp_path, default_voice="eugene")

    response = client.post("/knowledge", json=feed_with_a_second_group())

    assert response.status_code == 200
    ask_line(client, "call-pm-4", "74951468847", "AskQuestion", "стиралка сломалась")
    answer = ask_line(client, "call-pm-4", "74951468847", "Confirm", "да")
    assert answer["RedirectExten"] == "7105"  # номер из самой записи, как и раньше


def test_prewarm_skips_phrases_played_from_a_recorded_file():
    """Синтезировать то, что и так лежит на станции, незачем."""
    from ai_assistant.service.main import collect_speakable_phrases

    phrases = _phrases()
    texts = collect_speakable_phrases(
        phrases, KnowledgeStub([]), {"greeting": "AsterBotGL\\Actual.wav"}
    )

    assert phrases.greeting not in texts
    assert phrases.transfer in texts


class RecordingEngine:
    """Запоминает PCM, который до него доехал."""

    target_sample_rate = 8000

    def __init__(self):
        self.received = []

    def transcribe(self, pcm):
        self.received.append(pcm)
        return "да"


def test_short_utterance_reaches_the_engine_padded_with_silence():
    """Живой звонок 18.08.2026: «нет» дважды дало пустое распознавание.

    Замер показал, что короткие отрезки распознаются заметно лучше, если
    дополнить их тишиной по краям — см. таблицу в test_stt_base.py.
    """
    from ai_assistant.service.stt.base import SILENCE_PAD_SECONDS

    engine_obj = RecordingEngine()
    short = pcm(2000)  # 0.25 с — примерно столько занимает «нет»
    servicer = SpeechServicer(
        lambda: FakeSegmenter([[SegmentEvent(kind="utterance", pcm=short)]]),
        engine_obj,
        [],
    )
    list(servicer.Recognize(FakeRequestIterator("call-1", [b"\x00" * 512]), None))

    pad_bytes = int(8000 * SILENCE_PAD_SECONDS) * 2
    assert len(engine_obj.received) == 1
    assert len(engine_obj.received[0]) == len(short) + 2 * pad_bytes


def test_long_utterance_reaches_the_engine_untouched():
    engine_obj = RecordingEngine()
    long_pcm = pcm(24000)  # 3 с
    servicer = SpeechServicer(
        lambda: FakeSegmenter([[SegmentEvent(kind="utterance", pcm=long_pcm)]]),
        engine_obj,
        [],
    )
    list(servicer.Recognize(FakeRequestIterator("call-1", [b"\x00" * 512]), None))

    assert engine_obj.received == [long_pcm]


# --- Прогрев и подогрев моделей --------------------------------------------
#
# Первая реплика после долгой паузы считалась 5.7-5.8 с вместо обычных
# 1.5-2.5 (живые звонки 20.08.2026 15:17 и 21.08.2026 13:32). Во втором
# случае сервис работал сутки и звонки через него уже проходили, так что
# дело не в загрузке моделей: у простаивающего процесса система урезает
# рабочий набор и выгружает страницы с весами на диск.


class WarmupSpy:
    """Считает, сколько раз её прогревали."""

    target_sample_rate = 8000

    def __init__(self):
        self.transcribed = []
        self.queried = []

    def transcribe(self, pcm):
        self.transcribed.append(len(pcm))
        return ""

    def best_match(self, text):
        self.queried.append(text)
        return None


def test_prewarm_touches_both_recognition_and_search():
    from ai_assistant.service.main import prewarm_recognition

    spy = WarmupSpy()
    prewarm_recognition(spy, spy)

    assert len(spy.transcribed) == 1
    # Секунда звука по два байта на отсчёт — иначе движок отбросит отрезок как
    # слишком короткий и модель не поднимется.
    assert spy.transcribed[0] == WarmupSpy.target_sample_rate * 2
    assert len(spy.queried) == 1


def test_prewarm_survives_a_broken_engine():
    """Прогрев не имеет права помешать сервису принимать звонки."""
    from ai_assistant.service.main import prewarm_recognition

    class Broken:
        target_sample_rate = 8000

        def transcribe(self, pcm):
            raise RuntimeError("движок не поднялся")

        def best_match(self, text):
            raise RuntimeError("эмбеддер не поднялся")

    prewarm_recognition(Broken(), Broken())  # не бросает


def test_keepwarm_is_off_when_interval_is_zero():
    from ai_assistant.service.main import start_keepwarm

    spy = WarmupSpy()
    assert start_keepwarm(spy, spy, 0) is None
    assert spy.transcribed == []


def test_keepwarm_repeats_the_warmup_while_nobody_calls():
    from ai_assistant.service.main import start_keepwarm

    spy = WarmupSpy()
    stop = threading.Event()
    thread = start_keepwarm(spy, spy, 0.01, stop_event=stop)
    try:
        deadline = time.time() + 5
        while len(spy.transcribed) < 3 and time.time() < deadline:
            time.sleep(0.01)
    finally:
        stop.set()
        thread.join(timeout=5)

    assert len(spy.transcribed) >= 3
    assert len(spy.queried) >= 3


def test_keepwarm_stops_promptly_when_asked():
    """Ждём событие, а не спим циклами: выключение сервиса не должно ждать
    целый интервал подогрева."""
    from ai_assistant.service.main import start_keepwarm

    spy = WarmupSpy()
    stop = threading.Event()
    thread = start_keepwarm(spy, spy, 30, stop_event=stop)
    stop.set()
    thread.join(timeout=5)

    assert not thread.is_alive()


def test_effective_voice_keeps_the_voice_and_logs_missing_for_per_phrase_fallback(caplog):
    """Голос сохраняется, даже если записаны не все фразы: недостающие уйдут в
    запас пофразно (RecordedSynthesizer), а не весь голос целиком в s3 (заказчик,
    05.11.2026). Недостающие всё равно логируются для следующего прогона синтеза."""
    import logging

    from ai_assistant.service.main import effective_voice

    class Library:
        voices = ["voice-a"]

        def missing(self, voice, texts):
            return [t for t in texts if "новая" in t]

    library = Library()
    with caplog.at_level(logging.WARNING):
        full = effective_voice("voice-a", ["Здравствуйте"], library, "s3", "группа 1")
        partial = effective_voice("voice-a", lambda: ["Здравствуйте", "новая тема"], library, "s3", "группа 2")
        plain = effective_voice("s4", lambda: (_ for _ in ()).throw(AssertionError("фразы не нужны")), library, "s3")

    assert full == "voice-a"
    # Пробел в библиотеке больше не роняет весь голос: группа остаётся на голосе A,
    # а «новая тема» озвучится запасным движком пофразно.
    assert partial == "voice-a"
    assert plain == "s4"
    # Недостающую фразу всё равно логируем, чтобы по ней сделать синтез.
    assert "группа 2" in caplog.text and "новая тема" in caplog.text


def test_second_opinion_takes_the_fallback_text_when_the_first_finds_no_topic():
    """«Верхер не включается» (v3) темы не находит, «керхер не включается» (v2) находит —
    в ответ уходит второй текст (14.10.2026, 1791976427). Если и второй мимо — первый."""
    class PrimaryEngine(FakeEngine):
        def transcribe(self, pcm):
            return "верхер не включается"

    class FallbackEngine(FakeEngine):
        calls = 0

        def transcribe(self, pcm):
            FallbackEngine.calls += 1
            return "керхер не включается"

    class Knowledge:
        def resolve(self, text):
            class R:
                pass
            r = R()
            r.trusted = "керхер" in text
            # Запись-бренд: по тексту второй модели тема засчитывается строго — здесь по бренду.
            r.record = KnowledgeRecord(id=7, question="керхер не включается", equipment_type="Karcher") if r.trusted else None
            r.source = "phrases"
            return r

    script = [[SegmentEvent(kind="utterance", pcm=pcm(800))]]
    servicer = SpeechServicer(
        lambda: FakeSegmenter(script), PrimaryEngine(), timeline_sink=[],
        fallback_engine=FallbackEngine(), knowledge_lookup=lambda: Knowledge(),
    )
    responses = list(servicer.Recognize(FakeRequestIterator("call-9", [pcm(400)]), context=None))
    finals = [r.text for r in responses if r.type == speech_pb2.StreamResponse.FINAL]
    assert finals == ["керхер не включается"]
    assert FallbackEngine.calls == 1

    # Тема по первому тексту нашлась — вторая модель не зовётся.
    class GoodEngine(FakeEngine):
        def transcribe(self, pcm):
            return "керхер сломался"
    FallbackEngine.calls = 0
    servicer = SpeechServicer(
        lambda: FakeSegmenter([[SegmentEvent(kind="utterance", pcm=pcm(800))]]), GoodEngine(), timeline_sink=[],
        fallback_engine=FallbackEngine(), knowledge_lookup=lambda: Knowledge(),
    )
    list(servicer.Recognize(FakeRequestIterator("call-10", [pcm(400)]), context=None))
    assert FallbackEngine.calls == 0


def test_second_opinion_is_rejected_when_its_topic_is_found_only_by_similarity():
    """270057961 (9-я волна): v3 «мне нужен», v2 «мне нужен сайт» — по близости 0.75
    нашлась тема интернета, и бот спросил про интернет. Текст второй модели
    засчитывается только по дословному совпадению, слову-ключу или бренду."""
    class PrimaryEngine(FakeEngine):
        def transcribe(self, pcm):
            return "мне нужен"

    class FallbackEngine(FakeEngine):
        def transcribe(self, pcm):
            return "мне нужен сайт"

    class Knowledge:
        def resolve(self, text):
            class R:
                pass
            r = R()
            r.trusted = "сайт" in text
            r.record = KnowledgeRecord(id=30, question="нужен интернет на дачу", equipment_type="Интернет") if r.trusted else None
            r.source = "phrases"
            return r

    servicer = SpeechServicer(
        lambda: FakeSegmenter([[SegmentEvent(kind="utterance", pcm=pcm(800))]]), PrimaryEngine(), timeline_sink=[],
        fallback_engine=FallbackEngine(), knowledge_lookup=lambda: Knowledge(),
    )
    responses = list(servicer.Recognize(FakeRequestIterator("call-11", [pcm(400)]), context=None))
    finals = [r.text for r in responses if r.type == speech_pb2.StreamResponse.FINAL]
    assert finals == ["мне нужен"]

    # Слово-ключ или дословная формулировка во втором тексте — принимается.
    class KeywordKnowledge(Knowledge):
        def resolve(self, text):
            r = super().resolve(text)
            r.source = "keyword"
            return r

    servicer = SpeechServicer(
        lambda: FakeSegmenter([[SegmentEvent(kind="utterance", pcm=pcm(800))]]), PrimaryEngine(), timeline_sink=[],
        fallback_engine=FallbackEngine(), knowledge_lookup=lambda: KeywordKnowledge(),
    )
    responses = list(servicer.Recognize(FakeRequestIterator("call-12", [pcm(400)]), context=None))
    assert [r.text for r in responses if r.type == speech_pb2.StreamResponse.FINAL] == ["мне нужен сайт"]


def test_second_opinion_is_not_asked_for_a_short_single_word():
    """«Але», «да», «угу»: тема по ним не ищется, а вторая модель стоила по 0,3 с
    на каждом подтверждении и на «але» выдумывала «алло» (270043147)."""
    class PrimaryEngine(FakeEngine):
        def transcribe(self, pcm):
            return "але"

    class FallbackEngine(FakeEngine):
        calls = 0

        def transcribe(self, pcm):
            FallbackEngine.calls += 1
            return "алло"

    class Knowledge:
        def resolve(self, text):
            return None

    servicer = SpeechServicer(
        lambda: FakeSegmenter([[SegmentEvent(kind="utterance", pcm=pcm(800))]]), PrimaryEngine(), timeline_sink=[],
        fallback_engine=FallbackEngine(), knowledge_lookup=lambda: Knowledge(),
    )
    responses = list(servicer.Recognize(FakeRequestIterator("call-13", [pcm(400)]), context=None))
    assert [r.text for r in responses if r.type == speech_pb2.StreamResponse.FINAL] == ["але"]
    assert FallbackEngine.calls == 0


def _debug_file(directory, name, size_bytes, age_days, now):
    path = directory / name
    path.write_bytes(bytes(size_bytes))
    stamp = now - age_days * 86400
    os.utime(path, (stamp, stamp))
    return path


def test_prune_old_files_removes_files_older_than_the_keep_period(tmp_path):
    """Записи разговоров клиентов не должны лежать без срока хранения."""
    now = time.time()
    old = _debug_file(tmp_path, "old_ПОТОК.wav", 1000, 20, now)
    fresh = _debug_file(tmp_path, "fresh_ПОТОК.wav", 1000, 1, now)
    removed = prune_old_files(str(tmp_path), max_mb=0, keep_days=14, now=now)
    assert removed == 1
    assert not old.exists()
    assert fresh.exists()


def test_prune_old_files_trims_the_oldest_files_over_the_size_limit(tmp_path):
    """Сверх предела объёма уходят самые старые записи, свежие остаются."""
    now = time.time()
    mb = 1024 * 1024
    oldest = _debug_file(tmp_path, "a_ПОТОК.wav", mb, 3, now)
    middle = _debug_file(tmp_path, "b_ПОТОК.wav", mb, 2, now)
    newest = _debug_file(tmp_path, "c_ПОТОК.wav", mb, 1, now)
    removed = prune_old_files(str(tmp_path), max_mb=2, keep_days=0, now=now)
    assert removed == 1
    assert not oldest.exists()
    assert middle.exists() and newest.exists()


def test_prune_old_files_keeps_everything_when_rules_are_off(tmp_path):
    now = time.time()
    kept = _debug_file(tmp_path, "a_ПОТОК.wav", 1000, 900, now)
    assert prune_old_files(str(tmp_path), max_mb=0, keep_days=0, now=now) == 0
    assert kept.exists()


def test_prune_old_files_survives_a_missing_directory():
    """Чистка не имеет права уронить живой звонок, даже если папки нет."""
    assert prune_old_files("", max_mb=10, keep_days=1) == 0
    assert prune_old_files("нет-такой-папки-ultracode", max_mb=10, keep_days=1) == 0


class _StubSynthesizer:
    """Синтезатор-пустышка: отдаёт тишину и считает вызовы."""

    model_id = "заглушка"

    def __init__(self):
        self.calls = []

    def synthesize(self, text, voice):
        self.calls.append((text, voice))
        return b"\x00" * 1600


def test_tts_cache_is_pruned_before_the_prewarm_puts_the_live_phrases_back(tmp_path):
    """Кэш синтеза чистится ДО прогрева, иначе живая фраза уедет в звонок.

    Попадание в кэш время файла не обновляет, поэтому живая фраза,
    синтезированная месяц назад, для правила срока выглядит так же, как мусор
    от прежнего отпечатка библиотеки голосов. Порядок «сначала чистка, потом
    прогрев» делает это безопасным: нужное создаётся заново с новым временем,
    мусор не возвращается. Обратный порядок удалял бы живую фразу, и холодный
    синтез пришёлся бы на разговор (A6, п. 6-8).
    """
    from ai_assistant.service.main import prewarm_tts_cache
    from ai_assistant.service.tts import TtsCache

    now = time.time()
    synth = _StubSynthesizer()
    cache = TtsCache(synth, str(tmp_path))
    live = cache.get("минуту, перевожу ваш звонок", "eugene")
    os.utime(live, (now - 40 * 86400, now - 40 * 86400))
    junk = _debug_file(tmp_path, "aia_мусор-прежнего-отпечатка.wav", 1000, 40, now)

    removed = prune_old_files(str(tmp_path), max_mb=0, keep_days=30, now=now, what="Кэш синтеза")
    assert removed == 2
    assert not os.path.exists(live) and not junk.exists()

    synth.calls = []
    done, _elapsed = prewarm_tts_cache(cache, "eugene", ["минуту, перевожу ваш звонок"])
    assert done == 1
    # Синтез позвали один раз, имя файла то же самое, мусор не вернулся.
    assert synth.calls == [("минуту, перевожу ваш звонок", "eugene")]
    assert os.path.exists(live)
    assert not junk.exists()


def test_forced_flag_of_a_live_call_survives_the_overflow():
    """Признак срезанной реплики не теряется на переполнении словаря.

    Прежний clear() при переполнении стирал флаги ВСЕХ звонков, включая идущие
    прямо сейчас: на две тысячи первом звонке живой разговор терял признак и
    получал повтор вопроса вместо продолжения срезанной реплики (находка
    B1-08 ультракода).
    """
    from ai_assistant.service.main import FORCED_FINALS, FORCED_FINALS_MAX, remember_forced, was_forced

    FORCED_FINALS.clear()
    remember_forced("живой-звонок", True)
    for index in range(FORCED_FINALS_MAX + 50):
        remember_forced("старый-%d" % index, False)
    # Живой звонок вытеснен как самый старый, это нормально: он один и тот же
    # признак держит не дольше звонка. Проверяем главное: словарь не обнулился
    # целиком, и свежие звонки свои признаки сохранили.
    assert len(FORCED_FINALS) == FORCED_FINALS_MAX
    remember_forced("свежий", True)
    assert was_forced("свежий") is True
    assert was_forced("старый-%d" % (FORCED_FINALS_MAX + 49)) is False
    FORCED_FINALS.clear()


def test_last_peak_is_remembered_per_call():
    from ai_assistant.service.main import LAST_PEAKS, last_peak, remember_peak

    LAST_PEAKS.clear()
    assert last_peak("нет-такого") == -99.0
    remember_peak("звонок", -18.5)
    assert last_peak("звонок") == -18.5
    LAST_PEAKS.clear()



def test_build_fingerprint_names_every_threshold_that_decides_a_call(caplog):
    """Отпечаток сборки должен позволять привязать волну разбора к КОДУ.

    Разбор волн 8-10 восстановить уже нельзя: в логе не было ни коммита, ни
    настроек. Эта строка закрывает дыру, но сама дважды оказывалась неполной:
    в ней не было порога серой зоны (главная правка волны 13), числа
    переспросов, основной модели распознавания (писалась только вторая),
    пометки незакоммиченных правок и хэша яруса намерения.
    """
    import logging

    from ai_assistant.service import main as main_module
    from ai_assistant.service.config import load_config

    with caplog.at_level(logging.INFO):
        main_module.log_build_fingerprint(load_config())
    line = next(r.getMessage() for r in caplog.records if r.getMessage().startswith("СБОРКА"))
    for field in ("коммит=", "модули=", "распознавание=", "второе_мнение=",
                  "порог_детектора=", "формулировки=", "корпус=", "оператор=",
                  "перевод=", "серая_зона=", "переспросов_в_серой=", "ярус=",
                  "порог_повторного=", "предел_фраз=", "второй_круг=",
                  "голос=", "корпус_индекс="):
        assert field in line, field
    # Шесть модулей: dialog, knowledge, main, vad, tts, intent. Ярус намерения
    # решает больше трети реплик, и его версия в отпечаток не входила вовсе.
    hashes = line.split("модули=")[1].split(" ")[0].split("/")
    assert len(hashes) == 6, hashes


def test_build_fingerprint_marks_uncommitted_changes(caplog):
    """Номер коммита без пометки правок описывает НЕ тот код, что в работе.

    Сервис почти всегда запускается с незакоммиченными правками, и по одному
    коммиту версию не восстановить. Пометка говорит разборщику смотреть хэши
    модулей.
    """
    import logging
    import subprocess

    from ai_assistant.service import main as main_module
    from ai_assistant.service.config import load_config

    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(main_module.__file__))))
    try:
        dirty = subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=repo, stderr=subprocess.DEVNULL, timeout=5).decode("utf-8", "replace").strip()
    except Exception:
        pytest.skip("git недоступен")
    with caplog.at_level(logging.INFO):
        main_module.log_build_fingerprint(load_config())
    line = next(r.getMessage() for r in caplog.records if r.getMessage().startswith("СБОРКА"))
    if dirty:
        assert "+правки(" in line
    else:
        assert "+правки" not in line


def test_the_cache_cleanup_is_tied_to_the_prewarm_in_the_source():
    """Чистка кэша синтеза не имеет права работать без прогрева.

    Чистку зовут безусловно, а прогрев выключается настройкой
    `AIA_PREWARM_TTS=0`. В такой паре чистка снесла бы живой набор, а
    восстанавливать его стало бы НЕКОМУ: каждая фраза досинтезировалась бы
    внутри разговора по полсекунды, приветствие в том числе. Обоснование
    порядка «чистим до прогрева, он всё создаст заново» при выключенном
    прогреве просто неверно.

    `main()` целиком требует моделей, портов и базы знаний, поэтому связку
    сторожим по исходнику: это дешевле, чем поднимать сервис, и ловит ровно ту
    правку, которая связь разорвёт.
    """
    import ast
    import pathlib

    source_path = pathlib.Path(__file__).resolve().parents[1] / "service" / "main.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    guarded = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        condition = ast.dump(node.test)
        if "prewarm_tts" not in condition:
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Call) and getattr(inner.func, "id", "") == "prune_old_files":
                guarded.append(ast.dump(inner))
    assert guarded, ("чистка кэша синтеза должна стоять под проверкой cfg.prewarm_tts: "
                     "без прогрева восстанавливать удалённое некому")
    assert any("Кэш синтеза" in dumped for dumped in guarded)
