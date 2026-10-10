"""
Mailboxes router — connect Gmail (OAuth), Outlook (OAuth) or IMAP mailboxes,
adjust their intake rules, trigger a sync, and receive push notifications.
"""
from __future__ import annotations
import asyncio
import base64
import hashlib
import hmac
import json
import re
import secrets
from typing import Optional
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, PlainTextResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session
from loguru import logger
from jose import JWTError, jwt
from datetime import datetime, timedelta, timezone

from app.database import get_db
from app.models.email import EmailIntegration
from app.models.user import User, OAuthState
from app.schemas.email import IntegrationOut
from app.config import settings
from app.utils.crypto import encrypt_token
from app.jobs.queue import enqueue
from app.access import owner_for_new_mailbox, owns, scope_mailboxes
from app.routers.auth import get_current_user, require_admin

router = APIRouter()


def _verify_webhook_secret(request: Request, expected: str) -> None:
    # Google Pub/Sub push cannot add custom headers, so a ?token= query
    # parameter on the push endpoint URL is accepted as well.
    supplied = request.headers.get("X-Webhook-Secret", "") or request.query_params.get("token", "")
    if not expected or not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid webhook credentials")


async def _queue_sync(integration_id: int) -> str:
    """Queue a mailbox sync; the job id coalesces bursts of push notifications."""
    return await enqueue("sync_mailbox", integration_id, job_id=f"sync:{integration_id}")


def _frontend_redirect(path: str, **params: str) -> RedirectResponse:
    query = "&".join(f"{k}={quote(str(v), safe='')}" for k, v in params.items())
    base = settings.FRONTEND_URL.rstrip("/")
    return RedirectResponse(url=f"{base}{path}{'?' + query if query else ''}")


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
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Queue an immediate sync of every active mailbox."""
    ids = [row.id for row in db.query(EmailIntegration.id).filter(EmailIntegration.is_active == True)]
    for integration_id in ids:
        await _queue_sync(integration_id)
    return {"message": f"Sync queued for {len(ids)} mailbox(es)"}


# ── Gmail Push Notification / PubSub Webhook ─────────────────
@router.post("/gmail/webhook")
async def gmail_push_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Endpoint for Google Cloud Pub/Sub Push subscriptions.
    Syncs only the mailbox named in the notification.
    """
    _verify_webhook_secret(request, settings.GMAIL_WEBHOOK_SECRET)
    email_address = None
    try:
        data = await request.json()
        encoded = (data.get("message") or {}).get("data")
        if encoded:
            decoded = json.loads(base64.b64decode(encoded + "=" * (-len(encoded) % 4)))
            email_address = decoded.get("emailAddress")
    except Exception as exc:
        logger.warning(f"[Gmail Webhook] Could not parse push payload: {exc}")

    if email_address:
        integration = db.query(EmailIntegration).filter(
            EmailIntegration.email_address == email_address,
            EmailIntegration.provider == "gmail",
            EmailIntegration.is_active == True,
        ).first()
        if not integration:
            return {"status": "ignored"}
        await _queue_sync(integration.id)
    else:
        for (integration_id,) in db.query(EmailIntegration.id).filter(
            EmailIntegration.provider == "gmail", EmailIntegration.is_active == True,
        ).all():
            await _queue_sync(integration_id)
    return {"status": "accepted"}


@router.post("/outlook/webhook")
async def outlook_graph_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    """Receive Microsoft Graph change notifications and sync the affected mailbox."""
    validation_token = request.query_params.get("validationToken")
    if validation_token:
        # Subscription validation handshake: echo the token as plain text.
        return PlainTextResponse(validation_token[:1024])

    expected_state = settings.OUTLOOK_WEBHOOK_CLIENT_STATE
    try:
        data = await request.json()
        notifications = data.get("value", []) if isinstance(data, dict) else []
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid notification payload")

    valid = [
        item for item in notifications
        if isinstance(item, dict) and expected_state
        and hmac.compare_digest(str(item.get("clientState", "")), expected_state)
    ]
    if not valid:
        raise HTTPException(status_code=401, detail="Invalid Outlook webhook client state")
    logger.info(f"[Outlook Webhook] Received {len(valid)} notification(s)")

    subscription_ids = {str(item.get("subscriptionId", "")) for item in valid}
    integrations = db.query(EmailIntegration.id).filter(
        EmailIntegration.outlook_subscription_id.in_(subscription_ids),
        EmailIntegration.is_active == True,
    ).all()
    for (integration_id,) in integrations:
        await _queue_sync(integration_id)
    return {"status": "accepted"}


@router.post("/outlook/subscription")
def create_outlook_subscription(
    integration_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a Microsoft Graph Inbox subscription for an owned Outlook integration."""
    if not settings.OUTLOOK_WEBHOOK_URL or not settings.OUTLOOK_WEBHOOK_CLIENT_STATE:
        raise HTTPException(
            status_code=501,
            detail="OUTLOOK_WEBHOOK_URL and OUTLOOK_WEBHOOK_CLIENT_STATE must be configured",
        )
    integration = db.query(EmailIntegration).filter(EmailIntegration.id == integration_id).first()
    if not integration or integration.provider != "outlook":
        raise HTTPException(status_code=404, detail="Outlook integration not found")
    if not owns(current_user, integration):
        raise HTTPException(status_code=403, detail="You can only manage your own integration")
    from app.services.document_intake.provider_adapters import OutlookGraphAdapter
    try:
        subscription = OutlookGraphAdapter(integration).create_subscription(settings.OUTLOOK_WEBHOOK_URL)
    except Exception as exc:
        logger.error(f"[Outlook] Subscription creation failed for {integration_id}: {exc}")
        raise HTTPException(status_code=502, detail="Could not create the Outlook subscription")
    return {"id": subscription.get("id"), "expirationDateTime": subscription.get("expirationDateTime")}


@router.post("/{integration_id}/sync")
async def sync_one_integration(
    integration_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Queue an immediate sync of one mailbox (owner or admin)."""
    _owned_integration(db, integration_id, current_user)
    status = await _queue_sync(integration_id)
    return {"message": "Mailbox sync already in progress" if status == "duplicate" else "Mailbox sync queued"}


# ── IMAP mailboxes ────────────────────────────────────────────
class ImapIntegrationCreate(BaseModel):
    email_address: str = Field(..., max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    imap_host: str = Field(..., min_length=1, max_length=255)
    imap_port: int = Field(993, ge=1, le=65535)
    imap_username: Optional[str] = Field(None, max_length=255)
    imap_password: str = Field(..., min_length=1, max_length=500)
    smtp_host: Optional[str] = Field(None, max_length=255)
    smtp_port: int = Field(465, ge=1, le=65535)
    smtp_username: Optional[str] = Field(None, max_length=255)
    smtp_password: Optional[str] = Field(None, max_length=500)
    owner_user_id: Optional[int] = None


@router.post("/imap", status_code=201)
async def create_imap_integration(
    payload: ImapIntegrationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Connect an IMAP/SMTP mailbox. The IMAP login is verified before saving."""
    from app.services.email_fetcher import IMAPFetcher

    owner_id = owner_for_new_mailbox(current_user)
    if payload.owner_user_id is not None:
        if current_user.role != "admin":
            raise HTTPException(status_code=403, detail="Only admins can assign integration ownership")
        if not db.query(User.id).filter(User.id == payload.owner_user_id, User.is_active == True, User.role != "user").first():
            raise HTTPException(status_code=422, detail="owner_user_id must reference an active client or admin")
        owner_id = payload.owner_user_id
    if db.query(EmailIntegration.id).filter(EmailIntegration.email_address == payload.email_address).first():
        raise HTTPException(status_code=409, detail="This mailbox is already connected")

    username = payload.imap_username or payload.email_address

    def _check_login():
        with IMAPFetcher(payload.imap_host, payload.imap_port, username, payload.imap_password, timeout=15):
            pass

    try:
        await asyncio.to_thread(_check_login)
    except Exception as exc:
        logger.warning(f"[IMAP] Connection test failed for {payload.email_address}: {exc}")
        raise HTTPException(status_code=422, detail="Could not log in to the IMAP server with these settings")

    integration = EmailIntegration(
        provider="imap",
        email_address=payload.email_address,
        owner_user_id=owner_id,
        imap_host=payload.imap_host,
        imap_port=payload.imap_port,
        imap_username=username,
        imap_password=encrypt_token(payload.imap_password),
        smtp_host=payload.smtp_host,
        smtp_port=payload.smtp_port,
        smtp_username=payload.smtp_username,
        smtp_password=encrypt_token(payload.smtp_password) if payload.smtp_password else None,
        is_active=True,
        process_since=datetime.now(timezone.utc),
        health_status="unknown",
    )
    db.add(integration)
    db.commit()
    db.refresh(integration)
    await _queue_sync(integration.id)
    return {"message": "IMAP mailbox connected", "integration_id": integration.id}


# ── List active integrations ──────────────────────────────────
@router.get("", response_model=list[IntegrationOut])
def list_integrations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(EmailIntegration).filter(EmailIntegration.is_active == True)
    query = scope_mailboxes(query, current_user)
    return query.order_by(EmailIntegration.created_at.desc()).all()


def _owned_integration(db: Session, integration_id: int, current_user: User) -> EmailIntegration:
    integration = db.query(EmailIntegration).filter(EmailIntegration.id == integration_id).first()
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    if not owns(current_user, integration):
        raise HTTPException(status_code=403, detail="You can only manage your own integration")
    return integration


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
    oauth_user_id = _require_oauth_user_id(db, state, "gmail")
    if error:
        return _frontend_redirect("/mailboxes", error=error[:100])
    if not code:
        return _frontend_redirect("/mailboxes", error="missing_code")
    if not settings.GMAIL_CLIENT_ID or not settings.GMAIL_CLIENT_SECRET:
        raise HTTPException(status_code=501, detail="Gmail OAuth is not configured.")
    try:
        from google_auth_oauthlib.flow import Flow
        from googleapiclient.discovery import build
        from app.services.gmail_client import GMAIL_SCOPES

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
            scopes=GMAIL_SCOPES,
        )
        flow.redirect_uri = settings.GMAIL_REDIRECT_URI
        flow.fetch_token(code=code)
        credentials = flow.credentials

        # Ensure the returned credentials include the gmail.send scope we requested.
        returned_scopes = getattr(credentials, "scopes", None) or []
        if "https://www.googleapis.com/auth/gmail.send" not in returned_scopes:
            return _frontend_redirect("/mailboxes", error="missing_send_scope")

        service = build("oauth2", "v2", credentials=credentials, cache_discovery=False)
        user_info = service.userinfo().get().execute()
        email_address = user_info["email"]

        connecting_user = db.get(User, oauth_user_id)
        oauth_user_id = owner_for_new_mailbox(connecting_user) if connecting_user else oauth_user_id
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
                is_active=False,   # set below; marks the mailbox as newly activated
            )
            db.add(integration)
        elif integration.provider != "gmail":
            return _frontend_redirect("/mailboxes", error="mailbox_connected_with_other_provider")
        elif integration.owner_user_id not in (None, oauth_user_id):
            return _frontend_redirect("/mailboxes", error="mailbox_owned_by_another_user")
        elif integration.owner_user_id is None:
            integration.owner_user_id = oauth_user_id

        if not integration.is_active or integration.process_since is None:
            integration.process_since = datetime.now(timezone.utc)
        integration.access_token  = encrypt_token(credentials.token)
        if credentials.refresh_token:
            integration.refresh_token = encrypt_token(credentials.refresh_token)
        if credentials.expiry:
            integration.token_expiry = credentials.expiry.replace(tzinfo=timezone.utc)
        integration.is_active     = True
        integration.health_status = "unknown"
        integration.health_message = None
        db.commit()

        return _frontend_redirect("/mailboxes", connected="gmail")

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(f"[Gmail OAuth] Callback failed: {exc}")
        db.rollback()
        return _frontend_redirect("/mailboxes", error="oauth_failed")


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
    code: str = Query(None),
    error: str = Query(None),
    state: str = Query(...),
    db: Session = Depends(get_db),
):
    """Handle Outlook OAuth callback."""
    oauth_user_id = _require_oauth_user_id(db, state, "outlook")
    if error:
        return _frontend_redirect("/mailboxes", error=error[:100])
    if not code:
        return _frontend_redirect("/mailboxes", error="missing_code")
    try:
        import msal
        import httpx

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
            logger.warning(f"[Outlook OAuth] Token exchange failed: {result.get('error_description')}")
            return _frontend_redirect("/mailboxes", error="oauth_failed")

        me_response = httpx.get(
            "https://graph.microsoft.com/v1.0/me",
            headers={"Authorization": f"Bearer {result['access_token']}"},
            timeout=15,
        )
        me_response.raise_for_status()
        me = me_response.json()
        email_address = me.get("mail") or me.get("userPrincipalName")
        if not email_address:
            return _frontend_redirect("/mailboxes", error="no_mailbox_address")

        connecting_user = db.get(User, oauth_user_id)
        oauth_user_id = owner_for_new_mailbox(connecting_user) if connecting_user else oauth_user_id
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
                is_active=False,   # set below; marks the mailbox as newly activated
            )
            db.add(integration)
        elif integration.provider != "outlook":
            return _frontend_redirect("/mailboxes", error="mailbox_connected_with_other_provider")
        elif integration.owner_user_id not in (None, oauth_user_id):
            return _frontend_redirect("/mailboxes", error="mailbox_owned_by_another_user")
        elif integration.owner_user_id is None:
            integration.owner_user_id = oauth_user_id

        if not integration.is_active or integration.process_since is None:
            integration.process_since = datetime.now(timezone.utc)
        integration.access_token  = encrypt_token(result["access_token"])
        if result.get("refresh_token"):
            integration.refresh_token = encrypt_token(result.get("refresh_token"))
        if result.get("expires_in"):
            integration.token_expiry = datetime.now(timezone.utc) + timedelta(seconds=int(result["expires_in"]))
        integration.is_active     = True
        integration.health_status = "unknown"
        integration.health_message = None
        db.commit()

        return _frontend_redirect("/mailboxes", connected="outlook")

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(f"[Outlook OAuth] Callback failed: {exc}")
        db.rollback()
        return _frontend_redirect("/mailboxes", error="oauth_failed")


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
    if not owns(current_user, integration):
        raise HTTPException(status_code=403, detail="You can only manage your own integration")
    integration.is_active     = False
    integration.access_token  = None
    integration.refresh_token = None
    db.commit()
    return {"message": "Integration disconnected"}


_VALID_EXTENSIONS = {"pdf", "doc", "docx", "tiff", "tif"}


class IntegrationSettingsUpdate(BaseModel):
    """Per-mailbox intake rules. Every field is optional — defaults work out of the box."""
    batch_prefix: Optional[str] = Field(None, pattern=r"^[A-Za-z0-9]{1,10}$")
    mailbox_type: Optional[str] = Field(None, pattern=r"^(PROD|UAT|DEV)$")
    allowed_extensions: Optional[str] = Field(None, max_length=100)
    max_file_size_mb: Optional[int] = Field(None, ge=1, le=100)
    allowed_sender_domains: Optional[str] = Field(None, max_length=5000)
    retention_days: Optional[int] = Field(None, ge=1, le=3650)
    # Seconds between checks for new email; null = global default.
    fetch_interval_seconds: Optional[int] = Field(None, ge=15, le=3600)
    owner_user_id: Optional[int] = None

    @field_validator("allowed_sender_domains")
    @classmethod
    def valid_domains(cls, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        domains = [d.strip().lower().lstrip("@") for d in re.split(r"[,\s]+", value) if d.strip()]
        bad = [d for d in domains if not re.match(r"^([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$", d)]
        if bad:
            raise ValueError(f"Invalid domain(s): {', '.join(bad[:5])}")
        return ",".join(dict.fromkeys(domains))

    @field_validator("allowed_extensions")
    @classmethod
    def known_extensions(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        items = [e.strip().lower().lstrip(".") for e in value.split(",") if e.strip()]
        unknown = sorted(set(items) - _VALID_EXTENSIONS)
        if not items or unknown:
            raise ValueError(f"Allowed extensions must be a subset of {sorted(_VALID_EXTENSIONS)}")
        return ",".join(dict.fromkeys(items))

    @field_validator("batch_prefix", "mailbox_type")
    @classmethod
    def upper(cls, value: Optional[str]) -> Optional[str]:
        return value.upper() if value else value


@router.patch("/{integration_id}")
def update_integration_settings(
    integration_id: int,
    payload: IntegrationSettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a mailbox's intake rules (prefix, accepted file types/size, sender domains)."""
    integration = _owned_integration(db, integration_id, current_user)
    if payload.owner_user_id is not None and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can assign mailbox ownership")
    if payload.owner_user_id is not None and not db.query(User.id).filter(
        User.id == payload.owner_user_id, User.is_active == True, User.role != "user"
    ).first():
        raise HTTPException(status_code=422, detail="owner_user_id must reference an active client or admin")

    for field_name, value in payload.model_dump(exclude_unset=True).items():
        setattr(integration, field_name, value)
    db.commit()
    db.refresh(integration)
    return {"message": "Mailbox settings updated", "integration_id": integration.id}
