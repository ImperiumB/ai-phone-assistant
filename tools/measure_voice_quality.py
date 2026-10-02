# -*- coding: utf-8 -*-
"""Разборчивость синтеза в телефонной полосе: голоса и эквализация.

Как меряем. Слушать двадцать вариантов подряд и сравнивать «на слух» —
занятие ненадёжное, поэтому судьёй берём распознавание речи. Фраза
синтезируется, проходит ровно тот путь, что и в бою (48 кГц → 8 кГц →
кодек A-law линии → обратно), и подаётся движку. Чем больше слов движок
разобрал верно, тем разборчивее звучала фраза.

Это не замена человеческому уху: движок и человек ошибаются по-разному.
Но мера объективная, повторяемая и считается за минуты, а не за день
прослушиваний. Финальный выбор голоса всё равно за людьми — для этого
скрипт заодно раскладывает готовые файлы, которые можно послушать.

Работа идёт в два прохода, и это не прихоть: синтез и распознавание держат в
памяти по своей модели, а на машине рядом обычно крутится боевой сервис с
третьей. Загруженные разом, они не помещаются — замер 31.08.2026 падал с
«файл подкачки слишком мал», пока проходы не развели.

    py -3 tools/measure_voice_quality.py synth   [--voices baya,kseniya] [--out ПАПКА]
    py -3 tools/measure_voice_quality.py score   [--out ПАПКА]
"""
import argparse
import json
import os
import re
import sys
import wave

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import numpy as np  # noqa: E402
from scipy.signal import resample_poly  # noqa: E402

from ai_assistant.service.tts import (  # noqa: E402
    MODEL_SAMPLE_RATE_HZ,
    TARGET_PEAK,
    TELEPHONY_SAMPLE_RATE_HZ,
    _DOWNSAMPLE_FACTOR,
    telephony_eq,
)

MANIFEST = "manifest.json"

# Служебные фразы бота и типичные уточняющие вопросы: меряем на том, что
# клиенты слышат на самом деле, а не на отвлечённом тексте.
PHRASES = [
    "здравствуйте чем могу помочь",
    "правильно понимаю что вас интересует ремонт стиральной машины",
    "минуту перевожу ваш звонок на специалиста",
    "попробуйте переформулировать свой вопрос пожалуйста",
    "тогда подскажите пожалуйста что вас интересует",
    "соединяю вас с отделом сопровождения оставайтесь на линии",
    "правильно понимаю что вас интересует ремонт посудомоечной машины",
    "простите не слышу вас скажите пожалуйста да или нет",
]

ALL_VOICES = ["aidar", "baya", "kseniya", "xenia", "eugene"]


def alaw_roundtrip(pcm16):
    """Прогнать звук через кодек линии и обратно.

    Именно A-law стоит в pjsip.conf станции. Кодек логарифмический: тихие
    места он передаёт точнее громких, и на слабом сигнале это слышно как
    шум квантования. Без этого шага замер мерил бы звук, которого в трубке
    никогда не бывает.
    """
    import audioop

    return np.frombuffer(
        audioop.alaw2lin(audioop.lin2alaw(pcm16.tobytes(), 2), 2), dtype=np.int16
    )


# Уровни шума в линии. Без шума мерить нечего: чистый синтез распознавание
# разбирает без единой ошибки на всех голосах и с любой эквализацией — метрика
# упирается в потолок и перестаёт что-либо различать (проверено 31.08.2026).
# Живой звонок чистым не бывает: шум в трубке, комната, слабый сигнал. Под
# шумом и видно, чья разборчивость держится дольше.
NOISE_SNR_DB = [12, 6, 0]


def to_line(audio_model_rate, use_eq, snr_db=None, seed=0):
    """Путь фразы от модели до линии — тот же, что в бою, плюс шум."""
    audio = telephony_eq(audio_model_rate, MODEL_SAMPLE_RATE_HZ) if use_eq else audio_model_rate
    audio_8k = resample_poly(audio, up=1, down=_DOWNSAMPLE_FACTOR)
    peak = float(np.max(np.abs(audio_8k))) if audio_8k.size else 0.0
    if peak > 0:
        audio_8k = audio_8k * (TARGET_PEAK / peak)

    if snr_db is not None:
        # Уровень шума считаем от мощности речи, а не всей дорожки: паузы между
        # словами занизили бы её и шум вышел бы тише заказанного.
        frame = TELEPHONY_SAMPLE_RATE_HZ // 50
        frames = audio_8k[: len(audio_8k) // frame * frame].reshape(-1, frame)
        energies = np.sqrt(np.mean(frames ** 2, axis=1))
        speech = energies[energies > np.max(energies) * 0.1]
        speech_rms = float(np.mean(speech)) if speech.size else 0.0
        # Одно и то же зерно на все варианты одной фразы: голоса надо
        # сравнивать на одинаковом шуме, иначе разница будет случайной.
        rng = np.random.default_rng(seed)
        noise = rng.normal(0.0, speech_rms * (10.0 ** (-snr_db / 20.0)), len(audio_8k))
        audio_8k = audio_8k + noise

    pcm = (np.clip(audio_8k, -1.0, 1.0) * 32767).astype(np.int16)
    return alaw_roundtrip(pcm)


_WORDS = re.compile(r"[а-яёa-z0-9]+")


def words(text):
    return _WORDS.findall(text.lower().replace("ё", "е"))


def word_errors(reference, hypothesis):
    """Расстояние Левенштейна по словам: сколько слов пришлось бы исправить."""
    ref, hyp = words(reference), words(hypothesis)
    previous = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        current = [i]
        for j, h in enumerate(hyp, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1,
                               previous[j - 1] + (r != h)))
        previous = current
    return previous[-1], len(ref)


def band_energy(pcm16, low, high, rate=TELEPHONY_SAMPLE_RATE_HZ):
    x = pcm16.astype(np.float64) / 32768.0
    spectrum = np.abs(np.fft.rfft(x)) ** 2
    freqs = np.fft.rfftfreq(len(x), 1.0 / rate)
    band = spectrum[(freqs >= low) & (freqs < high)].sum()
    total = spectrum.sum()
    return band / total if total > 0 else 0.0


def save_wav(path, pcm16, rate=TELEPHONY_SAMPLE_RATE_HZ):
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm16.tobytes())


def stage_synth(out_dir, voices):
    """Первый проход: разложить все варианты фраз по файлам. Только синтез."""
    from ai_assistant.service.tts import SileroSynthesizer

    os.makedirs(out_dir, exist_ok=True)
    synth = SileroSynthesizer("v5_ru")
    items = []

    for voice in voices:
        for index, phrase in enumerate(PHRASES):
            audio = synth.synthesize_at_model_rate(phrase, voice).numpy()
            for use_eq in (False, True):
                tag = "eq" if use_eq else "orig"
                clean = to_line(audio, use_eq)
                name = "{0}_{1}_{2}.wav".format(voice, index, tag)
                save_wav(os.path.join(out_dir, name), clean)
                items.append({
                    "voice": voice, "phrase": phrase, "eq": use_eq, "snr": None,
                    "file": name,
                    "low": band_energy(clean, 0, 300),
                    "high": band_energy(clean, 1500, 3400),
                })
                for snr in NOISE_SNR_DB:
                    noisy = to_line(audio, use_eq, snr_db=snr, seed=index * 100 + snr)
                    name = "{0}_{1}_{2}_snr{3}.wav".format(voice, index, tag, snr)
                    save_wav(os.path.join(out_dir, name), noisy)
                    items.append({
                        "voice": voice, "phrase": phrase, "eq": use_eq, "snr": snr,
                        "file": name,
                    })
        print("  {0}: готово".format(voice))

    with open(os.path.join(out_dir, MANIFEST), "w", encoding="utf-8") as handle:
        json.dump(items, handle, ensure_ascii=False)
    print("\nФайлов: {0}. Дальше: score.".format(len(items)))


def stage_score(out_dir, engine_name, vosk_model_path):
    """Второй проход: распознать зашумлённые файлы. Только распознавание.

    Судьёй по умолчанию взят Vosk, а не боевой GigaAM, и на то две причины.
    Первая житейская: GigaAM грузит каждый файл через внешний ffmpeg, которого
    на машине может не быть, и держит вдвое больше памяти — рядом с работающим
    сервисом замер просто не помещается. Вторая по существу: GigaAM разбирает
    чистый синтез вообще без ошибок, и метрика упирается в потолок, ничего не
    различая. Судья должен ошибаться, иначе он не судья.
    """
    from ai_assistant.service.stt.base import create_engine, prepare_audio

    with open(os.path.join(out_dir, MANIFEST), encoding="utf-8") as handle:
        items = json.load(handle)

    engine = create_engine(engine_name, model_path=vosk_model_path, model_name="v3_rnnt")
    voices = sorted({item["voice"] for item in items})

    stats = {}
    for item in items:
        key = (item["voice"], item["eq"])
        entry = stats.setdefault(key, {"bad": 0, "words": 0, "low": [], "high": []})
        if item["snr"] is None:
            entry["low"].append(item["low"])
            entry["high"].append(item["high"])
            continue
        with wave.open(os.path.join(out_dir, item["file"]), "rb") as handle:
            pcm = handle.readframes(handle.getnframes())
        text = engine.transcribe(prepare_audio(pcm, engine.target_sample_rate))
        bad, count = word_errors(item["phrase"], text)
        entry["bad"] += bad
        entry["words"] += count

    print("\nФраз: {0}, голосов: {1}, уровни шума: {2} дБ."
          .format(len(PHRASES), len(voices), ", ".join(str(s) for s in NOISE_SNR_DB)))
    print("Путь каждой фразы: 48 кГц → эквализация → 8 кГц → шум линии → A-law.\n")
    print("{0:<10} {1:>11} {2:>11} {3:>9} {4:>11} {5:>11}".format(
        "ГОЛОС", "ОШИБОК БЕЗ", "ОШИБОК С EQ", "НИЗЫ ДО", "НИЗЫ ПОСЛЕ", "СОГЛАСНЫЕ"))
    print("-" * 70)

    summary = []
    for voice in voices:
        plain, eq = stats[(voice, False)], stats[(voice, True)]
        wer_plain = 100.0 * plain["bad"] / max(plain["words"], 1)
        wer_eq = 100.0 * eq["bad"] / max(eq["words"], 1)
        summary.append((voice, wer_plain, wer_eq))
        print("{0:<10} {1:>10.1f}% {2:>10.1f}% {3:>8.1f}% {4:>10.1f}% {5:>10.1f}%".format(
            voice, wer_plain, wer_eq,
            100.0 * np.mean(plain["low"]), 100.0 * np.mean(eq["low"]),
            100.0 * np.mean(eq["high"])))

    print("\nОШИБОК — доля слов, не разобранных распознаванием, в среднем по всем")
    print("       уровням шума. Меньше — лучше.")
    print("НИЗЫ — доля энергии ниже 300 Гц: канал её не пропустит, а запас")
    print("       громкости она съедает. Столбцы до и после эквализации.")
    print("СОГЛАСНЫЕ — доля энергии в 1500-3400 Гц, где живёт разборчивость.")

    best = min(summary, key=lambda row: (row[2], row[1]))
    better = sum(1 for row in summary if row[2] < row[1])
    worse = sum(1 for row in summary if row[2] > row[1])
    print("\nЛучший голос под шумом: {0}".format(best[0]))
    print("Эквализация помогла {0} голосам из {1}, помешала {2}.".format(
        better, len(summary), worse))
    print("Файлы для прослушивания: {0}".format(os.path.abspath(out_dir)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["synth", "score"])
    parser.add_argument("--voices", default=",".join(ALL_VOICES))
    parser.add_argument("--out", default=os.path.join(BASE, "voice_samples", "telephone"))
    parser.add_argument("--engine", default="vosk", choices=["vosk", "gigaam"])
    parser.add_argument("--vosk-model", default=os.environ.get(
        "AIA_VOSK_MODEL_PATH", r"C:\Users\user\models\vosk-model-small-ru-0.22"))
    args = parser.parse_args()

    if args.stage == "synth":
        stage_synth(args.out, [v.strip() for v in args.voices.split(",") if v.strip()])
    else:
        stage_score(args.out, args.engine, args.vosk_model)


if __name__ == "__main__":
    main()
