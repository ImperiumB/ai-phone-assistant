"""Скрипт последней воли: сообщение в ERP об оборванном звонке.

Основной AGI-скрипт при обрыве канала умирает мгновенно (SIGHUP, SIG_DFL —
намеренно, против зомби-процессов, которые роняли станцию), поэтому сказать
что-либо об обрыве он не может физически. Это делает отдельный скрипт,
который Астериск запускает на `exten => h`.
"""
import ast
import pathlib

import pytest
import requests

from ai_assistant.agi.ai_assistant_last_will import (
    ERP_TIMEOUT_S,
    build_hangup_request,
    erp_url,
    send_last_will,
)


def pairs_of(request):
    return {item["Key"]: item["Value"] for item in request["prms"]}


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def test_hangup_request_carries_the_document():
    pairs = pairs_of(build_hangup_request("1204567", "1755.42", "холодильник не морозит", "False"))
    assert pairs["eventType"] == "AiAssistantHangup"
    assert pairs["documentId"] == "1204567"
    assert pairs["recognizedText"] == "холодильник не морозит"


def test_linked_id_is_always_sent():
    """Обрыв на первой секунде: обращение могло не успеть создаться, и найти
    его ERP сможет только по каналу."""
    pairs = pairs_of(build_hangup_request("", "1755.42", "", "False"))
    assert pairs["linkedId"] == "1755.42"
    assert "documentId" not in pairs


def test_zero_document_id_is_not_sent():
    """Переменная канала не выставлена — Астериск отдаёт пустую строку или ноль."""
    assert "documentId" not in pairs_of(build_hangup_request("0", "1755.42", "", "False"))


def test_script_finished_flag_is_passed_through():
    pairs = pairs_of(build_hangup_request("1204567", "1755.42", "", "True"))
    assert pairs["scriptFinished"] == "True"


def test_values_are_strings():
    request = build_hangup_request(1204567, "1755.42", "вопрос", False)
    for item in request["prms"]:
        assert isinstance(item["Value"], str)


def test_url_is_built_from_the_channel_variable():
    assert erp_url("10.0.0.1:65/svc") == (
        "http://10.0.0.1:65/svc/ReturnConversationIntermediateResult3"
    )


def test_last_will_uses_a_short_timeout():
    seen = {}

    def fake_post(url, json=None, timeout=None):
        seen["timeout"] = timeout
        return FakeResponse([{"Key": "Result", "Value": "OK"}])

    assert send_last_will("host/svc", {"prms": []}, post=fake_post) is True
    assert seen["timeout"] == ERP_TIMEOUT_S


def test_last_will_survives_a_dead_service():
    """Канала уже нет, ругаться некому — падать нельзя, только записать в лог."""
    def fake_post(url, json=None, timeout=None):
        raise requests.exceptions.ConnectionError("ERP лежит")

    assert send_last_will("host/svc", {"prms": []}, post=fake_post) is False


def test_last_will_survives_a_non_200_answer():
    def fake_post(url, json=None, timeout=None):
        return FakeResponse("Internal Server Error", status_code=500)

    assert send_last_will("host/svc", {"prms": []}, post=fake_post) is False


def test_source_is_parseable_by_python_39_grammar():
    """На Астериске Python 3.9.2 — синтаксис новее там не запустится."""
    source_path = pathlib.Path(__file__).resolve().parents[1] / "agi" / "ai_assistant_last_will.py"
    ast.parse(source_path.read_text(encoding="utf-8"), feature_version=(3, 9))


def test_source_avoids_pep604_unions_in_annotations():
    source_path = pathlib.Path(__file__).resolve().parents[1] / "agi" / "ai_assistant_last_will.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.annotation, ast.BinOp):
            pytest.fail("Аннотация вида X | Y не работает на Python 3.9")


def test_script_does_not_import_the_main_agi_module():
    """На станции файлы лежат рядом в agi-bin, пакета там нет.

    Импорт основного скрипта потянул бы за собой grpc и сгенерированные
    заглушки protobuf — ровно то, на чём станция уже спотыкалась при
    развёртывании. Скрипт последней воли обязан подниматься сам по себе.
    """
    source_path = pathlib.Path(__file__).resolve().parents[1] / "agi" / "ai_assistant_last_will.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    assert not [name for name in imported if "ai_assistant" in name or "grpc" in name]
