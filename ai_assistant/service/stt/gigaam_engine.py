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
import os
import shutil
import tempfile
import wave

from ai_assistant.service.stt.base import SttEngine

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

        # gigaam.transcribe() принимает путь к аудиофайлу, поэтому пишем
        # временный WAV на target_sample_rate.
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
