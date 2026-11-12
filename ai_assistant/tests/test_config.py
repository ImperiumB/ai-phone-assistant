import io
import os
import re

import pytest
from ai_assistant.service.config import OFF_WORDS, load_config


def test_defaults_are_applied(monkeypatch):
    for key in list(os.environ):
        if key.startswith("AIA_"):
            monkeypatch.delenv(key, raising=False)
    cfg = load_config()
    assert cfg.grpc_port == 50051
    assert cfg.http_port == 8080
    assert cfg.stt_engine == "vosk"
    # 0.74, а не 0.66 (07.11.2026, Э2): полоса 0.66-0.74 бесполезна, ошибка в
    # ней 58-69 % без зазора. Порог двигался в паре с операторским порогом
    # корпуса, замер пары в журнале тикета UL-19020.
    assert cfg.similarity_threshold == pytest.approx(0.74)
    assert cfg.corpus_operator_threshold == pytest.approx(0.50)
    # Предел одновременных звонков задан: без него лишний звонок молча ждал
    # в очереди, и клиент слушал тишину до таймаута станции 120 с.
    assert cfg.grpc_max_calls == 24
    # Потоки одного распознавания не ограничиваем, пока не замерено.
    assert cfg.torch_threads == 0
    # Записи разговоров не копятся без предела.
    assert cfg.debug_audio_max_mb == 1024
    assert cfg.debug_audio_keep_days == 14
    # Записи разговоров на диск по умолчанию не складываются.
    assert cfg.debug_audio_dir == ""
    # Кэш синтеза тоже не копится без предела: в ключ входит отпечаток
    # библиотеки голосов, и каждая её правка переименовывает весь кэш.
    assert cfg.tts_cache_max_mb == 64
    assert cfg.tts_cache_keep_days == 30
    assert cfg.keepwarm_seconds == 120
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



def test_optional_settings_can_be_turned_off_by_a_word(monkeypatch):
    """Выключение задаётся словом, потому что пустоту из bat задать нельзя.

    В cmd `set AIA_X=` переменную не обнуляет, а УДАЛЯЕТ, после чего
    os.environ.get отдаёт умолчание. На этом молча не сработала правка F6 плана
    ультракода («убрать второе мнение распознавания»): 07.11.2026 в bat
    поставили пустое значение, а в логе СБОРКА печаталось
    `второе_мнение=v2_rnnt`, и вторая модель грузилась на каждом старте.
    Поймала это строка отпечатка сборки 09.11.2026, до волны правка не дошла.
    """
    for word in ("нет", "выкл", "off", "none", "-", "НЕТ", "  нет  ", ""):
        monkeypatch.setenv("AIA_STT_FALLBACK_MODEL", word)
        monkeypatch.setenv("AIA_VOICE_LIBRARY_DIR", word)
        monkeypatch.setenv("AIA_CORPUS_INDEX_PATH", word)
        cfg = load_config()
        assert cfg.stt_fallback_model == "", word
        assert cfg.voice_library_dir == "", word
        assert cfg.corpus_index_path == "", word


def test_second_opinion_is_off_by_default_and_turns_on_by_name(monkeypatch):
    """Второе мнение распознавания выключено по умолчанию (решение F6).

    Прежнее умолчание «v2_rnnt» означало, что вторую модель нельзя выключить
    вовсе: выключатель в bat не работал, а умолчание её включало.
    """
    monkeypatch.delenv("AIA_STT_FALLBACK_MODEL", raising=False)
    assert load_config().stt_fallback_model == ""
    monkeypatch.setenv("AIA_STT_FALLBACK_MODEL", "v2_rnnt")
    assert load_config().stt_fallback_model == "v2_rnnt"


def test_production_bat_boots_the_config(monkeypatch):
    """Конфиг должен подниматься на окружении из боевого bat без исключений.

    09.11.2026 сервис упал на старте: выключатель второго мнения в bat написан
    транслитом (`net`), а список слов выключения в config.py был только
    кириллическим. Конфиг принял «net» за имя модели распознавания, и gigaam
    такой модели не нашёл. Юнит-тесты проверяли мой же список слов, а не то
    значение, которое реально стоит в пусковом файле, поэтому пропустили.

    Тест читает bat, подставляет ВСЕ его переменные и смотрит на результат.
    """
    bat = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "ЗАПУСК СЕРВИСА.bat")
    if not os.path.isfile(bat):
        pytest.skip("пусковой bat рядом не найден")
    for key in list(os.environ):
        if key.startswith("AIA_"):
            monkeypatch.delenv(key, raising=False)
    assigned = 0
    with io.open(bat, encoding="cp1251") as handle:
        for line in handle:
            found = re.match(r"\s*set\s+(AIA_[A-Z0-9_]+)=(.*)$", line.strip(), re.I)
            if found:
                monkeypatch.setenv(found.group(1), found.group(2))
                assigned += 1
    assert assigned > 10, "в bat не нашлось настроек, тест бесполезен"

    cfg = load_config()

    # Необязательные настройки: значение из bat должно быть либо выключением
    # (пустая строка), либо осмысленным значением, но НЕ словом-выключателем,
    # просочившимся как имя файла или модели.
    for name, value in (("stt_fallback_model", cfg.stt_fallback_model),
                        ("voice_library_dir", cfg.voice_library_dir),
                        ("corpus_index_path", cfg.corpus_index_path)):
        assert value.strip().lower() not in OFF_WORDS, (
            "%s = %r: слово выключения просочилось как значение, сервис упадёт "
            "на старте" % (name, value))

    # Имя модели распознавания должно быть из списка поддерживаемых: именно на
    # этом сервис и упал.
    assert re.match(r"^v?\d?_?(rnnt|ctc|ssl)$|^v\d+_e2e_(rnnt|ctc)$", cfg.gigaam_model), \
        "основная модель %r не похожа на имя модели gigaam" % cfg.gigaam_model
    if cfg.stt_fallback_model:
        assert re.match(r"^v?\d?_?(rnnt|ctc|ssl)$|^v\d+_e2e_(rnnt|ctc)$", cfg.stt_fallback_model), \
            "вторая модель %r не похожа на имя модели gigaam" % cfg.stt_fallback_model


def test_cleanup_limits_can_be_switched_off_by_a_word(monkeypatch):
    """В боевом bat настройку выключают словом, и на этом уже падал старт.

    09.11.2026 `AIA_STT_FALLBACK_MODEL=net` конфиг принял за имя модели, и
    служба не поднялась. Пределы чистки папок тюнят из того же bat и тем же
    способом, поэтому «нет» и «net» здесь означают ровно то, что человек имел
    в виду: правило выключить, то есть ноль.
    """
    monkeypatch.setenv("AIA_TTS_CACHE_MAX_MB", "net")
    monkeypatch.setenv("AIA_TTS_CACHE_KEEP_DAYS", "нет")
    monkeypatch.setenv("AIA_DEBUG_AUDIO_MAX_MB", "выкл")
    cfg = load_config()
    assert cfg.tts_cache_max_mb == 0
    assert cfg.tts_cache_keep_days == 0
    assert cfg.debug_audio_max_mb == 0


def test_a_broken_number_names_the_variable_in_the_error(monkeypatch):
    """Голое «invalid literal for int()» не говорит, ЧТО поправить в bat.

    Падает это при старте службы, когда до логов ещё не дошло, и человек видит
    только трассировку.
    """
    monkeypatch.setenv("AIA_GRPC_MAX_CALLS", "двадцать четыре")
    with pytest.raises(ValueError) as failure:
        load_config()
    assert "AIA_GRPC_MAX_CALLS" in str(failure.value)
