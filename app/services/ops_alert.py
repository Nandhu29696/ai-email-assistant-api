"""
Ops alerts to a Slack/Teams/Google Chat incoming webhook (OPS_ALERT_WEBHOOK_URL).

Sent when something needs a person: an email ended as "needs attention" (a
system problem, e.g. LibreOffice or storage down) or a mailbox's connection
broke (e.g. revoked/expired login). Alerts are best effort: they never raise and
never slow the pipeline down for more than the HTTP timeout.
"""
from __future__ import annotations

import threading

import httpx
from loguru import logger

from app.config import settings


def send_ops_alert(title: str, message: str) -> bool:
    """Post one alert. Returns True if the webhook accepted it. Blocking (call via a thread)."""
    url = settings.OPS_ALERT_WEBHOOK_URL
    if not url:
        return False
    text = f"*{title}*\n{message}"
    try:
        # "text" is understood by Slack, Microsoft Teams (incoming webhook) and Google Chat.
        response = httpx.post(url, json={"text": text}, timeout=10)
        response.raise_for_status()
        return True
    except Exception as exc:
        logger.warning(f"[ops_alert] Alert could not be delivered: {exc}")
        return False


def _app_link(path: str) -> str:
    return f"{settings.FRONTEND_URL.rstrip('/')}{path}"


def alert_email_needs_attention(batch_no: str, sender: str, subject: str | None, reason: str | None) -> bool:
    return send_ops_alert(
        f"Email needs attention: {batch_no}",
        f"From {sender} — “{(subject or '(no subject)')[:120]}”\n"
        f"Reason: {(reason or 'system error')[:300]}\n"
        f"The sender only received the acknowledgement. Fix the cause, then click Reprocess: "
        f"{_app_link('/emails?batch=' + batch_no)}",
    )


def alert_mailbox_health(email_address: str, previous: str | None, current: str, message: str | None) -> bool:
    """Alert only when a mailbox *becomes* broken, not on every failed sync."""
    if current != "error" or previous == "error":
        return False
    return send_ops_alert(
        f"Mailbox stopped working: {email_address}",
        f"{(message or 'Sync failed')[:300]}\nNew emails are not being picked up. "
        f"Reconnect it on the Mailboxes page: {_app_link('/mailboxes')}",
    )


def mailbox_health_changed(email_address: str, previous: str | None, current: str, message: str | None) -> None:
    """Called by the sync code after saving a health status; alerts in the background."""
    if settings.OPS_ALERT_WEBHOOK_URL and current == "error" and previous != "error":
        threading.Thread(
            target=alert_mailbox_health, args=(email_address, previous, current, message), daemon=True,
        ).start()
