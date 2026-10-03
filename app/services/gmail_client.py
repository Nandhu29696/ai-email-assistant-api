"""Shared Gmail API client construction with token refresh + persistence."""
from __future__ import annotations

from datetime import timezone

from loguru import logger

from app.config import settings
from app.database import SessionLocal
from app.models.email import EmailIntegration
from app.utils.crypto import decrypt_token, encrypt_token

GMAIL_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]


class GmailAuthError(RuntimeError):
    """Raised when an integration's Gmail credentials cannot be used."""


def _mark_health(integration_id: int, status: str, message: str) -> None:
    db = SessionLocal()
    try:
        row = db.query(EmailIntegration).filter(EmailIntegration.id == integration_id).first()
        if row:
            previous = row.health_status
            row.health_status = status
            row.health_message = message[:1000]
            db.commit()
            from app.services.ops_alert import mailbox_health_changed
            mailbox_health_changed(row.email_address, previous, status, message)
    except Exception as exc:
        logger.warning(f"[gmail_client] Failed to update health for {integration_id}: {exc}")
        db.rollback()
    finally:
        db.close()


def build_gmail_service(integration_id: int):
    """Return an authenticated Gmail service for an active Gmail integration.

    Refreshes the access token when it is expired (or its expiry is unknown)
    and persists the new token + expiry. Blocking — call via ``asyncio.to_thread``
    from async code.
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    db = SessionLocal()
    try:
        integration = (
            db.query(EmailIntegration)
            .filter(
                EmailIntegration.id == integration_id,
                EmailIntegration.is_active == True,
                EmailIntegration.provider == "gmail",
            )
            .first()
        )
        if integration is None or not integration.access_token:
            raise GmailAuthError("Gmail integration not found or not connected")
        access_token = decrypt_token(integration.access_token)
        refresh_token = decrypt_token(integration.refresh_token)
        expiry = integration.token_expiry
    finally:
        db.close()

    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GMAIL_CLIENT_ID,
        client_secret=settings.GMAIL_CLIENT_SECRET,
        scopes=GMAIL_SCOPES,
    )
    if expiry is not None:
        # google-auth compares against a naive UTC datetime.
        creds.expiry = expiry.astimezone(timezone.utc).replace(tzinfo=None)

    if (expiry is None or creds.expired) and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as exc:
            _mark_health(integration_id, "error", f"Token refresh failed: {exc}")
            raise GmailAuthError(f"Token refresh failed: {exc}") from exc

        db = SessionLocal()
        try:
            row = db.query(EmailIntegration).filter(EmailIntegration.id == integration_id).first()
            if row:
                row.access_token = encrypt_token(creds.token)
                if creds.expiry:
                    row.token_expiry = creds.expiry.replace(tzinfo=timezone.utc)
                db.commit()
        finally:
            db.close()

    try:
        return build("gmail", "v1", credentials=creds, cache_discovery=False)
    except Exception as exc:
        _mark_health(integration_id, "error", f"Gmail service creation failed: {exc}")
        raise GmailAuthError(f"Gmail service creation failed: {exc}") from exc


def format_message_id(message_id: str | None) -> str | None:
    """Return an RFC 5322 msg-id (``<id@host>``) or None when the value isn't one."""
    if not message_id:
        return None
    value = message_id.strip().strip("<>").strip()
    if "@" not in value:
        return None  # e.g. a Gmail API id — not usable for threading headers
    return f"<{value}>"


def classify_gmail_http_error(exc) -> str:
    """Map a googleapiclient HttpError to a stable error code."""
    text = str(exc)
    status = getattr(getattr(exc, "resp", None), "status", None)
    if status == 429 or "rateLimitExceeded" in text or "userRateLimitExceeded" in text:
        return "rate_limit_exceeded"
    if "dailyLimitExceeded" in text or "quotaExceeded" in text:
        return "rate_limit_exceeded"
    if status == 403 and ("insufficientPermissions" in text or "insufficient authentication scopes" in text.lower()):
        return "invalid_scope"
    if status == 401:
        return "auth_failed"
    return text
