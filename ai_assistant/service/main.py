"""Сборка сервиса: gRPC-поток распознавания плюс HTTP-ручки диалога и синтеза."""
import logging
import os
import sys
import threading
import time
from collections import deque
from concurrent import futures
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

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
# Тот же класс проблемы, что и MAX_TIMELINE_RECORDS/DEFAULT_MAX_SESSIONS
# (dialog.py), но для реестра активных таймлайнов (Minor из повторного
# ревью): он наполняется в Recognize() и вычищается только при обращении к
# /dialog. Если звонок оборвался между этими моментами (сброс трубки,
# срабатывание общего таймаута звонка, падение AGI-скрипта на станции) —
# запись остаётся в реестре навсегда, а демон живёт постоянно. Предел ниже —
# подстраховка на этот случай: самая старая запись вытесняется, как и в
# dialog.py._session().
MAX_ACTIVE_TIMELINES = 1000

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
    KnowledgeBase,
    SentenceTransformerEmbedder,
    load_knowledge_base,
)
from ai_assistant.service.knowledge_feed import (  # noqa: E402
    FeedError,
    ParsedFeed,
    load_feed,
    parse_feed,
    save_feed,
)
from ai_assistant.service.metrics import (  # noqa: E402
    STAGE_DIALOG_DONE,
    STAGE_SPEECH_END,
    STAGE_STT_DONE,
    CallTimeline,
)
from ai_assistant.service.stt.base import create_engine, prepare_audio  # noqa: E402
from ai_assistant.service.tts import SileroSynthesizer, TtsCache  # noqa: E402
from ai_assistant.service.vad import SileroVoiceDetector, UtteranceSegmenter  # noqa: E402

log = logging.getLogger("aia")


class SpeechServicer(speech_pb2_grpc.SpeechServicer):
    def __init__(
        self,
        segmenter_factory: Callable[[], object],
        engine,
        timeline_sink: List[dict],
        active_timelines: Optional[Dict[str, Tuple[CallTimeline, dict]]] = None,
        timelines_lock: Optional[threading.Lock] = None,
        max_active_timelines: int = MAX_ACTIVE_TIMELINES,
    ):
        self._segmenter_factory = segmenter_factory
        self._engine = engine
        self._timeline_sink = timeline_sink
        # Последний таймлайн по каждому звонку (ключ — session_id, он же
        # linkedId AGI-скрипта): ручка /dialog (build_http_app) достаёт его
        # отсюда, чтобы пометить конец решения диалога на ТОМ ЖЕ таймлайне,
        # а не завести новый несвязанный замер. Опционально — старые вызовы
        # SpeechServicer(...) без этих двух параметров (тесты, прежний код)
        # продолжают работать как раньше, просто без сквозной разбивки.
        self._active_timelines = active_timelines
        self._timelines_lock = timelines_lock or threading.Lock()
        self._max_active_timelines = max_active_timelines

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
                if event.forced:
                    # Реплика выдана принудительно по потолку длины
                    # (MAX_UTTERANCE_SECONDS в vad.py) — паузы перед этим не
                    # было вообще, вычитать pause_seconds нельзя (Minor из
                    # повторного ревью): для монолога длиннее двадцати секунд
                    # замер оказался бы завышен на три несуществующие секунды.
                    timeline.mark(STAGE_SPEECH_END)
                else:
                    # Точка отсчёта — не "сейчас", а "сейчас минус
                    # длительность паузы из настроек" (Important из
                    # финального ревью): реплика рождается только после
                    # pause_seconds тишины, и метка "конец речи" честно
                    # показывала бы только работу движка, занижая реальное
                    # ожидание абонента на всю длительность паузы. getattr —
                    # на случай сегментатора-заглушки без атрибута (тесты
                    # подставляют собственные, не обязанные его иметь).
                    timeline.mark_with_offset(STAGE_SPEECH_END, getattr(segmenter, "pause_seconds", 0.0))
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
                snapshot = timeline.as_dict()
                self._timeline_sink.append(snapshot)
                if self._active_timelines is not None and session_id:
                    # Тот же объект timeline и тот же словарь snapshot кладём
                    # в общий реестр — /dialog найдёт их по session_id и
                    # мутирует snapshot на месте через .update(), поэтому
                    # обновление станет видно и в /metrics (там лежит именно
                    # этот объект, а не его копия).
                    with self._timelines_lock:
                        if (
                            session_id not in self._active_timelines
                            and len(self._active_timelines) >= self._max_active_timelines
                        ):
                            # Тот же приём, что в dialog.py._session(): словарь
                            # хранит порядок вставки, первый ключ — самая
                            # старая запись. Проверяем "not in" отдельно,
                            # чтобы повторная запись для ТОГО ЖЕ звонка
                            # (следующая реплика в разговоре) не считалась
                            # новой и не запускала вытеснение на ровном месте.
                            oldest_session_id = next(iter(self._active_timelines))
                            del self._active_timelines[oldest_session_id]
                        self._active_timelines[session_id] = (timeline, snapshot)
                log.info("STT [%s]: %s | %s", session_id, text, timeline.durations())

                yield speech_pb2.StreamResponse(
                    type=speech_pb2.StreamResponse.FINAL, text=text
                )


class KnowledgeState:
    """Текущая база знаний и сведения о посылке, из которой она собрана.

    Подмена — одной операцией в самом конце: пока новый индекс считается,
    звонки обслуживаются прежним. Кривая посылка не должна оставлять базу
    знаний наполовину обновлённой, потому что такое расхождение не видно.
    """

    def __init__(self, cache_path, embedder, threshold=0.64, dialog_factory=None):
        self._cache_path = cache_path
        self._embedder = embedder
        self._threshold = threshold
        self._dialog_factory = dialog_factory
        self._lock = threading.Lock()

        self.knowledge = None
        self.dialog_engine = None
        self.generated_at = None
        self.received_at = None
        self.record_count = 0
        self.phrase_count = 0

    def apply(self, feed: ParsedFeed) -> None:
        knowledge = KnowledgeBase(feed.records, self._embedder, self._threshold)
        phrase_count = sum(1 + len(r.question_variants) for r in feed.records)
        engine = self._dialog_factory(knowledge, feed) if self._dialog_factory else None

        with self._lock:
            self.knowledge = knowledge
            self.dialog_engine = engine
            self.generated_at = feed.generated_at
            self.received_at = datetime.now().isoformat(timespec="seconds")
            self.record_count = len(feed.records)
            self.phrase_count = phrase_count

    def accept(self, payload) -> ParsedFeed:
        # Порядок важен: сначала разбор и применение, и только потом запись на
        # диск. Иначе на диск попадёт посылка, которую сервис не смог применить,
        # и после перезапуска он поднимется именно на ней.
        feed = parse_feed(payload)
        self.apply(feed)
        save_feed(payload, self._cache_path)
        return feed

    def restore_from_disk(self) -> bool:
        payload = load_feed(self._cache_path)
        if payload is None:
            return False
        try:
            self.apply(parse_feed(payload))
            return True
        except FeedError:
            log.exception("Копия посылки не разбирается, стартуем без неё")
            return False


def collect_speakable_phrases(phrases: Phrases, knowledge) -> List[str]:
    """Всё, что бот вообще способен произнести.

    Служебные фразы плюс уточняющие вопросы и ответы при согласии из базы
    знаний. Записи без уточняющего вопроса — это ещё не размеченные
    неопознанные реплики, бот их не произносит и синтезировать их незачем.
    """
    texts = [phrases.greeting, phrases.misrecognition, phrases.transfer, phrases.silence]
    for record in knowledge.records:
        if not record.clarifying_question:
            continue
        texts.append(record.clarifying_question)
        if record.positive_reply:
            texts.append(record.positive_reply)

    unique: List[str] = []
    seen = set()
    for text in texts:
        text = (text or "").strip()
        if text and text not in seen:
            seen.add(text)
            unique.append(text)
    return unique


def prewarm_tts_cache(tts_cache, voice: str, texts: List[str]) -> Tuple[int, float]:
    """Синтезировать фразы заранее, чтобы звонок не ждал холодного синтеза.

    Холодный синтез стоит до двух секунд, и клиент слышит их как тишину.
    Отказ синтеза здесь не должен ронять запуск сервиса: фраза просто
    синтезируется позже, по ходу звонка, как было раньше.
    """
    started = time.perf_counter()
    done = 0
    for text in texts:
        try:
            tts_cache.get(text, voice)
            done += 1
        except Exception:
            log.exception("Не удалось заранее синтезировать фразу: %r", text[:60])
    return done, time.perf_counter() - started


def build_http_app(
    dialog_engine: DialogEngine,
    tts_cache,
    voice: str,
    active_timelines: Optional[Dict[str, Tuple[CallTimeline, dict]]] = None,
    timelines_lock: Optional[threading.Lock] = None,
    state: Optional["KnowledgeState"] = None,
) -> FastAPI:
    app = FastAPI(title="AI Assistant speech service")
    lock = timelines_lock or threading.Lock()

    @app.post("/dialog")
    def dialog(payload: dict):
        prms = prms_to_dict(payload.get("prms", []))
        result = dialog_engine.handle(prms)

        # Сквозная разбивка задержки (Important из финального ревью): у
        # звонка тот же linkedId, что и session_id в gRPC-потоке — находим
        # по нему таймлайн, оставленный Recognize() после STT, и помечаем
        # завершение решения диалога на нём же, а не заводим отдельный
        # замер. Формат ответа /dialog (список пар Key/Value) не меняется —
        # это чисто внутренняя бухгалтерия сервиса.
        linked_id = prms.get("linkedId", "")
        if active_timelines is not None and linked_id:
            with lock:
                entry = active_timelines.pop(linked_id, None)
            if entry is not None:
                timeline, snapshot = entry
                timeline.mark(STAGE_DIALOG_DONE)
                snapshot.update(timeline.as_dict())
                log.info("DIALOG [%s]: %s", linked_id, timeline.durations())

        return JSONResponse(result)

    @app.get("/tts")
    def tts(text: str = Query(...), voice_name: str = Query(default="")):
        if not text.strip():
            raise HTTPException(status_code=400, detail="Пустой текст для синтеза")
        # /tts не получает linkedId (контракт с AGI-скриптом не меняем —
        # см. фразу задачи "не меняй формат обмена и сигнатуры"), поэтому
        # длительность синтеза не с чем сопоставить на конкретный звонок в
        # /metrics. Логируем её отдельно — соединить с конкретным звонком
        # человек сможет по временным меткам скачивания в логе станции
        # (ai_assistant/agi/ai_assistant.py, TIMING download_*).
        start = time.perf_counter()
        path = tts_cache.get(text, voice_name or voice)
        duration_ms = (time.perf_counter() - start) * 1000.0
        log.info("TTS %.1f ms | voice=%s | text=%.80r", duration_ms, voice_name or voice, text)
        return FileResponse(path, media_type="audio/wav")

    @app.post("/knowledge")
    def knowledge_feed(payload: dict):
        if state is None:
            raise HTTPException(status_code=503, detail="Приём справочников не настроен")
        try:
            feed = state.accept(payload)
        except FeedError as error:
            log.warning("Посылка отвергнута: %s", error)
            raise HTTPException(status_code=400, detail=str(error))
        log.info(
            "Принята база знаний: %s записей, %s формулировок, собрана %s",
            state.record_count, state.phrase_count, feed.generated_at,
        )
        return {"records": state.record_count, "phrases": state.phrase_count}

    @app.get("/health")
    def health():
        # Возраст данных — единственный способ заметить, что робот перестал
        # приносить справочники: сервис при этом жив и отвечает на звонки
        # прежней базой знаний, и по одному "ok" поломки не видно.
        knowledge_info = {"records": 0, "phrases": 0, "generated_at": None, "received_at": None}
        if state is not None:
            knowledge_info = {
                "records": state.record_count,
                "phrases": state.phrase_count,
                "generated_at": state.generated_at,
                "received_at": state.received_at,
            }
        return {"status": "ok", "knowledge": knowledge_info}

    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config()

    log.info("Загружаем эмбеддер %s", cfg.embedder_model)
    embedder = SentenceTransformerEmbedder(cfg.embedder_model)
    knowledge = load_knowledge_base(cfg.knowledge_path, embedder, cfg.similarity_threshold)

    log.info("Загружаем движок распознавания %s", cfg.stt_engine)
    engine = create_engine(
        cfg.stt_engine,
        model_path=os.environ.get("AIA_VOSK_MODEL_PATH", ""),
        model_name=cfg.gigaam_model,
    )

    log.info("Загружаем VAD и синтез")
    detector = SileroVoiceDetector()
    tts_cache = TtsCache(SileroSynthesizer(cfg.tts_model), cfg.tts_cache_dir)

    phrases = Phrases(
        greeting="Здравствуйте, чем могу помочь?",
        misrecognition="Попробуйте переформулировать свой вопрос, пожалуйста",
        transfer="Минуту, перевожу ваш звонок на специалиста",
        silence="Вы меня слышите?",
        wrong_guess="Тогда подскажите, пожалуйста, что вас интересует?",
    )
    dialog_engine = DialogEngine(
        knowledge,
        phrases,
        support_exten="489",
        sales_exten="500",
        audio_signature="{0}|{1}".format(cfg.tts_model, cfg.tts_voice),
    )

    if cfg.prewarm_tts:
        speakable = collect_speakable_phrases(phrases, knowledge)
        log.info("Прогреваем синтез: %s фраз", len(speakable))
        done, elapsed = prewarm_tts_cache(tts_cache, cfg.tts_voice, speakable)
        log.info("Синтез прогрет: %s из %s фраз за %.1f с", done, len(speakable), elapsed)

    # deque(maxlen=...) сам вытесняет самые старые записи при переполнении —
    # без этого /metrics копил бы данные, пока не кончится память.
    timeline_sink: "deque[dict]" = deque(maxlen=MAX_TIMELINE_RECORDS)
    # Последний таймлайн по каждому звонку (см. SpeechServicer и
    # build_http_app выше) — общий между gRPC-обработчиком и HTTP-ручкой
    # /dialog, оба выполняются каждый в своём потоке.
    active_timelines: Dict[str, Tuple[CallTimeline, dict]] = {}
    timelines_lock = threading.Lock()

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
        SpeechServicer(segmenter_factory, engine, timeline_sink, active_timelines, timelines_lock),
        server,
    )
    server.add_insecure_port("0.0.0.0:{0}".format(cfg.grpc_port))
    server.start()
    log.info("gRPC слушает порт %s", cfg.grpc_port)

    # Приёмник справочников из ERP. Живой разговор он пока не трогает: диалог
    # обслуживает база знаний из файла, как и раньше. Здесь только приём,
    # копия на диске и возраст данных в /health — подмена базы под звонками
    # будет отдельным шагом, чтобы её можно было включить осознанно.
    knowledge_state = KnowledgeState(
        cache_path=cfg.feed_cache_path,
        embedder=embedder,
        threshold=cfg.similarity_threshold,
    )
    if knowledge_state.restore_from_disk():
        log.info(
            "Поднята копия последней посылки: %s записей, собрана %s",
            knowledge_state.record_count, knowledge_state.generated_at,
        )

    app = build_http_app(
        dialog_engine,
        tts_cache,
        cfg.tts_voice,
        active_timelines,
        timelines_lock,
        state=knowledge_state,
    )

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
