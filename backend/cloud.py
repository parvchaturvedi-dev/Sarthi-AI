"""Cloud entrypoint (Render) — the ACCOUNTS API only.

The full Sarthi backend drives a Windows PC (pyautogui, Ollama, mic, screen OCR)
and cannot run on a Linux server. This slim app exposes just the auth endpoints
so a deployed frontend can sign users in and gets a real HTTPS origin for Google
Sign-In. PC control / voice / vision / local models stay on the user's own PC.

Run:  uvicorn cloud:app --host 0.0.0.0 --port $PORT
Env:  JWT_SECRET, ORDS_BASE_URL (apex), GOOGLE_LOGIN_CLIENT_ID
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from nova.auth.routes import router as auth_router

app = FastAPI(title="Sarthi Auth")

# Auth is via the Authorization header (no cookies), so "*" is safe. Lock this
# to your frontend URL later if you like.
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
    from nova.auth import db
    return {"app": "sarthi-auth", "ok": True, "accounts_backend": db.available()}


# --- Portal stubs -----------------------------------------------------------
# The deployed web frontend is the full chat dashboard, but the real assistant
# (chat, PC control, vision, local models) runs on the user's OWN machine — it
# can't run on this Linux server. Without these the dashboard 404s on load and
# (by its own error handling) logs the user straight back out. So we answer the
# few endpoints it hits with empty/portal responses: login works, the dashboard
# loads, and chat explains where the assistant actually lives.

_PORTAL_MSG = (
    "You're signed in. Sarthi's assistant runs on your own PC (the desktop app) "
    "or your phone — this website is just the account portal. Open the app there "
    "to chat and control your device."
)


class _ChatIn(BaseModel):
    text: str = ""
    session_id: int | None = None


@app.get("/api/session/current")
def _session_current():
    return {"id": 0, "turns": []}


@app.get("/api/sessions")
def _sessions():
    return {"sessions": []}


@app.post("/api/session/new")
def _session_new():
    return {"id": 0}


@app.get("/api/session/{sid}")
def _session_get(sid: int):
    return {"id": sid, "turns": []}


@app.post("/api/chat")
def _chat(body: _ChatIn):
    return {"session_id": 0, "replies": [_PORTAL_MSG], "pending": None}


@app.get("/api/settings")
def _settings():
    return {"mode": "pc_control", "connectors": {"google": {"connected": False}},
            "google_ready": False}


@app.post("/api/settings")
def _settings_set(body: dict | None = None):
    return {"ok": True}


@app.post("/api/connectors/google/connect")
def _google_connect():
    return {"error": "setup_needed"}
