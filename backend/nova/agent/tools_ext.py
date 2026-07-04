"""Extra desktop tools — system control + productivity.

Registered into the main tool registry (see tools.py). Each is a small verifiable
action; the brain calls them by name. Destructive/outward ones (power, WhatsApp)
are marked sensitive so they hit the confirmation gate.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Dict, List

import pyautogui

log = logging.getLogger("nova.tools_ext")

SENSITIVE = {"system_power"}

SPECS: List[Dict[str, str]] = [
    {"tool": "set_volume", "args": "{level: int}", "desc": "Set system volume 0-100."},
    {"tool": "change_volume", "args": "{direction: str}", "desc": "Nudge volume 'up' or 'down'."},
    {"tool": "mute", "args": "{state: bool}", "desc": "Mute (true) or unmute (false) audio."},
    {"tool": "set_reminder", "args": "{minutes: float, seconds: float, text: str}", "desc": "Speak a reminder after a delay."},
    {"tool": "window", "args": "{action: str}", "desc": "Manage active window: minimize/maximize/restore/snap_left/snap_right/minimize_all/switch."},
    {"tool": "find_file", "args": "{name: str}", "desc": "Search Desktop/Documents/Downloads for a file by name."},
    {"tool": "open_file", "args": "{path: str}", "desc": "Open a file (by full path or name)."},
    {"tool": "play_youtube", "args": "{query: str}", "desc": "Open YouTube for a song/video."},
    {"tool": "system_power", "args": "{action: str}", "desc": "lock/sleep/restart/shutdown/logoff (sensitive)."},
]


# --- volume (pycaw) ---------------------------------------------------------
def _endpoint_volume():
    from pycaw.pycaw import AudioUtilities

    dev = AudioUtilities.GetSpeakers()
    # Newer pycaw exposes the cast interface directly.
    if getattr(dev, "EndpointVolume", None) is not None:
        return dev.EndpointVolume
    # Older pycaw: activate it ourselves.
    from ctypes import POINTER, cast

    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import IAudioEndpointVolume

    iface = dev._dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(iface, POINTER(IAudioEndpointVolume))


def set_volume(ctx, level=50) -> str:
    v = _endpoint_volume()
    lv = max(0, min(100, int(level)))
    v.SetMasterVolumeLevelScalar(lv / 100.0, None)
    return f"volume set to {lv}%"


def change_volume(ctx, direction="up") -> str:
    v = _endpoint_volume()
    cur = v.GetMasterVolumeLevelScalar()
    up = str(direction).lower() in ("up", "badhao", "increase", "raise", "+", "high", "tez")
    new = max(0.0, min(1.0, cur + (0.1 if up else -0.1)))
    v.SetMasterVolumeLevelScalar(new, None)
    return f"volume {'up' if up else 'down'} to {int(round(new * 100))}%"


def mute(ctx, state=True) -> str:
    v = _endpoint_volume()
    on = state in (True, 1, "on", "mute", "yes", "true", "True", "1")
    v.SetMute(1 if on else 0, None)
    return "muted" if on else "unmuted"


# --- reminder / timer -------------------------------------------------------
def set_reminder(ctx, minutes=0, seconds=0, text="") -> str:
    delay = float(minutes) * 60 + float(seconds)
    if delay <= 0:
        delay = 60.0
    msg = text or "आपका रिमाइंडर।"

    def fire() -> None:
        try:
            ctx.speak(msg)
        except Exception as e:  # noqa: BLE001
            log.warning("reminder speak failed: %s", e)

    t = threading.Timer(delay, fire)
    t.daemon = True
    t.start()
    return f"reminder set in {int(delay)}s: {text or '(reminder)'}"


# --- window management ------------------------------------------------------
def window(ctx, action="minimize") -> str:
    import pygetwindow as gw

    a = str(action).lower()
    if a in ("minimize_all", "show_desktop"):
        pyautogui.hotkey("win", "d")
        return "minimized everything"
    if a in ("switch", "switch_apps", "alt_tab", "next"):
        pyautogui.hotkey("alt", "tab")
        return "switched window"
    if a in ("snap_left", "left"):
        pyautogui.hotkey("win", "left")
        return "snapped left"
    if a in ("snap_right", "right"):
        pyautogui.hotkey("win", "right")
        return "snapped right"

    w = gw.getActiveWindow()
    if not w:
        return "no active window"
    if a in ("minimize", "min"):
        w.minimize(); return f"minimized {w.title or 'window'}"
    if a in ("maximize", "max"):
        w.maximize(); return f"maximized {w.title or 'window'}"
    if a in ("restore",):
        w.restore(); return f"restored {w.title or 'window'}"
    return f"unknown window action '{action}'"


# --- files ------------------------------------------------------------------
_SEARCH_DIRS = [
    Path.home() / "Desktop", Path.home() / "Documents", Path.home() / "Downloads",
    Path.home() / "OneDrive" / "Desktop", Path.home() / "OneDrive" / "Documents",
    Path.home() / "Pictures",
]


def find_file(ctx, name="", limit=5) -> str:
    q = name.lower().strip()
    if not q:
        return "no name given"
    hits: List[str] = []
    for d in _SEARCH_DIRS:
        if not d.exists():
            continue
        try:
            for p in d.rglob("*"):
                if q in p.name.lower():
                    hits.append(str(p))
                    if len(hits) >= limit:
                        return "; ".join(hits)
        except Exception:
            continue
    return "; ".join(hits) if hits else f"no file matching '{name}'"


def open_file(ctx, path="") -> str:
    p = Path(path)
    if not p.exists():
        found = find_file(ctx, path, 1)
        if found.startswith("no file") or found == "no name given":
            raise RuntimeError(f"file not found: {path}")
        p = Path(found.split(";")[0].strip())
    os.startfile(str(p))  # noqa: S606 - user-directed file open
    return f"opened {p.name}"


# --- media / messaging ------------------------------------------------------
def play_youtube(ctx, query="") -> str:
    q = urllib.parse.quote(query)
    url = f"https://www.youtube.com/results?search_query={q}"
    if getattr(ctx, "use_managed_browser", True):
        try:
            from ..browser.manager import get_browser
            get_browser(getattr(ctx, "browser_profile", "browser_profile")).open_or_focus(url)
            return f"YouTube par '{query}' khol rahi hoon"
        except Exception:
            pass
    webbrowser.open(url)
    return f"YouTube par '{query}' khol rahi hoon"


def system_power(ctx, action="lock") -> str:
    a = str(action).lower()
    cmds = {
        "lock": ["rundll32.exe", "user32.dll,LockWorkStation"],
        "sleep": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
        "restart": ["shutdown", "/r", "/t", "0"],
        "shutdown": ["shutdown", "/s", "/t", "0"],
        "logoff": ["shutdown", "/l"],
    }
    if a not in cmds:
        raise RuntimeError(f"unknown power action '{action}'")
    subprocess.Popen(cmds[a])
    return f"{a} triggered"


REGISTRY = {
    "set_volume": set_volume,
    "change_volume": change_volume,
    "mute": mute,
    "set_reminder": set_reminder,
    "window": window,
    "find_file": find_file,
    "open_file": open_file,
    "play_youtube": play_youtube,
    "system_power": system_power,
}
