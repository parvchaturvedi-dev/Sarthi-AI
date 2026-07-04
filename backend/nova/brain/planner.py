"""The planner — turns a spoken utterance into a structured Plan.

Primary path: ask the local LLM for a JSON Plan.
Fallback path: a small rule-based planner so common commands ("open chrome",
"go to youtube.com", "type ...") still work with Ollama offline.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from ..agent.tools import KNOWN_APPS, TOOL_SPECS
from ..schema import Plan, Step, Verify
from .llm import OllamaClient

log = logging.getLogger("nova.planner")


def _tool_catalog() -> str:
    return "\n".join(f"- {t['tool']}{t['args']}: {t['desc']}" for t in TOOL_SPECS)


SYSTEM_PROMPT = f"""You are Sarthi, a voice-controlled assistant for a Windows PC.
You do NOT execute anything yourself. You output a JSON plan that a separate,
trusted executor will run and verify.

Available tools:
{_tool_catalog()}

Return ONLY a JSON object with this shape:
{{
  "say":  "<one short sentence spoken immediately, e.g. 'Opening Chrome.'>",
  "steps": [
    {{"tool": "<tool name>", "args": {{...}},
      "verify": {{"type": "window_title_contains", "value": "<expected window text>"}},
      "sensitive": false}}
  ],
  "final": "<one short spoken confirmation after the steps succeed>"
}}

Rules:
- Use only the tools listed. Keep steps minimal.
- Verify types you may use: window_title_contains, window_gone, file_exists, always.
- For open_app, add a verify whose value is a word expected in the app's window title.
- For close_app, verify with window_gone. For screenshot, verify with file_exists.
- To search the web, prefer open_url with a full Google URL
  (https://www.google.com/search?q=...), NOT typing into a browser window.
- If you must type into a field, follow type_text with a press_keys "enter" step.
- Mark a step "sensitive": true if it sends a message, makes a payment, or deletes data.
- Keep spoken text short and natural. No markdown, no explanations outside the JSON.

Example — user: "search for weather in delhi"
{{"say": "Searching for weather in Delhi.",
 "steps": [{{"tool": "open_url",
            "args": {{"url": "https://www.google.com/search?q=weather+in+delhi"}},
            "verify": {{"type": "always", "value": ""}}, "sensitive": false}}],
 "final": "Here's the weather in Delhi."}}
"""


# Force the spoken language regardless of what the small model guesses.
LANG_DIRECTIVE = {
    "hinglish": (
        "\nIMPORTANT LANGUAGE RULE: Write every \"say\" and \"final\" value in casual "
        "HINGLISH — Hindi in Roman/English letters, mixing English words naturally, "
        "as a female (e.g. 'Notepad khol rahi hoon', 'ho gaya yaar'). NEVER use "
        "Devanagari script. Only tool args (app names, URLs, commands) stay in English."
    ),
    "hindi": (
        "\nIMPORTANT LANGUAGE RULE: Write every \"say\" and \"final\" value in natural "
        "spoken Hindi using Devanagari script (देवनागरी). Never use Turkish, English "
        "sentences, or Roman/Latin transliteration for these fields. Only tool args "
        "(app names, URLs, commands) stay in English."
    ),
    "english": "\nWrite every \"say\" and \"final\" value in simple English.",
    "auto": (
        "\nWrite \"say\"/\"final\" in the SAME language the user used; for Hindi/Hinglish "
        "use natural Hindi in Devanagari script."
    ),
}


class Planner:
    def __init__(
        self,
        llm: Optional[OllamaClient],
        fallback_to_rules: bool = True,
        language: str = "hinglish",
    ):
        self.llm = llm
        self.fallback_to_rules = fallback_to_rules
        self.language = language

    def plan(self, utterance: str, context: str = "") -> Plan:
        utterance = (utterance or "").strip()
        if not utterance:
            return Plan(say=self._miss(), steps=[], final="")

        if self.llm is not None:
            system = SYSTEM_PROMPT + LANG_DIRECTIVE.get(self.language, "")
            user = f"Recent context: {context}\n\nUser: {utterance}" if context else utterance
            data = self.llm.chat_json(system, user)
            if data:
                try:
                    plan = Plan.from_dict(data)
                    if plan.steps or plan.say:
                        return plan
                except Exception as e:  # noqa: BLE001
                    log.warning("could not parse LLM plan: %s", e)

        if self.fallback_to_rules:
            log.info("using rule-based planner")
            return rule_based_plan(utterance, self.language)

        return Plan(say=_p(self.language, "sorry"), steps=[], final="")

    def _miss(self) -> str:
        return _p(self.language, "miss")


# --- offline rule-based fallback -------------------------------------------

# English verbs plus common Hinglish forms (target usually precedes the verb).
_OPEN = re.compile(r"^(?:open|launch|start|run)\s+(.+)$", re.I)
_OPEN_HI = re.compile(
    r"^(.+?)\s+(?:kholo|khol do|khol dena|khol|chalu karo|chaalu karo|"
    r"open karo|open kar do|open kro|open kar|chala do|chalao)$", re.I)
_CLOSE = re.compile(r"^(?:close|quit|exit)\s+(.+)$", re.I)
_CLOSE_HI = re.compile(r"^(.+?)\s+(?:band karo|band kar do|bandh karo|close karo)$", re.I)
_SHOT = re.compile(r"\b(screenshot|screen shot|capture (?:the )?screen|screenshot lo|screenshot le)\b", re.I)
_URL = re.compile(r"^(?:open|go to|goto|visit|browse to)\s+(.+)$", re.I)
_SEARCH = re.compile(r"^(?:search|google|look up)\s+(?:for\s+)?(.+)$", re.I)
_SEARCH_HI = re.compile(r"^(.+?)\s+(?:search karo|dhundo|dhoondo|google karo)$", re.I)
_TYPE = re.compile(r"^(?:type|type karo)\s+(.+)$", re.I)
_GREET = re.compile(r"\b(hi|hello|hey|namaste|namaskar|good morning|good evening)\b", re.I)


# Spoken phrases per language. Hinglish (Roman) is the default — the small model
# truncates Devanagari, and the user prefers casual Hinglish anyway.
PHRASES = {
    "hinglish": {
        "typing": "theek hai, type kar rahi hoon.", "done": "ho gaya.",
        "shot": "screenshot le rahi hoon.", "shot_done": "screenshot save ho gaya.",
        "closing": "{t} band kar rahi hoon.", "closed": "{t} band ho gaya.",
        "opening_site": "site khol rahi hoon.", "there": "ye lo.",
        "searching": "{q} search kar rahi hoon.", "results": "ye rahe results.",
        "opening": "{t} khol rahi hoon.", "opened": "{t} khul gaya.",
        "greet": "haan bolo, kya help karun?",
        "help": "main app ya website khol sakti hoon, type ya search kar sakti hoon. kya karna hai?",
        "sorry": "sorry yaar, abhi ye nahi ho paya.",
        "miss": "sorry, samajh nahi aaya.",
        "yes": "haan bolo.",
        "ok": "theek hai.",
        "bye": "theek hai, zaroorat ho toh bula lena.",
    },
    "hindi": {
        "typing": "ठीक है, टाइप कर रही हूँ।", "done": "हो गया।",
        "shot": "स्क्रीनशॉट ले रही हूँ।", "shot_done": "स्क्रीनशॉट सेव हो गया।",
        "closing": "{t} बंद कर रही हूँ।", "closed": "{t} बंद हो गया।",
        "opening_site": "साइट खोल रही हूँ।", "there": "यह लीजिए।",
        "searching": "{q} सर्च कर रही हूँ।", "results": "यह रहे नतीजे।",
        "opening": "{t} खोल रही हूँ।", "opened": "{t} खुल गया।",
        "greet": "नमस्ते! मैं आपकी क्या मदद करूँ?",
        "help": "मैं ऐप या वेबसाइट खोल सकती हूँ, टाइप या सर्च कर सकती हूँ। क्या करना है?",
        "sorry": "माफ़ कीजिए, अभी मैं यह नहीं कर पाई।",
        "miss": "माफ़ कीजिए, मैं समझ नहीं पाई।",
        "yes": "हाँ, बोलिए।",
        "ok": "ठीक है।",
        "bye": "ठीक है, ज़रूरत हो तो बुला लीजिएगा।",
    },
    "english": {
        "typing": "Typing that.", "done": "Done.",
        "shot": "Taking a screenshot.", "shot_done": "Screenshot saved.",
        "closing": "Closing {t}.", "closed": "{t} closed.",
        "opening_site": "Opening the site.", "there": "There you go.",
        "searching": "Searching for {q}.", "results": "Here are the results.",
        "opening": "Opening {t}.", "opened": "{t} is open.",
        "greet": "Hey! What can I do for you?",
        "help": "I can open apps and websites, type, or search. What would you like?",
        "sorry": "Sorry, I couldn't do that right now.",
        "miss": "Sorry, I didn't catch that.",
        "yes": "Yes?",
        "ok": "Okay.",
        "bye": "Okay, call me when you need me.",
    },
}


def _p(language: str, key: str, **kw) -> str:
    table = PHRASES.get(language, PHRASES["english"])
    return table[key].format(**kw)


def _looks_like_url(text: str) -> bool:
    return bool(re.search(r"\.(com|org|net|io|dev|in|co|ai|gov|edu)\b", text, re.I))


def _verify_word(target: str) -> str:
    key = target.lower()
    for name in KNOWN_APPS:
        if name in key:
            return name
    return key


def rule_based_plan(utterance: str, language: str = "hinglish") -> Plan:
    u = utterance.strip().rstrip(".!?")
    low = u.lower()

    m = _TYPE.match(u)
    if m:
        return Plan(_p(language, "typing"),
                    [Step("type_text", {"text": m.group(1)})], _p(language, "done"))

    if _SHOT.search(low):
        return Plan(_p(language, "shot"),
                    [Step("screenshot", {}, verify=Verify("file_exists", "screenshots/shot.png"))],
                    _p(language, "shot_done"))

    m = _CLOSE.match(u) or _CLOSE_HI.match(u)
    if m:
        target = m.group(1).strip()
        return Plan(_p(language, "closing", t=target),
                    [Step("close_app", {"name": target}, verify=Verify("window_gone", _verify_word(target)))],
                    _p(language, "closed", t=target))

    m = _URL.match(u)
    if m and _looks_like_url(m.group(1)):
        return Plan(_p(language, "opening_site"),
                    [Step("open_url", {"url": m.group(1).strip()})], _p(language, "there"))

    m = _SEARCH.match(u) or _SEARCH_HI.match(u)
    if m:
        q = m.group(1).strip()
        url = "https://www.google.com/search?q=" + re.sub(r"\s+", "+", q)
        return Plan(_p(language, "searching", q=q),
                    [Step("open_url", {"url": url})], _p(language, "results"))

    m = _OPEN.match(u) or _OPEN_HI.match(u)
    if m:
        target = m.group(1).strip()
        if _looks_like_url(target):
            return Plan(_p(language, "opening_site"),
                        [Step("open_url", {"url": target})], _p(language, "there"))
        return Plan(_p(language, "opening", t=target),
                    [Step("open_app", {"name": target},
                          verify=Verify("window_title_contains", _verify_word(target)))],
                    _p(language, "opened", t=target))

    if _GREET.search(low):
        return Plan(say=_p(language, "greet"), steps=[], final="")

    return Plan(say=_p(language, "help"), steps=[], final="")
