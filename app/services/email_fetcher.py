"""
Email fetcher service.
Supports Gmail (IMAP) and Outlook (Microsoft Graph API).
"""
from __future__ import annotations
import imaplib
import email
import email.header
from dataclasses import dataclass
from datetime import datetime
from typing import Generator
from loguru import logger


def _decode_header(value: str | bytes | None) -> str:
    """Safely decode MIME-encoded email headers."""
    if not value:
        return ""
    if isinstance(value, bytes):
        decoded_parts = email.header.decode_header(value.decode("utf-8", errors="replace"))
    else:
        decoded_parts = email.header.decode_header(value)

    result = []
    for part, charset in decoded_parts:
        if isinstance(part, bytes):
            result.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(str(part))
    return " ".join(result)


def _extract_body(msg: email.message.Message) -> tuple[str, str]:
    """Extract plain text and HTML bodies from an email message."""
    plain, html = "", ""

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))
            if "attachment" in content_disposition:
                continue
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            charset = part.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
            if content_type == "text/plain":
                plain = text
            elif content_type == "text/html":
                html = text
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
            if msg.get_content_type() == "text/html":
                html = text
            else:
                plain = text

    return plain, html


def _extract_attachments(msg: email.message.Message) -> list[dict]:
    attachments: list[dict] = []
    for part in msg.walk():
        filename = part.get_filename()
        disposition = str(part.get("Content-Disposition", "")).lower()
        if not filename or "attachment" not in disposition:
            continue
        data = part.get_payload(decode=True) or b""
        attachments.append({
            "filename": _decode_header(filename),
            "content_type": part.get_content_type(),
            "data": data,
            "size_bytes": len(data),
        })
    return attachments


class IMAPFetcher:
    """Fetch emails from any IMAP-compatible mailbox."""

    def __init__(self, host: str, port: int, username: str, password: str, timeout: int = 30):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.timeout = timeout
        self._conn: imaplib.IMAP4_SSL | None = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

    def connect(self):
        try:
            self._conn = imaplib.IMAP4_SSL(self.host, self.port, timeout=self.timeout)
            self._conn.login(self.username, self.password)
        except Exception as exc:
            logger.error(f"[IMAPFetcher] Failed to connect to {self.host}:{self.port} - {exc}")
            raise

    def disconnect(self):
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            try:
                self._conn.logout()
            except Exception:
                pass
            self._conn = None

    def fetch_unseen(self, mailbox: str = "INBOX", limit: int = 50) -> Generator[dict, None, None]:
        """Yield dicts of unseen email data."""
        if not self._conn:
            raise RuntimeError("Not connected. Call connect() first.")

        self._conn.select(mailbox, readonly=True)
        _, data = self._conn.search(None, "UNSEEN")
        uids = data[0].split()

        for uid in uids[:limit]:
            try:
                _, msg_data = self._conn.fetch(uid, "(RFC822)")
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)

                subject   = _decode_header(msg.get("Subject", "(no subject)"))
                from_raw  = _decode_header(msg.get("From", ""))
                sender_name, sender_email = email.utils.parseaddr(from_raw)
                date_str  = msg.get("Date", "")
                message_id = msg.get("Message-ID", uid.decode())
                plain, html = _extract_body(msg)
                attachments = _extract_attachments(msg)

                try:
                    received_at = email.utils.parsedate_to_datetime(date_str)
                except Exception:
                    received_at = datetime.utcnow()

                yield {
                    "message_id": message_id.strip(),
                    "subject": subject,
                    "sender_name": sender_name,
                    "sender_email": sender_email,
                    "body_plain": plain,
                    "body_html": html,
                    "received_at": received_at,
                    "thread_id": msg.get("In-Reply-To"),
                    "headers": {key.lower(): _decode_header(value) for key, value in msg.items()},
                    "attachments": attachments,
                    "uid": uid.decode(errors="replace"),
                }
            except Exception as exc:
                logger.warning(f"Failed to parse email uid={uid}: {exc}")
                continue
