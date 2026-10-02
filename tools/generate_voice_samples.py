r"""UL-17568. Образцы голосов для формы выбора голоса в ERP.

    py -3.12 tools/generate_voice_samples.py --model-path C:\Users\user\models\vosk-model-tts-ru-0.7-multi

Кладёт по одному WAV на голос в `voice_samples/` в корне репозитория. Имена
файлов — строго `<голос>.wav` (`s3.wav`, `s4.wav`, ...): форма ERP ищет образец
по имени голоса, отступать от него нельзя.

Готовые файлы уезжают в клиент ERP — `SOURCES/CLIENT/Dictionaries/Sounds/` — и
подключаются там как EmbeddedResource в `Dictionaries.csproj`. Добавили голос
здесь, а строчку в csproj забыли — кнопка «Прослушать» на нём промолчит.

Образцы студийные: прямой выход модели на её собственной частоте, моно, 16
бит, без понижения. Руководитель колл-центра выбирает голос по тому, насколько
он приятный и живой, а телефонный канал портит все голоса примерно одинаково —
на выбор это не влияет, зато мешает расслышать разницу. Боевой синтез при этом
идёт другим путём (ресемпл в телефонные 8 кГц плюс эквализация, см.
ai_assistant/service/tts.py) — путать эти два пути не надо.

Движок по умолчанию — vosk: Silero v5_ru лицензирована как CC BY-NC, и
сгенерированные ею файлы в клиенте ERP были той же правовой проблемой, что и
сама модель на линии (разбор 03.09.2026). Поэтому старые silero-образцы из
клиента удалены, а не оставлены рядом.
"""

from __future__ import annotations

import argparse
import sys
import wave
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ai_assistant.service.tts import create_synthesizer  # noqa: E402

DEFAULT_ENGINE = "vosk"
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

    pause = np.zeros(
        int(synthesizer.model_sample_rate * pause_seconds), dtype="float32"
    )
    parts = []
    for index, text in enumerate(phrases):
        if index:
            parts.append(pause)
        parts.append(synthesizer.synthesize_at_model_rate(text, voice))

    audio = np.concatenate(parts)
    # Модель изредка чуть выходит за [-1, 1]; без обрезки это даёт щелчки.
    return (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16).tobytes()


def write_wav(path: Path, pcm: bytes, sample_rate: int) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--engine", default=DEFAULT_ENGINE, choices=["vosk", "silero"])
    parser.add_argument(
        "--model-path", default="",
        help="папка с распакованной моделью Vosk-TTS (только для --engine vosk)",
    )
    parser.add_argument(
        "--silero-model", default="v5_ru", help="только для --engine silero",
    )
    parser.add_argument(
        "--voices", nargs="*", default=None,
        help="по умолчанию все голоса выбранного движка, в порядке списка формы",
    )
    args = parser.parse_args(argv)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    print("Загружаем движок {0}...".format(args.engine), file=sys.stderr)
    synthesizer = create_synthesizer(
        args.engine, args.silero_model, args.model_path
    )
    voices = args.voices or list(synthesizer.VOICES)
    sample_rate = synthesizer.model_sample_rate

    for voice in voices:
        target = args.output_dir / "{0}.wav".format(voice)
        pcm = build_sample(synthesizer, voice)
        write_wav(target, pcm, sample_rate)
        seconds = len(pcm) / 2.0 / sample_rate
        print(
            "{0:<8} {1:>9} байт  {2:.1f} с  {3} Гц".format(
                voice, target.stat().st_size, seconds, sample_rate
            )
        )

    print("Готово: {0}".format(args.output_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
