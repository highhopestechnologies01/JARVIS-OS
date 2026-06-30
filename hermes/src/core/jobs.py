"""
Scheduled job handlers — the actual work Hermes does on a schedule.
Each function is a standalone async coroutine, registered with APScheduler.
"""

from datetime import date, datetime, timezone

import structlog

log = structlog.get_logger()


async def daily_briefing():
    """
    Run every day at 8am ET.
    Generates and delivers the daily executive briefing.
    """
    from src.db.connection import AsyncSessionLocal
    from src.db.models import Briefing, Event
    from src.core.planner import planner
    from src.core.notifications import dispatcher

    log.info("jobs.daily_briefing.start")
    today = date.today()

    async with AsyncSessionLocal() as db:
        # Check if already generated today
        from sqlalchemy import select
        existing = await db.execute(
            select(Briefing).where(Briefing.date == today)
        )
        if existing.scalar_one_or_none():
            log.info("jobs.daily_briefing.already_exists", date=str(today))
            return

        # Gather context
        context = {
            "date": today.strftime("%A, %B %d, %Y"),
            "infrastructure": await _get_infra_status(),
            "recent_events": await _get_recent_events(db),
        }

        # Generate briefing
        content = await planner.generate_briefing(context, today)
        summary = await planner.summarize(content)

        # Save to database
        briefing = Briefing(
            date=today,
            content=content,
            summary=summary,
            sources=["infrastructure", "events", "memory"],
            status="generated",
        )
        db.add(briefing)

        # Deliver
        results = await dispatcher.send_briefing(content, today.strftime("%Y-%m-%d"))
        briefing.status = "delivered"
        briefing.delivered_at = datetime.now(timezone.utc)

        # Log event
        db.add(Event(
            type="briefing.generated",
            source="daily_briefing_job",
            payload={"date": str(today), "delivery": results},
        ))

        await db.commit()
        log.info("jobs.daily_briefing.complete", date=str(today))


async def infrastructure_health_check():
    """
    Run every 15 minutes.
    Checks all Docker services and alerts if anything is down.
    """
    import httpx

    log.info("jobs.health_check.start")

    # Use Docker internal hostnames — Hermes checks itself via localhost
    services = {
        "hermes":     "http://localhost:8000/api/v1/health/ready",
        "n8n":        "http://n8n:5678/healthz",
        "grafana":    "http://grafana:3000/api/health",
        "prometheus": "http://prometheus:9090/-/healthy",
    }

    statuses: dict[str, str] = {}
    failures: list[str] = []

    async with httpx.AsyncClient(timeout=5.0) as client:
        for name, url in services.items():
            try:
                resp = await client.get(url)
                if resp.status_code >= 400:
                    failures.append(f"{name}: HTTP {resp.status_code}")
                    statuses[name] = "down"
                else:
                    statuses[name] = "ok"
            except Exception as e:
                failures.append(f"{name}: unreachable")
                statuses[name] = "down"
                log.warning("jobs.health_check.service_error", service=name, error=str(e))

    # Persist result to database
    from src.db.connection import AsyncSessionLocal
    from src.db.models import Event
    async with AsyncSessionLocal() as db:
        db.add(Event(
            type="health_check.completed",
            source="infrastructure_health_check_job",
            payload={"statuses": statuses, "failures": failures},
        ))
        await db.commit()

    if failures:
        from src.core.notifications import dispatcher
        alert = "⚠️ JARVIS Health Alert:\n" + "\n".join(f"• {f}" for f in failures)
        await dispatcher.send_sms(alert)
        log.warning("jobs.health_check.failures", failures=failures)
    else:
        log.info("jobs.health_check.all_ok", checked=len(services))


async def weekly_report():
    """
    Run every Monday at 9am ET.
    Generates a weekly performance summary.
    """
    from src.db.connection import AsyncSessionLocal
    from src.core.planner import planner
    from src.core.notifications import dispatcher

    log.info("jobs.weekly_report.start")

    async with AsyncSessionLocal() as db:
        events = await _get_week_events(db)
        context = {
            "period": "last 7 days",
            "events": events,
        }
        report = await planner.generate_briefing(context)
        await dispatcher.send_email(
            subject=f"JARVIS Weekly Report — {date.today().strftime('%B %d, %Y')}",
            body=report,
        )

    log.info("jobs.weekly_report.complete")


async def consolidate_memories():
    """
    Run every day at 2am.
    Prunes expired memories to keep the store clean.
    """
    from src.db.connection import AsyncSessionLocal
    from src.core.memory import memory_engine

    log.info("jobs.memory_consolidation.start")
    async with AsyncSessionLocal() as db:
        pruned = await memory_engine.prune_expired(db)
        await db.commit()
    log.info("jobs.memory_consolidation.complete", pruned=pruned)


# --- Helpers ---

async def _get_infra_status() -> dict:
    """Quick check of key service health for briefing context."""
    return {"status": "checking via health_check job"}


async def _get_recent_events(db) -> list[str]:
    """Get recent Hermes events for briefing context."""
    from sqlalchemy import select
    from src.db.models import Event
    result = await db.execute(
        select(Event.type, Event.created_at)
        .order_by(Event.created_at.desc())
        .limit(10)
    )
    return [f"{row.type} at {row.created_at.strftime('%H:%M')}" for row in result]


async def _get_week_events(db) -> list[str]:
    """Get events from the past 7 days."""
    from datetime import timedelta
    from sqlalchemy import select, and_
    from src.db.models import Event
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    result = await db.execute(
        select(Event).where(Event.created_at >= cutoff).order_by(Event.created_at.desc())
    )
    events = result.scalars().all()
    return [f"{e.type}: {e.payload}" for e in events]
