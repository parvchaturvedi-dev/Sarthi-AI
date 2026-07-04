"""Auth API — register / login / Google sign-in, backed by Oracle PL/SQL.

Passwords are hashed with bcrypt in Python; the hash is stored in Oracle. On
success the client gets a JWT it sends as `Authorization: Bearer <token>`.
"""

from __future__ import annotations

import os
import time

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from . import db

router = APIRouter(prefix="/api/auth")


def _secret() -> str:
    return os.getenv("JWT_SECRET", "dev-secret-change-me")


class RegisterIn(BaseModel):
    email: str
    name: str
    password: str


class LoginIn(BaseModel):
    email: str
    password: str


class GoogleIn(BaseModel):
    credential: str            # Google ID token from the Sign-in button


def _issue(user: dict) -> dict:
    import jwt

    payload = {
        "sub": user["id"], "email": user["email"], "name": user.get("name"),
        "exp": int(time.time()) + 7 * 86400,
    }
    token = jwt.encode(payload, _secret(), algorithm="HS256")
    return {"token": token, "user": {"id": user["id"], "email": user["email"], "name": user.get("name")}}


def _ensure_oracle():
    if not db.available():
        raise HTTPException(503, "Oracle is not configured. Set ORACLE_* in backend/.env")


@router.post("/register")
def register(body: RegisterIn):
    _ensure_oracle()
    import bcrypt

    pw_hash = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode()
    try:
        if db.get_user(body.email):
            raise HTTPException(400, "That email is already registered")
        uid = db.register_user(body.email, body.name, pw_hash, "local")
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Accounts backend error: {e}")
    return _issue({"id": uid, "email": body.email.lower(), "name": body.name})


@router.post("/guest")
def guest():
    """No-password guest session — try the app without an account. Real accounts
    use /register or /login. (Replaces the old hardcoded dev credentials.)"""
    return _issue({"id": 0, "email": "guest@local", "name": "Guest"})


@router.post("/login")
def login(body: LoginIn):
    _ensure_oracle()
    import bcrypt

    try:
        u = db.get_user(body.email)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Accounts backend error: {e}")
    if not u or not u.get("password_hash") or not bcrypt.checkpw(
        body.password.encode(), u["password_hash"].encode()
    ):
        raise HTTPException(401, "Invalid email or password")
    return _issue(u)


@router.post("/google")
def google(body: GoogleIn):
    _ensure_oracle()
    from google.auth.transport import requests as greq
    from google.oauth2 import id_token as gidt

    client_id = os.getenv("GOOGLE_LOGIN_CLIENT_ID") or os.getenv("GOOGLE_CLIENT_ID")
    try:
        # clock_skew tolerance so a few seconds of clock drift doesn't reject the token
        info = gidt.verify_oauth2_token(
            body.credential, greq.Request(), client_id, clock_skew_in_seconds=30
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(401, f"Google sign-in failed: {e}")
    email = info.get("email")
    if not email:
        raise HTTPException(401, "Google account has no email")
    try:
        uid = db.upsert_google(email, info.get("name", ""))
    except Exception as e:  # noqa: BLE001 - surface the real accounts-backend error
        raise HTTPException(502, f"Accounts backend error: {e}")
    return _issue({"id": uid, "email": email.lower(), "name": info.get("name", "")})


def current_user(authorization: str = Header(default="")) -> dict:
    import jwt

    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Not signed in")
    try:
        return jwt.decode(authorization[7:], _secret(), algorithms=["HS256"])
    except Exception:
        raise HTTPException(401, "Session expired, sign in again")


@router.get("/me")
def me(user: dict = Depends(current_user)):
    return {"user": user}
