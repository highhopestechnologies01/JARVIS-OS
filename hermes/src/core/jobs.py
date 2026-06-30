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
    Generates and delivers the daily executive briefing using full system context.
    """
    from src.db.connection import AsyncSessionLocal
    from src.db.models import Briefing, Event
    from src.core.planner import planner
    from src.core.notifications import dispatcher
    from src.core.context_builder import context_builder
    from sqlalchemy import select

    log.info("jobs.daily_briefing.start")
    today = date.today()

    async with AsyncSessionLocal() as db:
        # Check if already generated today
        existing = await db.execute(
            select(Briefing).where(Briefing.date == today)
        )
        if existing.scalar_one_or_none():
            log.info("jobs.daily_briefing.already_exists", date=str(today))
            return

        # Build rich context from all system data
        context = await context_builder.build_briefing_context(db)
        context["date"] = today.strftime("%A, %B %d, %Y")

        # Generate briefing with Claude
        content = await planner.generate_briefing(context, today)
        summary = await planner.summarize(content)

        # Save to database
        briefing = Briefing(
            date=today,
            content=content,
            summary=summary,
            sources=["infrastructure", "events", "memory", "pattern_insights"],
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
    # n8n is Coolify-managed (n8n-n8n-1) connected to jarvis-net
    services = {
        "hermes":     "http://localhost:8000/api/v1/health/ready",
        "n8n":        "http://n8n-n8n-1:5678/healthz",
        "grafana":    "http://jarvis-grafana:3000/api/health",
        "prometheus": "http://jarvis-prometheus:9090/-/healthy",
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

    # Check RDP machines (TCP port 3389)
    from src.integrations.rdp import check_all_rdp_hosts
    rdp_results = await check_all_rdp_hosts()
    for rdp in rdp_results:
        if rdp["online"]:
            statuses[rdp["name"]] = "ok"
        else:
            statuses[rdp["name"]] = "down"
            failures.append(f"{rdp['name']}: offline ({rdp.get('error', 'unreachable')})")

    if failures:
        from src.core.notifications import dispatcher
        alert = "⚠️ JARVIS Health Alert:\n" + "\n".join(f"• {f}" for f in failures)
        await dispatcher.send_sms(alert)
        log.warning("jobs.health_check.failures", failures=failures)

        # POST to n8n health alert workflow (non-blocking — failure here is OK)
        try:
            async with httpx.AsyncClient(timeout=3.0) as n8n_client:
                await n8n_client.post(
                    "http://n8n-n8n-1:5678/webhook/jarvis-health-alert",
                    json={"failures": failures, "statuses": statuses},
                )
            log.info("jobs.health_check.n8n_alert_sent")
        except Exception as e:
            log.warning("jobs.health_check.n8n_alert_failed", error=str(e))
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


async def pattern_analysis():
    """
    Run every day at 3am.
    Uses Claude Haiku to analyze system events and store pattern insights as memories.
    """
    from src.db.connection import AsyncSessionLocal
    from src.db.models import Event
    from src.core.pattern_analyzer import pattern_analyzer

    log.info("jobs.pattern_analysis.start")
    async with AsyncSessionLocal() as db:
        insights = await pattern_analyzer.analyze(db)
        db.add(Event(
            type="pattern_analysis.completed",
            source="pattern_analysis_job",
            payload={"insights_count": len(insights), "insights": insights},
        ))
        await db.commit()
    log.info("jobs.pattern_analysis.complete", insights=len(insights))


async def autonomous_planning():
    """
    Run every Sunday at 6am ET.
    JARVIS autonomously reviews the week and generates a forward plan,
    stored as a briefing for the coming week.
    """
    from src.db.connection import AsyncSessionLocal
    from src.db.models import Briefing, Event, Memory
    from src.core.planner import planner
    from src.core.context_builder import context_builder
    from sqlalchemy import select

    log.info("jobs.autonomous_planning.start")
    today = date.today()

    async with AsyncSessionLocal() as db:
        # Build full context
        context = await context_builder.build_briefing_context(db)

        # Generate weekly plan with Claude Opus
        from src.config import settings
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=settings.anthropic_api_key)

        context_text = planner._format_context(context)
        response = await client.messages.create(
            model="claude-opus-4-8",
            max_tokens=2500,
            system="""You are Hermes, JARVIS OS's autonomous planning agent for Thomas Shelby.

Each Sunday you review the past week and generate a forward plan for the coming week.

Your plan must include:
1. Last Week Review — what happened, what worked, what didn't
2. This Week's Priorities — top 5 focus areas with specific actions
3. Risk Watch — items to monitor proactively
4. Automated Actions — tasks Hermes will handle autonomously
5. Requests for Thomas — decisions or inputs needed from the user

Be specific, direct, and actionable. No filler.""",
            messages=[{
                "role": "user",
                "content": f"Generate the weekly autonomous plan for the week starting {today.strftime('%A, %B %d, %Y')}.\n\nSystem context:\n{context_text}"
            }],
        )

        plan_content = response.content[0].text

        # Store as a special briefing
        from datetime import timedelta
        plan_date = today + timedelta(days=1)  # Label it as Monday
        db.add(Briefing(
            date=plan_date,
            content=plan_content,
            summary=f"Autonomous weekly plan — week of {plan_date.strftime('%B %d')}",
            sources=["autonomous_planning", "pattern_analysis", "events", "memory"],
            status="delivered",
            delivered_at=datetime.now(timezone.utc),
        ))

        # Store as a high-importance memory
        db.add(Memory(
            type="weekly_plan",
            topic=f"week_of_{today.isoformat()}",
            content=plan_content[:500] + "...",
            importance=9,
            source="autonomous_planning_job",
        ))

        db.add(Event(
            type="autonomous_planning.completed",
            source="autonomous_planning_job",
            payload={"week_start": str(plan_date), "tokens": response.usage.output_tokens},
        ))

        await db.commit()
        log.info("jobs.autonomous_planning.complete", date=str(plan_date))


# --- Helpers (kept for backward compat) ---

async def _get_infra_status() -> dict:
    """Quick status stub — full context now via context_builder."""
    return {"status": "see infrastructure key in full context"}


async def _get_recent_events(db) -> list[str]:
    """Legacy helper — full context now via context_builder."""
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
