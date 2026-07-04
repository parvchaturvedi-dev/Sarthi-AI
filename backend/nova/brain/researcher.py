"""Search-grounded answers — the JARVIS move: look it up, then explain.

Given a question that needs live/factual info, we (1) web-search via LangSearch,
(2) optionally rerank, (3) hand the top results to the LLM as grounding, and
(4) get back a natural, spoken-friendly answer in the user's language — grounded
in what's actually on the web today, not the model's stale memory.

Returns (spoken_answer, sources) so the UI can show links while Sarthi speaks.
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional, Tuple

from ..connectors.web_search import SearchResult, WebSearchClient

log = logging.getLogger("nova.researcher")

# how "fresh" the results must be, inferred from the wording of the question
_TODAY = re.compile(r"\b(aaj|today|abhi|abhi ka|right now|is waqt|breaking|just now)\b", re.I)
_RECENT = re.compile(r"\b(latest|recent|news|khabar|update|score|live|current|"
                     r"is hafte|this week|kal|yesterday|price|bhaav|rate|stock|mausam|weather)\b", re.I)

_ANSWER_SYSTEM = {
    "hinglish": (
        "You are Sarthi, a smart female assistant. Using ONLY the web results given, "
        "answer the user's question in casual HINGLISH (Roman script, female voice: "
        "'bata rahi hoon'). Be accurate and specific — pull the real facts, numbers, "
        "names and dates from the results. Keep it natural and spoken (this is read "
        "aloud), 2-5 sentences. If the results don't actually answer it, say so "
        "honestly. NEVER use Devanagari. Do NOT read out URLs."
    ),
    "hindi": (
        "तुम सारथी हो। सिर्फ़ दिए गए वेब परिणामों के आधार पर उपयोगकर्ता के सवाल का "
        "उत्तर देवनागरी हिंदी में दो — सटीक तथ्य, नाम, तारीख़ें शामिल करो। बोलकर सुनाने "
        "लायक़, 2-5 वाक्य। URL मत पढ़ो।"
    ),
    "english": (
        "You are Sarthi, a smart assistant. Using ONLY the web results provided, "
        "answer the user's question accurately with the real facts, numbers, names "
        "and dates. Natural, spoken style (read aloud), 2-5 sentences. If the results "
        "don't answer it, say so honestly. Do not read out URLs."
    ),
}


class Researcher:
    def __init__(self, llm, search: WebSearchClient, language: str = "hinglish"):
        self.llm = llm
        self.search = search
        self.language = language

    def available(self) -> bool:
        return self.search.available()

    def _freshness(self, query: str) -> str:
        if _TODAY.search(query):
            return "oneDay"
        if _RECENT.search(query):
            return "oneWeek"
        return "noLimit"

    def answer(self, query: str, count: int = 5) -> Tuple[str, List[SearchResult]]:
        """Search the web and return a grounded spoken answer + the sources used."""
        query = (query or "").strip()
        if not query:
            return ("Kya search karun, thoda batao?", [])
        if not self.search.available():
            return (self._no_key(), [])

        results = self.search.search(query, count=max(count, 5),
                                     freshness=self._freshness(query), summary=True)
        if not results:
            return (self._nothing(), [])

        results = self.search.rerank(query, results, top_n=count)

        if self.llm is None:                       # no brain -> read the top result
            top = results[0]
            text = top.best_text[:400] or top.title
            return (f"{text} (source: {_domain(top.url)})", results)

        context = self._format(results)
        system = _ANSWER_SYSTEM.get(self.language, _ANSWER_SYSTEM["english"])
        user = f"QUESTION: {query}\n\nWEB RESULTS:\n{context}\n\nAnswer now."
        reply = self.llm.chat_text(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.3,
        )
        if not reply:
            top = results[0]
            reply = top.best_text[:400] or top.title
        return (reply.strip(), results)

    # --- helpers -----------------------------------------------------------
    def _format(self, results: List[SearchResult], limit: int = 5) -> str:
        blocks = []
        for i, r in enumerate(results[:limit], 1):
            body = r.best_text[:600]
            date = f" ({r.date})" if r.date else ""
            blocks.append(f"[{i}] {r.title}{date}\n{body}\nsource: {_domain(r.url)}")
        return "\n\n".join(blocks)

    def _no_key(self) -> str:
        if self.language == "hinglish":
            return ("Web search on karne ke liye LangSearch ka API key chahiye — "
                    "langsearch.com se free le lo, phir main net se dhoond ke bataungi.")
        return ("I need a LangSearch API key to search the web — grab a free one from "
                "langsearch.com and I'll look things up live.")

    def _nothing(self) -> str:
        if self.language == "hinglish":
            return "Net pe iske baare me kuch khaas nahi mila, thoda alag tarah se poochho."
        return "I couldn't find anything useful on that — try rephrasing it."


def _domain(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url or "")
    return (m.group(1).replace("www.", "") if m else url)[:60]
