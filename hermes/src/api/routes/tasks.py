"""Scheduled tasks API routes."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.connection import get_db
from src.db.models import ScheduledTask

router = APIRouter()


@router.get("/")
async def list_tasks(db: AsyncSession = Depends(get_db)):
    """List all scheduled tasks."""
    result = await db.execute(select(ScheduledTask).order_by(ScheduledTask.name))
    tasks = result.scalars().all()
    return [
        {
            "id": str(t.id),
            "name": t.name,
            "description": t.description,
            "cron_expr": t.cron_expr,
            "enabled": t.enabled,
            "last_run": t.last_run.isoformat() if t.last_run else None,
            "last_status": t.last_status,
            "next_run": t.next_run.isoformat() if t.next_run else None,
        }
        for t in tasks
    ]


@router.get("/scheduler")
async def scheduler_status():
    """Get APScheduler job list."""
    from src.core.scheduler import scheduler
    jobs = scheduler.get_jobs()
    return [
        {
            "id": job.id,
            "name": job.name,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
        }
        for job in jobs
    ]
