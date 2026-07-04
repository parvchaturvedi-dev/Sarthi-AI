"""LangSearch web-search client — Sarthi's window to the live internet.

This is what turns her from an offline model (stale knowledge) into a JARVIS-like
assistant that knows *today's* world: news, weather, prices, scores, "who won",
"latest ...". LangSearch (https://langsearch.com) gives a free Web Search API +
a semantic reranker; we wrap both, dependency-light (just `requests`).

Key resolution order: explicit arg -> env LANGSEARCH_API_KEY -> config search.api_key.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import List, Optional

import requests

log = logging.getLogger("nova.search")

SEARCH_URL = "https://api.langsearch.com/v1/web-search"
RERANK_URL = "https://api.langsearch.com/v1/rerank"


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    summary: str
    date: Optional[str] = None

    @property
    def best_text(self) -> str:
        """The richest text available for this result (summary beats snippet)."""
        return (self.summary or self.snippet or "").strip()


class WebSearchClient:
    def __init__(self, api_key: Optional[str] = None, timeout_s: int = 20):
        self.api_key = (api_key or os.getenv("LANGSEARCH_API_KEY") or "").strip()
        self.timeout_s = timeout_s

    def available(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def search(
        self,
        query: str,
        count: int = 5,
        freshness: str = "noLimit",
        summary: bool = True,
    ) -> List[SearchResult]:
        """Run a web search and return parsed results (empty list on any failure)."""
        query = (query or "").strip()
        if not query or not self.available():
            return []
        try:
            r = requests.post(
                SEARCH_URL,
                headers=self._headers(),
                json={
                    "query": query,
                    "freshness": freshness,
                    "summary": summary,
                    "count": max(1, min(int(count), 10)),
                },
                timeout=self.timeout_s,
            )
            r.raise_for_status()
            data = r.json()
            values = (
                (data.get("data") or {}).get("webPages", {}).get("value") or []
            )
            out: List[SearchResult] = []
            for v in values:
                out.append(
                    SearchResult(
                        title=(v.get("name") or "").strip(),
                        url=(v.get("url") or "").strip(),
                        snippet=(v.get("snippet") or "").strip(),
                        summary=(v.get("summary") or "").strip(),
                        date=v.get("datePublished"),
                    )
                )
            return out
        except Exception as e:  # noqa: BLE001
            log.warning("LangSearch web-search failed: %s", e)
            return []

    def rerank(
        self, query: str, results: List[SearchResult], top_n: int = 5
    ) -> List[SearchResult]:
        """Reorder results by semantic relevance to the query (best-effort).

        Falls back to the original order if the reranker is unavailable or errors.
        """
        if not results or not self.available():
            return results[:top_n]
        docs = [r.best_text or r.title for r in results]
        try:
            r = requests.post(
                RERANK_URL,
                headers=self._headers(),
                json={
                    "model": "langsearch-reranker-v1",
                    "query": query,
                    "documents": docs,
                    "top_n": min(top_n, len(docs)),
                    "return_documents": False,
                },
                timeout=self.timeout_s,
            )
            r.raise_for_status()
            ranked = r.json().get("results") or []
            order = [item.get("index") for item in ranked if item.get("index") is not None]
            picked = [results[i] for i in order if 0 <= i < len(results)]
            return picked or results[:top_n]
        except Exception as e:  # noqa: BLE001
            log.info("rerank fell back to original order: %s", e)
            return results[:top_n]
