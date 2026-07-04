"""Read the user's REAL Chrome profiles and open URLs in a chosen one.

The managed (Playwright) browser uses Nova's own empty profile — which looks like
"guest mode" (none of your accounts). For normal browsing the user wants their
actual signed-in Chrome profile, so here we:
  - read the profile list from Chrome's `Local State` (name + signed-in email),
  - launch the real chrome.exe with `--profile-directory=<folder>` so the chosen
    account (with its logins) opens.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

log = logging.getLogger("nova.chrome")


def _user_data_dir() -> Path:
    return Path(os.getenv("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data"


def list_chrome_profiles() -> List[dict]:
    """Return [{'dir','name','email'}, ...] in Chrome's own display order."""
    ls = _user_data_dir() / "Local State"
    if not ls.exists():
        return []
    try:
        data = json.loads(ls.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        log.info("could not read Chrome Local State: %s", e)
        return []
    prof = data.get("profile") or {}
    cache = prof.get("info_cache") or {}
    order = prof.get("profiles_order") or list(cache.keys())

    def entry(d: str) -> dict:
        info = cache.get(d) or {}
        return {
            "dir": d,
            "name": (info.get("name") or d).strip(),
            "email": (info.get("user_name") or "").strip(),
        }

    out = [entry(d) for d in order if d in cache]
    for d in cache:                       # any not listed in the order array
        if all(o["dir"] != d for o in out):
            out.append(entry(d))
    return out


def chrome_exe() -> Optional[str]:
    cands = [
        Path(os.getenv("PROGRAMFILES", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.getenv("PROGRAMFILES(X86)", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.getenv("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    ]
    for c in cands:
        if c.exists():
            return str(c)
    return shutil.which("chrome")


def open_in_profile(profile_dir: str, url: Optional[str] = None) -> bool:
    """Launch real Chrome with the given profile folder (and optional URL)."""
    exe = chrome_exe()
    if not exe:
        log.info("chrome.exe not found")
        return False
    args = [exe, f"--profile-directory={profile_dir}"]
    if url:
        args.append(url)
    try:
        subprocess.Popen(args)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("failed to launch Chrome profile %s: %s", profile_dir, e)
        return False
