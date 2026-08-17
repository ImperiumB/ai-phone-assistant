import pytest

from ai_assistant.service.knowledge_feed import FeedError, parse_feed


def minimal_payload():
    return {
        "generated_at": "2026-08-14T15:00:00",
        "settings": {
            "line_group_id": 1,
            "voice": "eugene",
            "greeting": "Здравствуйте, чем могу помочь?",
            "misrecognition": "Попробуйте переформулировать свой вопрос, пожалуйста",
            "transfer": "Минуту, перевожу ваш звонок на специалиста",
            "silence": "Вы меня слышите?",
            "wrong_guess": "Тогда подскажите, пожалуйста, что вас интересует?",
            "positive_answers": ["да", "так"],
            "negative_answers": ["нет", "не то"],
        },
        "records": [
            {
                "id": 1,
                "question": "стиральная машина не отжимает",
                "phrases": ["стиралка сломалась", "не крутит бельё"],
                "clarifying_question": "Речь о стиральной машине?",
                "positive_reply": "Соединяю со специалистом",
                "equipment_type": "Стиральные машины",
                "equipment_type_id": 17,
                "telephone_direction_id": 53,
                "redirect_exten": "7105",
            }
        ],
    }


def test_records_are_parsed_with_their_phrases():
    feed = parse_feed(minimal_payload())
    assert len(feed.records) == 1
    record = feed.records[0]
    assert record.id == 1
    assert record.question == "стиральная машина не отжимает"
    assert record.question_variants == ["стиралка сломалась", "не крутит бельё"]
    assert record.redirect_exten == "7105"
    assert record.telephone_direction_id == 53


def test_answers_come_from_settings_not_from_records():
    """Списки согласия и отказа вынесены в настройки группы линий.

    В ТЗ они лежали в каждой записи, но на практике оказались одинаковыми
    во всех — держать 33 копии одного списка значит гарантированно их
    рассинхронизировать.
    """
    feed = parse_feed(minimal_payload())
    record = feed.records[0]
    assert record.positive_answers == ["да", "так"]
    assert record.negative_answers == ["нет", "не то"]


def test_phrases_are_parsed():
    feed = parse_feed(minimal_payload())
    assert feed.phrases.greeting == "Здравствуйте, чем могу помочь?"
    assert feed.phrases.wrong_guess == "Тогда подскажите, пожалуйста, что вас интересует?"
    assert feed.voice == "eugene"
    assert feed.line_group_id == 1


def test_scenario_is_always_direction_redirect():
    feed = parse_feed(minimal_payload())
    assert feed.records[0].scenario == "redirect_direction"


def test_equipment_type_id_is_parsed():
    """Код типа оборудования — единственный способ проставить технику в
    обращении, не угадывая её по названию строкой."""
    feed = parse_feed(minimal_payload())
    assert feed.records[0].equipment_type_id == 17
    assert feed.records[0].equipment_type == "Стиральные машины"


def test_record_without_equipment_type_id_is_allowed():
    """Тип оборудования в записи необязателен: часть тем не про технику вовсе."""
    payload = minimal_payload()
    del payload["records"][0]["equipment_type_id"]
    feed = parse_feed(payload)
    assert feed.records[0].equipment_type_id == 0


def test_payload_without_records_is_rejected():
    payload = minimal_payload()
    payload["records"] = []
    with pytest.raises(FeedError):
        parse_feed(payload)


def test_payload_without_settings_is_rejected():
    payload = minimal_payload()
    del payload["settings"]
    with pytest.raises(FeedError):
        parse_feed(payload)


def test_record_without_question_is_rejected():
    payload = minimal_payload()
    del payload["records"][0]["question"]
    with pytest.raises(FeedError):
        parse_feed(payload)


def test_record_without_clarifying_question_is_rejected():
    """Такие записи фильтрует обработчик — до сервиса они доходить не должны."""
    payload = minimal_payload()
    payload["records"][0]["clarifying_question"] = ""
    with pytest.raises(FeedError):
        parse_feed(payload)


def test_missing_greeting_is_rejected():
    payload = minimal_payload()
    payload["settings"]["greeting"] = ""
    with pytest.raises(FeedError):
        parse_feed(payload)


def test_empty_phrases_of_a_record_are_allowed():
    """Запись может жить на одной каноничной формулировке, хоть это и хуже."""
    payload = minimal_payload()
    payload["records"][0]["phrases"] = []
    feed = parse_feed(payload)
    assert feed.records[0].question_variants == []


def test_blank_phrases_are_dropped():
    payload = minimal_payload()
    payload["records"][0]["phrases"] = ["стиралка сломалась", "", "   "]
    feed = parse_feed(payload)
    assert feed.records[0].question_variants == ["стиралка сломалась"]


def test_saved_feed_is_read_back(tmp_path):
    from ai_assistant.service.knowledge_feed import load_feed, save_feed

    target = str(tmp_path / "feed.json")
    save_feed(minimal_payload(), target)
    restored = load_feed(target)

    assert restored is not None
    assert parse_feed(restored).records[0].question == "стиральная машина не отжимает"


def test_load_returns_none_when_file_is_absent(tmp_path):
    from ai_assistant.service.knowledge_feed import load_feed

    assert load_feed(str(tmp_path / "нет-такого.json")) is None


def test_load_returns_none_on_broken_file(tmp_path):
    """Битую копию нельзя применять и нельзя падать из-за неё при старте."""
    from ai_assistant.service.knowledge_feed import load_feed

    target = tmp_path / "feed.json"
    target.write_text("{это не json", encoding="utf-8")
    assert load_feed(str(target)) is None


def test_save_leaves_no_temporary_file(tmp_path):
    from ai_assistant.service.knowledge_feed import save_feed

    target = tmp_path / "feed.json"
    save_feed(minimal_payload(), str(target))
    assert list(tmp_path.glob("*.tmp")) == []


def test_save_creates_missing_directory(tmp_path):
    from ai_assistant.service.knowledge_feed import load_feed, save_feed

    target = str(tmp_path / "глубже" / "feed.json")
    save_feed(minimal_payload(), target)
    assert load_feed(target) is not None
