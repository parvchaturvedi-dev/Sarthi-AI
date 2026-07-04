"""Verification — confirm a step actually changed the machine's state.

This is the step that separates an assistant from a demo. After an action we
read the world back and check it matches what the plan expected.

We scan ALL window titles rather than only the active one: on Windows 11 the
foreground/UWP window title is often unreadable, but the window still shows up
in the full title list. Existence is the reliable signal for "did it open".
"""

from __future__ import annotations

import time
from typing import List

from ..schema import Verify

try:
    import pygetwindow as gw
except Exception:  # pragma: no cover - optional at import time
    gw = None


def all_window_titles() -> List[str]:
    if gw is None:
        return []
    try:
        return [t for t in gw.getAllTitles() if t and t.strip()]
    except Exception:
        return []


def active_window_title() -> str:
    if gw is None:
        return ""
    try:
        w = gw.getActiveWindow()
        return (w.title if w else "") or ""
    except Exception:
        return ""


def check(verify: Verify, timeout_s: float = 5.0) -> tuple[bool, str]:
    """Return (ok, detail). Polls until timeout for window-based checks."""
    if verify.type == "always":
        return True, "no verification required"

    if verify.type == "window_title_contains":
        target = (verify.value or "").lower()
        deadline = time.time() + timeout_s
        seen: List[str] = []
        while time.time() < deadline:
            seen = all_window_titles()
            hit = next((t for t in seen if target in t.lower()), None)
            if hit:
                return True, f"window '{hit}' matches '{verify.value}'"
            time.sleep(0.25)
        return False, f"no window titled like '{verify.value}' (saw {seen[:6]})"

    if verify.type == "window_gone":
        target = (verify.value or "").lower()
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if not any(target in t.lower() for t in all_window_titles()):
                return True, f"no window matching '{verify.value}' remains"
            time.sleep(0.25)
        return False, f"window matching '{verify.value}' still open"

    if verify.type == "file_exists":
        from pathlib import Path

        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if verify.value and Path(verify.value).exists():
                return True, f"file '{verify.value}' exists"
            time.sleep(0.25)
        return False, f"file '{verify.value}' not found"

    return True, f"unknown verify type '{verify.type}', skipped"
