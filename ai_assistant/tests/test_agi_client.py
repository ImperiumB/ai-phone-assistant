import ast
import pathlib

import pytest

from ai_assistant.agi.ai_assistant import (
    DialogAnswer,
    build_dialog_request,
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


def test_source_is_parseable_by_python_39_grammar():
    """На Астериске Python 3.9.2 — синтаксис новее там не запустится."""
    source_path = pathlib.Path(__file__).resolve().parents[1] / "agi" / "ai_assistant.py"
    source = source_path.read_text(encoding="utf-8")
    ast.parse(source, feature_version=(3, 9))


def test_source_avoids_pep604_unions_in_annotations():
    source_path = pathlib.Path(__file__).resolve().parents[1] / "agi" / "ai_assistant.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.annotation, ast.BinOp):
            pytest.fail("Аннотация вида X | Y не работает на Python 3.9")
