import ast
import pathlib
import threading

import grpc
import pytest
import requests

from ai_assistant.agi.ai_assistant import (
    ERP_INTEGRATION,
    ERP_TIMEOUT_S,
    REAL_REDIRECT,
    REASON_CALL_TIMEOUT,
    REASON_SCRIPT_ERROR,
    REASON_SERVICE_UNAVAILABLE,
    REASON_SPEECH_FAILED,
    DialogAnswer,
    _atomic_write,
    build_call_start_request,
    build_dialog_request,
    build_equipment_request,
    build_transfer_request,
    build_unknown_request,
    decide_failure_step,
    decide_next_step,
    direction_name_of,
    erp_url,
    parse_dialog_response,
    parse_erp_response,
    plays_from_station,
    remember_recognized_text,
    send_to_erp,
    station_playback_path,
    tts_params,
    should_send_equipment,
    should_send_unknown_question,
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


def test_conversation_start_time_is_published_to_the_channel():
    """Длительность разговора считает скрипт последней воли — по этой переменной.

    Основной скрипт при обрыве канала умирает мгновенно и сам ничего сообщить
    не успеет, так что время старта обязано лежать в канале с самого начала.
    `_main()` требует живого канала Asterisk, поэтому проверяем по исходнику.
    """
    source_path = pathlib.Path(__file__).resolve().parents[1] / "agi" / "ai_assistant.py"
    source = source_path.read_text(encoding="utf-8")
    assert 'set_variable("conversation_start_time", time.time())' in source


def test_source_avoids_pep604_unions_in_annotations():
    source_path = pathlib.Path(__file__).resolve().parents[1] / "agi" / "ai_assistant.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.annotation, ast.BinOp):
            pytest.fail("Аннотация вида X | Y не работает на Python 3.9")


# --- Обращение в ERP на время звонка (UL-18797) -------------------------------


def erp_pairs(request):
    return {item["Key"]: item["Value"] for item in request["prms"]}


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def test_erp_integration_is_on_by_default():
    """Выключатель существует ради отладки, но по умолчанию интеграция работает."""
    assert ERP_INTEGRATION is True


def test_erp_url_is_built_from_the_channel_variable():
    assert erp_url("10.0.0.1:65/Aster2ServiceWebHttp") == (
        "http://10.0.0.1:65/Aster2ServiceWebHttp/ReturnConversationIntermediateResult3"
    )


def test_erp_url_tolerates_a_trailing_slash():
    assert erp_url("10.0.0.1:65/svc/") == (
        "http://10.0.0.1:65/svc/ReturnConversationIntermediateResult3"
    )


def test_call_start_request_carries_the_three_keys_erp_needs():
    request = build_call_start_request("1755.42", "74951468847", "79161234567")
    pairs = erp_pairs(request)
    assert pairs["eventType"] == "AiAssistantCallStart"
    assert pairs["linkedId"] == "1755.42"
    # Набранный номер — по нему ERP ищет телефон линии, без него обращения нет.
    assert pairs["dialedNumber"] == "74951468847"
    assert pairs["callerPhone"] == "79161234567"


def test_erp_values_are_always_strings():
    """Служба перекладывает пары в Hashtable как есть, числа приезжают дробными."""
    request = build_equipment_request(12345, "холодильник не морозит", "Холодильники", "Холодильники")
    for item in request["prms"]:
        assert isinstance(item["Key"], str)
        assert isinstance(item["Value"], str)
    assert erp_pairs(request)["documentId"] == "12345"


def test_equipment_request_carries_the_topic():
    request = build_equipment_request("12345", "холодильник не морозит", "Холодильники", "Холодильники")
    pairs = erp_pairs(request)
    assert pairs["eventType"] == "AiAssistantEquipment"
    assert pairs["documentId"] == "12345"
    assert pairs["recognizedText"] == "холодильник не морозит"
    assert pairs["equipmentTypeName"] == "Холодильники"
    assert pairs["directionName"] == "Холодильники"


def test_empty_values_are_not_sent_at_all():
    """Пустое значение ключа обработчику ERP ничего не сообщает, только мусорит."""
    pairs = erp_pairs(build_equipment_request("12345", "", "Холодильники", ""))
    assert "recognizedText" not in pairs
    assert "directionName" not in pairs


def test_transfer_request_carries_where_the_call_went():
    request = build_transfer_request("12345", "7104", "Холодильники", "холодильник не морозит")
    pairs = erp_pairs(request)
    assert pairs["eventType"] == "AiAssistantTransfer"
    assert pairs["documentId"] == "12345"
    assert pairs["redirectExten"] == "7104"
    assert pairs["directionName"] == "Холодильники"
    assert pairs["recognizedText"] == "холодильник не морозит"


def test_erp_answer_is_parsed():
    answer = parse_erp_response([
        {"Key": "Result", "Value": "OK"},
        {"Key": "documentId", "Value": "1204567"},
        {"Key": "Message", "Value": "Обращение создано"},
    ])
    assert answer.ok is True
    assert answer.document_id == "1204567"
    assert answer.message == "Обращение создано"


def test_failed_erp_answer_is_not_ok():
    answer = parse_erp_response([
        {"Key": "Result", "Value": "FAIL"},
        {"Key": "documentId", "Value": "0"},
        {"Key": "Message", "Value": "Не найден телефон линии"},
    ])
    assert answer.ok is False
    # Нулевой код — это отсутствие обращения, запоминать его нельзя.
    assert answer.document_id == ""


def test_erp_answer_of_unexpected_shape_does_not_explode():
    answer = parse_erp_response("совсем не то, чего мы ждали")
    assert answer.ok is False
    assert answer.document_id == ""


def test_equipment_is_sent_once_when_the_topic_becomes_known():
    known = DialogAnswer(action="Redirect", text_to_speak="", file_to_playback="",
                         conversation_point="Finished", redirect_exten="7104",
                         equipment_type="Холодильники", telephone_direction_id="52")
    assert should_send_equipment(known, already_sent=False) is True
    assert should_send_equipment(known, already_sent=True) is False


def test_the_question_is_remembered_not_the_confirmation():
    """Обращение с текстом «да» оператору ничего не говорит."""
    question = remember_recognized_text("", "AskQuestion", "холодильник не морозит")
    assert question == "холодильник не морозит"
    assert remember_recognized_text(question, "Confirm", "да") == "холодильник не морозит"


def test_empty_recognition_does_not_erase_the_question():
    assert remember_recognized_text("холодильник не морозит", "AskQuestion", "") == (
        "холодильник не морозит"
    )


def test_a_second_question_replaces_the_first():
    """Бот не угадал, клиент переспросил по-другому — в обращении нужен второй вопрос."""
    assert remember_recognized_text("холодильник не морозит", "AskQuestion", "нужен мастер по плите") == (
        "нужен мастер по плите"
    )


def test_direction_name_comes_from_the_equipment_type_of_the_record():
    """Отдельного поля с названием направления у сервиса нет, а в справочнике
    ERP название направления совпадает с названием типа оборудования."""
    answer = DialogAnswer(action="Redirect", text_to_speak="", file_to_playback="",
                          conversation_point="Finished", redirect_exten="7104",
                          equipment_type="Холодильники", telephone_direction_id="52")
    assert direction_name_of(answer) == "Холодильники"


def test_direction_name_is_empty_when_the_topic_is_unknown():
    answer = DialogAnswer(action="Redirect", text_to_speak="", file_to_playback="",
                          conversation_point="Finished", redirect_exten="489")
    assert direction_name_of(answer) == ""


def test_equipment_is_not_sent_while_the_topic_is_unknown():
    unknown = DialogAnswer(action="Recognize", text_to_speak="", file_to_playback="",
                           conversation_point="AskQuestion", redirect_exten="")
    assert should_send_equipment(unknown, already_sent=False) is False


def test_dialog_answer_carries_the_erp_context():
    answer = parse_dialog_response([
        {"Key": "Action", "Value": "Redirect"},
        {"Key": "RedirectExten", "Value": "7104"},
        {"Key": "EquipmentType", "Value": "Холодильники"},
        {"Key": "Scenario", "Value": "redirect_direction"},
        {"Key": "TelephoneDirectionId", "Value": "52"},
        {"Key": "KnowledgeRecordId", "Value": "10"},
        {"Key": "MatchedQuestion", "Value": "не морозит холодильник"},
        {"Key": "Similarity", "Value": "0.8312"},
    ])
    assert answer.equipment_type == "Холодильники"
    assert answer.scenario == "redirect_direction"
    assert answer.telephone_direction_id == "52"
    assert answer.knowledge_record_id == "10"
    assert answer.matched_question == "не морозит холодильник"
    assert answer.similarity == "0.8312"


def test_old_answer_without_erp_context_still_parses():
    answer = parse_dialog_response([{"Key": "Action", "Value": "Recognize"}])
    assert answer.equipment_type == ""
    assert answer.knowledge_record_id == ""


def test_erp_call_returns_the_parsed_answer():
    def fake_post(url, json=None, timeout=None):
        return FakeResponse([{"Key": "Result", "Value": "OK"}, {"Key": "documentId", "Value": "77"}])

    answer = send_to_erp("host/svc", {"prms": []}, post=fake_post)
    assert answer is not None
    assert answer.document_id == "77"


def test_erp_call_uses_a_short_timeout():
    """Клиент в трубке важнее обращения: ждать ERP дольше пары секунд нельзя."""
    seen = {}

    def fake_post(url, json=None, timeout=None):
        seen["timeout"] = timeout
        seen["url"] = url
        return FakeResponse([{"Key": "Result", "Value": "OK"}])

    send_to_erp("host/svc", {"prms": []}, post=fake_post)
    assert seen["timeout"] == ERP_TIMEOUT_S
    assert ERP_TIMEOUT_S <= 5
    assert seen["url"].endswith("/ReturnConversationIntermediateResult3")


def test_erp_call_survives_a_dead_service():
    def fake_post(url, json=None, timeout=None):
        raise requests.exceptions.ConnectionError("ERP лежит")

    assert send_to_erp("host/svc", {"prms": []}, post=fake_post) is None


def test_erp_call_survives_a_broken_answer():
    def fake_post(url, json=None, timeout=None):
        raise ValueError("не разобрался json")

    assert send_to_erp("host/svc", {"prms": []}, post=fake_post) is None


def test_erp_call_ignores_a_non_200_answer():
    def fake_post(url, json=None, timeout=None):
        return FakeResponse("Internal Server Error", status_code=500)

    assert send_to_erp("host/svc", {"prms": []}, post=fake_post) is None


def test_erp_call_is_skipped_entirely_when_integration_is_off(monkeypatch):
    """Выключатель должен снимать сам запрос, а не только его последствия."""
    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append(url)
        return FakeResponse([{"Key": "Result", "Value": "OK"}])

    monkeypatch.setattr("ai_assistant.agi.ai_assistant.ERP_INTEGRATION", False)
    assert send_to_erp("host/svc", {"prms": []}, post=fake_post) is None
    assert calls == []


def test_dialog_answer_carries_the_equipment_type_code():
    """Код типа оборудования приходит от сервиса вместе с названием."""
    answer = parse_dialog_response([
        {"Key": "Action", "Value": "Redirect"},
        {"Key": "EquipmentType", "Value": "Холодильники"},
        {"Key": "EquipmentTypeId", "Value": "31"},
    ])
    assert answer.equipment_type_id == "31"


def test_old_answer_without_the_equipment_type_code_still_parses():
    """Сервис прежней сборки этого ключа не присылает — разговор от него не зависит."""
    answer = parse_dialog_response([{"Key": "Action", "Value": "Recognize"}])
    assert answer.equipment_type_id == ""


def test_equipment_request_carries_the_equipment_type_code():
    """Обработчик ERP предпочитает код названию: по названию он искал тип
    строкой, и это единственное место цепочки на совпадении текста."""
    request = build_equipment_request(
        "12345", "холодильник не морозит", "Холодильники", "Холодильники", "31"
    )
    pairs = erp_pairs(request)
    assert pairs["equipmentTypeId"] == "31"
    assert pairs["equipmentTypeName"] == "Холодильники"


def test_equipment_request_without_the_code_sends_only_the_name():
    """Тема не про технику — кода нет, пустой ключ обработчику ничего не скажет."""
    pairs = erp_pairs(build_equipment_request("12345", "жалоба", "", "Жалобы"))
    assert "equipmentTypeId" not in pairs


def test_equipment_is_sent_when_only_the_code_is_known():
    """Название типа со временем станет необязательным — код заменяет его целиком.
    Признак «тема известна» не должен держаться на одном названии."""
    known = DialogAnswer(action="Redirect", text_to_speak="", file_to_playback="",
                         conversation_point="Finished", redirect_exten="7104",
                         equipment_type_id="31")
    assert should_send_equipment(known, already_sent=False) is True


# --- Неопознанный вопрос в базу знаний ERP (UL-17568) -------------------------


def redirect_answer(**kwargs):
    fields = dict(action="Redirect", text_to_speak="", file_to_playback="",
                  conversation_point="Finished", redirect_exten="489")
    fields.update(kwargs)
    return DialogAnswer(**fields)


def test_dialog_answer_carries_the_unrecognized_question_flag():
    answer = parse_dialog_response([
        {"Key": "Action", "Value": "Redirect"},
        {"Key": "RedirectExten", "Value": "489"},
        {"Key": "UnknownQuestion", "Value": "True"},
    ])
    assert answer.unknown_question is True


def test_old_answer_without_the_flag_still_parses():
    """Сервис прежней сборки этого ключа не присылает — разговор от него не зависит."""
    assert parse_dialog_response([{"Key": "Action", "Value": "Recognize"}]).unknown_question is False


def test_unknown_question_is_sent_when_the_bot_found_no_answer():
    answer = redirect_answer(unknown_question=True)
    assert should_send_unknown_question(
        answer, "AskQuestion", "во сколько вы открываетесь", False
    ) is True


def test_silence_transfer_is_not_an_unknown_question():
    """Двойное молчание тоже уводит звонок на сопровождение, но вопроса не было."""
    assert should_send_unknown_question(redirect_answer(), "AskQuestion", "", True) is False


def test_silence_flag_wins_over_anything_the_service_said():
    """Реплики не было — что бы ни пришло в ответе, записывать нечего."""
    assert should_send_unknown_question(
        redirect_answer(unknown_question=True), "AskQuestion", "холодильник", True
    ) is False


def test_empty_recognition_is_not_an_unknown_question():
    """Щелчок в линии, шорох, кашель — распозналось пусто, вопроса нет."""
    assert should_send_unknown_question(
        redirect_answer(unknown_question=True), "AskQuestion", "   ", False
    ) is False


def test_service_failure_is_not_an_unknown_question():
    """Аварийный перевод при отказе речевого сервиса: ответа нет вовсе."""
    assert should_send_unknown_question(None, "AskQuestion", "холодильник не морозит", False) is False


def test_found_answer_is_not_an_unknown_question():
    known = redirect_answer(redirect_exten="7104", equipment_type="Холодильники",
                            equipment_type_id="31", telephone_direction_id="52")
    assert should_send_unknown_question(known, "Confirm", "да", False) is False


def test_answer_at_the_confirmation_point_is_never_an_unknown_question():
    """«Да»/«нет» — это ответ на уточнение бота, а не вопрос клиента.

    Даже если сессия разговора на сервисе потерялась и он увёл звонок на общее
    сопровождение, отправлять отсюда нечего: сам вопрос прозвучал раньше и
    тогда же был найден в базе.
    """
    assert should_send_unknown_question(
        redirect_answer(unknown_question=True), "Confirm", "да", False
    ) is False


def test_nothing_is_sent_while_the_bot_keeps_talking():
    """Бот продолжает разговор — итог звонка ещё не известен."""
    listening = DialogAnswer(action="Recognize", text_to_speak="", file_to_playback="",
                             conversation_point="AskQuestion", redirect_exten="",
                             unknown_question=True)
    assert should_send_unknown_question(listening, "AskQuestion", "холодильник", False) is False


def test_unknown_request_carries_the_question_and_the_case():
    request = build_unknown_request("12345", "во сколько вы открываетесь")
    pairs = erp_pairs(request)
    assert pairs["eventType"] == "AiAssistantUnknown"
    assert pairs["documentId"] == "12345"
    assert pairs["recognizedText"] == "во сколько вы открываетесь"


def test_unknown_question_obeys_the_erp_switch(monkeypatch):
    """Пятое событие подчиняется тому же выключателю, что и остальные четыре."""
    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append(url)
        return FakeResponse([{"Key": "Result", "Value": "OK"}])

    monkeypatch.setattr("ai_assistant.agi.ai_assistant.ERP_INTEGRATION", False)
    body = build_unknown_request("12345", "во сколько вы открываетесь")
    assert send_to_erp("host/svc", body, post=fake_post) is None
    assert calls == []


def test_unknown_question_is_reported_from_the_call_flow():
    """Решение принимается на том же шаге, что и сообщение о теме разговора.

    `_main()` требует живого канала Asterisk, поэтому проверяем по исходнику:
    без вызова из apply() чистая функция осталась бы мёртвым кодом.
    """
    source_path = pathlib.Path(__file__).resolve().parents[1] / "agi" / "ai_assistant.py"
    source = source_path.read_text(encoding="utf-8")
    assert "report_unknown_question(answer)" in source
    assert "build_unknown_request(" in source


# --- Причина отказа нашей стороны (UL-18797) ----------------------------------
#
# Обратный звонок положен клиенту только тогда, когда он остался без ответа по
# нашей вине. Причину называет этот скрипт и кладёт её в переменную канала:
# скрипт последней воли поднимается отдельным процессом и нашей памяти не
# видит, а при обрыве канала мы умираем мгновенно (SIGHUP, SIG_DFL).
#
# `_main()` требует живого канала Asterisk, поэтому проверяем по исходнику —
# тем же способом, что и остальные переменные канала.

KNOWN_REASONS = {
    "REASON_SERVICE_UNAVAILABLE",
    "REASON_SCRIPT_ERROR",
    "REASON_CALL_TIMEOUT",
    "REASON_SPEECH_FAILED",
}


def reason_calls():
    """Все места, где скрипт называет причину: (объемлющая функция, константа)."""
    source_path = pathlib.Path(__file__).resolve().parents[1] / "agi" / "ai_assistant.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    found = []

    def visit(node, function_name):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef):
                visit(child, child.name)
                continue
            if isinstance(child, ast.Call) and getattr(child.func, "id", "") == "set_failure_reason":
                argument = child.args[0] if child.args else None
                found.append((function_name, getattr(argument, "id", "")))
            visit(child, function_name)

    visit(tree, "<module>")
    return found


def test_reason_texts_are_short_and_russian():
    """Их читает оператор в истории обращения, а не программист в логе."""
    for reason in (REASON_SERVICE_UNAVAILABLE, REASON_SCRIPT_ERROR,
                   REASON_CALL_TIMEOUT, REASON_SPEECH_FAILED):
        assert reason.strip()
        assert len(reason) <= 60
        assert any("а" <= letter <= "я" for letter in reason.lower())


def test_service_failover_names_the_reason():
    """Речевой сервис не ответил или оборвался поток распознавания."""
    assert ("failover_to_support", "REASON_SERVICE_UNAVAILABLE") in reason_calls()


def test_unhandled_exception_names_the_reason():
    """Упал наш скрипт — клиент остался без ответа не по своей воле."""
    assert ("_main", "REASON_SCRIPT_ERROR") in reason_calls()


def test_call_timeout_names_the_reason():
    """Разговор упёрся в предельную длительность (CALL_TIMEOUT_S)."""
    assert ("_main", "REASON_CALL_TIMEOUT") in reason_calls()


def test_failed_playback_names_the_reason():
    """Ответ не удалось озвучить — клиент услышал тишину вместо ответа."""
    assert ("speak", "REASON_SPEECH_FAILED") in reason_calls()


def test_reason_is_set_only_on_our_own_failures():
    """Клиент, положивший трубку, причиной не является: там переменная пуста.

    Причин ровно столько, сколько путей отказа нашей стороны; появится новая —
    её надо осознанно внести в список, а не выставить мимоходом.
    """
    for _, reason in reason_calls():
        assert reason in KNOWN_REASONS


def test_successful_playback_clears_the_reason():
    """Неудача озвучки перестаёт быть причиной, как только фраза прозвучала.

    Иначе один сорвавшийся синтез в середине разговора увёл бы в ПЦК звонок,
    в котором клиент всё-таки получил ответ.
    """
    source_path = pathlib.Path(__file__).resolve().parents[1] / "agi" / "ai_assistant.py"
    source = source_path.read_text(encoding="utf-8")
    assert "clear_failure_reason()" in source


def test_reason_is_published_to_the_channel_variable():
    source_path = pathlib.Path(__file__).resolve().parents[1] / "agi" / "ai_assistant.py"
    source = source_path.read_text(encoding="utf-8")
    assert "set_var(FAILURE_REASON_VAR, reason)" in source


# --- Набранный номер и записанные аудио (UL-17568) ----------------------------
#
# Галочка «Виртуальный AI помощник» стоит на номерах разных групп линий, и набор
# фраз сервис выбирает по набранному номеру. У части фраз вместо синтеза стоит
# заранее записанный файл: он уже лежит на станции, скачивать его неоткуда.


def dialog_pairs(request):
    return {item["Key"]: item["Value"] for item in request["prms"]}


def test_dialog_request_carries_the_dialed_number():
    """По нему сервис выбирает фразы и голос — тем же ключом, что и события ERP."""
    request = build_dialog_request("call-1", "AskQuestion", "привет", False, "74951468847")

    assert dialog_pairs(request)["dialedNumber"] == "74951468847"


def test_dialog_request_without_a_dialed_number_still_works():
    """Сервис без номера отвечает набором по умолчанию, а не падает."""
    assert dialog_pairs(build_dialog_request("call-1", "Start", "", False))["dialedNumber"] == ""


def test_dialog_answer_carries_the_recorded_file_flag():
    answer = parse_dialog_response([
        {"Key": "Action", "Value": "Recognize"},
        {"Key": "FileToPlayback", "Value": "VoicesOKK\\voice-a\\2_spich.wav"},
        {"Key": "FileIsOnStation", "Value": "True"},
        {"Key": "Voice", "Value": "kseniya"},
    ])

    assert answer.file_is_on_station is True
    assert answer.voice == "kseniya"


def test_old_answer_without_the_recorded_file_flag_still_parses():
    """Новый скрипт со старым сервисом обязан вести себя как раньше: признака
    нет — файл скачивается из /tts, как и всегда."""
    answer = parse_dialog_response([
        {"Key": "Action", "Value": "Recognize"},
        {"Key": "FileToPlayback", "Value": "aia_abc"},
    ])

    assert answer.file_is_on_station is False
    assert answer.voice == ""
    assert plays_from_station(answer) is False


def test_recorded_file_is_played_without_downloading_anything():
    answer = DialogAnswer(
        action="Recognize", text_to_speak="Здравствуйте",
        file_to_playback="VoicesOKK\\voice-a\\2_spich.wav",
        conversation_point="AskQuestion", redirect_exten="", file_is_on_station=True,
    )

    assert plays_from_station(answer) is True


def test_flag_without_a_file_is_not_a_recorded_file():
    """Путь пустой, а флаг включён — синтезируем, как обычно."""
    answer = DialogAnswer(
        action="Recognize", text_to_speak="Здравствуйте", file_to_playback="",
        conversation_point="AskQuestion", redirect_exten="", file_is_on_station=True,
    )

    assert plays_from_station(answer) is False


@pytest.mark.parametrize("raw,expected", [
    ("VoicesOKK\\voice-a\\2_spich.wav",
     "/var/lib/asterisk/sounds/audioivr20/VoicesOKK/voice-a/2_spich"),
    ("AsterBotGL\\Actual.wav", "/var/lib/asterisk/sounds/audioivr20/AsterBotGL/Actual"),
    ("AsterBotGL/Actual.WAV", "/var/lib/asterisk/sounds/audioivr20/AsterBotGL/Actual"),
    ("AsterBotGL/Actual", "/var/lib/asterisk/sounds/audioivr20/AsterBotGL/Actual"),
    ("  AsterBotGL\\Actual.wav  ", "/var/lib/asterisk/sounds/audioivr20/AsterBotGL/Actual"),
])
def test_station_path_is_given_to_asterisk_the_way_it_expects_it(raw, expected):
    """Путь из справочника относительный, и папку к нему приклеивает скрипт —
    так же делает боевой бот (recosintsite_V2.py, audio_path_rec). Разделители
    прямые, расширение Астериск подставляет сам: с ним он искал бы файл
    «Actual.wav.wav» и не нашёл бы, промолчав вместо приветствия."""
    assert station_playback_path(raw) == expected


def test_absolute_station_path_is_left_alone():
    """Абсолютный путь задан осознанно — приклеивать к нему папку значит
    гарантированно его сломать."""
    assert station_playback_path("/var/lib/asterisk/sounds/asterbot/Hello.wav") == \
        "/var/lib/asterisk/sounds/asterbot/Hello"


def test_empty_station_path_stays_empty():
    """Пустой путь не должен превращаться в саму папку: Астериск попытался бы
    её проиграть."""
    assert station_playback_path("") == ""


def test_tts_asks_for_the_voice_of_the_group():
    """Иначе фразу второй группы синтезировали бы голосом первой, а имя файла
    станция запомнила бы со своей подписью — то есть навсегда."""
    assert tts_params("здравствуйте", "kseniya") == {
        "text": "здравствуйте", "voice_name": "kseniya"
    }


def test_tts_without_a_voice_asks_the_service_to_decide():
    """Старый сервис голоса не присылает — синтез идёт тем, что настроено у него."""
    assert tts_params("здравствуйте", "") == {"text": "здравствуйте"}


def test_the_script_sends_the_dialed_number_to_the_dialog():
    """`_main()` требует живого канала Asterisk, поэтому проверяем по исходнику:
    без этого аргумента сервис не отличит группы линий друг от друга."""
    source_path = pathlib.Path(__file__).resolve().parents[1] / "agi" / "ai_assistant.py"
    source = source_path.read_text(encoding="utf-8")

    assert 'build_dialog_request(linked_id, state["point"], text, silence, dialed_number)' in source


def test_the_script_plays_the_recorded_file_instead_of_downloading_it():
    source_path = pathlib.Path(__file__).resolve().parents[1] / "agi" / "ai_assistant.py"
    source = source_path.read_text(encoding="utf-8")

    assert "if plays_from_station(answer):" in source
    assert "station_playback_path(answer.file_to_playback)" in source
