"""Turn a natural phone command into a structured device action.

The mobile app executes these on-device via Android intents / URL schemes
(open an app, dial, message, navigate, search). The heavy lifting (understanding
the request) happens here with the LLM; a rules fallback keeps it working when
Ollama is down.

Action shape (JSON):
  {"kind": "open_app", "app": "whatsapp"}
  {"kind": "call", "number": "+9198..."}
  {"kind": "sms", "number": "...", "body": "..."}
  {"kind": "whatsapp", "number": "...", "message": "..."}
  {"kind": "maps", "query": "..."}
  {"kind": "web", "query": "..."}          # or {"url": "https://..."}
  {"kind": "youtube", "query": "..."}
  {"kind": "email", "to": "...", "subject": "...", "body": "..."}
None  -> no executable action (Sarthi is just asking a question / chatting)
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

# Apps the phone knows how to open (kept in sync with lib/device.js on mobile).
KNOWN_APPS = [
    "whatsapp", "youtube", "instagram", "maps", "chrome", "google", "camera",
    "settings", "phone", "gmail", "spotify", "photos", "files", "playstore",
    "facebook", "telegram", "twitter", "linkedin", "phonepe", "paytm", "gpay",
]

OUTWARD = {"call", "sms", "whatsapp", "email"}  # need approval before firing

_SYSTEM = (
    "You are Sarthi's phone-control planner. Convert the user's request into ONE "
    "device action as strict JSON. Respond with a JSON object: "
    '{"reply": <short spoken confirmation>, "action": <action object or null>}.\n'
    "Action kinds and fields:\n"
    '- open_app: {"kind":"open_app","app":"<one of: ' + "|".join(KNOWN_APPS) + '>"}\n'
    '- call: {"kind":"call","number":"<digits>"}\n'
    '- sms: {"kind":"sms","number":"<digits>","body":"<text>"}\n'
    '- whatsapp: {"kind":"whatsapp","number":"<digits or empty>","message":"<text>"}\n'
    '- maps: {"kind":"maps","query":"<place or address>"}\n'
    '- web: {"kind":"web","query":"<search text>"}\n'
    '- youtube: {"kind":"youtube","query":"<search text>"}\n'
    '- email: {"kind":"email","to":"<addr>","subject":"<s>","body":"<b>"}\n'
    "Rules: If a required detail is missing (e.g. a phone number you don't know, "
    "a contact name with no number), set action to null and ASK for it in reply. "
    "NEVER invent phone numbers, emails, or bracketed placeholders like [name]. "
    "Keep reply to one short sentence. Output JSON only."
)


_OPERATE_SYS = (
    "You are Sarthi operating an Android app for the user, one step at a time. "
    "You are given the GOAL and the list of on-screen elements (each has an index, "
    "text, and whether it's clickable/editable). Decide the SINGLE next action as "
    "JSON: {\"say\":\"<very short status>\",\"action\":\"tap|type|scroll|back|done|ask|confirm\","
    "\"text\":\"<tap target text OR text to type>\",\"label\":\"<for confirm/ask: what you're about to do>\"}.\n"
    "Rules: tap → text is the visible label to tap. type → first tap the input field in a "
    "previous step, then type. When the message/details are ready and only an irreversible "
    "SEND / PAY / CONFIRM tap remains, return action \"confirm\" with label describing it and "
    "text = the exact button label to tap (do NOT tap it yourself). Use \"done\" when the goal "
    "is achieved. Use \"ask\" if you're stuck or need info. Never invent contacts/amounts. JSON only."
)


def plan_operate_step(llm, goal: str, screen: list, history: list) -> dict:
    """Decide ONE in-app action from the current screen. Returns the action dict."""
    elems = "\n".join(
        f'[{i}] "{e.get("text","")}"'
        + (" (input)" if e.get("editable") else "")
        + (" (button)" if e.get("clickable") else "")
        for i, e in enumerate((screen or [])[:60])
    ) or "(screen is empty)"
    hist = "\n".join(f"- {h}" for h in (history or [])[-6:]) or "(none yet)"
    user = f"GOAL: {goal}\n\nDONE SO FAR:\n{hist}\n\nSCREEN:\n{elems}\n\nNext action as JSON:"
    try:
        if llm is not None and llm.available():
            out = llm.chat_json(_OPERATE_SYS, user)
            if isinstance(out, dict) and out.get("action"):
                return out
    except Exception:
        pass
    return {"action": "ask", "say": "I couldn't work out the next step.", "label": ""}


def plan_device_action(llm, text: str) -> Tuple[str, Optional[dict]]:
    text = (text or "").strip()
    if not text:
        return ("What would you like me to do on your phone?", None)

    # Try the model first.
    try:
        if llm is not None and llm.available():
            out = llm.chat_json(_SYSTEM, text)
            if isinstance(out, dict):
                reply = (out.get("reply") or "").strip() or "On it."
                action = out.get("action")
                action = _clean(action)
                return (reply, action)
    except Exception:
        pass

    # Rules fallback — covers the common asks without a model.
    return _rules(text)


def _clean(action):
    if not isinstance(action, dict):
        return None
    kind = (action.get("kind") or "").strip().lower()
    if kind not in {
        "open_app", "call", "sms", "whatsapp", "maps", "web", "youtube", "email"
    }:
        return None
    if kind == "open_app":
        app = (action.get("app") or "").strip().lower()
        if app not in KNOWN_APPS:
            return None
        return {"kind": "open_app", "app": app}
    # keep only string fields, drop empties we don't need
    out = {"kind": kind}
    for k, v in action.items():
        if k != "kind" and isinstance(v, (str, int)):
            out[k] = str(v)
    return out


def _rules(text: str) -> Tuple[str, Optional[dict]]:
    t = text.lower()

    # open an app
    m = re.search(r"\b(?:open|launch|khol|start)\s+([a-z ]+)", t)
    if m:
        name = m.group(1).strip().split()[0]
        alias = {"insta": "instagram", "wa": "whatsapp", "yt": "youtube", "map": "maps", "browser": "chrome"}
        name = alias.get(name, name)
        if name in KNOWN_APPS:
            return (f"Opening {name}.", {"kind": "open_app", "app": name})

    # navigation / maps
    m = re.search(r"\b(?:navigate to|directions to|maps? (?:to|for)|take me to)\s+(.+)", t)
    if m:
        q = m.group(1).strip()
        return (f"Opening maps for {q}.", {"kind": "maps", "query": q})

    # youtube / play
    m = re.search(r"\b(?:play|youtube|watch)\s+(.+)", t)
    if m:
        q = m.group(1).strip()
        return (f"Searching YouTube for {q}.", {"kind": "youtube", "query": q})

    # call
    m = re.search(r"\bcall\s+(.+)", t)
    if m:
        who = m.group(1).strip()
        num = re.sub(r"[^\d+]", "", who)
        if len(num) >= 7:
            return (f"Calling {num}.", {"kind": "call", "number": num})
        return (f"What's {who}'s number? I don't have it saved.", None)

    # whatsapp message
    m = re.search(r"\bwhatsapp\s+(.+)", t)
    if m:
        return ("Who should I message on WhatsApp, and what should it say?", None)

    # web search
    m = re.search(r"\b(?:search|google|find|look up)\s+(?:for\s+)?(.+)", t)
    if m:
        q = m.group(1).strip()
        return (f"Searching the web for {q}.", {"kind": "web", "query": q})

    return ("I can open apps, call, message on WhatsApp, navigate, or search — try 'open YouTube' or 'navigate to Connaught Place'.", None)
