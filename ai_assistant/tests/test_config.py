import os
import pytest
from ai_assistant.service.config import load_config


def test_defaults_are_applied(monkeypatch):
    for key in list(os.environ):
        if key.startswith("AIA_"):
            monkeypatch.delenv(key, raising=False)
    cfg = load_config()
    assert cfg.grpc_port == 50051
    assert cfg.http_port == 8080
    assert cfg.stt_engine == "vosk"
    assert cfg.similarity_threshold == pytest.approx(0.66)
    # Записи разговоров на диск по умолчанию не складываются.
    assert cfg.debug_audio_dir == ""
    assert cfg.keepwarm_seconds == 300
    assert cfg.utterance_pause_ms == 1500
    assert cfg.silence_timeout_ms == 15000
    assert cfg.stt_timeout_s == 10
    # Боевой движок синтеза — vosk: у Silero модель v5_ru под CC BY-NC,
    # некоммерческой (UL-17568, разбор 03.09.2026).
    assert cfg.tts_engine == "vosk"
    # s3 — лучший по разборчивости диктор Vosk-TTS (замер 04.09.2026).
    assert cfg.tts_voice == "s3"
    # Пусто намеренно: модель кладётся на диск руками, путь задаётся явно.
    assert cfg.vosk_tts_model_path == ""
    # Третья версия: замер 14.08.2026 дал распознавание 0.281 с против 0.378 с
    # у v2_rnnt при том же результате.
    assert cfg.gigaam_model == "v3_rnnt"
    assert cfg.prewarm_tts is True
    assert cfg.feed_cache_path == "ai_assistant/knowledge_feed_cache.json"


def test_environment_overrides_defaults(monkeypatch):
    monkeypatch.setenv("AIA_STT_ENGINE", "gigaam")
    monkeypatch.setenv("AIA_SIMILARITY_THRESHOLD", "0.62")
    monkeypatch.setenv("AIA_GRPC_PORT", "9999")
    cfg = load_config()
    assert cfg.stt_engine == "gigaam"
    assert cfg.similarity_threshold == pytest.approx(0.62)
    assert cfg.grpc_port == 9999
