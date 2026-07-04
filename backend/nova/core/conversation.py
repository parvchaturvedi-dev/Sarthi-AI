"""Conversation engine — makes Nova feel like a person, not a command runner.

Attention state machine:

    SLEEPING  only the wake word ("Nova") gets her attention.
    ACTIVE    she's in a conversation: every turn is answered, no wake word
              needed between turns. Handles actions AND chit-chat.
    PAUSED    you told her to wait ("ruk ja, main papa se baat kar raha hoon").
              She stays SILENT even if she hears you — until you call her name
              again ("Nova, sun") which flips her back to ACTIVE.

Routing inside ACTIVE:
    control  -> pause / sleep
    action   -> rules-first (instant); LLM planner only if rules can't parse it
    question -> conversational answer (Q&A / chit-chat)

Rules-first is also the speed win: common commands never wait on the LLM.
"""

from __future__ import annotations

import logging
import re
from enum import Enum
from typing import List, Tuple

from ..brain.chat import Chat
from ..brain.planner import Planner, _p, rule_based_plan
from ..pipeline import Pipeline
from ..schema import Plan, Step
from ..voice.tts import Speaker
from ..voice.wake import matched as name_called

log = logging.getLogger("nova.conversation")


class State(Enum):
    SLEEPING = "sleeping"
    ACTIVE = "active"
    PAUSED = "paused"


# "wait / I'm talking to someone else" — go silent until called by name.
_PAUSE = re.compile(
    r"\b(ruk(o|ja|jao|iye|na)?|rukna|thehro|thahro|stop|wait|hold on|"
    r"ek (?:minute|min|sec|second|pal)|chup|shh+|baat kar raha|baat kar rahi|"
    r"kisi aur se|abhi mat|abhi nahi)\b",
    re.I,
)
# "go to sleep / bye" — back to wake-word-only.
_SLEEP = re.compile(
    r"\b(so ?ja(?:o|iye)?|soja|bye|good ?bye|band ho ja|so jao|"
    r"ja(?:o)? aram kar|sleep|bas kar(?:o)?|khatam)\b",
    re.I,
)
# Words that mean "she's being asked to DO something" (English + Hinglish).
_ACTION_HINT = re.compile(
    r"\b(open|close|launch|start|run|type|search|google|screenshot|play|"
    r"khol|kholo|band|bandh|chalu|chala|chalao|likho|likh|dhundo|dhoondo|"
    r"bajao|bajaa|volume|mute|awaaz|lock|shutdown|restart|"
    r"copy|paste|click|khol do)\b",
    re.I,
)
# Multi-step "operate an app" goals -> the vision-action loop (see-understand-act).
# No trailing \b so verb-stems match: bhej -> bhejde/bhejna/bhejdena/bhejo.
_OPERATE = re.compile(
    r"\b(bhej|send|reply|forward|mail|email|gmail|whatsapp|instagram|insta|"
    r"telegram|compose|message|msg|likhkar bhej|likh ke bhej)", re.I)
# "try again" -> re-run the last task, don't chat about it.
_RETRY = re.compile(
    r"\b(dubara|dobara|dubaara|phir se|firse|try again|retry|ek baar aur|"
    r"phir try|dubara try|try kar)\b", re.I)
# tasks that can go through Google connectors when Automation is on.
_EMAIL = re.compile(r"\b(mail|email|gmail)\b", re.I)
_CAL = re.compile(r"\b(calendar|meeting|appointment|event|schedule)\b", re.I)
_DRIVE = re.compile(r"\b(drive|google drive)\b", re.I)
# "remember this" -> save a long-term fact.
_REMEMBER = re.compile(r"\b(yaad rakh(?:na|o|lo|na)?|yaad rakhna|remember|note kar(?:na|lo)?)\b[:,]?\s*(.+)$", re.I)
# web-search intent -> look it up live (LangSearch) and answer, grounded.
_WEB = re.compile(
    r"\b(search|google it|dhoond|dhundh|khoj|look ?up|pata (?:kar|karo|lagao)|"
    r"net pe|internet pe|web pe|online dekh|"
    r"news|khabar|headlines?|weather|mausam|"
    r"latest|kaun jeeta|kya (?:bhaav|rate|price)|share price|stock|score|kitne ka)\b",
    re.I)
# explicit "go search the web" verbs — fire even before checking for an API key.
_WEB_EXPLICIT = re.compile(
    r"\b(search|google it|net pe|internet pe|web pe|dhoond|khoj|look ?up|"
    r"pata (?:kar|karo|lagao))\b", re.I)
# "open/launch" verbs — a search word next to these means an app, not a web query.
_OPEN = re.compile(r"\b(khol|kholo|khol do|launch|open|start karo|chala do|chalu)\b", re.I)
# a browser is named -> the user wants to SEE the search in a browser, not just hear it.
_BROWSER = re.compile(r"\b(chrome|browser|firefox|edge|opera|brave)\b", re.I)
# a search/find verb (used with _BROWSER to catch "chrome me X search karo").
_SEARCH = re.compile(
    r"\b(search|dhoond(?:o|na)?|dhundh(?:o)?|khoj(?:o|na)?|find|look ?up|"
    r"dekh(?:o|na|lo)?|news|khabar|google (?:kar|karo|kr))\b", re.I)
# user is signalling they want to pick / change the Chrome account this time.
_ASK_PROFILE = re.compile(
    r"\b(kaun|kaunsa|konsa|which|puch(?:o|kar|ke)?|account|profile|"
    r"alag|dusr[ae]|dusra|change|switch|badal)\b", re.I)
# --- image / PDF analysis (all offline, local models) ---
_IMG_WORD = re.compile(r"\b(image|photo|photos|tasveer|tasvir|pic|picture|screenshot)\b", re.I)
_IMG_EXT = re.compile(r"\.(jpe?g|png|webp|bmp|gif)\b", re.I)
_PDF_ANY = re.compile(r"\bpdf\b|\.pdf\b", re.I)
_ANALYZE_VERB = re.compile(
    r"\b(kya|kaun|kitn|kab|kahan|dekh|dekho|analyz|analys|samjh|samajh|"
    r"bata|batao|describe|padh|read|likha|summar|explain|what|who|how)\w*", re.I)
_DOC_REF = re.compile(
    r"\b(is pdf|is document|is file|isme|ismein|is me|usme|us me|"
    r"document me|pdf me|file me|isme)\b", re.I)
_SCREENSHOT = re.compile(r"\bscreenshot\b|\bscreen (?:pe|par|me|mein)\b", re.I)
# command words stripped when isolating the real question from a file command.
_DOC_CMD = re.compile(
    r"\b(pdf|photo|image|tasveer|tasvir|pic|picture|screenshot|padho|padh|read|"
    r"analyz\w*|analys\w*|kholo|khol|open|load|dekho|dekh|summary|summari\w*|"
    r"isme|ismein|isme|is me|document|file|me|mein|ka|ki|ko|se|karo|kar|do)\b", re.I)


class ConversationEngine:
    def __init__(
        self,
        pipeline: Pipeline,
        chat: Chat,
        speaker: Speaker,
        *,
        wake_word: str = "hey nova",
        language: str = "hinglish",
        max_history: int = 12,
        vision_llm=None,
        researcher=None,
        stream_replies: bool = False,
    ):
        self.pipeline = pipeline
        self.planner: Planner = pipeline.planner
        self.chat = chat
        self.speaker = speaker
        self.wake_word = wake_word
        self.language = language
        self.max_history = max_history
        self.vision_llm = vision_llm     # VLM for the operate-any-app loop (or None)
        self.researcher = researcher     # live web-search answers (LangSearch) or None
        self.stream_replies = stream_replies  # speak each sentence as it generates
        self.last_sources = []           # sources from the last web answer (for the UI)
        self.state = State.SLEEPING
        self._vagent = None
        self.last_goal = None  # last "operate an app" task, for "dubara try kar"
        self.pending_action = None  # a draft awaiting Approve/Reject/Edit
        self.pending_browser = None  # {"url":..,"profiles":[..]} awaiting a profile pick
        self.current_doc = None    # last PDF loaded, for follow-up "isme ..." questions
        self._img = None           # lazy ImageAnalyzer
        self.user_name = None       # signed-in user's name, for email signatures
        try:
            from ..settings import Settings
            self.settings = Settings()   # server may replace with the shared instance
        except Exception:
            self.settings = None
        self.ui_hide = None    # optional callables to hide/show Nova's own window
        self.ui_show = None    # so the vision loop doesn't OCR itself

        # persistent memory: resume the most recent session (like a chat thread)
        self.memory = getattr(pipeline, "memory", None)
        self.session_id = None
        self.history: List[Tuple[str, str]] = []
        if self.memory:
            try:
                self.session_id = self.memory.current_session()
                self.history = self.memory.session_turns(self.session_id)[-max_history:]
            except Exception:
                pass

    # --- sessions (new chat / switch) ---------------------------------------
    def new_session(self) -> int:
        if self.memory:
            self.session_id = self.memory.create_session()
        self.history = []
        return self.session_id

    def switch_session(self, session_id: int) -> None:
        if not self.memory:
            return
        self.session_id = session_id
        self.history = self.memory.session_turns(session_id)[-self.max_history:]

    # --- the one entry point ------------------------------------------------
    def feed(self, text: str) -> None:
        """Process one recognized utterance according to the current state."""
        text = (text or "").strip()
        if not text:
            return
        low = text.lower()
        called = name_called(text, self.wake_word)

        if self.state is State.SLEEPING:
            if called:
                self._activate()
                self._route_rest(text)
            return  # not addressed -> ignore

        if self.state is State.PAUSED:
            if called:
                self._resume()
                self._route_rest(text)
            return  # user is talking to someone else -> stay silent

        # ACTIVE
        if _SLEEP.search(low):
            self._sleep()
            return
        if _PAUSE.search(low):
            self._pause()
            return
        self._route(text)

    def address(self, text: str) -> None:
        """Explicit addressing (typed box / one-shot): no wake word needed."""
        if self.state is not State.ACTIVE:
            self.state = State.ACTIVE
        self.feed(text)

    # --- state transitions --------------------------------------------------
    def _activate(self) -> None:
        self.state = State.ACTIVE
        self.speaker.say(_p(self.language, "yes"))

    def _resume(self) -> None:
        self.state = State.ACTIVE
        self.speaker.say(_p(self.language, "yes"))

    def _pause(self) -> None:
        self.speaker.say(_p(self.language, "ok"))     # brief ack, then silence
        self.state = State.PAUSED

    def _sleep(self) -> None:
        self.speaker.say(_p(self.language, "bye"))
        self.state = State.SLEEPING

    # --- routing ------------------------------------------------------------
    def _route_rest(self, text: str) -> None:
        """After the name, run any trailing command (e.g. 'Nova, notepad kholo')."""
        rest = self._strip_name(text)
        if rest:
            self._route(rest)

    def _vision_agent(self):
        if self._vagent is None:
            from .agent_loop import VisionAgent
            self._vagent = VisionAgent(
                self.planner.llm, self.speaker.say, vision_llm=self.vision_llm
            )
        return self._vagent

    def _try_email_automation(self, goal: str) -> bool:
        """If Automation+Gmail are on and this is an email, send it directly (no UI)."""
        st = getattr(self, "settings", None)
        if not st or st.mode != "automation" or not _EMAIL.search(goal):
            return False
        g = st.gmail()
        if not g.get("connected"):
            return False
        fields = self._extract_email(goal)
        if not fields or not fields.get("to"):
            return False
        to = fields["to"]
        if "@" not in to:                        # a name -> look it up in Contacts
            try:
                from ..connectors.google import contacts_email
                found = contacts_email(g["email"], to)
                if found:
                    to = found
            except Exception:
                pass
        if "@" not in to:
            self.speaker.say(f"I couldn't find an email for '{fields['to']}'. "
                             "What's the full email address I should send it to?")
            return True
        # DON'T send yet — draft it and wait for the user's approval.
        self.pending_action = {
            "kind": "email", "account": g["email"], "to": to,
            "subject": fields.get("subject", ""), "body": fields.get("body", ""),
        }
        self.speaker.say(f"Here's a draft email to {to}. Review it, then Approve to send "
                         "(or Edit it first, or Reject).")
        return True

    def _connected_google(self):
        st = getattr(self, "settings", None)
        if not st or st.mode != "automation":
            return None
        g = st.google()
        return g if g.get("connected") else None

    def _try_calendar_automation(self, goal: str) -> bool:
        if not _CAL.search(goal):
            return False
        g = self._connected_google()
        if not g:
            return False
        from ..connectors.google import calendar_add, calendar_upcoming
        low = goal.lower()
        make = any(w in low for w in ("laga", "add", "set", "banao", "book", "daal", "create", "schedule a"))
        if make:
            ev = self._extract_event(goal)
            if ev and ev.get("title") and ev.get("start"):
                self.pending_action = {
                    "kind": "calendar", "account": g["email"], "title": ev["title"],
                    "start": ev["start"], "end": ev.get("end"),
                }
                self.speaker.say(f"Here's the event '{ev['title']}'. Approve to add it to your "
                                 "calendar (or Edit / Reject).")
            else:
                self.speaker.say("I couldn't work out the time. Try e.g. 'add a meeting tomorrow at 3pm'.")
            return True
        try:                                     # otherwise, read the schedule
            evs = calendar_upcoming(g["email"])
            if not evs:
                self.speaker.say("koi upcoming event nahi hai.")
            else:
                self.speaker.say("upcoming events: " + "; ".join(f"{t} — {s}" for t, s in evs[:5]))
        except Exception as e:  # noqa: BLE001
            self.speaker.say(f"calendar padhne me dikkat: {e}")
        return True

    def _extract_event(self, goal: str) -> dict:
        llm = getattr(self.planner, "llm", None)
        if llm is None:
            return {}
        import time as _t
        from datetime import datetime
        now = datetime.now().astimezone().isoformat()
        sysmsg = (
            f"Current datetime is {now}. Extract a calendar event from the request. "
            'Return ONLY JSON: {"title":"...","start":"<ISO 8601 with timezone offset>",'
            '"end":"<ISO 8601 or null>"}. Compute relative times (kal/tomorrow, 3 baje/3pm) '
            "from the current datetime. Default duration 1 hour if no end time given."
        )
        return llm.chat_json(sysmsg, goal) or {}

    def _try_drive_automation(self, goal: str) -> bool:
        if not _DRIVE.search(goal):
            return False
        g = self._connected_google()
        if not g:
            return False
        q = re.sub(r"\b(google drive|drive|me|se|par|pe|mein|search|dhundo|find|kholo|open|file|files)\b",
                   "", goal, flags=re.I).strip()
        from ..connectors.google import drive_search
        try:
            files = drive_search(g["email"], q or goal)
            if not files:
                self.speaker.say(f"drive me '{q}' se koi file nahi mili.")
            else:
                self.speaker.say("drive me ye files mili: " + "; ".join(n for n, _ in files[:5]))
        except Exception as e:  # noqa: BLE001
            self.speaker.say(f"drive search me dikkat: {e}")
        return True

    def _extract_email(self, goal: str) -> dict:
        llm = getattr(self.planner, "llm", None)
        if llm is None:
            return {}
        name = getattr(self, "user_name", None)
        sign = (f"Sign off naturally as '{name}'." if name
                else "End with just 'Best regards,' and NO name line.")
        sysmsg = (
            "Extract email fields from the user's request. Return ONLY JSON: "
            '{"to": "<address>", "subject": "<compose a fitting subject>", '
            '"body": "<write the complete email body in English>"}. '
            "Write a real subject and body — do NOT copy the instruction text. "
            "NEVER use bracketed placeholders like [Your Name], [Company], [Date]. "
            f"{sign}"
        )
        return llm.chat_json(sysmsg, goal) or {}

    def _operate(self, goal: str, retries: int = 2) -> None:
        """Do the task itself, auto-retrying until it works."""
        import time

        self.last_goal = goal
        if self._try_email_automation(goal):     # silent connector paths
            return
        if self._try_calendar_automation(goal):
            return
        if self._try_drive_automation(goal):
            return
        self.speaker.say(_p(self.language, "ok"))
        if self.ui_hide:
            self.ui_hide()
            time.sleep(0.5)                     # let Nova's own window disappear first
        ok = False
        try:
            for attempt in range(max(1, retries)):
                if attempt:
                    self.speaker.say("ek baar aur koshish kar rahi hoon…")
                ok = self._vision_agent().run(goal)
                if ok:
                    break
        finally:
            if self.ui_show:
                self.ui_show()
        if not ok:
            self.speaker.say("abhi ye nahi ho paya. 'dubara try kar' bolo toh phir se karungi.")
        self._remember(goal, "kaam ho gaya" if ok else "abhi nahi kar payi")

    def _extract_search_query(self, text: str) -> str:
        """Pull just the thing to search from a command like
        'chrome open karo aur todays news ke liye search karo' -> 'todays news'."""
        llm = getattr(self.planner, "llm", None)
        if llm is not None:
            data = llm.chat_json(
                "Extract ONLY the web search query the user wants. Strip command words "
                "like 'chrome', 'browser', 'open', 'kholo', 'search', 'dhoondo', 'dekho', "
                "'karo', 'ke liye', 'aur', 'me', 'par'. Return JSON: "
                '{"query": "<the actual thing to search>"}. Keep the real topic only.',
                text,
            ) or {}
            q = (data.get("query") or "").strip()
            if q:
                return q
        # offline fallback: strip the command scaffolding with regex
        q = _BROWSER.sub(" ", text)
        q = re.sub(
            r"\b(open|kholo|khol do|khol|launch|start|karo|kar do|kr do|kro|"
            r"aur|and|then|phir|search|dhoondo|dhoond|dekho|dekh|find|look ?up|"
            r"ke liye|ke liyeh|me|mein|par|pe|karke|todays?)\b",
            " ", q, flags=re.I,
        )
        return re.sub(r"\s+", " ", q).strip()

    def _try_browser_search(self, text: str) -> bool:
        """Open a real browser search-results page for the query in `text`."""
        query = self._extract_search_query(text)
        if not query:
            return False
        from urllib.parse import quote_plus
        url = f"https://www.google.com/search?q={quote_plus(query)}"
        self._open_browser(url, text, ask_ok=bool(_ASK_PROFILE.search(text)))
        return True

    # --- Chrome profile picking ("which account?") -------------------------
    def _open_browser(self, url, text: str, ask_ok: bool = False) -> None:
        """Open `url` (or just Chrome if None) in the user's chosen real profile.

        First run with several profiles -> ask which account; the choice is
        remembered so it won't nag every time (say 'dusre account me' to switch).
        """
        from ..browser import profiles as P
        profs = P.list_chrome_profiles()

        # a remembered preference, unless the user is explicitly re-choosing
        pref = None
        if self.memory and not ask_ok:
            try:
                pref = self.memory.get_pref("chrome_profile_dir")
            except Exception:
                pref = None
        if pref and any(p["dir"] == pref for p in profs):
            self._launch_profile(pref, url, text)
            return

        if len(profs) <= 1:                       # nothing to choose between
            d = profs[0]["dir"] if profs else "Default"
            self._launch_profile(d, url, text)
            return

        # multiple accounts -> ask which one
        self.pending_browser = {"url": url, "text": text, "profiles": profs}
        lines = "; ".join(
            f"{i + 1}. {p['name']}" + (f" ({p['email']})" if p['email'] else "")
            for i, p in enumerate(profs)
        )
        if self.language == "english":
            self.speaker.say(f"You have {len(profs)} Chrome accounts: {lines}. "
                             "Which one should I open? Say the number or the name.")
        else:
            self.speaker.say(f"Aapke paas {len(profs)} Chrome accounts hain: {lines}. "
                             "Kaunsa kholu? Number ya naam bolo.")

    def _launch_profile(self, profile_dir: str, url, text: str) -> None:
        from ..browser import profiles as P
        ok = P.open_in_profile(profile_dir, url)
        if not ok:                                # no real Chrome -> managed fallback
            if url:
                self.pipeline.run_plan(
                    Plan(steps=[Step(tool="open_url", args={"url": url})]), text)
            else:
                self.pipeline.run_plan(
                    Plan(steps=[Step(tool="open_app", args={"name": "chrome"})]), text)
        say = ("Chrome khol rahi hoon." if self.language != "english"
               else "Opening Chrome.")
        if ok:
            self.speaker.say(say)
        self._remember(text, say)

    def _resolve_browser_choice(self, text: str) -> None:
        pb = self.pending_browser
        self.pending_browser = None
        profs = pb.get("profiles", [])
        choice = self._match_profile(text, profs)
        if not choice:
            self.pending_browser = pb             # keep waiting for a valid pick
            msg = ("Samajh nahi aaya kaunsa — number bolo (1, 2, ...) ya naam."
                   if self.language != "english"
                   else "I didn't catch which one — say the number or the name.")
            self.speaker.say(msg)
            return
        if self.memory:
            try:
                self.memory.set_pref("chrome_profile_dir", choice["dir"])
            except Exception:
                pass
        self._launch_profile(choice["dir"], pb.get("url"), pb.get("text", text))

    def _match_profile(self, text: str, profs):
        t = " " + text.lower().strip() + " "
        words = {"pehl": 0, "first": 0, "ek ": 0, "dusr": 1, "second": 1,
                 "teesr": 2, "tisr": 2, "third": 2, "chauth": 3, "fourth": 3}
        for w, idx in words.items():
            if w in t and idx < len(profs):
                return profs[idx]
        m = re.search(r"\b(\d+)\b", text)
        if m:
            i = int(m.group(1)) - 1
            if 0 <= i < len(profs):
                return profs[i]
        for p in profs:                           # by name or email
            nm = (p.get("name") or "").lower()
            em = (p.get("email") or "").lower()
            if nm and nm in t:
                return p
            if em and (em in t or em.split("@")[0] in t):
                return p
        for p in profs:                           # by any distinctive name token
            for tok in (p.get("name") or "").lower().split():
                if len(tok) > 2 and f" {tok} " in t:
                    return p
        return None

    # --- image + PDF analysis (offline) ------------------------------------
    def _doc_question(self, text: str) -> str:
        """Strip the file reference + command words to isolate the real question."""
        q = re.sub(r"[A-Za-z]:\\[^\s\"']+", " ", text)                 # full paths
        q = re.sub(r"[\w\-]+\.(pdf|jpe?g|png|webp|bmp|gif)", " ", q, flags=re.I)  # filenames
        q = _DOC_CMD.sub(" ", q)
        q = re.sub(r"\s+", " ", q).strip(" ?.")
        if len(q.split()) >= 2 or re.search(r"\b(kya|kaun|kitn|kab|kahan|what|who|how|why)\b", q, re.I):
            return q
        return ""

    def _image_analyzer(self):
        if self._img is None:
            from ..vision.analyze import ImageAnalyzer
            self._img = ImageAnalyzer(self.vision_llm, self.language)
        return self._img

    def _grab_screenshot(self):
        try:
            import tempfile
            import pyautogui
            path = str(__import__("pathlib").Path(tempfile.gettempdir()) / "nova_shot.png")
            pyautogui.screenshot().save(path)
            return path
        except Exception as e:  # noqa: BLE001
            log.warning("screenshot failed: %s", e)
            return None

    def _analyze_image(self, text: str) -> None:
        from ..docs.files import resolve_file
        path = resolve_file(text, [".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"])
        if not path and _SCREENSHOT.search(text):
            path = self._grab_screenshot()
        if not path:
            self.speaker.say("Kaunsi image? File ka naam/path batao, ya 'latest photo dekho' bolo.")
            return
        analyzer = self._image_analyzer()
        if not analyzer.available():
            self.speaker.say("Image samajhne wala vision model abhi available nahi hai.")
            return
        self.speaker.say(_p(self.language, "ok"))
        ans = analyzer.describe(path, self._doc_question(text)) or "Is image ko samajh nahi payi."
        self.speaker.say(ans)
        self._remember(text, ans)

    def _analyze_pdf(self, text: str) -> None:
        from ..docs.files import resolve_file
        path = resolve_file(text, [".pdf"])
        if path:
            from ..docs.pdf import PdfDoc
            emb = getattr(self.memory, "embedder", None)
            llm = getattr(self.planner, "llm", None)
            if not emb and llm is not None:
                emb = llm.embed
            self.speaker.say(_p(self.language, "ok"))
            doc = PdfDoc(path, emb, llm, self.language)
            try:
                doc.build()
            except Exception as e:  # noqa: BLE001
                self.speaker.say(f"PDF khol nahi payi: {e}")
                return
            self.current_doc = doc
            q = self._doc_question(text)
            ans = doc.answer(q) if q else doc.summary()
        elif self.current_doc:
            ans = self.current_doc.answer(text)          # follow-up on the loaded PDF
        else:
            self.speaker.say("Kaunsi PDF? Naam ya path batao — jaise 'Downloads me resume.pdf padho'.")
            return
        self.speaker.say(ans)
        self._remember(text, ans)

    def _search_answer(self, text: str) -> None:
        """Live web search -> grounded spoken answer, remembering the sources."""
        query = self._strip_name(text)
        try:
            answer, sources = self.researcher.answer(query or text)
        except Exception as e:  # noqa: BLE001
            log.warning("web search failed: %s", e)
            answer, sources = ("Net se laane me dikkat aa gayi, thodi der me try karo.", [])
        self.last_sources = [{"title": s.title, "url": s.url} for s in sources]
        self.speaker.say(answer)
        self._remember(text, answer)

    def _route(self, text: str) -> None:
        # 0) waiting for a Chrome-account pick -> this utterance IS the answer
        if self.pending_browser:
            self._resolve_browser_choice(text)
            return

        # 0a) "yaad rakhna X" -> save a long-term fact
        m = _REMEMBER.search(text)
        if m and self.memory:
            fact = m.group(2).strip()
            self.memory.add_fact(fact)
            reply = f"theek hai, yaad rakh liya: {fact}"
            self.speaker.say(reply)
            self._remember(text, reply)
            return

        # 0b) "dubara try kar" -> re-run the last task itself (never explain steps)
        if _RETRY.search(text) and self.last_goal:
            self._operate(self.last_goal, retries=3)
            return

        # 0b3) image analysis — a picture path, or "photo/screenshot me kya hai"
        if _IMG_EXT.search(text) or (_IMG_WORD.search(text) and _ANALYZE_VERB.search(text)):
            self._analyze_image(text)
            return

        # 0b4) PDF analysis / Q&A — a .pdf, or a follow-up "isme ..." on the loaded PDF
        if _PDF_ANY.search(text) or (self.current_doc and _DOC_REF.search(text)):
            self._analyze_pdf(text)
            return

        # 0c) an action goal — send/operate, or a Calendar/Drive intent for a connector
        if _OPERATE.search(text) or _CAL.search(text) or _DRIVE.search(text):
            self._operate(text, retries=2)
            return

        # 0c2) "open chrome AND search X" — a browser is named + a search verb.
        #      Do it properly: open the browser straight to the search results,
        #      instead of dumping the whole sentence into the Start menu.
        if _BROWSER.search(text) and _SEARCH.search(text):
            if self._try_browser_search(text):
                return

        # 0c3) just "chrome kholo" (browser + open, no search) — open the real
        #      Chrome in the chosen account, not the empty guest-like profile.
        if _BROWSER.search(text) and _OPEN.search(text) and not _SEARCH.search(text):
            self._open_browser(None, text, ask_ok=bool(_ASK_PROFILE.search(text)))
            return

        # 0d) web-search intent -> look it up live and answer, grounded in results.
        #     Explicit "search/google/net pe" always fires; soft cues (news/latest)
        #     only when a key is set, else fall through to normal chat.
        if self.researcher and _WEB.search(text) and not _OPEN.search(text):
            if self.researcher.available() or _WEB_EXPLICIT.search(text):
                self._search_answer(text)
                return

        # 1) rules-first fast-path — instant, no LLM
        fast = rule_based_plan(text, self.language)
        if fast.steps:
            self.pipeline.run_plan(fast, text)
            self._remember(text, fast.final or fast.say)
            return

        # 2) looks like an action rules couldn't parse -> LLM planner
        if _ACTION_HINT.search(text):
            plan = self.planner.plan(text, context=self._context())
            if plan.steps:
                self.pipeline.run_plan(plan, text)
                self._remember(text, plan.final or plan.say)
                return

        # 3) otherwise it's conversation -> answer (with persistent history +
        #    the facts most RELEVANT to this turn, recalled by meaning)
        facts = self._relevant_facts(text)
        if self.stream_replies and getattr(self.chat, "llm", None) is not None:
            # speak sentence-by-sentence so the first words come out fast
            answer = self.chat.answer_stream(text, self.history, facts, self.speaker.say)
        else:
            answer = self.chat.answer(text, self.history, facts)
            self.speaker.say(answer)
        self._remember(text, answer)

    # --- helpers ------------------------------------------------------------
    def _strip_name(self, text: str) -> str:
        t = text.strip()
        t = re.sub(r"^(hey|hi|arre|arey|yaar|yrr|o|suno|sun)\s+", "", t, flags=re.I).strip()
        t = re.sub(r"^(nova|nowa|no va)\b[,\s]*", "", t, flags=re.I).strip()
        t = re.sub(r"^(yaar|yrr|sun|suno|bata|tu bata|zara)\b[,\s]*", "", t, flags=re.I).strip()
        return t

    def _context(self) -> str:
        if not self.history:
            return ""
        return " | ".join(f"{r}: {c}" for r, c in self.history[-2:])

    def _facts(self) -> List[str]:
        try:
            return self.memory.all_facts() if self.memory else []
        except Exception:
            return []

    def _relevant_facts(self, query: str) -> List[str]:
        """Facts relevant to this turn (semantic if embeddings exist, else recent)."""
        if not self.memory:
            return []
        try:
            return self.memory.relevant_facts(query)
        except Exception:
            return self._facts()

    def _remember(self, user_text: str, assistant_text: str) -> None:
        self.history.append(("user", user_text))
        if assistant_text:
            self.history.append(("assistant", assistant_text))
        if self.memory:                          # persist so the chat survives restarts
            try:
                self.memory.add_turn(self.session_id, "user", user_text)
                if assistant_text:
                    self.memory.add_turn(self.session_id, "assistant", assistant_text)
            except Exception:
                pass
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history:]
