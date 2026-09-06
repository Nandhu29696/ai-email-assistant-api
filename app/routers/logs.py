"""
Logs router — audit trail and API request logs. Admin-only.
"""
from __future__ import annotations
from typing import Optional
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models.user import User, AuditLog, ApiRequestLog
from app.routers.auth import require_admin

router = APIRouter()


@router.get("/audit")
def list_audit_logs(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
    user_id: Optional[int] = Query(None),
    action: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    days: int = Query(7, ge=1, le=90),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    q = db.query(AuditLog).filter(AuditLog.created_at >= since)

    if user_id:
        q = q.filter(AuditLog.user_id == user_id)
    if action:
        q = q.filter(AuditLog.action.ilike(f"%{action}%"))
    if status:
        q = q.filter(AuditLog.status == status)

    total = q.count()
    items = (
        q.order_by(AuditLog.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": l.id,
                "user_id": l.user_id,
                "action": l.action,
                "resource_type": l.resource_type,
                "resource_id": l.resource_id,
                "ip_address": l.ip_address,
                "user_agent": l.user_agent,
                "status": l.status,
                "details": l.details,
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
            for l in items
        ],
    }


@router.get("/requests")
def list_api_logs(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
    path: Optional[str] = Query(None),
    method: Optional[str] = Query(None),
    status_code: Optional[int] = Query(None),
    user_id: Optional[int] = Query(None),
    min_response_ms: Optional[int] = Query(None),
    days: int = Query(1, ge=1, le=30),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    q = db.query(ApiRequestLog).filter(ApiRequestLog.created_at >= since)

    if path:
        q = q.filter(ApiRequestLog.path.ilike(f"%{path}%"))
    if method:
        q = q.filter(ApiRequestLog.method == method.upper())
    if status_code:
        q = q.filter(ApiRequestLog.status_code == status_code)
    if user_id:
        q = q.filter(ApiRequestLog.user_id == user_id)
    if min_response_ms:
        q = q.filter(ApiRequestLog.response_time_ms >= min_response_ms)

    total = q.count()
    items = (
        q.order_by(ApiRequestLog.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": l.id,
                "user_id": l.user_id,
                "method": l.method,
                "path": l.path,
                "query_params": l.query_params,
                "status_code": l.status_code,
                "response_time_ms": l.response_time_ms,
                "ip_address": l.ip_address,
                "user_agent": l.user_agent,
                "error_detail": l.error_detail,
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
            for l in items
        ],
    }


@router.get("/summary")
def logs_summary(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
    days: int = Query(7, ge=1, le=30),
):
    """Aggregated metrics for the monitoring dashboard."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # Top actions
    top_actions = (
        db.query(AuditLog.action, func.count(AuditLog.id).label("count"))
        .filter(AuditLog.created_at >= since)
        .group_by(AuditLog.action)
        .order_by(func.count(AuditLog.id).desc())
        .limit(10)
        .all()
    )

    # Error rate
    total_reqs  = db.query(func.count(ApiRequestLog.id)).filter(ApiRequestLog.created_at >= since).scalar() or 0
    error_reqs  = db.query(func.count(ApiRequestLog.id)).filter(
        ApiRequestLog.created_at >= since,
        ApiRequestLog.status_code >= 400,
    ).scalar() or 0

    # Avg response time
    avg_ms = db.query(func.avg(ApiRequestLog.response_time_ms)).filter(
        ApiRequestLog.created_at >= since,
        ApiRequestLog.response_time_ms.isnot(None),
    ).scalar() or 0

    # Slowest endpoints (top 5)
    slowest = (
        db.query(ApiRequestLog.path, func.avg(ApiRequestLog.response_time_ms).label("avg_ms"))
        .filter(ApiRequestLog.created_at >= since)
        .group_by(ApiRequestLog.path)
        .order_by(func.avg(ApiRequestLog.response_time_ms).desc())
        .limit(5)
        .all()
    )

    # Failed logins in period
    failed_logins = db.query(func.count(AuditLog.id)).filter(
        AuditLog.created_at >= since,
        AuditLog.action == "login_failed",
    ).scalar() or 0

    return {
        "period_days": days,
        "api_requests": {
            "total": total_reqs,
            "errors": error_reqs,
            "error_rate_pct": round(error_reqs / total_reqs * 100, 2) if total_reqs else 0,
            "avg_response_ms": round(float(avg_ms), 1),
        },
        "top_actions": [{"action": a, "count": c} for a, c in top_actions],
        "slowest_endpoints": [{"path": p, "avg_ms": round(float(m), 1)} for p, m in slowest],
        "security": {
            "failed_logins": failed_logins,
        },
    }
