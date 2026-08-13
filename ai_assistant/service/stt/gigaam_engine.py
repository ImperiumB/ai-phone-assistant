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

    def __init__(self, model_name: str = "v2_rnnt"):
        _ensure_ffmpeg_on_path()

        import gigaam

        self._model = gigaam.load_model(model_name)

    def transcribe(self, pcm: bytes) -> str:
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
