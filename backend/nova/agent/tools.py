"""The tool registry — the ONLY place in Nova that touches the OS.

Each tool is a small, verifiable action. The brain selects tools by name and
supplies args; it never imports or runs any of this directly.

To add a capability, register a new tool here and describe it in TOOL_SPECS so
the planner knows it exists.
"""

from __future__ import annotations

import os
import re
import subprocess
import time
import webbrowser
from pathlib import Path
from typing import Any, Callable, Dict, List

import pyautogui

pyautogui.FAILSAFE = True   # slam mouse to a corner to abort

# Tools that ALWAYS require user confirmation, no matter what the planner marks.
ALWAYS_SENSITIVE = {"run_shell"}

# Patterns hard-blocked in run_shell even after confirmation — irreversible/destructive.
_SHELL_DENYLIST = [
    r"\brm\s+-rf\b", r"remove-item\b.*-recurse", r"\brd\s+/s\b", r"\bdel\s+/[sq]\b",
    r"\bformat\b", r"\bmkfs\b", r"\bdiskpart\b", r"\bshutdown\b", r"\bReset-Computer\b",
    r":\s*>\s*/dev", r"\bfdisk\b",
]

SCREENSHOT_DIR = Path("screenshots")

# Human-friendly name -> launch command. Unknown apps fall back to Start-menu search.
KNOWN_APPS: Dict[str, str] = {
    "notepad": "notepad",
    "calculator": "calc",
    "calc": "calc",
    "explorer": "explorer",
    "file explorer": "explorer",
    "cmd": "cmd",
    "command prompt": "cmd",
    "powershell": "powershell",
    "chrome": "chrome",
    "google chrome": "chrome",
    "edge": "msedge",
    "firefox": "firefox",
    "vscode": "code",
    "vs code": "code",
    "code": "code",
    "settings": "ms-settings:",
    "paint": "mspaint",
    "word": "winword",
    "excel": "excel",
}

# What the planner is told it can call. Keep in sync with the registry below.
TOOL_SPECS: List[Dict[str, str]] = [
    {"tool": "open_app", "args": "{name: str}", "desc": "Launch an application by name."},
    {"tool": "open_url", "args": "{url: str}", "desc": "Open a website in the default browser."},
    {"tool": "type_text", "args": "{text: str}", "desc": "Type text into the focused window."},
    {"tool": "press_keys", "args": "{keys: str}", "desc": "Press a key or hotkey, e.g. 'enter' or 'ctrl+s'."},
    {"tool": "wait", "args": "{seconds: float}", "desc": "Pause to let the UI settle."},
    {"tool": "scroll", "args": "{direction: str, amount: int}", "desc": "Scroll up/down to reveal off-screen content."},
    {"tool": "say", "args": "{text: str}", "desc": "Speak a short message to the user mid-task."},
    {"tool": "focus_window", "args": "{title: str}", "desc": "Bring an open window to the front before typing into it."},
    {"tool": "close_app", "args": "{name: str}", "desc": "Close windows whose title matches name."},
    {"tool": "clipboard_set", "args": "{text: str}", "desc": "Put text on the clipboard."},
    {"tool": "clipboard_get", "args": "{}", "desc": "Read the current clipboard text."},
    {"tool": "screenshot", "args": "{path?: str}", "desc": "Capture the screen to an image file."},
    {"tool": "read_screen", "args": "{}", "desc": "OCR the screen and return the visible text."},
    {"tool": "click_text", "args": "{text: str}", "desc": "Find on-screen text via OCR and click it."},
    {"tool": "run_shell", "args": "{command: str}", "desc": "Run a PowerShell command (sensitive; asks first)."},
]


class ToolContext:
    """Shared services handed to tools at call time (speaker, config, memory)."""

    def __init__(
        self,
        speak: Callable[[str], None],
        pause: float = 0.6,
        use_managed_browser: bool = True,
        browser_profile: str = "browser_profile",
    ):
        self.speak = speak
        self.pause = pause
        self.use_managed_browser = use_managed_browser
        self.browser_profile = browser_profile


# --- individual tools -------------------------------------------------------

def _launch(cmd: str) -> None:
    """Launch a command without blocking. Handles protocol handlers and exes."""
    if cmd.endswith(":"):                       # e.g. ms-settings:
        os.startfile(cmd)                       # noqa: S606 - trusted, from KNOWN_APPS
        return
    # `start` resolves PATH apps (code.cmd, chrome) and detaches cleanly.
    subprocess.Popen(["cmd", "/c", "start", "", cmd], shell=False)


def _shortcut_dirs() -> List[Path]:
    """Folders where Windows keeps app shortcuts: Desktop + Start Menu."""
    home = Path.home()
    env = os.environ.get
    cands = [
        home / "Desktop",
        home / "OneDrive" / "Desktop",
        Path(env("PUBLIC", "") or "X:\\nope") / "Desktop",
        Path(env("APPDATA", "") or "X:\\nope") / "Microsoft/Windows/Start Menu/Programs",
        Path(env("PROGRAMDATA", "") or "X:\\nope") / "Microsoft/Windows/Start Menu/Programs",
    ]
    return [d for d in cands if d.exists()]


def _norm_name(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def find_app_shortcut(name: str) -> "str | None":
    """Find a Desktop/Start-Menu shortcut (.lnk/.url/.exe) matching `name`.

    This is what makes "open LegalX" work: LegalX has no Start-menu entry, but it
    IS a shortcut on the Desktop — so we resolve it to a real path and launch it.
    """
    target = _norm_name(re.sub(r"\bapp\b", " ", name or "", flags=re.I))
    if len(target) < 2:
        return None
    exts = (".lnk", ".url", ".exe")
    partial = None
    for d in _shortcut_dirs():
        try:
            entries = d.rglob("*") if "Start Menu" in str(d) else d.iterdir()
        except OSError:
            continue
        for p in entries:
            try:
                if not p.is_file() or p.suffix.lower() not in exts:
                    continue
            except OSError:
                continue
            stem = _norm_name(p.stem)
            if stem == target:
                return str(p)                      # exact match — best
            if partial is None and len(target) >= 3 and (target in stem or stem in target):
                partial = str(p)
    return partial


def _double_click_desktop_icon(name: str) -> "str | None":
    """See the desktop and double-click the icon by name — like a human would."""
    try:
        pyautogui.hotkey("win", "d")               # show the desktop
        time.sleep(0.9)
        box = _ocr().locate(name)
        if box is None and name.split():
            box = _ocr().locate(name.split()[0])
        if box is None:
            pyautogui.hotkey("win", "d")            # restore — nothing found
            return None
        x, y = box.center
        pyautogui.doubleClick(x, y)
        return f"double-clicked '{box.text}' on the desktop"
    except Exception:
        return None


def open_app(ctx: ToolContext, name: str) -> str:
    key = (name or "").strip().lower()
    cmd = KNOWN_APPS.get(key)
    if cmd:
        _launch(cmd)
        return f"launched {name} via '{cmd}'"

    # A real shortcut on the Desktop / Start Menu -> launch it directly. This is
    # "double-clicking the icon", but reliable — no Start-menu guessing.
    sc = find_app_shortcut(name)
    if sc:
        os.startfile(sc)                           # noqa: S606 - user's own shortcut
        return f"opened {name} via {os.path.basename(sc)}"

    # No shortcut file: look at the desktop and double-click the icon.
    hit = _double_click_desktop_icon(name)
    if hit:
        return hit

    # Truly not found anywhere: fall back to typing into the Start menu.
    pyautogui.press("win")
    time.sleep(0.5)
    pyautogui.typewrite(name, interval=0.02)
    time.sleep(0.6)
    pyautogui.press("enter")
    return f"searched Start menu for {name}"


def open_url(ctx: ToolContext, url: str) -> str:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    # Prefer Nova's persistent browser so tabs are reused (not a new tab each time).
    if getattr(ctx, "use_managed_browser", True):
        try:
            from ..browser.manager import get_browser
            get_browser(getattr(ctx, "browser_profile", "browser_profile")).open_or_focus(url)
            return f"opened/focused {url} in Nova's browser"
        except Exception as e:  # noqa: BLE001 - fall back to the default browser
            import logging
            logging.getLogger("nova.tools").info("managed browser failed (%s); default", e)
    webbrowser.open(url)
    return f"opened {url}"


def type_text(ctx: ToolContext, text: str) -> str:
    pyautogui.typewrite(text, interval=0.02)
    return f"typed {len(text)} chars"


def press_keys(ctx: ToolContext, keys: str) -> str:
    parts = [k.strip() for k in keys.replace("+", " ").split() if k.strip()]
    if len(parts) == 1:
        pyautogui.press(parts[0])
    else:
        pyautogui.hotkey(*parts)
    return f"pressed {keys}"


def wait(ctx: ToolContext, seconds: float = 1.0) -> str:
    time.sleep(min(float(seconds), 10.0))       # clamp so a bad plan can't hang us
    return f"waited {seconds}s"


def scroll(ctx: ToolContext, direction: str = "down", amount: int = 500) -> str:
    a = str(direction).lower()
    clicks = int(amount)
    pyautogui.scroll(-clicks if a in ("down", "neeche", "niche") else clicks)
    return f"scrolled {a} {clicks}"


def say(ctx: ToolContext, text: str) -> str:
    ctx.speak(text)
    return "spoke"


def focus_window(ctx: ToolContext, title: str) -> str:
    import pygetwindow as gw

    wins = [w for w in gw.getWindowsWithTitle(title)] if title else []
    if not wins:
        raise RuntimeError(f"no window matching '{title}'")
    w = wins[0]
    try:
        if w.isMinimized:
            w.restore()
        w.activate()
    except Exception:
        # activate() is flaky on Windows; a minimize+restore usually forces focus.
        try:
            w.minimize(); w.restore()
        except Exception:
            pass
    return f"focused '{w.title}'"


def close_app(ctx: ToolContext, name: str) -> str:
    import pygetwindow as gw

    key = (name or "").lower()
    wins = [w for w in gw.getAllWindows() if key in (w.title or "").lower()]
    if not wins:
        return f"no open window matching '{name}'"
    for w in wins:
        try:
            w.close()
        except Exception:
            pass
    return f"closed {len(wins)} window(s) matching '{name}'"


def clipboard_set(ctx: ToolContext, text: str) -> str:
    import win32clipboard

    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
    finally:
        win32clipboard.CloseClipboard()
    return f"copied {len(text)} chars to clipboard"


def clipboard_get(ctx: ToolContext) -> str:
    import win32clipboard

    win32clipboard.OpenClipboard()
    try:
        data = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
    except Exception:
        data = ""
    finally:
        win32clipboard.CloseClipboard()
    return data or ""


def screenshot(ctx: ToolContext, path: str = "") -> str:
    SCREENSHOT_DIR.mkdir(exist_ok=True)
    target = Path(path) if path else SCREENSHOT_DIR / "shot.png"
    img = pyautogui.screenshot()
    img.save(str(target))
    return str(target.resolve())


_OCR = None


def _ocr():
    """Lazily build the OCR engine once (model load is slow)."""
    global _OCR
    if _OCR is None:
        from ..vision.ocr import OcrEngine
        _OCR = OcrEngine()
    return _OCR


def read_screen(ctx: ToolContext) -> str:
    boxes = _ocr().read_screen()
    if not boxes:
        return "(no text found on screen)"
    text = " | ".join(b.text for b in boxes)
    return text[:1500]


def click_text(ctx: ToolContext, text: str) -> str:
    box = _ocr().locate(text)
    if box is None:
        raise RuntimeError(f"could not find '{text}' on screen")
    x, y = box.center
    pyautogui.click(x, y)
    return f"clicked '{box.text}' at ({x},{y})"


def run_shell(ctx: ToolContext, command: str) -> str:
    for pat in _SHELL_DENYLIST:
        if re.search(pat, command, re.I):
            raise RuntimeError(f"refused: '{command}' matches a destructive pattern")
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True, text=True, timeout=60,
    )
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    tail = out[-500:] if out else (err[-500:] if err else "(no output)")
    return f"exit={proc.returncode}; {tail}"


REGISTRY: Dict[str, Callable[..., str]] = {
    "open_app": open_app,
    "open_url": open_url,
    "type_text": type_text,
    "press_keys": press_keys,
    "wait": wait,
    "scroll": scroll,
    "say": say,
    "focus_window": focus_window,
    "close_app": close_app,
    "clipboard_set": clipboard_set,
    "clipboard_get": clipboard_get,
    "screenshot": screenshot,
    "read_screen": read_screen,
    "click_text": click_text,
    "run_shell": run_shell,
}

# Merge the extra system/productivity tools (kept in a separate module for size).
from . import tools_ext  # noqa: E402

REGISTRY.update(tools_ext.REGISTRY)
TOOL_SPECS.extend(tools_ext.SPECS)
ALWAYS_SENSITIVE |= tools_ext.SENSITIVE
