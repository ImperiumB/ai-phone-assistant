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


def test_content_hash_is_parsed_from_the_payload():
    """Отпечаток содержимого считает ERP; сервис его только хранит и возвращает."""
    payload = minimal_payload()
    payload["content_hash"] = "0123456789abcdef0123456789abcdef"
    feed = parse_feed(payload)
    assert feed.content_hash == "0123456789abcdef0123456789abcdef"


def test_payload_without_content_hash_is_applied():
    """Обработчик прежней версии отпечаток не присылает.

    Сделать поле обязательным значит отвергнуть первую же посылку от старого
    обработчика и оставить бота на вчерашней базе знаний.
    """
    feed = parse_feed(minimal_payload())
    assert feed.content_hash == ""
    assert len(feed.records) == 1


def test_confirm_not_heard_comes_from_settings_when_erp_sends_it():
    """Переспрос в точке подтверждения правится там же, где остальные фразы."""
    payload = minimal_payload()
    payload["settings"]["confirm_not_heard"] = "Повторите, пожалуйста: да или нет"
    feed = parse_feed(payload)
    assert feed.phrases.confirm_not_heard == "Повторите, пожалуйста: да или нет"


# --- Группы линий (UL-17568) --------------------------------------------------
#
# Галочка «Виртуальный AI помощник» может стоять на номерах разных групп линий,
# а у каждой группы свои фразы, свой голос и свои записанные аудио. База знаний
# при этом общая — это решение заказчика: темы про ремонт техники не зависят от
# того, на какой номер позвонили.


def group(**overrides):
    payload = {
        "line_group_id": 9060,
        "phones": ["74951468847"],
        "voice": "kseniya",
        "greeting": "Здравствуйте, это частный мастер",
        "misrecognition": "Повторите, пожалуйста",
        "transfer": "Соединяю с мастером",
        "silence": "Алло, вы здесь?",
        "wrong_guess": "А что тогда вас интересует?",
        "confirm_not_heard": "Скажите да или нет, пожалуйста",
        "positive_answers": ["да", "ага"],
        "negative_answers": ["нет"],
        "use_recorded_audio": False,
        "greeting_path": "",
        "misrecognition_path": "",
        "transfer_path": "",
        "silence_path": "",
        "wrong_guess_path": "",
        "confirm_not_heard_path": "",
    }
    payload.update(overrides)
    return payload


def payload_with_groups(*groups):
    payload = minimal_payload()
    payload["line_groups"] = list(groups)
    return payload


def test_line_groups_are_parsed_with_their_phones_and_phrases():
    feed = parse_feed(payload_with_groups(group()))

    assert len(feed.line_groups) == 1
    parsed = feed.line_groups[0]
    assert parsed.line_group_id == 9060
    assert parsed.phones == ["74951468847"]
    assert parsed.voice == "kseniya"
    assert parsed.phrases.greeting == "Здравствуйте, это частный мастер"
    assert parsed.phrases.confirm_not_heard == "Скажите да или нет, пожалуйста"
    assert parsed.positive_answers == ["да", "ага"]


def test_payload_without_line_groups_is_applied_as_before():
    """Рассинхрон версий не должен оставлять бота без базы знаний.

    Обработчик прежней сборки массива не присылает вовсе — посылка обязана
    примениться на одном наборе, как до разделения по группам.
    """
    feed = parse_feed(minimal_payload())

    assert feed.line_groups == []
    assert len(feed.records) == 1
    assert feed.phrases.greeting == "Здравствуйте, чем могу помочь?"


def test_unfilled_phrase_of_a_group_falls_back_to_the_default_set():
    """Ненастроенная фраза одной группы не должна отвергать посылку целиком.

    Лучше поздороваться чужой фразой, чем молчать в трубку, — то же правило,
    по которому неопознанный номер получает набор по умолчанию.
    """
    feed = parse_feed(payload_with_groups(group(greeting="", positive_answers=[])))

    parsed = feed.line_groups[0]
    assert parsed.phrases.greeting == "Здравствуйте, чем могу помочь?"
    assert parsed.positive_answers == ["да", "так"]
    assert parsed.phrases.transfer == "Соединяю с мастером"  # своё не затирается


def test_group_without_phones_is_dropped():
    """По набранному номеру такую группу всё равно не найти — она только
    заставила бы прогрев синтеза молоть лишний голос."""
    feed = parse_feed(payload_with_groups(group(phones=[])))

    assert feed.line_groups == []


def test_recorded_audio_paths_are_ignored_while_the_flag_is_off():
    """Пути в справочнике могут быть заполнены заранее, до включения галочки."""
    feed = parse_feed(payload_with_groups(group(
        use_recorded_audio=False, greeting_path="VoicesOKK\\voice-a\\2_spich.wav"
    )))

    assert feed.line_groups[0].audio_files == {}


def test_recorded_audio_paths_are_kept_when_the_flag_is_on():
    feed = parse_feed(payload_with_groups(group(
        use_recorded_audio=True,
        greeting_path="VoicesOKK\\voice-a\\2_spich.wav",
        transfer_path="AsterBotGL\\Actual.wav",
    )))

    assert feed.line_groups[0].audio_files == {
        "greeting": "VoicesOKK\\voice-a\\2_spich.wav",
        "transfer": "AsterBotGL\\Actual.wav",
    }


def test_empty_path_with_the_flag_on_is_not_a_recorded_file():
    """Ненастроенная фраза — это не поломка: её просто синтезируют, как обычно."""
    feed = parse_feed(payload_with_groups(group(use_recorded_audio=True, greeting_path="   ")))

    assert feed.line_groups[0].audio_files == {}


def test_the_default_set_has_its_own_recorded_audio_too():
    """`settings` — это первая группа, и записанные аудио у неё такие же свои."""
    payload = minimal_payload()
    payload["settings"]["use_recorded_audio"] = True
    payload["settings"]["silence_path"] = "AsterBotGL\\Alo.wav"

    feed = parse_feed(payload)

    assert feed.audio_files == {"silence": "AsterBotGL\\Alo.wav"}


def test_old_payload_without_recorded_audio_fields_has_none():
    assert parse_feed(minimal_payload()).audio_files == {}


def test_broken_line_groups_section_is_rejected():
    """Мусор вместо массива — повод отвергнуть посылку, а не гадать."""
    payload = minimal_payload()
    payload["line_groups"] = "9060"
    with pytest.raises(FeedError):
        parse_feed(payload)


def test_confirm_not_heard_falls_back_to_the_service_default():
    """Поля в справочнике ERP пока нет, и посылка без него обязана применяться.

    Обязательным это поле делать нельзя: тогда первая же посылка от прежнего
    обработчика отвергается целиком, и сервис остаётся с устаревшей базой
    знаний из-за одной ненастроенной фразы.
    """
    from ai_assistant.service.dialog import DEFAULT_CONFIRM_NOT_HEARD

    feed = parse_feed(minimal_payload())
    assert feed.phrases.confirm_not_heard == DEFAULT_CONFIRM_NOT_HEARD
