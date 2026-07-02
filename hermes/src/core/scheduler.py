"""
Scheduler — APScheduler-based task runner for Hermes.

Loads scheduled tasks from the database and runs them on their cron schedule.
"""

import asyncio
from datetime import datetime, timezone

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

log = structlog.get_logger()

scheduler = AsyncIOScheduler(timezone="America/New_York")


def register_core_jobs():
    """Register all built-in Hermes jobs with the scheduler."""
    from src.core.jobs import (
        daily_briefing,
        infrastructure_health_check,
        weekly_report,
        consolidate_memories,
        pattern_analysis,
        autonomous_planning,
        campaign_insights,
    )
    from src.integrations.telegram_bot import process_updates

    jobs = [
        {
            "id": "daily_briefing",
            "func": daily_briefing,
            "trigger": CronTrigger(hour=8, minute=0, timezone="America/New_York"),
            "name": "Daily Executive Briefing",
        },
        {
            "id": "health_check",
            "func": infrastructure_health_check,
            "trigger": CronTrigger(minute="*/15"),
            "name": "Infrastructure Health Check",
        },
        {
            "id": "weekly_report",
            "func": weekly_report,
            "trigger": CronTrigger(day_of_week="mon", hour=9, minute=0, timezone="America/New_York"),
            "name": "Weekly Report",
        },
        {
            "id": "memory_consolidation",
            "func": consolidate_memories,
            "trigger": CronTrigger(hour=2, minute=0),
            "name": "Memory Consolidation",
        },
        {
            "id": "pattern_analysis",
            "func": pattern_analysis,
            "trigger": CronTrigger(hour=3, minute=0),
            "name": "AI Pattern Analysis",
        },
        {
            "id": "autonomous_planning",
            "func": autonomous_planning,
            "trigger": CronTrigger(day_of_week="sun", hour=6, minute=0, timezone="America/New_York"),
            "name": "Autonomous Weekly Planning",
        },
        {
            "id": "campaign_insights",
            "func": campaign_insights,
            "trigger": CronTrigger(hour=9, minute=30, timezone="America/New_York"),
            "name": "Campaign Insights AI",
        },
        {
            "id": "telegram_polling",
            "func": process_updates,
            "trigger": CronTrigger(second="*/10"),
            "name": "Telegram Bot Polling",
        },
    ]

    for job in jobs:
        scheduler.add_job(
            job["func"],
            trigger=job["trigger"],
            id=job["id"],
            name=job["name"],
            replace_existing=True,
            misfire_grace_time=300,  # 5 min grace period
        )
        log.info("scheduler.job.registered", id=job["id"], name=job["name"])


# Register jobs when scheduler starts
scheduler.add_listener(
    lambda event: log.info("scheduler.started"),
    mask=0x001,  # EVENT_SCHEDULER_STARTED
)
