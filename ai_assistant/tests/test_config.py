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
    assert cfg.similarity_threshold == pytest.approx(0.64)
    assert cfg.utterance_pause_ms == 1500
    assert cfg.silence_timeout_ms == 15000
    assert cfg.stt_timeout_s == 10
    assert cfg.tts_voice == "eugene"
    # Третья версия: замер 14.08.2026 дал распознавание 0.281 с против 0.378 с
    # у v2_rnnt при том же результате.
    assert cfg.gigaam_model == "v3_rnnt"
    assert cfg.prewarm_tts is True


def test_environment_overrides_defaults(monkeypatch):
    monkeypatch.setenv("AIA_STT_ENGINE", "gigaam")
    monkeypatch.setenv("AIA_SIMILARITY_THRESHOLD", "0.62")
    monkeypatch.setenv("AIA_GRPC_PORT", "9999")
    cfg = load_config()
    assert cfg.stt_engine == "gigaam"
    assert cfg.similarity_threshold == pytest.approx(0.62)
    assert cfg.grpc_port == 9999
