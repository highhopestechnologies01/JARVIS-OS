"""
Intelligence API routes — pattern insights and autonomous planning results.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from fastapi import APIRouter, BackgroundTasks
from sqlalchemy import select, and_

from src.db.connection import AsyncSessionLocal
from src.db.models import Memory, Event

log = structlog.get_logger()
router = APIRouter()


@router.get("/insights")
async def get_insights() -> dict[str, Any]:
    """
    Return the latest AI-generated pattern insights.
    GET /api/v1/intelligence/insights
    """
    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)

        # Latest pattern insights
        result = await db.execute(
            select(Memory)
            .where(
                and_(
                    Memory.type == "pattern_insight",
                    (Memory.expires_at.is_(None)) | (Memory.expires_at > now),
                )
            )
            .order_by(Memory.created_at.desc())
            .limit(5)
        )
        insights = result.scalars().all()

        # Latest autonomous plan
        result = await db.execute(
            select(Memory)
            .where(Memory.type == "weekly_plan")
            .order_by(Memory.created_at.desc())
            .limit(1)
        )
        plan = result.scalar_one_or_none()

        # Last pattern analysis run
        result = await db.execute(
            select(Event)
            .where(Event.type == "pattern_analysis.completed")
            .order_by(Event.created_at.desc())
            .limit(1)
        )
        last_analysis = result.scalar_one_or_none()

        return {
            "insights": [
                {
                    "content": m.content,
                    "created_at": m.created_at.isoformat(),
                    "importance": m.importance,
                }
                for m in insights
            ],
            "last_analysis": last_analysis.created_at.isoformat() if last_analysis else None,
            "weekly_plan": plan.content[:300] + "..." if plan else None,
            "weekly_plan_date": plan.topic if plan else None,
        }


@router.post("/analyze")
async def trigger_analysis(background_tasks: BackgroundTasks) -> dict[str, str]:
    """
    Manually trigger a pattern analysis run.
    POST /api/v1/intelligence/analyze
    """
    async def run_analysis():
        from src.core.pattern_analyzer import pattern_analyzer
        from src.db.models import Event
        async with AsyncSessionLocal() as db:
            insights = await pattern_analyzer.analyze(db)
            db.add(Event(
                type="pattern_analysis.completed",
                source="manual_trigger",
                payload={"insights_count": len(insights), "insights": insights},
            ))
            await db.commit()
        log.info("intelligence.manual_analysis.complete", insights=len(insights))

    background_tasks.add_task(run_analysis)
    return {"status": "analysis_started", "note": "Results available in ~10 seconds at /insights"}
