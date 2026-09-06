"""
Client callback notifier (§4) — POSTs the exact status payload contract to the
client-configured webhook URL, with retry + full delivery audit logging.
"""
from __future__ import annotations
import asyncio
import ipaddress
import socket
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import httpx
from loguru import logger
from sqlalchemy.orm import Session

from app.config import settings
from app.models.document_intake import EmailBatch, EmailBatchAttachment, EmailBatchCallback
from app.utils.crypto import decrypt_token

# Maps internal batch status -> client-facing processResultStatusCode (§4.3)
_STATUS_CODE_MAP = {
    "SUCCESS": "SUCCESS",
    "REJECTED": "FAILED",
    "FAILED": "FAILED",
}


def validate_callback_url(webhook_url: str) -> str:
    """Reject callback targets that can reach local or cloud metadata services."""
    parsed = urlparse(webhook_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Callback URL must use http or https and include a hostname")
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError("Callback URL cannot contain credentials or a fragment")
    if settings.ENVIRONMENT.lower() == "production" and parsed.scheme != "https":
        raise ValueError("Callback URLs must use HTTPS in production")

    host = parsed.hostname.lower().rstrip(".")
    blocked_names = {"localhost", "metadata.google.internal", "instance-data.ec2.internal"}
    if host in blocked_names or host == "metadata" or host.endswith(".localhost"):
        raise ValueError("Callback URL targets a blocked host")

    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, parsed.port, type=socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        raise ValueError("Callback URL hostname could not be resolved") from exc

    for address in addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified:
            raise ValueError("Callback URL cannot target a private, local, or reserved address")
    return webhook_url


def build_callback_payload(batch: EmailBatch, attachments: list[EmailBatchAttachment]) -> dict:
    """Construct the exact client contract (§4.1), with additive sensitivity extension fields (§1.2.4)."""
    attachments_payload = [
        {
            "filename": a.batch_source_filename,
            "docType": a.doc_type,
            "sizeBytes": a.file_size_bytes,
            "status": a.status,
        }
        for a in attachments
    ]

    payload = {
        "processResultStatusCode": _STATUS_CODE_MAP.get(batch.status, "FAILED"),
        "processResultMessage": batch.status_reason or "",
        "emailInfo": {
            "emailAccount": batch.recipient_email or "",
            "emailSubject": batch.subject or "",
            "fromEmail": batch.sender_email or "",
            "toEmail": batch.recipient_email or "",
            "noOfAttachments": batch.attachment_count or 0,
            "attachments": attachments_payload,
            "emailDate": batch.received_datetime.isoformat() if batch.received_datetime else None,
        },
    }

    if batch.sensitivity_level or batch.contains_pii:
        payload["emailInfo"]["sensitivityLevel"] = batch.sensitivity_level
        payload["emailInfo"]["containsPii"] = bool(batch.contains_pii)

    return payload


def _parse_backoff_seconds() -> list[float]:
    try:
        return [float(x.strip()) for x in settings.CALLBACK_RETRY_BACKOFF_SECONDS.split(",") if x.strip()]
    except Exception:
        return [1.0, 5.0, 15.0]


async def send_callback(
    db: Session,
    batch: EmailBatch,
    webhook_url: str,
    auth_header_encrypted: Optional[str] = None,
) -> bool:
    """
    POST the callback payload to `webhook_url` with retry + backoff.
    Every attempt is recorded as an EmailBatchCallback row (§3.5). Never
    raises — failures are logged and returned as False so the caller can
    log a CALLBACK_FAILED event without affecting the batch's own status.
    """
    validate_callback_url(webhook_url)
    attachments = list(batch.attachments)
    payload = build_callback_payload(batch, attachments)

    headers = {"Content-Type": "application/json"}
    auth_header = decrypt_token(auth_header_encrypted) if auth_header_encrypted else None
    if auth_header:
        headers["Authorization"] = auth_header

    backoffs = _parse_backoff_seconds()
    max_attempts = max(1, settings.CALLBACK_MAX_RETRIES)

    delivered = False
    last_error = ""
    last_status_code: Optional[int] = None

    for attempt in range(1, max_attempts + 1):
        try:
            async with httpx.AsyncClient(
                timeout=settings.CALLBACK_TIMEOUT_SECONDS,
                follow_redirects=False,
            ) as client:
                response = await client.post(webhook_url, json=payload, headers=headers)
            last_status_code = response.status_code
            delivered = 200 <= response.status_code < 300
            last_error = "" if delivered else f"Non-2xx response: {response.status_code}"
        except Exception as exc:
            last_error = str(exc)
            delivered = False

        db.add(
            EmailBatchCallback(
                parent_batch_id=batch.id,
                batch_no=batch.batch_no,
                process_result_status_code=payload["processResultStatusCode"],
                process_result_message=payload["processResultMessage"],
                payload_json=payload,
                webhook_url=webhook_url,
                http_status_code=last_status_code,
                attempt_no=attempt,
                delivered=delivered,
                error_detail=last_error or None,
            )
        )
        db.commit()

        if delivered:
            logger.info(f"[client_callback_notifier] Callback delivered for batch {batch.batch_no} (attempt {attempt})")
            return True

        logger.warning(
            f"[client_callback_notifier] Callback attempt {attempt}/{max_attempts} failed for "
            f"batch {batch.batch_no}: {last_error}"
        )
        if attempt < max_attempts:
            delay = backoffs[min(attempt - 1, len(backoffs) - 1)]
            await asyncio.sleep(delay)

    logger.error(f"[client_callback_notifier] Callback permanently failed for batch {batch.batch_no} after {max_attempts} attempts")

    # Open question #8 — raise an internal ops alert once retries are exhausted.
    from app.services.document_intake.ops_alert_service import send_ops_alert
    await send_ops_alert(
        title=f"Client callback delivery failed — {batch.batch_no}",
        message=(
            f"All {max_attempts} delivery attempts to {webhook_url} failed for batch "
            f"{batch.batch_no} (status={batch.status}). Last error: {last_error}"
        ),
        details={"batch_no": batch.batch_no, "webhook_url": webhook_url, "last_error": last_error},
    )

    return False
