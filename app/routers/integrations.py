"""
Integrations router — Gmail and Outlook OAuth2 flows.
"""
from __future__ import annotations
import asyncio
import hashlib
import hmac
import secrets
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, BackgroundTasks
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from loguru import logger
from jose import JWTError, jwt
from datetime import datetime, timedelta, timezone

from app.database import get_db
from app.models.email import EmailIntegration, Email, EmailReply
from app.models.user import User, OAuthState
from app.models.document_intake import EmailTemplate, EmailTemplateVersion
from app.schemas.email import IntegrationOut
from app.config import settings
from app.utils.crypto import encrypt_token, decrypt_token
from app.services.gmail_sync import sync_all_gmail
from app.services.document_intake.client_callback_notifier import validate_callback_url
from app.routers.auth import get_current_user, require_admin

router = APIRouter()


def _verify_webhook_secret(request: Request, expected: str) -> None:
    supplied = request.headers.get("X-Webhook-Secret", "")
    if not expected or not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid webhook credentials")


def _oauth_state(db: Session, user: User, provider: str) -> str:
    jti = secrets.token_urlsafe(24)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    db.add(OAuthState(
        state_hash=hashlib.sha256(jti.encode()).hexdigest(),
        user_id=user.id,
        provider=provider,
        expires_at=expires_at,
    ))
    db.commit()
    return jwt.encode(
        {"sub": str(user.id), "provider": provider, "type": "oauth_state", "jti": jti,
         "exp": expires_at},
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )


def _oauth_user_id(db: Session, state: str | None, provider: str) -> int | None:
    if not state:
        return None
    try:
        payload = jwt.decode(state, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("type") != "oauth_state" or payload.get("provider") != provider:
            return None
        jti = payload.get("jti")
        if not jti:
            return None
        record = db.query(OAuthState).filter(
            OAuthState.state_hash == hashlib.sha256(jti.encode()).hexdigest(),
            OAuthState.provider == provider,
            OAuthState.used_at.is_(None),
            OAuthState.expires_at > datetime.now(timezone.utc),
        ).with_for_update().first()
        if not record or record.user_id != int(payload["sub"]):
            return None
        record.used_at = datetime.now(timezone.utc)
        db.commit()
        return record.user_id
    except (JWTError, ValueError, TypeError, KeyError):
        return None


def _require_oauth_user_id(db: Session, state: str | None, provider: str) -> int:
    user_id = _oauth_user_id(db, state, provider)
    if user_id is None:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    return user_id


# ── Instant Sync Trigger ──────────────────────────────────────
@router.post("/sync")
async def trigger_immediate_sync(
    background_tasks: BackgroundTasks,
    admin: User = Depends(require_admin),
):
    """
    Trigger immediate mailbox synchronization across all active integrations
    without waiting for the background polling interval.
    """
    background_tasks.add_task(sync_all_gmail)
    return {"message": "Immediate mailbox sync triggered in background"}


# ── Gmail Push Notification / PubSub Webhook ─────────────────
@router.post("/gmail/webhook")
async def gmail_push_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Endpoint for Google Cloud Pub/Sub Push subscriptions.
    Captures incoming emails instantly in real-time when Gmail sends a push notification.
    """
    _verify_webhook_secret(request, settings.GMAIL_WEBHOOK_SECRET)
    try:
        data = await request.json()
        logger.info(f"[Gmail Webhook] Received push event: {data.get('message', {}).get('messageId', 'unknown')}")
    except Exception:
        pass

    # Trigger immediate sync upon push notification
    background_tasks.add_task(sync_all_gmail)
    return {"status": "accepted"}


@router.post("/outlook/webhook")
async def outlook_graph_webhook(request: Request, background_tasks: BackgroundTasks):
    """Receive Microsoft Graph change notifications and trigger delta-style inbox sync."""
    validation_token = request.query_params.get("validationToken")
    if validation_token:
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(validation_token)

    try:
        data = await request.json()
        expected_state = settings.OUTLOOK_WEBHOOK_CLIENT_STATE
        if not expected_state or not any(
            hmac.compare_digest(str(item.get("clientState", "")), expected_state)
            for item in data.get("value", [])
        ):
            raise HTTPException(status_code=401, detail="Invalid Outlook webhook client state")
        logger.info(f"[Outlook Webhook] Received {len(data.get('value', []))} notification(s)")
    except Exception:
        pass

    async def sync_outlook():
        from app.services.document_intake.provider_sync import sync_all_document_providers
        await sync_all_document_providers()

    background_tasks.add_task(sync_outlook)
    return {"status": "accepted"}


@router.post("/outlook/subscription")
def create_outlook_subscription(
    integration_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a Microsoft Graph Inbox subscription for an owned Outlook integration."""
    if not settings.OUTLOOK_WEBHOOK_URL:
        raise HTTPException(status_code=501, detail="OUTLOOK_WEBHOOK_URL is not configured")
    integration = db.query(EmailIntegration).filter(EmailIntegration.id == integration_id).first()
    if not integration or integration.provider != "outlook":
        raise HTTPException(status_code=404, detail="Outlook integration not found")
    if current_user.role != "admin" and integration.owner_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only manage your own integration")
    from app.services.document_intake.provider_adapters import OutlookGraphAdapter
    return OutlookGraphAdapter(integration).create_subscription(settings.OUTLOOK_WEBHOOK_URL)


# ── List active integrations ──────────────────────────────────
@router.get("", response_model=list[IntegrationOut])
def list_integrations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(EmailIntegration).filter(EmailIntegration.is_active == True)
    if current_user.role != "admin":
        query = query.filter(EmailIntegration.owner_user_id == current_user.id)
    return query.order_by(EmailIntegration.created_at.desc()).all()


class TemplateUpdate(BaseModel):
    subject_template: Optional[str] = None
    html_body_template: Optional[str] = None
    signature_html: Optional[str] = None
    logo_url: Optional[str] = None
    is_active: Optional[bool] = None


def _owned_integration(db: Session, integration_id: int, current_user: User) -> EmailIntegration:
    integration = db.query(EmailIntegration).filter(EmailIntegration.id == integration_id).first()
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    if current_user.role != "admin" and integration.owner_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only manage your own integration")
    return integration


def _template_out(template: EmailTemplate) -> dict:
    return {
        "id": template.id,
        "template_key": template.template_key,
        "locale": template.locale,
        "subject_template": template.subject_template,
        "html_body_template": template.html_body_template,
        "signature_html": template.signature_html or "",
        "logo_url": template.logo_url or "",
        "is_active": template.is_active,
    }


def _version_out(version: EmailTemplateVersion) -> dict:
    return {
        "id": version.id,
        "template_key": version.template_key,
        "subject_template": version.subject_template,
        "html_body_template": version.html_body_template,
        "signature_html": version.signature_html or "",
        "logo_url": version.logo_url or "",
        "created_by_user_id": version.created_by_user_id,
        "created_at": version.created_at.isoformat() if version.created_at else None,
    }


@router.get("/{integration_id}/templates")
def list_integration_templates(
    integration_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _owned_integration(db, integration_id, current_user)
    from app.services.document_intake.template_renderer import seed_default_templates
    seed_default_templates(db)
    templates = db.query(EmailTemplate).filter(
        (EmailTemplate.integration_id == integration_id) | EmailTemplate.integration_id.is_(None)
    ).order_by(EmailTemplate.template_key, EmailTemplate.integration_id.desc()).all()
    resolved = {}
    for template in templates:
        resolved.setdefault(template.template_key, template)
    return [_template_out(template) for template in resolved.values()]


@router.put("/{integration_id}/templates/{template_key}")
def update_integration_template(
    integration_id: int,
    template_key: str,
    payload: TemplateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _owned_integration(db, integration_id, current_user)
    from app.services.document_intake.template_renderer import _DEFAULT_TEMPLATES
    if template_key not in _DEFAULT_TEMPLATES:
        raise HTTPException(status_code=404, detail="Unknown template")
    template = db.query(EmailTemplate).filter(
        EmailTemplate.integration_id == integration_id,
        EmailTemplate.template_key == template_key,
        EmailTemplate.locale == "en",
    ).first()
    if not template:
        default_subject, default_body = _DEFAULT_TEMPLATES[template_key]
        template = EmailTemplate(
            integration_id=integration_id,
            template_key=template_key,
            locale="en",
            subject_template=default_subject,
            html_body_template=default_body,
        )
        db.add(template)
        db.flush()
    db.add(EmailTemplateVersion(
        template_id=template.id,
        template_key=template.template_key,
        subject_template=template.subject_template,
        html_body_template=template.html_body_template,
        signature_html=template.signature_html,
        logo_url=template.logo_url,
        created_by_user_id=current_user.id,
    ))
    for field_name, value in payload.model_dump(exclude_unset=True).items():
        setattr(template, field_name, value)
    db.commit()
    db.refresh(template)
    return _template_out(template)


@router.get("/{integration_id}/templates/{template_key}/versions")
def list_template_versions(
    integration_id: int,
    template_key: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _owned_integration(db, integration_id, current_user)
    template = db.query(EmailTemplate).filter(
        EmailTemplate.integration_id == integration_id,
        EmailTemplate.template_key == template_key,
    ).first()
    if not template:
        return []
    return [_version_out(version) for version in db.query(EmailTemplateVersion).filter(
        EmailTemplateVersion.template_id == template.id,
    ).order_by(EmailTemplateVersion.created_at.desc()).limit(20).all()]


@router.post("/{integration_id}/templates/{template_key}/reset")
def reset_integration_template(
    integration_id: int,
    template_key: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _owned_integration(db, integration_id, current_user)
    from app.services.document_intake.template_renderer import _DEFAULT_TEMPLATES
    if template_key not in _DEFAULT_TEMPLATES:
        raise HTTPException(status_code=404, detail="Unknown template")
    template = db.query(EmailTemplate).filter(
        EmailTemplate.integration_id == integration_id,
        EmailTemplate.template_key == template_key,
        EmailTemplate.locale == "en",
    ).first()
    if not template:
        return {"message": "Template already uses the default", "reset": False}
    db.add(EmailTemplateVersion(
        template_id=template.id,
        template_key=template.template_key,
        subject_template=template.subject_template,
        html_body_template=template.html_body_template,
        signature_html=template.signature_html,
        logo_url=template.logo_url,
        created_by_user_id=current_user.id,
    ))
    template.subject_template, template.html_body_template = _DEFAULT_TEMPLATES[template_key]
    template.signature_html = None
    template.logo_url = None
    template.is_active = True
    db.commit()
    db.refresh(template)
    return _template_out(template)


@router.post("/{integration_id}/templates/{template_key}/test")
def test_integration_template(
    integration_id: int,
    template_key: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    integration = _owned_integration(db, integration_id, current_user)
    if integration.provider != "gmail":
        raise HTTPException(status_code=501, detail="Test email is currently available for Gmail integrations")
    if template_key not in {"success", "failure"}:
        raise HTTPException(status_code=400, detail="Only success and failure templates can be tested")
    from app.services.document_intake.template_renderer import render_template
    from app.services.gmail_send import send_reply_via_gmail
    rendered = render_template(
        db,
        template_key,
        {"subject": "Template preview", "batch_no": "TEST-PROD-000001", "reason": "This is a test failure reason."},
        integration_id=integration.id,
    )
    email = Email(
        integration_id=integration.id,
        message_id=f"template-test-{integration.id}-{template_key}",
        subject="Template test",
        sender_email=integration.email_address,
        recipient_email=integration.email_address,
    )
    reply = EmailReply(subject=rendered.subject, body=rendered.html_body, is_draft=False)
    sent, error = send_reply_via_gmail(email, reply)
    if not sent:
        raise HTTPException(status_code=502, detail=error or "Test email could not be sent")
    return {"message": f"Test {template_key} email sent to {integration.email_address}"}


# ── Gmail ─────────────────────────────────────────────────────
@router.get("/gmail/auth-url")
def gmail_auth_url(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the Google OAuth2 authorization URL."""
    if not settings.GMAIL_CLIENT_ID or not settings.GMAIL_CLIENT_SECRET:
        raise HTTPException(
            status_code=501,
            detail="Gmail OAuth is not configured. Set GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET in backend/.env",
        )
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": settings.GMAIL_CLIENT_ID,
                "client_secret": settings.GMAIL_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [settings.GMAIL_REDIRECT_URI],
            }
        },
        scopes=[
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/gmail.send",
        ],
    )
    flow.redirect_uri = settings.GMAIL_REDIRECT_URI
    auth_url, _ = flow.authorization_url(
        prompt="consent",
        access_type="offline",
        include_granted_scopes=False,
        state=_oauth_state(db, current_user, "gmail"),
    )
    return {"auth_url": auth_url}


@router.get("/gmail/callback")
def gmail_callback(
    code: str = Query(None),
    error: str = Query(None),
    state: str = Query(...),
    db: Session = Depends(get_db),
):
    """Handle Gmail OAuth callback."""
    frontend_base = settings.FRONTEND_URL.rstrip("/")
    oauth_user_id = _require_oauth_user_id(db, state, "gmail")
    if error:
        return RedirectResponse(
            url=f"{frontend_base}/integrations?error={error}"
        )
    if not code:
        return RedirectResponse(
            url=f"{frontend_base}/integrations?error=missing_code"
        )
    if not settings.GMAIL_CLIENT_ID or not settings.GMAIL_CLIENT_SECRET:
        raise HTTPException(status_code=501, detail="Gmail OAuth is not configured.")
    try:
        from google_auth_oauthlib.flow import Flow
        from googleapiclient.discovery import build

        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": settings.GMAIL_CLIENT_ID,
                    "client_secret": settings.GMAIL_CLIENT_SECRET,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [settings.GMAIL_REDIRECT_URI],
                }
            },
            scopes=[
                "openid",
                "https://www.googleapis.com/auth/userinfo.email",
                "https://www.googleapis.com/auth/gmail.modify",
                "https://www.googleapis.com/auth/gmail.send",
            ],
        )
        flow.redirect_uri = settings.GMAIL_REDIRECT_URI
        flow.fetch_token(code=code)
        credentials = flow.credentials

        # Ensure the returned credentials include the gmail.send scope we requested.
        returned_scopes = getattr(credentials, "scopes", None) or []
        if "https://www.googleapis.com/auth/gmail.send" not in returned_scopes:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Gmail OAuth failed: missing gmail.send scope. "
                    "Please re-authorize and grant the Send permission (try an incognito window)."
                ),
            )

        # Get user email
        service = build("oauth2", "v2", credentials=credentials)
        user_info = service.userinfo().get().execute()
        email_address = user_info["email"]

        # Save or update integration
        integration = (
            db.query(EmailIntegration)
            .filter(EmailIntegration.email_address == email_address)
            .first()
        )
        if not integration:
            integration = EmailIntegration(
                provider="gmail",
                email_address=email_address,
                owner_user_id=oauth_user_id,
            )
            db.add(integration)
        elif integration.owner_user_id not in (None, oauth_user_id):
            raise HTTPException(status_code=409, detail="This mailbox is already owned by another user")
        elif integration.owner_user_id is None:
            integration.owner_user_id = oauth_user_id

        integration.access_token  = encrypt_token(credentials.token)
        integration.refresh_token = encrypt_token(credentials.refresh_token) if credentials.refresh_token else integration.refresh_token
        integration.is_active     = True
        db.commit()

        return RedirectResponse(url=f"{frontend_base}/settings?connected=gmail")

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Gmail OAuth failed: {exc}")


# ── Outlook ───────────────────────────────────────────────────
@router.get("/outlook/auth-url")
def outlook_auth_url(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the Microsoft OAuth2 authorization URL."""
    if not settings.OUTLOOK_CLIENT_ID or not settings.OUTLOOK_CLIENT_SECRET:
        raise HTTPException(
            status_code=501,
            detail="Outlook OAuth is not configured. Set OUTLOOK_CLIENT_ID and OUTLOOK_CLIENT_SECRET in backend/.env",
        )
    import msal

    authority = f"https://login.microsoftonline.com/{settings.OUTLOOK_TENANT_ID}"
    app = msal.ConfidentialClientApplication(
        settings.OUTLOOK_CLIENT_ID,
        authority=authority,
        client_credential=settings.OUTLOOK_CLIENT_SECRET,
    )
    auth_url = app.get_authorization_request_url(
        scopes=["Mail.Read", "Mail.ReadWrite", "Mail.Send", "User.Read", "offline_access"],
        redirect_uri=settings.OUTLOOK_REDIRECT_URI,
        state=_oauth_state(db, current_user, "outlook"),
    )
    return {"auth_url": auth_url}


@router.get("/outlook/callback")
def outlook_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_db),
):
    """Handle Outlook OAuth callback."""
    try:
        import msal

        oauth_user_id = _require_oauth_user_id(db, state, "outlook")

        authority = f"https://login.microsoftonline.com/{settings.OUTLOOK_TENANT_ID}"
        app = msal.ConfidentialClientApplication(
            settings.OUTLOOK_CLIENT_ID,
            authority=authority,
            client_credential=settings.OUTLOOK_CLIENT_SECRET,
        )
        result = app.acquire_token_by_authorization_code(
            code,
            scopes=["Mail.Read", "Mail.ReadWrite", "Mail.Send", "User.Read", "offline_access"],
            redirect_uri=settings.OUTLOOK_REDIRECT_URI,
        )

        if "error" in result:
            raise HTTPException(status_code=400, detail=result.get("error_description", "OAuth failed"))

        import httpx
        headers = {"Authorization": f"Bearer {result['access_token']}"}
        me = httpx.get("https://graph.microsoft.com/v1.0/me", headers=headers).json()
        email_address = me.get("mail") or me.get("userPrincipalName")

        integration = (
            db.query(EmailIntegration)
            .filter(EmailIntegration.email_address == email_address)
            .first()
        )
        if not integration:
            integration = EmailIntegration(
                provider="outlook",
                email_address=email_address,
                owner_user_id=oauth_user_id,
            )
            db.add(integration)
        elif integration.owner_user_id not in (None, oauth_user_id):
            raise HTTPException(status_code=409, detail="This mailbox is already owned by another user")
        elif integration.owner_user_id is None:
            integration.owner_user_id = oauth_user_id

        integration.access_token  = encrypt_token(result["access_token"])
        if result.get("refresh_token"):
            integration.refresh_token = encrypt_token(result.get("refresh_token"))
        integration.is_active     = True
        db.commit()

        frontend_base = settings.FRONTEND_URL.rstrip("/")
        return RedirectResponse(url=f"{frontend_base}/settings?connected=outlook")

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Outlook OAuth failed: {exc}")


@router.delete("/{integration_id}")
def disconnect_integration(
    integration_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    integration = db.query(EmailIntegration).filter(
        EmailIntegration.id == integration_id
    ).first()
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    if current_user.role != "admin" and integration.owner_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only manage your own integration")
    integration.is_active     = False
    integration.access_token  = None
    integration.refresh_token = None
    db.commit()
    return {"message": "Integration disconnected"}


class IntegrationSettingsUpdate(BaseModel):
    """Per-mailbox processing settings, configurable by the mailbox owner or an admin."""
    batch_prefix: Optional[str] = None
    mailbox_type: Optional[str] = None                 # PROD | UAT | DEV
    processing_mode: Optional[str] = None              # conversation | document_intake | both
    conversation_analysis_enabled: Optional[bool] = None
    allowed_extensions: Optional[str] = None
    max_file_size_mb: Optional[int] = None
    auto_reply_no_attachment: Optional[bool] = None
    auto_reply_invalid_domain: Optional[bool] = None
    success_auto_reply_enabled: Optional[bool] = None
    failure_auto_reply_enabled: Optional[bool] = None
    success_folder_label: Optional[str] = None
    failed_folder_label: Optional[str] = None
    storage_provider: Optional[str] = None
    callback_webhook_url: Optional[str] = None
    callback_auth_header: Optional[str] = None
    callback_enabled: Optional[bool] = None
    retention_days: Optional[int] = None
    owner_user_id: Optional[int] = None


@router.patch("/{integration_id}")
def update_integration_settings(
    integration_id: int,
    payload: IntegrationSettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update document-intake settings for an integration (batch prefix, folder labels, callback, retention)."""
    integration = db.query(EmailIntegration).filter(EmailIntegration.id == integration_id).first()
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    if current_user.role != "admin" and integration.owner_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only manage your own integration")
    if payload.owner_user_id is not None and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can assign integration ownership")

    updates = payload.model_dump(exclude_unset=True)
    if payload.callback_webhook_url:
        try:
            validate_callback_url(payload.callback_webhook_url)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    if payload.callback_enabled and not (payload.callback_webhook_url or integration.callback_webhook_url):
        raise HTTPException(status_code=422, detail="callback_webhook_url is required when callbacks are enabled")
    for field_name, value in updates.items():
        if field_name == "callback_auth_header" and value:
            value = encrypt_token(value)
        setattr(integration, field_name, value)

    db.commit()
    db.refresh(integration)
    return {"message": "Integration settings updated", "integration_id": integration.id}
