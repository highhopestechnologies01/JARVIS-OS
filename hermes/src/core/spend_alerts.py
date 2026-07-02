"""
Spend Alert Engine — runs after every Meta Ads ingest.

Checks:
1. Campaign spend ≥ alert_pct% of daily budget → Telegram alert
2. Campaign spend ≥ auto_pause_pct% of daily budget → alert + auto-pause via CDP
3. Total daily spend across all profiles ≥ total_daily_cap → alert
4. Campaign suddenly stopped (had spend last cycle, now $0, still active) → alert

Budget config is stored in Memory table (type="config", topic="spend_alerts_config").
Default config applied if none set.
"""

import json
from datetime import datetime, timezone, timedelta, date as date_type
from typing import Any

import structlog
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Memory, MetaAdsSnapshot, CampaignCommand

log = structlog.get_logger()

DEFAULT_CONFIG = {
    "enabled": True,
    "total_daily_cap": 0.0,          # 0 = disabled
    "alert_pct": 80,                  # alert at 80% of campaign budget
    "auto_pause_pct": 100,            # auto-pause at 100% of budget
    "campaign_budgets": {},           # {"Campaign Name": daily_budget_usd}
    "stopped_detection": True,        # alert when active campaign drops to $0
}


async def load_config(db: AsyncSession) -> dict:
    result = await db.execute(
        select(Memory).where(Memory.type == "config", Memory.topic == "spend_alerts_config")
    )
    row = result.scalar_one_or_none()
    if row is None:
        return DEFAULT_CONFIG.copy()
    try:
        stored = json.loads(row.content)
        cfg = DEFAULT_CONFIG.copy()
        cfg.update(stored)
        return cfg
    except Exception:
        return DEFAULT_CONFIG.copy()


async def save_config(db: AsyncSession, config: dict) -> None:
    result = await db.execute(
        select(Memory).where(Memory.type == "config", Memory.topic == "spend_alerts_config")
    )
    row = result.scalar_one_or_none()
    content = json.dumps(config)
    if row is None:
        row = Memory(type="config", topic="spend_alerts_config", content=content, importance=10)
        db.add(row)
    else:
        row.content = content
    await db.commit()


def _parse_spend(spend_str: str | None) -> float:
    """Parse spend string like '$12.34' or '12.34' to float."""
    if not spend_str:
        return 0.0
    try:
        return float(str(spend_str).replace("$", "").replace(",", "").strip())
    except (ValueError, TypeError):
        return 0.0


def _is_active(status: str | None) -> bool:
    if not status:
        return False
    s = status.lower()
    return any(k in s for k in ("active", "delivering", "learning", "in review"))


async def _get_previous_snapshot(
    db: AsyncSession, rdp_host: str, profile_id: str, before: datetime
) -> MetaAdsSnapshot | None:
    result = await db.execute(
        select(MetaAdsSnapshot)
        .where(
            MetaAdsSnapshot.rdp_host == rdp_host,
            MetaAdsSnapshot.profile_id == profile_id,
            MetaAdsSnapshot.scraped_at < before,
        )
        .order_by(desc(MetaAdsSnapshot.scraped_at))
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _queue_pause(
    db: AsyncSession, rdp_host: str, profile_id: str, campaign_name: str
) -> None:
    cmd = CampaignCommand(
        rdp_host=rdp_host,
        profile_id=profile_id,
        campaign_name=campaign_name,
        action="PAUSE",
    )
    db.add(cmd)
    await db.commit()
    log.info("spend_alerts.auto_pause_queued", campaign=campaign_name, rdp=rdp_host)


async def _send_alert(msg: str, kb: dict | None = None) -> None:
    """Send Telegram alert via Hermes notification dispatcher."""
    try:
        from src.core.notifications import dispatcher
        await dispatcher.send_telegram(msg, reply_markup=kb)
    except Exception as e:
        log.warning("spend_alerts.telegram_failed", error=str(e))


def _pause_kb(rdp_host: str, profile_id: str, campaign_name: str) -> dict:
    """Inline keyboard with a Pause Now button."""
    import urllib.parse
    data = f"pause:{rdp_host}:{profile_id}:{urllib.parse.quote(campaign_name[:50])}"
    return {
        "inline_keyboard": [[
            {"text": "⏸ Pause Now", "callback_data": data},
            {"text": "✅ Dismiss", "callback_data": "alert:dismiss"},
        ]]
    }


async def check_spend_alerts(
    db: AsyncSession,
    profiles: list[dict],
    rdp_host: str,
    scraped_at: datetime,
) -> None:
    """
    Main entry point — call this after saving a successful ingest.
    profiles: list of ProfilePayload dicts (same as IngestPayload.profiles).
    """
    cfg = await load_config(db)
    if not cfg.get("enabled"):
        return

    alert_pct: float = cfg.get("alert_pct", 80)
    auto_pause_pct: float = cfg.get("auto_pause_pct", 100)
    total_daily_cap: float = cfg.get("total_daily_cap", 0.0)
    campaign_budgets: dict = cfg.get("campaign_budgets", {})
    stopped_detection: bool = cfg.get("stopped_detection", True)

    total_today_spend = 0.0

    for p in profiles:
        profile_id = p.get("profile_id", "")
        profile_name = p.get("profile_name") or profile_id
        campaigns: list[dict] = p.get("campaigns", [])
        error = p.get("error")

        if error and not campaigns:
            continue  # scrape failed for this profile — skip

        # Get previous snapshot for stopped-campaign detection
        prev_snap = None
        if stopped_detection:
            prev_snap = await _get_previous_snapshot(db, rdp_host, profile_id, scraped_at)
        prev_campaigns: dict[str, dict] = {}
        if prev_snap:
            for c in prev_snap.campaigns:
                name = c.get("name", "")
                if name:
                    prev_campaigns[name] = c

        for c in campaigns:
            name = c.get("name", "")
            if not name:
                continue

            spend = _parse_spend(c.get("spend"))
            status = c.get("status", "")
            total_today_spend += spend

            budget = campaign_budgets.get(name, 0.0)

            # ── Budget % alerts ───────────────────────────────────────────────
            if budget > 0 and spend > 0:
                pct_used = (spend / budget) * 100

                if pct_used >= auto_pause_pct:
                    # Auto-pause
                    await _queue_pause(db, rdp_host, profile_id, name)
                    msg = (
                        f"🚨 <b>AUTO-PAUSED</b> — Budget limit reached\n"
                        f"📊 <b>{name}</b>\n"
                        f"💰 Spent: <b>${spend:,.2f}</b> / ${budget:,.2f} budget "
                        f"(<b>{pct_used:.0f}%</b>)\n"
                        f"🖥 {rdp_host} · {profile_name}\n"
                        f"<i>Campaign paused via CDP — will execute on next scraper run</i>"
                    )
                    await _send_alert(msg)
                    log.info("spend_alerts.auto_pause", campaign=name, pct=pct_used)

                elif pct_used >= alert_pct:
                    msg = (
                        f"⚠️ <b>Budget Alert</b> — {pct_used:.0f}% spent\n"
                        f"📊 <b>{name}</b>\n"
                        f"💰 ${spend:,.2f} of ${budget:,.2f} daily budget\n"
                        f"🖥 {rdp_host} · {profile_name}"
                    )
                    kb = _pause_kb(rdp_host, profile_id, name)
                    await _send_alert(msg, kb)
                    log.info("spend_alerts.budget_alert", campaign=name, pct=pct_used)

            # ── Stopped campaign detection ────────────────────────────────────
            if stopped_detection and _is_active(status):
                prev = prev_campaigns.get(name)
                if prev:
                    prev_spend = _parse_spend(prev.get("spend"))
                    if prev_spend > 0 and spend == 0:
                        msg = (
                            f"🛑 <b>Campaign Stopped</b>\n"
                            f"📊 <b>{name}</b> was spending but dropped to $0\n"
                            f"📈 Previous spend: ${prev_spend:,.2f}\n"
                            f"🖥 {rdp_host} · {profile_name}\n"
                            f"Status still shows: {status}"
                        )
                        kb = _pause_kb(rdp_host, profile_id, name)
                        await _send_alert(msg, kb)
                        log.info("spend_alerts.campaign_stopped", campaign=name)

    # ── Total daily cap check ─────────────────────────────────────────────────
    if total_daily_cap > 0 and total_today_spend >= total_daily_cap:
        msg = (
            f"🚨 <b>Daily Cap Hit!</b>\n"
            f"💰 Total spend: <b>${total_today_spend:,.2f}</b> "
            f"(cap: ${total_daily_cap:,.2f})\n"
            f"🖥 {rdp_host}\n"
            f"<i>Review all active campaigns immediately.</i>"
        )
        await _send_alert(msg)
        log.info("spend_alerts.daily_cap_hit", total=total_today_spend, cap=total_daily_cap)
