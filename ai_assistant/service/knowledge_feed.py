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
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ai_assistant.service.dialog import (
    DEFAULT_CONFIRM_NOT_HEARD,
    PHRASE_SLOTS,
    SCENARIO_DIRECTION,
    LineProfile,
    Phrases,
)
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
    #: Отпечаток содержимого, посчитанный на стороне ERP. Сервис его не
    #: пересчитывает: заставить C# и Python сериализовать JSON побайтово
    #: одинаково ради сравнения — гиблое дело, а сравнивать надо строго то же
    #: самое, что считал обработчик. Пусто — отпечатка не прислали.
    content_hash: str = ""
    #: Заранее записанные аудио набора по умолчанию, по именам фраз.
    audio_files: Dict[str, str] = field(default_factory=dict)
    #: Наборы остальных групп линий. Пусто — обработчик прежней сборки массива
    #: не присылает вовсе, и весь бот живёт на одном наборе, как раньше.
    line_groups: List[LineProfile] = field(default_factory=list)


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


def _parse_phrases(
    source: Dict[str, Any], where: str, defaults: Optional[Phrases] = None
) -> Phrases:
    """Служебные фразы одного набора.

    `defaults` передаётся для группы линий: незаполненная там фраза берётся из
    набора по умолчанию, а не отвергает посылку целиком. Одна ненастроенная
    фраза в третьей по счёту группе иначе оставила бы без базы знаний весь
    бот — то же правило, по которому неопознанный номер получает чужой набор:
    лучше поздороваться чужой фразой, чем молчать в трубку.
    """

    def required(key: str) -> str:
        value = str(source.get(key) or "").strip()
        if value:
            return value
        if defaults is not None:
            return getattr(defaults, key)
        return _required_text(source, key, where)

    return Phrases(
        greeting=required("greeting"),
        misrecognition=required("misrecognition"),
        transfer=required("transfer"),
        silence=required("silence"),
        wrong_guess=required("wrong_guess"),
        # Необязательное, в отличие от остальных: своего поля в справочнике
        # группы линий у переспроса пока нет, и обработчик его не присылает.
        # Сделать его обязательным значит отвергнуть целиком первую же
        # посылку от прежнего обработчика — сервис останется с устаревшей
        # базой знаний из-за одной ненастроенной фразы. Когда поле в ERP
        # заведут, оно подхватится здесь само, без правки сервиса.
        confirm_not_heard=(
            str(source.get("confirm_not_heard") or "").strip()
            or (defaults.confirm_not_heard if defaults is not None else DEFAULT_CONFIRM_NOT_HEARD)
        ),
    )


def _parse_audio_files(source: Dict[str, Any]) -> Dict[str, str]:
    """Заранее записанные аудио набора: имя фразы -> путь на станции.

    Пути живут в справочнике и при выключенной галочке: их заполняют заранее.
    Пустой путь при включённой галочке — тоже не поломка, а просто
    ненастроенная фраза, её синтезируют как обычно. И в том, и в другом случае
    в словарь она не попадает, а всё, что в нём есть, играется файлом.
    """
    if not source.get("use_recorded_audio"):
        return {}
    files = {}
    for slot in PHRASE_SLOTS:
        path = str(source.get(slot + "_path") or "").strip()
        if path:
            files[slot] = path
    return files


def _parse_line_groups(
    payload: Dict[str, Any], defaults: Phrases, default_answers: Dict[str, List[str]]
) -> List[LineProfile]:
    raw = payload.get("line_groups")
    if raw is None:
        # Обработчик прежней сборки массива не присылает вовсе. Требовать его
        # значит при рассинхроне версий оставить бота без базы знаний совсем —
        # а это хуже, чем один набор фраз на все группы.
        return []
    if not isinstance(raw, list):
        raise FeedError("Раздел line_groups должен быть массивом")

    groups = []
    for item in raw:
        if not isinstance(item, dict):
            raise FeedError("Группа линий должна быть объектом")
        where = "группа линий {0}".format(item.get("line_group_id", "без кода"))
        phones = _clean_list(item.get("phones"))
        if not phones:
            # По набранному номеру такую группу не найти никогда, а прогрев
            # синтеза из-за неё молол бы лишний голос.
            log.warning("%s: нет ни одного номера, набор пропущен", where)
            continue
        groups.append(LineProfile(
            phrases=_parse_phrases(item, where, defaults),
            voice=str(item.get("voice") or "").strip(),
            audio_files=_parse_audio_files(item),
            positive_answers=(
                _clean_list(item.get("positive_answers")) or list(default_answers["positive"])
            ),
            negative_answers=(
                _clean_list(item.get("negative_answers")) or list(default_answers["negative"])
            ),
            phones=phones,
            line_group_id=_optional_int(item.get("line_group_id"), "line_group_id", where),
        ))
    return groups


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

    phrases = _parse_phrases(settings, "настройки")

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
        # Необязательное: обработчик прежней версии отпечаток не присылает, а
        # отвергнуть из-за этого целую посылку значит оставить бота на вчерашней
        # базе знаний. Пустой отпечаток обработчик считает поводом прислать
        # справочники — то есть худшее, что даёт его отсутствие, это лишняя
        # посылка, а не потерянное обновление.
        content_hash=str(payload.get("content_hash") or "").strip(),
        audio_files=_parse_audio_files(settings),
        line_groups=_parse_line_groups(payload, phrases, answers),
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
