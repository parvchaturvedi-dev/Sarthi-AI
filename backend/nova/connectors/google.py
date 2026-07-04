"""Unified Google connector — Gmail, Calendar, Drive, Contacts via one OAuth.

Same login/credentials as Gmail; we just request the extra scopes so one Google
sign-in connects all four. The account token lives in google_tokens/<email>.json.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path

import os

# tolerate Google returning scopes in a different order / adding openid
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",   # to read the account email
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/contacts.readonly",
]
CRED_FILE = "nova_gmail_credentials.json"
TOKEN_DIR = "google_tokens"


def has_credentials(cred_file: str = CRED_FILE) -> bool:
    return Path(cred_file).exists()


def connect(cred_file: str = CRED_FILE, token_dir: str = TOKEN_DIR) -> str:
    """Google login granting all scopes. Returns the account email."""
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    flow = InstalledAppFlow.from_client_secrets_file(cred_file, SCOPES)
    creds = flow.run_local_server(
        port=0, access_type="offline", prompt="consent", open_browser=True,
        authorization_prompt_message="",
        success_message="Nova connected to Google — you can close this tab.",
    )
    # userinfo works with the userinfo.email scope (gmail.send can't read the profile)
    info = build("oauth2", "v2", credentials=creds).userinfo().get().execute()
    email = info.get("email")
    Path(token_dir).mkdir(exist_ok=True)
    (Path(token_dir) / f"{email}.json").write_text(creds.to_json(), encoding="utf-8")
    return email


def _creds(email: str, token_dir: str = TOKEN_DIR):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    p = Path(token_dir) / f"{email}.json"
    if not p.exists():
        return None
    creds = Credentials.from_authorized_user_file(str(p), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        p.write_text(creds.to_json(), encoding="utf-8")
    return creds


def _svc(email: str, api: str, ver: str):
    from googleapiclient.discovery import build

    creds = _creds(email)
    if not creds:
        raise RuntimeError("Google account not connected")
    return build(api, ver, credentials=creds, cache_discovery=False)


# --- Gmail ------------------------------------------------------------------
def gmail_send(email: str, to: str, subject: str, body: str) -> None:
    svc = _svc(email, "gmail", "v1")
    msg = MIMEText(body, _charset="utf-8")
    msg["To"] = to
    msg["From"] = email
    msg["Subject"] = subject or "(no subject)"
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    svc.users().messages().send(userId="me", body={"raw": raw}).execute()


# --- Contacts (resolve a name to an email) ----------------------------------
def contacts_email(email: str, name: str) -> str | None:
    svc = _svc(email, "people", "v1")
    name_l = (name or "").lower().strip()
    try:                                    # warm the search cache, then query
        svc.people().searchContacts(query="", readMask="names,emailAddresses").execute()
        res = svc.people().searchContacts(query=name, readMask="names,emailAddresses").execute()
        for r in res.get("results", []):
            emails = r.get("person", {}).get("emailAddresses", [])
            if emails:
                return emails[0].get("value")
    except Exception:
        pass
    # fallback: scan connections
    res = svc.people().connections().list(
        resourceName="people/me", personFields="names,emailAddresses", pageSize=500
    ).execute()
    for p in res.get("connections", []):
        names = " ".join(n.get("displayName", "") for n in p.get("names", [])).lower()
        emails = p.get("emailAddresses", [])
        if name_l in names and emails:
            return emails[0].get("value")
    return None


# --- Calendar ---------------------------------------------------------------
def calendar_upcoming(email: str, max_results: int = 6):
    svc = _svc(email, "calendar", "v3")
    now = datetime.now(timezone.utc).isoformat()
    res = svc.events().list(calendarId="primary", timeMin=now, maxResults=max_results,
                            singleEvents=True, orderBy="startTime").execute()
    out = []
    for e in res.get("items", []):
        start = e.get("start", {}).get("dateTime") or e.get("start", {}).get("date")
        out.append((e.get("summary", "(no title)"), start))
    return out


def calendar_add(email: str, title: str, start_iso: str, end_iso: str | None = None) -> None:
    svc = _svc(email, "calendar", "v3")
    ev = {"summary": title, "start": {"dateTime": start_iso}, "end": {"dateTime": end_iso or start_iso}}
    svc.events().insert(calendarId="primary", body=ev).execute()


# --- Drive ------------------------------------------------------------------
def drive_search(email: str, query: str, max_results: int = 10):
    svc = _svc(email, "drive", "v3")
    q = query.replace("'", "\\'")
    res = svc.files().list(q=f"name contains '{q}' and trashed=false", pageSize=max_results,
                           fields="files(name,webViewLink)").execute()
    return [(f["name"], f.get("webViewLink", "")) for f in res.get("files", [])]
