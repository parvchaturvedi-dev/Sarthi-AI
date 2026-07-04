"""Thin Ollama client. Asks for JSON-only responses so the planner can parse them.

Kept dependency-light (just `requests`) and defensive: a short probe tells the
planner whether to use the model or fall back to rules.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

import requests

log = logging.getLogger("nova.llm")


class OllamaClient:
    def __init__(self, url: str, model: str, timeout_s: int = 60,
                 embed_model: str = "nomic-embed-text"):
        self.url = url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s
        self.embed_model = embed_model

    def available(self) -> bool:
        """Quick reachability + model-presence probe (~1s)."""
        try:
            r = requests.get(f"{self.url}/api/tags", timeout=2)
            r.raise_for_status()
            names = [m.get("name", "") for m in r.json().get("models", [])]
            if names and not any(self.model.split(":")[0] in n for n in names):
                log.warning("model %s not found; have: %s", self.model, names)
            return True
        except Exception as e:
            log.info("Ollama unavailable: %s", e)
            return False

    def has_model(self, model: str) -> bool:
        """True only if `model` is actually pulled (stricter than available())."""
        try:
            r = requests.get(f"{self.url}/api/tags", timeout=2)
            r.raise_for_status()
            names = [m.get("name", "") for m in r.json().get("models", [])]
            stem = model.split(":")[0]
            return any(model == n or stem in n for n in names)
        except Exception as e:
            log.info("has_model probe failed: %s", e)
            return False

    def warm(self) -> None:
        """Load the model into memory so the first real plan isn't slow."""
        try:
            requests.post(
                f"{self.url}/api/generate",
                json={"model": self.model, "prompt": "ok", "stream": False},
                timeout=self.timeout_s,
            )
            log.info("model %s warmed", self.model)
        except Exception as e:
            log.info("warm-up skipped: %s", e)

    def chat_text(self, messages: list, temperature: float = 0.6) -> Optional[str]:
        """Plain conversational reply (no JSON) from a messages list."""
        payload = {
            "model": self.model,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": 512},
            "messages": messages,
        }
        try:
            r = requests.post(f"{self.url}/api/chat", json=payload, timeout=self.timeout_s)
            r.raise_for_status()
            return (r.json().get("message", {}).get("content", "") or "").strip()
        except Exception as e:
            log.warning("Ollama chat_text failed: %s", e)
            return None

    def chat_stream(self, messages: list, temperature: float = 0.6):
        """Yield the reply in chunks as they generate (for speak-as-you-go TTS)."""
        payload = {
            "model": self.model,
            "stream": True,
            "options": {"temperature": temperature, "num_predict": 512},
            "messages": messages,
        }
        try:
            with requests.post(
                f"{self.url}/api/chat", json=payload, timeout=self.timeout_s, stream=True
            ) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    chunk = (obj.get("message", {}) or {}).get("content", "")
                    if chunk:
                        yield chunk
                    if obj.get("done"):
                        break
        except Exception as e:
            log.warning("Ollama chat_stream failed: %s", e)
            return

    def chat_json(self, system: str, user: str) -> Optional[dict]:
        """Return the model's reply parsed as a JSON object, or None on failure."""
        payload = {
            "model": self.model,
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.2},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        try:
            r = requests.post(
                f"{self.url}/api/chat", json=payload, timeout=self.timeout_s
            )
            r.raise_for_status()
            content = r.json().get("message", {}).get("content", "")
            return json.loads(content)
        except json.JSONDecodeError as e:
            log.warning("model returned non-JSON: %s", e)
            return None
        except Exception as e:
            log.warning("Ollama chat failed: %s", e)
            return None

    def chat_json_vision(
        self, system: str, user: str, images: list, model: Optional[str] = None
    ) -> Optional[dict]:
        """Like chat_json, but sends screenshot(s) to a vision model.

        `images` is a list of base64-encoded PNG/JPEG strings (no data: prefix).
        Ollama attaches them to the user message so a VLM can actually SEE the
        screen — icons, layout, buttons — not just OCR text.
        """
        payload = {
            "model": model or self.model,
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.1},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user, "images": images},
            ],
        }
        try:
            r = requests.post(f"{self.url}/api/chat", json=payload, timeout=self.timeout_s)
            r.raise_for_status()
            content = r.json().get("message", {}).get("content", "")
            return json.loads(content)
        except json.JSONDecodeError as e:
            log.warning("vision model returned non-JSON: %s", e)
            return None
        except Exception as e:
            log.warning("Ollama vision chat failed: %s", e)
            return None

    def chat_vision_text(
        self, system: str, user: str, images: list,
        model: Optional[str] = None, temperature: float = 0.2,
    ) -> Optional[str]:
        """Free-text answer about image(s) — for analysing a photo/PDF page."""
        payload = {
            "model": model or self.model,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": 700},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user, "images": images},
            ],
        }
        try:
            r = requests.post(f"{self.url}/api/chat", json=payload, timeout=self.timeout_s)
            r.raise_for_status()
            return (r.json().get("message", {}).get("content", "") or "").strip()
        except Exception as e:
            log.warning("Ollama vision text failed: %s", e)
            return None

    def embed(self, text: str, model: Optional[str] = None) -> Optional[list]:
        """Return an embedding vector for `text` (for semantic memory), or None."""
        text = (text or "").strip()
        if not text:
            return None
        try:
            r = requests.post(
                f"{self.url}/api/embed",
                json={"model": model or self.embed_model, "input": text},
                timeout=self.timeout_s,
            )
            r.raise_for_status()
            data = r.json()
            # /api/embed returns {"embeddings": [[...]]}; be tolerant of the older shape
            embs = data.get("embeddings")
            if embs:
                return embs[0]
            return data.get("embedding")
        except Exception as e:
            log.warning("Ollama embed failed: %s", e)
            return None
