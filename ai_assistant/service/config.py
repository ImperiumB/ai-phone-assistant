"""Настройки сервиса. Читаются из переменных окружения с префиксом AIA_."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    grpc_port: int
    http_port: int
    stt_engine: str
    gigaam_model: str
    tts_model: str
    tts_voice: str
    embedder_model: str
    similarity_threshold: float
    silence_timeout_ms: int
    utterance_pause_ms: int
    stt_timeout_s: int
    knowledge_path: str
    feed_cache_path: str
    tts_cache_dir: str
    prewarm_tts: bool


def _env_str(name: str, default: str) -> str:
    return os.environ.get("AIA_" + name, default)


def _env_int(name: str, default: int) -> int:
    return int(os.environ.get("AIA_" + name, default))


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get("AIA_" + name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on", "да")


def _env_float(name: str, default: float) -> float:
    return float(os.environ.get("AIA_" + name, default))


def load_config() -> Config:
    return Config(
        grpc_port=_env_int("GRPC_PORT", 50051),
        http_port=_env_int("HTTP_PORT", 8080),
        stt_engine=_env_str("STT_ENGINE", "vosk"),
        # v3_rnnt, а не v2_rnnt: замер 14.08.2026 на одном материале дал
        # распознавание 0.281 с против 0.378 с при том же результате.
        # Другие варианты: v3_ctc (ещё быстрее, чуть менее точна),
        # v3_e2e_rnnt (расставляет пунктуацию и заглавные буквы).
        gigaam_model=_env_str("GIGAAM_MODEL", "v3_rnnt"),
        tts_model=_env_str("TTS_MODEL", "v4_ru"),
        tts_voice=_env_str("TTS_VOICE", "eugene"),
        embedder_model=_env_str("EMBEDDER_MODEL", "ai-forever/ru-en-RoSBERTa"),
        # 0.64 подобран замером 14.08.2026 на базе из 28 направлений
        # (348 формулировок). 34 живые фразы клиентов попали в своё
        # направление с близостью 0.684-0.832; посторонние вопросы
        # ("сколько стоит ремонт", "хочу оставить жалобу", "где вы находитесь",
        # "как до вас доехать") — 0.465-0.597. Порог стоит посередине зазора.
        #
        # Прежние 0.75 отсекали больше половины нормальной речи: реальное
        # "стиралка машинка сломалась" давало 0.719 и уходило на оператора
        # вместо уточняющего вопроса.
        #
        # Правило на будущее: чем больше синонимов в записях, тем выше можно
        # держать порог — варианты поднимают близость к своей записи, не трогая
        # близость к чужим. Но чем больше самих записей, тем теснее они стоят
        # друг к другу, и зазор снова сужается. После правки базы порог надо
        # перемерять, а не оставлять на глаз.
        similarity_threshold=_env_float("SIMILARITY_THRESHOLD", 0.64),
        silence_timeout_ms=_env_int("SILENCE_TIMEOUT_MS", 15000),
        # 1500, а не 3000: с трёхсекундной паузой ответ бота приходит через ~4 секунды
        # после конца фразы, и разговор ощущается сломанным. Плата — бот перебьёт того,
        # кто задумался дольше полутора секунд.
        utterance_pause_ms=_env_int("UTTERANCE_PAUSE_MS", 1500),
        stt_timeout_s=_env_int("STT_TIMEOUT_S", 10),
        knowledge_path=_env_str("KNOWLEDGE_PATH", "ai_assistant/knowledge_base.json"),
        # Копия последней присланной посылки. Сервис поднимается с неё, не
        # дожидаясь робота: перезапуск занимает минуту, робот приходит раз в
        # десять.
        feed_cache_path=_env_str("FEED_CACHE_PATH", "ai_assistant/knowledge_feed_cache.json"),
        tts_cache_dir=_env_str("TTS_CACHE_DIR", "/tmp/aia_tts_cache"),
        # Синтезировать все известные фразы при старте, а не по ходу звонка.
        # Холодный синтез стоит до 2 секунд (замер 14.08.2026 на v5_ru), и
        # клиент слушает их как тишину. Старт удлиняется, звонки — нет.
        prewarm_tts=_env_bool("PREWARM_TTS", True),
    )
