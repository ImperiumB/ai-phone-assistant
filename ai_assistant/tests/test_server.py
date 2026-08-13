import os
import struct
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "proto"))
import speech_pb2  # noqa: E402

from ai_assistant.service.dialog import DialogEngine, Phrases
from ai_assistant.service.knowledge import KnowledgeRecord
from ai_assistant.service.main import SpeechServicer, build_http_app
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
    def search(self, text):
        record = KnowledgeRecord(
            id=1,
            question="стиральная машина не отжимает",
            clarifying_question="Речь о стиральной машине?",
            positive_answers=["да"],
            negative_answers=["нет"],
            positive_reply="Соединяю",
            scenario="redirect_sales",
            equipment_type="Стиральные машины",
        )
        return record, 0.9

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
