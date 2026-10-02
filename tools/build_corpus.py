# coding=utf8
r"""Сбор корпуса «реплика клиента -> тема» из архива записей разговоров (UL-19020).

Зачем: бот узнаёт тему по примерам, а их в справочнике 61 штука на 34 темы —
у 30 тем ровно по одному. Отсюда промахи вида «ремонт холодильника» ->
«жалоба на сервисный центр». Корпус строится из того, что уже есть: записи
разговоров плюс тип оборудования, который оператор проставил в обращении, —
то есть разметка берётся готовой, руками её делать не надо.

    py -3.12 tools/build_corpus.py --workers 4

Прогон рассчитан на ночь и на обрывы: каждая обработанная запись сразу
дописывается в файл, при повторном запуске уже разобранные пропускаются.
Остановить можно в любой момент (Ctrl+C) — продолжится с того же места.

Вход  — dataset/calls.tsv, выгрузка из ERP (см. sql в шапке export_calls).
Выход — dataset/corpus.jsonl, по одной записи в строке.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
import wave
from concurrent.futures import ProcessPoolExecutor, as_completed

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

DATASET_DIR = os.path.join(REPO, "dataset")
CALLS_PATH = os.path.join(DATASET_DIR, "calls.tsv")
CORPUS_PATH = os.path.join(DATASET_DIR, "corpus.jsonl")
STEREO_ROOT = r"\\10.20.0.13\stereo"

# Сколько секунд от начала разговора вообще смотрим. Повод обращения клиент
# называет в первых репликах; дальше идёт оформление заказа, и для корпуса
# оно бесполезно.
HEAD_SECONDS = 45
PAUSE_MS = 700
SILENCE_TIMEOUT_MS = 15000
MIN_CALL_SECONDS = 3

# Распознавание — самая дорогая часть, и на звонок его тратится
# PROBE_UTTERANCES * 2 + MAX_CLIENT_SEARCH раз.
#
# Урезание до 1 и 3 пробовали 17.09.2026 и откатили: скорость выросла с 2,2 до
# 1,32 с на звонок, но выход упал с 34% до 20% — примеров в час ровно столько
# же. А звонков в архиве конечное число, и выжать из каждого больше важнее,
# чем пробежать быстрее. Уменьшать эти числа ради скорости бессмысленно.
PROBE_UTTERANCES = 2
MAX_CLIENT_SEARCH = 5

# Автоинформаторы площадок — звучат до того, как кто-либо поздоровался.
IVR_MARKS = [
    "звонок по объявлению", "разговор может быть записан", "вам звонок из яндекс",
    "авито", "если у вас вопрос по гарантии", "ваша техника передана",
    "все операторы заняты", "оставайтесь на линии", "ваш звонок очень важен",
]

# Живой оператор своими словами: спрашивает, уточняет, обещает соединить.
OPERATOR_MARKS = [
    "подскажите", "назовите", "уточните", "продиктуйте", "соединю", "соединим",
    "переведу", "переключу", "оформим", "оформлю", "чем могу", "какой у вас вопрос",
    "с какого номера", "по поводу вашего", "ваш заказ", "номер заказа", "минуточку",
    "оставайтесь", "я вас слушаю", "слушаю вас", "что у вас случилось",
    "вы обращались", "мы вам звонили", "вам удобно", "записываю",
]

# Клиент, наоборот, говорит о себе.
CLIENT_MARKS = [
    " я ", "я ", " мне", "мне ", "у меня", " мой", " моя", " мою", " моего",
    "я оставля", "я заказыв", "я звонил", "я хочу", "мне нужен", "мне нужна",
    "нам нужно", "у нас ", "вы ремонтируете",
]

GREETINGS = {"алло", "але", "да", "ага", "угу", "здравствуйте", "здравствуй",
             "добрый", "день", "вечер", "утро", "доброе", "привет", "слушаю"}

# По этим словам видно, что клиент назвал повод обращения.
TOPIC_MARKS = [
    "ремонт", "почин", "сломал", "не работа", "не включ", "не греет", "не морозит",
    "не сушит", "не отжим", "течет", "течёт", "потек", "потёк", "засор", "разбил",
    "установ", "подключ", "настро", "замен", "мастер", "вызва", "диагностик",
    "уборк", "клининг", "обработ", "дезинсек", "ветеринар", "мрт", "окно", "окон",
    "сантехник", "электрик", "мебел", "интернет", "домофон", "форсунк", "жалоб",
    "гаранти", "заказ", "заявк", "не заряж", "не показыв", "не печата",
]

_engine = None
_detector = None
_bot_marks = None


def _lower_priority():
    """Ниже обычного, чтобы не отнимать процессор у боевого сервиса."""
    try:
        if os.name == "nt":
            import ctypes

            BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            ctypes.windll.kernel32.SetPriorityClass(handle, BELOW_NORMAL_PRIORITY_CLASS)
        else:
            os.nice(10)
    except Exception:
        # Не вышло — не повод не собирать корпус.
        pass


def _bot_phrase_marks():
    """Фразы обоих ботов — из группы линий, а не из головы."""
    marks = set(IVR_MARKS)
    path = os.path.join(DATASET_DIR, "bot_phrases.txt")
    if os.path.exists(path):
        for line in io.open(path, encoding="utf-8").read().splitlines():
            words = [w for w in line.lower().replace(",", " ").replace(".", " ")
                     .replace("?", " ").replace("!", " ").split() if len(w) > 2]
            if len(words) >= 4:
                marks.add(" ".join(words[:4]))
    return sorted(marks)


def _init_worker(torch_threads):
    """Своя модель на процесс: делить её между потоками нельзя.

    Приоритет процесса опускаем ниже обычного. На этой же машине работает
    боевой речевой сервис, и живой звонок всегда важнее сбора корпуса:
    при нехватке процессора планировщик должен отдавать его сервису.
    """
    global _engine, _detector, _bot_marks
    import torch

    _lower_priority()
    torch.set_num_threads(torch_threads)
    from ai_assistant.service.stt.base import create_engine
    from ai_assistant.service.vad import SileroVoiceDetector

    _engine = create_engine("gigaam", model_name="v3_rnnt")
    _detector = SileroVoiceDetector()
    _bot_marks = _bot_phrase_marks()


def _is_bot(text):
    t = " ".join(text.lower().split())
    return any(m in t for m in _bot_marks)


def _speaker_score(texts):
    """Больше — больше похоже на оператора, меньше — на клиента."""
    joined = " " + " ".join(t.lower() for t in texts if t) + " "
    score = sum(3 for t in texts if t and _is_bot(t))
    score += sum(2 for m in OPERATOR_MARKS if m in joined)
    score -= sum(1 for m in CLIENT_MARKS if m in joined)
    return score


def _is_meaningful(text):
    t = " ".join(text.lower().split())
    words = [w for w in t.replace(",", " ").split() if w]
    if len(words) < 3 or _is_bot(t):
        return False
    if all(w in GREETINGS for w in words):
        return False
    return any(m in t for m in TOPIC_MARKS)


def _read_stereo(path):
    with wave.open(path, "rb") as w:
        if w.getnchannels() != 2:
            raise IOError("не стерео")
        rate = w.getframerate()
        frames = w.readframes(min(w.getnframes(), int(rate * HEAD_SECONDS)))
    left, right = bytearray(), bytearray()
    for i in range(0, len(frames) - 3, 4):
        left += frames[i:i + 2]
        right += frames[i + 2:i + 4]
    return bytes(left), bytes(right), rate


def _utterances(pcm, rate, limit):
    from ai_assistant.service.vad import UtteranceSegmenter

    seg = UtteranceSegmenter(_detector.clone(), PAUSE_MS, SILENCE_TIMEOUT_MS, rate)
    out, step = [], int(rate * 0.32) * 2
    for off in range(0, len(pcm), step):
        for ev in seg.feed(pcm[off:off + step]):
            if ev.kind == "utterance" and ev.pcm:
                out.append(ev.pcm)
                if len(out) >= limit:
                    return out
    return out


def _say(pcm, rate):
    from ai_assistant.service.stt.base import pad_short_utterance, prepare_audio

    try:
        audio = prepare_audio(pad_short_utterance(pcm, rate), _engine.target_sample_rate)
        return _engine.transcribe(audio).strip()
    except Exception:
        return ""


def process_call(row):
    """Одна запись. Возвращает словарь — он же строка будущего корпуса."""
    uid, doc, date, equipment, direction = row
    base = {"uid": uid, "doc": doc, "equipment": equipment, "direction": direction}
    y, m, d = date.split("-")
    path = os.path.join(STEREO_ROOT, y, m, d, uid + ".wav")

    try:
        left, right, rate = _read_stereo(path)
    except Exception:
        return dict(base, status="нет записи")

    if max(len(left), len(right)) / 2 / rate < MIN_CALL_SECONDS:
        return dict(base, status="короткий")

    probes = [[_say(p, rate) for p in _utterances(t, rate, PROBE_UTTERANCES)]
              for t in (left, right)]
    if not any(probes[0] + probes[1]):
        return dict(base, status="тишина")

    score = [_speaker_score(t) for t in probes]
    if score[0] == score[1]:
        # Ничья: оператор обычно заговаривает первым и говорит длиннее.
        client_idx = 1 if len("".join(probes[0])) >= len("".join(probes[1])) else 0
    else:
        client_idx = 0 if score[0] < score[1] else 1

    for pcm in _utterances((left, right)[client_idx], rate, MAX_CLIENT_SEARCH):
        text = _say(pcm, rate)
        if _is_meaningful(text) and _speaker_score([text]) <= 0:
            return dict(base, status="ок", phrase=text, channel="LR"[client_idx])

    return dict(base, status="без темы")


def load_calls():
    rows = []
    for line in io.open(CALLS_PATH, encoding="utf-8").read().splitlines():
        parts = line.split("\t")
        if len(parts) == 5:
            rows.append(tuple(parts))
    return rows


def load_done():
    """Что уже разобрано — чтобы продолжить с места обрыва, а не с нуля."""
    done = set()
    if os.path.exists(CORPUS_PATH):
        for line in io.open(CORPUS_PATH, encoding="utf-8"):
            try:
                done.add(json.loads(line)["uid"])
            except Exception:
                continue
    return done


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--torch-threads", type=int, default=2,
                        help="потоков torch на процесс; workers*threads <= ядер")
    parser.add_argument("--limit", type=int, default=0, help="0 — все")
    args = parser.parse_args(argv)

    os.makedirs(DATASET_DIR, exist_ok=True)
    rows = load_calls()
    done = load_done()
    todo = [r for r in rows if r[0] not in done]
    if args.limit:
        todo = todo[:args.limit]

    print("всего звонков: %d | уже разобрано: %d | в работе: %d"
          % (len(rows), len(done), len(todo)), flush=True)
    if not todo:
        return 0

    stats, started = {}, time.time()
    out = io.open(CORPUS_PATH, "a", encoding="utf-8")
    try:
        with ProcessPoolExecutor(max_workers=args.workers,
                                 initializer=_init_worker,
                                 initargs=(args.torch_threads,)) as pool:
            futures = {pool.submit(process_call, r): r for r in todo}
            for n, fut in enumerate(as_completed(futures), 1):
                try:
                    rec = fut.result()
                except Exception as error:
                    rec = {"uid": futures[fut][0], "status": "ошибка: %s" % error}
                stats[rec["status"]] = stats.get(rec["status"], 0) + 1
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                if n % 200 == 0:
                    out.flush()
                    speed = n / max(1e-6, time.time() - started)
                    left = (len(todo) - n) / max(1e-6, speed) / 3600
                    print("  %d/%d | %.1f зв/с | осталось ~%.1f ч | ок: %d"
                          % (n, len(todo), speed, left, stats.get("ок", 0)), flush=True)
    except KeyboardInterrupt:
        print("\nостановлено, разобранное сохранено", flush=True)
    finally:
        out.close()

    print("\n=== ИТОГ ===", flush=True)
    for key in sorted(stats, key=lambda k: -stats[k]):
        print("%-14s %d" % (key, stats[key]))
    spent = time.time() - started
    print("время: %.0f с (%.2f ч) | %.2f с на звонок | %.2f зв/с"
          % (spent, spent / 3600, spent / max(1, len(todo)), len(todo) / max(1e-6, spent)))
    print("файл: %s" % CORPUS_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
