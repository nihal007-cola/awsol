"""SMTP mailer for awsol.

Reads SMTP config from the Settings object and sends plain emails.
Used by the password-reset flow.
"""
import logging
import smtplib
from email.message import EmailMessage

from .config import settings

logger = logging.getLogger("erp.mailer")


def send_email(to_email: str, subject: str, body: str) -> bool:
    """Send a plaintext email. Returns True on success, False on failure."""
    if not settings.smtp_user or not settings.smtp_pass:
        logger.error("SMTP not configured; refusing to send email")
        return False

    msg = EmailMessage()
    msg["From"] = settings.smtp_from or settings.smtp_user
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            smtp.starttls()
            smtp.login(settings.smtp_user, settings.smtp_pass)
            smtp.send_message(msg)
        logger.info("Email sent to %s: %s", to_email, subject)
        return True
    except Exception as e:
        logger.exception("Failed to send email to %s: %s", to_email, e)
        return False
