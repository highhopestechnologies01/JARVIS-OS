"""
Scheduler API routes — list jobs and trigger them manually.
"""

from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException

from src.core.scheduler import scheduler

log = structlog.get_logger()
router = APIRouter()


def _job_to_dict(job) -> dict[str, Any]:
    """Serialize an APScheduler job to a JSON-safe dict."""
    next_run = job.next_run_time
    return {
        "id": job.id,
        "name": job.name,
        "next_run": next_run.isoformat() if next_run else None,
        "next_run_relative": _relative_time(next_run) if next_run else "paused",
        "trigger": str(job.trigger),
        "running": next_run is None,
    }


def _relative_time(dt: datetime) -> str:
    """Human-readable relative time string."""
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    diff = (dt - now).total_seconds()
    if diff < 0:
        return "overdue"
    if diff < 60:
        return f"in {int(diff)}s"
    if diff < 3600:
        return f"in {int(diff // 60)}m"
    if diff < 86400:
        return f"in {int(diff // 3600)}h {int((diff % 3600) // 60)}m"
    return f"in {int(diff // 86400)}d"


@router.get("/jobs")
async def list_jobs() -> dict[str, Any]:
    """
    List all registered scheduler jobs with their next run times.
    GET /api/v1/scheduler/jobs
    """
    jobs = scheduler.get_jobs()
    return {
        "jobs": [_job_to_dict(j) for j in jobs],
        "count": len(jobs),
        "scheduler_running": scheduler.running,
    }


@router.post("/trigger/{job_id}")
async def trigger_job(job_id: str) -> dict[str, str]:
    """
    Manually trigger a scheduler job immediately.
    POST /api/v1/scheduler/trigger/{job_id}
    """
    job = scheduler.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    log.info("scheduler.manual_trigger", job_id=job_id, job_name=job.name)

    # Run in background — don't block the request
    import asyncio
    asyncio.create_task(job.func())

    return {"status": "triggered", "job_id": job_id, "job_name": job.name}
