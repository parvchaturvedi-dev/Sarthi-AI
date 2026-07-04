"""Image analysis — Sarthi looks at a photo and tells you what's in it.

Reuses the local vision model (qwen2.5-VL) already pulled for the operate-loop,
so this is fully offline. Handles "is photo me kya hai", reading text off an
image, answering a specific question about a picture, etc.
"""

from __future__ import annotations

import base64
import io
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger("nova.analyze")

ANALYZE_SYSTEM = {
    "hinglish": (
        "You are Sarthi. Look at the image and answer in casual HINGLISH (Roman, "
        "female voice: 'dikh raha hai'). Be specific and accurate about what's "
        "actually visible — objects, people, text, colours, scene. If the user "
        "asked a specific question, answer THAT. Never use Devanagari."
    ),
    "hindi": (
        "तुम सारथी हो। तस्वीर देखकर देवनागरी हिंदी में साफ़ जवाब दो — जो सच में दिख "
        "रहा है वही बताओ। अगर कोई ख़ास सवाल पूछा है तो उसी का जवाब दो।"
    ),
    "english": (
        "You are Sarthi. Look at the image and answer clearly and accurately about "
        "what's actually visible — objects, people, any text, colours, the scene. "
        "If the user asked a specific question, answer that one."
    ),
}

_MAX_SIDE = 1400            # downscale big photos so the VLM stays fast


def _encode(image_path: str) -> Optional[str]:
    p = Path(image_path)
    if not p.exists():
        return None
    try:
        from PIL import Image

        img = Image.open(p).convert("RGB")
        w, h = img.size
        scale = min(1.0, _MAX_SIDE / max(w, h))
        if scale < 1.0:
            img = img.resize((int(w * scale), int(h * scale)), Image.BILINEAR)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception as e:  # noqa: BLE001
        log.warning("could not read image %s: %s", image_path, e)
        return None


class ImageAnalyzer:
    def __init__(self, vision_llm, language: str = "english"):
        self.llm = vision_llm
        self.language = language

    def available(self) -> bool:
        return self.llm is not None

    def describe(self, image_path: str, question: Optional[str] = None) -> Optional[str]:
        """Answer `question` about the image (or describe it if no question)."""
        if not self.available():
            return None
        b64 = _encode(image_path)
        if not b64:
            return None
        system = ANALYZE_SYSTEM.get(self.language, ANALYZE_SYSTEM["english"])
        user = (question or "").strip() or (
            "Describe this image in detail — what is in it?"
        )
        return self.llm.chat_vision_text(system, user, [b64])
