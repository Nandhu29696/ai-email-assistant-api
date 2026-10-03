"""Microsoft Graph token management (refresh + persistence) for Outlook integrations."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
from loguru import logger

from app.config import settings
from app.database import SessionLocal
from app.models.email import EmailIntegration
from app.utils.crypto import decrypt_token, encrypt_token

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
OUTLOOK_SCOPES = ["Mail.Read", "Mail.ReadWrite", "Mail.Send", "User.Read"]


class OutlookAuthError(RuntimeError):
    pass


def refresh_outlook_token(integration_id: int) -> str:
    """Exchange the stored refresh token for a new access token and persist it."""
    import msal

    db = SessionLocal()
    try:
        integration = db.query(EmailIntegration).filter(EmailIntegration.id == integration_id).first()
        if not integration or not integration.refresh_token:
            raise OutlookAuthError("Outlook integration has no refresh token; reconnect the mailbox")
        refresh_token = decrypt_token(integration.refresh_token)

        app = msal.ConfidentialClientApplication(
            settings.OUTLOOK_CLIENT_ID,
            authority=f"https://login.microsoftonline.com/{settings.OUTLOOK_TENANT_ID}",
            client_credential=settings.OUTLOOK_CLIENT_SECRET,
        )
        result = app.acquire_token_by_refresh_token(refresh_token, scopes=OUTLOOK_SCOPES)
        if "access_token" not in result:
            previous = integration.health_status
            integration.health_status = "error"
            integration.health_message = f"Token refresh failed: {result.get('error_description', 'unknown error')}"[:1000]
            db.commit()
            from app.services.ops_alert import mailbox_health_changed
            mailbox_health_changed(integration.email_address, previous, "error", integration.health_message)
            raise OutlookAuthError(integration.health_message)

        integration.access_token = encrypt_token(result["access_token"])
        if result.get("refresh_token"):
            integration.refresh_token = encrypt_token(result["refresh_token"])
        if result.get("expires_in"):
            integration.token_expiry = datetime.now(timezone.utc) + timedelta(seconds=int(result["expires_in"]))
        db.commit()
        logger.info(f"[outlook_client] Token refreshed for integration {integration_id}")
        return result["access_token"]
    finally:
        db.close()


def graph_request(integration_id: int, access_token: str, method: str, path: str, **kwargs) -> tuple[dict, str]:
    """Perform a Graph request, refreshing the token once on 401.

    Returns ``(json_body, access_token_used)`` so callers can keep the fresh token.
    """
    url = path if path.startswith("http") else f"{GRAPH_BASE_URL}{path}"
    for attempt in (1, 2):
        with httpx.Client(timeout=30) as client:
            response = client.request(
                method, url, headers={"Authorization": f"Bearer {access_token}"}, **kwargs,
            )
        if response.status_code == 401 and attempt == 1:
            access_token = refresh_outlook_token(integration_id)
            continue
        response.raise_for_status()
        return (response.json() if response.content else {}), access_token
    raise OutlookAuthError("Graph request failed after token refresh")
