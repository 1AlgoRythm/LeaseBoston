"""Deliver a message on the channel the person chose, and record it in the outbox.

Channels:
  email      real email if SMTP_* settings are present, otherwise simulated
  sms        simulated (plug a provider in here)
  app  simulated push notification (plug the app's push service in here)
  chat_only  nothing is sent; the renter checks back in the chat

Simulated means the message is written to the outbox table and shown at
/outbox, exactly as it would have been sent. Addresses at example.com are
never really sent, because that domain is reserved and cannot receive mail.

Real email settings (environment variables):
  SMTP_HOST, SMTP_PORT (default 587), SMTP_USER, SMTP_PASSWORD, SMTP_FROM
"""

import os
import smtplib
from email.message import EmailMessage

from .db import now

CHANNELS = ("email", "sms", "app", "chat_only")


def send(conn, *, channel: str, recipient: str, subject: str, body: str, question_ref: str | None) -> str:
    """Returns the outbox status: 'sent', 'simulated' or 'failed'."""
    if channel == "chat_only":
        return "not_sent"
    status, detail = "simulated", None
    if channel == "email" and os.environ.get("SMTP_HOST") and not recipient.lower().endswith("example.com"):
        try:
            _smtp(recipient, subject, body)
            status = "sent"
        except Exception as e:  # keep the queue working even if email is down
            status, detail = "failed", f"{type(e).__name__}: {e}"
    conn.execute(
        "INSERT INTO outbox (question_ref, channel, recipient, subject, body, status, detail, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (question_ref, channel, recipient, subject, body, status, detail, now()),
    )
    return status


def _smtp(to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = os.environ.get("SMTP_FROM", os.environ.get("SMTP_USER", "leaseboston-demo@localhost"))
    msg["To"], msg["Subject"] = to, subject
    msg.set_content(body)
    with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587")), timeout=10) as s:
        if os.environ.get("SMTP_USER"):
            s.starttls()
            s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        s.send_message(msg)
