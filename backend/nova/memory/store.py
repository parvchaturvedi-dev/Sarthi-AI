"""Persistent memory — SQLite for now (contacts, preferences, command history).

Small and synchronous on purpose. Vector memory (ChromaDB/FAISS) can slot in
later behind the same Memory interface without changing callers.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Callable, List, Optional

log = logging.getLogger("nova.memory")

SCHEMA = """
CREATE TABLE IF NOT EXISTS prefs (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS contacts (
    name    TEXT PRIMARY KEY,
    channel TEXT,          -- e.g. whatsapp
    handle  TEXT           -- resolved contact/number
);
CREATE TABLE IF NOT EXISTS history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         REAL,
    utterance  TEXT,
    plan_json  TEXT,
    ok         INTEGER
);
CREATE TABLE IF NOT EXISTS sessions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT,
    created_ts REAL,
    updated_ts REAL
);
CREATE TABLE IF NOT EXISTS conversation (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         REAL,
    role       TEXT,          -- user | assistant
    content    TEXT,
    session_id INTEGER
);
CREATE TABLE IF NOT EXISTS facts (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    ts   REAL,
    fact TEXT UNIQUE        -- things to remember long-term about the user
);
CREATE TABLE IF NOT EXISTS fact_vecs (
    fact TEXT PRIMARY KEY,  -- the fact text (mirrors facts.fact)
    vec  BLOB               -- float32 embedding for semantic recall
);
"""


class Memory:
    def __init__(self, db_path: str):
        self.path = str(Path(db_path))
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self._lock = threading.RLock()          # one connection shared across threads
        # optional text->vector fn (set by the engine when Ollama embeddings exist);
        # when present, facts are recalled semantically instead of most-recent-first.
        self.embedder: Optional[Callable[[str], Optional[List[float]]]] = None
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        # older DBs have a conversation table without session_id
        cols = [r[1] for r in self.conn.execute("PRAGMA table_info(conversation)").fetchall()]
        if "session_id" not in cols:
            self.conn.execute("ALTER TABLE conversation ADD COLUMN session_id INTEGER")

    # prefs ------------------------------------------------------------------
    def set_pref(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO prefs(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self.conn.commit()

    def get_pref(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self.conn.execute("SELECT value FROM prefs WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    # contacts ---------------------------------------------------------------
    def resolve_contact(self, name: str) -> Optional[tuple[str, str]]:
        row = self.conn.execute(
            "SELECT channel, handle FROM contacts WHERE name=? COLLATE NOCASE", (name,)
        ).fetchone()
        return (row[0], row[1]) if row else None

    def set_contact(self, name: str, channel: str, handle: str) -> None:
        self.conn.execute(
            "INSERT INTO contacts(name,channel,handle) VALUES(?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET channel=excluded.channel, handle=excluded.handle",
            (name, channel, handle),
        )
        self.conn.commit()

    # history ----------------------------------------------------------------
    def log(self, utterance: str, plan_json: str, ok: bool) -> None:
        self.conn.execute(
            "INSERT INTO history(ts,utterance,plan_json,ok) VALUES(?,?,?,?)",
            (time.time(), utterance, plan_json, int(ok)),
        )
        self.conn.commit()

    # sessions (separate chats, like ChatGPT/Claude threads) ----------------
    def create_session(self, title: str = "New chat") -> int:
      with self._lock:
        ts = time.time()
        cur = self.conn.execute(
            "INSERT INTO sessions(title,created_ts,updated_ts) VALUES(?,?,?)", (title, ts, ts)
        )
        self.conn.commit()
        return cur.lastrowid

    def current_session(self) -> int:
      with self._lock:
        row = self.conn.execute(
            "SELECT id FROM sessions ORDER BY updated_ts DESC LIMIT 1"
        ).fetchone()
        return row[0] if row else self.create_session()

    def list_sessions(self, limit: int = 40) -> list[tuple[int, str, float]]:
      with self._lock:
        rows = self.conn.execute(
            "SELECT id, title, updated_ts FROM sessions ORDER BY updated_ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [(r[0], r[1] or "New chat", r[2]) for r in rows]

    def session_turns(self, session_id: int, limit: int = 300) -> list[tuple[str, str]]:
      with self._lock:
        rows = self.conn.execute(
            "SELECT role, content FROM conversation WHERE session_id=? ORDER BY id ASC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        return [(r[0], r[1]) for r in rows]

    # conversation (persistent, per-session) --------------------------------
    def add_turn(self, session_id: int, role: str, content: str) -> None:
        if not content:
            return
        with self._lock:
            now = time.time()
            self.conn.execute(
                "INSERT INTO conversation(ts,role,content,session_id) VALUES(?,?,?,?)",
                (now, role, content, session_id),
            )
            self.conn.execute("UPDATE sessions SET updated_ts=? WHERE id=?", (now, session_id))
            if role == "user":                          # name the chat after the first ask
                row = self.conn.execute(
                    "SELECT title FROM sessions WHERE id=?", (session_id,)
                ).fetchone()
                if row and (not row[0] or row[0] == "New chat"):
                    self.conn.execute(
                        "UPDATE sessions SET title=? WHERE id=?", (content[:42], session_id)
                    )
            self.conn.commit()

    def recent_turns(self, n: int = 12) -> list[tuple[str, str]]:
        rows = self.conn.execute(
            "SELECT role, content FROM conversation ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()
        return [(r[0], r[1]) for r in reversed(rows)]      # oldest -> newest

    # facts (long-term things to remember) ----------------------------------
    def add_fact(self, fact: str) -> None:
        fact = (fact or "").strip()
        if not fact:
            return
        with self._lock:
            self.conn.execute(
                "INSERT OR IGNORE INTO facts(ts,fact) VALUES(?,?)", (time.time(), fact)
            )
            self.conn.commit()
        self._embed_fact(fact)

    def all_facts(self, limit: int = 50) -> list[str]:
        rows = self.conn.execute(
            "SELECT fact FROM facts ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [r[0] for r in rows]

    # --- semantic recall (RAG) ---------------------------------------------
    def _embed_fact(self, fact: str) -> None:
        """Compute + store the embedding for one fact (best-effort, non-fatal)."""
        if not self.embedder:
            return
        try:
            vec = self.embedder(fact)
            if not vec:
                return
            from .vectors import pack
            with self._lock:
                self.conn.execute(
                    "INSERT OR REPLACE INTO fact_vecs(fact,vec) VALUES(?,?)",
                    (fact, pack(vec)),
                )
                self.conn.commit()
        except Exception as e:  # noqa: BLE001
            log.info("fact embed skipped: %s", e)

    def reindex_facts(self) -> int:
        """Backfill embeddings for facts saved before the embedder existed.

        Returns how many were newly embedded. Cheap and idempotent — safe to call
        on every startup.
        """
        if not self.embedder:
            return 0
        rows = self.conn.execute(
            "SELECT fact FROM facts WHERE fact NOT IN (SELECT fact FROM fact_vecs)"
        ).fetchall()
        n = 0
        for (fact,) in rows:
            before = self.conn.execute(
                "SELECT 1 FROM fact_vecs WHERE fact=?", (fact,)
            ).fetchone()
            self._embed_fact(fact)
            if not before and self.conn.execute(
                "SELECT 1 FROM fact_vecs WHERE fact=?", (fact,)
            ).fetchone():
                n += 1
        if n:
            log.info("reindexed %d fact(s) into semantic memory", n)
        return n

    def relevant_facts(self, query: str, k: int = 6) -> list[str]:
        """Facts most relevant to `query` by meaning (falls back to recent facts).

        This is what makes recall feel smart: 'papa ko mail karo' surfaces the
        fact about papa's email even if it was saved long ago and worded
        differently — not just the last N things blindly.
        """
        query = (query or "").strip()
        if not self.embedder or not query:
            return self.all_facts(k)
        try:
            qvec = self.embedder(query)
            if not qvec:
                return self.all_facts(k)
            rows = self.conn.execute("SELECT fact, vec FROM fact_vecs").fetchall()
            if not rows:
                return self.all_facts(k)
            from .vectors import top_k, unpack
            items = [(r[0], unpack(r[1])) for r in rows]
            hits = top_k(qvec, items, k=k)
            if hits:
                return [text for text, _ in hits]
        except Exception as e:  # noqa: BLE001
            log.info("semantic recall fell back: %s", e)
        return self.all_facts(k)

    def close(self) -> None:
        self.conn.close()
