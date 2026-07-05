"""Email delivery — SMTP if configured, console fallback for dev."""
import logging
import os

log = logging.getLogger(__name__)

_FROM = os.getenv("SMTP_FROM", "noreply@axon.app")
_APP_URL = os.getenv("APP_URL", "http://localhost:3000")


async def send_email(to: str, subject: str, html: str) -> None:
    smtp_host = os.getenv("SMTP_HOST")
    if not smtp_host:
        log.info("[EMAIL] to=%s subject=%s\n%s", to, subject, html)
        return
    try:
        import aiosmtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = _FROM
        msg["To"] = to
        msg.attach(MIMEText(html, "html"))

        await aiosmtplib.send(
            msg,
            hostname=smtp_host,
            port=int(os.getenv("SMTP_PORT", "587")),
            username=os.getenv("SMTP_USER"),
            password=os.getenv("SMTP_PASS"),
            start_tls=True,
        )
    except Exception:
        log.exception("Failed to send email to %s", to)


async def send_verification_email(to: str, token: str) -> None:
    url = f"{_APP_URL}/verify-email?token={token}"
    await send_email(
        to,
        "Verify your Axon account",
        f"""
        <p>Welcome to Axon! Click the link below to verify your email address:</p>
        <p><a href="{url}">{url}</a></p>
        <p>This link expires in 24 hours.</p>
        """,
    )


async def send_password_reset_email(to: str, token: str) -> None:
    url = f"{_APP_URL}/reset-password?token={token}"
    await send_email(
        to,
        "Reset your Axon password",
        f"""
        <p>You requested a password reset. Click the link below:</p>
        <p><a href="{url}">{url}</a></p>
        <p>This link expires in 1 hour. If you didn't request this, ignore this email.</p>
        """,
    )
