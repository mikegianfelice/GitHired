"""Configurable email delivery: Resend if keyed, else SMTP."""

from __future__ import annotations

import json
import smtplib
import ssl
from email.message import EmailMessage
from typing import Any

from jobseek.config_loader import Settings
from jobseek.http_client import RateLimitedClient


def send_digest_email(
    body_markdown: str,
    *,
    subject: str = "Daily job digest",
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or Settings.from_env()
    if settings.resend_api_key:
        return _send_resend(body_markdown, subject=subject, settings=settings)
    if settings.smtp_host:
        return _send_smtp(body_markdown, subject=subject, settings=settings)
    raise RuntimeError(
        "No email provider configured. Set RESEND_API_KEY or SMTP_HOST/SMTP_TO."
    )


def _send_smtp(body: str, *, subject: str, settings: Settings) -> dict[str, Any]:
    if not settings.smtp_to or not settings.smtp_from:
        raise RuntimeError("SMTP_FROM and SMTP_TO are required for SMTP delivery")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from
    msg["To"] = settings.smtp_to
    msg.set_content(body)
    if settings.smtp_use_tls:
        context = ssl.create_default_context()
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls(context=context)
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_pass)
            server.send_message(msg)
    else:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_pass)
            server.send_message(msg)
    return {"provider": "smtp", "to": settings.smtp_to, "ok": True}


def _send_resend(body: str, *, subject: str, settings: Settings) -> dict[str, Any]:
    to_addr = settings.resend_to or settings.smtp_to
    from_addr = settings.resend_from or settings.smtp_from
    if not to_addr or not from_addr:
        raise RuntimeError("RESEND_FROM/RESEND_TO (or SMTP_FROM/SMTP_TO) required")
    client = RateLimitedClient()
    try:
        # httpx post — use underlying client
        resp = client._client.post(  # noqa: SLF001 — intentional thin wrapper
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {settings.resend_api_key}",
                "Content-Type": "application/json",
            },
            content=json.dumps(
                {
                    "from": from_addr,
                    "to": [to_addr],
                    "subject": subject,
                    "text": body,
                }
            ),
        )
        if resp.status_code >= 300:
            raise RuntimeError(f"Resend HTTP {resp.status_code}: {resp.text[:300]}")
        return {"provider": "resend", "to": to_addr, "ok": True, "response": resp.json()}
    finally:
        client.close()
