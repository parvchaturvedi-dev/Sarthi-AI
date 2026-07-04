"""Wake-word listening — "Hey Nova".

Two backends, because there is no pretrained "nova" neural model:

  keyword  (default): energy-gated micro-transcription. Only runs STT when the
           mic hears sound, then checks the text for the wake word. Responds to
           "Hey Nova" literally, today, with no extra model. Heavier on CPU.

  openwakeword: efficient always-on neural spotter, but the pretrained models
           are alexa / hey_jarvis / hey_mycroft / ... To make it fire on the
           real phrase, drop a custom-trained hey_nova.onnx at custom_model_path.

Both expose the same surface: wait() blocks until the wake word is heard.
"""

from __future__ import annotations

import logging
from typing import Callable, List, Optional

import numpy as np

log = logging.getLogger("nova.wake")

SAMPLE_RATE = 16000
_FRAME = 1280  # 80ms at 16kHz — openwakeword's expected chunk


def _wake_variants(wake_word: str) -> List[str]:
    w = wake_word.lower().strip()
    # Tolerate how Whisper mishears a short name (nova / no va / nowa ...).
    base = w.split()[-1]                      # "hey nova" -> "nova"
    return list({w, base, "hey " + base, "hi " + base, base.replace(" ", "")})


def matched(text: str, wake_word: str) -> bool:
    """True if a transcript contains the wake word (fuzzy on the short name)."""
    if not text:
        return False
    t = text.lower()
    if any(v in t for v in _wake_variants(wake_word)):
        return True
    base = wake_word.lower().split()[-1]
    # near-misses Whisper commonly emits for "nova"
    return base == "nova" and any(x in t for x in ("no va", "nowa", "nolva", "novia"))


class WakeWord:
    def __init__(
        self,
        backend: str = "keyword",
        wake_word: str = "hey nova",
        *,
        transcriber=None,                     # required for the keyword backend
        chunk_seconds: float = 1.5,
        energy_threshold: float = 0.012,      # RMS gate; below this = silence, skip STT
        oww_model: str = "hey_jarvis",
        threshold: float = 0.5,
        custom_model_path: Optional[str] = None,
    ):
        self.backend = backend
        self.wake_word = wake_word
        self.transcriber = transcriber
        self.chunk_seconds = chunk_seconds
        self.energy_threshold = energy_threshold
        self.threshold = threshold
        self.available = False
        self._oww = None

        if backend == "openwakeword":
            self._init_oww(custom_model_path or oww_model)
        elif backend == "keyword":
            self.available = bool(transcriber and getattr(transcriber, "available", False))
            if not self.available:
                log.warning("keyword wake needs a working transcriber (install STT deps)")
        else:
            log.warning("unknown wake backend '%s'", backend)

    def _init_oww(self, model: str) -> None:
        try:
            from openwakeword.model import Model
            from openwakeword.utils import download_models

            download_models()
            kwargs = {"inference_framework": "onnx"}
            if model.endswith(".onnx"):
                kwargs["wakeword_models"] = [model]
            else:
                kwargs["wakeword_models"] = [model]
            self._oww = Model(**kwargs)
            self._target = list(self._oww.models.keys())[0]
            self.available = True
            log.info("openwakeword ready (target=%s)", self._target)
        except Exception as e:
            log.warning("openwakeword unavailable: %s", e)

    # --- detection ----------------------------------------------------------
    def wait(self, stop: Optional[Callable[[], bool]] = None) -> bool:
        """Block until the wake word is detected. Returns True, or False if stopped."""
        stop = stop or (lambda: False)
        if not self.available:
            return False
        if self.backend == "openwakeword":
            return self._wait_oww(stop)
        return self._wait_keyword(stop)

    def _wait_keyword(self, stop) -> bool:
        import sounddevice as sd

        while not stop():
            audio = sd.rec(
                int(self.chunk_seconds * SAMPLE_RATE),
                samplerate=SAMPLE_RATE, channels=1, dtype="float32",
            )
            sd.wait()
            audio = np.squeeze(audio)
            if float(np.sqrt(np.mean(audio**2))) < self.energy_threshold:
                continue                       # silence — don't spend STT on it
            text = self.transcriber.transcribe_from_array(audio) or ""
            if matched(text, self.wake_word):
                log.info("wake matched on %r", text)
                return True
        return False

    def _wait_oww(self, stop) -> bool:
        import sounddevice as sd

        with sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=_FRAME
        ) as stream:
            while not stop():
                data, _ = stream.read(_FRAME)
                scores = self._oww.predict(np.squeeze(data))
                if scores.get(self._target, 0.0) >= self.threshold:
                    log.info("wake matched (oww score=%.2f)", scores[self._target])
                    return True
        return False
