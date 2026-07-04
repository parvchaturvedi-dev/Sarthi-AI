"""Gmail connector — send mail directly via SMTP, no browser theater.

Uses a Gmail App Password (created under Google Account -> Security -> App
passwords). This is the "connect once, then Nova sends in the background"
behaviour: when Automation is on and Gmail is connected, Nova mails through
here instead of driving the Gmail UI with the vision loop.
"""

from __future__ import annotations

import smtplib
from email.mime.text import MIMEText


def send_email(email: str, app_password: str, to: str, subject: str, body: str) -> None:
    msg = MIMEText(body, _charset="utf-8")
    msg["Subject"] = subject or "(no subject)"
    msg["From"] = email
    msg["To"] = to
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as s:
        s.login(email, (app_password or "").replace(" ", ""))
        s.sendmail(email, [to], msg.as_string())
