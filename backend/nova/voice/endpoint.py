"""Voice-activity endpointing — reply the moment you STOP talking.

The old capture recorded a fixed 6 seconds every time (so even a 1-second command
waited 6s). This replaces that with a live endpointer: it starts capturing when
you begin speaking and stops ~0.7s after you go quiet — so Sarthi reacts right
when your sentence ends, not on a timer.

Energy-based (no extra deps): it calibrates the room's noise floor, then treats
frames above an adaptive threshold as speech. The state machine here is pure and
unit-tested; the mic I/O lives in `record_utterance()`.
"""

from __future__ import annotations

import logging
import math
from collections import deque
from typing import List, Optional

log = logging.getLogger("nova.endpoint")

SAMPLE_RATE = 16000


def rms(frame) -> float:
    """Root-mean-square energy of a float32 mono frame."""
    if len(frame) == 0:
        return 0.0
    try:
        import numpy as np
        return float(np.sqrt(np.mean(np.square(frame, dtype="float64"))))
    except Exception:
        return math.sqrt(sum(x * x for x in frame) / len(frame))


class Endpointer:
    """Pure speech start/stop detector fed one frame-energy at a time.

    Lifecycle per call: push() energies until it returns 'end', then reset().
    """

    def __init__(
        self,
        frame_ms: int = 30,
        start_ms: int = 150,        # need this much speech to "start" (debounce)
        end_silence_ms: int = 700,  # this much quiet after speech = "you're done"
        max_ms: int = 15000,        # hard cap so it can't listen forever
        calibrate_frames: int = 8,  # frames used to learn the room noise floor
        energy_mult: float = 3.0,   # speech = energy_mult x noise floor …
        min_threshold: float = 0.010,  # … but never below this absolute floor
    ):
        self.frame_ms = frame_ms
        self.start_frames = max(1, start_ms // frame_ms)
        self.end_frames = max(1, end_silence_ms // frame_ms)
        self.max_frames = max(1, max_ms // frame_ms)
        self.calibrate_frames = calibrate_frames
        self.energy_mult = energy_mult
        self.min_threshold = min_threshold
        self.reset()

    def reset(self) -> None:
        self._noise: List[float] = []
        self.threshold = self.min_threshold
        self.started = False
        self._speech_run = 0
        self._silence_run = 0
        self._frames_seen = 0

    def push(self, energy: float) -> Optional[str]:
        """Feed one frame's RMS. Returns 'start', 'end', or None."""
        self._frames_seen += 1

        # 1) learn the ambient noise floor from the first few frames
        if len(self._noise) < self.calibrate_frames:
            self._noise.append(energy)
            if len(self._noise) == self.calibrate_frames:
                floor = sorted(self._noise)[len(self._noise) // 2]  # median
                self.threshold = max(self.min_threshold, floor * self.energy_mult)
                log.debug("noise floor set, threshold=%.4f", self.threshold)
            return None

        speaking = energy >= self.threshold
        event: Optional[str] = None

        if not self.started:
            self._speech_run = self._speech_run + 1 if speaking else 0
            if self._speech_run >= self.start_frames:
                self.started = True
                self._silence_run = 0
                event = "start"
        else:
            if speaking:
                self._silence_run = 0
            else:
                self._silence_run += 1
                if self._silence_run >= self.end_frames:
                    return "end"

        if self.started and self._frames_seen >= self.max_frames:
            return "end"
        return event


def record_utterance(
    sd,
    frame_ms: int = 30,
    start_ms: int = 150,
    end_silence_ms: int = 700,
    max_ms: int = 15000,
    preroll_ms: int = 300,
):
    """Block until the user speaks and stops; return the utterance as float32 mono.

    Returns None if nothing was said (all silence up to max_ms).
    """
    import numpy as np

    frame_len = int(SAMPLE_RATE * frame_ms / 1000)
    preroll = deque(maxlen=max(1, preroll_ms // frame_ms))
    ep = Endpointer(frame_ms=frame_ms, start_ms=start_ms,
                    end_silence_ms=end_silence_ms, max_ms=max_ms)
    captured: List = []

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                        blocksize=frame_len) as stream:
        while True:
            block, _ = stream.read(frame_len)
            frame = np.squeeze(block)
            ev = ep.push(rms(frame))
            if not ep.started:
                preroll.append(frame)              # keep recent audio for pre-roll
            else:
                if ev == "start":                  # include the pre-roll so word 1 isn't clipped
                    captured.extend(preroll)
                captured.append(frame)
            if ev == "end":
                break

    if not captured:
        return None
    return np.concatenate(captured)
