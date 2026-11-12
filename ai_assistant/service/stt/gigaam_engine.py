"""GigaAM (Сбер, MIT): лучший WER на русском среди открытых моделей.

Стриминга из коробки нет, поэтому распознаём целыми репликами — границы даёт VAD.
Модель работает на 16 кГц (gigaam.preprocess.SAMPLE_RATE == 16000), телефонные
8 кГц апсемплятся вызывающей стороной через prepare_audio(), см. base.py.

gigaam.load_audio() декодирует входной файл через системный бинарник ffmpeg
(subprocess), своего декодера у библиотеки нет. Если "ffmpeg" не найден на PATH,
используем бинарник, который ставится вместе с пакетом imageio-ffmpeg (см.
requirements.txt), и один раз кладём рядом с ним копию с именем ffmpeg.exe —
Windows ищет исполняемый файл по точному имени, "ffmpeg-win-x86_64-*.exe"
подхвачен не будет.
"""
import logging
import os
import shutil
import tempfile
import wave

from ai_assistant.service.stt.base import SttEngine

log = logging.getLogger("aia")

# Реплики короче этого порога — тишина, шум или обрезок на границе VAD, а не
# осмысленная речь; модель на них не рассчитана и падает необработанным
# исключением из своего стека: ValueError на пустом буфере ("both buffer
# length (0) and count (-1) must not be 0") и RuntimeError из torchaudio на
# паддинге спектрограммы ("Padding size should be less than the
# corresponding input dimension") на паре десятков байт тишины. Vosk на
# таком же входе спокойно отдаёт пустую строку, и transcribe() обязан вести
# себя так же: короче этого в реальном звонке осмысленной речи не бывает.
MIN_TRANSCRIBABLE_SECONDS = 0.1

_BYTES_PER_SAMPLE = 2  # PCM 16 бит моно

#: Ниже какой пиковой громкости пробовать распознать тихую реплику второй раз,
#: подняв уровень. Ноль выключает вторую попытку.
#:
#: Сначала здесь стояло -30 дБ: столько дал речевой аудит, у которого тише этого
#: лежали 3,1 % коротких «да» и «нет». Порог выбирался по ХВОСТУ распределения
#: громкости, а не по тому, где реально теряется текст, и оказался вдвое строже
#: нужного.
#:
#: Нашлось это на живом прозвоне 09.11.2026: заказчик сказал «да», бот ответил
#: «Слушаю вас». У той реплики пик -15,8 дБ, первый проход вернул пустоту, а
#: подъём уровня даёт «да» — но вторая попытка не сработала, потому что -15,8 это
#: ГРОМЧЕ порога -30.
#:
#: Замер по всем 251 записанной реплике: пустыми первый проход вернул 14, подъём
#: вытаскивает 6, и все шесть достаются порогом -15 дБ, дальше прибавки нет
#: (на -12 и ниже попыток больше, вытащенных столько же). При -30 дБ вытаскивалось
#: только 3 из 6.
#:
#: Цена: четыре лишних прохода распознавания на 251 реплику, и только там, где
#: первый проход УЖЕ вернул пустоту, то есть бот всё равно собирался переспросить.
#: Три громких пустых (-4,2, -1,6 и 0,0 дБ) подъёмом не лечатся вовсе: это отказ
#: самой модели, и порогом его не достать.
QUIET_RETRY_DBFS = float(os.environ.get("AIA_QUIET_RETRY_DBFS", "-15.0"))

#: До какого уровня поднимать. Минус 6 дБ это запас от клиппинга.
QUIET_RETRY_TARGET_DBFS = float(os.environ.get("AIA_QUIET_RETRY_TARGET_DBFS", "-6.0"))


def _peak_dbfs(pcm: bytes) -> float:
    """Пиковая громкость отрезка в дБ относительно полной шкалы."""
    import numpy as np

    if not pcm:
        return -120.0
    samples = np.frombuffer(pcm, dtype=np.int16)
    peak = int(np.max(np.abs(samples))) if samples.size else 0
    if peak <= 0:
        return -120.0
    return float(20.0 * np.log10(peak / 32767.0))


def _normalize_peak(pcm: bytes, target_dbfs: float) -> bytes:
    """Поднять отрезок по уровню до цели. Тише не делаем никогда.

    Возвращает тот же объект, если подъём не нужен: вызывающий по этому
    признаку понимает, что второй проход бессмысленен.
    """
    import numpy as np

    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    if peak <= 0:
        return pcm
    gain = ((10.0 ** (target_dbfs / 20.0)) * 32767.0) / peak
    if gain <= 1.0:
        return pcm
    return np.clip(samples * gain, -32768, 32767).astype(np.int16).tobytes()


def _ensure_ffmpeg_on_path() -> None:
    if shutil.which("ffmpeg"):
        return

    import imageio_ffmpeg

    bundled = imageio_ffmpeg.get_ffmpeg_exe()
    bundled_dir = os.path.dirname(bundled)
    aliased = os.path.join(bundled_dir, "ffmpeg.exe")
    if not os.path.exists(aliased):
        shutil.copy2(bundled, aliased)
    os.environ["PATH"] = bundled_dir + os.pathsep + os.environ.get("PATH", "")


class GigaamEngine(SttEngine):
    # gigaam.preprocess.SAMPLE_RATE = 16000 — модель обучена на 16 кГц.
    # Библиотека сама ресемплит вход через ffmpeg до этой частоты, но раз
    # телефонный тракт даёт 8 кГц, честнее поднять частоту снаружи через
    # prepare_audio(), как и для Vosk, а не полагаться на скрытый ресемплинг
    # внутри чужой библиотеки.
    target_sample_rate = 16000

    #: Внутренний API библиотеки оказался недоступен (другая версия пакета):
    #: дальше распознаём штатным путём через файл и больше не пробуем. Объявлен
    #: на классе, а не только в __init__: движок иногда создают через
    #: object.__new__ без инициализации (так делают тесты защитных ветвей), и
    #: обращение к несуществующему полю уронило бы распознавание на пустяке.
    _tensor_path_broken = False

    def __init__(self, model_name: str = "v3_rnnt"):
        _ensure_ffmpeg_on_path()

        import gigaam

        self._model = gigaam.load_model(model_name)

    def transcribe(self, pcm: bytes) -> str:
        # Отсекаем вырожденный вход до обращения к модели: пустой буфер, обрывок
        # не по границе 16-битного отсчёта и любой отрезок короче
        # MIN_TRANSCRIBABLE_SECONDS. Длительность считаем по факту, а не по
        # числу байт — так порог не завязан на конкретный размер буфера.
        sample_count = len(pcm) // _BYTES_PER_SAMPLE
        if (
            len(pcm) % _BYTES_PER_SAMPLE
            or sample_count / self.target_sample_rate < MIN_TRANSCRIBABLE_SECONDS
        ):
            return ""

        text = self._transcribe_once(pcm)
        if text.strip():
            return text

        # Вторая попытка только на ТИХОЙ реплике и только когда первая вернула
        # пустоту. Поднимать уровень всегда нельзя: неизвестно, что это даст на
        # нормальных репликах, а ломать то, что уже узнаётся, недопустимо.
        # Здесь же терять нечего: выбор между пустотой и попыткой.
        #
        # Замер по 251 записанной реплике (09.11.2026, после живого прозвона):
        # пустыми первый проход вернул 14, подъём вытаскивает 6 из них. Порог
        # стоит на -15 дБ, и это все шесть; при прежних -30 дБ доставалось три.
        # Подробнее про выбор порога — у константы QUIET_RETRY_DBFS.
        if QUIET_RETRY_DBFS and _peak_dbfs(pcm) < QUIET_RETRY_DBFS:
            louder = _normalize_peak(pcm, QUIET_RETRY_TARGET_DBFS)
            if louder is not pcm:
                second = self._transcribe_once(louder)
                if second.strip():
                    log.info("Тихая реплика (%.1f дБ) со второй попытки по громкости: %r",
                             _peak_dbfs(pcm), second)
                    return second
        return text

    def _transcribe_once(self, pcm: bytes) -> str:
        if not self._tensor_path_broken:
            try:
                return self._transcribe_tensor(pcm)
            except Exception:
                # Путь через тензор идёт в обход публичного метода библиотеки и
                # опирается на её внутренности (forward, _decode, _device,
                # _dtype). Обновление gigaam может их переименовать, и тогда
                # распознавание обязано продолжить работать, а не умереть:
                # падаем на штатный путь через файл до перезапуска сервиса.
                log.exception("Распознавание из массива не удалось, дальше идём через файл")
                self._tensor_path_broken = True
        return self._transcribe_via_file(pcm)

    def _transcribe_tensor(self, pcm: bytes) -> str:
        """Распознать прямо из отсчётов: без временного файла и без ffmpeg.

        Штатный `model.transcribe(path)` принимает только путь к файлу и
        декодирует его через системный бинарник ffmpeg, то есть на КАЖДУЮ
        реплику звонка приходится запись временного WAV и запуск внешнего
        процесса. Замер на 12 живых репликах 07.11.2026: 368 мс через файл
        против 281 мс из массива, то есть 88 мс на реплику (24 %), и текст
        совпал на всех двенадцати до символа.

        Внутри повторяется ровно то, что делает сам `transcribe`: отсчёты в
        тензор нужного устройства и типа, длина, `forward`, `_decode`. Разница
        только в источнике отсчётов, поэтому результат и совпадает.
        """
        import numpy as np
        import torch

        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        with torch.inference_mode():
            wav = torch.from_numpy(samples.copy()).to(self._model._device).to(self._model._dtype)
            wav = wav.unsqueeze(0)
            length = torch.full([1], wav.shape[-1], device=self._model._device)
            encoded, encoded_len = self._model.forward(wav, length)
            text, _words = self._model._decode(encoded, encoded_len, length, False)[0]
        return text

    def _transcribe_via_file(self, pcm: bytes) -> str:
        """Штатный путь библиотеки: временный WAV плюс ffmpeg. Запас на случай сбоя."""
        handle, path = tempfile.mkstemp(suffix=".wav")
        os.close(handle)
        try:
            with wave.open(path, "wb") as writer:
                writer.setnchannels(1)
                writer.setsampwidth(2)
                writer.setframerate(self.target_sample_rate)
                writer.writeframes(pcm)
            return self._model.transcribe(path).text
        finally:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
