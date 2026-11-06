# coding=utf8
r"""Прогнать запись звонка через датчик речи и распознавание сервиса — офлайн.

    py -3.12 tools/replay_call.py <запись.wav> [--thresholds 0.5,0.35,0.25] [--pause-ms 1500]

Зачем: по логу сервиса видно только то, что датчик речи выдал распознаванию.
Если клиент сказал «да», а в логе за это время пусто (5-я волна, 269218128:
три «да», в логе ни одного), причина либо в датчике (короткое тихое слово не
дотянуло до порога), либо в распознавании («да» с помехами стало «а»). Этот
скрипт берёт запись станции, гонит её через тот же UtteranceSegmenter + SileroVAD +
STT, что и сервис, и печатает, что нашлось при каждом пороге датчика.

Запись: WAV любой частоты, моно или стерео (стерео сводится в моно). Станция
пишет обе стороны разговора, поэтому в выдаче будут и фразы бота — они
подписаны по времени, отличить просто.
"""
from __future__ import annotations

import argparse
import os
import sys
import wave

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from ai_assistant.service.config import load_config  # noqa: E402
from ai_assistant.service.stt.base import create_engine, pad_short_utterance, prepare_audio  # noqa: E402
from ai_assistant.service.vad import FRAME_BYTES, SileroVoiceDetector, UtteranceSegmenter  # noqa: E402


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
        # Линейная интерполяция: для речи и телефонной полосы достаточно.
        count = int(round(len(samples) * 8000 / rate))
        positions = np.linspace(0, len(samples) - 1, count)
        samples = np.interp(positions, np.arange(len(samples)), samples)
    return np.clip(samples, -32768, 32767).astype(np.int16).tobytes()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("wav")
    parser.add_argument("--thresholds", default="0.5,0.35,0.25",
                        help="пороги датчика речи через запятую; боевой — 0.5")
    parser.add_argument("--pause-ms", type=int, default=None,
                        help="пауза, по которой режется реплика; по умолчанию как у сервиса (UTTERANCE_PAUSE_MS)")
    parser.add_argument("--no-stt", action="store_true", help="только датчик речи, без распознавания")
    args = parser.parse_args()

    cfg = load_config()
    pause_ms = args.pause_ms if args.pause_ms is not None else cfg.utterance_pause_ms
    pcm = load_pcm_8k(args.wav)
    total_s = len(pcm) / 2 / 8000.0
    # Хвост тишины: иначе реплика, на которой запись обрывается, не закроется
    # паузой и не попадёт в выдачу.
    pcm += bytes(2 * 8000 * 3)
    print("запись %.1f с, пауза реплики %d мс, движок %s" % (total_s, pause_ms, cfg.stt_engine))

    engine = None
    if not args.no_stt:
        engine = create_engine(
            cfg.stt_engine,
            model_path=os.environ.get("AIA_VOSK_MODEL_PATH", ""),
            model_name=cfg.gigaam_model,
        )

    detector = SileroVoiceDetector()
    for threshold in [float(x) for x in args.thresholds.split(",")]:
        detector._threshold = threshold  # тот же экземпляр модели, другой порог
        segmenter = UtteranceSegmenter(detector, pause_ms=pause_ms, silence_timeout_ms=cfg.silence_timeout_ms)
        print("\n== порог датчика %.2f" % threshold)
        position = 0
        step = FRAME_BYTES * 25  # 0.8 с на шаг — как куски с линии
        while position < len(pcm):
            chunk = pcm[position:position + step]
            position += step
            for event in segmenter.feed(chunk):
                if event.kind != "utterance":
                    continue
                end_s = position / 2 / 8000.0 - segmenter.pause_seconds
                length_s = len(event.pcm) / 2 / 8000.0
                start_s = max(0.0, end_s - length_s)
                text = ""
                if engine is not None:
                    padded = pad_short_utterance(event.pcm)
                    text = engine.transcribe(prepare_audio(padded, engine.target_sample_rate))
                print("  %6.1f–%6.1f с (%.1f с)%s: %r" % (
                    start_s, end_s, length_s, " принудительно" if event.forced else "", text))


if __name__ == "__main__":
    main()
