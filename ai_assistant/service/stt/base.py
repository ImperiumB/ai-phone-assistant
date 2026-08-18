"""Интерфейс движка распознавания.

Движки сменные: телефонный канал 8 кГц может по-разному даваться разным моделям,
и прототип обязан сравнить как минимум Vosk и GigaAM на одном материале.
"""
from abc import ABC, abstractmethod

import numpy as np
from scipy.signal import resample_poly


#: Отрезки короче этого дополняются тишиной с обеих сторон перед распознаванием.
#: Длинная речь и так распознаётся целиком, а добавка стоит времени: на фразах
#: по 3-4 секунды медиана распознавания росла с 771 до 1015 мс (замер
#: 18.08.2026) без единого улучшения результата — 10/10 в обоих случаях.
PAD_BELOW_SECONDS = 1.0

#: Сколько тишины добавляется с каждой стороны. Величина подобрана замером
#: 18.08.2026: синтез пяти голосов, приведённый к телефонному виду (полоса
#: 300-3400 Гц, A-law, шум линии), отрезки 110-250 мс, по 320 попыток на
#: величину, два независимых прогона с разными посевами шума.
#:
#:   добавка     0 мс   100 мс   200 мс   300 мс   500 мс   700 мс   1000 мс
#:   прогон 1   89.1%    53.1%    70.9%    87.2%    97.8%        -         -
#:   прогон 2   89.1%        -        -    85.9%    97.2%    98.1%     96.6%
#:
#: Зависимость немонотонная, и это главное, что здесь надо знать: маленькая
#: добавка не «слабее помогает», а РЕАЛЬНО ВРЕДИТ — 100-200 мс роняют
#: распознавание вдвое, а «очевидные» 300 мс в обоих прогонах оказались хуже,
#: чем не делать ничего вообще. Работает только от 500 мс, а на 1000 мс
#: результат снова начинает падать. НЕ ПОДКРУЧИВАТЬ на глаз — перемерять.
SILENCE_PAD_SECONDS = 0.5

#: Ниже этого дополнять нечего: это не речь, а щелчок в линии или шорох.
#: GigaamEngine.transcribe() отвергает такой обрывок до обращения к модели и
#: стоит на нём 0.0 мс, а дополненный до секунды щелчок дошёл бы до модели и
#: обошёлся бы примерно в 450 мс — на каждый посторонний звук в разговоре.
MIN_PADDABLE_SECONDS = 0.1

_BYTES_PER_SAMPLE = 2  # PCM 16 бит моно


class SttEngine(ABC):
    #: Частота, которую движок ожидает на входе.
    target_sample_rate = 8000

    @abstractmethod
    def transcribe(self, pcm: bytes) -> str:
        """Распознать одну реплику целиком. PCM 16 бит моно в target_sample_rate."""


def resample_8k_to_16k(pcm: bytes) -> bytes:
    samples = np.frombuffer(pcm, dtype=np.int16)
    upsampled = resample_poly(samples.astype(np.float32), up=2, down=1)
    clipped = np.clip(upsampled, -32768, 32767)
    return clipped.astype(np.int16).tobytes()


def prepare_audio(pcm8k: bytes, target_sample_rate: int) -> bytes:
    if target_sample_rate == 8000:
        return pcm8k
    if target_sample_rate == 16000:
        return resample_8k_to_16k(pcm8k)
    raise ValueError("Неподдерживаемая частота дискретизации: {0}".format(target_sample_rate))


def pad_short_utterance(pcm: bytes, sample_rate: int = 8000) -> bytes:
    """Дополнить короткий отрезок тишиной с обеих сторон.

    На живом звонке 18.08.2026 клиент дважды ответил «нет» на уточняющий
    вопрос, и распознавание оба раза вернуло пустоту, хотя длинную фразу тем
    же движком разобрало прекрасно. Причина не в громкости и не в качестве
    линии: сегментатор отдаёт только те кадры, которые VAD признал речью, и
    вокруг короткого слова не остаётся ни миллисекунды контекста.

    Правка общая для обоих движков и применяется до выбора движка — в
    единственном месте, откуда вызывается transcribe() (main.py). Величины
    добавки и порогов — см. константы выше, все три подобраны замером.

    Отрезки, которые дополнять не надо (длинные, вырожденные, битые по
    границе отсчёта), возвращаются тем же объектом — вызывающая сторона
    вправе на это рассчитывать.
    """
    if len(pcm) % _BYTES_PER_SAMPLE:
        return pcm  # обрывок не по границе отсчёта — не наше дело, разберётся движок

    seconds = len(pcm) / _BYTES_PER_SAMPLE / sample_rate
    if seconds >= PAD_BELOW_SECONDS or seconds < MIN_PADDABLE_SECONDS:
        return pcm

    silence = b"\x00" * (int(sample_rate * SILENCE_PAD_SECONDS) * _BYTES_PER_SAMPLE)
    return silence + pcm + silence


def create_engine(name: str, **kwargs) -> SttEngine:
    if name == "vosk":
        from ai_assistant.service.stt.vosk_engine import VoskEngine

        return VoskEngine(kwargs["model_path"])
    if name == "gigaam":
        from ai_assistant.service.stt.gigaam_engine import GigaamEngine

        return GigaamEngine(kwargs.get("model_name", "v3_rnnt"))
    raise ValueError("Неизвестный движок распознавания: {0}".format(name))
