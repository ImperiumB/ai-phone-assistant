"""UL-17568. Образцы голосов Silero для формы выбора голоса в ERP.

    py -3.12 tools/generate_voice_samples.py

Кладёт по одному WAV на голос в `voice_samples/` в корне репозитория. Имена
файлов — строго `<голос>.wav` (`eugene.wav`, `baya.wav`, ...): форма ERP ищет
образец по имени голоса, отступать от него нельзя.

Образцы студийные: прямой выход модели на 48 кГц, моно, 16 бит, без понижения
частоты. Руководитель колл-центра выбирает голос по тому, насколько он приятный
и живой, а телефонный канал портит все пять голосов примерно одинаково — на
выбор это не влияет, зато мешает расслышать разницу. Боевой синтез при этом
идёт другим путём (48 кГц с ресемплом в телефонные 8 кГц, см.
ai_assistant/service/tts.py) — путать эти два пути не надо.

Первый запуск на новой модели дольше: качаются веса через torch.hub.
"""

from __future__ import annotations

import argparse
import sys
import wave
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ai_assistant.service.tts import MODEL_SAMPLE_RATE_HZ, SileroSynthesizer  # noqa: E402

# Все голоса русской модели Silero. Порядок — как в выпадающем списке формы.
VOICES = ["aidar", "baya", "kseniya", "xenia", "eugene"]

DEFAULT_MODEL = "v5_ru"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "voice_samples"

# Первая фраза — та, которой бот реально встречает клиента: именно её слышат
# чаще всего. Вторая длиннее, на связном тексте с вопросительной интонацией:
# на одном коротком приветствии голоса различаются куда хуже, чем на фразе.
PHRASES = [
    "Здравствуйте, чем могу помочь?",
    "Правильно понимаю, вас интересует ремонт стиральной машины?",
]

# Пауза между фразами — чтобы они не слипались в одну, но и не тянуть образец.
PAUSE_SECONDS = 0.7


def build_sample(synthesizer, voice: str, phrases=PHRASES, pause_seconds=PAUSE_SECONDS) -> bytes:
    """Все фразы одним куском звука, с паузой между ними. PCM 16 бит."""
    import numpy as np

    pause = np.zeros(int(MODEL_SAMPLE_RATE_HZ * pause_seconds), dtype="float32")
    parts = []
    for index, text in enumerate(phrases):
        if index:
            parts.append(pause)
        parts.append(synthesizer.synthesize_at_model_rate(text, voice).numpy())

    audio = np.concatenate(parts)
    # Модель изредка чуть выходит за [-1, 1]; без обрезки это даёт щелчки.
    return (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16).tobytes()


def write_wav(path: Path, pcm: bytes, sample_rate: int = MODEL_SAMPLE_RATE_HZ) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--voices", nargs="*", default=VOICES, help="по умолчанию все пять голосов"
    )
    args = parser.parse_args(argv)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    print("Загружаем модель {0}...".format(args.model), file=sys.stderr)
    synthesizer = SileroSynthesizer(args.model)

    for voice in args.voices:
        target = args.output_dir / "{0}.wav".format(voice)
        pcm = build_sample(synthesizer, voice)
        write_wav(target, pcm)
        seconds = len(pcm) / 2.0 / MODEL_SAMPLE_RATE_HZ
        print(
            "{0:<8} {1:>9} байт  {2:.1f} с  {3} Гц".format(
                voice, target.stat().st_size, seconds, MODEL_SAMPLE_RATE_HZ
            )
        )

    print("Готово: {0}".format(args.output_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
