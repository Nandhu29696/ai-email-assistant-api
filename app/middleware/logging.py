"""
Request logging middleware — writes slow requests, client/server errors and
unhandled exceptions to api_request_logs.
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

# Keep references so pending writes are not garbage-collected mid-flight.
_pending_writes: set[asyncio.Task] = set()


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


def _user_id_from_request(request: Request) -> int | None:
    try:
        auth = request.headers.get("Authorization", "")
        token = auth[7:] if auth.startswith("Bearer ") else request.cookies.get("ea_access")
        if token:
            payload = jwt.decode(
                token, settings.SECRET_KEY,
                algorithms=[settings.ALGORITHM],
                options={"verify_exp": False},
            )
            raw = payload.get("sub")
            return int(raw) if raw else None
    except (JWTError, ValueError, TypeError):
        pass
    return None


def _schedule_write(**kwargs) -> None:
    task = asyncio.create_task(asyncio.to_thread(_write_log_in_thread, **kwargs))
    _pending_writes.add(task)
    task.add_done_callback(_pending_writes.discard)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path

        # Skip noisy paths
        if any(path.startswith(p) for p in _SKIP_PREFIXES):
            return await call_next(request)

        start = time.perf_counter()
        error_detail: str | None = None
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception as exc:
            error_detail = f"{type(exc).__name__}: {exc}"[:2000]
            raise
        finally:
            elapsed = int((time.perf_counter() - start) * 1000)
            # Persist slow requests and every error; normal traffic belongs in logs.
            if elapsed >= settings.API_REQUEST_LOG_MIN_MS or status_code >= 400 or error_detail:
                ip = request.headers.get("X-Forwarded-For", "")
                ip = ip.split(",")[0].strip() if ip else (request.client.host if request.client else "unknown")
                _schedule_write(
                    user_id=_user_id_from_request(request),
                    method=request.method,
                    path=path,
                    query_params=str(request.query_params) or None,
                    status_code=status_code,
                    response_time_ms=elapsed,
                    ip_address=ip[:45],
                    user_agent=request.headers.get("User-Agent", "")[:512],
                    error_detail=error_detail,
                )

        return response
