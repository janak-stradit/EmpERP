import logging
import smtplib
from email.message import EmailMessage

from app.core.config import get_settings

logger = logging.getLogger("app.email")
settings = get_settings()


def send_email(to: str, subject: str, body: str, html_body: str | None = None) -> None:
    """Sends a plain-text email, or a multipart plain-text + HTML email when html_body
    is given (mail clients that render HTML show that; everything else falls back to body)."""
    if settings.email_backend == "smtp":
        _send_via_smtp(to, subject, body, html_body)
    else:
        logger.info("EMAIL (console backend) to=%s subject=%r body=%r html=%s", to, subject, body, bool(html_body))


def _send_via_smtp(to: str, subject: str, body: str, html_body: str | None) -> None:
    message = EmailMessage()
    message["From"] = settings.smtp_from_address
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    if html_body:
        message.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        server.starttls()
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(message)
