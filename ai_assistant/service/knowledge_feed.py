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
from typing import Any, Dict, List, Optional, Tuple

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
    #: Номер приёма ТН 17 «Сопровождение» — куда уезжает звонок во всех
    #: непонятных ситуациях. Приезжает в посылке, а не зашит в сервис: правят
    #: его в справочнике направлений. Пусто — номер у ТН 17 не заполнен либо
    #: обработчик прежней сборки поля не присылает; тогда остаётся прежний
    #: номер из настроек сервиса.
    support_exten: str = ""
    #: Раздел settings — такая же группа линий, и она тоже может оказаться
    #: группой частных мастеров.
    is_private_master: bool = False


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
            is_private_master=bool(item.get("is_private_master")),
        ))
    return groups


def _parse_record(raw: Dict[str, Any], answers: Dict[str, List[str]]) -> KnowledgeRecord:
    where = "запись {0}".format(raw.get("id", "без кода"))
    return KnowledgeRecord(
        id=_optional_int(raw.get("id"), "id", where),
        question=_required_text(raw, "question", where),
        question_variants=_clean_list(raw.get("phrases")),
        # Необязателен намеренно. Пустой уточняющий вопрос — это не брак
        # посылки, а тема, которую уточнять не надо: клиент прямым текстом
        # просит человека, и переспрашивать его значит злить (UL-19020,
        # разбор аналитика КЦ 17.09.2026 — четыре таких звонка за день).
        #
        # Такую запись движок диалога переводит сразу на сопровождение —
        # см. ветку «уточнять нечего» в dialog.py. Мусор сюда не попадает:
        # обработчик 15424 отсекает неразобранные реплики по IS_FROM_BOT.
        clarifying_question=str(raw.get("clarifying_question") or "").strip(),
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
        # Второй номер того же направления — для звонков с линий частных
        # мастеров. Необязателен: отдела частных мастеров у направления может
        # не быть вовсе, и тогда такой звонок уходит на сопровождение.
        redirect_exten_pm=str(raw.get("redirect_exten_pm") or "").strip(),
        # Замки записи. Необязательны: посылка от ERP без этого поля (до
        # 12.11.2026) применяется как раньше, просто без замков.
        gates=_clean_list(raw.get("gates")),
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

    support_exten = str(payload.get("support_exten") or "").strip()
    if not support_exten:
        # Отвергать посылку из-за незаполненного номера нельзя: бот остался бы
        # с устаревшей базой знаний. Но и молчать нельзя — без этой строки
        # непонятно, почему непонятые звонки уезжают на прежний номер сервиса,
        # а не на ТН 17.
        log.warning(
            "В посылке нет номера сопровождения (support_exten): непонятные "
            "звонки продолжат уезжать на прежний номер из настроек сервиса"
        )

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
        support_exten=support_exten,
        is_private_master=bool(settings.get("is_private_master")),
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


#: Сколько посылок держим в архиве. Десять это примерно полтора часа работы
#: робота или около двух недель правок аналитика, если он правит базу редко.
FEED_ARCHIVE_KEEP = 10


def archive_feed(payload: Dict[str, Any], cache_path: str, content_hash: str) -> str:
    """Сложить копию принятой посылки в архив рядом с кэшем.

    На диске лежала ТОЛЬКО последняя копия, и это закрывало разбор прошлого:
    реплей волны, прошедшей две недели назад, шёл на нынешней базе знаний, то
    есть проверял не то, что тогда отвечало на звонки. Правка данных трижды
    меняла поведение бота (короткие формы в sql/20, перенос швейных машин,
    формулировки оператора), и каждый раз восстановить прежнюю базу было нечем.

    Имя файла несёт отпечаток содержимого: по нему посылку из журнала разбора
    находят однозначно, даже если robot принёс её трижды.
    """
    directory = os.path.join(os.path.dirname(os.path.abspath(cache_path)) or ".", "feed_archive")
    try:
        os.makedirs(directory, exist_ok=True)
        stamp = str(payload.get("generated_at") or "").replace(":", "-").replace(" ", "_")[:19]
        name = "%s_%s.json" % (stamp or "без-даты", (content_hash or "без-хэша")[:12])
        path = os.path.join(directory, name)
        if not os.path.exists(path):
            save_feed(payload, path)
        # Старые копии подчищаем сами: папка рядом с рабочим кэшем, и расти ей
        # незачем. Сортировка по имени совпадает с хронологией: дата впереди.
        kept = sorted(f for f in os.listdir(directory) if f.endswith(".json"))
        for extra in kept[:-FEED_ARCHIVE_KEEP]:
            try:
                os.remove(os.path.join(directory, extra))
            except OSError:
                pass
        return path
    except Exception:
        log.exception("Посылку не удалось положить в архив (%s)", directory)
        return ""


def check_feed(feed: "ParsedFeed") -> List[str]:
    """Что в принятой базе знаний выглядит сломанным. Список предупреждений.

    Это не отказ: посылка применяется всё равно. Отвергать правку аналитика
    из-за подозрения значит остановить его работу, а он правит базу по живым
    жалобам. Но молчать тоже нельзя: мёртвый замок категории жил в работе две
    недели (целился в тип оборудования 915, а запись заведена с типом 912), и
    увидеть это было нечем.

    Предупреждения видны в логе при приёме и в /health, то есть аналитик
    узнаёт о своей опечатке в тот же день, а не на разборе волны.
    """
    warnings: List[str] = []
    searchable = [r for r in feed.records if (r.clarifying_question or "").strip()]
    if not searchable:
        warnings.append("ни одной записи с уточняющим вопросом: боту не с чем работать")

    # Записи без единой формулировки: поиск по смыслу их почти не находит,
    # потому что в индексе у них только собственный вопрос.
    empty = [r.id for r in searchable if not r.question_variants]
    if empty:
        warnings.append("записей без формулировок %d (id %s): поиск по смыслу найдёт их только "
                        "дословно" % (len(empty), ", ".join(str(i) for i in empty[:12])))

    # Одна и та же формулировка у двух записей: дословное совпадение на ней не
    # работает вовсе, решает близость.
    seen: Dict[str, int] = {}
    collisions = []
    for record in searchable:
        for phrase in [record.question] + list(record.question_variants):
            key = " ".join(str(phrase).lower().replace("ё", "е").split())
            if not key:
                continue
            owner = seen.get(key)
            if owner is not None and owner != record.id:
                collisions.append((key, owner, record.id))
            else:
                seen[key] = record.id
    if collisions:
        warnings.append("одинаковых формулировок у разных записей %d (например %r у %s и %s)"
                        % (len(collisions), collisions[0][0][:40], collisions[0][1], collisions[0][2]))

    # Замки категорий целятся в тип оборудования: если записи с таким типом в
    # посылке нет, замок молча не делает ничего.
    from ai_assistant.service.knowledge import CATEGORY_GATES

    # Гейт мёртв, только когда пусты ВСЕ его типы: у ветеринарного их три (общий,
    # собака, кошка), и отсутствие видовой записи это не поломка гейта, а просто
    # не заведённая запись. Прежняя проверка считала мёртвым каждый тип по
    # отдельности и ругалась бы на живой гейт.
    types = {r.equipment_type_id for r in searchable}
    dead = sorted(eqs[0] for _pattern, eqs in CATEGORY_GATES if not (set(eqs) & types))
    if dead:
        warnings.append("замки категорий без записей в базе: типы оборудования %s"
                        % ", ".join(str(t) for t in dead))
    # Тип гейта, у которого записи нет, а у соседних по гейту есть: гейт жив, но
    # этой темой не пользуется. Не ошибка, но знать полезно: ровно так запись по
    # кошке и была недостижима.
    partial = sorted({eq for _pattern, eqs in CATEGORY_GATES if set(eqs) & types
                      for eq in eqs if eq not in types})
    if partial:
        warnings.append("типы в замках категорий без своих записей (замок жив соседями): %s"
                        % ", ".join(str(t) for t in partial))

    # Замки записей. Строка с коротким словом не действует вовсе, и аналитик
    # должен узнать об этом сразу, а не гадать, почему замок молчит.
    from ai_assistant.service.knowledge import GATE_MIN_LETTERS, gate_is_valid, gate_words

    short = ["%s у %s" % (row, r.id) for r in searchable for row in (r.gates or []) if not gate_is_valid(row)]
    if short:
        warnings.append("замков с пустой строкой или словом короче %d букв %d, они не действуют (%s)"
                        % (GATE_MIN_LETTERS, len(short), "; ".join(short[:8])))
    # Одна и та же строка замка у записей разных направлений: звонок уйдёт туда,
    # где ближе формулировки, то есть замок перестаёт быть однозначным.
    owners: Dict[Tuple[str, ...], Dict[int, int]] = {}
    for record in searchable:
        for row in record.gates or []:
            if gate_is_valid(row):
                owners.setdefault(gate_words(row), {})[record.telephone_direction_id] = record.id
    split = ["%s (записи %s)" % (" ".join(words), ", ".join(str(i) for i in sorted(by_dir.values())))
             for words, by_dir in sorted(owners.items()) if len(by_dir) > 1]
    if split:
        warnings.append("замков, ведущих в разные направления, %d: %s" % (len(split), "; ".join(split[:8])))

    # Запись без направления и без номера приёма перевести некуда.
    nowhere = [r.id for r in searchable
               if not r.telephone_direction_id and not (r.redirect_exten or "").strip()]
    if nowhere:
        warnings.append("записей без направления и без номера перевода %d (id %s)"
                        % (len(nowhere), ", ".join(str(i) for i in nowhere[:12])))

    return warnings


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
