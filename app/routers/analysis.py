"""
Analysis router — manual re-analysis and notification management.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.email import Notification
from app.models.email import EmailIntegration
from app.models.user import User
from app.schemas.email import NotificationOut
from app.routers.auth import get_current_user

router = APIRouter()


@router.get("/notifications", response_model=list[NotificationOut])
def list_notifications(
    unread_only: bool = Query(False),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List recent notifications."""
    query = db.query(Notification)
    if current_user.role != "admin":
        query = query.join(Notification.email).join(EmailIntegration).filter(
            EmailIntegration.owner_user_id == current_user.id
        )
    if unread_only:
        query = query.filter(Notification.is_read == False)
    return query.order_by(Notification.created_at.desc()).limit(limit).all()


@router.patch("/notifications/{notification_id}/read")
def mark_notification_read(
    notification_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Notification).filter(Notification.id == notification_id)
    if current_user.role != "admin":
        query = query.join(Notification.email).join(EmailIntegration).filter(
            EmailIntegration.owner_user_id == current_user.id
        )
    notif = query.first()
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")
    notif.is_read = True
    db.commit()
    return {"message": "Marked as read"}


@router.patch("/notifications/read-all")
def mark_all_notifications_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Notification).filter(Notification.is_read == False)
    if current_user.role != "admin":
        query = query.join(Notification.email).join(EmailIntegration).filter(
            EmailIntegration.owner_user_id == current_user.id
        )
    for notification in query.all():
        notification.is_read = True
    db.commit()
    return {"message": "All notifications marked as read"}
