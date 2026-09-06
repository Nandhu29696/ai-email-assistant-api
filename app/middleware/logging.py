"""
Request logging middleware — writes every API call to api_request_logs.
Skips health-check, docs, static, and WebSocket paths to reduce noise.
"""
from __future__ import annotations
import asyncio
import time
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from jose import JWTError, jwt
from loguru import logger

from app.config import settings

# Paths to skip (not worth logging)
_SKIP_PREFIXES = ("/docs", "/redoc", "/openapi", "/health", "/ws/", "/static")


def _write_log_in_thread(**kwargs):
    """Write log row to DB in a worker thread so main ASGI event loop is never blocked."""
    try:
        from app.database import SessionLocal
        from app.models.user import ApiRequestLog
        db = SessionLocal()
        try:
            db.add(ApiRequestLog(**kwargs))
            db.commit()
        finally:
            db.close()
    except Exception as exc:
        logger.debug(f"RequestLoggingMiddleware: failed to write log: {exc}")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path

        # Skip noisy paths
        if any(path.startswith(p) for p in _SKIP_PREFIXES):
            return await call_next(request)

        start    = time.perf_counter()
        response = await call_next(request)
        elapsed  = int((time.perf_counter() - start) * 1000)

        # Persist only slow requests; normal request telemetry belongs in logs.
        if elapsed < settings.API_REQUEST_LOG_MIN_MS:
            return response

        # Try to extract user_id from bearer token (best-effort — never crash)
        user_id: int | None = None
        try:
            auth = request.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                payload = jwt.decode(
                    auth[7:], settings.SECRET_KEY,
                    algorithms=[settings.ALGORITHM],
                    options={"verify_exp": False},
                )
                raw = payload.get("sub")
                user_id = int(raw) if raw else None
        except (JWTError, ValueError, TypeError):
            pass

        # Write log in background thread without blocking HTTP response
        ip = request.headers.get("X-Forwarded-For", "")
        ip = ip.split(",")[0].strip() if ip else (request.client.host if request.client else "unknown")

        asyncio.create_task(asyncio.to_thread(
            _write_log_in_thread,
            user_id=user_id,
            method=request.method,
            path=path,
            query_params=str(request.query_params) or None,
            status_code=response.status_code,
            response_time_ms=elapsed,
            ip_address=ip,
            user_agent=request.headers.get("User-Agent", "")[:512],
            error_detail=None,
        ))

        return response
