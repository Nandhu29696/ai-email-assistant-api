"""
Attachment extractor for the document-intake pipeline (§5 step 5).
Recursively walks a Gmail API message payload and pulls out every
non-inline attachment as raw bytes + filename.
"""
from __future__ import annotations
import base64
from dataclasses import dataclass


@dataclass
class ExtractedAttachment:
    filename: str
    content_type: str
    data: bytes
    size_bytes: int


def _decode_gmail_body_data(data_b64url: str) -> bytes:
    padded = data_b64url + "=" * (-len(data_b64url) % 4)
    return base64.urlsafe_b64decode(padded)


def extract_attachments_from_gmail_payload(
    service,
    gmail_message_id: str,
    payload: dict,
) -> list[ExtractedAttachment]:
    """
    Walk a Gmail API message payload and download every attachment part.
    `service` is an authenticated Gmail API resource (googleapiclient discovery build).
    """
    results: list[ExtractedAttachment] = []
    _walk_parts(service, gmail_message_id, payload, results)
    return results


def _walk_parts(service, message_id: str, part: dict, results: list[ExtractedAttachment]) -> None:
    filename = part.get("filename") or ""
    body = part.get("body", {})

    if filename:
        attachment_id = body.get("attachmentId")
        data_b64url = body.get("data")

        if attachment_id:
            att = (
                service.users()
                .messages()
                .attachments()
                .get(userId="me", messageId=message_id, id=attachment_id)
                .execute()
            )
            data_b64url = att.get("data", "")

        if data_b64url:
            raw = _decode_gmail_body_data(data_b64url)
            results.append(
                ExtractedAttachment(
                    filename=filename,
                    content_type=part.get("mimeType", "application/octet-stream"),
                    data=raw,
                    size_bytes=len(raw),
                )
            )

    for sub_part in part.get("parts", []) or []:
        _walk_parts(service, message_id, sub_part, results)


def has_attachments(payload: dict) -> bool:
    """Quick existence check without downloading attachment bytes (§5 step 4)."""
    if payload.get("attachments"):
        return True
    if payload.get("has_attachments") is True:
        return True
    return _has_attachments_recursive(payload)


def _has_attachments_recursive(part: dict) -> bool:
    if part.get("filename"):
        return True
    for sub_part in part.get("parts", []) or []:
        if _has_attachments_recursive(sub_part):
            return True
    return False
