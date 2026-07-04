"""Text-to-speech with a natural Hindi option.

Engines (config: voice.tts.engine):
  edge     - Microsoft neural voices (hi-IN-SwaraNeural / MadhurNeural). Natural
             Hindi + Hinglish. ONLINE. Falls back to SAPI if the network fails.
  sapi     - Windows SAPI via win32com. OFFLINE, reliable, but English-accented.
  pyttsx3  - last-resort fallback.

Edge audio is mp3; we decode it with PyAV and play via sounddevice (both already
installed for the voice stack). SAPI stays as the offline safety net.

Quick check:  python -m nova.voice.tts "namaste, kya main sunai de rahi hoon"
"""

from __future__ import annotations

import io
import logging

log = logging.getLogger("nova.tts")


class Speaker:
    def __init__(self, rate: int = 185, engine: str = "edge", voice: str = "hi-IN-SwaraNeural"):
        self.rate = rate
        self.engine = engine
        self.voice = voice
        self._sapi = None
        self._edge_ok = self._check_edge() if engine == "edge" else False
        if engine == "edge" and not self._edge_ok:
            log.info("edge-tts not usable; using SAPI")

    def _check_edge(self) -> bool:
        try:
            import av  # noqa: F401
            import edge_tts  # noqa: F401
            import sounddevice  # noqa: F401
            return True
        except Exception as e:
            log.info("edge deps missing (%s)", e)
            return False

    # --- public -------------------------------------------------------------
    def say(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        print(f"[Nova] {text}")
        if self.engine == "edge" and self._edge_ok and self._say_edge(text):
            return
        if self._say_sapi(text):        # offline fallback (also default engine)
            return
        self._say_pyttsx3(text)

    def stop(self) -> None:
        """Interrupt any audio currently playing (used by the Stop button)."""
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass
        try:
            if self._sapi is not None:
                # SAPI: 2 = SVSFPurgeBeforeSpeak — flush the queue
                self._sapi.Speak("", 3)
        except Exception:
            pass

    # --- edge (natural Hindi, online) --------------------------------------
    def _say_edge(self, text: str) -> bool:
        import asyncio

        import sounddevice as sd

        for attempt in range(2):                # retry once before falling back
            try:
                mp3 = asyncio.run(self._edge_synth(text))
                if not mp3:
                    continue
                pcm, rate = self._decode_mp3(mp3)
                if pcm.size == 0:
                    continue
                sd.play(pcm, rate)
                sd.wait()
                return True
            except Exception as e:
                log.warning("edge-tts attempt %d failed (%s)", attempt + 1, e)
        return False

    async def _edge_synth(self, text: str) -> bytes:
        import edge_tts

        c = edge_tts.Communicate(text, self.voice)
        buf = bytearray()
        async for ch in c.stream():
            if ch["type"] == "audio":
                buf += ch["data"]
        return bytes(buf)

    @staticmethod
    def _decode_mp3(mp3: bytes, rate: int = 24000):
        import av
        import numpy as np

        cont = av.open(io.BytesIO(mp3))
        rs = av.audio.resampler.AudioResampler(format="flt", layout="mono", rate=rate)
        out = []
        for frame in cont.decode(audio=0):
            for r in rs.resample(frame):
                out.append(r.to_ndarray().reshape(-1))
        for r in rs.resample(None):             # flush buffered tail (no cut-off)
            out.append(r.to_ndarray().reshape(-1))
        return (np.concatenate(out) if out else np.zeros(0, "float32")), rate

    # --- sapi (offline) -----------------------------------------------------
    def _say_sapi(self, text: str) -> bool:
        try:
            import pythoncom
            import win32com.client

            if self._sapi is None:
                pythoncom.CoInitialize()
                self._sapi = win32com.client.Dispatch("SAPI.SpVoice")
                self._select_female_voice()      # match the female edge voice
                try:
                    self._sapi.Rate = max(-10, min(10, int((self.rate - 175) / 12)))
                except Exception:
                    pass
            self._sapi.Speak(text)
            return True
        except Exception as e:
            log.warning("SAPI speak failed: %s", e)
            return False

    def _select_female_voice(self) -> None:
        """Pick a female SAPI voice (Zira) so fallback stays consistent with edge."""
        try:
            for tok in self._sapi.GetVoices():
                desc = tok.GetDescription()
                if "Zira" in desc or "female" in desc.lower() or "Heera" in desc:
                    self._sapi.Voice = tok
                    return
        except Exception as e:
            log.debug("could not select female SAPI voice: %s", e)

    def _say_pyttsx3(self, text: str) -> None:
        try:
            import pyttsx3

            engine = pyttsx3.init()
            engine.setProperty("rate", self.rate)
            engine.say(text)
            engine.runAndWait()
        except Exception as e:
            log.warning("pyttsx3 say failed: %s", e)


if __name__ == "__main__":
    import sys

    from ..config import load_config

    cfg = load_config()
    phrase = " ".join(sys.argv[1:]) or "नमस्ते! मैं नोवा हूँ। क्या मैं आपकी मदद कर सकती हूँ?"
    s = Speaker(
        rate=int(cfg.get("voice.tts.rate", 185)),
        engine=cfg.get("voice.tts.engine", "edge"),
        voice=cfg.get("voice.tts.voice", "hi-IN-SwaraNeural"),
    )
    print(f"engine={s.engine} edge_ok={s._edge_ok} voice={s.voice}")
    s.say(phrase)
    print("done")
