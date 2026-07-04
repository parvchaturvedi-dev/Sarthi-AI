"""The vision loop's eyes — OCR the screen into text + positions.

Engine: RapidOCR (the PaddleOCR models running on onnxruntime — no torch, no
system binary, pip-installable on Windows). This turns "the AI reads the screen"
from the spec into something the agent can actually act on: every visible string
comes back with a click point.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

log = logging.getLogger("nova.ocr")


@dataclass
class TextBox:
    text: str
    box: List[Tuple[float, float]]   # 4 corner points
    score: float

    @property
    def center(self) -> Tuple[int, int]:
        xs = [p[0] for p in self.box]
        ys = [p[1] for p in self.box]
        return int(sum(xs) / 4), int(sum(ys) / 4)


class OcrEngine:
    def __init__(self) -> None:
        self.available = False
        self._engine = None
        try:
            from rapidocr_onnxruntime import RapidOCR
            self._engine = RapidOCR()
            self.available = True
            log.info("OCR ready (RapidOCR / onnxruntime)")
        except Exception as e:
            log.info("OCR disabled (%s). Install: pip install rapidocr-onnxruntime", e)

    def read_image(self, image) -> List[TextBox]:
        """OCR a numpy image (BGR) or file path -> list of TextBox."""
        if not self.available:
            return []
        result, _ = self._engine(image)
        boxes: List[TextBox] = []
        for det in result or []:
            box, text, score = det[0], det[1], float(det[2])
            boxes.append(TextBox(text=text, box=[tuple(p) for p in box], score=score))
        return boxes

    def read_screen(self) -> List[TextBox]:
        """Screenshot the screen and OCR it."""
        import numpy as np
        import pyautogui

        shot = pyautogui.screenshot()
        bgr = np.array(shot)[:, :, ::-1]     # PIL RGB -> BGR for RapidOCR
        return self.read_image(bgr)

    def locate(self, target: str, boxes: Optional[List[TextBox]] = None) -> Optional[TextBox]:
        """Find the best on-screen match for `target` text (case-insensitive)."""
        boxes = boxes if boxes is not None else self.read_screen()
        t = target.lower().strip()
        exact = [b for b in boxes if b.text.lower().strip() == t]
        if exact:
            return max(exact, key=lambda b: b.score)
        partial = [b for b in boxes if t in b.text.lower()]
        if partial:
            return max(partial, key=lambda b: (len(t) / max(len(b.text), 1), b.score))
        return None
