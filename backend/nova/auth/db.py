"""Auth data access.

apex.oracle.com has no external DB access, so the default path is ORDS REST:
the PL/SQL is exposed as HTTPS endpoints (see backend/sql/03_ords_rest.sql) and
we call them with `requests`. If instead you point at a real Oracle DB
(ORACLE_DSN set), it falls back to python-oracledb calling the PL/SQL procs.

Config (backend/.env):
  ORDS_BASE_URL   e.g. https://oracleapex.com/ords/novadb/nova/auth   <- apex path
  -- or --
  ORACLE_USER / ORACLE_PASSWORD / ORACLE_DSN  (+ wallet vars for Autonomous)
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Optional


def _mode() -> Optional[str]:
    if os.getenv("ORDS_BASE_URL"):
        return "ords"
    if os.getenv("ORACLE_DSN"):
        return "oracle"
    return None


def available() -> bool:
    return True


class _LocalAuthStore:
    def __init__(self):
        self.path = os.getenv("AUTH_LOCAL_DB") or str(Path(__file__).resolve().parent / "auth_local.db")
        self._init_db()

    def _init_db(self, force: bool = False):
        if force and os.path.exists(self.path):
            os.remove(self.path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        try:
            conn.execute("""CREATE TABLE IF NOT EXISTS auth_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                name TEXT,
                password_hash TEXT,
                provider TEXT NOT NULL DEFAULT 'local',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            conn.commit()
        finally:
            conn.close()

    def _connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def register(self, email: str, name: str, pw_hash: str, provider: str = "local") -> int:
        email = email.lower()
        conn = self._connect()
        try:
            existing = conn.execute(
                "SELECT id FROM auth_users WHERE email = ? COLLATE NOCASE",
                (email,),
            ).fetchone()
            if existing:
                raise ValueError("That email is already registered")
            cur = conn.execute(
                "INSERT INTO auth_users (email, name, password_hash, provider) VALUES (?, ?, ?, ?)",
                (email, name, pw_hash, provider),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def get(self, email: Optional[str]) -> Optional[dict]:
        if not email:
            return None
        email = email.lower()
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT id, email, name, password_hash, provider FROM auth_users WHERE email = ? COLLATE NOCASE",
                (email,),
            ).fetchone()
            if not row:
                return None
            return {
                "id": int(row["id"]),
                "email": row["email"],
                "name": row["name"],
                "password_hash": row["password_hash"],
                "provider": row["provider"],
            }
        finally:
            conn.close()

    def upsert_google(self, email: str, name: str) -> int:
        email = email.lower()
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT id FROM auth_users WHERE email = ? COLLATE NOCASE",
                (email,),
            ).fetchone()
            if row:
                conn.execute("UPDATE auth_users SET name = ?, provider = 'google' WHERE id = ?", (name, int(row["id"])))
                conn.commit()
                return int(row["id"])
            cur = conn.execute(
                "INSERT INTO auth_users (email, name, password_hash, provider) VALUES (?, ?, ?, ?)",
                (email, name, None, "google"),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()


local_store = _LocalAuthStore()


# ============================ ORDS (apex.oracle.com) ========================
def _base() -> str:
    return os.getenv("ORDS_BASE_URL", "").rstrip("/")


def _ords_err(what, r):
    return RuntimeError(f"ORDS {what} -> HTTP {r.status_code}: {(r.text or '')[:300]}")


# apex.oracle.com's free tier can be slow (multi-second cold responses) and
# Render <-> Oracle inter-region latency adds more. Give it real breathing room
# via a (connect, read) tuple and one automatic retry on timeout / connection
# errors. Overridable via env for tuning without a code push.
_ORDS_TIMEOUT = (
    float(os.getenv("ORDS_CONNECT_TIMEOUT", "10")),
    float(os.getenv("ORDS_READ_TIMEOUT", "60")),
)
_ORDS_RETRIES = int(os.getenv("ORDS_RETRIES", "2"))


def _ords_request(method, path, **kwargs):
    """HTTP call to ORDS with retry-on-timeout — apex is often slow the first time."""
    import time
    import requests

    kwargs.setdefault("timeout", _ORDS_TIMEOUT)
    url = f"{_base()}{path}"
    last_err = None
    for attempt in range(_ORDS_RETRIES + 1):
        try:
            return requests.request(method, url, **kwargs)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_err = e
            if attempt < _ORDS_RETRIES:
                time.sleep(1.0 * (attempt + 1))     # gentle backoff
                continue
            raise


def _ords_register(email, name, pw_hash, provider):
    r = _ords_request(
        "POST", "/register",
        json={"email": email, "name": name, "hash": pw_hash, "provider": provider},
    )
    if not r.ok:
        raise _ords_err("/register", r)
    # The ORDS plsql/block handler inserts the row but returns an EMPTY body
    # (it can't serialize its OUT bind), so read the new id back from /user.
    u = _ords_get_user(email)
    if not u or u.get("id") is None:
        raise _ords_err("/register (saved but /user returned no id)", r)
    return int(u["id"])


def _ords_get_user(email):
    r = _ords_request("GET", "/user", params={"email": email})
    if r.status_code == 404:
        return None
    r.raise_for_status()
    d = r.json() or {}
    if d.get("id") is None:
        return None
    return {
        "id": int(d["id"]), "email": email.lower(), "name": d.get("name"),
        "password_hash": d.get("password_hash"), "provider": d.get("provider"),
    }


def _ords_upsert_google(email, name):
    # The /google plsql/block handler upserts the user but returns an EMPTY body,
    # so read the id back from /user (which returns proper JSON).
    r = _ords_request("POST", "/google", json={"email": email, "name": name})
    if not r.ok:
        raise _ords_err("/google", r)
    u = _ords_get_user(email)
    if not u or u.get("id") is None:
        raise _ords_err("/google (saved but /user returned no id)", r)
    return int(u["id"])


# ============================ python-oracledb (direct) ======================
def _connect():
    import oracledb

    kwargs = dict(user=os.getenv("ORACLE_USER"), password=os.getenv("ORACLE_PASSWORD"),
                  dsn=os.getenv("ORACLE_DSN"))
    cfg = os.getenv("ORACLE_CONFIG_DIR")
    if cfg:
        kwargs["config_dir"] = cfg
        kwargs["wallet_location"] = cfg
    if os.getenv("ORACLE_WALLET_PASSWORD"):
        kwargs["wallet_password"] = os.getenv("ORACLE_WALLET_PASSWORD")
    return oracledb.connect(**kwargs)


def _ora_register(email, name, pw_hash, provider):
    import oracledb

    with _connect() as con:
        cur = con.cursor()
        out = cur.var(oracledb.NUMBER)
        cur.callproc("nova_register", [email, name, pw_hash, provider, out])
        con.commit()
        return int(out.getvalue())


def _ora_get_user(email):
    import oracledb

    with _connect() as con:
        cur = con.cursor()
        pid, pname, phash, pprov = cur.var(oracledb.NUMBER), cur.var(str), cur.var(str), cur.var(str)
        cur.callproc("nova_get_user", [email, pid, pname, phash, pprov])
        if pid.getvalue() is None:
            return None
        return {"id": int(pid.getvalue()), "email": email.lower(), "name": pname.getvalue(),
                "password_hash": phash.getvalue(), "provider": pprov.getvalue()}


def _ora_upsert_google(email, name):
    import oracledb

    with _connect() as con:
        cur = con.cursor()
        out = cur.var(oracledb.NUMBER)
        cur.callproc("nova_upsert_google", [email, name, out])
        con.commit()
        return int(out.getvalue())


# ============================ dispatch ======================================
# When ORDS/Oracle is configured we go THERE — no silent SQLite fallback (that
# was hiding real ORDS errors and saving users to an ephemeral local file that
# gets wiped on every Render restart). SQLite is only used when no accounts
# backend is configured at all (pure local/dev).
def register_user(email: str, name: str, pw_hash: str, provider: str = "local") -> int:
    mode = _mode()
    if mode == "ords":
        return _ords_register(email, name, pw_hash, provider)
    if mode == "oracle":
        return _ora_register(email, name, pw_hash, provider)
    return local_store.register(email, name, pw_hash, provider)


def get_user(email: str) -> Optional[dict]:
    mode = _mode()
    if mode == "ords":
        return _ords_get_user(email)
    if mode == "oracle":
        return _ora_get_user(email)
    return local_store.get(email)


def upsert_google(email: str, name: str) -> int:
    mode = _mode()
    if mode == "ords":
        return _ords_upsert_google(email, name)
    if mode == "oracle":
        return _ora_upsert_google(email, name)
    return local_store.upsert_google(email, name)
