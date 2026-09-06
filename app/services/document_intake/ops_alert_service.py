"""
Internal ops alert escalation (open question #8) — fired when client callback
delivery is permanently exhausted (all CALLBACK_MAX_RETRIES attempts failed).
Broadcasts an in-app notification and, if configured, posts to a
Slack/Teams-compatible incoming webhook.
"""
from __future__ import annotations
import httpx
from loguru import logger

from app.config import settings
from app.services.notification_service import notification_manager


async def send_ops_alert(title: str, message: str, details: dict | None = None) -> None:
    """Best-effort internal alert — never raises, so it can't break the calling pipeline."""
    try:
        await notification_manager.broadcast_notification({
            "id": f"ops-alert-{title[:40]}",
            "email_id": None,
            "type": "ops_alert",
            "title": title,
            "message": message,
            "is_read": False,
            "created_at": _now_iso(),
        })
    except Exception as exc:
        logger.warning(f"[ops_alert_service] In-app broadcast failed: {exc}")

    webhook_url = settings.OPS_ALERT_WEBHOOK_URL
    if not webhook_url:
        return

    try:
        payload = {"text": f"*{title}*\n{message}"}
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(webhook_url, json=payload)
    except Exception as exc:
        logger.warning(f"[ops_alert_service] Webhook alert failed: {exc}")


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
