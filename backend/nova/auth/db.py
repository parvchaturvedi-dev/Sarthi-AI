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
_MG_CHATS = None
_MG_MESSAGES = None
_MG_TOKENS = None


def _mg_init():
    global _MG_READY, _MG_USERS, _MG_COUNTERS, _MG_CHATS, _MG_MESSAGES, _MG_TOKENS
    if _MG_READY:
        return
    import pymongo

    uri = os.getenv("MONGODB_URI", "")
    kwargs = {"serverSelectionTimeoutMS": 10000}
    if uri.startswith("mongodb+srv://"):
        import certifi
        kwargs["tls"] = True
        kwargs["tlsCAFile"] = certifi.where()
        if os.getenv("MONGODB_TLS_INSECURE", "").strip() in ("1", "true", "yes"):
            kwargs["tlsAllowInvalidCertificates"] = True
            kwargs["tlsAllowInvalidHostnames"] = True
    client = pymongo.MongoClient(uri, **kwargs)
    db = client[os.getenv("MONGODB_DB", "sarthi")]
    _MG_USERS = db["users"]
    _MG_COUNTERS = db["counters"]
    _MG_CHATS = db["chats"]
    _MG_MESSAGES = db["messages"]
    _MG_TOKENS = db["google_tokens"]
    _MG_USERS.create_index("email", unique=True)
    _MG_CHATS.create_index([("user_id", 1), ("updated_at", -1)])
    _MG_MESSAGES.create_index([("chat_id", 1), ("_id", 1)])
    _MG_TOKENS.create_index("user_id", unique=True)
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


# ============================ per-user cloud data (Mongo only) ==============
# Chats, messages, and OAuth tokens live in MongoDB and are keyed by user_id
# from the JWT — never accept a user_id from the request body.

def _next(counter_name: str) -> int:
    _mg_init()
    from pymongo import ReturnDocument
    r = _MG_COUNTERS.find_one_and_update(
        {"_id": counter_name}, {"$inc": {"seq": 1}},
        upsert=True, return_document=ReturnDocument.AFTER,
    )
    return int(r["seq"])


def create_chat(user_id: int, title: str = "New chat") -> dict:
    _mg_init()
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    doc = {"_id": _next("chat_id"), "user_id": int(user_id),
           "title": title, "created_at": now, "updated_at": now}
    _MG_CHATS.insert_one(doc)
    return {"id": doc["_id"], "title": title, "user_id": int(user_id)}


def list_chats(user_id: int, limit: int = 50) -> list:
    _mg_init()
    return [
        {"id": int(c["_id"]), "title": c.get("title", "New chat")}
        for c in _MG_CHATS.find({"user_id": int(user_id)})
                          .sort("updated_at", -1).limit(limit)
    ]


def get_chat(user_id: int, chat_id: int) -> dict | None:
    _mg_init()
    c = _MG_CHATS.find_one({"_id": int(chat_id), "user_id": int(user_id)})
    if not c:
        return None
    msgs = list(_MG_MESSAGES.find({"chat_id": int(chat_id)}).sort("_id", 1))
    return {
        "id": int(c["_id"]),
        "title": c.get("title", "New chat"),
        "turns": [{"role": m["role"], "content": m["content"]} for m in msgs],
    }


def latest_chat(user_id: int) -> dict | None:
    _mg_init()
    c = _MG_CHATS.find_one({"user_id": int(user_id)}, sort=[("updated_at", -1)])
    if not c:
        return None
    return get_chat(user_id, int(c["_id"]))


def add_message(user_id: int, chat_id: int, role: str, content: str) -> None:
    _mg_init()
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    _MG_MESSAGES.insert_one({
        "_id": _next("msg_id"), "chat_id": int(chat_id),
        "user_id": int(user_id), "role": role, "content": content,
        "created_at": now,
    })
    # first user message becomes the title
    update = {"$set": {"updated_at": now}}
    if role == "user":
        chat = _MG_CHATS.find_one({"_id": int(chat_id)})
        if chat and (chat.get("title") in (None, "", "New chat")):
            update["$set"]["title"] = content[:42]
    _MG_CHATS.update_one({"_id": int(chat_id), "user_id": int(user_id)}, update)


# --- Google OAuth tokens (per user, one row per user_id) --------------------
def save_google_tokens(user_id: int, email: str, access_token: str,
                       refresh_token: str | None, expires_at) -> None:
    _mg_init()
    from datetime import datetime, timezone
    doc = {
        "user_id": int(user_id), "email": email,
        "access_token": access_token, "refresh_token": refresh_token,
        "expires_at": expires_at, "updated_at": datetime.now(timezone.utc),
    }
    _MG_TOKENS.update_one({"user_id": int(user_id)}, {"$set": doc}, upsert=True)


def get_google_tokens(user_id: int) -> dict | None:
    _mg_init()
    doc = _MG_TOKENS.find_one({"user_id": int(user_id)})
    if not doc:
        return None
    return {"email": doc.get("email"),
            "access_token": doc.get("access_token"),
            "refresh_token": doc.get("refresh_token"),
            "expires_at": doc.get("expires_at")}


def delete_google_tokens(user_id: int) -> None:
    _mg_init()
    _MG_TOKENS.delete_one({"user_id": int(user_id)})
