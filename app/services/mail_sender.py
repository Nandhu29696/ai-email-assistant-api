"""Send a new (non-reply) email from a connected mailbox — used for template test emails."""
from __future__ import annotations

import base64
from email.mime.text import MIMEText

from app.database import SessionLocal
from app.models.email import EmailIntegration
from app.utils.crypto import decrypt_token


class MailSendError(RuntimeError):
    pass


def send_new_message(integration_id: int, to_address: str, subject: str, html_body: str) -> None:
    """Blocking. Raises MailSendError with a user-readable reason on failure."""
    db = SessionLocal()
    try:
        mailbox = db.query(EmailIntegration).filter(EmailIntegration.id == integration_id).first()
        if mailbox is None:
            raise MailSendError("Mailbox not found")
        if not mailbox.is_active:
            raise MailSendError("This mailbox is not connected")
        db.expunge(mailbox)
    finally:
        db.close()

    try:
        if mailbox.provider == "gmail":
            from app.services.gmail_client import build_gmail_service

            message = MIMEText(html_body, "html", "utf-8")
            message["To"] = to_address
            message["From"] = mailbox.email_address
            message["Subject"] = subject
            raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
            build_gmail_service(mailbox.id).users().messages().send(userId="me", body={"raw": raw}).execute()
        elif mailbox.provider == "outlook":
            from app.services.outlook_client import graph_request

            graph_request(mailbox.id, decrypt_token(mailbox.access_token) or "", "POST", "/me/sendMail", json={
                "message": {
                    "subject": subject,
                    "body": {"contentType": "HTML", "content": html_body},
                    "toRecipients": [{"emailAddress": {"address": to_address}}],
                },
                "saveToSentItems": True,
            })
        elif mailbox.provider == "imap":
            from app.services.document_intake.provider_adapters import IMAPDocumentAdapter
            from app.services.preprocessor import strip_html

            IMAPDocumentAdapter(mailbox).send_message(
                to_address, subject, strip_html(html_body).strip() or " ", html_body, auto_submitted=True,
            )
        else:
            raise MailSendError(f"Sending is not supported for {mailbox.provider} mailboxes")
    except MailSendError:
        raise
    except Exception as exc:
        raise MailSendError(f"The mailbox could not send the email ({type(exc).__name__}: {str(exc)[:200]})") from exc
