"""Structured logging, request ids and Prometheus metrics."""
from __future__ import annotations

import logging
import sys
import time
import uuid

from loguru import logger
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.config import settings

# ── Metrics ───────────────────────────────────────────────────
HTTP_REQUESTS = Counter(
    "http_requests_total", "HTTP requests", ["method", "route", "status"],
)
HTTP_LATENCY = Histogram(
    "http_request_duration_seconds", "HTTP request latency", ["method", "route"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)
JOBS_TOTAL = Counter("jobs_total", "Background job outcomes", ["job", "outcome"])
JOB_DURATION = Histogram(
    "job_duration_seconds", "Background job duration", ["job"],
    buckets=(0.1, 0.5, 1, 5, 15, 30, 60, 120, 300, 600),
)
EMAILS_INGESTED = Counter("emails_ingested_total", "Inbound emails saved", ["provider"])
AUTO_REPLIES = Counter("auto_replies_total", "Auto-reply decisions", ["outcome"])
LLM_CALLS = Counter("llm_calls_total", "LLM calls", ["purpose", "outcome"])


# ── Logging ───────────────────────────────────────────────────
class _InterceptHandler(logging.Handler):
    """Route stdlib logging (uvicorn, sqlalchemy, arq) through loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        logger.opt(depth=6, exception=record.exc_info).log(level, record.getMessage())


_configured = False


def configure_logging() -> None:
    global _configured
    if _configured:
        return
    _configured = True
    logger.remove()
    if settings.LOG_FORMAT.lower() == "json":
        # One JSON object per line including bound context (request_id, job, ...).
        logger.add(sys.stdout, level=settings.LOG_LEVEL.upper(), serialize=True, backtrace=False)
    else:
        logger.add(
            sys.stderr, level=settings.LOG_LEVEL.upper(),
            format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | "
                   "{extra[request_id]} | <cyan>{name}</cyan>:<cyan>{function}</cyan>:{line} - <level>{message}</level>",
        )
    logger.configure(extra={"request_id": "-"})
    logging.basicConfig(handlers=[_InterceptHandler()], level=logging.getLevelName(settings.LOG_LEVEL.upper()), force=True)
    for noisy in ("uvicorn.access",):
        logging.getLogger(noisy).handlers = [_InterceptHandler()]


# ── Middleware ────────────────────────────────────────────────
class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns/propagates X-Request-ID, binds it to log records and records metrics."""

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.state.request_id = request_id
        start = time.perf_counter()
        status = 500
        with logger.contextualize(request_id=request_id):
            try:
                response = await call_next(request)
                status = response.status_code
            finally:
                route = request.scope.get("route")
                route_path = getattr(route, "path", "unmatched")
                if route_path not in ("/metrics", "/health", "/health/live"):
                    elapsed = time.perf_counter() - start
                    HTTP_REQUESTS.labels(request.method, route_path, str(status)).inc()
                    HTTP_LATENCY.labels(request.method, route_path).observe(elapsed)
        response.headers["X-Request-ID"] = request_id
        return response


def metrics_response(request: Request) -> Response:
    if settings.METRICS_TOKEN:
        supplied = request.headers.get("Authorization", "")
        import hmac
        if not hmac.compare_digest(supplied, f"Bearer {settings.METRICS_TOKEN}"):
            return Response(status_code=401)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
