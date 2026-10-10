from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
import asyncio
from typing import Any

from app.config import settings
from app.database import SessionLocal
from app.routers import dashboard, integrations, domains, document_intake
from app.routers.auth import router as auth_router
from app.routers.admin import router as admin_router
from app.routers.logs import router as logs_router
from app.routers.team import router as team_router
from app.services.gmail_sync import start_email_poller
from app.middleware.logging import RequestLoggingMiddleware
from app.observability import RequestContextMiddleware, configure_logging, metrics_response
import app.jobs  # noqa: F401  (registers background job functions)

configure_logging()

# ── Start-up ──────────────────────────────────────────────────
def _seed_templates():
    from app.services.document_intake.template_renderer import seed_default_templates

    db = SessionLocal()
    try:
        seed_default_templates(db)
    except Exception as exc:
        logger.error(f"Template seeding failed: {exc}")
        db.rollback()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Starting application")
    _seed_templates()

    poller: asyncio.Task | None = None
    if settings.RUN_BACKGROUND_WORKERS:
        # New mail is picked up and processed inside this process, so nothing
        # else has to be started. Production can run app.worker instead.
        from app.jobs.queue import use_inline_only
        use_inline_only(True)
        poller = asyncio.create_task(start_email_poller())

    yield

    logger.info("🛑 Shutting down")
    if poller:
        poller.cancel()
        try:
            await poller
        except asyncio.CancelledError:
            pass


# ── FastAPI App ───────────────────────────────────────────────
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Automatic email intake: domain check, acknowledgement, attachment validation, PDF conversion and merge",
    docs_url="/docs" if settings.ENABLE_API_DOCS else None,
    redoc_url="/redoc" if settings.ENABLE_API_DOCS else None,
    openapi_url="/openapi.json" if settings.ENABLE_API_DOCS else None,
    lifespan=lifespan,
)


# ── Middleware ────────────────────────────────────────────────
# Add request logging first so CORS remains outermost and headers
# are still attached when downstream handlers fail.
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(RequestContextMiddleware)

@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if not request.url.path.startswith(("/docs", "/redoc")):
        response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
    if settings.IS_PRODUCTION:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


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
app.include_router(team_router, prefix="/api/team", tags=["Team"])
app.include_router(logs_router, prefix="/api/logs", tags=["Logs"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["Dashboard"])
app.include_router(integrations.router, prefix="/api/integrations", tags=["Mailboxes"])
app.include_router(domains.router, prefix="/api/domains", tags=["Domains"])
app.include_router(document_intake.router, prefix="/api/document-intake", tags=["Emails"])


# ── Health, readiness and metrics ─────────────────────────────
_llm_health_cache: dict[str, Any] = {"checked_at": 0.0, "ok": None, "detail": None}


def llm_model_status(status_code: int, payload: dict | None, model: str, provider: str) -> tuple[bool, str]:
    """Interpret the LLM backend's model listing: reachable AND the configured model is available."""
    if status_code >= 400:
        return False, f"HTTP {status_code}"
    payload = payload or {}
    if provider == "ollama":
        names = {m.get("name", "") for m in payload.get("models", [])}
        # Ollama lists "llama3.2:latest"; the config may say "llama3.2".
        available = model in names or f"{model}:latest" in names
    else:
        available = model in {m.get("id", "") for m in payload.get("data", [])}
    if not available:
        return False, f"model '{model}' is not available on the {provider} server"
    return True, f"model '{model}' available"


async def _check_llm() -> tuple[bool | None, str | None]:
    """Probe the LLM backend: reachable and the configured model installed (cached for 60s)."""
    import time
    import httpx
    from app.services.ai_client import ai_available, get_model

    if not settings.HEALTH_CHECK_LLM or not ai_available():
        return None, "not configured"
    if time.monotonic() - _llm_health_cache["checked_at"] < 60:
        return _llm_health_cache["ok"], _llm_health_cache["detail"]
    provider = "ollama" if settings.OLLAMA_BASE_URL else "openai"
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            if provider == "ollama":
                response = await client.get(f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/tags")
            else:
                response = await client.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
                )
        try:
            payload = response.json()
        except ValueError:
            payload = None
        ok, detail = llm_model_status(response.status_code, payload, get_model(), provider)
    except Exception as exc:
        ok, detail = False, type(exc).__name__
    _llm_health_cache.update(checked_at=time.monotonic(), ok=ok, detail=detail)
    return ok, detail


async def _check_redis() -> bool | None:
    if not settings.REDIS_URL:
        return None
    try:
        import redis.asyncio as aioredis
        client = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
        try:
            return bool(await client.ping())
        finally:
            await client.aclose()
    except Exception:
        return False


def _check_database() -> bool:
    from sqlalchemy import text
    try:
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
        finally:
            db.close()
        return True
    except Exception as exc:
        logger.error(f"Health check database error: {exc}")
        return False


@app.get("/health/live", tags=["System"])
def liveness():
    """Process is up (no dependency checks) — for container liveness probes."""
    return {"status": "ok"}


@app.get("/health", tags=["System"])
async def health_check():
    """Readiness: database is required (503 if down); Redis and the LLM degrade gracefully."""
    from fastapi.responses import JSONResponse

    db_ok = await asyncio.to_thread(_check_database)
    redis_ok = await _check_redis()
    llm_ok, llm_detail = await _check_llm()
    from app.services.document_intake.conversion.doc_to_pdf import converter_status
    converter_ok, converter_detail = converter_status()
    degraded = llm_ok is False or not converter_ok
    body = {
        "status": "down" if not db_ok else ("degraded" if degraded else "ok"),
        "version": settings.APP_VERSION,
        "database": db_ok,
        "redis": redis_ok,
        "llm": {"ok": llm_ok, "detail": llm_detail},
        "converter": {"ok": converter_ok, "detail": converter_detail},
        "mail_pickup": "api" if settings.RUN_BACKGROUND_WORKERS else "worker",
        "ops_alerts": bool(settings.OPS_ALERT_WEBHOOK_URL),
    }
    return JSONResponse(body, status_code=200 if db_ok else 503)


@app.get("/metrics", include_in_schema=False)
def metrics(request: Request):
    """Prometheus metrics (set METRICS_TOKEN to require a bearer token)."""
    if not settings.METRICS_ENABLED:
        from fastapi.responses import Response
        return Response(status_code=404)
    return metrics_response(request)
