"""Email via Gmail SMTP (port 587, STARTTLS, app password). Spec §3, "Alerts by email only".

With EMAIL_DRY_RUN=1 (the default) messages are written to data/outbox/ as .eml files
instead, which you can open in any mail client. Tests always use dry run.
"""

import re
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path

from tracker.core.settings import Settings
from tracker.core.timeutil import now_utc, to_dhaka


@dataclass(frozen=True)
class Email:
    subject: str
    text: str
    html: str | None = None


def build_message(email: Email, sender: str, to: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = email.subject
    msg["From"] = sender
    msg["To"] = to
    msg.set_content(email.text)
    if email.html:
        msg.add_alternative(email.html, subtype="html")
    return msg


def send(email: Email, settings: Settings) -> Path | None:
    """Send `email`, or write it to the outbox in dry-run mode (returns the file path then)."""
    sender = settings.smtp_user or "tracker@localhost"
    msg = build_message(email, sender=sender, to=settings.alert_to or sender)

    if settings.email_dry_run:
        outbox = settings.data_dir / "outbox"
        outbox.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^A-Za-z0-9]+", "-", email.subject).strip("-")[:60]
        path = outbox / f"{to_dhaka(now_utc()):%Y%m%d_%H%M%S}_{slug}.eml"
        path.write_bytes(bytes(msg))
        return path

    if not (settings.smtp_user and settings.smtp_app_password and settings.alert_to):
        raise RuntimeError("SMTP_USER, SMTP_APP_PASSWORD and ALERT_TO must be set to send email")
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(settings.smtp_user, settings.smtp_app_password)
        smtp.send_message(msg)
    return None
