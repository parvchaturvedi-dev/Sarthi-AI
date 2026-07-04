"""Conversational Q&A — Sarthi answers questions and chit-chats, not just acts.

Separate from the planner (which only emits JSON action plans). This uses the
LLM in plain chat mode with a short rolling history, so Sarthi feels like a person
you talk to, not a command runner. Offline -> a simple canned reply.
"""

from __future__ import annotations

import logging
import re
from typing import Callable, List, Optional, Tuple

from .llm import OllamaClient

log = logging.getLogger("nova.chat")

# sentence boundary — so we can speak each sentence the moment it's complete
_SENT_END = re.compile(r"[.!?।\n]")

CHAT_SYSTEM = {
    "hinglish": (
        "You are Sarthi, a friendly, smart female assistant for an Indian user. "
        "Reply in casual HINGLISH — Hindi in Roman/English letters, mixing English "
        "words naturally, like Indian friends chat (e.g. 'haan yaar, ...'). Speak as "
        "a female ('kar rahi hoon', 'bata rahi hoon'). Give a PROPER, genuinely "
        "helpful answer with the useful details — don't be one-liner-lazy; if the "
        "question needs 3-4 sentences or a few points, give them. Stay natural and "
        "conversational, not robotic. NEVER use Devanagari script. Only use short "
        "simple formatting (a dash list) if it truly helps clarity."
    ),
    "hindi": (
        "तुम सारथी हो — एक मददगार, दोस्ताना वॉइस असिस्टेंट। छोटे, स्वाभाविक जवाब दो, "
        "हिंदी में देवनागरी लिपि में। जवाब बोलकर सुनाया जाएगा, इसलिए साफ़ रखो।"
    ),
    "english": (
        "You are Sarthi, a friendly, smart assistant. Give a proper, genuinely "
        "helpful answer with the useful details — don't be one-liner-lazy; if the "
        "question needs a few sentences or points, give them. Stay natural and "
        "conversational, not robotic. Keep it clean (this may be read aloud), and "
        "only use light formatting (a short dash list) when it truly helps."
    ),
}


class Chat:
    def __init__(self, llm: Optional[OllamaClient], language: str = "hinglish"):
        self.llm = llm
        self.language = language

    def answer(
        self,
        text: str,
        history: Optional[List[Tuple[str, str]]] = None,
        facts: Optional[List[str]] = None,
    ) -> str:
        text = (text or "").strip()
        if not text:
            return self._offline()
        if self.llm is None:
            return self._offline()

        system = CHAT_SYSTEM.get(self.language, CHAT_SYSTEM["english"])
        if facts:
            system += "\n\nThings you remember about the user:\n- " + "\n- ".join(facts[:20])
        messages = [{"role": "system", "content": system}]
        for role, content in (history or [])[-8:]:      # last few turns for context
            messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": text})

        reply = self.llm.chat_text(messages)
        return reply or self._offline()

    def answer_stream(
        self,
        text: str,
        history: Optional[List[Tuple[str, str]]],
        facts: Optional[List[str]],
        speak: Callable[[str], None],
    ) -> str:
        """Same as answer(), but speaks each sentence as it generates (low latency).

        Returns the full text (for memory). Falls back to a blocking answer if
        streaming yields nothing.
        """
        text = (text or "").strip()
        if not text or self.llm is None:
            out = self._offline()
            speak(out)
            return out

        system = CHAT_SYSTEM.get(self.language, CHAT_SYSTEM["english"])
        if facts:
            system += "\n\nThings you remember about the user:\n- " + "\n- ".join(facts[:20])
        messages = [{"role": "system", "content": system}]
        for role, content in (history or [])[-8:]:
            messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": text})

        buf, full = "", ""
        for chunk in self.llm.chat_stream(messages):
            buf += chunk
            full += chunk
            m = _SENT_END.search(buf)
            while m:                                   # flush every complete sentence
                cut = m.end()
                sentence = buf[:cut].strip()
                buf = buf[cut:]
                if len(sentence) >= 2:
                    speak(sentence)
                m = _SENT_END.search(buf)
        tail = buf.strip()
        if tail:
            speak(tail)

        full = full.strip()
        if not full:                                   # streaming gave nothing -> fallback
            full = self.answer(text, history, facts)
            speak(full)
        return full

    def _offline(self) -> str:
        if self.language == "hinglish":
            return "Sorry yaar, abhi jawab nahi de pa rahi — model ya internet band lag raha hai."
        if self.language == "hindi":
            return "माफ़ कीजिए, अभी मैं जवाब नहीं दे पा रही।"
        return "Sorry, I can't answer that right now."
