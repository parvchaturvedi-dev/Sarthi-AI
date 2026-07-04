"""Vision-action loop — the general "operate any app" capability.

Instead of hardcoding each app (WhatsApp, etc.), Nova does what a human does:
look at the screen, decide one action, do it, look again. This is the
Screenshot -> OCR -> LLM decide -> click/type -> repeat loop.

Hardened behaviours:
  - open_url / scroll actions (so "web whatsapp" and off-screen contacts work)
  - re-reads the screen every step and tells the model whether it changed
  - stuck detection: if the screen stops changing, it stops instead of spinning
  - login/QR detection: if it lands on a sign-in wall it asks you to handle it
  - it announces what it's doing so you can follow along and abort (mouse to a
    screen corner = pyautogui failsafe) if it's about to do the wrong thing
"""

from __future__ import annotations

import base64
import io
import json
import logging
import time
from typing import Callable, Dict, List

from ..agent import tools
from ..agent.tools import ToolContext

log = logging.getLogger("nova.agent_loop")

DECIDE_SYSTEM = """You operate a Windows PC to accomplish a goal, like a human
using mouse and keyboard. You see the screen only as a list of visible text
labels (from OCR). Decide the SINGLE next action.

Return ONLY JSON, one of:
  {"action": "open_app", "name": "<app>"}          open an application
  {"action": "open_url", "url": "<https://...>"}   open a website (use for "web ...")
  {"action": "click",    "text": "<label>"}        click a VISIBLE text label
  {"action": "type",     "text": "<text>"}          type into the focused field
  {"action": "press",    "keys": "<key>"}           press a key/hotkey e.g. "enter"
  {"action": "scroll",   "direction": "down"}       scroll to reveal off-screen items
  {"action": "wait"}                                 let the screen settle
  {"action": "ask",      "message": "<hinglish>"}    need info OR a login/QR wall
  {"action": "done",     "message": "<hinglish>"}    goal achieved
  {"action": "fail",     "message": "<hinglish>"}    can't proceed

Sending an EMAIL (Gmail): the reliable way is ONE open_url to a prefilled Gmail
compose link, then click Send. Build the URL exactly like:
  https://mail.google.com/mail/?view=cm&fs=1&to=<TO>&su=<SUBJECT>&body=<BODY>
COMPOSE real content: write a proper SUBJECT and a complete BODY yourself in the
requested language — do NOT copy the user's instruction words literally. If they
say "subject apne hisaab se", invent a fitting subject. URL-encode spaces as %20
and newlines as %0A. After the compose window opens, click "Send".

Rules:
- LOOK AT VISIBLE FIRST. If the target app/website content is ALREADY on screen
  (you can see its chats, menus, search box), do NOT open it again — move on to
  the next real step (search / click / type).
- For "click", the text MUST appear in the VISIBLE list. If your target is not
  visible, "scroll" to find it (don't invent a label).
- To open a website (e.g. web.whatsapp.com) use "open_url", not open_app — but
  only if it is NOT already open.
- If you see a login / QR / "link a device" screen, or you're unsure which
  person/item the user means, use "ask" — do NOT guess.
- If SCREEN_CHANGED was false after your last action, try a different action.
- One action only. No prose. JSON object only.
"""

# Same task, but the model can actually SEE the screenshot. Each clickable text
# element is numbered [i] both in the list AND drawn on the image, so the model
# can point precisely by index — far more reliable than matching text alone, and
# it understands icons/layout/highlighting that OCR text can't convey.
VISION_SYSTEM = """You operate a Windows PC to accomplish a goal, like a human
using mouse and keyboard. You are given a SCREENSHOT of the current screen and a
numbered list of the clickable text elements OCR found (each number [i] is also
drawn on the screenshot). Look at the image, then decide the SINGLE next action.

Return ONLY JSON, one of:
  {"action": "open_app", "name": "<app>"}            open an application
  {"action": "open_url", "url": "<https://...>"}     open a website (use for "web ...")
  {"action": "click",    "index": <i>}               click element number i (preferred)
  {"action": "click",    "text": "<label>"}          click by visible text (if no number fits)
  {"action": "type",     "text": "<text>"}            type into the focused field
  {"action": "press",    "keys": "<key>"}             press a key/hotkey e.g. "enter"
  {"action": "scroll",   "direction": "down"}         scroll to reveal off-screen items
  {"action": "wait"}                                   let the screen settle
  {"action": "ask",      "message": "<hinglish>"}      need info OR a login/QR wall
  {"action": "done",     "message": "<hinglish>"}      goal achieved
  {"action": "fail",     "message": "<hinglish>"}      can't proceed

Sending an EMAIL (Gmail): the reliable way is ONE open_url to a prefilled Gmail
compose link, then click Send. Build it like:
  https://mail.google.com/mail/?view=cm&fs=1&to=<TO>&su=<SUBJECT>&body=<BODY>
Compose a real SUBJECT and complete BODY yourself in the requested language;
URL-encode spaces as %20 and newlines as %0A. Then click "Send".

Rules:
- PREFER {"action":"click","index":i}. Use the image to pick the RIGHT element
  (correct button, not a lookalike label). Only use "text" if nothing is numbered.
- LOOK AT THE IMAGE FIRST. If the target app/site is ALREADY visible (you can see
  its chats, menus, search box), do NOT open it again — move to the next step.
- If you see a login / QR / "link a device" screen, or you're unsure which
  person/item is meant, use "ask" — do NOT guess.
- If SCREEN_CHANGED was false after your last action, try something different.
- One action only. No prose. JSON object only.
"""

_LOGIN_HINTS = ("qr code", "scan the qr", "link a device", "link with phone",
                "log in", "sign in", "to use whatsapp on your")

# Nova's own floating-UI text — must never be treated as a screen element to click.
_NOVA_UI = ("working:", "listening", "sun rahi", "suna:", "samajh nahi",
            "ready.", "press the button", "type a command", "wake word",
            "🎙", "nova")


def _is_nova_ui(text: str) -> bool:
    t = text.lower()
    return any(h in t for h in _NOVA_UI)


def _looks_like_login(elements: List[str]) -> bool:
    blob = " | ".join(elements).lower()
    return any(h in blob for h in _LOGIN_HINTS)


class VisionAgent:
    def __init__(
        self,
        llm,
        speak: Callable[[str], None],
        *,
        vision_llm=None,
        max_steps: int = 14,
        step_pause_s: float = 1.2,
        dry_run: bool = False,
    ):
        self.llm = llm
        self.vision_llm = vision_llm     # VLM that SEES the screenshot (or None)
        self.speak = speak
        self.max_steps = max_steps
        self.dry_run = dry_run
        self.ctx = ToolContext(speak=speak, pause=step_pause_s)
        self._ocr = None
        self._marks: List = []           # filtered TextBoxes aligned with the list
        self._shot_b64 = None            # annotated screenshot for the VLM

    # --- perception ---------------------------------------------------------
    def _see(self, limit: int = 45) -> List[str]:
        """One screenshot -> OCR (for click coords) + an annotated copy (for the VLM).

        Screenshotting once and OCR-ing that exact image keeps the drawn [i] marks
        perfectly aligned with the click coordinates.
        """
        if self._ocr is None:
            from ..vision.ocr import OcrEngine
            self._ocr = OcrEngine()

        import numpy as np
        import pyautogui

        shot = pyautogui.screenshot()               # PIL RGB
        bgr = np.array(shot)[:, :, ::-1]            # -> BGR for RapidOCR
        boxes = self._ocr.read_image(bgr)

        seen, marks, out = set(), [], []
        for b in boxes:
            t = b.text.strip()
            if t and t.lower() not in seen and not _is_nova_ui(t):
                seen.add(t.lower())
                marks.append(b)
                out.append(t)
                if len(out) >= limit:
                    break

        self._marks = marks
        self._shot_b64 = self._annotate(shot, marks) if self.vision_llm else None
        return out

    def _annotate(self, shot, marks) -> str | None:
        """Draw [i] tags on a downscaled screenshot; return base64 PNG (set-of-marks)."""
        try:
            from PIL import Image, ImageDraw

            img = shot.convert("RGB")
            w, h = img.size
            scale = min(1.0, 1280.0 / max(w, h))
            if scale < 1.0:
                img = img.resize((int(w * scale), int(h * scale)), Image.BILINEAR)
            draw = ImageDraw.Draw(img)
            for i, b in enumerate(marks):
                cx, cy = b.center
                x, y = int(cx * scale), int(cy * scale)
                tag = str(i)
                pad = 3 + 6 * len(tag)
                draw.rectangle([x - 2, y - 9, x + pad, y + 3], fill=(220, 20, 60))
                draw.text((x, y - 9), tag, fill=(255, 255, 255))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode("ascii")
        except Exception as e:  # noqa: BLE001
            log.info("annotate failed, VLM will fall back to text: %s", e)
            return None

    # --- decision -----------------------------------------------------------
    def decide(self, goal: str, elements: List[str], history: List[Dict],
               screen_changed: bool) -> Dict:
        # Vision path first (the model literally sees the screen); fall back to
        # text-only OCR reasoning if there's no VLM or it doesn't respond.
        if self.vision_llm is not None and self._shot_b64:
            data = self._decide_vision(goal, elements, history, screen_changed)
            if data and "action" in data:
                return data
            log.info("VLM gave nothing usable — falling back to text decide")
        return self._decide_text(goal, elements, history, screen_changed)

    def _numbered(self, elements: List[str]) -> str:
        return "\n".join(f"[{i}] {t}" for i, t in enumerate(elements))

    def _decide_vision(self, goal: str, elements: List[str], history: List[Dict],
                       screen_changed: bool) -> Dict:
        user = (
            f"GOAL: {goal}\n\n"
            f"NUMBERED ELEMENTS (each [i] is also drawn on the screenshot):\n"
            f"{self._numbered(elements)}\n\n"
            f"SCREEN_CHANGED after last action: {screen_changed}\n\n"
            f"ACTIONS DONE SO FAR:\n{json.dumps(history[-6:], ensure_ascii=False)}\n\n"
            "Look at the screenshot and decide the next action."
        )
        return self.vision_llm.chat_json_vision(VISION_SYSTEM, user, [self._shot_b64]) or {}

    def _decide_text(self, goal: str, elements: List[str], history: List[Dict],
                     screen_changed: bool) -> Dict:
        if self.llm is None:
            return {"action": "fail", "message": "Brain offline hai, abhi ye nahi kar sakti."}
        user = (
            f"GOAL: {goal}\n\n"
            f"VISIBLE ON SCREEN:\n{json.dumps(elements, ensure_ascii=False)}\n\n"
            f"SCREEN_CHANGED after last action: {screen_changed}\n\n"
            f"ACTIONS DONE SO FAR:\n{json.dumps(history[-6:], ensure_ascii=False)}\n\n"
            "Next action?"
        )
        data = self.llm.chat_json(DECIDE_SYSTEM, user)
        if not data or "action" not in data:
            return {"action": "fail", "message": "Samajh nahi aaya aage kya karun."}
        return data

    # --- action -------------------------------------------------------------
    def _do(self, action: Dict) -> str:
        a = action.get("action")
        if self.dry_run:
            return f"[dry-run] {action}"
        if a == "open_app":
            return tools.open_app(self.ctx, action.get("name", ""))
        if a == "open_url":
            return tools.open_url(self.ctx, action.get("url", ""))
        if a == "click":
            idx = action.get("index")
            if isinstance(idx, int) and 0 <= idx < len(self._marks):
                import pyautogui
                b = self._marks[idx]
                x, y = b.center
                pyautogui.click(x, y)
                return f"clicked [{idx}] '{b.text}' at ({x},{y})"
            return tools.click_text(self.ctx, action.get("text", ""))
        if a == "type":
            return tools.type_text(self.ctx, action.get("text", ""))
        if a == "press":
            return tools.press_keys(self.ctx, action.get("keys", "enter"))
        if a == "scroll":
            return tools.scroll(self.ctx, action.get("direction", "down"))
        if a == "wait":
            return tools.wait(self.ctx, 1.0)
        return f"unknown action {a}"

    # --- the loop -----------------------------------------------------------
    def run(self, goal: str) -> bool:
        history: List[Dict] = []
        prev: List[str] = []
        stuck = 0

        for step in range(self.max_steps):
            elements = self._see()
            changed = step == 0 or elements != prev

            if _looks_like_login(elements):
                self.speak("WhatsApp Web pe login/QR screen hai — aap QR scan karke bolo, "
                           "phir main aage badhungi.")
                return False

            stuck = stuck + 1 if (step > 0 and not changed) else 0
            if stuck >= 2:
                self.speak("Screen change nahi ho raha, lagta hai main atak gayi. Aap khud dekh lo.")
                return False

            action = self.decide(goal, elements, history, changed)
            a = action.get("action")
            log.info("step %d (changed=%s): %s", step + 1, changed, action)

            if a == "done":
                self.speak(action.get("message") or "Ho gaya.")
                return True
            if a == "fail":
                self.speak(action.get("message") or "Sorry, ye nahi kar payi.")
                return False
            if a == "ask":
                self.speak(action.get("message") or "Thoda confirm karo — kaunsa wala?")
                return False

            # announce the meaningful moves so the user can follow / abort
            if a == "open_app":
                self.speak(f"{action.get('name', 'app')} khol rahi hoon.")
            elif a == "open_url":
                self.speak("website khol rahi hoon.")
            elif a == "type":
                self.speak("type kar rahi hoon.")

            prev = elements
            try:
                detail = self._do(action)
                history.append({"action": a, "args": {k: v for k, v in action.items() if k != "action"},
                                "result": detail[:80]})
            except Exception as e:  # noqa: BLE001
                log.warning("action failed: %s", e)
                history.append({"action": a, "result": f"failed: {e}"})
            time.sleep(self.ctx.pause)

        self.speak("Itne steps me pura nahi kar payi, ruk rahi hoon.")
        return False
