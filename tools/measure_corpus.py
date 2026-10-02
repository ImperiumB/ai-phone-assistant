# coding=utf8
r"""Замер: сколько корпуса живых реплик бот угадывает нынешней базой знаний (UL-19020).

    py -3.12 tools/measure_corpus.py

Берёт ту же базу знаний, с которой сервис реально работал (кэш последней
принятой посылки), тот же эмбеддер и тот же порог — и прогоняет через них
реплики из dataset/corpus.jsonl, у которых оператор проставил тип
оборудования. Ответ считается верным, если сценарий найденной записи
совпадает со сценарием, к которому относится этот тип оборудования.

Сведение «тип оборудования -> сценарий бота» — по данным ERP, не по названиям:
  1. явная привязка типа к записи базы знаний (AI_KNOWLEDGE_BASE.EQUIPMENT_TYPE_ID);
  2. телефонное направление типа (EQUIPMENT_TYPES.TELEPHONE_DIRECTION_ID) ->
     сценарий с тем же направлением;
  3. то же по родителю типа (PARENT_ID), и так до корня.
Тип, который так и не свёлся, из замера выпадает и попадает в отчёт отдельно.

Пишет dataset/measure_<дата>.txt (читать) и .json (сравнивать между прогонами).
"""
from __future__ import annotations

import collections
import datetime as dt
import io
import json
import os
import sys
import time

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

DATASET_DIR = os.path.join(REPO, "dataset")
CORPUS_PATH = os.path.join(DATASET_DIR, "corpus.jsonl")
REFS_PATH = os.path.join(DATASET_DIR, "refs.tsv")
FEED_CACHE = os.path.join(REPO, "ai_assistant", "knowledge_feed_cache.json")

# Направление «Сопровождение»: на него смотрят сразу три сценария (жалобы
# и оператор), по нему тип оборудования к сценарию не привязать.
SUPPORT_DIRECTION = 17
THRESHOLDS = [0.55, 0.60, 0.62, 0.64, 0.66, 0.68, 0.70, 0.72, 0.75, 0.80]
MIN_PER_SCENARIO_REPORT = 30


def lower_priority():
    try:
        if os.name == "nt":
            import ctypes

            ctypes.windll.kernel32.SetPriorityClass(
                ctypes.windll.kernel32.GetCurrentProcess(), 0x00004000)
        else:
            os.nice(10)
    except Exception:
        pass


def load_refs():
    et, kb, sc = {}, {}, {}
    for line in io.open(REFS_PATH, encoding="utf-8").read().splitlines():
        p = line.split("\t")
        if p[0] == "ET" and len(p) >= 5:
            et[int(p[1])] = {
                "parent": int(p[2]) if p[2] else None,
                "direction": int(p[3]) if p[3] else None,
                "name": p[4],
            }
        elif p[0] == "KB" and len(p) >= 7:
            kb[int(p[1])] = {
                "scenario": int(p[2]) if p[2] else None,
                "equipment": int(p[3]) if p[3] else None,
                "from_bot": p[4] == "1",
                "has_question": p[5] == "1",
                "not_active": p[6] == "1",
            }
        elif p[0] == "SC" and len(p) >= 4:
            sc[int(p[1])] = {"direction": int(p[2]) if p[2] else None, "name": p[3]}
    return et, kb, sc


def build_equipment_to_scenario(et, kb, sc):
    """Тип оборудования -> сценарий. Возвращает карту по коду типа и журнал того, как свелось."""
    explicit = {}
    for rec in kb.values():
        if rec["equipment"] and rec["scenario"] and rec["has_question"] and not rec["not_active"]:
            explicit.setdefault(rec["equipment"], rec["scenario"])

    by_direction = collections.defaultdict(set)
    for sid, s in sc.items():
        if s["direction"] and s["direction"] != SUPPORT_DIRECTION:
            by_direction[s["direction"]].add(sid)

    def resolve(eq_id):
        seen = set()
        cur = eq_id
        while cur is not None and cur not in seen and cur in et:
            seen.add(cur)
            if cur in explicit:
                return explicit[cur], "привязка"
            d = et[cur]["direction"]
            if d in by_direction and len(by_direction[d]) == 1:
                return next(iter(by_direction[d])), "направление"
            cur = et[cur]["parent"]
        return None, "не свёлся"

    mapping, how = {}, collections.Counter()
    for eq_id in et:
        sid, why = resolve(eq_id)
        mapping[eq_id] = sid
        how[why] += 1
    return mapping, how


# Типы оборудования, у которых в ERP нет ни привязки к записи базы знаний, ни
# телефонного направления, — сведены руками (21.09.2026). Без этого 1 500
# реплик про плиты, системники и принтеры в индекс не попадали, и «у нас
# сломалась духовка» уходило в холодильники — ближайших соседей про духовки
# просто не было. Правильное место для этого — EQUIPMENT_TYPE_ID у записей
# AI_KNOWLEDGE_BASE (тогда и обработчик 15422 проставит тип в обращении);
# как только привязки появятся в ERP, этот список станет лишним.
MANUAL_SCENARIO_BY_NAME = {
    "Системный блок": 16, "MacBook": 16, "Моноблок": 16, "Сервер и Роутер": 16,
    "IMAC - (Моноблок Apple)": 16, "Mac mini": 16,
    "Духовые шкафы ремонт": 6, "Электроплиты ремонт": 6, "Плиты ремонт (ГАЗ-ЭЛЕКТР+СТОПЫ)": 6,
    "Духовые шкафы ремонт (ГАЗ-ЭЛЕКТР+СТОПЫ)": 6, "Вытяжки (ремонт)": 6,
    "Струйные принтеры - МФУ": 17, "МФУ": 17, "Оргтехника (КМТ)": 17, "Плоттеры": 17,
    "Встраиваемая СВЧ": 5, "СВЧ общее": 5,
    "Кухонные комбайны и блендеры": 10, "Мультиварки": 10, "Мясорубки": 10, "Парогенераторы": 10,
    "Смартфоны": 22, "Смартфон Xiaomi": 22, "Смартфон Huawei - Honor": 22, "Планшеты остальные модели": 22,
    "Планшеты Samsung": 20,
}


def name_to_scenario(et, mapping):
    """Корпус хранит название типа, а не код. Одно имя может стоять на нескольких
    кодах — берём его только если все коды сводятся к одному сценарию."""
    by_name = collections.defaultdict(set)
    for eq_id, e in et.items():
        by_name[e["name"]].add(mapping.get(eq_id))
    result, ambiguous = {}, []
    for name, sids in by_name.items():
        sids.discard(None)
        if len(sids) == 1:
            result[name] = next(iter(sids))
        elif len(sids) > 1:
            ambiguous.append(name)
    for name, sid in MANUAL_SCENARIO_BY_NAME.items():
        result.setdefault(name, sid)
    return result, ambiguous


def load_examples():
    rows = []
    for line in io.open(CORPUS_PATH, encoding="utf-8"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("status") == "ок" and r.get("phrase"):
            rows.append(r)
    return rows


def load_records_from_db_export(kb_path, phrases_path, sc, drop, rehome):
    """База знаний прямо из выгрузки ULTIMA.AI_KNOWLEDGE_BASE / AI_KB_PHRASES
    (sqlplus, поля через табуляцию) — с теми же условиями отбора, что в 15424.
    drop — записи выкинуть, rehome — {запись: сценарий} пересадить на другой
    сценарий без уточняющего вопроса (моделируем правку до её внесения в ERП)."""
    from ai_assistant.service.knowledge import KnowledgeRecord

    phrases = collections.defaultdict(list)
    for line in io.open(phrases_path, encoding="utf-8", errors="replace"):
        p = line.rstrip("\n").split("\t")
        if len(p) == 2:
            phrases[int(p[0])].append(p[1])
    records, scenario_of = [], {}
    for line in io.open(kb_path, encoding="utf-8", errors="replace"):
        p = line.rstrip("\n").split("\t")
        if len(p) < 8:
            continue
        rid, scenario_id, eq, from_bot, not_active, has_question = (int(x) for x in p[:6])
        if not_active or rid in drop or not (has_question or not from_bot):
            continue
        clarifying = p[7] if p[7] != "-" else ""
        if rid in rehome:
            scenario_id, clarifying = rehome[rid], ""
        if scenario_id not in sc:
            continue
        scenario_of[rid] = scenario_id
        records.append(KnowledgeRecord(
            id=rid, question=p[6], question_variants=phrases[rid],
            clarifying_question=clarifying, scenario=sc[scenario_id]["name"],
            equipment_type_id=eq,
            # Направление записи — как его вычисляет 15424: по сценарию.
            # Без него корпус не найдёт запись для своего голоса.
            telephone_direction_id=sc[scenario_id]["direction"] or 0))
    return records, scenario_of


def parse_args():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--kb", choices=["cache", "db"], default="cache",
                    help="cache — посылка, с которой работал сервис; db — выгрузка dataset/kb_now.tsv + kb_phrases_now.tsv")
    ap.add_argument("--drop", default="", help="записи выкинуть, через запятую")
    ap.add_argument("--rehome", default="", help="пересадить записи: 28:35,58:35")
    ap.add_argument("--phrases", default="", help="файл с репликами (по одной в строке) — прогнать их и показать ответ")
    ap.add_argument("--tag", default="", help="суффикс имени отчёта")
    ap.add_argument("--corpus-index", default="",
                    help="готовый индекс корпуса (ai_assistant/corpus_index.npz) — как в сервисе; для --phrases")
    ap.add_argument("--corpus-knn", action="store_true",
                    help="решение «корпус + формулировки» (KnowledgeBase.resolve), корпус — по 5 фолдам, "
                         "чтобы реплика не находила саму себя")
    ap.add_argument("--corpus-threshold", type=float, default=0.60)
    ap.add_argument("--corpus-k", type=int, default=15)
    return ap.parse_args()


# Повторное обращение: «мне звонил мастер», «я по заявке», «по гарантии» —
# такое должно уходить сразу на оператора, а не в предметный сценарий.
REPEAT_MARKERS = ("заяв", "заказ", "мастер приезжал", "мастер звонил", "мне звонил", "повторн",
                  "гарант", "уже был", "отмен", "статус", "когда приед", "перезвон", "сдал",
                  "сдавал", "забрал", "готовност", "ранее обращал", "уже обращал")
OPERATOR_SCENARIOS = {"Соединить с оператором", "Жалобы БТ", "Жалобы СЦ"}


def is_repeat(phrase):
    return any(m in phrase for m in REPEAT_MARKERS)


def measure_with_corpus(args, labeled, examples, knowledge, record_scenario, sc, kb_label, cfg):
    """Как решал бы сервис с корпусом: KnowledgeBase.resolve по каждой реплике.

    Корпус для реплики строится из четырёх пятых остальных (5 фолдов), иначе
    реплика нашла бы саму себя и цифра вышла бы дутой. Векторы — из кэша
    train_classifier (dataset/corpus_emb.npz), эмбеддер второй раз не гоняем.
    """
    from sklearn.model_selection import StratifiedKFold

    from ai_assistant.service.corpus_knn import OPERATOR_DIRECTION, CorpusIndex
    from train_classifier import embeddings_for

    # Метка направления для индекса: повторное → сопровождение, иначе направление сценария.
    rows = [(r["uid"], r["phrase"], r["equipment"]) for r in examples]
    by_uid = {u: (p, e) for u, p, e in rows}
    uids = [uid for uid, _, _ in rows if by_uid[uid][0] in {p for p, _, _ in labeled}]
    labeled_uids, labels, directions = [], [], []
    label_of_phrase = {p: sid for p, sid, _ in labeled}
    for uid, phrase, _ in rows:
        sid = label_of_phrase.get(phrase)
        if sid is None:
            continue
        labeled_uids.append(uid)
        labels.append(sid)
        directions.append(OPERATOR_DIRECTION if is_repeat(phrase) else sc[sid]["direction"])
    phrases = [by_uid[u][0] for u in labeled_uids]
    vectors = embeddings_for([(u, p, None) for u, p in zip(labeled_uids, phrases)])
    directions = np.array(directions)
    n = len(labeled_uids)
    print("корпус: %d реплик с направлением; %d фолдов" % (n, 5), flush=True)

    predicted, trusted, source = [None] * n, [False] * n, [""] * n
    strata = [str(d) for d in directions]
    for fold, (train, test) in enumerate(StratifiedKFold(5, shuffle=True, random_state=1).split(vectors, strata)):
        index = CorpusIndex(vectors[train], directions[train], [phrases[i] for i in train],
                            k=args.corpus_k, threshold=args.corpus_threshold)
        knowledge._corpus = index  # инструмент замера, сервис так не делает
        for i in test:
            res = knowledge.resolve_vector(vectors[i])
            if res is not None and res.record is not None:
                predicted[i] = record_scenario.get(res.record.id)
                trusted[i] = res.trusted
                source[i] = res.source
        print("  фолд %d/5" % (fold + 1), flush=True)
    knowledge._corpus = None

    tally = collections.Counter()
    by_source = collections.Counter()
    per_scenario = collections.defaultdict(lambda: [0, 0, 0])
    confusion = collections.Counter()
    for i in range(n):
        repeat = directions[i] == OPERATOR_DIRECTION
        answer_name = sc.get(predicted[i], {}).get("name")
        p = per_scenario[labels[i]]
        p[0] += 1
        if not trusted[i]:
            tally["молчит (повторное)" if repeat else "молчит"] += 1
            continue
        by_source[source[i]] += 1
        p[1] += 1
        if answer_name in OPERATOR_SCENARIOS:
            tally["оператор — верно (повторное)" if repeat else "оператор — лишний перевод"] += 1
            if repeat:
                p[2] += 1
        elif predicted[i] == labels[i]:
            tally["сценарий верно"] += 1
            p[2] += 1
        else:
            tally["не туда"] += 1
            confusion[(sc[labels[i]]["name"], answer_name or "?")] += 1

    answered = sum(v for k, v in tally.items() if not k.startswith("молчит"))
    right = tally["сценарий верно"] + tally["оператор — верно (повторное)"]
    out = ["ЗАМЕР С КОРПУСОМ %s" % dt.datetime.now().isoformat(timespec="seconds"),
           "база знаний: %s | корпус %d реплик, k=%d, порог уверенности %.2f, порог близости %.2f"
           % (kb_label, n, args.corpus_k, args.corpus_threshold, cfg.similarity_threshold),
           "",
           "ИТОГ: ответил на %.1f%%, из них верно %.1f%% (оператор без маркеров считается лишним переводом)"
           % (100 * answered / n, 100 * right / max(1, answered)),
           "решал корпус: %d, формулировки: %d" % (by_source["corpus"], by_source["phrases"]),
           ""]
    for key in ("сценарий верно", "оператор — верно (повторное)", "оператор — лишний перевод",
                "не туда", "молчит", "молчит (повторное)"):
        out.append("  %-32s %6d  %5.1f%%" % (key, tally[key], 100 * tally[key] / n))
    out.append("")
    out.append("ПО СЦЕНАРИЯМ (не меньше %d реплик): всего / ответил / верно" % MIN_PER_SCENARIO_REPORT)
    for sid, (tot, ans, ok) in sorted(per_scenario.items(), key=lambda kv: -kv[1][0]):
        if tot >= MIN_PER_SCENARIO_REPORT:
            out.append("  %-34s %5d  %5.0f%%  %5.0f%%" % (sc[sid]["name"][:34], tot, 100 * ans / tot, 100 * ok / tot))
    out.append("")
    out.append("КУДА УВОДИТ ЧАЩЕ ВСЕГО:")
    for (a, b), v in confusion.most_common(10):
        out.append("  %5d   %-30s -> %s" % (v, a[:30], b[:30]))
    text = "\n".join(out)
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M") + "_knn" + (("_" + args.tag) if args.tag else "")
    io.open(os.path.join(DATASET_DIR, "measure_%s.txt" % stamp), "w", encoding="utf-8").write(text)
    print(text, flush=True)
    return 0


def main():
    lower_priority()
    args = parse_args()
    drop = {int(x) for x in args.drop.split(",") if x.strip()}
    rehome = {int(a): int(b) for a, b in (x.split(":") for x in args.rehome.split(",") if x.strip())}
    started = time.time()
    et, kb, sc = load_refs()
    mapping, how = build_equipment_to_scenario(et, kb, sc)
    names, ambiguous = name_to_scenario(et, mapping)
    print("типов оборудования: %d | свелось: %s" % (len(et), dict(how)), flush=True)

    examples = load_examples()
    labeled, unmapped = [], collections.Counter()
    for r in examples:
        sid = names.get(r["equipment"])
        if sid is None:
            unmapped[r["equipment"]] += 1
        else:
            labeled.append((r["phrase"], sid, r["equipment"]))
    print("реплик в корпусе: %d | с меткой сценария: %d | без: %d"
          % (len(examples), len(labeled), len(examples) - len(labeled)), flush=True)

    # База знаний — ровно та, с которой работал сервис.
    from ai_assistant.service.config import load_config
    from ai_assistant.service.knowledge import (
        QUERY_PREFIX, KnowledgeBase, SentenceTransformerEmbedder)
    from ai_assistant.service.knowledge_feed import parse_feed

    cfg = load_config()
    if args.kb == "db":
        kb_records, record_scenario = load_records_from_db_export(
            os.path.join(DATASET_DIR, "kb_now.tsv"), os.path.join(DATASET_DIR, "kb_phrases_now.tsv"),
            sc, drop, rehome)
        kb_label = "выгрузка из БД"
    else:
        feed = parse_feed(json.load(io.open(FEED_CACHE, encoding="utf-8")))
        kb_records = [r for r in feed.records if r.id not in drop]
        record_scenario = {rid: rec["scenario"] for rid, rec in kb.items()}
        for r in kb_records:
            if r.id in rehome:
                r.scenario, r.clarifying_question = sc[rehome[r.id]]["name"], ""
                record_scenario[r.id] = rehome[r.id]
        kb_label = "посылка от %s" % feed.generated_at
    if drop or rehome:
        kb_label += " (убраны %s, пересажены %s)" % (sorted(drop) or "-", rehome or "-")
    print("%s, записей %d | эмбеддер %s | порог %.2f"
          % (kb_label, len(kb_records), cfg.embedder_model, cfg.similarity_threshold), flush=True)
    t0 = time.time()
    embedder = SentenceTransformerEmbedder(cfg.embedder_model)
    corpus_index = None
    if args.corpus_index:
        from ai_assistant.service.corpus_knn import CorpusIndex
        corpus_index = CorpusIndex.load(args.corpus_index, k=args.corpus_k, threshold=args.corpus_threshold)
        print("индекс корпуса: %d реплик, k=%d, порог %.2f"
              % (len(corpus_index), corpus_index.k, corpus_index.threshold), flush=True)
    knowledge = KnowledgeBase(kb_records, embedder, cfg.similarity_threshold, corpus=corpus_index)
    print("база знаний загружена за %.0f с, формулировок в индексе: %d"
          % (time.time() - t0, len(knowledge._phrases)), flush=True)

    if args.phrases:
        # Режим «прогнать список реплик»: ровно то решение, что принял бы сервис.
        for line in io.open(args.phrases, encoding="utf-8"):
            phrase = line.strip()
            if not phrase or phrase.startswith("#"):
                print(line.rstrip("\n"))
                continue
            res = knowledge.resolve(phrase)
            if res is None or res.record is None:
                print("  ??    %s" % phrase)
                continue
            rec = res.record
            if args.kb == "cache":
                # В посылке scenario — служебная константа, имя берём по направлению записи.
                by_direction = {s["direction"]: s["name"] for s in sc.values()}
                scenario = "Оператор" if rec.telephone_direction_id == 17 else by_direction.get(rec.telephone_direction_id, "?")
            else:
                scenario = sc.get(record_scenario.get(rec.id), {}).get("name", "?")
            who = ("корпус %.2f" % res.vote.confidence) if res.source == "corpus" else ("фраза %.2f" % res.score)
            verdict = "ОТВЕТ " if res.trusted else "молчит"
            top = res.vote.neighbours[0].phrase if res.vote and res.vote.neighbours else ""
            print("  %s %-11s %-24s #%-3d %s <- %s%s" % (
                verdict, who, scenario[:24], rec.id,
                "сразу перевод " if not rec.clarifying_question else "уточн. вопрос ",
                phrase[:64], ("   [сосед: %s]" % top[:45]) if top else ""))
        return 0

    if args.corpus_knn:
        return measure_with_corpus(args, labeled, examples, knowledge, record_scenario, sc, kb_label, cfg)

    feed_records = kb_records
    owners = knowledge._phrase_owners
    vectors = knowledge._vectors

    # Считаем один раз пачками, а не по одной реплике: 13 тысяч запросов по
    # одному — это десятки минут, пачками — минуты.
    t0 = time.time()
    phrases = [QUERY_PREFIX + p for p, _, _ in labeled]
    scores_best, predicted, hit_record, hit_phrase = [], [], [], []
    for i in range(0, len(phrases), 256):
        q = embedder.encode(phrases[i:i + 256])
        s = q @ vectors.T
        idx = s.argmax(axis=1)
        scores_best.extend(s[np.arange(len(idx)), idx].tolist())
        predicted.extend(record_scenario.get(owners[j].id) for j in idx)
        hit_record.extend(owners[j].id for j in idx)
        hit_phrase.extend(knowledge._phrases[j] for j in idx)
        if (i // 256) % 10 == 0:
            print("  %d/%d" % (min(i + 256, len(phrases)), len(phrases)), flush=True)
    print("реплики прогнаны за %.0f с" % (time.time() - t0), flush=True)

    labels = [sid for _, sid, _ in labeled]
    n = len(labels)
    results = {"generated_at": dt.datetime.now().isoformat(timespec="seconds"),
               "knowledge": kb_label, "records": len(kb_records),
               "phrases_in_index": len(knowledge._phrases), "examples": n,
               "unmapped_examples": len(examples) - n, "thresholds": {}}

    for th in THRESHOLDS:
        above = [i for i in range(n) if scores_best[i] >= th]
        correct = sum(1 for i in above if predicted[i] == labels[i])
        wrong = len(above) - correct
        results["thresholds"]["%.2f" % th] = {
            "coverage": len(above) / n,          # доля реплик, по которым бот вообще ответил
            "precision": correct / max(1, len(above)),  # из ответивших — верно
            "correct_total": correct / n,       # верно от всех реплик
            "confident_wrong_total": wrong / n, # уверенно не туда от всех — самое опасное
        }

    th = cfg.similarity_threshold
    above = [i for i in range(n) if scores_best[i] >= th]

    # Правило заказчик: повторное обращение должно уходить на оператора, и это
    # верный ответ независимо от типа оборудования в документе.
    tally = collections.Counter()
    for i in range(n):
        answer_name = sc.get(predicted[i], {}).get("name")
        repeat = is_repeat(labeled[i][0])
        if scores_best[i] < th:
            tally["молчит (повторное)" if repeat else "молчит"] += 1
        elif answer_name in OPERATOR_SCENARIOS:
            tally["оператор — верно (повторное)" if repeat else "оператор — лишний перевод"] += 1
        elif predicted[i] == labels[i]:
            tally["сценарий верно"] += 1
        else:
            tally["не туда"] += 1
    results["by_rule"] = dict(tally)

    confusion = collections.Counter(
        (sc[labels[i]]["name"], sc.get(predicted[i], {}).get("name", "?"))
        for i in above if predicted[i] != labels[i])
    per_scenario = collections.defaultdict(lambda: [0, 0, 0])  # всего, ответил, верно
    for i in range(n):
        p = per_scenario[labels[i]]
        p[0] += 1
        if scores_best[i] >= th:
            p[1] += 1
            if predicted[i] == labels[i]:
                p[2] += 1

    out = []
    out.append("ЗАМЕР %s" % results["generated_at"])
    out.append("база знаний: %s, %d записей, %d формулировок в индексе"
               % (kb_label, len(kb_records), len(knowledge._phrases)))
    out.append("реплик с меткой: %d (без метки выпало %d)" % (n, len(examples) - n))
    out.append("")
    out.append("ПОРОГ   ответил   из них верно   верно от всех   уверенно не туда")
    for key, m in results["thresholds"].items():
        mark = "  <- текущий" if float(key) == th else ""
        out.append("%s    %5.1f%%      %5.1f%%         %5.1f%%          %5.1f%%%s" % (
            key, 100 * m["coverage"], 100 * m["precision"],
            100 * m["correct_total"], 100 * m["confident_wrong_total"], mark))
    out.append("")
    out.append("ПО ПРАВИЛУ «ПОВТОРНОЕ -> ОПЕРАТОР» (порог %.2f):" % th)
    for key in ("сценарий верно", "оператор — верно (повторное)", "оператор — лишний перевод",
                "не туда", "молчит", "молчит (повторное)"):
        out.append("  %-32s %6d  %5.1f%%" % (key, tally[key], 100 * tally[key] / n))
    out.append("")
    out.append("КУДА УВОДИТ ЧАЩЕ ВСЕГО (порог %.2f, метка -> ответ бота):" % th)
    for (a, b), v in confusion.most_common(12):
        out.append("  %5d   %-30s -> %s" % (v, a[:30], b[:30]))
    out.append("")
    out.append("ПО СЦЕНАРИЯМ (не меньше %d реплик): всего / ответил / верно" % MIN_PER_SCENARIO_REPORT)
    for sid, (tot, ans, ok) in sorted(per_scenario.items(), key=lambda kv: -kv[1][0]):
        if tot >= MIN_PER_SCENARIO_REPORT:
            out.append("  %-34s %5d  %5.0f%%  %5.0f%%" % (
                sc[sid]["name"][:34], tot, 100 * ans / tot, 100 * ok / tot))
    # Какие записи базы знаний собирают чужие реплики — и через какую формулировку.
    record_question = {r.id: r.question for r in kb_records}
    wrong_by_record = collections.Counter(hit_record[i] for i in above if predicted[i] != labels[i])
    right_by_record = collections.Counter(hit_record[i] for i in above if predicted[i] == labels[i])
    out.append("")
    out.append("ЗАПИСИ-ПЫЛЕСОСЫ (порог %.2f): запись / чужих / своих / формулировка-магнит" % th)
    for rid, wrong in wrong_by_record.most_common(10):
        magnet = collections.Counter(
            hit_phrase[i] for i in above if hit_record[i] == rid and predicted[i] != labels[i])
        top_phrase, top_n = magnet.most_common(1)[0]
        out.append("  #%-3d %-42s %5d %5d   «%s» (%d)" % (
            rid, record_question.get(rid, "?")[:42], wrong, right_by_record.get(rid, 0),
            top_phrase[:50], top_n))
    out.append("")
    out.append("НЕ СВЕЛИСЬ К СЦЕНАРИЮ (топ типов оборудования):")
    for name, v in unmapped.most_common(12):
        out.append("  %5d   %s" % (v, name[:50]))
    if ambiguous:
        out.append("  имена на нескольких кодах с разными сценариями: %s" % ", ".join(ambiguous[:6]))
    out.append("")
    out.append("время: %.0f с" % (time.time() - started))

    results["confusion_top"] = [[a, b, v] for (a, b), v in confusion.most_common(30)]
    results["per_scenario"] = {sc[s]["name"]: v for s, v in per_scenario.items()}
    results["unmapped_top"] = unmapped.most_common(30)
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M") + (("_" + args.tag) if args.tag else "")
    # Пореплично — чтобы дальше разбирать без повторного прогона эмбеддера.
    with io.open(os.path.join(DATASET_DIR, "measure_%s_details.jsonl" % stamp), "w", encoding="utf-8") as f:
        for i in range(n):
            f.write(json.dumps({
                "phrase": labeled[i][0], "equipment": labeled[i][2],
                "label": sc[labels[i]]["name"],
                "answer": sc.get(predicted[i], {}).get("name"),
                "record": hit_record[i], "matched": hit_phrase[i],
                "score": round(scores_best[i], 4),
            }, ensure_ascii=False) + "\n")
    io.open(os.path.join(DATASET_DIR, "measure_%s.txt" % stamp), "w", encoding="utf-8").write("\n".join(out))
    json.dump(results, io.open(os.path.join(DATASET_DIR, "measure_%s.json" % stamp), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("\n".join(out), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
