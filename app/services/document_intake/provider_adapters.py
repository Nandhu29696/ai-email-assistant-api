"""Provider adapters for Outlook Graph and generic IMAP document intake."""
from __future__ import annotations
import base64
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from loguru import logger

from app.config import settings
from app.database import SessionLocal
from app.models.email import EmailIntegration
from app.services.email_fetcher import IMAPFetcher
from app.services.document_intake.attachment_extractor import ExtractedAttachment
from app.services.outlook_client import graph_request
from app.utils.crypto import decrypt_token

_MESSAGE_FIELDS = (
    "id,subject,from,toRecipients,receivedDateTime,conversationId,"
    "internetMessageId,body,internetMessageHeaders,hasAttachments"
)


class OutlookGraphAdapter:
    """Microsoft Graph adapter implementing the shared document-intake mailbox contract."""

    def __init__(self, integration):
        self.integration = integration
        self.integration_id = integration.id
        self.access_token = decrypt_token(integration.access_token) or ""
        self._attachment_cache: dict[str, list[dict]] = {}

    def _request(self, method: str, path: str, **kwargs) -> dict:
        data, self.access_token = graph_request(self.integration_id, self.access_token, method, path, **kwargs)
        return data

    def fetch_unseen(self, limit: int = 50) -> list[dict]:
        """Unread Inbox messages, oldest first. Each is marked read after processing."""
        data = self._request(
            "GET", "/me/mailFolders/inbox/messages",
            params={
                "$filter": "isRead eq false",
                "$orderby": "receivedDateTime asc",
                "$top": limit,
                "$select": _MESSAGE_FIELDS,
            },
        )
        return data.get("value", [])

    def get_message(self, message_id: str) -> dict:
        return self._request("GET", f"/me/messages/{message_id}", params={"$select": _MESSAGE_FIELDS})

    def mark_read(self, message_id: str) -> None:
        try:
            self._request("PATCH", f"/me/messages/{message_id}", json={"isRead": True})
        except Exception as exc:
            logger.warning(f"[outlook_adapter] Failed to mark {message_id} read: {exc}")

    def create_subscription(self, notification_url: str) -> dict:
        # Graph allows up to ~4230 minutes for mail; renewals happen in the poller.
        expiration = datetime.now(timezone.utc) + timedelta(minutes=4200)
        subscription = self._request("POST", "/subscriptions", json={
            "changeType": "created",
            "notificationUrl": notification_url,
            "resource": "/me/mailFolders('Inbox')/messages",
            "expirationDateTime": expiration.isoformat().replace("+00:00", "Z"),
            "clientState": settings.OUTLOOK_WEBHOOK_CLIENT_STATE,
        })
        self._save_subscription(subscription.get("id"), expiration)
        return subscription

    def renew_subscription(self, subscription_id: str) -> None:
        expiration = datetime.now(timezone.utc) + timedelta(minutes=4200)
        self._request("PATCH", f"/subscriptions/{subscription_id}", json={
            "expirationDateTime": expiration.isoformat().replace("+00:00", "Z"),
        })
        self._save_subscription(subscription_id, expiration)

    def _save_subscription(self, subscription_id: str | None, expiration: datetime) -> None:
        db = SessionLocal()
        try:
            row = db.query(EmailIntegration).filter(EmailIntegration.id == self.integration_id).first()
            if row:
                row.outlook_subscription_id = subscription_id
                row.outlook_subscription_expires_at = expiration
                db.commit()
        finally:
            db.close()

    def build_context(self, message: dict):
        from app.services.document_intake.pipeline import IntakeEmailContext
        from app.services.preprocessor import strip_html

        sender = message.get("from", {}).get("emailAddress", {})
        received = message.get("receivedDateTime")
        received_at = datetime.fromisoformat(received.replace("Z", "+00:00")) if received else datetime.now(timezone.utc)
        headers = {h.get("name", ""): h.get("value", "") for h in message.get("internetMessageHeaders", []) or []}
        body = message.get("body", {}) or {}
        content = body.get("content", "") or ""
        headers["_body_plain"] = strip_html(content) if body.get("contentType", "").lower() == "html" else content
        if message.get("internetMessageId"):
            headers.setdefault("Message-ID", message["internetMessageId"])
        return IntakeEmailContext(
            gmail_message_id=message["id"],
            stored_message_id=(message.get("internetMessageId") or message["id"]).strip("<>"),
            thread_id=message.get("conversationId"),
            headers=headers,
            sender_name=sender.get("name", ""),
            sender_email=sender.get("address", ""),
            recipient_email=self.integration.email_address,
            subject=message.get("subject") or "(no subject)",
            received_at=received_at,
            payload=message,
        )

    def _file_attachments(self, message_id: str) -> list[dict]:
        if message_id not in self._attachment_cache:
            data = self._request("GET", f"/me/messages/{message_id}/attachments")
            self._attachment_cache[message_id] = [
                a for a in data.get("value", [])
                if a.get("@odata.type") == "#microsoft.graph.fileAttachment" and not a.get("isInline")
            ]
        return self._attachment_cache[message_id]

    def extract_attachments(self, context) -> list[ExtractedAttachment]:
        result = []
        for attachment in self._file_attachments(context.gmail_message_id):
            raw = base64.b64decode(attachment.get("contentBytes", ""))
            result.append(ExtractedAttachment(
                filename=attachment.get("name", "attachment"),
                content_type=attachment.get("contentType", "application/octet-stream"),
                data=raw,
                size_bytes=len(raw),
            ))
        return result

    def has_attachments(self, context) -> bool:
        return bool(self._file_attachments(context.gmail_message_id))

    def send_reply(self, context, subject: str, html_body: str) -> bool:
        """Reply in-thread: create a reply draft, set subject/body, then send it."""
        try:
            draft = self._request("POST", f"/me/messages/{context.gmail_message_id}/createReply")
            self._request("PATCH", f"/me/messages/{draft['id']}", json={
                "subject": subject,
                "body": {"contentType": "HTML", "content": html_body},
            })
            self._request("POST", f"/me/messages/{draft['id']}/send")
            return True
        except Exception as exc:
            logger.warning(f"[outlook_adapter] Reply failed: {exc}")
            return False

    def _folder_id(self, display_name: str) -> str:
        """Resolve (creating as needed) a folder path such as 'Processed/Success'."""
        parent_path = "/me/mailFolders"
        folder_id = ""
        for part in [p for p in display_name.split("/") if p.strip()]:
            folders = self._request(
                "GET", parent_path,
                params={"$top": 100, "$filter": f"displayName eq '{part.replace(chr(39), chr(39) * 2)}'"},
            ).get("value", [])
            if folders:
                folder_id = folders[0]["id"]
            else:
                folder_id = self._request("POST", parent_path, json={"displayName": part})["id"]
            parent_path = f"/me/mailFolders/{folder_id}/childFolders"
        return folder_id

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
    """IMAP adapter (per-mailbox credentials, falling back to the global IMAP_*/SMTP_* settings)."""

    def __init__(self, integration):
        self.integration = integration
        self.imap_host = integration.imap_host or settings.IMAP_HOST
        self.imap_port = integration.imap_port or settings.IMAP_PORT
        self.imap_username = integration.imap_username or integration.email_address
        self.imap_password = decrypt_token(integration.imap_password) if integration.imap_password else settings.IMAP_PASSWORD
        self.smtp_host = integration.smtp_host or settings.SMTP_HOST
        self.smtp_port = integration.smtp_port or settings.SMTP_PORT
        self.smtp_username = integration.smtp_username or settings.SMTP_USERNAME or self.imap_username
        self.smtp_password = decrypt_token(integration.smtp_password) if integration.smtp_password else (
            settings.SMTP_PASSWORD or self.imap_password
        )
        self.fetcher = IMAPFetcher(self.imap_host, self.imap_port, self.imap_username, self.imap_password)

    def _context_from_item(self, item: dict):
        from app.services.document_intake.pipeline import IntakeEmailContext
        context = IntakeEmailContext(
            gmail_message_id=item["uid"], stored_message_id=item["message_id"].strip("<>"),
            thread_id=item.get("thread_id"), headers=dict(item.get("headers", {})),
            sender_name=item.get("sender_name", ""), sender_email=item["sender_email"],
            recipient_email=self.integration.email_address, subject=item["subject"],
            received_at=item["received_at"],
            payload={"attachments": item.get("attachments", []), "has_attachments": bool(item.get("attachments"))},
        )
        context.headers["_body_plain"] = item.get("body_plain", "")
        return context

    def unseen_uids(self, limit: int = 50) -> list[str]:
        with self.fetcher as fetcher:
            return fetcher.search_unseen_uids(limit=limit)

    def fetch_item(self, uid: str) -> dict | None:
        with self.fetcher as fetcher:
            return fetcher.fetch_uid(uid)

    def context_for(self, item: dict):
        return self._context_from_item(item)

    def mark_seen(self, uid: str) -> None:
        try:
            with self.fetcher as fetcher:
                fetcher.add_flags(uid, "(\\Seen)")
        except Exception as exc:
            logger.warning(f"[imap_adapter] Failed to mark {uid} seen: {exc}")

    def fetch_contexts(self) -> list[tuple[object, dict]]:
        contexts = []
        with self.fetcher as fetcher:
            for item in fetcher.fetch_unseen(limit=50):
                contexts.append((self._context_from_item(item), item))
        return contexts

    def send_message(self, to_addr: str, subject: str, text_body: str, html_body: str | None = None,
                     in_reply_to: str | None = None, attachments: list | None = None,
                     auto_submitted: bool = False) -> bool:
        if not self.smtp_host or not self.smtp_username:
            raise RuntimeError("SMTP is not configured for this mailbox")
        message = EmailMessage()
        message["From"] = self.integration.email_address
        message["To"] = to_addr
        message["Subject"] = subject
        if in_reply_to:
            message["In-Reply-To"] = in_reply_to
            message["References"] = in_reply_to
        if auto_submitted:
            message["Auto-Submitted"] = "auto-replied"
        message.set_content(text_body)
        if html_body:
            message.add_alternative(html_body, subtype="html")
        for meta, data in attachments or []:
            maintype, _, subtype = (meta.get("content_type") or "application/octet-stream").partition("/")
            message.add_attachment(data, maintype=maintype, subtype=subtype or "octet-stream", filename=meta["filename"])
        smtp_cls = smtplib.SMTP_SSL if int(self.smtp_port) == 465 else smtplib.SMTP
        with smtp_cls(self.smtp_host, int(self.smtp_port), timeout=30) as smtp:
            if smtp_cls is smtplib.SMTP:
                smtp.starttls()
            smtp.login(self.smtp_username, self.smtp_password)
            smtp.send_message(message)
        return True

    def extract_attachments(self, context) -> list[ExtractedAttachment]:
        return [ExtractedAttachment(a["filename"], a["content_type"], a["data"], a["size_bytes"]) for a in context.payload.get("attachments", [])]

    def has_attachments(self, context) -> bool:
        return bool(context.payload.get("attachments"))

    def send_reply(self, context, subject: str, html_body: str) -> bool:
        from app.services.preprocessor import strip_html
        from app.services.gmail_client import format_message_id
        try:
            lower = {k.lower(): v for k, v in context.headers.items()}
            return self.send_message(
                context.sender_email, subject, strip_html(html_body).strip() or " ", html_body,
                in_reply_to=format_message_id(lower.get("message-id")), auto_submitted=True,
            )
        except Exception as exc:
            logger.warning(f"[imap_adapter] Reply failed: {exc}")
            return False

    def move_to_success(self, message_id: str, label: str) -> bool:
        return self._move(message_id, label)

    def move_to_failed(self, message_id: str, label: str) -> bool:
        return self._move(message_id, label)

    def _move(self, uid: str, label: str) -> bool:
        """Move by UID — sequence numbers shift after expunge and would hit the wrong message."""
        try:
            with self.fetcher as fetcher:
                conn = fetcher._conn
                conn.select("INBOX")
                conn.create(label)  # no-op error if it already exists
                typ, _ = conn.uid("COPY", uid, label)
                if typ != "OK":
                    raise RuntimeError(f"UID COPY failed for {uid}")
                conn.uid("STORE", uid, "+FLAGS", "(\\Deleted)")
                try:
                    conn.uid("EXPUNGE", uid)  # UIDPLUS: expunge only this message
                except Exception:
                    conn.expunge()
            return True
        except Exception as exc:
            logger.warning(f"[imap_adapter] Folder move failed: {exc}")
            return False
