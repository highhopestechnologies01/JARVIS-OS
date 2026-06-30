"""
Meta Ads — ingest endpoint (receives data from RDP scraper)
and query endpoints (serves dashboard + Telegram).

Auth: X-Scraper-Token header on POST /ingest.
"""

from datetime import datetime, timezone, timedelta
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.db.connection import get_db
from src.db.models import MetaAdsSnapshot

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
    return {"status": "ok", "profiles_ingested": saved}


@router.get("/summary")
async def summary(db: AsyncSession = Depends(get_db)):
    """
    Return latest snapshot per profile (last 2 hours) with aggregated totals.
    Used by dashboard panel and Telegram /ads command.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=2)
    result = await db.execute(
        select(MetaAdsSnapshot)
        .where(MetaAdsSnapshot.scraped_at >= cutoff)
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
    }


@router.get("/campaigns")
async def campaigns(
    rdp_host: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """All campaigns from latest snapshots, optionally filtered by RDP host."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=2)
    q = select(MetaAdsSnapshot).where(MetaAdsSnapshot.scraped_at >= cutoff).order_by(
        desc(MetaAdsSnapshot.scraped_at)
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
            all_campaigns.append({
                **c,
                "profile_name": r.profile_name,
                "ad_account_name": r.ad_account_name,
                "rdp_host": r.rdp_host,
            })

    return {"campaigns": all_campaigns, "total": len(all_campaigns)}
