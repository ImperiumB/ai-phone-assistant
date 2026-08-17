"""Разбор посылки со справочниками ERP.

ERP толкает содержимое справочников POST-запросом; здесь оно превращается в
те же объекты, которыми сервис пользовался, пока база знаний лежала в файле.

Посылка применяется целиком или не применяется вовсе: наполовину обновлённая
база знаний хуже устаревшей, потому что расхождение в ней не видно.
"""
import json
import logging
import os
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ai_assistant.service.dialog import SCENARIO_DIRECTION, Phrases
from ai_assistant.service.knowledge import KnowledgeRecord

log = logging.getLogger("aia.feed")


class FeedError(Exception):
    """Посылка непригодна и применяться не должна."""


@dataclass
class ParsedFeed:
    generated_at: str
    records: List[KnowledgeRecord]
    phrases: Phrases
    voice: str
    line_group_id: int


def _clean_list(raw: Any) -> List[str]:
    if not raw:
        return []
    if not isinstance(raw, list):
        raise FeedError("Ожидался список, получено: {0}".format(type(raw).__name__))
    return [str(item).strip() for item in raw if str(item).strip()]


def _required_text(source: Dict[str, Any], key: str, where: str) -> str:
    value = str(source.get(key) or "").strip()
    if not value:
        raise FeedError("{0}: не заполнено обязательное поле {1!r}".format(where, key))
    return value


def _optional_int(raw: Any, key: str, where: str) -> int:
    """Целое из посылки. Мусор в числовом поле — повод отвергнуть всю посылку,
    а не молча подставить ноль: код оборудования с опечаткой проставит в
    обращении чужую технику, и по обращению этого уже не увидеть."""
    if raw is None or raw == "":
        return 0
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise FeedError("{0}: поле {1!r} должно быть числом, получено {2!r}".format(where, key, raw))


def _parse_record(raw: Dict[str, Any], answers: Dict[str, List[str]]) -> KnowledgeRecord:
    where = "запись {0}".format(raw.get("id", "без кода"))
    return KnowledgeRecord(
        id=_optional_int(raw.get("id"), "id", where),
        question=_required_text(raw, "question", where),
        question_variants=_clean_list(raw.get("phrases")),
        clarifying_question=_required_text(raw, "clarifying_question", where),
        positive_answers=list(answers["positive"]),
        negative_answers=list(answers["negative"]),
        positive_reply=str(raw.get("positive_reply") or "").strip(),
        # Единственный сценарий на этом этапе — перевод по телефонному
        # направлению. Номер приёма приходит из справочника направлений.
        scenario=SCENARIO_DIRECTION,
        equipment_type=str(raw.get("equipment_type") or "").strip(),
        # Код типа оборудования из справочника ERP. Пока его не было, обработчик
        # искал тип по названию строкой — единственное место всей цепочки, где
        # связь держалась на совпадении текста.
        equipment_type_id=_optional_int(
            raw.get("equipment_type_id"), "equipment_type_id", where
        ),
        telephone_direction_id=_optional_int(
            raw.get("telephone_direction_id"), "telephone_direction_id", where
        ),
        redirect_exten=str(raw.get("redirect_exten") or "").strip(),
    )


def parse_feed(payload: Dict[str, Any]) -> ParsedFeed:
    if not isinstance(payload, dict):
        raise FeedError("Посылка должна быть объектом")

    settings = payload.get("settings")
    if not isinstance(settings, dict):
        raise FeedError("В посылке нет раздела settings")

    raw_records = payload.get("records")
    if not isinstance(raw_records, list) or not raw_records:
        raise FeedError("В посылке нет ни одной записи базы знаний")

    phrases = Phrases(
        greeting=_required_text(settings, "greeting", "настройки"),
        misrecognition=_required_text(settings, "misrecognition", "настройки"),
        transfer=_required_text(settings, "transfer", "настройки"),
        silence=_required_text(settings, "silence", "настройки"),
        wrong_guess=_required_text(settings, "wrong_guess", "настройки"),
    )

    answers = {
        "positive": _clean_list(settings.get("positive_answers")),
        "negative": _clean_list(settings.get("negative_answers")),
    }
    if not answers["positive"]:
        raise FeedError("настройки: пустой список вариантов согласия")

    records = [_parse_record(raw, answers) for raw in raw_records]

    return ParsedFeed(
        generated_at=str(payload.get("generated_at") or ""),
        records=records,
        phrases=phrases,
        voice=str(settings.get("voice") or "").strip(),
        line_group_id=_optional_int(settings.get("line_group_id"), "line_group_id", "настройки"),
    )


def save_feed(payload: Dict[str, Any], path: str) -> None:
    """Сохранить посылку на диск атомарно.

    Копия нужна, чтобы сервис поднимался сразу после перезапуска: он встаёт
    за минуту, а робот приносит данные раз в десять. Имя временного файла
    уникально — на той же грабле уже спотыкались в кэше синтеза.
    """
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    tmp_path = "{0}.{1}.tmp".format(path, uuid.uuid4().hex)
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    finally:
        try:
            os.remove(tmp_path)
        except FileNotFoundError:
            pass  # обычный случай: файл уже переименован


def load_feed(path: str) -> Optional[Dict[str, Any]]:
    """Прочитать копию. Отсутствие или порча копии — не повод падать при старте."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return None
    except Exception:
        log.exception("Копия посылки повреждена и будет проигнорирована: %s", path)
        return None
