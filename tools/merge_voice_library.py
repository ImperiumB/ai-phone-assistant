# coding=utf8
r"""Долить в библиотеку голосов фразы из отдельно собранной библиотеки.

    py -3.12 tools/build_voice_library.py --source C:\aia_tts_lab\linux_listen ^
        --phrases C:\aia_tts_lab\linux\phrases_listen.tsv --out C:\aia_tts_lab\lib_listen
    py -3.12 tools/merge_voice_library.py --source C:\aia_tts_lab\lib_listen

build_voice_library пишет index.tsv голоса целиком, только по тем фразам, что
нашёл в --source, — собирать новую фразу прямо в ai_assistant/voices нельзя,
индекс остальных 127 фраз был бы затёрт. Поэтому новые фразы собираются в
отдельную папку, а сюда доливаются: файлы копируются, индекс дописывается.

В конце — проверка «весь набор»: у всех голосов должен быть один и тот же
список текстов, иначе группа линий с неполным голосом уедет на s3 (main.py,
effective_voice). Расхождение печатается и даёт код возврата 1.
"""
from __future__ import annotations

import argparse
import io
import os
import shutil
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_INTO = os.path.join(REPO, "ai_assistant", "voices")
HEADER = "# ключ (tts.library_key по тексту посылки) <TAB> текст фразы\n"


def read_index(path):
    entries = {}
    if not os.path.exists(path):
        return entries
    with io.open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if line and not line.startswith("#") and "\t" in line:
                key, text = line.split("\t", 1)
                entries[key.strip()] = text
    return entries


def write_index(path, entries):
    with io.open(path, "w", encoding="utf-8") as handle:
        handle.write(HEADER)
        for key, text in sorted(entries.items(), key=lambda kv: kv[1]):
            handle.write("%s\t%s\n" % (key, text))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, help="библиотека, собранная build_voice_library в отдельную папку")
    ap.add_argument("--into", default=DEFAULT_INTO)
    args = ap.parse_args()

    voices = sorted(d for d in os.listdir(args.source) if os.path.isdir(os.path.join(args.source, d)))
    if not voices:
        print("в %s нет папок голосов" % args.source)
        return 1
    for voice in voices:
        source_index = read_index(os.path.join(args.source, voice, "index.tsv"))
        target_dir = os.path.join(args.into, voice)
        os.makedirs(target_dir, exist_ok=True)
        target_index = read_index(os.path.join(target_dir, "index.tsv"))
        added = 0
        for key, text in source_index.items():
            wav = os.path.join(args.source, voice, key + ".wav")
            if not os.path.exists(wav):
                print("  %s: нет файла %s (%s) — пропущено" % (voice, key, text))
                continue
            shutil.copyfile(wav, os.path.join(target_dir, key + ".wav"))
            if key not in target_index:
                added += 1
            target_index[key] = text
        write_index(os.path.join(target_dir, "index.tsv"), target_index)
        print("%s: +%d, всего %d фраз" % (voice, added, len(target_index)))

    # Весь набор или никак: сравниваем списки текстов всех голосов библиотеки.
    all_voices = sorted(d for d in os.listdir(args.into) if os.path.isdir(os.path.join(args.into, d)))
    texts_by_voice = {v: set(read_index(os.path.join(args.into, v, "index.tsv")).values()) for v in all_voices}
    union = set().union(*texts_by_voice.values()) if texts_by_voice else set()
    incomplete = False
    for voice, texts in texts_by_voice.items():
        missing = sorted(union - texts)
        if missing:
            incomplete = True
            print("НЕПОЛНЫЙ голос %s, нет %d фраз: %s" % (voice, len(missing), "; ".join(missing[:5])))
    if incomplete:
        return 1
    print("все %d голосов полны: %d фраз у каждого" % (len(all_voices), len(union)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
