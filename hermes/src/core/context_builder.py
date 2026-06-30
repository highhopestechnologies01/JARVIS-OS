"""
Context Builder — aggregates all available system data into a rich context object.

Used by the daily briefing job to give Claude maximum information.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Event, Memory, Briefing, Notification

log = structlog.get_logger()


class ContextBuilder:
    """Assembles rich context from all JARVIS data sources."""

    async def build_briefing_context(self, db: AsyncSession) -> dict[str, Any]:
        """
        Build full context for the daily briefing.
        Pulls from events, memories, notifications, and health history.
        """
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(hours=24)
        last_week = now - timedelta(days=7)

        context = {
            "infrastructure": await self._get_infra_status(db, yesterday),
            "health_history": await self._get_health_history(db, yesterday),
            "recent_events": await self._get_recent_events(db, yesterday),
            "active_memories": await self._get_active_memories(db),
            "weekly_summary": await self._get_weekly_summary(db, last_week),
            "patterns": await self._get_pattern_insights(db),
            "system_uptime": await self._get_uptime_stats(db, yesterday),
        }

        log.info("context_builder.built", keys=list(context.keys()))
        return context

    async def _get_infra_status(self, db: AsyncSession, since: datetime) -> dict[str, Any]:
        """Get latest health check result."""
        result = await db.execute(
            select(Event)
            .where(
                and_(
                    Event.type == "health_check.completed",
                    Event.created_at >= since,
                )
            )
            .order_by(Event.created_at.desc())
            .limit(1)
        )
        last_check = result.scalar_one_or_none()

        if last_check and last_check.payload:
            statuses = last_check.payload.get("statuses", {})
            failures = last_check.payload.get("failures", [])
            return {
                "last_check": last_check.created_at.strftime("%H:%M UTC"),
                "services": statuses,
                "failures": failures,
                "overall": "degraded" if failures else "healthy",
            }
        return {"overall": "unknown", "note": "No health check data in last 24h"}

    async def _get_health_history(self, db: AsyncSession, since: datetime) -> dict[str, Any]:
        """Summarize health check history."""
        result = await db.execute(
            select(Event)
            .where(
                and_(
                    Event.type == "health_check.completed",
                    Event.created_at >= since,
                )
            )
            .order_by(Event.created_at.asc())
        )
        checks = result.scalars().all()

        if not checks:
            return {"checks_run": 0, "uptime_pct": "unknown"}

        total = len(checks)
        healthy = sum(1 for c in checks if not c.payload.get("failures"))
        uptime_pct = round((healthy / total) * 100, 1) if total > 0 else 0

        all_failures: list[str] = []
        for c in checks:
            all_failures.extend(c.payload.get("failures", []))

        # Count failure frequency by service
        failure_counts: dict[str, int] = {}
        for f in all_failures:
            service = f.split(":")[0].strip()
            failure_counts[service] = failure_counts.get(service, 0) + 1

        return {
            "checks_run": total,
            "healthy": healthy,
            "degraded": total - healthy,
            "uptime_pct": f"{uptime_pct}%",
            "frequent_failures": failure_counts if failure_counts else "none",
        }

    async def _get_recent_events(self, db: AsyncSession, since: datetime) -> list[str]:
        """Get significant events from the last 24h."""
        result = await db.execute(
            select(Event)
            .where(Event.created_at >= since)
            .order_by(Event.created_at.desc())
            .limit(30)
        )
        events = result.scalars().all()

        # Filter out noisy health checks — show only notable events
        notable = [
            e for e in events
            if e.type not in ("health_check.completed",)
        ]

        summary = []
        for e in notable[:15]:
            ts = e.created_at.strftime("%H:%M")
            summary.append(f"{ts} — {e.type}" + (f" ({e.source})" if e.source else ""))

        # Add health check summary
        health_events = [e for e in events if e.type == "health_check.completed"]
        if health_events:
            summary.append(f"{len(health_events)} health checks ran in last 24h")

        return summary if summary else ["No notable events in last 24h"]

    async def _get_active_memories(self, db: AsyncSession) -> list[str]:
        """Get top important memories for context."""
        now = datetime.now(timezone.utc)
        result = await db.execute(
            select(Memory)
            .where(
                (Memory.expires_at.is_(None)) | (Memory.expires_at > now)
            )
            .order_by(Memory.importance.desc(), Memory.created_at.desc())
            .limit(10)
        )
        memories = result.scalars().all()
        if not memories:
            return ["No memories stored yet"]
        return [
            f"[{m.type}] {m.topic or 'note'}: {m.content[:150]}"
            for m in memories
        ]

    async def _get_weekly_summary(self, db: AsyncSession, since: datetime) -> dict[str, Any]:
        """Get counts of activity over the last 7 days."""
        result = await db.execute(
            select(Event.type, func.count(Event.id).label("count"))
            .where(Event.created_at >= since)
            .group_by(Event.type)
            .order_by(func.count(Event.id).desc())
        )
        rows = result.all()
        return {row.type: row.count for row in rows} if rows else {"note": "No events this week"}

    async def _get_pattern_insights(self, db: AsyncSession) -> list[str]:
        """Get recent AI-generated pattern insights from memory."""
        now = datetime.now(timezone.utc)
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
        if not insights:
            return ["No pattern analysis run yet — first analysis runs at 3am"]
        return [m.content for m in insights]

    async def _get_uptime_stats(self, db: AsyncSession, since: datetime) -> dict[str, Any]:
        """Get system uptime statistics."""
        # Count total health checks and failures
        result = await db.execute(
            select(func.count(Event.id))
            .where(
                and_(
                    Event.type == "health_check.completed",
                    Event.created_at >= since,
                )
            )
        )
        total_checks = result.scalar_one() or 0

        # Count checks with failures
        result = await db.execute(
            select(Event)
            .where(
                and_(
                    Event.type == "health_check.completed",
                    Event.created_at >= since,
                )
            )
        )
        checks = result.scalars().all()
        degraded = sum(1 for c in checks if c.payload.get("failures"))

        healthy = total_checks - degraded
        pct = round((healthy / total_checks) * 100, 1) if total_checks > 0 else 100

        return {
            "total_health_checks": total_checks,
            "uptime_24h": f"{pct}%",
            "expected_checks": 96,  # every 15min = 96/day
            "coverage": f"{round((total_checks / 96) * 100)}%" if total_checks > 0 else "0%",
        }


# Singleton
context_builder = ContextBuilder()
