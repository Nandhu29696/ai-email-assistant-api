"""Provider adapters for Outlook Graph and generic IMAP document intake."""
from __future__ import annotations
import base64
import email.mime.text
import smtplib
from datetime import timedelta
from email.message import EmailMessage
from datetime import datetime, timezone

import httpx
from loguru import logger

from app.config import settings
from app.services.email_fetcher import IMAPFetcher
from app.services.document_intake.attachment_extractor import ExtractedAttachment
from app.utils.crypto import decrypt_token


class OutlookGraphAdapter:
    """Microsoft Graph adapter implementing the shared document-intake mailbox contract."""

    def __init__(self, integration):
        self.integration = integration
        self.access_token = decrypt_token(integration.access_token) or ""
        self.base_url = "https://graph.microsoft.com/v1.0"
        self.headers = {"Authorization": f"Bearer {self.access_token}"}

    def _request(self, method: str, path: str, **kwargs):
        with httpx.Client(timeout=30) as client:
            response = client.request(method, f"{self.base_url}{path}", headers=self.headers, **kwargs)
        response.raise_for_status()
        return response.json() if response.content else {}

    def fetch_unseen(self, limit: int = 50) -> list[dict]:
        data = self._request(
            "GET", "/me/mailFolders/inbox/messages/delta",
            params={"$top": limit,
                    "$select": "id,subject,from,toRecipients,receivedDateTime,conversationId,internetMessageId,body,internetMessageHeaders"},
        )
        return [message for message in data.get("value", []) if "@removed" not in message]

    def create_subscription(self, notification_url: str) -> dict:
        expiration = (datetime.now(timezone.utc) + timedelta(hours=23)).isoformat().replace("+00:00", "Z")
        return self._request("POST", "/subscriptions", json={
            "changeType": "created,updated",
            "notificationUrl": notification_url,
            "resource": "/me/mailFolders('Inbox')/messages",
            "expirationDateTime": expiration,
            "clientState": "ai-email-assistant",
        })

    def build_context(self, message: dict):
        from app.services.document_intake.pipeline import IntakeEmailContext
        sender = message.get("from", {}).get("emailAddress", {})
        recipients = message.get("toRecipients", [])
        recipient = recipients[0].get("emailAddress", {}).get("address", "") if recipients else self.integration.email_address
        received = message.get("receivedDateTime")
        received_at = datetime.fromisoformat(received.replace("Z", "+00:00")) if received else datetime.now(timezone.utc)
        headers = {h.get("name", "").lower(): h.get("value", "") for h in message.get("internetMessageHeaders", [])}
        body = message.get("body", {}).get("content", "")
        headers["_body_plain"] = body
        return IntakeEmailContext(
            gmail_message_id=message["id"],
            stored_message_id=message.get("internetMessageId") or message["id"],
            thread_id=message.get("conversationId"),
            headers=headers,
            sender_name=sender.get("name", ""),
            sender_email=sender.get("address", ""),
            recipient_email=recipient,
            subject=message.get("subject") or "(no subject)",
            received_at=received_at,
            payload=message,
        )

    def extract_attachments(self, context) -> list[ExtractedAttachment]:
        data = self._request("GET", f"/me/messages/{context.gmail_message_id}/attachments")
        result = []
        for attachment in data.get("value", []):
            if attachment.get("@odata.type") != "#microsoft.graph.fileAttachment":
                continue
            raw = base64.b64decode(attachment.get("contentBytes", ""))
            result.append(ExtractedAttachment(
                filename=attachment.get("name", "attachment"),
                content_type=attachment.get("contentType", "application/octet-stream"),
                data=raw,
                size_bytes=len(raw),
            ))
        return result

    def has_attachments(self, context) -> bool:
        data = self._request("GET", f"/me/messages/{context.gmail_message_id}/attachments")
        return any(a.get("@odata.type") == "#microsoft.graph.fileAttachment" for a in data.get("value", []))

    def send_reply(self, context, subject: str, html_body: str) -> bool:
        try:
            self._request("POST", f"/me/messages/{context.gmail_message_id}/reply", json={
                "message": {"body": {"contentType": "HTML", "content": html_body}},
                "comment": subject,
            })
            return True
        except Exception as exc:
            logger.warning(f"[outlook_adapter] Reply failed: {exc}")
            return False

    def _folder_id(self, display_name: str) -> str:
        folders = self._request("GET", "/me/mailFolders", params={"$top": 100}).get("value", [])
        for folder in folders:
            if folder.get("displayName") == display_name:
                return folder["id"]
        created = self._request("POST", "/me/mailFolders", json={"displayName": display_name})
        return created["id"]

    def _move(self, message_id: str, label: str) -> bool:
        try:
            self._request("POST", f"/me/messages/{message_id}/move", json={"destinationId": self._folder_id(label)})
            return True
        except Exception as exc:
            logger.warning(f"[outlook_adapter] Move failed: {exc}")
            return False

    def move_to_success(self, message_id: str, label: str) -> bool:
        return self._move(message_id, label)

    def move_to_failed(self, message_id: str, label: str) -> bool:
        return self._move(message_id, label)


class IMAPDocumentAdapter:
    """IMAP adapter using the existing fetcher and optional SMTP settings for replies."""

    def __init__(self, integration):
        self.integration = integration
        self.fetcher = IMAPFetcher(settings.IMAP_HOST, settings.IMAP_PORT, integration.email_address, settings.IMAP_PASSWORD)

    def fetch_contexts(self) -> list[tuple[object, dict]]:
        from app.services.document_intake.pipeline import IntakeEmailContext
        contexts = []
        with self.fetcher as fetcher:
            for item in fetcher.fetch_unseen(limit=50):
                context = IntakeEmailContext(
                    gmail_message_id=item["uid"], stored_message_id=item["message_id"],
                    thread_id=item.get("thread_id"), headers=item.get("headers", {}),
                    sender_name=item.get("sender_name", ""), sender_email=item["sender_email"],
                    recipient_email=self.integration.email_address, subject=item["subject"],
                    received_at=item["received_at"],
                    payload={"attachments": item.get("attachments", []), "has_attachments": bool(item.get("attachments"))},
                )
                context.headers["_body_plain"] = item.get("body_plain", "")
                contexts.append((context, item))
        return contexts

    def extract_attachments(self, context) -> list[ExtractedAttachment]:
        return [ExtractedAttachment(a["filename"], a["content_type"], a["data"], a["size_bytes"]) for a in context.payload.get("attachments", [])]

    def has_attachments(self, context) -> bool:
        return bool(context.payload.get("attachments"))

    def send_reply(self, context, subject: str, html_body: str) -> bool:
        if not settings.SMTP_HOST or not settings.SMTP_USERNAME:
            return False
        try:
            message = EmailMessage()
            message["From"] = self.integration.email_address
            message["To"] = context.sender_email
            message["Subject"] = subject
            message.set_content("This message requires an HTML-capable email client.")
            message.add_alternative(html_body, subtype="html")
            with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT) as smtp:
                smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
                smtp.send_message(message)
            return True
        except Exception as exc:
            logger.warning(f"[imap_adapter] Reply failed: {exc}")
            return False

    def move_to_success(self, message_id: str, label: str) -> bool:
        return self._move(message_id, label)

    def move_to_failed(self, message_id: str, label: str) -> bool:
        return self._move(message_id, label)

    def _move(self, message_id: str, label: str) -> bool:
        try:
            with self.fetcher as fetcher:
                fetcher._conn.select("INBOX")
                fetcher._conn.copy(message_id, label)
                fetcher._conn.store(message_id, "+FLAGS", "\\Deleted")
                fetcher._conn.expunge()
            return True
        except Exception as exc:
            logger.warning(f"[imap_adapter] Folder move failed: {exc}")
            return False
