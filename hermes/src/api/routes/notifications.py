"""Notifications API routes."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.connection import get_db
from src.db.models import Notification
from src.core.notifications import dispatcher

router = APIRouter()


class SendNotificationRequest(BaseModel):
    channel: str  # 'sms' | 'email'
    message: str
    subject: str | None = None


@router.post("/send")
async def send_notification(body: SendNotificationRequest):
    """Send a notification immediately."""
    if body.channel == "sms":
        ok = await dispatcher.send_sms(body.message)
    elif body.channel == "email":
        ok = await dispatcher.send_email(
            subject=body.subject or "JARVIS Notification",
            body=body.message,
        )
    else:
        return {"status": "error", "message": f"Unknown channel: {body.channel}"}

    return {"status": "sent" if ok else "failed"}


@router.get("/")
async def list_notifications(
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    """List recent notifications."""
    result = await db.execute(
        select(Notification).order_by(Notification.created_at.desc()).limit(limit)
    )
    notifications = result.scalars().all()
    return [
        {
            "id": str(n.id),
            "channel": n.channel,
            "subject": n.subject,
            "status": n.status,
            "sent_at": n.sent_at.isoformat() if n.sent_at else None,
            "created_at": n.created_at.isoformat(),
        }
        for n in notifications
    ]
