# coding=utf8
r"""Прогнать запись звонка через датчик речи и распознавание сервиса — офлайн.

    py -3.12 tools/replay_call.py <запись.wav> [--thresholds 0.35] [--pause-ms 1000]
    py -3.12 tools/replay_call.py <...>_ПОТОК.wav --resets-from-log logs/aia.log

Зачем: по логу сервиса видно только то, что датчик речи выдал распознаванию.
Если клиент сказал «да», а в логе за это время пусто (5-я волна, 269218128:
три «да», в логе ни одного), причина либо в датчике (короткое тихое слово не
дотянуло до порога), либо в распознавании («да» с помехами стало «а»). Этот
скрипт берёт запись, гонит её через тот же UtteranceSegmenter + SileroVAD +
STT, что и сервис, и печатает, что нашлось при каждом пороге датчика.

КАКУЮ ЗАПИСЬ БРАТЬ. Нужен дамп ПОТОКА, который пишет сам сервис:
`<время>_<звонок>_ПОТОК.wav` в папке отладочных записей. В нём ровно то, что
пришло в сервис с линии, и только голос клиента. Запись станции
(`/var/spool/asterisk/monitor/*.wav`) для этого не годится: там сведены обе
стороны, и датчик режет на реплики фразы самого бота. Скрипт предупреждает,
если имя файла не похоже на дамп потока.

ЧТО ЗДЕСЬ ИСПРАВЛЕНО 09.11.2026 (F11 из речевого аудита). Инструмент не
воспроизводил боевой тракт, а решения по порогам датчика принимались на нём:
  * порог по умолчанию был 0,5 при боевых 0,35 с 13.10.2026 — теперь берётся из
    того же config.py, что и у сервиса, и его вообще не надо помнить;
  * сегментатор строился на ОДНОМ экземпляре датчика с подменой поля _threshold,
    а модель Silero несёт состояние: второй порог считался по памяти от первого.
    Теперь на каждый порог делается clone(), ровно как в сервисе;
  * ресемплинг был линейной интерполяцией, теперь resample_poly;
  * сброса памяти датчика по разрыву потока не было вовсе, хотя сервис его
    делает на каждой фразе бота (STREAM_GAP_RESET_S). Теперь моменты сброса
    задаются ключом или вычитываются из лога;
  * время принудительной реплики считалось с вычитанием паузы, которой там нет.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import wave

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from ai_assistant.service.config import load_config  # noqa: E402
from ai_assistant.service.main import STREAM_GAP_RESET_S  # noqa: E402
from ai_assistant.service.stt.base import create_engine, pad_short_utterance, prepare_audio  # noqa: E402
from ai_assistant.service.vad import FRAME_BYTES, SileroVoiceDetector, UtteranceSegmenter  # noqa: E402

#: Кусок, которым станция присылает звук. Им же кормим сегментатор, чтобы
#: границы реплик совпадали с боевыми.
CHUNK_FRAMES = 25

#: Пусковой файл сервиса. Из него берём настройки, чтобы инструмент мерил ту же
#: конфигурацию, что отвечает на звонки.
STARTUP_BAT = os.path.join(REPO, "ЗАПУСК СЕРВИСА.bat")


def apply_production_env() -> int:
    """Подставить настройки боевого пуска, которых нет в окружении.

    Без этого инструмент считал по умолчаниям консоли, а они с боевыми
    расходятся: движок распознавания по умолчанию vosk, в бою gigaam. Решения по
    порогам датчика принимались на этом инструменте, то есть на чужой
    конфигурации (F11).

    Уже заданные переменные не трогаем: явное окружение сильнее файла, иначе
    нельзя было бы прогнать «а что если».
    """
    if not os.path.isfile(STARTUP_BAT):
        return 0
    applied = 0
    pattern = re.compile(r"\s*set\s+(AIA_[A-Z0-9_]+)=(.*)$", re.I)
    with open(STARTUP_BAT, encoding="cp1251", errors="replace") as handle:
        for line in handle:
            found = pattern.match(line.strip())
            if found and found.group(1) not in os.environ:
                os.environ[found.group(1)] = found.group(2)
                applied += 1
    return applied


def load_pcm_8k(path: str) -> bytes:
    """WAV → PCM16 моно 8 кГц, как слышит сервис."""
    with wave.open(path, "rb") as handle:
        rate = handle.getframerate()
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        raw = handle.readframes(handle.getnframes())
    if width != 2:
        raise SystemExit("нужен 16-битный WAV, здесь %d байт на отсчёт" % width)
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    if rate != 8000:
        # resample_poly, а не линейная интерполяция: интерполяция не давит
        # зеркальные частоты, и на речи это слышно как шипение, которое датчик
        # принимает за голос. Дамп потока уже 8 кГц, пересчёт нужен только для
        # записей станции.
        from scipy.signal import resample_poly

        from math import gcd

        divisor = gcd(int(rate), 8000)
        samples = resample_poly(samples, 8000 // divisor, int(rate) // divisor)
    return np.clip(samples, -32768, 32767).astype(np.int16).tobytes()


def resets_from_log(log_path: str, session_id: str, stream_start: str = "") -> list:
    """Моменты сброса памяти датчика из лога сервиса, в секундах от начала дампа.

    Сервис пишет строку «Разрыв потока [<звонок>] N.N с — память детектора
    сброшена» на каждой фразе бота. Дамп потока сами паузы не хранит (куски
    пишутся подряд), поэтому моменты приходится брать из лога: иначе реплика
    сразу после фразы бота считается по памяти, которой в бою уже не было.

    ИСПРАВЛЕНО 09.11.2026 после ревью. Прежняя версия складывала ДЛИТЕЛЬНОСТИ
    разрывов и отдавала накопленную сумму как позицию. Это не позиция: в логе
    записана длительность разрыва и стенное время его конца, а позицию надо
    считать так:

        позиция = (время разрыва - время начала дампа) - сумма всех разрывов
                  включая текущий

    Вычитать сумму надо потому, что в дампе лежит только дошедший звук, то есть
    время дампа идёт медленнее стенного ровно на длительность разрывов.

    Чем стоила ошибка: на звонке из лога (дамп 49 с, пять разрывов) все пять
    сбросов ложились в первые 17 секунд, а нужны они были на 6,3 / 20,4 / 28,9 /
    34,4 / 42,5 с. Сброс, попавший внутрь реплики, сегментатор молча
    отбрасывает (reset_detector ничего не делает, пока копится речь), то есть
    инструмент обещал воспроизведение боя и не давал его. Правка F11 этого же
    дня заявляла, что сбросы появились, и была права только наполовину.

    `stream_start` это время создания дампа в виде «ЧЧММСС» (оно стоит первым в
    имени файла: `153816_<звонок>_ПОТОК.wav`). Без него моменты восстановить
    нельзя, и функция честно возвращает пустой список: пусть лучше вызывающий
    увидит «сбросов нет» и предупредит человека, чем получит неверные числа.
    """
    if not stream_start or len(stream_start) < 6 or not stream_start[:6].isdigit():
        return []
    base_s = (int(stream_start[0:2]) * 3600 + int(stream_start[2:4]) * 60
              + int(stream_start[4:6]))
    pattern = re.compile(
        r"(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2})[,.](?P<ms>\d{3}).*"
        r"Разрыв потока \[(?P<sid>[^\]]*)\]\s+(?P<dur>[\d.]+) с")
    seen = []
    spent = 0.0
    with open(log_path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            found = pattern.search(line)
            if not found:
                continue
            if session_id and found.group("sid") != session_id:
                continue
            wall = (int(found.group("h")) * 3600 + int(found.group("m")) * 60
                    + int(found.group("s")) + int(found.group("ms")) / 1000.0)
            # Через полночь дамп и лог расходятся на сутки: добираем их обратно.
            if wall < base_s:
                wall += 24 * 3600
            spent += float(found.group("dur"))
            position = (wall - base_s) - spent
            if position >= 0:
                seen.append(position)
    return sorted(seen)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("wav")
    applied = apply_production_env()
    cfg = load_config()
    parser.add_argument("--thresholds", default="",
                        help="пороги датчика через запятую; по умолчанию боевой из config.py")
    parser.add_argument("--pause-ms", type=int, default=None,
                        help="пауза, по которой режется реплика; по умолчанию боевая")
    parser.add_argument("--resets", default="",
                        help="секунды, на которых сбросить память датчика (фразы бота), через запятую")
    parser.add_argument("--resets-from-log", default="",
                        help="взять моменты сброса из лога сервиса (строки «Разрыв потока»)")
    parser.add_argument("--session", default="",
                        help="идентификатор звонка для --resets-from-log; пусто — все разрывы лога")
    parser.add_argument("--no-stt", action="store_true", help="только датчик речи, без распознавания")
    args = parser.parse_args()

    pause_ms = args.pause_ms if args.pause_ms is not None else cfg.utterance_pause_ms
    thresholds = ([float(x) for x in args.thresholds.split(",") if x.strip()]
                  or [cfg.vad_threshold])

    if "ПОТОК" not in os.path.basename(args.wav):
        print("ВНИМАНИЕ: имя файла не похоже на дамп потока сервиса. Если это запись станции,")
        print("          в ней сведены обе стороны, и датчик порежет на реплики фразы бота.")
        print("          Берите <время>_<звонок>_ПОТОК.wav из папки отладочных записей.")

    resets = [float(x) for x in args.resets.split(",") if x.strip()]
    if args.resets_from_log:
        # Время начала дампа стоит первым в его имени: 153816_<звонок>_ПОТОК.wav.
        # Без него позицию сброса в записи не восстановить, см. resets_from_log.
        start = os.path.basename(args.wav).split("_")[0]
        resets += resets_from_log(args.resets_from_log, args.session, start)
    resets = sorted(set(resets))

    pcm = load_pcm_8k(args.wav)
    total_s = len(pcm) / 2 / 8000.0
    # Хвост тишины: иначе реплика, на которой запись обрывается, не закроется
    # паузой и не попадёт в выдачу.
    pcm += bytes(2 * 8000 * 3)
    print("настроек взято из пускового файла: %d" % applied)
    print("запись %.1f с, пауза реплики %d мс, движок %s, модель %s"
          % (total_s, pause_ms, cfg.stt_engine, cfg.gigaam_model))
    print("пороги датчика: %s (боевой %.2f)"
          % (", ".join("%.2f" % t for t in thresholds), cfg.vad_threshold))
    if resets:
        print("сброс памяти датчика на: %s с"
              % ", ".join("%.1f" % r for r in resets))
    else:
        print("сброс памяти датчика НЕ задан: если в звонке говорил бот, реплика сразу")
        print("после его фразы будет считаться по памяти, которой в бою уже не было.")
        print("Задайте --resets-from-log logs/aia.log --session <звонок>.")

    engine = None
    if not args.no_stt:
        engine = create_engine(
            cfg.stt_engine,
            model_path=os.environ.get("AIA_VOSK_MODEL_PATH", ""),
            model_name=cfg.gigaam_model,
        )

    # Датчик строится на боевом пороге, а на каждый прогон берётся clone() —
    # ровно как в сервисе (main.segmenter_factory). Один экземпляр на все
    # пороги давал бы второму порогу память от первого.
    for threshold in thresholds:
        base = SileroVoiceDetector(threshold=threshold)
        segmenter = UtteranceSegmenter(
            base.clone(), pause_ms=pause_ms, silence_timeout_ms=cfg.silence_timeout_ms)
        print("\n== порог датчика %.2f" % threshold)
        step = FRAME_BYTES * CHUNK_FRAMES
        position = 0
        pending_resets = list(resets)
        while position < len(pcm):
            chunk = pcm[position:position + step]
            position += step
            now_s = position / 2 / 8000.0
            # Сброс делаем на том же месте, где его делает сервис: по факту
            # разрыва потока, то есть после фразы бота.
            while pending_resets and pending_resets[0] <= now_s:
                segmenter.reset_detector()
                print("  %6.1f с: память датчика сброшена (разрыв потока >= %.1f с)"
                      % (pending_resets[0], STREAM_GAP_RESET_S))
                pending_resets.pop(0)
            for event in segmenter.feed(chunk):
                if event.kind != "utterance":
                    continue
                length_s = len(event.pcm) / 2 / 8000.0
                # Пауза вычитается только у реплики, закрытой паузой. У
                # принудительной (упёрлись в предел длительности) паузы нет, и
                # вычитание сдвигало её на секунду в прошлое.
                end_s = now_s if event.forced else now_s - segmenter.pause_seconds
                start_s = max(0.0, end_s - length_s)
                text = ""
                if engine is not None:
                    padded = pad_short_utterance(event.pcm)
                    text = engine.transcribe(prepare_audio(padded, engine.target_sample_rate))
                peak = getattr(event, "peak_dbfs", None)
                print("  %6.1f–%6.1f с (%.1f с)%s%s: %r" % (
                    start_s, end_s, length_s,
                    " принудительно" if event.forced else "",
                    "" if peak is None else " пик %.1f дБ" % peak,
                    text))


if __name__ == "__main__":
    main()
