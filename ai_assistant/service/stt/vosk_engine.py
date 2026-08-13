"""Vosk: настоящий стриминг, работает на CPU, точность ниже остальных.

Держит крайнюю точку размена «быстро, но грубо».
"""
import json

from ai_assistant.service.stt.base import SttEngine


class VoskEngine(SttEngine):
    target_sample_rate = 8000

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
