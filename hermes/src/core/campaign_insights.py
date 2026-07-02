"""
Campaign Insights Engine — daily AI analysis of Meta Ads performance.

Runs once per day (configurable via APScheduler job).
Pulls the last 24h of campaign snapshots, feeds to Claude Haiku,
generates 3–5 actionable insights, stores them in Memory table,
and delivers a summary to Telegram.
"""

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from anthropic import AsyncAnthropic
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.db.models import Memory, MetaAdsSnapshot

log = structlog.get_logger()

INSIGHTS_SYSTEM_PROMPT = """You are JARVIS's Meta Ads intelligence module.

Analyze the provided campaign performance data and generate 3–5 concise, actionable insights.

Focus on:
- Campaigns with unusually high or low CTR / CPC
- Campaigns where spend is accelerating vs. stalling
- Budget efficiency patterns (best ROI, worst ROI)
- Campaigns that stopped or paused unexpectedly
- Opportunities to scale or cut based on data

Return a JSON object with this exact structure:
{
  "summary": "One sentence overview of overall performance.",
  "insights": [
    "Specific, actionable insight 1 (under 180 chars)",
    "Specific, actionable insight 2 (under 180 chars)",
    "Specific, actionable insight 3 (under 180 chars)"
  ],
  "top_campaign": "Name of best-performing campaign or null",
  "concern": "Biggest concern or null"
}

Return ONLY the JSON object, no markdown, no other text."""


class CampaignInsightsEngine:
    """Generates AI-powered insights from Meta Ads snapshots."""

    def __init__(self) -> None:
        self._client: AsyncAnthropic | None = None

    def _get_client(self) -> AsyncAnthropic:
        if not self._client:
            self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        return self._client

    async def _fetch_snapshots(
        self, db: AsyncSession, hours: int = 24
    ) -> list[MetaAdsSnapshot]:
        """Pull the latest snapshot per profile from the last `hours` window."""
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        result = await db.execute(
            select(MetaAdsSnapshot)
            .where(MetaAdsSnapshot.scraped_at >= since)
            .order_by(desc(MetaAdsSnapshot.scraped_at))
        )
        rows = result.scalars().all()

        # Keep only the most recent snapshot per (rdp, profile)
        seen: dict[str, MetaAdsSnapshot] = {}
        for r in rows:
            key = f"{r.rdp_host}:{r.profile_id}"
            if key not in seen:
                seen[key] = r
        return list(seen.values())

    def _build_data_block(self, snapshots: list[MetaAdsSnapshot]) -> str:
        """Serialize snapshot data into a compact string for the prompt."""
        lines: list[str] = []
        total_spend = 0.0

        for snap in snapshots:
            profile_label = snap.profile_name or snap.profile_id
            rdp = snap.rdp_host
            summary = snap.summary or {}
            profile_spend = summary.get("total_spend_all") or summary.get("total_spend", 0)
            total_spend += profile_spend

            lines.append(
                f"\n## {rdp} / {profile_label} — spend ${profile_spend:.2f}"
            )

            campaigns: list[dict[str, Any]] = snap.campaigns or []
            if not campaigns:
                lines.append("  (no campaign data)")
                continue

            for c in campaigns[:20]:  # cap at 20 campaigns per profile
                name = c.get("name", "unknown")
                status = c.get("status", "")
                spend = c.get("spend", "$0")
                budget = c.get("budget", "—")
                impressions = c.get("impressions", "0")
                clicks = c.get("clicks", "0")
                ctr = c.get("ctr", "—")
                cpc = c.get("cpc", "—")
                lines.append(
                    f"  - {name} | {status} | spend {spend}/{budget} | "
                    f"{impressions} impr | {clicks} clicks | CTR {ctr} | CPC {cpc}"
                )

        header = f"Total spend across all profiles (last 24h): ${total_spend:.2f}\n"
        return header + "\n".join(lines)

    async def _analyze(self, data_block: str) -> dict:
        """Call Claude Haiku and return the parsed JSON insight object."""
        client = self._get_client()
        try:
            resp = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=600,
                system=INSIGHTS_SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": f"Here is today's campaign performance data:\n\n{data_block}\n\nGenerate insights.",
                    }
                ],
            )
            raw = resp.content[0].text.strip()
            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            return json.loads(raw)
        except Exception as e:
            log.error("campaign_insights.llm_error", error=str(e))
            return {
                "summary": "Analysis unavailable — LLM error.",
                "insights": [],
                "top_campaign": None,
                "concern": str(e)[:100],
            }

    async def _save_to_memory(self, db: AsyncSession, result: dict, date_str: str) -> None:
        """Persist insights in the Memory table (type='insight', topic='campaign_insights')."""
        content = json.dumps(result)
        existing = await db.execute(
            select(Memory).where(
                Memory.type == "insight",
                Memory.topic == "campaign_insights",
            )
        )
        row = existing.scalar_one_or_none()
        if row is None:
            row = Memory(
                type="insight",
                topic="campaign_insights",
                content=content,
                importance=8,
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            )
            db.add(row)
        else:
            row.content = content
            row.importance = 8
            row.expires_at = datetime.now(timezone.utc) + timedelta(days=7)
        await db.commit()
        log.info("campaign_insights.saved", date=date_str)

    async def _send_telegram(self, result: dict, date_str: str) -> None:
        """Push the insight summary to Telegram."""
        try:
            from src.core.notifications import dispatcher

            summary = result.get("summary", "No summary.")
            insights = result.get("insights", [])
            top = result.get("top_campaign")
            concern = result.get("concern")

            lines = [f"📊 <b>Campaign Insights — {date_str}</b>\n"]
            lines.append(f"<i>{summary}</i>\n")

            for i, ins in enumerate(insights, 1):
                lines.append(f"{i}. {ins}")

            if top:
                lines.append(f"\n🏆 Top campaign: <b>{top}</b>")
            if concern:
                lines.append(f"⚠️ Watch: {concern}")

            await dispatcher.send_telegram("\n".join(lines))
        except Exception as e:
            log.warning("campaign_insights.telegram_failed", error=str(e))

    async def run(self, db: AsyncSession) -> dict:
        """Main entry point — call from APScheduler job."""
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        log.info("campaign_insights.starting", date=date_str)

        snapshots = await self._fetch_snapshots(db, hours=24)
        if not snapshots:
            log.warning("campaign_insights.no_data")
            return {"summary": "No campaign data in last 24h.", "insights": []}

        data_block = self._build_data_block(snapshots)
        result = await self._analyze(data_block)

        await self._save_to_memory(db, result, date_str)
        await self._send_telegram(result, date_str)

        log.info(
            "campaign_insights.complete",
            date=date_str,
            insights_count=len(result.get("insights", [])),
        )
        return result


# Singleton
insights_engine = CampaignInsightsEngine()
