"""Speech-to-text via faster-whisper. Optional: absent deps degrade gracefully.

First slice uses a fixed-window capture (record N seconds after activation),
which is simple and reliable. A VAD-based endpointer can replace `record()`
later without changing callers.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

# Anaconda ships its own OpenMP; CTranslate2/torch bring another. Allow the
# duplicate so the process doesn't abort on import. (See torch-anaconda-openmp.)
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

log = logging.getLogger("nova.stt")

SAMPLE_RATE = 16000


class Transcriber:
    """Wraps faster-whisper + sounddevice. `.available` reports readiness."""

    def __init__(self, model: str = "base", device: str = "auto",
                 language: str = "en"):
        self.available = False
        self._model = None
        self._sd = None
        # "" or "auto" -> let whisper detect the language each utterance
        self.language = (language or "").strip() or None
        if self.language in ("auto", "detect"):
            self.language = None
        try:
            import sounddevice as sd
            from faster_whisper import WhisperModel

            self._sd = sd
            compute = "float16" if device == "cuda" else "int8"
            resolved = None if device == "auto" else device
            try:
                self._model = WhisperModel(
                    model, device=(resolved or "auto"), compute_type=compute
                )
                log.info("STT ready (model=%s, device=%s)", model, resolved or "auto")
            except Exception as ge:                # GPU/cuDNN not happy -> CPU int8
                log.info("STT %s on %s failed (%s); falling back to CPU", model, resolved, ge)
                self._model = WhisperModel(model, device="cpu", compute_type="int8")
                log.info("STT ready (model=%s, device=cpu)", model)
            self.available = True
        except Exception as e:
            log.info("STT disabled (%s). Install: pip install faster-whisper sounddevice", e)

    def record(self, seconds: float = 6.0):
        """Capture mono audio from the default mic as a float32 numpy array."""
        import numpy as np

        if not self.available:
            return None
        audio = self._sd.rec(
            int(seconds * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype="float32"
        )
        self._sd.wait()
        return np.squeeze(audio)

    def transcribe(self, seconds: float = 6.0) -> Optional[str]:
        """Record then transcribe. Returns text, or None if STT is unavailable."""
        if not self.available:
            return None
        audio = self.record(seconds)
        if audio is None:
            return None
        return self._run(audio)

    def listen(
        self,
        end_silence_ms: int = 700,
        start_ms: int = 150,
        max_ms: int = 15000,
    ) -> Optional[str]:
        """Wait for the user to speak, stop when they go quiet, return the text.

        This is the "reply right when you stop talking" path — no fixed window.
        """
        if not self.available:
            return None
        from .endpoint import record_utterance

        audio = record_utterance(
            self._sd, end_silence_ms=end_silence_ms, start_ms=start_ms, max_ms=max_ms
        )
        if audio is None:
            return None
        return self._run(audio)

    def transcribe_file(self, path: str) -> Optional[str]:
        """Transcribe an existing audio file (also handy for testing without a mic)."""
        if self._model is None:
            return None
        return self._run(path)

    def transcribe_from_array(self, audio) -> Optional[str]:
        """Transcribe a float32 mono numpy array (used by the wake-word loop)."""
        if self._model is None or audio is None:
            return None
        return self._run(audio)

    def _run(self, audio) -> str:
        segments, _ = self._model.transcribe(
            audio, language=self.language, vad_filter=True
        )
        text = " ".join(seg.text for seg in segments).strip()
        log.info("heard: %r", text)
        return text
