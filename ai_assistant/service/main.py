"""Сборка сервиса: gRPC-поток распознавания плюс HTTP-ручки диалога и синтеза."""
import logging
import os
import re
import sys
import threading
import time
import wave
from collections import OrderedDict, deque
from concurrent import futures
from dataclasses import replace
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

# Куда уезжают записи без своего телефонного направления и звонки, в которых
# бот не понял клиента.
#
# Боевое значение приезжает из ERP полем `support_exten` — это номер ТН 17
# «Сопровождение», как требует ТЗ UL-18819. Здесь оно продублировано на случай
# работы без ERP (отладка, тесты, пустое поле у ТН 17). Раньше тут стояло 489
# из спека первого этапа: номер жил своей жизнью, к справочнику отношения не
# имел, и все переводы «не понял» шли мимо сопровождения.
SUPPORT_EXTEN = "7082"
SALES_EXTEN = "500"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "proto"))
import speech_pb2  # noqa: E402
import speech_pb2_grpc  # noqa: E402

from ai_assistant.service.config import load_config  # noqa: E402
from ai_assistant.service import dialog as dialog_module  # noqa: E402
from ai_assistant.service import knowledge as knowledge_module  # noqa: E402
from ai_assistant.service.dialog import (  # noqa: E402
    PHRASE_SLOTS,
    DialogEngine,
    LineProfile,
    Phrases,
    prms_to_dict,
)
from ai_assistant.service.corpus_knn import CorpusIndex  # noqa: E402
from ai_assistant.service.knowledge import (  # noqa: E402
    brand_gate,
    KnowledgeBase,
    SentenceTransformerEmbedder,
    load_knowledge_base,
)
from ai_assistant.service.intent import load_intent_model  # noqa: E402
from ai_assistant.service.knowledge_feed import (  # noqa: E402
    FeedError,
    ParsedFeed,
    archive_feed,
    check_feed,
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
from ai_assistant.service.stt.base import (  # noqa: E402
    create_engine,
    pad_short_utterance,
    prepare_audio,
)
from ai_assistant.service.tts import (  # noqa: E402
    AUDIO_PIPELINE_VERSION,
    RecordedSynthesizer,
    TtsCache,
    VoiceLibrary,
    VoskSynthesizer,
    create_synthesizer,
    engine_default_voice,
)
from ai_assistant.service.vad import SileroVoiceDetector, UtteranceSegmenter  # noqa: E402

log = logging.getLogger("aia")


def log_build_fingerprint(cfg) -> None:
    """Отпечаток версии сервиса и его настроек одной строкой при старте.

    Нужен, чтобы волну разбора можно было привязать к КОДУ, а не к дате.
    Версию кода волн 8-10 восстановить уже нельзя: в логе нет ни коммита, ни
    настроек, а пороги с тех пор менялись семь раз. Эта строка закрывает дыру:
    по ней видно, какой код и с какими порогами отвечал на звонки.
    """
    import hashlib
    import subprocess

    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    commit = ""
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_root, stderr=subprocess.DEVNULL, timeout=5,
        ).decode("ascii", "replace").strip()
    except Exception:
        commit = "неизвестен"
    # Коммита мало: сервис почти всегда запускается с незакоммиченными правками,
    # и тогда номер коммита описывает НЕ тот код, который отвечает на звонки.
    # Пометка «+правки» говорит разборщику волны, что по коммиту версию не
    # восстановить и надо смотреть хэши модулей ниже.
    try:
        dirty = subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=repo_root, stderr=subprocess.DEVNULL, timeout=5,
        ).decode("utf-8", "replace").strip()
        if dirty:
            commit += "+правки(%d файлов)" % len(dirty.splitlines())
    except Exception:
        commit += "+правки(неизвестно)"
    modules = []
    # intent.py добавлен 09.11.2026: ярус намерения решает 1595 реплик из 4000,
    # а его версия в отпечаток не входила вовсе.
    for name in ("dialog.py", "knowledge.py", "main.py", "vad.py", "tts.py", "intent.py"):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
        try:
            with open(path, "rb") as handle:
                modules.append(hashlib.sha1(handle.read()).hexdigest()[:8])
        except OSError:
            modules.append("нет")
    log.info(
        "СБОРКА коммит=%s модули=%s | распознавание=%s второе_мнение=%s порог_детектора=%.2f "
        "| пороги: формулировки=%.2f корпус=%.2f оператор=%.2f перевод=%.2f "
        "серая_зона=%s переспросов_в_серой=%s | ярус=%s порог_повторного=%.2f "
        "| предел_фраз=%s второй_круг=%s | голос=%s корпус_индекс=%s",
        commit, "/".join(modules),
        # Основная модель распознавания не писалась в лог НИГДЕ, хотя вторая
        # писалась: по логу волны нельзя было сказать, чем распознавали речь.
        cfg.gigaam_model or cfg.stt_engine,
        cfg.stt_fallback_model or "выкл", cfg.vad_threshold,
        cfg.similarity_threshold, cfg.corpus_threshold, cfg.corpus_operator_threshold,
        dialog_module.DIRECT_TRANSFER_MIN_SIMILARITY,
        # Серая зона это главная правка волны 13: ниже этого порога бот тему не
        # называет, а просит повторить. Без неё в отпечатке разбор волны не мог
        # бы сказать, действовало ли правило вообще.
        ("%.2f" % knowledge_module.CORPUS_GREY_ZONE) if knowledge_module.CORPUS_GREY_ZONE else "выкл",
        dialog_module.QUESTION_REASK_ATTEMPTS,
        "вкл" if cfg.tiers_enabled else "выкл", cfg.intent_repeat_threshold,
        dialog_module.MAX_BOT_PHRASES or "нет",
        "нет" if dialog_module.NO_SECOND_ROUND_AFTER_NO else "есть",
        # Эти две настройки можно выключить словом из bat, и отпечаток должен
        # показывать, что откат сработал.
        os.path.basename(cfg.voice_library_dir.rstrip("/\\")) if cfg.voice_library_dir else "выкл",
        os.path.basename(cfg.corpus_index_path) if cfg.corpus_index_path else "выкл",
    )


def load_corpus_index(cfg):
    """Индекс корпуса живых реплик; None — бот решает только по формулировкам.

    Отсутствие файла — не ошибка, а обычное состояние новой установки: индекс
    собирается отдельно из записей звонков (tools/build_corpus_index.py) и
    кладётся рядом с сервисом руками.
    """
    path = cfg.corpus_index_path
    if not path:
        # Выключен словом в bat (AIA_CORPUS_INDEX_PATH=нет). Прежде это было
        # невыразимо: пустое значение cmd удаляет, и откат не срабатывал.
        log.info("Корпус реплик выключен настройкой — решают только формулировки")
        return None
    if not os.path.exists(path):
        log.info("Корпус реплик не подключён (файла %s нет) — решают только формулировки", path)
        return None
    corpus = CorpusIndex.load(path, k=cfg.corpus_k, threshold=cfg.corpus_threshold,
                              operator_threshold=cfg.corpus_operator_threshold,
                              min_words=cfg.corpus_min_words)
    log.info("Корпус реплик: %d реплик, %d соседей, порог уверенности %.2f, оператор от %.2f, "
             "содержательных слов от %d (%s)", len(corpus), corpus.k, corpus.threshold,
             corpus.operator_threshold, corpus.min_words, path)
    return corpus


def prewarm_recognition(engine, knowledge, fallback_engine=None) -> float:
    """Прогреть распознавание и поиск по смыслу до первого живого звонка.

    Обе модели грузятся лениво, на первом обращении, и платит за это первый
    позвонивший после каждого перезапуска — тишиной в трубку. Замеры на живых
    звонках: 20.08.2026 в 15:17 распознавание 5.7 с плюс эмбеддер 3.4 с — девять
    секунд, клиент не дождался и положил трубку; 21.08.2026 в 13:32 — 5.8 плюс
    1.5. Следующие реплики в тех же звонках укладывались в 1.5-2.5 с.

    Прогрев не гасится настройкой PREWARM_TTS: та про синтез сотен фраз и
    вправду бывает лишней, а здесь одна короткая прогонка на старте.
    Оба отказа проглатываются — на приём звонков прогрев не влияет.
    """
    started = time.time()
    try:
        # Секунда тишины: распознаётся в пустую строку, но модель поднимает
        # ровно так же, как настоящая речь.
        silence = b"\x00\x00" * int(engine.target_sample_rate)
        engine.transcribe(silence)
    except Exception:
        log.exception("Прогрев распознавания не удался, первый звонок будет медленным")
    if fallback_engine is not None:
        # Вторую модель греем так же: 15.10.2026 12:18 (270036506) первый
        # промах после ночи поднимал её с диска 10 секунд, клиент не дождался.
        try:
            fallback_engine.transcribe(b"\x00\x00" * int(fallback_engine.target_sample_rate))
        except Exception:
            log.exception("Прогрев второй модели распознавания не удался")
    try:
        # База знаний закодирована при загрузке, но кодирование ЗАПРОСА идёт
        # своим путём (другой префикс, батч из одной строки) и на первом вызове
        # тоже стоит секунды.
        knowledge.best_match("прогрев")
    except Exception:
        log.exception("Прогрев поиска по смыслу не удался")
    return time.time() - started


def start_keepwarm(engine, knowledge, seconds: int, stop_event=None, fallback_engine=None):
    """Держать модели горячими, пока никто не звонит.

    Прогрева на старте мало. Замер на живых звонках: сервис работал сутки,
    вчера через него прошло несколько разговоров, а первая реплика следующего
    утра (21.08.2026, 13:32) снова считалась 5.8 с вместо обычных 1.5-2.5.
    Модели давно загружены — но у процесса, который сутки ничего не делал,
    Windows урезает рабочий набор и выгружает страницы с весами на диск;
    первое обращение поднимает их обратно, и платит за это позвонивший.

    Лечится тем же, чем и прогрев на старте, только повторяемым: короткая
    прогонка раз в несколько минут держит страницы в памяти. Стоит она
    десятки миллисекунд, поэтому на живые звонки не влияет даже если совпадёт
    с разговором.

    Возвращает поток (или None, если подогрев выключен нулём).
    """
    if seconds <= 0:
        log.info("Периодический подогрев моделей выключен")
        return None

    stop = stop_event or threading.Event()

    def loop() -> None:
        # wait() вместо sleep(): выключение сервиса не должно ждать целый цикл.
        while not stop.wait(seconds):
            log.debug("Подогрев моделей: %.0f мс", prewarm_recognition(engine, knowledge, fallback_engine) * 1000)

    thread = threading.Thread(target=loop, name="keepwarm", daemon=True)
    thread.start()
    log.info("Подогрев моделей каждые %s с", seconds)
    return thread


def dump_utterance(directory: str, session_id: str, text: str, pcm: bytes, sample_rate: int) -> str:
    """Сохранить реплику, как её услышал движок, рядом с тем, что он услышал.

    Нужно для разбора жалоб вида «я сказал нет, а распозналось да»: без записи
    спорить не с чем — лог показывает только результат, а был ли в этом отрезке
    голос клиента, голос бота (эхо собственной фразы) или обрывок, по логу не
    видно. 20.08.2026 такой разбор пришлось вести по длительностям файлов
    синтеза и арифметике, и он всё равно остался догадкой.

    Пишется только когда задан AIA_DEBUG_AUDIO_DIR: постоянно складывать
    записи разговоров на диск нельзя.
    """
    if not directory:
        return ""
    try:
        os.makedirs(directory, exist_ok=True)
        # Распознанное — в имя файла: слушать записи проще, когда рядом видно,
        # что движок из них сделал. Пусто — значит движок не услышал ничего.
        label = re.sub(r"[^\w\-]+", "_", text.strip(), flags=re.UNICODE)[:60] or "ПУСТО"
        name = "{0}_{1}_{2}.wav".format(
            time.strftime("%H%M%S"), re.sub(r"[^\w.\-]+", "_", session_id) or "нет-звонка", label,
        )
        path = os.path.join(directory, name)
        with wave.open(path, "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(sample_rate)
            writer.writeframes(pcm)
        return path
    except Exception:
        # Отладочная запись не имеет права уронить распознавание живого звонка.
        log.exception("Не удалось сохранить реплику звонка [%s] в %s", session_id, directory)
        return ""


class SpeechServicer(speech_pb2_grpc.SpeechServicer):
    def __init__(
        self,
        segmenter_factory: Callable[[], object],
        engine,
        timeline_sink: List[dict],
        active_timelines: Optional[Dict[str, Tuple[CallTimeline, dict]]] = None,
        timelines_lock: Optional[threading.Lock] = None,
        max_active_timelines: int = MAX_ACTIVE_TIMELINES,
        debug_audio_dir: str = "",
        fallback_engine=None,
        knowledge_lookup: Optional[Callable[[], object]] = None,
    ):
        self._segmenter_factory = segmenter_factory
        self._engine = engine
        # Второе мнение распознавания: если по тексту первой модели тема в базе
        # не находится, реплика распознаётся ещё раз второй моделью, и берётся
        # тот текст, по которому тема нашлась. На линии заказчика v3_rnnt писал
        # «перфер», «кркер», «верхер», «апл» — v2_rnnt на тех же записях
        # слышал «керхер» и «эпл» (13–14.10.2026). Цена — одно лишнее
        # распознавание только на промахах.
        self._fallback_engine = fallback_engine
        self._knowledge_lookup = knowledge_lookup
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
        self._debug_audio_dir = debug_audio_dir

    def _topic_found(self, text: str, strict: bool = False) -> bool:
        """Нашлась ли по тексту тема в текущей базе знаний (для второго мнения распознавания).

        strict — для текста ВТОРОЙ модели: тема засчитывается только по дословному
        совпадению, слову-ключу или названному бренду. Близости формулировок мало:
        v2 слышала «мне нужен сайт» вместо «мне нужен», по близости 0.75 нашлась
        тема интернета, и бот спросил про интернет (9-я волна, 270057961).
        """
        if not text.strip() or self._knowledge_lookup is None:
            return True  # сравнивать не с чем — первое мнение не оспариваем
        if DialogEngine._is_generic_only(text):
            # «Не включается» без техники: бренд мог потеряться в распознавании
            # («керхер не включается» → «не включается», 14.10.2026) — пусть
            # вторая модель попробует его расслышать.
            return False
        try:
            knowledge = self._knowledge_lookup()
            if knowledge is None:
                return True
            resolution = knowledge.resolve(text)
        except Exception:
            log.exception("Проверка темы для второго мнения упала, оставляем первое распознавание")
            return True
        found = bool(resolution is not None and resolution.trusted and resolution.record is not None)
        if not found or not strict:
            return found
        if getattr(resolution, "source", "") in ("exact", "keyword"):
            return True
        return brand_gate(resolution.record) is not None  # запись-бренд: бренд в тексте есть, иначе её бы не взяли

    def _second_opinion(self, session_id: str, text: str, audio) -> str:
        """Перераспознать второй моделью, если по первому тексту тема не нашлась."""
        if self._fallback_engine is None or not text.strip():
            return text
        words = text.split()
        if len(words) == 1 and len(words[0]) <= 4:
            # «Да», «нет», «ок», «угу»: тема по ним не ищется, а вторая модель
            # стоила по 0,3 с на каждом подтверждении (14.10.2026).
            return text
        if self._topic_found(text):
            return text
        try:
            alternative = self._fallback_engine.transcribe(audio).strip()
        except Exception:
            log.exception("Вторая модель распознавания упала на реплике звонка [%s]", session_id)
            return text
        if alternative and alternative != text and self._topic_found(alternative, strict=True):
            log.info("STT второе мнение [%s]: %r → %r (тема нашлась)", session_id, text, alternative)
            return alternative
        return text

    def Recognize(self, request_iterator, context):
        segmenter = self._segmenter_factory()
        session_id = ""
        # Весь поток звонка как пришёл, без нарезки — только при AIA_DEBUG_AUDIO_DIR.
        # Реплики (dump_utterance) показывают, что детектор отдал распознаванию;
        # «да», которого детектор не заметил, в них не попадает (13.10.2026,
        # 1791892399: два «да» из трёх есть в записи станции и нет в репликах).
        stream = None
        last_chunk_at = None

        try:
          for request in request_iterator:
            if request.session_id:
                session_id = request.session_id
            if request.audio_chunk:
                # Разрыв потока — фраза бота: на это время Asterisk звук в AGI
                # не пишет, куски не приходят. Память детектора речи после
                # разрыва глушит короткое слово сразу за ним (см.
                # UtteranceSegmenter.reset_detector) — сбрасываем её по факту.
                now = time.monotonic()
                if last_chunk_at is not None and now - last_chunk_at >= STREAM_GAP_RESET_S:
                    segmenter.reset_detector()
                    log.info("Разрыв потока [%s] %.1f с — память детектора сброшена", session_id, now - last_chunk_at)
                last_chunk_at = now
            if self._debug_audio_dir and request.audio_chunk:
                if stream is None:
                    stream = open_stream_dump(self._debug_audio_dir, session_id)
                if stream is not None:
                    try:
                        stream.writeframes(request.audio_chunk)
                    except Exception:
                        stream = None
            for event in segmenter.feed(request.audio_chunk):
                if event.kind == "silence":
                    yield speech_pb2.StreamResponse(
                        type=speech_pb2.StreamResponse.SILENCE,
                        silence_ms=event.silence_ms,
                    )
                    continue

                timeline = CallTimeline(session_id)
                remember_forced(session_id, bool(event.forced))
                # Громкость реплики нужна диалогу: по ней он отличает речь,
                # которую движок не разобрал, от шума в линии.
                remember_peak(session_id, float(event.peak_dbfs))
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
                    # Тишина подмешивается до ресемплинга и до выбора движка:
                    # короткие ответы вроде «да»/«нет» без контекста по краям
                    # распознаются заметно хуже (замер — см. pad_short_utterance).
                    padded = pad_short_utterance(event.pcm)
                    audio = prepare_audio(padded, self._engine.target_sample_rate)
                    text = self._engine.transcribe(audio)
                    # Второе мнение внутри замера: клиент ждёт и его тоже.
                    text = self._second_opinion(session_id, text, audio)
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
                # Длина реплики и признак принудительного среза — без них по
                # логу не отличить «клиент сказал два слова» от «детектор
                # держал реплику 13 секунд» (269469843, 06.10.2026).
                log.info("STT [%s]: %s | %.1f с%s | %s", session_id, text,
                         len(event.pcm) / 2 / 8000.0, " ПРИНУДИТЕЛЬНО" if event.forced else "",
                         timeline.durations())
                dumped = dump_utterance(
                    self._debug_audio_dir, session_id, text, audio, self._engine.target_sample_rate
                )
                if dumped:
                    log.info("Реплика сохранена: %s", dumped)

                yield speech_pb2.StreamResponse(
                    type=speech_pb2.StreamResponse.FINAL, text=text
                )
            # Метка ставится после обработки куска, а не при его приходе: пока
            # идёт распознавание (1–3 с), куски копятся в gRPC и приходят
            # пачкой сразу после — это не разрыв потока (14.10.2026, звонок
            # 1791966066: «разрывы» 2.6 и 1.3 с ровно на время распознавания).
            last_chunk_at = time.monotonic()
        finally:
            if stream is not None:
                try:
                    stream.close()
                    log.info("Поток звонка [%s] сохранён целиком", session_id)
                except Exception:
                    pass


#: Пауза между кусками звука одного звонка, с которой разрыв считается фразой
#: бота (куски идут каждые 0,5 с; сетевой джиттер — десятки миллисекунд).
STREAM_GAP_RESET_S = 1.0

#: Звонок → была ли его последняя реплика отдана распознаванию по потолку длины
#: (клиент ещё говорил). Пишет поток звука (Recognize), читает диалог через
#: forced_lookup: AGI присылает в /dialog только текст, а решение «это хвост
#: монолога, а не ответ» нужно именно диалогу. Записи вытесняются вместе с
#: сессиями диалога — ключ тот же linkedId.
#: Признак «последняя реплика звонка срезана по потолку длины»: диалог по нему
#: понимает, что клиент ещё говорил, когда бот заговорил сам.
#:
#: Хранится не словарём с полной очисткой, а упорядоченным словарём с
#: вытеснением самого старого (как MAX_ACTIVE_TIMELINES и сессии диалога).
#: Прежний `clear()` при переполнении стирал флаги ВСЕХ звонков, включая те,
#: что идут прямо сейчас: на две тысячи первом звонке живой разговор терял
#: признак срезанной реплики и получал повтор вопроса вместо продолжения
#: (находка B1-08 ультракода).
FORCED_FINALS: "OrderedDict[str, bool]" = OrderedDict()
FORCED_FINALS_MAX = 2000


def remember_forced(session_id: str, forced: bool) -> None:
    FORCED_FINALS[session_id] = forced
    FORCED_FINALS.move_to_end(session_id)
    while len(FORCED_FINALS) > FORCED_FINALS_MAX:
        # Вытесняем самый старый звонок, а не все разом.
        FORCED_FINALS.popitem(last=False)


def was_forced(session_id: str) -> bool:
    return FORCED_FINALS.get(session_id, False)


#: Громкость последней реплики каждого звонка в dBFS. Нужна диалогу: пустое
#: распознавание бывает двух сортов, и вести себя с ними надо по-разному. Щелчок
#: в линии или шорох это тишина, на такое бот молчит и слушает дальше. А реплика
#: нормальной громкости, из которой движок не достал ни слова, значит, что
#: человек говорил и ждёт ответа: молчать в ответ он читает как поломку.
#: На записях 07.11.2026 примерно половина пустых распознаваний громче минус 25
#: dBFS, то есть это живая речь, а не шум.
LAST_PEAKS: "OrderedDict[str, float]" = OrderedDict()


def remember_peak(session_id: str, peak: float) -> None:
    LAST_PEAKS[session_id] = peak
    LAST_PEAKS.move_to_end(session_id)
    while len(LAST_PEAKS) > FORCED_FINALS_MAX:
        LAST_PEAKS.popitem(last=False)


def last_peak(session_id: str) -> float:
    return LAST_PEAKS.get(session_id, -99.0)


#: Как часто чистить папку отладочных записей. Чаще смысла нет: в худшем
#: случае между чистками набегает несколько минут записей.
PRUNE_DEBUG_AUDIO_EVERY_S = 300


def prune_old_files(directory: str, max_mb: int, keep_days: int, now: Optional[float] = None,
                    what: str = "Отладочные записи") -> int:
    """Убрать из папки то, что старше срока и лишнее по объёму.

    Служит двум папкам: записям разговоров и кэшу синтеза. Имена в кэше это
    хэши от модели, голоса и текста, поэтому «устаревший» файл по имени не
    отличить, и чистить его можно только по возрасту и объёму. Копился он без
    предела: 2287 файлов и 177 МБ при 58 живых фразах, потому что в ключ входит
    отпечаток библиотеки, и каждая её правка переименовывает весь кэш, а старые
    имена остаются на диске навсегда (A6, п. 6-8).

    Записи разговоров клиентов нельзя копить без предела. Боевой bat держал
    запись включённой постоянно (а комментарий в нём обещает «только на время
    разбора споров»), и за 25 дней на одной группе линий набежало 1608 файлов
    на 181 МБ при 0,3 МБ на звонок. На всех линиях это кратно больше, а диск C
    на 07.11.2026 занят на 94 % (свободно 7,7 ГБ). Полный диск немеет бота
    целиком: синтез не может создать временный файл, ручка /tts отдаёт 500, и
    станция уводит каждый звонок на аварийный перевод.

    Сначала удаляется то, что старше keep_days, затем, если папка всё ещё
    больше max_mb, самые старые файлы до нужного объёма. Возвращает число
    удалённых файлов. Ноль в max_mb или keep_days отключает соответствующее
    правило.
    """
    if not directory:
        return 0
    stamp = time.time() if now is None else now
    removed = 0
    try:
        entries = []
        # scandir, а не listdir плюс stat плюс isfile: тип и размер приходят
        # вместе с именем, то есть один системный вызов на файл вместо трёх.
        # На папке из 1608 файлов это 0,09 с против 0,26 с.
        with os.scandir(directory) as scan:
            for entry in scan:
                try:
                    if not entry.is_file():
                        continue
                    stat = entry.stat()
                except OSError:
                    continue
                entries.append((stat.st_mtime, stat.st_size, entry.path))
        entries.sort()
        if keep_days > 0:
            deadline = stamp - keep_days * 86400
            for mtime, _size, path in list(entries):
                if mtime >= deadline:
                    break
                try:
                    os.remove(path)
                except OSError:
                    continue
                entries.remove((mtime, _size, path))
                removed += 1
        if max_mb > 0:
            limit = max_mb * 1024 * 1024
            total = sum(size for _mtime, size, _path in entries)
            for mtime, size, path in list(entries):
                if total <= limit:
                    break
                try:
                    os.remove(path)
                except OSError:
                    continue
                total -= size
                removed += 1
        if removed:
            log.info("%s: удалено %s файлов (срок %s дн., предел %s МБ)",
                     what, removed, keep_days, max_mb)
    except Exception:
        # Чистка не имеет права уронить живой звонок.
        log.exception("Не удалось почистить папку %s (%s)", directory, what)
    return removed


def start_debug_audio_cleaner(directory: str, max_mb: int, keep_days: int, stop_event=None):
    """Чистить папку отладочных записей в отдельном потоке, а не в звонке.

    Первая версия звала чистку прямо из обработчика потока на первом куске
    звука. Это ровно та авария, от которой избавлялись пределом одновременных
    вызовов: пока идёт обход каталога, обработчик не читает поток и не отдаёт
    ни распознанную реплику, ни событие тишины, то есть клиент слушает тишину.
    Замер на этой машине: папка из 1608 файлов обходится 0,26 с, удаление 1,36
    мс на файл, а первая чистка после рестарта удалила бы 1105 файлов, то есть
    около 1,8 с тишины в начале звонка. При пределе 1024 МБ каталог дорастает
    до девяти тысяч файлов, и полуторасекундная пауза попадала бы в каждый
    звонок после пятиминутного простоя.

    Возвращает поток (или None, если оба правила выключены нулём).
    """
    if not directory or (max_mb <= 0 and keep_days <= 0):
        log.info("Чистка папки отладочных записей выключена")
        return None

    stop = stop_event or threading.Event()

    def loop() -> None:
        # Первый проход сразу: после рестарта в папке обычно и лежит всё лишнее.
        while True:
            prune_old_files(directory, max_mb, keep_days)
            if stop.wait(PRUNE_DEBUG_AUDIO_EVERY_S):
                return

    thread = threading.Thread(target=loop, name="debug-audio-cleaner", daemon=True)
    thread.start()
    log.info("Чистка папки отладочных записей: каждые %d с, предел %d МБ, срок %d дн.",
             PRUNE_DEBUG_AUDIO_EVERY_S, max_mb, keep_days)
    return thread


def open_stream_dump(directory: str, session_id: str):
    """WAV на весь поток звонка (8 кГц, моно) в папке отладочных записей; None — не вышло."""
    try:
        os.makedirs(directory, exist_ok=True)
        name = "{0}_{1}_ПОТОК.wav".format(
            time.strftime("%H%M%S"), re.sub(r"[^\w.\-]+", "_", session_id) or "нет-звонка")
        handle = wave.open(os.path.join(directory, name), "wb")
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        return handle
    except Exception as error:
        log.warning("Поток звонка не сохраняется: %s", error)
        return None


def resolve_voice(feed_voice: Optional[str], default_voice: str) -> str:
    """Каким голосом бот говорит на самом деле.

    Заполненный голос из справочника побеждает: руководитель колл-центра меняет
    его в группе линий, не трогая настройки запуска. Пустое поле — это «оставить
    как есть», а не «синтезировать ничем»: новая группа линий, где голос ещё не
    выбрали, обязана продолжать говорить голосом из настроек запуска, а не
    ронять синтез.
    """
    return (feed_voice or "").strip() or default_voice


def effective_voice(voice: str, texts, library, fallback_voice: str,
                    label: str = "") -> str:
    """Голос набора. Желаемый голос сохраняется, даже если в библиотеке записаны
    не все фразы: недостающие озвучит запасной движок пофразно (RecordedSynthesizer),
    а не весь голос целиком уходит в запас (заказчик, 05.11.2026). Раньше любой пробел
    ронял группу в s3: аналитик завёл одну новую тему в разметке, и весь голос
    пропадал. Недостающие всё равно пишем в лог: по ним делается следующий прогон
    синтеза. Залипания запасного звука нет: отпечаток библиотеки входит в ключ кэша
    и в подпись станции (RecordedSynthesizer.model_id), так что добавленная запись
    подхватится, а не останется проигрываться запасным движком.
    """
    if library is None or voice not in library.voices:
        return voice
    # texts может быть функцией: набор фраз считается только когда он нужен,
    # без библиотеки фабрика диалога базу знаний не трогает вовсе.
    if callable(texts):
        texts = texts()
    missing = library.missing(voice, texts)
    if missing:
        log.warning(
            "%sголос %s: в библиотеке нет %d из %d фраз, их озвучит запасной %s пофразно. Нет: %s",
            (label + ": ") if label else "", voice, len(missing), len(texts), fallback_voice,
            " | ".join(missing[:5]) + (" | …" if len(missing) > 5 else ""),
        )
    return voice


def audio_signature_for(tts_model: str, voice: str) -> str:
    """Подпись звука — модель синтеза плюс действующий голос.

    Она входит в имя файла, который AGI-скрипт скачивает и кэширует на самой
    станции (dialog._playback_name). Если голос сменился, а подпись осталась
    прежней, Астериск продолжит играть уже скачанные файлы прежним голосом, и
    смена голоса со стороны выглядит несработавшей — ровно так уже вышло при
    переходе v4_ru -> v5_ru, когда в подписи не было модели. Голос сюда
    передаётся уже действующий (после resolve_voice), а не сырой из посылки:
    иначе пустое поле справочника обесценило бы кэш станции на ровном месте.

    Третья часть подписи — версия обработки звука (AUDIO_PIPELINE_VERSION).
    Модель и голос могут остаться теми же, а звук — измениться: так вышло с
    нормализацией громкости 31.08.2026. Без этой части правка осталась бы в
    коде и никогда не доехала бы до трубки.
    """
    return "{0}|{1}|{2}".format(tts_model, voice, AUDIO_PIPELINE_VERSION)


def build_dialog_factory(
    support_exten: str,
    sales_exten: str,
    tts_model: str = "",
    default_voice: str = "",
    library=None,
    fallback_voice: str = "",
):
    """Как из присланной посылки получается движок диалога.

    Служебные фразы бота берутся из той же посылки: их правят в той же группе
    линий, что и базу знаний, и разъезд между ними было бы видно только на
    живом звонке. Номера отделов остаются настройкой сервиса — в справочниках
    ERP их нет, а деться записи без своего направления куда-то должны.

    Подпись звука считается на каждую посылку заново: голос приезжает в ней же,
    и имена файлов обязаны меняться вместе с ним. У каждой группы линий она
    своя: одна и та же фраза, произнесённая двумя голосами, обязана получить
    два разных имени файла, иначе станция сыграет уже скачанное чужим голосом.
    """

    def factory(knowledge, feed: ParsedFeed) -> DialogEngine:
        voice = resolve_voice(feed.voice, default_voice)
        voice = effective_voice(
            voice, lambda: collect_speakable_phrases(feed.phrases, knowledge, feed.audio_files),
            library, fallback_voice or default_voice, "набор по умолчанию")
        profiles = []
        for group in feed.line_groups:
            # Голос группы, потом голос набора по умолчанию, потом голос
            # настроек запуска: пустое поле справочника — это «оставить как
            # есть», а не «синтезировать ничем».
            group_voice = resolve_voice(group.voice, voice)
            group_voice = effective_voice(
                group_voice, lambda g=group: collect_speakable_phrases(g.phrases, knowledge, g.audio_files),
                library, fallback_voice or default_voice, "группа линий %s" % group.line_group_id)
            profiles.append(replace(
                group,
                voice=group_voice,
                audio_signature=audio_signature_for(tts_model, group_voice),
            ))
        return DialogEngine(
            knowledge,
            feed.phrases,
            # Номер ТН 17 «Сопровождение» приезжает в посылке: правят его в
            # справочнике направлений, а не в настройках запуска сервиса.
            # Пустой — номер у ТН 17 не заполнен либо посылка от прежнего
            # обработчика; поведение остаётся прежним, а не выдуманным.
            support_exten=feed.support_exten or support_exten,
            sales_exten=sales_exten,
            audio_signature=audio_signature_for(tts_model, voice),
            voice=voice,
            audio_files=feed.audio_files,
            line_profiles=profiles,
            is_private_master=feed.is_private_master,
            forced_lookup=was_forced,
            peak_lookup=last_peak,
        )

    return factory


class KnowledgeState:
    """Текущая база знаний и сведения о посылке, из которой она собрана.

    Подмена — одной операцией в самом конце: пока новый индекс считается,
    звонки обслуживаются прежним. Кривая посылка не должна оставлять базу
    знаний наполовину обновлённой, потому что такое расхождение не видно.
    """

    def __init__(self, cache_path, embedder, threshold=0.64, dialog_factory=None,
                 fallback_engine=None, default_voice="", corpus=None,
                 intent=None, intent_repeat_threshold=0.70):
        self._cache_path = cache_path
        self._embedder = embedder
        self._threshold = threshold
        # Корпус живых реплик один на все посылки: он не приезжает из ERP,
        # а собирается из записей звонков и меняется только с перезапуском.
        self._corpus = corpus
        # Ярус намерения тоже один на все посылки и по той же причине: модель
        # обучается офлайн и лежит файлом рядом с сервисом. Передавать его
        # здесь ОБЯЗАТЕЛЬНО: база знаний пересобирается на каждой посылке из
        # ERP (раз в десять минут), и без этого ярус тихо отключился бы через
        # десять минут после запуска.
        self._intent = intent
        self._intent_repeat_threshold = intent_repeat_threshold
        self._dialog_factory = dialog_factory
        # Движок на базе из файла — он обслуживает звонки, пока первой посылки
        # не было, и разговоры при первой же подмене надо перенимать у него.
        self._fallback_engine = fallback_engine
        self._default_voice = default_voice
        self._lock = threading.Lock()

        self.knowledge = None
        self.dialog_engine = None
        self.phrases = None
        self.generated_at = None
        self.received_at = None
        #: Отпечаток той базы знаний, которая обслуживает звонки прямо сейчас.
        #: Пустая строка, а не None: обработчик сравнивает его строкой и пустое
        #: значение считает поводом прислать справочники — то есть до первой
        #: посылки он их пришлёт, как и должен.
        self.content_hash = ""
        #: Что в последней принятой базе знаний выглядит сломанным. Видно в
        #: /health: аналитик узнаёт о своей опечатке в тот же день, а не на
        #: разборе волны через две недели.
        self.warnings: List[str] = []
        self.record_count = 0
        self.phrase_count = 0
        #: Сколько наборов фраз приехало сверх набора по умолчанию. Смена
        #: настроек группы по самому справочнику не проверяется, а по этой
        #: цифре в логе сразу видно, доехало ли разделение по группам вообще.
        self.line_group_count = 0
        #: Голос, которым бот говорит прямо сейчас. Отсюда его берёт ручка /tts:
        #: AGI-скрипт голос не передаёт (контракт с ним не меняем), и решать,
        #: чем синтезировать, приходится самому сервису.
        self.voice = default_voice

    def apply(self, feed: ParsedFeed, warnings: Optional[List[str]] = None) -> None:
        warnings = list(warnings or ())
        knowledge = KnowledgeBase(feed.records, self._embedder, self._threshold,
                                  corpus=self._corpus, intent=self._intent,
                                  intent_repeat_threshold=self._intent_repeat_threshold)
        phrase_count = sum(1 + len(r.question_variants) for r in feed.records)
        voice = resolve_voice(feed.voice, self._default_voice)
        engine = self._dialog_factory(knowledge, feed) if self._dialog_factory else None
        if engine is not None:
            # Разговоры, идущие прямо сейчас, переезжают на новый движок
            # целиком — иначе клиент, услышавший уточняющий вопрос секунду
            # назад, ответит «да» движку, который про его звонок не знает.
            engine.adopt_sessions(self.dialog_engine or self._fallback_engine)

        with self._lock:
            self.knowledge = knowledge
            self.dialog_engine = engine
            self.phrases = feed.phrases
            self.voice = voice
            self.generated_at = feed.generated_at
            self.received_at = datetime.now().isoformat(timespec="seconds")
            # Отпечаток меняется здесь и только здесь — вместе с самой базой
            # знаний. Посылка, не прошедшая разбор, до apply() не доходит, так
            # что прежний отпечаток остаётся, и обработчик пришлёт свою базу
            # снова. Проставь мы отпечаток раньше применения — он бы решил, что
            # база принята, и бот молча жил бы на старой.
            self.content_hash = feed.content_hash
            self.warnings = warnings
            self.record_count = len(feed.records)
            self.phrase_count = phrase_count
            self.line_group_count = len(feed.line_groups)

    def accept(self, payload) -> ParsedFeed:
        # Порядок важен: сначала разбор и применение, и только потом запись на
        # диск. Иначе на диск попадёт посылка, которую сервис не смог применить,
        # и после перезапуска он поднимется именно на ней.
        feed = parse_feed(payload)
        warnings = check_feed(feed)
        self.apply(feed, warnings)
        save_feed(payload, self._cache_path)
        # Копия в архив под отпечатком содержимого: на диске лежала только
        # последняя посылка, и реплей прошлой волны шёл на нынешней базе, то
        # есть проверял не то, что тогда отвечало на звонки.
        archive_feed(payload, self._cache_path, feed.content_hash)
        return feed

    def restore_from_disk(self) -> bool:
        payload = load_feed(self._cache_path)
        if payload is None:
            return False
        try:
            restored = parse_feed(payload)
            self.apply(restored, check_feed(restored))
            return True
        except FeedError:
            log.exception("Копия посылки не разбирается, стартуем без неё")
            return False


def collect_speakable_phrases(
    phrases: Phrases, knowledge, audio_files: Optional[Dict[str, str]] = None
) -> List[str]:
    """Всё, что бот вообще способен синтезировать.

    Служебные фразы плюс уточняющие вопросы и ответы при согласии из базы
    знаний. Записи без уточняющего вопроса — это ещё не размеченные
    неопознанные реплики, бот их не произносит и синтезировать их незачем.

    Фразы с заранее записанным аудио сюда не попадают: файл уже лежит на
    станции, синтезировать его нечем и незачем.
    """
    recorded = audio_files or {}
    texts = [
        getattr(phrases, slot)
        # Порядок тот же, что и раньше: приветствие, переспрос, перевод,
        # молчание, «не угадал тему» и переспрос в точке подтверждения. Два
        # последних звучат в самые нервные моменты разговора — клиент уже
        # решил, что бот сломался, и две секунды холодного синтеза поверх
        # этого ровно то, что чинить и пытаемся.
        for slot in PHRASE_SLOTS
        if slot not in recorded
    ]
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


def collect_prewarm_plan(
    profiles: List[LineProfile], knowledge
) -> List[Tuple[str, List[str]]]:
    """Что и каким голосом греть: пары «голос — фразы».

    У каждой группы линий свой голос, и греть надо каждый: фраза второй
    группы, синтезированная впервые прямо на звонке, слушается клиентом как
    двухсекундная тишина. База знаний общая, поэтому её уточняющие вопросы
    попадают в план по разу на голос — своим голосом каждый.

    Группы с одинаковым голосом сливаются: у них и имена файлов одни и те же,
    греть их дважды значит впустую потратить минуты запуска.
    """
    plan: Dict[str, List[str]] = {}
    for profile in profiles:
        texts = collect_speakable_phrases(profile.phrases, knowledge, profile.audio_files)
        bucket = plan.setdefault(profile.voice, [])
        for text in texts:
            if text not in bucket:
                bucket.append(text)
    return list(plan.items())


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

    def current_voice() -> str:
        """Голос из справочника, пока он там заполнен, иначе из настроек запуска.

        Читается на каждый запрос, а не запоминается при сборке приложения:
        посылка приезжает из ERP посреди рабочего дня и может сменить голос.
        """
        if state is not None and state.voice:
            return state.voice
        return voice

    @app.post("/dialog")
    def dialog(payload: dict):
        prms = prms_to_dict(payload.get("prms", []))
        # Порядок выбора: пришедшая от ERP база знаний, если она есть, иначе
        # прежняя из файла. Ссылку берём один раз на весь запрос — посылка,
        # применённая посреди разговора, не должна расщепить одну реплику
        # между двумя базами.
        engine = dialog_engine
        if state is not None and state.dialog_engine is not None:
            engine = state.dialog_engine
        result = engine.handle(prms)

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
        effective_voice = voice_name or current_voice()
        start = time.perf_counter()
        path = tts_cache.get(text, effective_voice)
        duration_ms = (time.perf_counter() - start) * 1000.0
        log.info("TTS %.1f ms | voice=%s | text=%.80r", duration_ms, effective_voice, text)
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
        # Голос в логе не для красоты: смена голоса — единственная правка
        # справочника, которую по самому справочнику не проверить, а по логу
        # видно сразу, применилась она или поле приехало пустым.
        log.info(
            "Принята база знаний: %s записей, %s формулировок, %s групп линий, "
            "голос %s, собрана %s",
            state.record_count, state.phrase_count, state.line_group_count,
            state.voice, feed.generated_at,
        )
        for warning in state.warnings:
            # Предупреждением, а не отказом: правку аналитика из-за подозрения
            # останавливать нельзя, он правит базу по живым жалобам. Но мёртвый
            # замок категории уже жил в работе две недели незамеченным.
            log.warning("База знаний: %s", warning)
        return {
            "records": state.record_count,
            "phrases": state.phrase_count,
            "warnings": state.warnings,
        }

    @app.get("/health")
    def health():
        # Возраст данных — единственный способ заметить, что робот перестал
        # приносить справочники: сервис при этом жив и отвечает на звонки
        # прежней базой знаний, и по одному "ok" поломки не видно. По той же
        # причине здесь и source: "feed" — звонки обслуживает присланная база,
        # "file" — прежняя из файла.
        # content_hash здесь читает сам обработчик: совпал с посчитанным —
        # посылку он не отправляет вовсе, и сервис не пересчитывает эмбеддинги
        # пятисот формулировок ради базы, которая не менялась.
        knowledge_info = {
            "records": 0, "phrases": 0, "generated_at": None, "received_at": None,
            "content_hash": "", "source": "file", "warnings": [],
        }
        if state is not None:
            knowledge_info = {
                "records": state.record_count,
                "phrases": state.phrase_count,
                "generated_at": state.generated_at,
                "received_at": state.received_at,
                "content_hash": state.content_hash,
                "source": "feed" if state.dialog_engine is not None else "file",
                # Что в базе выглядит сломанным: записи без формулировок,
                # одинаковые формулировки у разных записей, замки категорий без
                # записей, записи, которые некуда переводить.
                "warnings": list(state.warnings),
            }
        gates_info = {}
        if state is not None and state.knowledge is not None:
            # Замок категории сработал, а вести по нему было некуда. Ноль здесь
            # означает, что все замки целятся в существующие записи.
            gates_info = dict(getattr(state.knowledge, "category_misses", {}) or {})
        return {"status": "ok", "knowledge": knowledge_info, "dead_category_gates": gates_info}

    return app


def setup_logging(log_dir: str) -> None:
    """Консоль плюс файл с ротацией.

    До 24.09.2026 лог жил только в окне сервиса: разбирать жалобы второго
    этапа теста («сказал нет — всё равно соединили») пришлось по истории
    обращений в ERP, без строк SIMILARITY/CORPUS, по которым и видно, кто и
    почему решил. Файл — logs/aia.log, 10 МБ × 5.
    """
    from logging.handlers import RotatingFileHandler

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)
    try:
        os.makedirs(log_dir, exist_ok=True)
        file_handler = RotatingFileHandler(
            os.path.join(log_dir, "aia.log"), maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except OSError as error:
        root.warning("Лог в файл не ведётся: %s", error)


def main() -> None:
    setup_logging(os.environ.get("AIA_LOG_DIR", "logs"))
    cfg = load_config()

    log.info("Загружаем эмбеддер %s", cfg.embedder_model)
    embedder = SentenceTransformerEmbedder(cfg.embedder_model)
    corpus = load_corpus_index(cfg)
    intent = None
    if cfg.tiers_enabled:
        # Размерность проверяется по живому эмбеддеру: модель, обученная на
        # другом эмбеддере, молча давала бы мусорные вероятности, а при
        # несовпадении длины вектора ронял бы каждый звонок в аварийный
        # перевод (находка консилиума L5-05).
        probe = embedder.encode(["search_query: проверка"])[0]
        intent = load_intent_model(
            cfg.intent_model_path,
            expected_dim=int(len(probe)),
            expected_embedder=cfg.embedder_model,
        )
        if intent is None:
            log.warning("Ярус намерения включён настройкой, но модель не загрузилась: решают корпус и формулировки")
        else:
            log.info("Ярус намерения включён, порог повторного обращения %.2f", cfg.intent_repeat_threshold)
    else:
        log.info("Ярус намерения выключен (AIA_TIERS_ENABLED=0)")
    knowledge = load_knowledge_base(
        cfg.knowledge_path, embedder, cfg.similarity_threshold, corpus=corpus,
        intent=intent, intent_repeat_threshold=cfg.intent_repeat_threshold,
    )

    log.info("Загружаем движок распознавания %s", cfg.stt_engine)
    engine = create_engine(
        cfg.stt_engine,
        model_path=os.environ.get("AIA_VOSK_MODEL_PATH", ""),
        model_name=cfg.gigaam_model,
    )

    fallback_engine = None
    if cfg.stt_engine == "gigaam" and cfg.stt_fallback_model and cfg.stt_fallback_model != cfg.gigaam_model:
        log.info("Загружаем вторую модель распознавания %s (второе мнение на промахах)", cfg.stt_fallback_model)
        fallback_engine = create_engine("gigaam", model_path="", model_name=cfg.stt_fallback_model)

    log.info("Загружаем VAD и синтез (%s)", cfg.tts_engine)
    detector = SileroVoiceDetector(threshold=cfg.vad_threshold)
    log.info("Порог детектора речи %.2f", cfg.vad_threshold)
    synthesizer = create_synthesizer(
        cfg.tts_engine, cfg.tts_model, cfg.vosk_tts_model_path
    )
    # Голос, которым говорит набор, если его библиотечный голос неполон.
    # Это голос движка синтеза, а не библиотеки: cfg.tts_voice может сам
    # оказаться библиотечным (руководитель выбрал голос A и по умолчанию).
    fallback_voice = cfg.tts_voice
    library = VoiceLibrary(cfg.voice_library_dir)
    if library.voices:
        # Запасной голос вычисляем ДО создания синтезатора и передаём ему
        # именем. Раньше синтезатор создавался первым и запасного голоса не
        # получал вовсе: в движок уходило имя библиотечного голоса, которого он
        # не знает, и он брал своё умолчание. Настройка запасного голоса не
        # действовала, а в логе появлялось ложное «проверьте AI_VOICE в группе
        # линий» (A6, п. 5).
        #
        # Умолчание берём у самого движка, а не прошиваем именем vosk-голоса:
        # на откате AIA_TTS_ENGINE=silero прошитое s3 уехало бы в silero,
        # который таких дикторов не знает, и ручка /tts отдала бы 500.
        if fallback_voice in library.voices:
            fallback_voice = engine_default_voice(synthesizer)
        synthesizer = RecordedSynthesizer(library, synthesizer, fallback_voice)
        log.info("Запасной голос для фраз вне библиотеки: %s", fallback_voice)
        log.info("Библиотека голосов %s: %s",
                 cfg.voice_library_dir,
                 ", ".join("%s (%d фраз)" % (v, library.phrase_count(v)) for v in library.voices))
    else:
        library = None
        if cfg.voice_library_dir:
            log.info("Библиотека голосов не подключена (%s пуста или нет) — только синтез",
                     cfg.voice_library_dir)
        else:
            # Выключена словом в bat (AIA_VOICE_LIBRARY_DIR=нет): это откат на
            # синтез, когда в бой уехала плохая запись голоса. Прежде такой
            # откат пустым значением не срабатывал, см. config._env_optional_str.
            log.info("Библиотека голосов выключена настройкой — только синтез")
    tts_cache = TtsCache(synthesizer, cfg.tts_cache_dir)
    # Чистка кэша синтеза идёт ДО прогрева, а не после. Попадание в кэш время
    # файла не обновляет, поэтому живая фраза, синтезированная месяц назад,
    # для правила срока выглядит так же, как мусор от старого отпечатка
    # библиотеки. Чистим первыми, и прогрев тут же создаёт заново всё, что
    # действительно нужно, с новым временем. После прогрева порядок был бы
    # обратным: живую фразу удалили бы, а синтез её пришёлся бы на звонок.
    #
    # И именно поэтому чистка держится за прогрев: без него восстанавливать
    # удалённое НЕКОМУ, и каждая живая фраза досинтезировалась бы внутри
    # разговора по полсекунды, приветствие в том числе. Обоснование порядка
    # выше при выключенном прогреве просто неверно, так что выключаем вместе.
    if cfg.prewarm_tts:
        prune_old_files(cfg.tts_cache_dir, cfg.tts_cache_max_mb, cfg.tts_cache_keep_days,
                        what="Кэш синтеза")
    elif cfg.tts_cache_max_mb > 0 or cfg.tts_cache_keep_days > 0:
        log.info("Чистка кэша синтеза пропущена: прогрев выключен, восстанавливать "
                 "удалённое было бы некому, и синтез пришёлся бы на разговор")
    # Подпись звука берётся у самого синтезатора, а не из cfg.tts_model:
    # у vosk модель задаётся папкой, и cfg.tts_model при нём вообще не
    # участвует в синтезе. Возьми мы его — подпись осталась бы прежней при
    # смене движка, а станция продолжила бы играть скачанные файлы прежним
    # голосом. Ровно так уже вышло при переходе v4_ru -> v5_ru.
    tts_model_id = synthesizer.model_id

    phrases = Phrases(
        greeting="Здравствуйте, чем могу помочь?",
        misrecognition="Попробуйте переформулировать свой вопрос, пожалуйста",
        transfer="Минуту, перевожу ваш звонок на специалиста",
        silence="Вы меня слышите?",
        wrong_guess="Тогда подскажите, пожалуйста, что вас интересует?",
    )
    file_voice = effective_voice(
        cfg.tts_voice, lambda: collect_speakable_phrases(phrases, knowledge), library, fallback_voice, "база из файла")
    audio_signature = audio_signature_for(tts_model_id, file_voice)
    dialog_engine = DialogEngine(
        knowledge,
        phrases,
        support_exten=SUPPORT_EXTEN,
        sales_exten=SALES_EXTEN,
        audio_signature=audio_signature,
        voice=file_voice,
    )

    def prewarm(plan: List[Tuple[str, List[str]]]) -> None:
        if not cfg.prewarm_tts:
            return
        for prewarm_voice, speakable in plan:
            log.info("Прогреваем синтез голосом %s: %s фраз", prewarm_voice, len(speakable))
            done, elapsed = prewarm_tts_cache(tts_cache, prewarm_voice, speakable)
            log.info("Синтез прогрет: %s из %s фраз за %.1f с", done, len(speakable), elapsed)

    prewarm([(file_voice, collect_speakable_phrases(phrases, knowledge))])

    log.info("Прогреваем распознавание и поиск по смыслу")
    log.info("Распознавание и поиск прогреты за %.1f с", prewarm_recognition(engine, knowledge, fallback_engine))
    start_keepwarm(engine, knowledge, cfg.keepwarm_seconds, fallback_engine=fallback_engine)

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

    # Предел одновременных вызовов задаётся вместе с пулом и равен ему.
    # Обработчик Recognize занимает поток на весь звонок, поэтому без
    # maximum_concurrent_rpcs лишний вызов не отклонялся, а молча ждал
    # свободного потока: обработчик не стартовал, события FINAL и SILENCE не
    # приходили, и клиент после приветствия слушал тишину до таймаута станции
    # 120 с. С пределом лишний звонок получает отказ сразу, а станция по
    # отказу gRPC уводит его на аварийный перевод к человеку
    # (agi/ai_assistant.py, decide_failure_step и failover_to_support).
    if cfg.torch_threads > 0:
        try:
            import torch

            torch.set_num_threads(cfg.torch_threads)
            log.info("Потоков на одно распознавание: %s", cfg.torch_threads)
        except Exception:
            log.exception("Не удалось ограничить число потоков torch")
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=cfg.grpc_max_calls),
        maximum_concurrent_rpcs=cfg.grpc_max_calls,
    )
    speech_pb2_grpc.add_SpeechServicer_to_server(
        SpeechServicer(
            segmenter_factory, engine, timeline_sink, active_timelines, timelines_lock,
            debug_audio_dir=cfg.debug_audio_dir,
            fallback_engine=fallback_engine,
            # knowledge_state создаётся ниже; к первому звонку она уже есть.
            knowledge_lookup=lambda: knowledge_state.knowledge,
        ),
        server,
    )
    if cfg.debug_audio_dir:
        log.info("Реплики звонков сохраняются в %s", cfg.debug_audio_dir)
        start_debug_audio_cleaner(cfg.debug_audio_dir, cfg.debug_audio_max_mb, cfg.debug_audio_keep_days)
    server.add_insecure_port("0.0.0.0:{0}".format(cfg.grpc_port))
    server.start()
    log.info("gRPC слушает порт %s", cfg.grpc_port)
    log_build_fingerprint(cfg)

    # Приёмник справочников из ERP. Пришедшая база знаний обслуживает звонки
    # сама (см. выбор движка в /dialog), база из файла остаётся страховкой на
    # то время, пока первая посылка не пришла.
    knowledge_state = KnowledgeState(
        cache_path=cfg.feed_cache_path,
        embedder=embedder,
        threshold=cfg.similarity_threshold,
        dialog_factory=build_dialog_factory(
            SUPPORT_EXTEN, SALES_EXTEN, tts_model_id, cfg.tts_voice,
            library=library, fallback_voice=fallback_voice,
        ),
        fallback_engine=dialog_engine,
        default_voice=cfg.tts_voice,
        corpus=corpus,
        intent=intent,
        intent_repeat_threshold=cfg.intent_repeat_threshold,
    )
    if knowledge_state.restore_from_disk():
        log.info(
            "Поднята копия последней посылки: %s записей, %s групп линий, голос %s, собрана %s",
            knowledge_state.record_count, knowledge_state.line_group_count,
            knowledge_state.voice, knowledge_state.generated_at,
        )
        # Звонки пойдут по ней же, значит и синтез греть надо по ней: иначе
        # первый после перезапуска клиент слушает тишину холодного синтеза.
        # Голоса берём те, которыми бот и будет говорить, — все, сколько их
        # приехало в группах линий: прогрев чужим голосом не пригодится вовсе.
        # Фразы посылок, пришедших уже во время работы, синтезируются по ходу
        # разговора — как было и раньше для новых записей.
        prewarm(collect_prewarm_plan(
            knowledge_state.dialog_engine.profiles, knowledge_state.knowledge
        ))

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
