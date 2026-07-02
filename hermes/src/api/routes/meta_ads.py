"""
Meta Ads — ingest endpoint (receives data from RDP scraper),
query endpoints (serves dashboard + Telegram), and campaign
command queue (toggle campaigns on/off via CDP).

Auth: X-Scraper-Token header on POST /ingest and command endpoints.
"""

import json
from datetime import datetime, timezone, timedelta, date as date_type
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.db.connection import get_db
from src.db.models import MetaAdsSnapshot, Memory, CampaignCommand

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1/meta-ads", tags=["meta-ads"])


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class CampaignData(BaseModel):
    name: str | None = None
    status: str | None = None
    budget: str | None = None
    results: str | None = None
    reach: str | None = None
    impressions: str | None = None
    clicks: str | None = None
    ctr: str | None = None
    cpc: str | None = None
    cpm: str | None = None
    spend: str | None = None
    extra: dict[str, Any] = {}


class ProfilePayload(BaseModel):
    profile_id: str
    profile_name: str | None = None
    ad_account_id: str | None = None
    ad_account_name: str | None = None
    campaigns: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    error: str | None = None


class IngestPayload(BaseModel):
    rdp_host: str           # "RDP-1" | "RDP-2"
    scraped_at: datetime
    profiles: list[ProfilePayload]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _require_scraper_token(request: Request) -> None:
    if not settings.scraper_token:
        return  # not configured — open (dev mode)
    token = request.headers.get("X-Scraper-Token", "")
    if token != settings.scraper_token:
        raise HTTPException(status_code=401, detail="Invalid scraper token")


def _date_window(date_str: str | None) -> tuple[datetime, datetime]:
    """Return (start, end) UTC datetimes for querying."""
    if date_str:
        try:
            d = date_type.fromisoformat(date_str)
            start = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=timezone.utc)
            return start, start + timedelta(days=1)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date — use YYYY-MM-DD")
    now = datetime.now(timezone.utc)
    return now - timedelta(hours=2), now


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/ingest")
async def ingest(
    payload: IngestPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Receive scraped Meta Ads data from an RDP machine."""
    _require_scraper_token(request)

    saved = 0
    for p in payload.profiles:
        snap = MetaAdsSnapshot(
            scraped_at=payload.scraped_at,
            rdp_host=payload.rdp_host,
            profile_id=p.profile_id,
            profile_name=p.profile_name,
            ad_account_id=p.ad_account_id,
            ad_account_name=p.ad_account_name,
            campaigns=p.campaigns,
            summary=p.summary,
            error=p.error,
        )
        db.add(snap)
        saved += 1

    await db.commit()
    log.info("meta_ads.ingest", rdp_host=payload.rdp_host, profiles=saved)

    # Run spend alerts (non-blocking background task — uses its own DB session)
    try:
        from src.core.spend_alerts import check_spend_alerts
        from src.db.connection import AsyncSessionLocal
        import asyncio

        profiles_dicts = [p.model_dump() for p in payload.profiles]
        rdp_host = payload.rdp_host
        scraped_at = payload.scraped_at

        async def _run_alerts():
            async with AsyncSessionLocal() as alert_db:
                await check_spend_alerts(alert_db, profiles_dicts, rdp_host, scraped_at)

        asyncio.create_task(_run_alerts())
    except Exception as e:
        log.warning("meta_ads.ingest.alerts_skipped", error=str(e))

    return {"status": "ok", "profiles_ingested": saved}


@router.get("/summary")
async def summary(
    date: str | None = Query(None, description="YYYY-MM-DD — omit for live (last 2h)"),
    db: AsyncSession = Depends(get_db),
):
    """
    Return latest snapshot per profile within the window with aggregated totals.
    date param: specific date (full day); omit for live last-2h view.
    """
    start, end = _date_window(date)
    result = await db.execute(
        select(MetaAdsSnapshot)
        .where(MetaAdsSnapshot.scraped_at >= start, MetaAdsSnapshot.scraped_at < end)
        .order_by(desc(MetaAdsSnapshot.scraped_at))
    )
    rows = result.scalars().all()

    # Keep latest snapshot per profile
    seen: dict[str, MetaAdsSnapshot] = {}
    for r in rows:
        if r.profile_id not in seen:
            seen[r.profile_id] = r
    latest = list(seen.values())

    # Aggregate
    total_spend = sum(r.summary.get("total_spend", 0) for r in latest)
    total_impr = sum(r.summary.get("total_impressions", 0) for r in latest)
    total_clicks = sum(r.summary.get("total_clicks", 0) for r in latest)
    active_campaigns = sum(r.summary.get("active_campaigns", 0) for r in latest)
    avg_ctr = round(total_clicks / total_impr * 100, 2) if total_impr > 0 else 0
    last_updated = max((r.scraped_at for r in latest), default=None) if latest else None

    profiles_out = []
    for r in latest:
        profiles_out.append({
            "profile_id": r.profile_id,
            "profile_name": r.profile_name,
            "ad_account_id": r.ad_account_id,
            "ad_account_name": r.ad_account_name,
            "rdp_host": r.rdp_host,
            "scraped_at": r.scraped_at.isoformat() if r.scraped_at else None,
            "campaigns": r.campaigns,
            "summary": r.summary,
            "error": r.error,
        })

    return {
        "total_spend": round(total_spend, 2),
        "total_impressions": total_impr,
        "total_clicks": total_clicks,
        "avg_ctr": avg_ctr,
        "active_campaigns": active_campaigns,
        "profiles_count": len(latest),
        "last_updated": last_updated.isoformat() if last_updated else None,
        "profiles": profiles_out,
        "stale": len(latest) == 0,
        "date": date,
    }


@router.get("/control")
async def get_control(db: AsyncSession = Depends(get_db)):
    """Return scraper enabled/disabled state."""
    result = await db.execute(
        select(Memory).where(Memory.type == "config", Memory.topic == "scraper_control")
    )
    row = result.scalar_one_or_none()
    if row is None:
        return {"enabled": True, "updated_at": None}
    data = json.loads(row.content)
    return {
        "enabled": data.get("enabled", True),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


class ControlPayload(BaseModel):
    enabled: bool


@router.post("/control")
async def set_control(
    payload: ControlPayload,
    db: AsyncSession = Depends(get_db),
):
    """Enable or disable the scraper. Called by dashboard toggle."""
    result = await db.execute(
        select(Memory).where(Memory.type == "config", Memory.topic == "scraper_control")
    )
    row = result.scalar_one_or_none()
    content = json.dumps({"enabled": payload.enabled})
    if row is None:
        row = Memory(type="config", topic="scraper_control", content=content, importance=10)
        db.add(row)
    else:
        row.content = content
    await db.commit()
    log.info("meta_ads.control", enabled=payload.enabled)
    return {"enabled": payload.enabled}


@router.get("/campaigns")
async def campaigns(
    rdp_host: str | None = None,
    date: str | None = Query(None, description="YYYY-MM-DD filter"),
    campaign: str | None = Query(None, description="Campaign name substring filter"),
    db: AsyncSession = Depends(get_db),
):
    """All campaigns from latest snapshots — filterable by date, RDP host, and name."""
    start, end = _date_window(date)
    q = (
        select(MetaAdsSnapshot)
        .where(MetaAdsSnapshot.scraped_at >= start, MetaAdsSnapshot.scraped_at < end)
        .order_by(desc(MetaAdsSnapshot.scraped_at))
    )
    result = await db.execute(q)
    rows = result.scalars().all()

    seen: dict[str, MetaAdsSnapshot] = {}
    for r in rows:
        key = f"{r.rdp_host}:{r.profile_id}"
        if key not in seen:
            seen[key] = r

    all_campaigns = []
    for r in seen.values():
        if rdp_host and r.rdp_host != rdp_host:
            continue
        for c in r.campaigns:
            c_name = c.get("name", "")
            if campaign and campaign.lower() not in c_name.lower():
                continue
            all_campaigns.append({
                **c,
                "profile_id": r.profile_id,
                "profile_name": r.profile_name,
                "ad_account_name": r.ad_account_name,
                "rdp_host": r.rdp_host,
            })

    return {"campaigns": all_campaigns, "total": len(all_campaigns)}


# ── Campaign Command Queue ────────────────────────────────────────────────────

class CommandPayload(BaseModel):
    rdp_host: str
    profile_id: str
    campaign_name: str
    action: str     # "ACTIVATE" | "PAUSE"


class CommandResultPayload(BaseModel):
    status: str     # "done" | "failed"
    error: str | None = None


@router.post("/commands")
async def queue_command(
    payload: CommandPayload,
    db: AsyncSession = Depends(get_db),
):
    """Queue a campaign on/off command. Dashboard or Telegram calls this."""
    if payload.action not in ("ACTIVATE", "PAUSE"):
        raise HTTPException(status_code=400, detail="action must be ACTIVATE or PAUSE")

    cmd = CampaignCommand(
        rdp_host=payload.rdp_host,
        profile_id=payload.profile_id,
        campaign_name=payload.campaign_name,
        action=payload.action,
    )
    db.add(cmd)
    await db.commit()
    await db.refresh(cmd)
    log.info("meta_ads.command.queued", campaign=payload.campaign_name, action=payload.action)
    return {"id": str(cmd.id), "status": "pending"}


@router.get("/commands/pending")
async def get_pending_commands(
    request: Request,
    rdp_host: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Return pending commands for a given RDP host. Called by the scraper."""
    _require_scraper_token(request)
    q = select(CampaignCommand).where(CampaignCommand.status == "pending")
    if rdp_host:
        q = q.where(CampaignCommand.rdp_host == rdp_host)
    result = await db.execute(q.order_by(CampaignCommand.created_at))
    cmds = result.scalars().all()
    return {
        "commands": [
            {
                "id": str(c.id),
                "profile_id": c.profile_id,
                "campaign_name": c.campaign_name,
                "action": c.action,
                "created_at": c.created_at.isoformat(),
            }
            for c in cmds
        ]
    }


@router.patch("/commands/{cmd_id}/result")
async def report_command_result(
    cmd_id: str,
    payload: CommandResultPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Scraper reports back whether the command succeeded or failed."""
    _require_scraper_token(request)

    result = await db.execute(
        select(CampaignCommand).where(CampaignCommand.id == cmd_id)
    )
    cmd = result.scalar_one_or_none()
    if not cmd:
        raise HTTPException(status_code=404, detail="Command not found")

    cmd.status = payload.status
    cmd.error = payload.error
    cmd.executed_at = datetime.now(timezone.utc)
    await db.commit()

    # Notify Thomas via Telegram
    try:
        from src.core.notifications import dispatcher
        action_word = "activated ✅" if cmd.action == "ACTIVATE" else "paused ⏸"
        if payload.status == "done":
            msg = f"📊 Campaign <b>{cmd.campaign_name}</b> {action_word} on {cmd.rdp_host}"
        else:
            msg = f"❌ Failed to toggle <b>{cmd.campaign_name}</b> on {cmd.rdp_host}: {payload.error or 'unknown'}"
        await dispatcher.send_telegram(msg)
    except Exception as e:
        log.warning("meta_ads.command.notify_failed", error=str(e))

    log.info("meta_ads.command.result", id=cmd_id, status=payload.status)
    return {"id": cmd_id, "status": payload.status}


# ── Budget Config ─────────────────────────────────────────────────────────────

class BudgetConfigPayload(BaseModel):
    enabled: bool = True
    total_daily_cap: float = 0.0          # 0 = disabled
    alert_pct: float = 80.0               # alert at this % of campaign budget
    auto_pause_pct: float = 100.0         # auto-pause at this %
    stopped_detection: bool = True
    campaign_budgets: dict[str, float] = {}   # {"Campaign Name": daily_budget_usd}


@router.get("/budget-config")
async def get_budget_config(db: AsyncSession = Depends(get_db)):
    """Return current spend alert config."""
    from src.core.spend_alerts import load_config
    cfg = await load_config(db)
    return cfg


@router.post("/budget-config")
async def set_budget_config(
    payload: BudgetConfigPayload,
    db: AsyncSession = Depends(get_db),
):
    """Save spend alert config. Called by dashboard settings."""
    from src.core.spend_alerts import save_config
    cfg = payload.model_dump()
    await save_config(db, cfg)
    log.info("meta_ads.budget_config.saved", total_cap=payload.total_daily_cap)
    return {"status": "ok", "config": cfg}


# ── Campaign Insights ─────────────────────────────────────────────────────────

@router.get("/insights")
async def get_insights(db: AsyncSession = Depends(get_db)):
    """Return latest stored AI campaign insights from Memory table."""
    result = await db.execute(
        select(Memory).where(Memory.type == "insight", Memory.topic == "campaign_insights")
    )
    row = result.scalar_one_or_none()
    if row is None:
        return {"available": False, "data": None, "updated_at": None}
    try:
        data = json.loads(row.content)
    except Exception:
        data = {"summary": row.content}
    return {
        "available": True,
        "data": data,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.post("/insights/run")
async def run_insights():
    """Manually trigger campaign insights analysis (for dashboard ▶ button)."""
    from src.core.campaign_insights import insights_engine
    from src.db.connection import AsyncSessionLocal
    import asyncio

    async def _run():
        async with AsyncSessionLocal() as bg_db:
            await insights_engine.run(bg_db)

    asyncio.create_task(_run())
    return {"status": "queued"}
