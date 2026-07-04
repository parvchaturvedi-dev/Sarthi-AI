"""Gmail connector via Google OAuth — "click Add, log in, done" (like Claude).

One-time developer setup: create an OAuth client (Desktop app) in Google Cloud,
enable the Gmail API, download the client JSON and save it as
`nova_gmail_credentials.json` in the project root. After that, connecting an
account is just the Google login flow, and Nova sends mail via the Gmail API —
no app passwords, no UI theater.
"""

from __future__ import annotations

import base64
from email.mime.text import MIMEText
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
CRED_FILE = "nova_gmail_credentials.json"     # the OAuth client (user provides once)
TOKEN_DIR = "gmail_tokens"                    # per-account tokens, after login


def has_credentials(cred_file: str = CRED_FILE) -> bool:
    return Path(cred_file).exists()


def connect(cred_file: str = CRED_FILE, token_dir: str = TOKEN_DIR) -> str:
    """Run the Google login flow (opens the account chooser). Returns the email."""
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    flow = InstalledAppFlow.from_client_secrets_file(cred_file, SCOPES)
    creds = flow.run_local_server(
        port=0, access_type="offline", prompt="consent", open_browser=True,
        authorization_prompt_message="", success_message="Nova se Gmail connect ho gaya — ye tab band kar sakte ho.",
    )
    service = build("gmail", "v1", credentials=creds)
    email = service.users().getProfile(userId="me").execute().get("emailAddress")
    Path(token_dir).mkdir(exist_ok=True)
    (Path(token_dir) / f"{email}.json").write_text(creds.to_json(), encoding="utf-8")
    return email


def _load(email: str, token_dir: str = TOKEN_DIR):
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


def send(email: str, to: str, subject: str, body: str, token_dir: str = TOKEN_DIR) -> None:
    from googleapiclient.discovery import build

    creds = _load(email, token_dir)
    if not creds:
        raise RuntimeError("Gmail account connected nahi hai")
    service = build("gmail", "v1", credentials=creds)
    msg = MIMEText(body, _charset="utf-8")
    msg["To"] = to
    msg["From"] = email
    msg["Subject"] = subject or "(no subject)"
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()
