"""Briefings API routes."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.connection import get_db
from src.db.models import Briefing
from src.core.planner import planner
from src.core.notifications import dispatcher

router = APIRouter()


class BriefingResponse(BaseModel):
    id: str
    date: str
    content: str
    summary: str | None
    status: str
    delivered_at: str | None
    created_at: str


class GenerateBriefingRequest(BaseModel):
    date: str | None = None
    deliver: bool = True


@router.get("/today")
async def get_today_briefing(db: AsyncSession = Depends(get_db)):
    """Get today's briefing, generating it if it doesn't exist."""
    today = date.today()
    result = await db.execute(select(Briefing).where(Briefing.date == today))
    briefing = result.scalar_one_or_none()

    if briefing:
        return {"id": str(briefing.id), "date": str(briefing.date), "content": briefing.content,
                "summary": briefing.summary, "status": briefing.status}

    # Generate on demand
    content = await planner.generate_briefing({"date": str(today)}, today)
    summary = await planner.summarize(content)

    briefing = Briefing(
        date=today,
        content=content,
        summary=summary,
        status="generated",
    )
    db.add(briefing)
    await db.commit()
    await db.refresh(briefing)

    return {"id": str(briefing.id), "date": str(briefing.date), "content": briefing.content,
            "summary": briefing.summary, "status": briefing.status}


@router.get("/")
async def list_briefings(
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
):
    """List recent briefings."""
    result = await db.execute(
        select(Briefing).order_by(Briefing.date.desc()).limit(limit)
    )
    briefings = result.scalars().all()
    return [
        {"id": str(b.id), "date": str(b.date), "summary": b.summary, "status": b.status}
        for b in briefings
    ]


@router.post("/generate")
async def generate_briefing(
    body: GenerateBriefingRequest,
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger briefing generation."""
    target = date.fromisoformat(body.date) if body.date else date.today()
    content = await planner.generate_briefing({"date": str(target)}, target)
    summary = await planner.summarize(content)

    briefing = Briefing(date=target, content=content, summary=summary, status="generated")
    db.add(briefing)
    await db.commit()

    if body.deliver:
        await dispatcher.send_briefing(content, str(target))

    return {"status": "ok", "date": str(target), "summary": summary}
