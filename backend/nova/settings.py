"""User settings — mode (PC Controlling vs Automation) and app connectors.

Stored as a small JSON file. The engine reads `mode` and the connectors to
decide, per task, whether to act directly through a connector (e.g. send mail
via Gmail) or fall back to the PC-controlling vision loop.
"""

from __future__ import annotations

import copy
import json
import threading
from pathlib import Path

DEFAULT = {
    "mode": "pc_control",              # pc_control | automation
    # which "brain" runs the assistant — fully local (private) or a cloud API.
    "brain": {
        "mode": "local",              # local | api
        "provider": "ollama",         # local: ollama ; api: openai|claude|gemini|grok
        "model": "qwen2.5:7b-instruct-q4_K_M",
        "api_key": "",                # only used when mode == api
    },
    # which account "owns" this PC — set when a phone pairs to it, so the phone
    # can tell its own PC apart from others on the same Wi-Fi.
    "owner_email": None,
    "device_name": None,               # friendly PC name shown in the phone's list
    "connectors": {
        # one Google login covers Gmail + Calendar + Drive + Contacts
        "google": {"connected": False, "email": None},
    },
}


def _deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Settings:
    def __init__(self, path: str = "nova_settings.json"):
        self.path = Path(path)
        self._lock = threading.Lock()
        self.data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                return _deep_merge(DEFAULT, loaded)   # keep new default keys too
            except Exception:
                pass
        return copy.deepcopy(DEFAULT)

    def _save(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")

    # --- reads --------------------------------------------------------------
    @property
    def mode(self) -> str:
        return self.data.get("mode", "pc_control")

    def google(self) -> dict:
        return self.data.get("connectors", {}).get("google", {})

    def gmail(self) -> dict:                       # engine still asks for gmail
        return self.google()

    def brain(self) -> dict:
        return self.data.get("brain", copy.deepcopy(DEFAULT["brain"]))

    @property
    def owner_email(self):
        return self.data.get("owner_email")

    @property
    def device_name(self):
        import platform
        return self.data.get("device_name") or platform.node() or "My PC"

    def set_owner(self, email, device_name=None) -> None:
        with self._lock:
            self.data["owner_email"] = (email or "").strip().lower() or None
            if device_name:
                self.data["device_name"] = device_name
            self._save()

    def public(self) -> dict:
        """Settings safe to send to the UI, plus whether OAuth is set up."""
        from .connectors.google import has_credentials

        d = copy.deepcopy(self.data)
        d["google_ready"] = has_credentials()      # is nova_gmail_credentials.json present?
        b = d.setdefault("brain", {})              # never leak the API key to the UI
        b["api_key_set"] = bool(b.get("api_key"))
        b["api_key"] = ""
        return d

    # --- writes -------------------------------------------------------------
    def set_mode(self, mode: str) -> None:
        with self._lock:
            self.data["mode"] = "automation" if mode == "automation" else "pc_control"
            self._save()

    def set_google_connected(self, email: str) -> None:
        with self._lock:
            self.data.setdefault("connectors", {})["google"] = {
                "connected": bool(email), "email": email,
            }
            self._save()

    def set_brain(self, mode=None, provider=None, model=None, api_key=None) -> None:
        """Update the brain choice. A blank/None api_key keeps the existing key
        (so the UI can re-save other fields without re-typing the secret)."""
        with self._lock:
            b = self.data.setdefault("brain", copy.deepcopy(DEFAULT["brain"]))
            if mode in ("local", "api"):
                b["mode"] = mode
            if provider:
                b["provider"] = provider
            if model:
                b["model"] = model
            if api_key:                            # only overwrite when a real key is given
                b["api_key"] = api_key
            self._save()
