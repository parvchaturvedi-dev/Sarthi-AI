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
