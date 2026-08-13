"""Сборка сервиса: gRPC-поток распознавания плюс HTTP-ручки диалога и синтеза."""
import logging
import os
import sys
import threading
from collections import deque
from concurrent import futures
from typing import Callable, List

import grpc
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse

# Демон работает постоянно, поэтому ограничения ниже — не опция, а
# обязательное условие (Important 4/5 из ревью Task 9):
#  - таймлайнов на реплики без предела накопилось бы неограниченно много за
#    время жизни процесса — храним только последние N;
#  - остановка gRPC не должна ждать бесконечно, если в моменте есть активный
#    звонок — даём разумный срок и после него завершаемся принудительно.
MAX_TIMELINE_RECORDS = 500
GRPC_SHUTDOWN_GRACE_SECONDS = 5

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "proto"))
import speech_pb2  # noqa: E402
import speech_pb2_grpc  # noqa: E402

from ai_assistant.service.config import load_config  # noqa: E402
from ai_assistant.service.dialog import (  # noqa: E402
    DialogEngine,
    Phrases,
    prms_to_dict,
)
from ai_assistant.service.knowledge import (  # noqa: E402
    SentenceTransformerEmbedder,
    load_knowledge_base,
)
from ai_assistant.service.metrics import (  # noqa: E402
    STAGE_SPEECH_END,
    STAGE_STT_DONE,
    CallTimeline,
)
from ai_assistant.service.stt.base import create_engine, prepare_audio  # noqa: E402
from ai_assistant.service.tts import SileroSynthesizer, TtsCache  # noqa: E402
from ai_assistant.service.vad import SileroVoiceDetector, UtteranceSegmenter  # noqa: E402

log = logging.getLogger("aia")


class SpeechServicer(speech_pb2_grpc.SpeechServicer):
    def __init__(self, segmenter_factory: Callable[[], object], engine, timeline_sink: List[dict]):
        self._segmenter_factory = segmenter_factory
        self._engine = engine
        self._timeline_sink = timeline_sink

    def Recognize(self, request_iterator, context):
        segmenter = self._segmenter_factory()
        session_id = ""

        for request in request_iterator:
            if request.session_id:
                session_id = request.session_id
            for event in segmenter.feed(request.audio_chunk):
                if event.kind == "silence":
                    yield speech_pb2.StreamResponse(
                        type=speech_pb2.StreamResponse.SILENCE,
                        silence_ms=event.silence_ms,
                    )
                    continue

                timeline = CallTimeline(session_id)
                timeline.mark(STAGE_SPEECH_END)
                try:
                    audio = prepare_audio(event.pcm, self._engine.target_sample_rate)
                    text = self._engine.transcribe(audio)
                except Exception:
                    # Один споткнувшийся движок не должен ронять весь поток:
                    # gRPC закрыл бы его целиком, и разговор оборвался бы до
                    # конца звонка вместо потери одной реплики (Important 3
                    # из ревью Task 9).
                    log.exception(
                        "Движок распознавания упал на реплике звонка [%s], реплика пропущена",
                        session_id,
                    )
                    continue
                timeline.mark(STAGE_STT_DONE)
                self._timeline_sink.append(timeline.as_dict())
                log.info("STT [%s]: %s | %s", session_id, text, timeline.durations())

                yield speech_pb2.StreamResponse(
                    type=speech_pb2.StreamResponse.FINAL, text=text
                )


def build_http_app(dialog_engine: DialogEngine, tts_cache, voice: str) -> FastAPI:
    app = FastAPI(title="AI Assistant speech service")

    @app.post("/dialog")
    def dialog(payload: dict):
        prms = prms_to_dict(payload.get("prms", []))
        return JSONResponse(dialog_engine.handle(prms))

    @app.get("/tts")
    def tts(text: str = Query(...), voice_name: str = Query(default="")):
        if not text.strip():
            raise HTTPException(status_code=400, detail="Пустой текст для синтеза")
        path = tts_cache.get(text, voice_name or voice)
        return FileResponse(path, media_type="audio/wav")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config()

    log.info("Загружаем эмбеддер %s", cfg.embedder_model)
    embedder = SentenceTransformerEmbedder(cfg.embedder_model)
    knowledge = load_knowledge_base(cfg.knowledge_path, embedder, cfg.similarity_threshold)

    log.info("Загружаем движок распознавания %s", cfg.stt_engine)
    engine = create_engine(
        cfg.stt_engine, model_path=os.environ.get("AIA_VOSK_MODEL_PATH", "")
    )

    log.info("Загружаем VAD и синтез")
    detector = SileroVoiceDetector()
    tts_cache = TtsCache(SileroSynthesizer(cfg.tts_model), cfg.tts_cache_dir)

    phrases = Phrases(
        greeting="Здравствуйте, чем могу помочь?",
        misrecognition="Попробуйте переформулировать свой вопрос, пожалуйста",
        transfer="Минуту, перевожу ваш звонок на специалиста",
        silence="Вы меня слышите?",
    )
    dialog_engine = DialogEngine(knowledge, phrases, support_exten="489", sales_exten="500")

    # deque(maxlen=...) сам вытесняет самые старые записи при переполнении —
    # без этого /metrics копил бы данные, пока не кончится память.
    timeline_sink: "deque[dict]" = deque(maxlen=MAX_TIMELINE_RECORDS)

    def segmenter_factory():
        # detector — общая на процесс "эталонная" модель, но она рекуррентная
        # и хранит внутреннее состояние между вызовами. При нескольких
        # одновременных звонках через один и тот же экземпляр кадры разных
        # абонентов перемешивались бы в одном состоянии, и сегментация речи
        # ломалась бы у всех сразу (Critical 1 из ревью Task 9). clone() даёт
        # каждому звонку независимую копию модели за ~7-12 мс вместо ~650-700 мс
        # на повторную загрузку через torch.hub — подробности и замеры в
        # SileroVoiceDetector.clone().
        return UtteranceSegmenter(
            detector.clone(),
            pause_ms=cfg.utterance_pause_ms,
            silence_timeout_ms=cfg.silence_timeout_ms,
        )

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=16))
    speech_pb2_grpc.add_SpeechServicer_to_server(
        SpeechServicer(segmenter_factory, engine, timeline_sink), server
    )
    server.add_insecure_port("0.0.0.0:{0}".format(cfg.grpc_port))
    server.start()
    log.info("gRPC слушает порт %s", cfg.grpc_port)

    app = build_http_app(dialog_engine, tts_cache, cfg.tts_voice)

    @app.get("/metrics")
    def metrics():
        return list(timeline_sink)

    @app.post("/knowledge/save")
    def save_knowledge():
        knowledge.save(cfg.knowledge_path)
        return {"records": len(knowledge.records)}

    import uvicorn

    threading.Thread(target=server.wait_for_termination, daemon=True).start()
    try:
        uvicorn.run(app, host="0.0.0.0", port=cfg.http_port, log_level="info")
    finally:
        # server.stop() нигде не вызывался — рабочие потоки пула не
        # демоны, и без явной остановки процесс при выходе ждал бы
        # завершения активных звонков неограниченно долго (Important 5 из
        # ревью Task 9). Даём разумный срок на завершение уже идущих
        # разговоров и останавливаемся принудительно после него.
        log.info(
            "Останавливаем gRPC-сервер (до %s с на завершение активных звонков)...",
            GRPC_SHUTDOWN_GRACE_SECONDS,
        )
        stopped = server.stop(GRPC_SHUTDOWN_GRACE_SECONDS)
        stopped.wait(GRPC_SHUTDOWN_GRACE_SECONDS + 1)
        log.info("gRPC-сервер остановлен")


if __name__ == "__main__":
    main()
