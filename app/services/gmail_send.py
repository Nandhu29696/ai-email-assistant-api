from __future__ import annotations

import base64
from email.mime.text import MIMEText

from loguru import logger
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.config import settings
from app.database import SessionLocal
from app.models.email import Email, EmailReply, EmailIntegration
from app.utils.crypto import decrypt_token, encrypt_token


def send_reply_via_gmail(
    email_obj: Email,
    reply_obj: EmailReply,
) -> tuple[bool, str | None]:
    """
    Send a reply using the Gmail account associated with the email integration.

    Returns:
        (True, None) on success
        (False, error_message) on failure
    """

    if not email_obj.integration_id:
        return False, "Email integration not found"

    # --------------------------------------------------
    # Load integration
    # --------------------------------------------------
    db = SessionLocal()
    try:
        integration = (
            db.query(EmailIntegration)
            .filter(
                EmailIntegration.id == email_obj.integration_id,
                EmailIntegration.is_active == True,
            )
            .first()
        )

        if not integration:
            return False, "Integration not found"

        if not integration.access_token:
            return False, "Missing access token"

        access_token = decrypt_token(integration.access_token)
        refresh_token = decrypt_token(integration.refresh_token)
        sender_email = integration.email_address

    finally:
        db.close()

    # --------------------------------------------------
    # Build credentials
    # --------------------------------------------------
    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GMAIL_CLIENT_ID,
        client_secret=settings.GMAIL_CLIENT_SECRET,
        scopes=[
            "https://www.googleapis.com/auth/gmail.send",
        ],
    )

    # --------------------------------------------------
    # Refresh token if expired
    # --------------------------------------------------
    try:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())

            db = SessionLocal()
            try:
                row = (
                    db.query(EmailIntegration)
                    .filter(EmailIntegration.id == email_obj.integration_id)
                    .first()
                )

                if row:
                    row.access_token = encrypt_token(creds.token)
                    db.commit()

            finally:
                db.close()

    except Exception as exc:
        logger.error(f"[gmail_send] Token refresh failed: {exc}")
        return False, f"Token refresh failed: {exc}"

    # --------------------------------------------------
    # Gmail Service
    # --------------------------------------------------
    try:
        service = build(
            "gmail",
            "v1",
            credentials=creds,
            cache_discovery=False,
        )
    except Exception as exc:
        logger.error(f"[gmail_send] Gmail service creation failed: {exc}")
        return False, f"Gmail service creation failed: {exc}"

    # --------------------------------------------------
    # Create Email Message
    # --------------------------------------------------
    message = MIMEText(reply_obj.body or "")

    message["To"] = email_obj.sender_email
    message["From"] = sender_email
    message["Subject"] = (
        reply_obj.subject
        or f"Re: {email_obj.subject}"
    )

    if email_obj.message_id:
        message["In-Reply-To"] = email_obj.message_id
        message["References"] = email_obj.message_id

    raw_message = base64.urlsafe_b64encode(
        message.as_bytes()
    ).decode()

    request_body = {
        "raw": raw_message
    }

    if email_obj.thread_id:
        request_body["threadId"] = email_obj.thread_id

    # --------------------------------------------------
    # Send Email
    # --------------------------------------------------
    try:
        response = (
            service.users()
            .messages()
            .send(
                userId="me",
                body=request_body,
            )
            .execute()
        )

        logger.info(
            f"[gmail_send] Reply sent successfully "
            f"(gmail_id={response.get('id')}) "
            f"to {email_obj.sender_email}"
        )

        return True, None

    except HttpError as exc:

        status = getattr(exc.resp, "status", None)

        if status == 429:
            logger.warning(
                "[gmail_send] Gmail send rate limit exceeded"
            )
            return (
                False,
                "rate_limit_exceeded",
            )

        if status == 403:
            logger.warning(
                "[gmail_send] Missing gmail.send permission"
            )
            return (
                False,
                "invalid_scope",
            )

        logger.error(f"[gmail_send] Gmail API error: {exc}")
        return False, str(exc)

    except Exception as exc:
        logger.error(f"[gmail_send] Unexpected error: {exc}")
        return False, str(exc)