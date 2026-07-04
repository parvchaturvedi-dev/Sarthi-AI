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
from typing import Optional


def _mode() -> Optional[str]:
    if os.getenv("ORDS_BASE_URL"):
        return "ords"
    if os.getenv("ORACLE_DSN"):
        return "oracle"
    return None


def available() -> bool:
    return _mode() is not None


# ============================ ORDS (apex.oracle.com) ========================
def _base() -> str:
    return os.getenv("ORDS_BASE_URL", "").rstrip("/")


def _ords_register(email, name, pw_hash, provider):
    import requests

    r = requests.post(f"{_base()}/register",
                      json={"email": email, "name": name, "hash": pw_hash, "provider": provider},
                      timeout=25)
    r.raise_for_status()
    uid = r.json().get("id")
    if uid in (-1, "-1"):
        raise ValueError("That email is already registered")
    return int(uid)


def _ords_get_user(email):
    import requests

    r = requests.get(f"{_base()}/user", params={"email": email}, timeout=25)
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
    import requests

    r = requests.post(f"{_base()}/google", json={"email": email, "name": name}, timeout=25)
    r.raise_for_status()
    return int(r.json().get("id"))


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
def register_user(email: str, name: str, pw_hash: str, provider: str = "local") -> int:
    return (_ords_register if _mode() == "ords" else _ora_register)(email, name, pw_hash, provider)


def get_user(email: str) -> Optional[dict]:
    return (_ords_get_user if _mode() == "ords" else _ora_get_user)(email)


def upsert_google(email: str, name: str) -> int:
    return (_ords_upsert_google if _mode() == "ords" else _ora_upsert_google)(email, name)
