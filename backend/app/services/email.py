"""Outbound email.

When SMTP isn't configured (`Settings.smtp_enabled` False — the local dev
default), an email is logged instead of sent, so alert code paths and the
worker are fully exercisable without any mail setup. In staging/production,
set `SMTP_HOST` (+ credentials) and real mail goes out.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from app.config import get_settings
from app.logging import get_logger

log = get_logger(__name__)


def send_email(to: str, subject: str, text_body: str, html_body: str | None = None) -> None:
    settings = get_settings()

    if not settings.smtp_enabled:
        log.info("email.logged_not_sent", to=to, subject=subject)
        return

    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text_body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            smtp.starttls()
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(msg)
        log.info("email.sent", to=to, subject=subject)
    except (OSError, smtplib.SMTPException) as exc:
        # A mail-server hiccup should not crash the worker run that triggered
        # it — the caller logs the failed delivery and moves on.
        log.error("email.send_failed", to=to, subject=subject, error=repr(exc))
        raise
