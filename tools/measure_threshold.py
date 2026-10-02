# -*- coding: utf-8 -*-
"""Замер порога близости: где проходит граница между «нашли тему» и «модель
просто вернула ближайшую строку».

Запускать после каждой правки базы знаний. Порог — не константа проекта, а
свойство конкретной базы: синонимы поднимают близость своей темы, новые темы
теснее прижимаются друг к другу, и зазор между «своим» и «чужим» гуляет.
Оставленный на глаз порог 20.08.2026 привёл к тому, что клиент, спросивший
про ремонт пиццы, услышал уверенный вопрос про посудомоечную машину.

    py -3 tools/measure_threshold.py [путь_к_кэшу_базы]

По умолчанию берётся ai_assistant/knowledge_feed_cache.json — та самая база,
которую сервис получил из ERP последней посылкой.
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import numpy as np  # noqa: E402

from ai_assistant.service.knowledge import (  # noqa: E402
    QUERY_PREFIX, KnowledgeBase, KnowledgeRecord, SentenceTransformerEmbedder,
)

DEFAULT_FEED = os.path.join(BASE, "ai_assistant", "knowledge_feed_cache.json")

# Заведомо посторонние вопросы: ни один не должен находить тему. Нарочно из
# разных областей — от бытовых до деловых, чтобы шумовой пол мерился не по
# одной случайной фразе.
OUTSIDERS = [
    "здравствуйте как починить пиццу",
    "я не понимаю как мне починить пиццу",
    "хочу заказать такси до аэропорта",
    "какая завтра погода в москве",
    "подскажите пожалуйста номер вашего директора",
    "у меня кот залез на дерево",
    "сколько стоит билет на самолёт",
    "я хочу устроиться к вам на работу",
    "мне нужна справка из налоговой",
    "где ближайшая аптека",
]

# Живая речь по темам, которые в базе есть, — с приветствиями и мусором, как
# говорят в трубку. Дословных совпадений с базой тут быть не должно: иначе
# замер меряет сам себя. Совпавшие помечаются в выводе.
INSIDERS = [
    # Короткая просьба о ремонте без описания поломки. Этот класс фраз стоит
    # первым не случайно: 20.08.2026 замер состоял из одних развёрнутых
    # жалоб на технику, показал зазор 0.643-0.716, порог выставили 0.68 — и
    # тем же вечером живой клиент сказал «ремонт стиральной машины» (0.6768)
    # и уехал на сопровождение. Мерить надо и то, как просят ремонт, а не
    # только то, как описывают поломку.
    "ремонт стиральной машины",
    "ремонт холодильника",
    "ремонт посудомоечной машины",
    "ремонт телевизора",
    "ремонт духовки",
    "ремонт ноутбука",
    "ремонт кофемашины",
    "ремонт микроволновки",
    "ремонт пылесоса",
    "ремонт кондиционера",
    "ремонт бойлера",
    "ремонт швейной машинки",
    "здравствуйте у меня стиралка перестала отжимать",
    "добрый день холодильник совсем не холодит что делать",
    "у меня тут посудомойка воду не сливает",
    "телек не хочет включаться уже второй день",
    "духовой шкаф перестал нагреваться",
    "кондиционер вместо холода гонит тёплый воздух",
    "свч печка искрит когда работает",
    "ноут перестал брать зарядку",
    "пылесос гудит но не тянет",
    "кофемашина перестала наливать кофе",
]

THRESHOLDS = (0.64, 0.66, 0.68, 0.70, 0.72, 0.75)


def load_base(feed_path):
    feed = json.load(open(feed_path, encoding="utf-8"))
    records = [
        KnowledgeRecord(
            id=row.get("id", 0),
            question=row.get("question", ""),
            # В посылке ERP синонимы лежат под ключом phrases, в файле базы
            # первого этапа — под question_variants. Читаем оба.
            question_variants=row.get("phrases") or row.get("question_variants") or [],
            clarifying_question=row.get("clarifying_question", ""),
            equipment_type=row.get("equipment_type", ""),
        )
        for row in feed["records"]
    ]
    embedder = SentenceTransformerEmbedder("ai-forever/ru-en-RoSBERTa")
    return KnowledgeBase(records, embedder, threshold=0.0), feed


def winning_phrase(base, probe):
    """Формулировка, которая сработала, — а не тема-владелец.

    Разбирать промахи без неё нельзя: тема может быть про посудомойку, а
    притянула звонок обобщённая фраза «почините посудомоечную машину», к
    которой липнет любое «починить что угодно».
    """
    query = base._embedder.encode([QUERY_PREFIX + probe])[0]
    return base._phrases[int(np.argmax(base._vectors @ query))]


def report(base, title, probes):
    print("\n=== {0} ===".format(title))
    scores = []
    for probe in probes:
        match = base.best_match(probe)
        if match is None:
            print("  ----    {0!r} — база пуста".format(probe))
            continue
        record, score = match
        scores.append(score)
        verbatim = "  [ЕСТЬ В БАЗЕ ДОСЛОВНО — замер меряет сам себя]" if probe in base._phrases else ""
        print("  {0:.4f}  {1!r}{2}".format(score, probe, verbatim))
        print("          тема: {0!r}".format(record.question))
        print("          сработала формулировка: {0!r}".format(winning_phrase(base, probe)))
    if scores:
        print("  min {0:.4f}   max {1:.4f}   среднее {2:.4f}".format(
            min(scores), max(scores), sum(scores) / len(scores)))
    return scores


def main():
    feed_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_FEED
    base, feed = load_base(feed_path)
    print("База: {0}".format(feed_path))
    print("Тем: {0}, формулировок в поиске: {1}, посылка от {2}".format(
        len(feed["records"]), len(base._phrases), feed.get("generated_at", "?")))

    outside = report(base, "ПОСТОРОННИЕ (должны НЕ находиться)", OUTSIDERS)
    inside = report(base, "СВОИ (должны находиться)", INSIDERS)
    if not outside or not inside:
        return

    print("\n=== порог ===")
    noise, weakest = max(outside), min(inside)
    print("  шумовой пол (максимум по посторонним): {0:.4f}".format(noise))
    print("  слабейшее своё:                        {0:.4f}".format(weakest))
    if weakest <= noise:
        print("  ЗАЗОРА НЕТ: чужие вопросы забираются выше своих. Порогом это не")
        print("  чинится — надо разбирать формулировки, которые притянули чужое.")
    else:
        print("  зазор {0:.4f}-{1:.4f}, середина {2:.4f}".format(
            noise, weakest, (noise + weakest) / 2))
    for threshold in THRESHOLDS:
        print("  порог {0:.2f}: пролезло чужих {1}/{2}, потеряно своих {3}/{4}".format(
            threshold,
            sum(1 for s in outside if s >= threshold), len(outside),
            sum(1 for s in inside if s < threshold), len(inside)))


if __name__ == "__main__":
    main()
