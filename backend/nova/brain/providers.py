"""Cloud LLM providers — same interface as OllamaClient, so they drop straight
into the planner / chat / researcher.

The user picks ONE in Settings and pastes an API key: ChatGPT (OpenAI), Grok
(xAI), Claude (Anthropic) or Gemini (Google). Each client exposes the exact
methods the rest of Nova calls — available / warm / chat_text / chat_json /
chat_stream — so nothing else has to change.

Embeddings + vision deliberately stay LOCAL (Ollama), so semantic memory and
image/PDF analysis keep working (and that data never leaves the machine) even
when chat runs on a cloud API.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

import requests

log = logging.getLogger("nova.provider")


def _split_system(messages):
    """Return (system_text, non_system_messages) for APIs with a separate system."""
    system = " ".join(m["content"] for m in messages if m.get("role") == "system")
    rest = [
        {"role": ("assistant" if m["role"] == "assistant" else "user"),
         "content": m["content"]}
        for m in messages if m.get("role") != "system"
    ]
    return system.strip(), rest


def _strip_fences(txt: str) -> str:
    txt = txt.strip()
    txt = re.sub(r"^```(?:json)?\s*", "", txt)
    txt = re.sub(r"\s*```$", "", txt)
    return txt.strip()


class OpenAICompatClient:
    """OpenAI-compatible Chat Completions — covers OpenAI (ChatGPT) and xAI (Grok)."""

    def __init__(self, api_key, model, base_url="https://api.openai.com/v1",
                 timeout_s=90, label="openai"):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.label = label

    def available(self) -> bool:
        return bool(self.api_key)

    def warm(self) -> None:
        pass

    def _headers(self):
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def chat_text(self, messages, temperature: float = 0.6) -> Optional[str]:
        try:
            r = requests.post(
                f"{self.base_url}/chat/completions", headers=self._headers(),
                json={"model": self.model, "messages": messages, "temperature": temperature},
                timeout=self.timeout_s,
            )
            r.raise_for_status()
            return (r.json()["choices"][0]["message"]["content"] or "").strip()
        except Exception as e:
            log.warning("%s chat_text failed: %s", self.label, e)
            return None

    def chat_json(self, system, user) -> Optional[dict]:
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        try:
            r = requests.post(
                f"{self.base_url}/chat/completions", headers=self._headers(),
                json={"model": self.model, "messages": msgs, "temperature": 0.2,
                      "response_format": {"type": "json_object"}},
                timeout=self.timeout_s,
            )
            r.raise_for_status()
            return json.loads(r.json()["choices"][0]["message"]["content"])
        except Exception as e:
            log.warning("%s chat_json failed: %s", self.label, e)
            return None

    def chat_stream(self, messages, temperature: float = 0.6):
        try:
            with requests.post(
                f"{self.base_url}/chat/completions", headers=self._headers(),
                json={"model": self.model, "messages": messages,
                      "temperature": temperature, "stream": True},
                timeout=self.timeout_s, stream=True,
            ) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if not line:
                        continue
                    s = line.decode("utf-8", "ignore")
                    if s.startswith("data: "):
                        s = s[6:]
                    if s.strip() == "[DONE]":
                        break
                    try:
                        delta = json.loads(s)["choices"][0]["delta"].get("content")
                    except Exception:
                        continue
                    if delta:
                        yield delta
        except Exception as e:
            log.warning("%s chat_stream failed: %s", self.label, e)
            return


class AnthropicClient:
    """Claude via the Anthropic Messages API."""

    URL = "https://api.anthropic.com/v1/messages"

    def __init__(self, api_key, model, timeout_s=90):
        self.api_key = api_key
        self.model = model
        self.timeout_s = timeout_s

    def available(self) -> bool:
        return bool(self.api_key)

    def warm(self) -> None:
        pass

    def _headers(self):
        return {"x-api-key": self.api_key, "anthropic-version": "2023-06-01",
                "content-type": "application/json"}

    def chat_text(self, messages, temperature: float = 0.6) -> Optional[str]:
        system, msgs = _split_system(messages)
        try:
            r = requests.post(self.URL, headers=self._headers(), json={
                "model": self.model, "max_tokens": 1024, "system": system,
                "messages": msgs, "temperature": temperature}, timeout=self.timeout_s)
            r.raise_for_status()
            return "".join(b.get("text", "") for b in r.json().get("content", [])).strip()
        except Exception as e:
            log.warning("claude chat_text failed: %s", e)
            return None

    def chat_json(self, system, user) -> Optional[dict]:
        try:
            r = requests.post(self.URL, headers=self._headers(), json={
                "model": self.model, "max_tokens": 1024,
                "system": system + " Return ONLY a single valid JSON object, no prose.",
                "messages": [{"role": "user", "content": user}]}, timeout=self.timeout_s)
            r.raise_for_status()
            txt = "".join(b.get("text", "") for b in r.json().get("content", []))
            return json.loads(_strip_fences(txt))
        except Exception as e:
            log.warning("claude chat_json failed: %s", e)
            return None

    def chat_stream(self, messages, temperature: float = 0.6):
        system, msgs = _split_system(messages)
        try:
            with requests.post(self.URL, headers=self._headers(), json={
                "model": self.model, "max_tokens": 1024, "system": system,
                "messages": msgs, "temperature": temperature, "stream": True},
                timeout=self.timeout_s, stream=True) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if not line:
                        continue
                    s = line.decode("utf-8", "ignore")
                    if not s.startswith("data: "):
                        continue
                    try:
                        obj = json.loads(s[6:])
                    except Exception:
                        continue
                    if obj.get("type") == "content_block_delta":
                        t = obj.get("delta", {}).get("text")
                        if t:
                            yield t
        except Exception as e:
            log.warning("claude chat_stream failed: %s", e)
            return


class GeminiClient:
    """Google Gemini via the Generative Language API."""

    BASE = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, api_key, model, timeout_s=90):
        self.api_key = api_key
        self.model = model
        self.timeout_s = timeout_s

    def available(self) -> bool:
        return bool(self.api_key)

    def warm(self) -> None:
        pass

    def _convert(self, messages):
        system, contents = "", []
        for m in messages:
            if m.get("role") == "system":
                system += m["content"] + " "
                continue
            role = "model" if m["role"] == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": m["content"]}]})
        return system.strip(), contents

    def _url(self):
        return f"{self.BASE}/{self.model}:generateContent?key={self.api_key}"

    def chat_text(self, messages, temperature: float = 0.6) -> Optional[str]:
        system, contents = self._convert(messages)
        body = {"contents": contents, "generationConfig": {"temperature": temperature}}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        try:
            r = requests.post(self._url(), json=body, timeout=self.timeout_s)
            r.raise_for_status()
            cands = r.json().get("candidates", [])
            if not cands:
                return None
            return "".join(p.get("text", "") for p in cands[0]["content"]["parts"]).strip()
        except Exception as e:
            log.warning("gemini chat_text failed: %s", e)
            return None

    def chat_json(self, system, user) -> Optional[dict]:
        body = {
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "systemInstruction": {"parts": [{"text": system}]},
            "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
        }
        try:
            r = requests.post(self._url(), json=body, timeout=self.timeout_s)
            r.raise_for_status()
            cands = r.json().get("candidates", [])
            txt = "".join(p.get("text", "") for p in cands[0]["content"]["parts"]) if cands else ""
            return json.loads(_strip_fences(txt))
        except Exception as e:
            log.warning("gemini chat_json failed: %s", e)
            return None

    def chat_stream(self, messages, temperature: float = 0.6):
        # Simplest reliable path: one non-streamed answer yielded as a single chunk.
        txt = self.chat_text(messages, temperature)
        if txt:
            yield txt


# sensible default model per provider; the user can override in Settings.
DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "grok": "grok-2-latest",
    "claude": "claude-sonnet-5",
    "gemini": "gemini-2.0-flash",
}


def build_chat_client(provider: str, model: str, api_key: str, timeout_s: int = 90):
    """Construct the right cloud client, or None for an unknown provider."""
    p = (provider or "").strip().lower()
    model = model or DEFAULT_MODELS.get(p, "")
    if p in ("openai", "chatgpt", "gpt"):
        return OpenAICompatClient(api_key, model or DEFAULT_MODELS["openai"],
                                  "https://api.openai.com/v1", timeout_s, "openai")
    if p in ("grok", "xai"):
        return OpenAICompatClient(api_key, model or DEFAULT_MODELS["grok"],
                                  "https://api.x.ai/v1", timeout_s, "grok")
    if p in ("claude", "anthropic"):
        return AnthropicClient(api_key, model or DEFAULT_MODELS["claude"], timeout_s)
    if p in ("gemini", "google"):
        return GeminiClient(api_key, model or DEFAULT_MODELS["gemini"], timeout_s)
    return None
