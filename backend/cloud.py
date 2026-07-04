"""Cloud entrypoint (Render) — accounts, per-user chats, Google OAuth.

Runs on Render alongside the frontend. Auth uses JWTs from /api/auth/*.
Per-user chats + connectors live in MongoDB (keyed by user_id from the JWT).

Run:  uvicorn cloud:app --host 0.0.0.0 --port $PORT
Env:  JWT_SECRET, MONGODB_URI, GOOGLE_LOGIN_CLIENT_ID
      GOOGLE_WEB_CLIENT_ID, GOOGLE_WEB_CLIENT_SECRET, OAUTH_REDIRECT_URL
      OPENAI_API_KEY   (optional, for the chat brain — canned reply otherwise)
      FRONTEND_URL     (optional, where to send users after OAuth; default same origin)
"""

from __future__ import annotations

import os
import secrets
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from nova.auth import db
from nova.auth.routes import current_user
from nova.auth.routes import router as auth_router

app = FastAPI(title="Sarthi Cloud")

_origins = os.getenv("CORS_ORIGINS", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins.split(",")] if _origins != "*" else ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)


@app.get("/")
def health():
    return {
        "app": "sarthi-cloud",
        "ok": True,
        "accounts_backend": db.available(),
        "brain": "openai" if os.getenv("OPENAI_API_KEY") else "canned",
        "google_oauth": bool(os.getenv("GOOGLE_WEB_CLIENT_ID")),
    }


# --- helpers ----------------------------------------------------------------
def _uid(user: dict) -> int:
    """Extract numeric user id from the JWT payload."""
    return int(user.get("sub") or 0)


def _frontend_url() -> str:
    return (os.getenv("FRONTEND_URL", "").rstrip("/")
            or "https://sarthi-ai-frontend.onrender.com")


# --- chats & messages -------------------------------------------------------
class ChatIn(BaseModel):
    text: str
    session_id: Optional[int] = None
    speak: bool = False
    model: str = ""            # "provider:model" chosen in the chat box


@app.get("/api/session/current")
def session_current(user: dict = Depends(current_user)):
    """Most recent chat for this user, or an empty new one."""
    uid = _uid(user)
    if uid <= 0:
        return {"id": 0, "turns": []}
    latest = db.latest_chat(uid)
    if latest:
        return latest
    chat = db.create_chat(uid)
    return {"id": chat["id"], "title": chat["title"], "turns": []}


@app.get("/api/sessions")
def sessions_list(user: dict = Depends(current_user)):
    return {"sessions": db.list_chats(_uid(user))}


@app.post("/api/session/new")
def session_new(user: dict = Depends(current_user)):
    chat = db.create_chat(_uid(user))
    return {"id": chat["id"], "title": chat["title"]}


@app.get("/api/session/{sid}")
def session_get(sid: int, user: dict = Depends(current_user)):
    chat = db.get_chat(_uid(user), sid)
    if chat is None:
        raise HTTPException(404, "Chat not found")
    return chat


def _brain_reply(uid: int, history: list, text: str, model_sel: str) -> str:
    """Reply using the user's OWN saved API key for the selected provider.

    `model_sel` is "provider:model" (e.g. "openai:gpt-4o") or just "provider".
    Falls back to whichever provider the user has a key for; if none, a message
    telling them to add a key in Settings.
    """
    from nova.brain.providers import build_chat_client

    provider, _, model = (model_sel or "").partition(":")
    provider = provider.strip().lower()

    saved = db.list_api_keys(uid)               # [{provider, model}]
    have = {k["provider"] for k in saved}
    if not have:
        return ("No AI model connected yet. Go to Settings -> AI Models, paste an "
                "API key for ChatGPT / Claude / Gemini / Grok / Groq, then pick it "
                "in the chat box.")
    if provider not in have:                    # pick a sane default
        provider = next(iter(have))
        model = ""

    keyrow = db.get_api_key(uid, provider)
    if not keyrow or not keyrow.get("api_key"):
        return f"No saved key for {provider}. Add one in Settings -> AI Models."
    model = model or keyrow.get("model") or ""

    client = build_chat_client(provider, model, keyrow["api_key"])
    if client is None:
        return f"Unsupported provider: {provider}"

    messages = [{"role": "system", "content": "You are Sarthi, a helpful assistant."}]
    for m in (history or [])[-12:]:
        messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": text})
    out = client.chat_text(messages)
    return out or f"(no reply from {provider} — check your key/model in Settings)"


@app.post("/api/chat")
def chat_send(body: ChatIn, user: dict = Depends(current_user)):
    uid = _uid(user)
    sid = body.session_id
    if not sid:
        sid = db.create_chat(uid)["id"]
    else:
        if db.get_chat(uid, int(sid)) is None:
            raise HTTPException(404, "Chat not found")
    db.add_message(uid, int(sid), "user", body.text)
    history = db.get_chat(uid, int(sid))["turns"]
    reply = _brain_reply(uid, history, body.text, body.model or "")
    db.add_message(uid, int(sid), "assistant", reply)
    return {"session_id": int(sid), "replies": [reply], "pending": None}


# --- per-user AI model keys -------------------------------------------------
class KeyIn(BaseModel):
    provider: str
    api_key: str
    model: str = ""


@app.get("/api/keys")
def keys_list(user: dict = Depends(current_user)):
    """Which providers the user has a key for (never returns the key value)."""
    from nova.brain.providers import PROVIDER_LABELS
    saved = db.list_api_keys(_uid(user))
    return {
        "providers": [
            {"provider": k["provider"],
             "label": PROVIDER_LABELS.get(k["provider"], k["provider"]),
             "model": k.get("model", "")}
            for k in saved
        ]
    }


@app.post("/api/keys")
def keys_save(body: KeyIn, user: dict = Depends(current_user)):
    from nova.brain.providers import PROVIDER_MODELS
    prov = body.provider.strip().lower()
    if prov not in PROVIDER_MODELS:
        raise HTTPException(400, f"Unknown provider '{body.provider}'")
    if not body.api_key.strip():
        raise HTTPException(400, "API key is empty")
    db.save_api_key(_uid(user), prov, body.api_key.strip(), body.model.strip())
    return {"ok": True, "provider": prov}


@app.delete("/api/keys/{provider}")
def keys_delete(provider: str, user: dict = Depends(current_user)):
    db.delete_api_key(_uid(user), provider.strip().lower())
    return {"ok": True}


@app.get("/api/models")
def models_available(user: dict = Depends(current_user)):
    """Models for the chat-box dropdown — ONLY providers the user has a key for."""
    from nova.brain.providers import PROVIDER_LABELS, PROVIDER_MODELS
    saved = {k["provider"] for k in db.list_api_keys(_uid(user))}
    groups = []
    for prov in saved:
        models = PROVIDER_MODELS.get(prov, [])
        groups.append({
            "provider": prov,
            "label": PROVIDER_LABELS.get(prov, prov),
            "models": [{"id": f"{prov}:{m}", "name": m} for m in models],
        })
    return {"groups": groups}


# --- settings (per-user) ----------------------------------------------------
@app.get("/api/settings")
def settings_get(user: dict = Depends(current_user)):
    tokens = db.get_google_tokens(_uid(user))
    return {
        "mode": "automation" if tokens else "pc_control",
        "connectors": {"google": {
            "connected": bool(tokens),
            "email": tokens.get("email") if tokens else None,
        }},
        "google_ready": bool(os.getenv("GOOGLE_WEB_CLIENT_ID")),
    }


class ModeIn(BaseModel):
    mode: str


@app.post("/api/settings")
def settings_set(body: ModeIn, user: dict = Depends(current_user)):
    # cloud mode is derived from whether Google is connected; nothing to store
    return {"ok": True, "mode": body.mode}


# --- Google OAuth (Web flow, per-user tokens in Mongo) ----------------------
# One-time state cache so the OAuth callback can verify the request originated
# from us. Small and in-memory — sessions here are short-lived anyway.
_OAUTH_STATE: dict[str, dict] = {}

GOOGLE_SCOPES = " ".join([
    "openid", "email", "profile",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/contacts.readonly",
])


def _oauth_redirect_url(request_origin: Optional[str] = None) -> str:
    """Where Google should send the user back to after consent."""
    override = os.getenv("OAUTH_REDIRECT_URL")
    if override:
        return override
    # default to this backend's own callback
    base = (request_origin or "").rstrip("/") or "https://sarthi-ai-pudg.onrender.com"
    return f"{base}/api/oauth/google/callback"


@app.post("/api/connectors/google/connect")
def google_connect_start(user: dict = Depends(current_user)):
    """Return the Google consent URL — frontend redirects the browser to it."""
    cid = os.getenv("GOOGLE_WEB_CLIENT_ID", "").strip()
    if not cid or not os.getenv("GOOGLE_WEB_CLIENT_SECRET", "").strip():
        return {"error": "setup_needed"}
    state = secrets.token_urlsafe(24)
    _OAUTH_STATE[state] = {"user_id": _uid(user), "at": time.time()}
    # prune old state entries (>5 min)
    cutoff = time.time() - 300
    for s in list(_OAUTH_STATE):
        if _OAUTH_STATE[s]["at"] < cutoff:
            _OAUTH_STATE.pop(s, None)
    params = {
        "client_id": cid,
        "redirect_uri": _oauth_redirect_url(),
        "response_type": "code",
        "scope": GOOGLE_SCOPES,
        "access_type": "offline",           # get a refresh token
        "prompt": "consent",                # always ask (so we always get refresh_token)
        "include_granted_scopes": "true",
        "state": state,
    }
    return {"auth_url": "https://accounts.google.com/o/oauth2/v2/auth?"
                        + urllib.parse.urlencode(params)}


@app.get("/api/oauth/google/callback")
def google_oauth_callback(code: str = Query(""), state: str = Query("")):
    """Google redirects the user's browser here with an auth code."""
    entry = _OAUTH_STATE.pop(state, None)
    if not entry:
        raise HTTPException(400, "OAuth state expired — try connecting again.")
    if not code:
        raise HTTPException(400, "Missing OAuth code.")
    cid = os.getenv("GOOGLE_WEB_CLIENT_ID", "").strip()
    csec = os.getenv("GOOGLE_WEB_CLIENT_SECRET", "").strip()

    import requests
    try:
        r = requests.post("https://oauth2.googleapis.com/token", data={
            "code": code, "client_id": cid, "client_secret": csec,
            "redirect_uri": _oauth_redirect_url(),
            "grant_type": "authorization_code",
        }, timeout=30)
        r.raise_for_status()
        tok = r.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Google token exchange failed: {e}")

    # look up the email using the access token
    email = ""
    try:
        u = requests.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {tok['access_token']}"}, timeout=15,
        )
        if u.ok:
            email = (u.json() or {}).get("email") or ""
    except Exception:
        pass

    expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=int(tok.get("expires_in", 3600))
    )
    db.save_google_tokens(
        entry["user_id"], email,
        tok["access_token"], tok.get("refresh_token"), expires_at,
    )
    # send the browser back to the frontend with a hint
    return RedirectResponse(f"{_frontend_url()}/?connected=google")


@app.post("/api/connectors/google/disconnect")
def google_disconnect(user: dict = Depends(current_user)):
    db.delete_google_tokens(_uid(user))
    return {"ok": True}
