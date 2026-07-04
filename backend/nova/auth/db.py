"""Auth data access.

Production: MongoDB (Atlas). Set `MONGODB_URI` in the environment and the app
auto-creates the `users` collection with a unique-email index and an atomic
integer id counter (so JWT `sub` and app code keep treating id as int).

Local dev / no env: a small SQLite file next to this module (works out of the
box — no cloud setup needed to run the desktop / local backend).
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Optional


def _mode() -> Optional[str]:
    if os.getenv("MONGODB_URI"):
        return "mongo"
    return None


def available() -> bool:
    return True


# ============================ Local SQLite (dev only) ======================
class _LocalAuthStore:
    def __init__(self):
        self.path = os.getenv("AUTH_LOCAL_DB") or str(
            Path(__file__).resolve().parent / "auth_local.db"
        )
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
                "SELECT id, email, name, password_hash, provider FROM auth_users "
                "WHERE email = ? COLLATE NOCASE", (email,),
            ).fetchone()
            if not row:
                return None
            return {
                "id": int(row["id"]), "email": row["email"], "name": row["name"],
                "password_hash": row["password_hash"], "provider": row["provider"],
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
                conn.execute(
                    "UPDATE auth_users SET name = ?, provider = 'google' WHERE id = ?",
                    (name, int(row["id"])),
                )
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


# ============================ MongoDB (production) ==========================
_MG_READY = False
_MG_USERS = None
_MG_COUNTERS = None


def _mg_init():
    global _MG_READY, _MG_USERS, _MG_COUNTERS
    if _MG_READY:
        return
    import pymongo

    uri = os.getenv("MONGODB_URI", "")
    kwargs = {"serverSelectionTimeoutMS": 10000}
    # Atlas (mongodb+srv://) needs TLS with a good CA bundle. Plain mongodb://
    # (Railway TCP proxy, self-hosted, etc.) is plain TCP — no TLS.
    if uri.startswith("mongodb+srv://"):
        import certifi
        kwargs["tls"] = True
        kwargs["tlsCAFile"] = certifi.where()
        # Escape hatch for cloud containers whose OpenSSL refuses Atlas TLS 1.3
        # even with a good CA bundle. Password still travels over the encrypted
        # tunnel; only cert VERIFICATION is skipped.
        if os.getenv("MONGODB_TLS_INSECURE", "").strip() in ("1", "true", "yes"):
            kwargs["tlsAllowInvalidCertificates"] = True
            kwargs["tlsAllowInvalidHostnames"] = True
    client = pymongo.MongoClient(uri, **kwargs)
    db = client[os.getenv("MONGODB_DB", "sarthi")]
    _MG_USERS = db["users"]
    _MG_COUNTERS = db["counters"]
    _MG_USERS.create_index("email", unique=True)
    _MG_READY = True


def _mg_next_id() -> int:
    """Atomic auto-incrementing numeric id — keeps user.id an int."""
    from pymongo import ReturnDocument
    r = _MG_COUNTERS.find_one_and_update(
        {"_id": "user_id"},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return int(r["seq"])


def _mg_register(email, name, pw_hash, provider):
    _mg_init()
    from datetime import datetime, timezone
    from pymongo.errors import DuplicateKeyError

    email = email.lower()
    uid = _mg_next_id()
    try:
        _MG_USERS.insert_one({
            "_id": uid, "email": email, "name": name,
            "password_hash": pw_hash, "provider": provider,
            "created_at": datetime.now(timezone.utc),
        })
    except DuplicateKeyError:
        raise ValueError("That email is already registered")
    return uid


def _mg_get_user(email):
    _mg_init()
    doc = _MG_USERS.find_one({"email": email.lower()})
    if not doc:
        return None
    return {
        "id": int(doc["_id"]), "email": doc["email"], "name": doc.get("name"),
        "password_hash": doc.get("password_hash"), "provider": doc.get("provider"),
    }


def _mg_upsert_google(email, name):
    _mg_init()
    from datetime import datetime, timezone

    email = email.lower()
    existing = _MG_USERS.find_one({"email": email})
    if existing:
        if name and name != existing.get("name"):
            _MG_USERS.update_one({"_id": existing["_id"]}, {"$set": {"name": name}})
        return int(existing["_id"])
    uid = _mg_next_id()
    _MG_USERS.insert_one({
        "_id": uid, "email": email, "name": name, "provider": "google",
        "created_at": datetime.now(timezone.utc),
    })
    return uid


# ============================ dispatch ======================================
def register_user(email: str, name: str, pw_hash: str, provider: str = "local") -> int:
    if _mode() == "mongo":
        return _mg_register(email, name, pw_hash, provider)
    return local_store.register(email, name, pw_hash, provider)


def get_user(email: str) -> Optional[dict]:
    if _mode() == "mongo":
        return _mg_get_user(email)
    return local_store.get(email)


def upsert_google(email: str, name: str) -> int:
    if _mode() == "mongo":
        return _mg_upsert_google(email, name)
    return local_store.upsert_google(email, name)
