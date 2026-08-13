import ast
import pathlib
import threading

import grpc
import pytest
import requests

from ai_assistant.agi.ai_assistant import (
    REAL_REDIRECT,
    DialogAnswer,
    _atomic_write,
    build_dialog_request,
    decide_failure_step,
    decide_next_step,
    parse_dialog_response,
)


def test_parses_full_erp_answer():
    answer = parse_dialog_response([
        {"Key": "Action", "Value": "Recognize"},
        {"Key": "TextToSpeak", "Value": "Здравствуйте"},
        {"Key": "FileToPlayback", "Value": "aia_abc"},
        {"Key": "ConversationPoint", "Value": "AskQuestion"},
        {"Key": "RedirectExten", "Value": ""},
    ])
    assert answer.action == "Recognize"
    assert answer.text_to_speak == "Здравствуйте"
    assert answer.file_to_playback == "aia_abc"
    assert answer.conversation_point == "AskQuestion"
    assert answer.redirect_exten == ""


def test_missing_keys_become_empty_strings():
    answer = parse_dialog_response([{"Key": "Action", "Value": "Hangup"}])
    assert answer.action == "Hangup"
    assert answer.text_to_speak == ""
    assert answer.redirect_exten == ""


def test_request_uses_key_value_shape_expected_by_erp():
    request = build_dialog_request("call-1", "AskQuestion", "привет", False)
    assert "prms" in request
    pairs = {item["Key"]: item["Value"] for item in request["prms"]}
    assert pairs["linkedId"] == "call-1"
    assert pairs["conversationPoint"] == "AskQuestion"
    assert pairs["recognizedText"] == "привет"
    assert pairs["silenceDetected"] == "False"


def test_silence_flag_is_serialised_as_capitalised_text():
    request = build_dialog_request("call-1", "AskQuestion", "", True)
    pairs = {item["Key"]: item["Value"] for item in request["prms"]}
    assert pairs["silenceDetected"] == "True"


@pytest.mark.parametrize(
    "action,expected",
    [("Recognize", "listen"), ("Redirect", "redirect"), ("Hangup", "hangup")],
)
def test_next_step_is_derived_from_action(action, expected):
    answer = DialogAnswer(action=action, text_to_speak="", file_to_playback="",
                          conversation_point="", redirect_exten="")
    assert decide_next_step(answer) == expected


def test_unknown_action_is_rejected_loudly():
    answer = DialogAnswer(action="Fly", text_to_speak="", file_to_playback="",
                          conversation_point="", redirect_exten="")
    with pytest.raises(ValueError):
        decide_next_step(answer)


@pytest.mark.parametrize(
    "error",
    [
        requests.exceptions.ConnectionError("service is down"),
        requests.exceptions.Timeout("dialog timed out"),
        grpc.RpcError(),
    ],
)
def test_network_failure_leads_to_failover(error):
    assert decide_failure_step(error) == "failover"


def test_programming_error_leads_to_general_catch():
    assert decide_failure_step(ValueError("bug in our own code")) == "reraise"


def test_atomic_write_creates_the_target_file_with_the_given_content(tmp_path):
    target = tmp_path / "phrase.wav"
    _atomic_write(str(target), b"hello")
    assert target.read_bytes() == b"hello"


def test_atomic_write_leaves_no_temporary_file_behind(tmp_path):
    target = tmp_path / "phrase.wav"
    _atomic_write(str(target), b"hello")
    assert list(tmp_path.glob("*.tmp")) == []


def test_atomic_write_uses_a_unique_temp_name_per_call(tmp_path, monkeypatch):
    """Item 8 финального ревью: раньше временный файл назывался одинаково
    для всех звонков — два одновременных, обоим нужна одна и та же ещё не
    закэшированная фраза, писали в один и тот же ".tmp" и затирали друг
    друга (ошибка молча проглатывалась в speak(), абонент не слышал ответа).
    """
    target = tmp_path / "phrase.wav"
    seen_tmp_names = []
    real_open = open

    def spying_open(path, *args, **kwargs):
        if str(path).endswith(".tmp"):
            seen_tmp_names.append(str(path))
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", spying_open)
    _atomic_write(str(target), b"one")
    _atomic_write(str(target), b"two")

    assert len(seen_tmp_names) == 2
    assert seen_tmp_names[0] != seen_tmp_names[1]


def test_atomic_write_survives_concurrent_writers_to_the_same_target(tmp_path):
    """Прямое воспроизведение сценария из ревью: несколько потоков
    одновременно пишут по одному и тому же итоговому пути — раньше падало
    ошибкой доступа к файлу на Windows (тот же паттерн, что и в
    ai_assistant/service/tts.py, test_concurrent_requests_for_the_same_uncached_text_all_succeed)."""
    target = tmp_path / "phrase.wav"
    errors = []
    lock = threading.Lock()

    def worker():
        try:
            _atomic_write(str(target), b"same phrase")
        except Exception as exc:  # noqa: BLE001 — тест должен увидеть любое падение
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert target.read_bytes() == b"same phrase"


def test_source_is_parseable_by_python_39_grammar():
    """На Астериске Python 3.9.2 — синтаксис новее там не запустится."""
    source_path = pathlib.Path(__file__).resolve().parents[1] / "agi" / "ai_assistant.py"
    source = source_path.read_text(encoding="utf-8")
    ast.parse(source, feature_version=(3, 9))


def test_real_redirect_is_off_by_default():
    """Спецификация ("Сценарий звонка") требует: реального перевода в очередь
    в прототипе нет — только запись в лог, иначе пока человек отлаживает
    бота, отделы продаж и сопровождения получают поток тестовых звонков.
    Включать переключатель можно только осознанно, после замеров."""
    assert REAL_REDIRECT is False


def test_source_avoids_pep604_unions_in_annotations():
    source_path = pathlib.Path(__file__).resolve().parents[1] / "agi" / "ai_assistant.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.annotation, ast.BinOp):
            pytest.fail("Аннотация вида X | Y не работает на Python 3.9")
