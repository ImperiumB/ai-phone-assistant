# coding=utf8
r"""Линейка бота: порепличный прогон резолвера в БОЕВОЙ конфигурации (UL-19020).

    set OMP_NUM_THREADS=4 & set MKL_NUM_THREADS=4
    py -3.12 tools/measure_live.py [--out <папка>] [--only-live] [--skip-sweeps] [--compare <прежняя таблица>]

Зачем отдельный инструмент вместо tools/measure_manual.py: тот меряет не то, что
работает в бою. Он берёт выгрузку базы знаний от 18.09 (52 записи, 660
формулировок) вместо живой посылки из ERP (93 записи, 1027 формулировок) и зовёт
только resolve_vector, то есть мимо стадий exact, direct_by_keyword,
operator_request и category_request и мимо правил диалога (порог прямого
перевода, сдача на сопровождение, развилка). Поэтому все пороги и правила,
подобранные им с 18.09.2026, подбирались вслепую: правка коротких форм (sql/20)
ухудшила путь формулировок втрое и этого никто не увидел.

Эта линейка обязательна перед КАЖДЫМ перезапуском сервиса и перед КАЖДЫМ SQL в
базу знаний. Главная цифра это вариант D (ниже): живая посылка плюс перемеченный
корпус плюс полный resolve плюс действия диалога.

Повторяет tools/measure_manual.py один в один (те же load_manual / labeled_by_direction /
embeddings_for из кэша, тот же CorpusIndex(k=15, 0.50, 0.72, min_words=2), та же база
kb_now.tsv + kb_phrases_now.tsv с пересадкой 33:35, тот же KnowledgeBase.resolve_vector с
текстом, тот же judge), но пишет решение по каждой реплике и считает четыре варианта:

  A_  как measure_manual без --relabel: корпус по направлениям документов + база из выгрузки 18.09
  B_  как measure_manual --relabel: корпус перемечен классификатором намерения (2 фолда, те же
      StratifiedKFold(2, shuffle=True, random_state=7), intent_model, relabel из build_corpus_index)
  C_  корпус как в A, база знаний из текущей посылки ERP (ai_assistant/knowledge_feed_cache.json)
  D_  корпус как в B, база из текущей посылки (ближе всего к бою)

Для каждого варианта два решения: <X>_* только resolve_vector (ровно как measure_manual) и
<X>_full_* полный resolve() (сначала текстовые стадии exact / direct_by_keyword /
operator_request / category_request, потом вектор), плюс <X>_[full_]dialog_action: что сделал бы
DialogEngine._handle_question по правилам dialog.py (обрывок, зачин, общий вопрос, развилка на
corpus-unsure, порог 0.72 прямого перевода, правило Борца).

Сверх прежнего прогона: стадия «phrases-override» (формулировка перебила уверенный корпус)
отделена от «phrases-nodir» (корпус уверен, но записи с таким направлением в базе нет);
столбцы rep_kb / rep_corpus (маркеры повторного обращения из knowledge.REPEAT_MARKERS и
measure_corpus.is_repeat); столбцы intent_pN / intent_pR / intent_pX (вероятности намерения
по классификатору из build_corpus_index.intent_model, обученному на ДРУГОМ фолде);
доверительные интервалы Уилсона у главных долей; разрез уверенности корпуса по N и R отдельно;
оценка «что дали бы гейты» по намерению и по маркерам повторного.

Главный вердикт сравнивает НАПРАВЛЕНИЕ звонка, поэтому правку данных внутри
одного отдела он не видит вовсе: клиент спрашивает про смеситель, бот отвечает
«правильно понимаю, установка карниза?», отдел тот же, цифра не шевелится.
Поэтому есть вторая метрика (столбец <X>_full_spoken и сводка «сменился ли
произносимый вопрос», С1): доля доверенных решений, у которых сменился сам
текст вопроса, с разбивкой «отдел тот же / отдел другой» и порепличным списком
смен. Считается только при двух прогонах, то есть требует --compare:

    py -3.12 tools/measure_live.py --only-live --out D:\aia_archive\до
    py -3.12 tools/measure_live.py --only-live --out D:\aia_archive\после --feed правка.json ^
        --compare D:\aia_archive\до\manual_predictions.tsv

Без --compare в сводке стоит «НЕ СЧИТАНО»: молчание на этом месте читается как
«смен нет», а ровно так мы трижды за два дня и сказали «регресса нет».

Пишет (в --out):
  manual_predictions.tsv        таблица по репликам
  exp_per_row_summary.txt       сводки
  exp_per_row_confusion.tsv     полные матрицы ошибок по сценариям (variant, want, got, n)
  exp_spoken_changes.tsv        порепличный список смен произносимого вопроса (при --compare)
Файлы репо бота не трогает: кэш эмбеддингов только читается; реплик без кэша быть не должно
(иначе СТОП, чтобы embeddings_for не перезаписал dataset/corpus_emb.npz).
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import io
import json
import math
import os
import sys
import time

import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("--repo", default=os.environ.get("AIA_REPO", r"C:\Users\user\Desktop\Новый бот-помощник"))
# Не внутрь репозитория: в таблице лежат 4000 дословных реплик клиентов, а репо
# публикуется очищенной копией на GitHub. По умолчанию кладём рядом с архивом.
ap.add_argument("--out", default=os.environ.get("AIA_MEASURE_OUT", r"D:\aia_archive\measure_live"))
ap.add_argument("--skip-sweeps", action="store_true")
ap.add_argument("--feed", default="", help="другая посылка базы знаний: проверка правки данных до внесения в ERP")
ap.add_argument("--tiers", action="store_true",
                help="включить ярус намерения (ai_assistant/intent_model.json) и мерить с ним")
ap.add_argument("--intent-threshold", type=float, default=None,
                help="порог повторного обращения; по умолчанию боевой AIA_INTENT_REPEAT_THRESHOLD")
ap.add_argument("--only-live", action="store_true",
                help="считать только вариант D (боевая конфигурация): быстрее, когда нужна одна главная цифра")
ap.add_argument("--compare", default="", help="прежняя manual_predictions.tsv для сверки воспроизводимости")
# При запуске скриптом разбираем командную строку, при импорте берём
# умолчания: иначе модуль нельзя ни импортировать, ни покрыть тестами (argparse
# увидел бы ключи pytest и свалился). Функции сводок чистые, и проверять их
# надо без получасового прогона всей линейки.
args = ap.parse_args(None if __name__ == "__main__" else [])

REPO = args.repo
OUT_DIR = args.out
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))
os.chdir(REPO)

from ai_assistant.service import dialog as dialog_module  # noqa: E402
from ai_assistant.service import knowledge as knowledge_module  # noqa: E402
from ai_assistant.service.corpus_knn import OPERATOR_DIRECTION, CorpusIndex  # noqa: E402
from ai_assistant.service.knowledge import (  # noqa: E402
    REPEAT_MARKERS, KnowledgeBase, Resolution, SentenceTransformerEmbedder, content_words, exact_key,
    record_allowed)
from ai_assistant.service.knowledge_feed import parse_feed  # noqa: E402
from build_corpus_index import intent_model, labeled_by_direction, load_manual, relabel  # noqa: E402
from measure_corpus import (  # noqa: E402
    DATASET_DIR, OPERATOR_SCENARIOS, is_repeat, load_records_from_db_export, load_refs, lower_priority)
from measure_manual import judge  # noqa: E402
from train_classifier import embeddings_for  # noqa: E402

DialogEngine = dialog_module.DialogEngine
POINT_ASK = dialog_module.POINT_ASK_QUESTION
DIRECT_TRANSFER = dialog_module.DIRECT_TRANSFER_MIN_SIMILARITY

LOG = []


if hasattr(sys.stdout, "reconfigure"):
    # С перенаправлением вывода в файл Windows берёт cp1251, и прогон падает в
    # самом конце на печати сводки: в ней есть стрелка «→», которой в cp1251
    # нет. Таблица и сводка к этому моменту уже записаны, то есть падение
    # выглядит как сорванный замер при целых результатах. Прогон в лог нужен
    # как раз для гейта выкладки, поэтому вывод прибиваем к utf-8.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def say(*parts):
    line = " ".join(str(p) for p in parts)
    LOG.append(line)
    print(line, flush=True)


def wilson(k, n, z=1.96):
    """95% интервал Уилсона для доли k/n, в процентах."""
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return 100 * (c - h), 100 * (c + h)


def pct_ci(k, n):
    lo, hi = wilson(k, n)
    return "%5.1f%% [%4.1f; %4.1f]" % (100 * k / max(1, n), lo, hi)


# --------------------------------------------------------------------------- данные

def missing_in_cache(rows):
    cache = os.path.join(DATASET_DIR, "corpus_emb.npz")
    z = np.load(cache, allow_pickle=False)
    cached = set(z["uids"].tolist())
    return [u for u, _, _ in rows if u not in cached]


class IntentProxy:
    """Ярус намерения с заранее посчитанной вероятностью повторного обращения.

    Нужен, чтобы замер был честным. Боевая модель (ai_assistant/intent_model.json)
    обучена на ВСЕХ 4000 строках ручной разметки, и если мерить её на тех же
    4000, получится оценка на обучающей выборке: внутри неё точность отбора
    99,5 % и ложно забрано 3 новых заказа, а вне фолда 98,4 % и около 10
    заказов. Решение «включаем ярус» нельзя подписывать первой цифрой.

    Линейка уже считает вероятности намерения вне фолда для перемечивания
    корпуса (StratifiedKFold, random_state=7): модель учится на одном фолде и
    применяется к другому. Этот прокси подставляет ту же вероятность в резолвер,
    то есть ярус меряется на репликах, которых его модель не видела.
    """

    def __init__(self):
        self.current = 0.0
        self.classes = ["N", "R", "X"]

    def repeat_probability(self, vector):
        return self.current


class VoteProxy:
    """Корпус с заранее посчитанными голосами: resolve_vector зовёт vote(query), а голос
    от порогов не зависит, поэтому развёртки порогов не пересчитывают kNN."""

    def __init__(self, n, k=15, threshold=None, operator_threshold=None, min_words=None):
        # Пороги берутся из боевой настройки, а не зашиты числами: ровно из-за
        # зашитых чисел прежняя линейка (tools/measure_manual.py) меряла не то,
        # что работает в бою, и все пороги с 18.09.2026 подбирались вслепую.
        from ai_assistant.service.config import load_config as _load_cfg

        _cfg = _load_cfg()
        self.k = k
        self.threshold = _cfg.corpus_threshold if threshold is None else threshold
        self.operator_threshold = (_cfg.corpus_operator_threshold
                                   if operator_threshold is None else operator_threshold)
        self.min_words = _cfg.corpus_min_words if min_words is None else min_words
        self.current = None
        self._n = n

    def __len__(self):
        return self._n

    def vote(self, query):
        return self.current


def build_index(vectors, directions, phrases):
    # Пороги из боевой настройки, а не зашитые числами, см. VoteProxy.
    from ai_assistant.service.config import load_config as _load_cfg

    _cfg = _load_cfg()
    return CorpusIndex(vectors, directions, phrases, k=15, threshold=_cfg.corpus_threshold,
                       operator_threshold=_cfg.corpus_operator_threshold,
                       min_words=_cfg.corpus_min_words)


def has_repeat_marker_kb(text):
    words = exact_key(text).split()
    return any(w.startswith(m) for w in words for m in REPEAT_MARKERS)


# --------------------------------------------------------------------------- резолвер

def pre_stage(kb, text, vec=None):
    """Стадии KnowledgeBase.resolve до поиска по смыслу, в том же порядке.

    Ярус намерения стоит между просьбами позвать человека и гейтами категорий
    ровно как в resolve(): ему нужен вектор реплики, а гейты и так решают
    текстом. Передавать vec обязательно, иначе ярус в замере не участвует и
    линейка покажет цифры версии без него.
    """
    rec = kb.exact(text)
    if rec is not None:
        return "exact", rec
    rec = kb.direct_by_keyword(text)
    if rec is not None:
        return "keyword", rec
    rec = kb.operator_request(text)
    if rec is not None:
        return "keyword-regex", rec
    if kb._intent is not None and vec is not None:
        repeat = kb._intent.repeat_probability(vec)
        if repeat >= kb._intent_repeat_threshold:
            rec = kb._operator_record()
            if rec is not None:
                return "intent", rec
    rec = kb.category_request(text)
    if rec is not None:
        return "category", rec
    return "", None


def has_record_for_direction(kb, direction_id, words):
    """Есть ли в базе запись направления, не закрытая воротами бренда/повторного
    (то, что проверяет _record_for_direction, knowledge.py 583-608)."""
    for r in kb._searchable_records:
        if r.telephone_direction_id == direction_id and record_allowed(r, words):
            return True
    return False


def phrase_best(kb, text, vec):
    """Лучшая формулировка после ворот брендов и повторного (как в resolve_vector 541-546)."""
    if kb._vectors is None:
        return None, 0.0
    scores = kb._vectors @ vec
    words = exact_key(text).split()
    allowed = np.array([record_allowed(o, words) for o in kb._phrase_owners])
    scores = np.where(allowed, scores, -1.0)
    i = int(np.argmax(scores))
    return kb._phrase_owners[i], float(scores[i])


def dialog_action(kb, text, res, scenario_of):
    """Что сделал бы DialogEngine.handle + _handle_question с таким решением
    (dialog.py 520-600, 701-781): обрывок, зачин, общий вопрос, развилка, порог 0.72, Борец."""
    if DialogEngine._is_scrap_for_search(text, POINT_ASK):
        return "обрывок: слушает", None
    if DialogEngine._is_filler_only(text, POINT_ASK):
        return "зачин: слушаю вас", None
    if DialogEngine._is_generic_only(text) and not kb.exact(text):
        return "Борец: общий вопрос", None
    found = res is not None and res.trusted and res.record is not None
    if not found and res is not None and res.source == "corpus-unsure":
        return "развилка", None
    if found and res.source == "phrases" and res.score < DIRECT_TRANSFER:
        return "Борец: фраза<%.2f" % DIRECT_TRANSFER, None
    if not found and res is not None and res.source == "corpus-grey":
        # Серая зона корпуса: бот НЕ сдаётся, а говорит «не понял, повторите» и
        # слушает дальше (dialog.py, ветка corpus-grey при
        # QUESTION_REASK_ATTEMPTS). Прежде линейка метила эти строки как
        # «Борец: не нашёл», и 106 строк из 4000 попадали в сводку как «сдался
        # на сопровождение», хотя разговор продолжался. Это была ошибка
        # разметки действия, а не поведения бота.
        return "переспрос: не понял", None
    if not found:
        return "Борец: не нашёл", None
    name = scenario_of(res.record)
    if not res.record.clarifying_question:
        return "перевод: " + (name or "?"), name
    return "вопрос: " + (name or "?"), name


def _same_cell(was, now):
    """Равны ли две ячейки, одна из которых прочитана из TSV, а другая живая.

    Прежний прогон приходит из `csv.DictReader`, то есть ВСЁ в нём строки, а в
    свежей строке код записи это число. Прямое сравнение `"83" != 83` всегда
    истинно, и на контрольном прогоне 09.11 это дало 738 ложных «запись
    другая» из 850 при нулевой реальной смене. Ловушка та же, по которой ключ
    реплики ищется через `str(r["n"])`.
    """
    return str("" if was is None else was) == str("" if now is None else now)


def _one_line(text):
    # Пробелы сводим к одному: в TSV перевод строки внутри ячейки ломает
    # таблицу, а на слух он никак не отличается от пробела.
    return " ".join((text or "").split())


def spoken_question(res, action):
    """Уточняющий вопрос, который бот произнесёт, или пусто, если вопроса нет.

    Звучит только на действии «вопрос: <отдел>». На прямом переводе и на
    «Борце» бот говорит служебную фразу из группы линий, одну на все записи
    (dialog.py `_transfer` берёт её из `profile.phrases`), и сравнивать там по
    записям нечего.
    """
    if not action.startswith("вопрос: ") or res is None or res.record is None:
        return ""
    return _one_line(res.record.clarifying_question)


def spoken_positive(res, action):
    """Что бот скажет, когда клиент ответит «да». Тоже текст ИЗ ЗАПИСИ.

    Это второе место, где звучит поле записи, и оно самое частое по весу: в
    посылке от 09.11.2026 на 64 записи всего два разных текста, и один из них
    стоит у 49 записей. Правку такого текста слышит каждый, кто дошёл до
    согласия, а без этого столбца метрика С1 показывала бы «смен нет»: она
    смотрела только уточняющий вопрос. Тот же способ обмана, что и у главного
    вердикта, только этажом ниже.

    Условие то же, что у вопроса: `positive_reply` произносится в ответ на
    согласие, а согласие бывает только после заданного вопроса (dialog.py
    `_handle_confirmation`, ветки «да» и «назвал ту же тему»). На прямом
    переводе без уточнения звучит служебная фраза.

    Чего здесь нет: случая «согласие назвало СОСЕДНЮЮ тему», когда звучит
    `positive_reply` другой записи. Линейка моделирует первую реплику, второй
    реплики у неё нет вовсе, и эта ветка в замер не попадает ни так, ни иначе.
    """
    if not action.startswith("вопрос: ") or res is None or res.record is None:
        return ""
    return _one_line(getattr(res.record, "positive_reply", ""))


def dialog_verdict(intent, want, action, name):
    if action.startswith("вопрос: "):
        if intent == "N":
            return "верно (вопрос)" if name == want else "не туда (вопрос)"
        if intent == "R":
            return "вопрос не по делу"
        return "вопрос (не клиент)"
    if action.startswith("перевод: "):
        if intent == "R":
            return "верно (оператор)"
        if intent == "N":
            return "на оператора (мягкий промах)" if name in OPERATOR_SCENARIOS else "не туда (перевод)"
        return "перевод (не клиент)"
    if action.startswith("Борец"):
        if intent == "R":
            return "сопровождение (сдался, верно по месту)"
        if intent == "N":
            return "сдался: сопровождение"
        return "сдался (не клиент)"
    if action == "развилка":
        return "развилка"
    if action.startswith("переспрос"):
        # Разговор продолжается, вердикт по первой реплике ещё не вынесен:
        # относить это к «сдался» нельзя, бот ничего не сдал.
        return "переспрос (разговор продолжается)"
    return action


def resolve_row(kb, proxy, vote, text, vec, cw, scenario_of, full):
    """Одно решение. full=True: сначала текстовые стадии, как в resolve()."""
    proxy.current = vote
    if full:
        # Боевой путь целиком: тот же resolve(), которым идёт звонок, с готовым
        # вектором из кэша. Своей копии порядка стадий здесь больше нет: она
        # расходилась с резолвером и прятала от замера правки в нём.
        res = kb.resolve(text, query=vec)
    else:
        res = kb.resolve_vector(vec, content_words=cw, text=text)
    trusted = res is not None and res.trusted and res.record is not None
    name = scenario_of(res.record) if trusted else None
    stage = res.source if res is not None else "none"
    if stage == "phrases" and vote is not None and kb._corpus_trusts(vote, cw):
        # корпус уверен, а решили формулировки: либо перебили (knowledge.py 550-563),
        # либо у направления корпуса нет записи в базе (565-566)
        if has_record_for_direction(kb, vote.direction_id, exact_key(text).split()):
            stage = "phrases-override"
        else:
            stage = "phrases-nodir"
    return res, trusted, name, stage


# --------------------------------------------------------------------------- сводки

def col(r, prefix, key):
    """Столбец по префиксу; для full_-префикса голос корпуса тот же, что у базового."""
    if prefix + key in r:
        return r[prefix + key]
    return r[prefix.replace("full_", "") + key]


def judge_tally(rows_out, prefix, title):
    """Сводка как в measure_manual.run по столбцу <prefix>verdict, с интервалами Уилсона."""
    tally = collections.defaultdict(collections.Counter)
    for r in rows_out:
        tally[r["intent"]][r[prefix + "verdict"]] += 1
    out = ["", "== %s ==" % title]
    for intent, name in (("N", "новый заказ"), ("R", "повторное обращение"), ("X", "не клиент / мимо")):
        total = sum(tally[intent].values())
        out.append("  %s: %d реплик" % (name, total))
        for verdict, v in tally[intent].most_common():
            out.append("      %-36s %4d  %s" % (verdict, v, pct_ci(v, total)))
    n_total = sum(tally["N"].values()) + sum(tally["R"].values())
    answered = sum(v for i in ("N", "R") for k, v in tally[i].items() if k != "молчит")
    right = tally["N"]["верно (сценарий)"] + tally["R"]["верно (оператор)"]
    soft = tally["N"]["на оператора (мягкий промах)"]
    wrong = answered - right - soft
    out.append("  ИТОГ по клиентским (N+R, %d): ответил %.1f%%, из ответивших верно %.1f%% "
               "(+%.1f%% мягких на оператора), не туда %.1f%%; молчит %.1f%% от всех N+R"
               % (n_total, 100 * answered / n_total, 100 * right / max(1, answered),
                  100 * soft / max(1, answered), 100 * wrong / max(1, answered),
                  100 * (n_total - answered) / n_total))
    out.append("  доля «не туда» от всех N+R: %s (%d)" % (pct_ci(wrong, n_total), wrong))
    return out, tally


def dialog_tally(rows_out, prefix, title):
    tally = collections.defaultdict(collections.Counter)
    for r in rows_out:
        tally[r["intent"]][r[prefix + "dialog_verdict"]] += 1
    out = ["", "== %s: действие диалога (dialog.py после резолвера) ==" % title]
    for intent, name in (("N", "новый заказ"), ("R", "повторное обращение"), ("X", "не клиент / мимо")):
        total = sum(tally[intent].values())
        out.append("  %s: %d реплик" % (name, total))
        for verdict, v in tally[intent].most_common():
            out.append("      %-40s %4d  %s" % (verdict, v, pct_ci(v, total)))
    n_bad = (tally["N"]["не туда (вопрос)"] + tally["N"]["не туда (перевод)"] + tally["R"]["вопрос не по делу"])
    n_total = sum(tally["N"].values()) + sum(tally["R"].values())
    gave_up = sum(tally[i][k] for i in ("N", "R") for k in tally[i] if k.startswith("сдался") or k.startswith("сопровождение"))
    fork = tally["N"]["развилка"] + tally["R"]["развилка"]
    out.append("  вопрос не по делу или не туда (N+R): %d из %d = %s" % (n_bad, n_total, pct_ci(n_bad, n_total)))
    out.append("  сдался на сопровождение (N+R): %d = %.1f%%; развилка: %d = %.1f%%" % (
        gave_up, 100 * gave_up / n_total, fork, 100 * fork / n_total))
    return out


def stage_table(rows_out, prefix, title):
    """Стадия резолвера: сколько решений, сколько верных, сколько не туда (N+R)."""
    per = collections.defaultdict(lambda: collections.Counter())
    for r in rows_out:
        if r["intent"] == "X":
            continue
        v = r[prefix + "verdict"]
        st = r[prefix + "stage"]
        per[st]["всего"] += 1
        if v.startswith("верно"):
            per[st]["верно"] += 1
        elif v.startswith("не туда"):
            per[st]["не туда"] += 1
        elif v == "молчит":
            per[st]["молчит"] += 1
        else:
            per[st]["мягко"] += 1
    out = ["", "== %s: по стадиям резолвера (N+R) ==" % title,
           "  %-18s %6s %6s %8s %7s %7s  %s" % ("стадия", "всего", "верно", "не туда", "мягко", "молчит", "точность среди ответивших")]
    total_wrong = sum(c["не туда"] for c in per.values())
    for st, c in sorted(per.items(), key=lambda kv: -kv[1]["всего"]):
        answered = c["верно"] + c["не туда"] + c["мягко"]
        out.append("  %-18s %6d %6d %8d %7d %7d  %5.1f%%   доля всех «не туда»: %4.1f%%" % (
            st, c["всего"], c["верно"], c["не туда"], c["мягко"], c["молчит"],
            100 * c["верно"] / max(1, answered), 100 * c["не туда"] / max(1, total_wrong)))
    # стадии у не-клиентов (X): куда они уходят
    per_x = collections.Counter(r[prefix + "stage"] for r in rows_out if r["intent"] == "X")
    out.append("  не клиенты (X) по стадиям: " + ", ".join("%s %d" % (k, v) for k, v in per_x.most_common()))
    return out


def bins_table(rows_out, prefix, title):
    """Распределение близости у верных и неверных ответов по стадиям."""
    out = ["", "== %s: распределение уверенности/близости у верных и неверных (N+R) ==" % title]

    def hist(values_right, values_wrong, edges, label):
        out.append("  %s" % label)
        out.append("    %-12s %6s %7s %11s" % ("интервал", "верно", "не туда", "доля ошибок"))
        for lo, hi in zip(edges[:-1], edges[1:]):
            a = sum(1 for v in values_right if lo <= v < hi)
            b = sum(1 for v in values_wrong if lo <= v < hi)
            out.append("    [%.2f;%.2f) %6d %7d %10.1f%%" % (lo, hi, a, b, 100 * b / max(1, a + b)))
        for name, vals in (("верно", values_right), ("не туда", values_wrong)):
            if vals:
                out.append("    %-8s n=%4d  среднее %.3f  медиана %.3f  p10 %.3f  p90 %.3f" % (
                    name, len(vals), float(np.mean(vals)), float(np.median(vals)),
                    float(np.percentile(vals, 10)), float(np.percentile(vals, 90))))

    def pick(stages, key, intents=("N", "R")):
        right, wrong = [], []
        for r in rows_out:
            if r["intent"] not in intents or r[prefix + "stage"] not in stages:
                continue
            v = r[prefix + "verdict"]
            val = col(r, prefix, key)
            if val == "" or val is None:
                continue
            if v.startswith("верно"):
                right.append(float(val))
            elif v.startswith("не туда"):
                wrong.append(float(val))
        return right, wrong

    r, w = pick(("corpus",), "vote_conf")
    hist(r, w, [0.5, 0.6, 0.7, 0.8, 0.9, 1.01], "решал корпус: уверенность голосования (vote_conf), N+R")
    r, w = pick(("corpus",), "vote_conf", ("N",))
    hist(r, w, [0.5, 0.6, 0.7, 0.8, 0.9, 1.01], "решал корпус: уверенность, только N (новые заказы)")
    r, w = pick(("corpus",), "vote_conf", ("R",))
    hist(r, w, [0.5, 0.6, 0.7, 0.8, 0.9, 1.01], "решал корпус: уверенность, только R (повторные)")
    r, w = pick(("corpus",), "top_sim")
    hist(r, w, [0.4, 0.6, 0.7, 0.8, 0.9, 1.01], "решал корпус: близость ближайшего соседа (top_sim), N+R")
    r, w = pick(("phrases", "phrases-override", "phrases-nodir"), "score")
    hist(r, w, [0.60, 0.66, 0.70, 0.72, 0.74, 0.78, 0.85, 1.01], "решали формулировки (все три стадии): близость к формулировке (score), N+R")
    r, w = pick(("phrases",), "score")
    hist(r, w, [0.60, 0.66, 0.70, 0.72, 0.74, 0.78, 0.85, 1.01], "решали формулировки, только стадия phrases (корпус не доверял себе), N+R")
    return out


def confusion(rows_out, prefix, title):
    """Матрица ошибок: ожидание (сценарий N или «повторное») -> ответ бота."""
    mat = collections.Counter()
    for r in rows_out:
        if r["intent"] == "X":
            continue
        want = r["scenario"] if r["intent"] == "N" else "ПОВТОРНОЕ (оператор)"
        got = r[prefix + "answer"] or ("молчит" if r[prefix + "verdict"] == "молчит" else "?")
        if got in OPERATOR_SCENARIOS:
            got = "ОПЕРАТОР"
        mat[(want, got)] += 1
    out = ["", "== %s: не туда чаще всего (ожидание -> ответ) ==" % title]
    pairs = [(k, v) for k, v in mat.items()
             if not (k[0] == "ПОВТОРНОЕ (оператор)" and k[1] in ("ОПЕРАТОР", "молчит"))
             and not (k[0] == k[1]) and k[1] not in ("молчит", "ОПЕРАТОР")]
    for (want, got), v in sorted(pairs, key=lambda kv: -kv[1])[:25]:
        out.append("   %4d  %-34s -> %s" % (v, want[:34], got))
    per = collections.defaultdict(collections.Counter)
    for r in rows_out:
        if r["intent"] != "N":
            continue
        v = r[prefix + "verdict"]
        c = per[r["scenario"]]
        c["всего"] += 1
        if v.startswith("верно"):
            c["верно"] += 1
        elif v.startswith("не туда"):
            c["не туда"] += 1
        elif v == "молчит":
            c["молчит"] += 1
        else:
            c["оператор"] += 1
    out.append("")
    out.append("  новые заказы по ожидаемому сценарию: всего / верно / не туда / на оператора / молчит")
    for sc_name, c in sorted(per.items(), key=lambda kv: -kv[1]["всего"]):
        out.append("    %-36s %4d  %4d  %4d  %4d  %4d   верно %4.0f%%" % (
            sc_name[:36], c["всего"], c["верно"], c["не туда"], c["оператор"], c["молчит"],
            100 * c["верно"] / max(1, c["всего"])))
    return out, mat


#: Корзины смен в порядке печати. Названия осторожные намеренно: первая
#: корзина это слепая зона вердикта по построению (ярлык отдела не менялся,
#: значит вердикт не шевельнётся), а вторая НЕ обещает, что вердикт смену
#: увидит. Вердикт сравнивает ярлык с ожидаемым, поэтому переезд между двумя
#: НЕВЕРНЫМИ отделами он показывает как «совпал», и то же касается реплик с
#: намерением «не клиент». В прогоне 09.11 таких строк 308 из 850, то есть
#: больше трети знаменателя.
CHANGE_SAME_DESK = "вопрос сменился, ОТДЕЛ ТОТ ЖЕ (вердикт не шевельнётся)"
CHANGE_OTHER_DESK = "вопрос сменился, отдел другой (вердикт может и не увидеть)"
CHANGE_APPEARED = "вопрос появился (прежде молчал или переводил)"
CHANGE_VANISHED = "вопрос пропал (стал переводить или сдаваться)"
CHANGE_POSITIVE = "сменился ответ на согласие (его слышит каждый, кто сказал «да»)"
CHANGE_RECORD = "текст тот же, но запись другая (в ERP уедет другой тип оборудования)"
CHANGE_MISSING = "реплики нет в прежнем прогоне"
CHANGE_KINDS = (CHANGE_SAME_DESK, CHANGE_OTHER_DESK, CHANGE_POSITIVE, CHANGE_RECORD,
                CHANGE_APPEARED, CHANGE_VANISHED, CHANGE_MISSING)


#: Столбцы, по которым сверяется воспроизводимость двух прогонов.
COMPARE_KEYS = ("A_full_verdict", "D_full_verdict", "D_full_stage", "D_full_dialog_verdict")


def compare_runs(rows_out, prev, source=""):
    """Сверка с прежним прогоном: совпал ли вердикт по каждой реплике.

    Вынесена из main отдельной функцией не для красоты: 09.11.2026 она валилась
    с `KeyError('A_full_verdict')` при `--only-live` (посчитан один вариант D,
    столбцов A в строке нет вовсе), и общий `except` уносил вместе с ней
    метрику С1 из того же `try`. В сводке не оставалось ни секции С1, ни
    страховочного «НЕ СЧИТАНО»: одна строка «сверка упала» на 282-й строке
    29-килобайтного файла. Документированный способ запуска попадал в эту
    ветку ВСЕГДА, то есть у метрики не было ни одного живого прогона.
    Отсутствующий столбец теперь считается отдельной строкой, а метрика живёт
    в своём `try`.
    """
    same = collections.Counter()
    for r in rows_out:
        pr = prev.get(str(r["n"]))
        if pr is None:
            same["нет в прежней"] += 1
            continue
        for key in COMPARE_KEYS:
            if key not in r:
                same[key + " не считан в этом прогоне"] += 1
                continue
            same[key + (" совпал" if pr.get(key) == r[key] else " РАЗОШЁЛСЯ")] += 1
    out = ["", "== сверка с прежним прогоном %s ==" % source]
    for k, v in sorted(same.items()):
        out.append("   %-36s %d" % (k, v))
    return out


def spoken_changes(rows_out, prev, prefix, title, out_path):
    """Вторая метрика линейки: сменилось ли то, что бот ПРОИЗНОСИТ (С1).

    Главный вердикт сравнивает направление звонка, поэтому правку данных
    внутри одного отдела он не видит вовсе. Пример из жизни: клиент
    спрашивает про смеситель, бот отвечает «правильно понимаю, установка
    карниза?», отдел при этом тот же, и цифра не шевелится. Трижды за два дня
    мы говорили «регресса нет», опираясь на цифру, которая этот класс правок
    не замечает, и каждый раз регресс искали потом руками порепличной сверкой.
    Эта функция и есть та сверка, встроенная в линейку.

    Знаменатель: решения, на которых бот открывает рот с текстом ИЗ ЗАПИСИ
    хотя бы в одном из двух прогонов. Полей записи, которые он озвучивает,
    два: уточняющий вопрос и ответ на согласие. Строки, где бот оба раза
    только переводил или сдавался, в знаменатель не идут: там звучит служебная
    фраза группы линий, одна на все записи.

    Чего знаменатель НЕ покрывает: серую зону корпуса (бот говорит «не понял,
    повторите» и доходит до записи на второй реплике). Линейка моделирует
    первую реплику, второй у неё нет, и эти строки в сравнение не попадают.
    В прогоне 09.11 их 106 из 4000.
    """
    key_q, key_yes = prefix + "spoken", prefix + "spoken_yes"
    key_desk, key_rec = prefix + "answer", prefix + "record"
    out = ["", "== %s: сменилось ли то, что бот произносит (С1) ==" % title]
    if not prev:
        return out + ["   прежнего прогона нет, сравнивать не с чем"]
    sample = next(iter(prev.values()))
    missing = [k for k in (key_q, key_yes) if k not in sample]
    if missing:
        return out + ["   в прежней таблице нет столбцов %s: она снята до того, как метрика"
                      " появилась. Сравнить можно только с прогоном этой же версии."
                      % ", ".join(missing)]
    tally = collections.Counter()
    changes = []
    for r in rows_out:
        pr = prev.get(str(r["n"]))
        if pr is None:
            tally[CHANGE_MISSING] += 1
            continue
        was_q, now_q = pr.get(key_q, ""), r[key_q]
        was_yes, now_yes = pr.get(key_yes, ""), r[key_yes]
        if not (was_q or now_q or was_yes or now_yes):
            continue
        tally["решений, где бот говорит текст записи"] += 1
        kinds = []
        if was_q != now_q:
            if not was_q:
                kinds.append(CHANGE_APPEARED)
            elif not now_q:
                kinds.append(CHANGE_VANISHED)
            elif pr.get(key_desk, "") == r[key_desk]:
                kinds.append(CHANGE_SAME_DESK)
            else:
                kinds.append(CHANGE_OTHER_DESK)
        if was_yes != now_yes:
            kinds.append(CHANGE_POSITIVE)
        if not kinds and _same_cell(pr.get(key_rec), r.get(key_rec)) is False:
            # Текст тот же, а запись другая: в посылке пять записей делят текст
            # вопроса с соседкой при РАЗНЫХ типах оборудования (7 и 131, 26 и
            # 177 и 178). Клиент услышит то же самое, а в обращение ERP уедет
            # другой тип, то есть мастера подберут по другому справочнику.
            kinds.append(CHANGE_RECORD)
        if not kinds:
            tally["всё то же"] += 1
            continue
        for kind in kinds:
            tally[kind] += 1
        changes.append((r["n"], r["phrase"], "; ".join(kinds),
                        pr.get(key_desk, ""), r[key_desk],
                        pr.get(key_rec, ""), r[key_rec],
                        was_q, now_q, was_yes, now_yes))
    total = tally["решений, где бот говорит текст записи"]
    changed = total - tally["всё то же"]
    out.append("   решений, где бот говорит текст записи: %d" % total)
    out.append("   сменилось хоть что-то: %d (%s)" % (changed, pct_ci(changed, total)))
    for name in CHANGE_KINDS:
        if tally[name]:
            out.append("      %-62s %d" % (name, tally[name]))
    if changes:
        with io.open(out_path, "w", encoding="utf-8", newline="") as f:
            f.write("n\tреплика\tчто сменилось\tотдел было\tотдел стало\tзапись было\t"
                    "запись стало\tвопрос было\tвопрос стало\tсогласие было\tсогласие стало\n")
            for row in changes:
                f.write("\t".join(str(v) for v in row) + "\n")
        out.append("   порепличный список смен: %s (%d строк)" % (out_path, len(changes)))
        for row in changes[:12]:
            out.append("      [%s] %s" % (row[0], row[1][:58]))
            if row[7] != row[8]:
                out.append("            вопрос было:  %s" % (row[7][:88] or "(без вопроса)"))
                out.append("            вопрос стало: %s" % (row[8][:88] or "(без вопроса)"))
            if row[9] != row[10]:
                out.append("            согласие было:  %s" % (row[9][:88] or "(нет)"))
                out.append("            согласие стало: %s" % (row[10][:88] or "(нет)"))
            if row[5] != row[6]:
                out.append("            запись %s -> %s" % (row[5] or "нет", row[6] or "нет"))
    return out


def worst_examples(rows_out, prefix, title, n=30):
    out = ["", "== %s: самые уверенные «не туда» ==" % title]
    bad = [r for r in rows_out if r["intent"] != "X" and r[prefix + "verdict"].startswith("не туда")]

    def conf(r):
        st = r[prefix + "stage"]
        if st == "corpus":
            return float(col(r, prefix, "vote_conf") or 0)
        return float(col(r, prefix, "score") or 0)
    bad.sort(key=conf, reverse=True)
    for r in bad[:n]:
        want = r["scenario"] if r["intent"] == "N" else "повторное"
        out.append("   %s %-16s %.3f  %s -> %s | %s" % (
            r["intent"], r[prefix + "stage"], conf(r), want[:22], (r[prefix + "answer"] or "?")[:22], r["phrase"][:90]))
    return out


def gates_what_if(rows_out, prefix, title):
    """Что дали бы два гейта поверх решения диалога (D full): маркеры повторного обращения в реплике
    и вероятность намерения по классификатору (обучен на другом фолде)."""
    out = ["", "== %s: что дали бы гейты поверх решения (по вердикту диалога) ==" % title]
    dv = prefix + "dialog_verdict"
    st = prefix + "stage"
    device_q = lambda r: r[dv] in ("верно (вопрос)", "не туда (вопрос)", "вопрос не по делу", "вопрос (не клиент)")
    # 1. маркеры повторного (knowledge.REPEAT_MARKERS, те же, что у repeat_gate записей)
    for flag, label in (("rep_kb", "маркеры knowledge.REPEAT_MARKERS в реплике"), ("rep_corpus", "маркеры measure_corpus.is_repeat")):
        c = collections.Counter()
        for r in rows_out:
            if not device_q(r):
                continue
            c[(r["intent"], r[dv], bool(r[flag]))] += 1
        fixed = c[("R", "вопрос не по делу", True)]
        total_r = c[("R", "вопрос не по делу", True)] + c[("R", "вопрос не по делу", False)]
        broken = c[("N", "верно (вопрос)", True)]
        total_n = c[("N", "верно (вопрос)", True)] + c[("N", "верно (вопрос)", False)]
        wrong_n = c[("N", "не туда (вопрос)", True)]
        x_q = c[("X", "вопрос (не клиент)", True)]
        out.append("  гейт «%s → оператор вместо вопроса про прибор»:" % label)
        out.append("      R «вопрос не по делу» закрыл бы %d из %d; N верных вопросов сломал бы %d из %d; "
                   "N неверных вопросов увёл бы на оператора %d; X вопросов снял бы %d"
                   % (fixed, total_r, broken, total_n, wrong_n, x_q))
        by_stage = collections.Counter(r[st] for r in rows_out if r["intent"] == "R" and r[dv] == "вопрос не по делу" and r[flag])
        out.append("      закрытые R по стадиям: " + ", ".join("%s %d" % kv for kv in by_stage.most_common()))
    # 2. намерение по классификатору
    out.append("  гейт по вероятности повторного P(R) ≥ t → оператор вместо вопроса про прибор (вероятность с другого фолда):")
    out.append("      %4s  %22s  %22s  %18s  %14s" % ("t", "R «не по делу» закрыто", "N верных сломано", "N неверных снято", "X вопросов снято"))
    for t in (0.5, 0.6, 0.7, 0.8, 0.9):
        c = collections.Counter()
        for r in rows_out:
            if not device_q(r):
                continue
            hit = float(r["intent_pR"]) >= t
            c[(r["intent"], r[dv], hit)] += 1
        out.append("      %4.1f  %10d из %-9d  %10d из %-9d  %7d из %-7d  %5d из %-5d" % (
            t, c[("R", "вопрос не по делу", True)], c[("R", "вопрос не по делу", True)] + c[("R", "вопрос не по делу", False)],
            c[("N", "верно (вопрос)", True)], c[("N", "верно (вопрос)", True)] + c[("N", "верно (вопрос)", False)],
            c[("N", "не туда (вопрос)", True)], c[("N", "не туда (вопрос)", True)] + c[("N", "не туда (вопрос)", False)],
            c[("X", "вопрос (не клиент)", True)], c[("X", "вопрос (не клиент)", True)] + c[("X", "вопрос (не клиент)", False)]))
    out.append("  гейт по вероятности «не клиент» P(X) ≥ t → слушать дальше вместо любого ответа:")
    out.append("      %4s  %18s  %18s  %18s" % ("t", "X ответов снято", "N верных сломано", "R верных сломано"))
    for t in (0.5, 0.6, 0.7, 0.8, 0.9):
        c = collections.Counter()
        for r in rows_out:
            hit = float(r["intent_pX"]) >= t
            v = r[dv]
            if r["intent"] == "X" and not v.startswith("обрывок") and not v.startswith("зачин"):
                c[("X", hit)] += 1
            if r["intent"] == "N" and v == "верно (вопрос)":
                c[("N", hit)] += 1
            if r["intent"] == "R" and v == "верно (оператор)":
                c[("R", hit)] += 1
        out.append("      %4.1f  %7d из %-7d  %7d из %-7d  %7d из %-7d" % (
            t, c[("X", True)], c[("X", True)] + c[("X", False)], c[("N", True)], c[("N", True)] + c[("N", False)],
            c[("R", True)], c[("R", True)] + c[("R", False)]))
    return out


def intent_model_report(rows_out):
    out = ["", "== классификатор намерения N/R/X (build_corpus_index.intent_model, 2 фолда, вероятности вне фолда) =="]
    y = [r["intent"] for r in rows_out]
    p = [r["intent_pred"] for r in rows_out]
    n_ok = sum(1 for a, b in zip(y, p) if a == b)
    out.append("  точность: %d из %d = %s" % (n_ok, len(y), pct_ci(n_ok, len(y))))
    mat = collections.Counter(zip(y, p))
    out.append("  матрица (строка: истина, столбец: предсказание)   N      R      X")
    for a in ("N", "R", "X"):
        out.append("    %s %40s %6d %6d %6d" % (a, "", mat[(a, "N")], mat[(a, "R")], mat[(a, "X")]))
    for c in ("N", "R", "X"):
        tp = mat[(c, c)]
        pred = sum(mat[(a, c)] for a in ("N", "R", "X"))
        true = sum(mat[(c, b)] for b in ("N", "R", "X"))
        out.append("    класс %s: точность %5.1f%% (из %d предсказанных), полнота %5.1f%% (из %d истинных)" % (
            c, 100 * tp / max(1, pred), pred, 100 * tp / max(1, true), true))
    return out


def silence_breakdown(rows_out, prefix, title):
    out = ["", "== %s: из чего состоит «молчит» резолвера (N+R) и что с ним делает диалог ==" % title]
    c = collections.Counter()
    for r in rows_out:
        if r["intent"] == "X":
            continue
        if r[prefix + "verdict"] == "молчит":
            c[(r["intent"], r[prefix + "stage"], r[prefix + "dialog_action"].split(":")[0])] += 1
    for (intent, st, act), v in sorted(c.items(), key=lambda kv: -kv[1]):
        out.append("   %4d  %s  %-16s -> %s" % (v, intent, st, act))
    return out


def sweep(kb, proxy, votes, rows, vectors, scenario_of, label, full):
    """Развёртка порогов: голоса корпуса закэшированы, поэтому дёшево."""
    out = ["", "== %s: развёртка порогов (N+R; ответил / из ответивших верно / не туда от всех / молчит) ==" % label]
    base = (proxy.threshold, proxy.operator_threshold, kb._threshold,
            knowledge_module.CORPUS_MIN_TOP_SIMILARITY, knowledge_module.PHRASE_OVERRIDE_SIMILARITY)

    def run_once():
        tally = collections.Counter()
        for i, r in enumerate(rows):
            if r["intent"] == "X":
                continue
            cw = len(content_words(r["phrase"]))
            res, trusted, name, stage = resolve_row(kb, proxy, votes[i], r["phrase"], vectors[i], cw, scenario_of, full)
            v = judge(r["intent"], r["scenario"], name, trusted)
            tally["всего"] += 1
            tally[r["intent"] + "всего"] += 1
            if v == "молчит":
                tally["молчит"] += 1
            elif v.startswith("верно"):
                tally["верно"] += 1
                tally[r["intent"] + "верно"] += 1
            elif v.startswith("не туда"):
                tally["не туда"] += 1
                tally[r["intent"] + "не туда"] += 1
            else:
                tally["мягко"] += 1
        answered = tally["всего"] - tally["молчит"]
        return ("ответил %5.1f%%  верно %5.1f%%  не туда %4.1f%% (%3d: N %3d, R %3d)  мягко %4.1f%%  молчит %5.1f%%  "
                "| N верно %5.1f%%  R оператор %5.1f%%" % (
                    100 * answered / tally["всего"], 100 * tally["верно"] / max(1, answered),
                    100 * tally["не туда"] / tally["всего"], tally["не туда"], tally["Nне туда"], tally["Rне туда"],
                    100 * tally["мягко"] / tally["всего"], 100 * tally["молчит"] / tally["всего"],
                    100 * tally["Nверно"] / max(1, tally["Nвсего"]), 100 * tally["Rверно"] / max(1, tally["Rвсего"])))

    def restore():
        proxy.threshold, proxy.operator_threshold, kb._threshold = base[0], base[1], base[2]
        knowledge_module.CORPUS_MIN_TOP_SIMILARITY = base[3]
        knowledge_module.PHRASE_OVERRIDE_SIMILARITY = base[4]

    out.append("  текущие настройки (corpus %.2f / operator %.2f / similarity %.2f / min_top %.2f / override %.2f): %s"
               % (base[0], base[1], base[2], base[3], base[4], run_once()))
    out.append("  порог уверенности корпуса (CORPUS_THRESHOLD):")
    for t in (0.40, 0.50, 0.60, 0.70, 0.80, 0.90):
        restore(); proxy.threshold = t
        out.append("    %.2f  %s" % (t, run_once()))
    out.append("  порог оператора без вопроса (CORPUS_OPERATOR_THRESHOLD):")
    for t in (0.50, 0.72, 0.90, 1.01):
        restore(); proxy.operator_threshold = t
        out.append("    %.2f  %s" % (t, run_once()))
    out.append("  порог близости формулировок (SIMILARITY_THRESHOLD):")
    for t in (0.62, 0.66, 0.70, 0.74, 0.78):
        restore(); kb._threshold = t
        out.append("    %.2f  %s" % (t, run_once()))
    out.append("  близость ближайшего соседа корпуса (CORPUS_MIN_TOP_SIMILARITY, 0 = выключено):")
    for t in (0.70, 0.80):
        restore(); knowledge_module.CORPUS_MIN_TOP_SIMILARITY = t
        out.append("    %.2f  %s" % (t, run_once()))
    out.append("  формулировка перебивает корпус (PHRASE_OVERRIDE_SIMILARITY):")
    for t in (0.70, 1.01):
        restore(); knowledge_module.PHRASE_OVERRIDE_SIMILARITY = t
        out.append("    %.2f  %s" % (t, run_once()))
    out.append("  сетка корпус x оператор:")
    for ct in (0.60, 0.70, 0.80):
        for ot in (0.85, 1.01):
            restore(); proxy.threshold = ct; proxy.operator_threshold = ot
            out.append("    corpus %.2f operator %.2f  %s" % (ct, ot, run_once()))
    # Сетка «оператор x формулировки». Нужна потому, что до 07.11.2026 пороги
    # меряли и двигали по одному, а в бою они работают вместе: операторский
    # порог решает, пойдёт ли уверенный голос корпуса за направление 17
    # (сопровождение) или звонок уйдёт в развилку, а порог формулировок решает,
    # задаст ли бот вопрос по записи или сдастся. Пара 0.50 плюс 0.74 это
    # предложение Э2 плана, и её эффект нельзя сложить из двух одиночных
    # развёрток: операторский порог забирает решения из «молчит», а порог
    # формулировок их туда добавляет.
    out.append("  сетка оператор x формулировки (пара порогов Э2):")
    for ot in (0.50, 0.72):
        for st in (0.66, 0.70, 0.72, 0.74, 0.78):
            restore(); proxy.operator_threshold = ot; kb._threshold = st
            out.append("    operator %.2f similarity %.2f  %s" % (ot, st, run_once()))
    restore()
    return out


# --------------------------------------------------------------------------- main

def main():
    lower_priority()
    t_start = time.time()
    # Настройка читается первой: пороги в шапке должны быть боевыми, а не
    # литералами. До 07.11.2026 печаталось «operator 0.72», и отчёт, который
    # идёт в журнал как доказательство конфигурации, в одной строке говорил
    # одно, а в другой другое.
    from ai_assistant.service.config import load_config
    cfg = load_config()
    say("ПОРЕПЛИЧНЫЙ ПРОГОН (прогон 2) %s" % dt.datetime.now().isoformat(timespec="seconds"))
    say("репо: %s" % REPO)
    say("пороги: corpus %.2f / operator %.2f / min_words %d / override %.2f / min_top %.2f / direct_transfer %.2f"
        % (cfg.corpus_threshold, cfg.corpus_operator_threshold, cfg.corpus_min_words,
           knowledge_module.PHRASE_OVERRIDE_SIMILARITY, knowledge_module.CORPUS_MIN_TOP_SIMILARITY,
           DIRECT_TRANSFER))

    # Папку вывода создаём сами: без неё прогон доходил до конца и падал на
    # записи результата, то есть двадцать минут счёта уходили впустую.
    os.makedirs(args.out, exist_ok=True)

    rows = load_manual()
    test_uids = {r["uid"] for r in rows}
    et, kb_refs, sc = load_refs()
    corpus_rows, skipped, _ = labeled_by_direction()
    corpus_rows = [r for r in corpus_rows if r[0] not in test_uids]
    miss = missing_in_cache(corpus_rows) + missing_in_cache([(r["uid"], r["phrase"], None) for r in rows])
    if miss:
        say("СТОП: %d реплик без кэша эмбеддингов, считать их значило бы писать в dataset/corpus_emb.npz" % len(miss))
        return 2
    corpus_vectors = embeddings_for(corpus_rows)
    test_vectors = embeddings_for([(r["uid"], r["phrase"], None) for r in rows])
    counts = collections.Counter(r["intent"] for r in rows)
    say("разметка: N %d, R %d, X %d, с «?» %d | корпус без размеченных: %d реплик (пропущено без направления %d)"
        % (counts["N"], counts["R"], counts["X"], sum(r["unsure"] for r in rows), len(corpus_rows), skipped))

    say("config: similarity_threshold %.2f, corpus_threshold %.2f, operator %.2f, min_words %d, embedder %s"
        % (cfg.similarity_threshold, cfg.corpus_threshold, cfg.corpus_operator_threshold, cfg.corpus_min_words, cfg.embedder_model))
    embedder = SentenceTransformerEmbedder(cfg.embedder_model)

    # База A/B: выгрузка 18.09 (kb_now.tsv + kb_phrases_now.tsv), пересадка 33:35, как в measure_manual
    rehome = {33: 35}
    records_db, record_scenario = load_records_from_db_export(
        os.path.join(DATASET_DIR, "kb_now.tsv"), os.path.join(DATASET_DIR, "kb_phrases_now.tsv"), sc, set(), rehome)
    kb_db = KnowledgeBase(records_db, embedder, cfg.similarity_threshold)
    say("база A/B (kb_now.tsv 18.09): записей %d, формулировок %d, ключевых основ %d, exact-ключей %d (из них двусмысленных %d), записей в поиске %d"
        % (len(records_db), len(kb_db._phrases), len([k for k, v in kb_db._direct_keywords.items() if v is not None]),
           len(kb_db._exact), sum(1 for v in kb_db._exact.values() if v is None), len(kb_db._searchable_records)))

    def scenario_db(rec):
        return sc.get(record_scenario.get(rec.id), {}).get("name")

    # База C/D: текущая посылка ERP
    # Посылку можно подменить: так проверяется ПРАВКА ДАННЫХ до внесения её в
    # ERP. Правка базы знаний трижды меняла поведение бота, и проверить её было
    # нечем, кроме живой волны через две недели.
    feed_path = args.feed or os.path.join(REPO, "ai_assistant", "knowledge_feed_cache.json")
    feed = parse_feed(json.load(io.open(feed_path, encoding="utf-8")))
    intent = None
    intent_threshold = cfg.intent_repeat_threshold if args.intent_threshold is None else args.intent_threshold
    if args.tiers:
        # Вероятности подставляются готовыми, вне фолда (см. IntentProxy):
        # боевой файл модели здесь не читается намеренно, он обучен на всей
        # разметке и дал бы оценку на своей же выборке.
        intent = IntentProxy()
        say("ярус намерения включён ВНЕ ФОЛДА, порог повторного обращения %.2f "
            "(из боевой настройки AIA_INTENT_REPEAT_THRESHOLD)" % intent_threshold)
    kb_feed = KnowledgeBase(feed.records, embedder, cfg.similarity_threshold,
                            intent=intent, intent_repeat_threshold=intent_threshold)
    dir_name = {s["direction"]: s["name"] for s in sc.values() if s["direction"] != OPERATOR_DIRECTION}
    dir_name[OPERATOR_DIRECTION] = "Соединить с оператором"
    say("база C/D (посылка %s): записей %d, формулировок %d, ключевых основ %d (%s), exact-ключей %d (из них двусмысленных %d), записей в поиске %d"
        % (feed.generated_at, len(feed.records), len(kb_feed._phrases),
           len([k for k, v in kb_feed._direct_keywords.items() if v is not None]),
           ", ".join(k for k, v in kb_feed._direct_keywords.items() if v is not None),
           len(kb_feed._exact), sum(1 for v in kb_feed._exact.values() if v is None), len(kb_feed._searchable_records)))
    amb = [k for k, v in kb_feed._exact.items() if v is None]
    say("двусмысленные дословные ключи посылки: " + "; ".join(amb))
    feed_dirs = collections.Counter(r.telephone_direction_id for r in kb_feed._searchable_records)
    unknown_dirs = [d for d in feed_dirs if d not in dir_name]
    say("направления посылки без имени сценария в refs.tsv: %s" % (unknown_dirs or "нет"))

    def scenario_feed(rec):
        return dir_name.get(rec.telephone_direction_id)

    # Индексы: A/C общий (по направлениям), B/D два фолда перемеченного корпуса
    say("индекс A/C: строим...")
    index_plain = build_index(corpus_vectors, [d for _, _, d in corpus_rows], [p for _, p, _ in corpus_rows])
    say("индекс A/C: %d реплик, повторных (напр. 17) %d" % (len(index_plain), int((index_plain.directions == OPERATOR_DIRECTION).sum())))
    t0 = time.time()
    votes_plain = [index_plain.vote(v) for v in test_vectors]
    say("голоса A/C посчитаны за %.0f с" % (time.time() - t0))
    del index_plain

    from sklearn.model_selection import StratifiedKFold
    intents = np.array([r["intent"] for r in rows])
    votes_relabel = [None] * len(rows)
    fold_of = [0] * len(rows)
    proba = np.zeros((len(rows), 3))
    relabel_stats = collections.Counter()
    for f, (train, test) in enumerate(StratifiedKFold(2, shuffle=True, random_state=7).split(test_vectors, intents)):
        model = intent_model(test_vectors[train], intents[train])
        classes = list(model.classes_)
        pr = model.predict_proba(test_vectors[test])
        for j, c in enumerate(("N", "R", "X")):
            proba[test, j] = pr[:, classes.index(c)] if c in classes else 0.0
        keep, directions = relabel(corpus_rows, corpus_vectors, model, 0.5)
        keep_idx = {uid for uid, _ in keep}
        vecs = corpus_vectors[[i for i, (uid, _, _) in enumerate(corpus_rows) if uid in keep_idx]]
        index = build_index(vecs, directions, [p for _, p in keep])
        relabel_stats["выкинуто"] += len(corpus_rows) - len(keep)
        relabel_stats["повторных"] += int((directions == OPERATOR_DIRECTION).sum())
        relabel_stats["размер"] += len(index)
        for i in test:
            votes_relabel[i] = index.vote(test_vectors[i])
            fold_of[i] = f + 1
        say("фолд %d: модель намерения на %d репликах, индекс %d реплик, повторных %d, выкинуто не-клиентов %d" % (
            f + 1, len(train), len(index), int((directions == OPERATOR_DIRECTION).sum()), len(corpus_rows) - len(keep)))
        del index
    say("индекс B/D (2 фолда, в среднем): %d реплик, повторных %d, выкинуто %d" % (
        relabel_stats["размер"] // 2, relabel_stats["повторных"] // 2, relabel_stats["выкинуто"] // 2))

    proxy_plain = VoteProxy(len(corpus_rows))
    proxy_relabel = VoteProxy(relabel_stats["размер"] // 2)

    variants = [
        ("A", kb_db, proxy_plain, votes_plain, scenario_db, "A: как measure_manual (корпус по направлениям, база 18.09)"),
        ("B", kb_db, proxy_relabel, votes_relabel, scenario_db, "B: как measure_manual --relabel (корпус перемечен, база 18.09)"),
        ("C", kb_feed, proxy_plain, votes_plain, scenario_feed, "C: корпус по направлениям, база из посылки ERP %s" % feed.generated_at),
        ("D", kb_feed, proxy_relabel, votes_relabel, scenario_feed, "D: корпус перемечен, база из посылки ERP %s (ближе всего к бою)" % feed.generated_at),
    ]
    if args.only_live:
        # Главная цифра линейки это D. Остальные варианты нужны, когда надо
        # понять, чем бой отличается от прежних замеров, а для гейта выкладки
        # хватает одного D.
        variants = [v for v in variants if v[0] == "D"]
        say("--only-live: считаю только вариант D (боевая конфигурация)")

    rows_out = []
    for i, r in enumerate(rows):
        rows_out.append({
            "n": r["n"], "uid": r["uid"], "intent": r["intent"], "scenario": r["scenario"], "phrase": r["phrase"],
            "erp_equipment": r["equipment"], "content_words": len(content_words(r["phrase"])), "fold": fold_of[i],
            "rep_kb": int(has_repeat_marker_kb(r["phrase"])), "rep_corpus": int(is_repeat(r["phrase"])),
            "intent_pN": "%.3f" % proba[i, 0], "intent_pR": "%.3f" % proba[i, 1], "intent_pX": "%.3f" % proba[i, 2],
            "intent_pred": ("N", "R", "X")[int(np.argmax(proba[i]))],
        })

    summary = list(LOG)
    for code, kb, proxy, votes, scenario_of, title in variants:
        kb._corpus = proxy
        t0 = time.time()
        for i, r in enumerate(rows):
            text = r["phrase"]
            cw = len(content_words(text))
            vote = votes[i]
            row = rows_out[i]
            if isinstance(getattr(kb, "_intent", None), IntentProxy):
                # Вероятность повторного обращения для ЭТОЙ реплики, посчитанная
                # моделью с другого фолда (столбец intent_pR).
                kb._intent.current = float(proba[i, 1])
            # как measure_manual: только resolve_vector
            res, trusted, name, stage = resolve_row(kb, proxy, vote, text, test_vectors[i], cw, scenario_of, full=False)
            verdict = judge(r["intent"], r["scenario"], name, trusted)
            pb_rec, pb_score = phrase_best(kb, text, test_vectors[i])
            action, a_name = dialog_action(kb, text, res, scenario_of)
            p = code + "_"
            row.update({
                p + "stage": stage,
                p + "record": res.record.id if (res is not None and res.record is not None) else "",
                p + "record_question": (res.record.question if (res is not None and res.record is not None) else "")[:60],
                p + "answer": name or "",
                p + "score": "%.4f" % res.score if res is not None else "",
                p + "trusted": int(trusted),
                p + "vote_dir": vote.direction_id if vote is not None else "",
                p + "vote_conf": "%.3f" % vote.confidence if vote is not None else "",
                p + "top_sim": "%.3f" % vote.neighbours[0].score if (vote is not None and vote.neighbours) else "",
                p + "top_neighbour": (vote.neighbours[0].phrase[:60] + " [%d]" % vote.neighbours[0].direction_id) if (vote is not None and vote.neighbours) else "",
                p + "phrase_best": "%.4f" % pb_score,
                p + "phrase_best_record": pb_rec.id if pb_rec is not None else "",
                p + "phrase_best_scenario": (scenario_of(pb_rec) or "") if pb_rec is not None else "",
                p + "verdict": verdict,
                p + "dialog_action": action,
                p + "dialog_verdict": dialog_verdict(r["intent"], r["scenario"], action, a_name),
            })
            # полный resolve(): плюс текстовые стадии exact / keyword / category
            res_f, trusted_f, name_f, stage_f = resolve_row(kb, proxy, vote, text, test_vectors[i], cw, scenario_of, full=True)
            action_f, a_name_f = dialog_action(kb, text, res_f, scenario_of)
            row.update({
                p + "full_stage": stage_f,
                p + "full_record": res_f.record.id if (res_f is not None and res_f.record is not None) else "",
                p + "full_score": "%.4f" % res_f.score if res_f is not None else "",
                p + "full_answer": name_f or "",
                p + "full_verdict": judge(r["intent"], r["scenario"], name_f, trusted_f),
                p + "full_dialog_action": action_f,
                p + "full_dialog_verdict": dialog_verdict(r["intent"], r["scenario"], action_f, a_name_f),
                # Что бот ПРОИЗНЕСЁТ, а не куда переведёт. Без этих столбцов
                # правка произносимого текста в вердикт не попадает вовсе:
                # вердикт сравнивает направление (С1). Два столбца, потому что
                # полей записи, которые бот озвучивает, тоже два: уточняющий
                # вопрос и ответ на согласие.
                p + "full_spoken": spoken_question(res_f, action_f),
                p + "full_spoken_yes": spoken_positive(res_f, action_f),
                # Направление доверенного решения. У недоверенного запись тоже
                # есть, но звонок по ней не идёт, поэтому столбец пуст: иначе
                # его читают как «куда ушёл звонок» и ошибаются.
                p + "full_direction": (res_f.record.telephone_direction_id
                                       if (trusted_f and res_f.record is not None) else ""),
            })
        say("вариант %s прогнан за %.0f с" % (code, time.time() - t0))
        kb._corpus = None

    # таблица пишется сразу: сводки ниже её не теряют при любой ошибке
    cols = list(rows_out[0].keys())
    table_path = os.path.join(OUT_DIR, "manual_predictions.tsv")
    with io.open(table_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, delimiter="\t", lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        for row in rows_out:
            w.writerow(row)
    say("таблица записана: %s (%d строк, %d столбцов)" % (table_path, len(rows_out), len(cols)))

    def write_summary():
        io.open(os.path.join(OUT_DIR, "exp_per_row_summary.txt"), "w", encoding="utf-8").write("\n".join(summary))

    summary += intent_model_report(rows_out)
    conf_rows = []
    for code, kb, proxy, votes, scenario_of, title in variants:
        p = code + "_"
        try:
            lines, _ = judge_tally(rows_out, p, title + " [resolve_vector, как measure_manual]")
            summary += lines
            lines, _ = judge_tally(rows_out, p + "full_", title + " [полный resolve: + exact/keyword/category]")
            summary += lines
            summary += dialog_tally(rows_out, p + "full_", title)
            summary += stage_table(rows_out, p + "full_", title)
            summary += silence_breakdown(rows_out, p + "full_", title)
            summary += bins_table(rows_out, p + "full_", title)
            lines, mat = confusion(rows_out, p + "full_", title)
            summary += lines
            for (want, got), v in sorted(mat.items(), key=lambda kv: -kv[1]):
                conf_rows.append((code, want, got, v))
            summary += worst_examples(rows_out, p + "full_", title)
            if code == "D":
                summary += gates_what_if(rows_out, p + "full_", title)
        except Exception as exc:  # сводка не должна ронять прогон
            import traceback
            summary += ["", "!! сводка варианта %s упала: %r" % (code, exc), traceback.format_exc()]
        write_summary()

    with io.open(os.path.join(OUT_DIR, "exp_per_row_confusion.tsv"), "w", encoding="utf-8", newline="") as f:
        f.write("variant\twant\tgot\tn\n")
        for code, want, got, v in conf_rows:
            f.write("%s\t%s\t%s\t%d\n" % (code, want, got, v))

    # согласие вариантов: где A и D расходятся
    if not args.only_live:
        diff = collections.Counter()
        for r in rows_out:
            if r["intent"] == "X":
                continue
            diff[(r["A_full_verdict"].split(" ")[0], r["D_full_verdict"].split(" ")[0])] += 1
        summary += ["", "== A против D (N+R): вердикт A -> вердикт D =="]
        for (a, d), v in diff.most_common():
            summary.append("   %4d  %-10s -> %s" % (v, a, d))
    diff = collections.Counter()
    for r in rows_out:
        if r["intent"] == "X":
            continue
        diff[(r["D_verdict"].split(" ")[0], r["D_full_verdict"].split(" ")[0])] += 1
    summary += ["", "== D: только resolve_vector против полного resolve (N+R): вердикт -> вердикт =="]
    for (a, d), v in diff.most_common():
        summary.append("   %4d  %-10s -> %s" % (v, a, d))
    write_summary()

    # сверка с прежним прогоном
    if args.compare and os.path.exists(args.compare):
        prev = {}
        try:
            with io.open(args.compare, encoding="utf-8", newline="") as f:
                for pr in csv.DictReader(f, delimiter="\t"):
                    prev[pr["n"]] = pr
        except Exception as exc:
            import traceback
            summary += ["", "!! прежнюю таблицу не прочесть: %r" % exc, traceback.format_exc(),
                        "   прочитано строк до обрыва: %d, дальше обе сверки считают по ним"
                        % len(prev)]
        try:
            summary += compare_runs(rows_out, prev, args.compare)
            write_summary()
        except Exception as exc:
            import traceback
            summary += ["", "!! сверка упала: %r" % exc, traceback.format_exc()]
        # Вторая метрика считается по той же прежней таблице, но СВОИМ try:
        # она отвечает на другой вопрос, чем вердикт, и падение сверки
        # воспроизводимости не имеет права её уносить. Ровно так и вышло в
        # первом же прогоне 09.11: KeyError('A_full_verdict') съел метрику.
        try:
            summary += spoken_changes(
                rows_out, prev, "D_full_", "D живая посылка",
                os.path.join(OUT_DIR, "exp_spoken_changes.tsv"))
        except Exception as exc:
            import traceback
            summary += ["", "!! метрика С1 упала: %r" % exc, traceback.format_exc()]
        write_summary()
    else:
        # Без второго прогона метрика С1 не считается, и это надо сказать
        # вслух. Молчание здесь читается как «смен нет», а именно так мы
        # трижды за два дня и сказали «регресса нет».
        summary += ["", "== сменился ли произносимый вопрос (С1) ==",
                    "   НЕ СЧИТАНО: нужен второй прогон. Передай --compare <прежняя "
                    "manual_predictions.tsv>;", "   для правки данных до внесения в ERP прогон "
                    "идёт дважды: без --feed и с --feed."]
        if args.compare:
            summary.append("   прежней таблицы нет по пути %s" % args.compare)

    if not args.skip_sweeps:
        for code, kb, proxy, votes, scenario_of, title in variants:
            if code not in ("A", "D"):
                continue
            kb._corpus = proxy
            try:
                summary += sweep(kb, proxy, votes, rows, test_vectors, scenario_of, title, full=True)
            except Exception as exc:
                summary += ["", "!! развёртка варианта %s упала: %r" % (code, exc)]
            kb._corpus = None
            write_summary()

    summary.append("")
    summary.append("время: %.0f с" % (time.time() - t_start))
    write_summary()
    print("\n".join(summary[len(LOG):]), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
