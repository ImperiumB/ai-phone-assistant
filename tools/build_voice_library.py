# coding=utf8
r"""Собрать библиотеку записанных голосов для сервиса (tts.VoiceLibrary).

    py -3.12 tools/build_voice_library.py --source C:\aia_tts_lab\linux_full --phrases C:\aia_tts_lab\linux\phrases_full.tsv

Вход — отобранные дубли CosyVoice (cosy_<голос>_<тег>.wav, 24 кГц) и TSV
«тег<TAB>текст» с текстами фраз **в том виде, в каком они лежат в ERP**: ключ
файла считается по тексту посылки (tts.library_key), и если для синтеза текст
подменяли («Кэрхер» вместо «Karcher»), сюда всё равно передаётся оригинал.

Выход — ai_assistant/voices/<голос>/<ключ>.wav (телефонный PCM 8 кГц, через
тот же to_telephony_pcm, что и синтез) плюс index.tsv «ключ<TAB>текст».
Сервис подхватывает библиотеку при старте; обновили — перезапуск.
"""
from __future__ import annotations

import argparse
import collections
import glob
import io
import os
import re
import sys
import wave

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from ai_assistant.service.tts import library_key, to_telephony_pcm, write_wav_8k  # noqa: E402

DEFAULT_OUT = os.path.join(REPO, "ai_assistant", "voices")
NAME_RE = re.compile(r"^cosy_(?P<voice>[a-z-]+)_(?P<tag>.+)\.wav$")


def read_phrases(path):
    texts = {}
    with io.open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if line and not line.startswith("#") and "\t" in line:
                tag, text = line.split("\t", 1)
                texts[tag.strip()] = " ".join(text.split())
    return texts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, help="папка с cosy_<голос>_<тег>.wav")
    ap.add_argument("--phrases", required=True, help="TSV тег/текст, тексты как в ERP")
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()

    texts = read_phrases(args.phrases)
    index = collections.defaultdict(dict)
    skipped = []
    for path in sorted(glob.glob(os.path.join(args.source, "cosy_*.wav"))):
        match = NAME_RE.match(os.path.basename(path))
        if not match:
            continue
        voice, tag = match.group("voice"), match.group("tag")
        text = texts.get(tag)
        if text is None:
            skipped.append(os.path.basename(path))
            continue
        with wave.open(path, "rb") as handle:
            rate = handle.getframerate()
            pcm = np.frombuffer(handle.readframes(handle.getnframes()), dtype=np.int16)
        key = library_key(text)
        folder = os.path.join(args.out, voice)
        os.makedirs(folder, exist_ok=True)
        write_wav_8k(os.path.join(folder, key + ".wav"), to_telephony_pcm(pcm.astype(np.float64) / 32768.0, rate))
        index[voice][key] = text
    for voice, entries in index.items():
        with io.open(os.path.join(args.out, voice, "index.tsv"), "w", encoding="utf-8") as handle:
            handle.write("# ключ (tts.library_key по тексту посылки) <TAB> текст фразы\n")
            for key, text in sorted(entries.items(), key=lambda kv: kv[1]):
                handle.write("%s\t%s\n" % (key, text))
        print("%s: %d фраз" % (voice, len(entries)))
    if skipped:
        print("без текста в TSV, пропущены: %d (%s…)" % (len(skipped), ", ".join(skipped[:3])))
    print("библиотека: %s" % args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
