"""Vosk: настоящий стриминг, работает на CPU, точность ниже остальных.

Держит крайнюю точку размена «быстро, но грубо».
"""
import json

from ai_assistant.service.stt.base import SttEngine


class VoskEngine(SttEngine):
    # Модель vosk-model-small-ru-0.22 обучена на 16 кГц (conf/mfcc.conf:
    # --sample-frequency=16000). Библиотека vosk при несовпадении заявленной
    # и модельной частоты не пересчитывает звук сама, а падает с
    # "Sampling frequency mismatch" — своего ресемплинга у неё нет.
    # Телефонные 8 кГц поднимает до 16 кГц prepare_audio() перед вызовом
    # transcribe(), см. base.py.
    target_sample_rate = 16000

    def __init__(self, model_path: str):
        from vosk import KaldiRecognizer, Model, SetLogLevel

        SetLogLevel(-1)  # без этого Kaldi засоряет stderr
        self._model = Model(model_path)
        self._recognizer_class = KaldiRecognizer

    def transcribe(self, pcm: bytes) -> str:
        recognizer = self._recognizer_class(self._model, float(self.target_sample_rate))
        recognizer.AcceptWaveform(pcm)
        result = json.loads(recognizer.FinalResult())
        return result.get("text", "")
