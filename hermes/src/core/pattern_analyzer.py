"""
Pattern Analyzer — AI-powered trend detection and anomaly flagging.

Uses Claude Haiku to analyze JARVIS event data and generate
actionable insights stored as high-importance memories.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from anthropic import AsyncAnthropic
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.db.models import Event, Memory

log = structlog.get_logger()

ANALYSIS_SYSTEM_PROMPT = """You are Hermes's internal pattern analysis module.

Your job: analyze JARVIS OS system data and identify meaningful patterns, trends, and anomalies.

Output exactly 3-5 concise insights as a JSON array. Each insight is a string under 200 characters.
Focus on: service reliability trends, performance patterns, unusual activity, and actionable observations.

Example output:
["Grafana has been unreachable for 3 of the last 8 health checks — investigate network config.",
 "Health check coverage is at 87% — scheduler is running reliably.",
 "No critical failures detected in the last 24 hours — all core services stable."]

Return ONLY the JSON array, no other text."""


class PatternAnalyzer:
    """Analyzes system events to find patterns and generate insights."""

    def __init__(self):
        self._client: AsyncAnthropic | None = None

    @property
    def client(self) -> AsyncAnthropic:
        if not self._client:
            self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        return self._client

    async def analyze(self, db: AsyncSession) -> list[str]:
        """
        Run a full pattern analysis pass.
        Returns list of insight strings.
        """
        if not settings.anthropic_api_key:
            log.warning("pattern_analyzer.no_api_key")
            return ["Pattern analysis unavailable — ANTHROPIC_API_KEY not set"]

        raw_data = await self._gather_data(db)
        insights = await self._generate_insights(raw_data)
        await self._store_insights(db, insights)
        return insights

    async def _gather_data(self, db: AsyncSession) -> dict[str, Any]:
        """Gather system data for analysis."""
        now = datetime.now(timezone.utc)
        since_24h = now - timedelta(hours=24)
        since_7d = now - timedelta(days=7)

        # Health check breakdown
        result = await db.execute(
            select(Event)
            .where(
                and_(
                    Event.type == "health_check.completed",
                    Event.created_at >= since_24h,
                )
            )
            .order_by(Event.created_at.desc())
        )
        health_checks = result.scalars().all()

        service_failures: dict[str, int] = {}
        service_ok: dict[str, int] = {}
        for check in health_checks:
            statuses = check.payload.get("statuses", {})
            for svc, status in statuses.items():
                if status == "ok":
                    service_ok[svc] = service_ok.get(svc, 0) + 1
                else:
                    service_failures[svc] = service_failures.get(svc, 0) + 1

        # Event volume by type (7d)
        result = await db.execute(
            select(Event.type, func.count(Event.id).label("count"))
            .where(Event.created_at >= since_7d)
            .group_by(Event.type)
            .order_by(func.count(Event.id).desc())
        )
        event_counts = {row.type: row.count for row in result.all()}

        # Memory count
        result = await db.execute(select(func.count(Memory.id)))
        memory_count = result.scalar_one() or 0

        # Briefings generated this week
        from src.db.models import Briefing
        result = await db.execute(
            select(func.count(Briefing.id)).where(Briefing.created_at >= since_7d)
        )
        briefing_count = result.scalar_one() or 0

        return {
            "health_checks_24h": len(health_checks),
            "expected_health_checks": 96,
            "service_ok_counts": service_ok,
            "service_failure_counts": service_failures,
            "event_counts_7d": event_counts,
            "memory_count": memory_count,
            "briefings_this_week": briefing_count,
            "analysis_timestamp": now.isoformat(),
        }

    async def _generate_insights(self, data: dict[str, Any]) -> list[str]:
        """Use Claude Haiku to generate insights from raw data."""
        import json

        data_str = json.dumps(data, indent=2, default=str)

        response = await self.client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            system=ANALYSIS_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": f"Analyze this JARVIS OS system data and generate insights:\n\n{data_str}"
            }],
        )

        raw = response.content[0].text.strip()
        log.info("pattern_analyzer.claude_response", raw=raw[:200])

        try:
            # Parse JSON array
            insights = json.loads(raw)
            if isinstance(insights, list):
                return [str(i) for i in insights[:5]]
        except json.JSONDecodeError:
            # Fallback: split on newlines
            pass

        # Fallback: extract lines that look like insights
        lines = [l.strip().strip('"').strip("'") for l in raw.split("\n") if len(l.strip()) > 20]
        return lines[:5] if lines else ["Pattern analysis completed — no significant trends detected."]

    async def _store_insights(self, db: AsyncSession, insights: list[str]) -> None:
        """Store insights as pattern_insight memories (expire after 7 days)."""
        from datetime import timezone
        expires = datetime.now(timezone.utc) + timedelta(days=7)

        for i, insight in enumerate(insights):
            memory = Memory(
                type="pattern_insight",
                topic="system_pattern_analysis",
                content=insight,
                importance=7,
                source="pattern_analyzer",
                metadata_={"rank": i + 1, "generated_at": datetime.now(timezone.utc).isoformat()},
                expires_at=expires,
            )
            db.add(memory)

        log.info("pattern_analyzer.insights_stored", count=len(insights))


# Singleton
pattern_analyzer = PatternAnalyzer()
