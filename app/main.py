from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
import asyncio
from typing import Any, cast

from app.config import settings
from app.database import SessionLocal
from app.models.user import User
from jose import JWTError, jwt
from app.routers import emails, analysis, dashboard, integrations
from app.routers import lookups, replies, domains, document_intake
from app.routers.auth import router as auth_router
from app.routers.admin import router as admin_router
from app.routers.logs import router as logs_router
from app.routers.reply_tracker import router as reply_tracker_router
from app.services.notification_service import notification_manager
from app.services.gmail_sync import start_email_poller
from app.middleware.logging import RequestLoggingMiddleware

# ── Seed lookup tables ────────────────────────────────────────
def _seed_lookups():
    from app.models.email import (
        SentimentOption,
        PriorityOption,
        CategoryOption,
        AllowedDomain,
    )

    db = SessionLocal()

    try:
        if db.query(SentimentOption).count() == 0:
            db.bulk_insert_mappings(
                cast(Any, SentimentOption),
                [
                    {"value": "positive", "label": "Positive", "color": "green", "sort_order": 1},
                    {"value": "neutral", "label": "Neutral", "color": "gray", "sort_order": 2},
                    {"value": "negative", "label": "Negative", "color": "red", "sort_order": 3},
                ],
            )

        if db.query(PriorityOption).count() == 0:
            db.bulk_insert_mappings(
                cast(Any, PriorityOption),
                [
                    {"value": "critical", "label": "Critical", "color": "red", "score": 4, "sort_order": 1},
                    {"value": "high", "label": "High", "color": "orange", "score": 3, "sort_order": 2},
                    {"value": "medium", "label": "Medium", "color": "yellow", "score": 2, "sort_order": 3},
                    {"value": "low", "label": "Low", "color": "blue", "score": 1, "sort_order": 4},
                ],
            )

        if db.query(CategoryOption).count() == 0:
            db.bulk_insert_mappings(
                cast(Any, CategoryOption),
                [
                    {"value": "complaint", "label": "Complaint", "description": "Customer complaints", "sort_order": 1},
                    {"value": "support", "label": "Support", "description": "Technical support requests", "sort_order": 2},
                    {"value": "sales", "label": "Sales", "description": "Sales inquiries and leads", "sort_order": 3},
                    {"value": "refund", "label": "Refund", "description": "Refund and cancellation", "sort_order": 4},
                    {"value": "invoice", "label": "Invoice", "description": "Billing queries", "sort_order": 5},
                    {"value": "feedback", "label": "Feedback", "description": "Product feedback", "sort_order": 6},
                    {"value": "general", "label": "General", "description": "General enquiries", "sort_order": 7},
                ],
            )

        if db.query(AllowedDomain).count() == 0:
            db.bulk_insert_mappings(
                cast(Any, AllowedDomain),
                [
                    {"domain": "gmail.com", "is_active": True, "notes": "Google Gmail"},
                    {"domain": "outlook.com", "is_active": True, "notes": "Microsoft Outlook"},
                    {"domain": "hotmail.com", "is_active": True, "notes": "Microsoft Hotmail"},
                    {"domain": "yahoo.com", "is_active": True, "notes": "Yahoo Mail"},
                    {"domain": "icloud.com", "is_active": True, "notes": "Apple iCloud Mail"},
                    {"domain": "protonmail.com", "is_active": True, "notes": "ProtonMail"},
                ],
            )

        db.commit()
        logger.info("Lookup tables seeded.")

    except Exception as exc:
        logger.error(f"Lookup seeding failed: {exc}")
        db.rollback()

    finally:
        db.close()


# ── Application Lifespan ──────────────────────────────────────
poller_task = None
retention_task = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global poller_task, retention_task

    logger.info("🚀 Starting application")

    _seed_lookups()

    if settings.RUN_BACKGROUND_WORKERS:
        poller_task = asyncio.create_task(start_email_poller())

        from app.services.document_intake.retention_service import start_retention_archiver
        retention_task = asyncio.create_task(start_retention_archiver())

    yield

    logger.info("🛑 Shutting down")

    for task in (poller_task, retention_task):
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

# ── FastAPI App ───────────────────────────────────────────────
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="AI-powered email management system with sentiment analysis and NLP",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


# ── Middleware ────────────────────────────────────────────────
# Add request logging first so CORS remains outermost and headers
# are still attached when downstream handlers fail.
app.add_middleware(RequestLoggingMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Routers ───────────────────────────────────────────────────
app.include_router(auth_router, prefix="/api/auth", tags=["Auth"])
app.include_router(admin_router, prefix="/api/admin", tags=["Admin"])
app.include_router(logs_router, prefix="/api/logs", tags=["Logs"])
app.include_router(emails.router, prefix="/api/emails", tags=["Emails"])
app.include_router(analysis.router, prefix="/api/analysis", tags=["Analysis"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["Dashboard"])
app.include_router(integrations.router, prefix="/api/integrations", tags=["Integrations"])
app.include_router(lookups.router, prefix="/api/lookups", tags=["Lookups"])
app.include_router(replies.router, prefix="/api/emails", tags=["Replies"])
app.include_router(domains.router, prefix="/api/domains", tags=["Domains"])
app.include_router(reply_tracker_router, prefix="/api/reply-tracker", tags=["ReplyTracker"])
app.include_router(document_intake.router, prefix="/api/document-intake", tags=["DocumentIntake"])


# ── WebSocket – Real-time notifications ──────────────────────
@app.websocket("/ws/notifications")
async def websocket_notifications(websocket: WebSocket):
    token = websocket.query_params.get("access_token")
    if not token:
        await websocket.close(code=1008, reason="Authentication required")
        return
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("type") != "access":
            raise ValueError("Invalid token type")
        user_id = int(payload["sub"])
    except (JWTError, ValueError, TypeError, KeyError):
        await websocket.close(code=1008, reason="Invalid authentication token")
        return

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    finally:
        db.close()
    if not user:
        await websocket.close(code=1008, reason="Invalid authentication token")
        return

    await notification_manager.connect(
        websocket,
        user_id,
        cast(str, user.role),
    )

    try:
        while True:
            await asyncio.sleep(30)
            await websocket.send_json({"type": "ping"})

    except WebSocketDisconnect:
        notification_manager.disconnect(websocket)

    except Exception as exc:
        logger.error(f"WebSocket error: {exc}")
        notification_manager.disconnect(websocket)


# ── Health Check ──────────────────────────────────────────────
@app.get("/health", tags=["System"])
async def health_check():
    return {
        "status": "ok",
        "version": settings.APP_VERSION,
    }