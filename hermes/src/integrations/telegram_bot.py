"""
JARVIS Telegram Bot — command handler using long-polling.
Runs as an APScheduler job every 10 seconds.

Commands:
  /status   — infrastructure health summary
  /briefing — today's executive briefing
  /memory   — last 5 memory entries
  /rdp      — RDP machine statuses
  /help     — list commands
  <text>    — ask Claude Haiku anything
"""

import structlog
import httpx

from src.config import settings

log = structlog.get_logger()

TELEGRAM_API = f"https://api.telegram.org/bot{settings.telegram_bot_token}"

# Track last processed update_id to avoid reprocessing
_last_update_id: int = 0


async def _send(chat_id: str | int, text: str, parse_mode: str = "HTML") -> None:
    """Send a message back to the user."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(f"{TELEGRAM_API}/sendMessage", json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
            })
    except Exception as e:
        log.error("telegram_bot.send.failed", error=str(e))


async def _get_updates(offset: int = 0) -> list[dict]:
    """Long-poll for new messages."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{TELEGRAM_API}/getUpdates", params={
                "offset": offset,
                "timeout": 5,
                "allowed_updates": ["message"],
            })
            data = resp.json()
            return data.get("result", [])
    except Exception as e:
        log.warning("telegram_bot.poll.failed", error=str(e))
        return []


async def _handle_status(chat_id: int) -> None:
    """Return live infrastructure health."""
    import httpx as _httpx
    services = {
        "hermes":     "http://localhost:8000/api/v1/health/ready",
        "n8n":        "http://jarvis-n8n:5677/healthz",
        "grafana":    "http://jarvis-grafana:3000/api/health",
        "prometheus": "http://jarvis-prometheus:9090/-/healthy",
    }
    lines = ["<b>🖥 JARVIS Infrastructure Status</b>\n"]
    async with _httpx.AsyncClient(timeout=5.0) as client:
        for name, url in services.items():
            try:
                r = await client.get(url)
                icon = "✅" if r.status_code < 400 else "❌"
            except Exception:
                icon = "❌"
            lines.append(f"{icon} {name}")

    # RDP
    from src.integrations.rdp import check_all_rdp_hosts
    rdp_results = await check_all_rdp_hosts()
    lines.append("")
    for rdp in rdp_results:
        icon = "✅" if rdp["online"] else "❌"
        lat = f" {rdp['latency_ms']}ms" if rdp["online"] else ""
        lines.append(f"{icon} {rdp['name']} ({rdp['ip']}){lat}")

    await _send(chat_id, "\n".join(lines))


async def _handle_briefing(chat_id: int) -> None:
    """Return today's briefing from DB, or generate one."""
    from src.db.connection import AsyncSessionLocal
    from src.db.models import Briefing
    from sqlalchemy import select
    from datetime import date

    await _send(chat_id, "⏳ Fetching today's briefing...")

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Briefing)
            .where(Briefing.date == date.today())
            .order_by(Briefing.created_at.desc())
            .limit(1)
        )
        briefing = result.scalar_one_or_none()

    if briefing:
        text = f"<b>📋 Briefing — {briefing.date}</b>\n\n{briefing.content[:3800]}"
        if len(briefing.content) > 3800:
            text += "\n\n<i>[truncated — full briefing in dashboard]</i>"
    else:
        text = "No briefing for today yet. Use the dashboard Scheduler panel to trigger one manually."

    await _send(chat_id, text)


async def _handle_memory(chat_id: int) -> None:
    """Return last 5 memory entries."""
    from src.db.connection import AsyncSessionLocal
    from src.db.models import Memory
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Memory)
            .order_by(Memory.created_at.desc())
            .limit(5)
        )
        memories = result.scalars().all()

    if not memories:
        await _send(chat_id, "No memories stored yet.")
        return

    lines = ["<b>🧠 Recent Memories</b>\n"]
    for m in memories:
        lines.append(f"<b>{m.topic}</b> [{m.type}]\n{m.content[:200]}\n")

    await _send(chat_id, "\n".join(lines))


async def _handle_rdp(chat_id: int) -> None:
    """Return RDP machine statuses."""
    from src.integrations.rdp import check_all_rdp_hosts
    results = await check_all_rdp_hosts()
    lines = ["<b>🖥 RDP Machines</b>\n"]
    for r in results:
        icon = "🟢" if r["online"] else "🔴"
        lat = f" • {r['latency_ms']}ms" if r["online"] else f" • {r.get('error', 'offline')}"
        lines.append(f"{icon} <b>{r['name']}</b> — {r['ip']}\n   {r['username']}{lat}")
    lines.append("\nTunnel: localhost:13389 / localhost:23389")
    await _send(chat_id, "\n".join(lines))


async def _handle_ads(chat_id: int, date_arg: str | None = None) -> None:
    """Return Meta Ads summary — live (last 2h) or for a specific date."""
    label = f"for {date_arg}" if date_arg else "live"
    await _send(chat_id, f"⏳ Fetching Meta Ads data ({label})...")
    try:
        url = "http://localhost:8000/api/v1/meta-ads/summary"
        params = {"date": date_arg} if date_arg else {}
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            data = resp.json()
    except Exception as e:
        await _send(chat_id, f"❌ Failed to fetch ads data: {e}")
        return

    if data.get("stale") or data.get("profiles_count", 0) == 0:
        msg = f"⚠️ <b>No Meta Ads data</b> for {date_arg or 'last 2 hours'}."
        await _send(chat_id, msg)
        return

    title = f"📊 <b>Meta Ads — {date_arg or 'Live'}</b>"
    lines = [
        title,
        "",
        f"💰 Total Spend: <b>${data['total_spend']:,.2f}</b>",
        f"▶️ Active Campaigns: <b>{data['active_campaigns']}</b>",
        f"👁 Impressions: <b>{data['total_impressions']:,}</b>",
        f"📈 Avg CTR: <b>{data['avg_ctr']:.2f}%</b>",
        "",
        "<b>Campaigns:</b>",
    ]

    for p in data.get("profiles", []):
        s = p.get("summary", {})
        acc = p.get("ad_account_name") or p.get("profile_name") or p.get("profile_id")
        spend = s.get("total_spend", 0) or 0
        err = " ⚠️" if p.get("error") else ""
        lines.append(f"\n<b>{acc}</b>{err} [{p['rdp_host']}] ${spend:,.2f}")
        for c in p.get("campaigns", [])[:8]:
            name = c.get("name", "?")
            c_spend = c.get("spend", "")
            status = c.get("status", "")
            icon = "🟢" if "active" in status.lower() or "delivering" in status.lower() else "⚪"
            line = f"  {icon} {name}"
            if c_spend:
                line += f" · {c_spend}"
            lines.append(line)

    updated = data.get("last_updated", "")
    if updated:
        from datetime import datetime, timezone as tz
        try:
            dt = datetime.fromisoformat(updated)
            diff = int((datetime.now(tz.utc) - dt).total_seconds())
            age = f"{diff // 60}m ago" if diff >= 60 else f"{diff}s ago"
            lines.append(f"\n<i>Last scraped: {age}</i>")
        except Exception:
            pass

    await _send(chat_id, "\n".join(lines))


async def _handle_campaign_toggle(chat_id: int, action: str, campaign_name: str) -> None:
    """Queue a campaign ACTIVATE or PAUSE command."""
    if not campaign_name:
        cmd_word = "pause" if action == "PAUSE" else "activate"
        await _send(chat_id, f"Usage: /{cmd_word} &lt;campaign name&gt;")
        return

    await _send(chat_id, f"🔍 Searching for campaign <b>{campaign_name}</b>...")

    # Find campaign in recent snapshots (last 24h)
    from src.db.connection import AsyncSessionLocal
    from src.db.models import MetaAdsSnapshot
    from sqlalchemy import select, desc
    from datetime import datetime, timezone as tz, timedelta

    cutoff = datetime.now(tz.utc) - timedelta(hours=24)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(MetaAdsSnapshot)
            .where(MetaAdsSnapshot.scraped_at >= cutoff)
            .order_by(desc(MetaAdsSnapshot.scraped_at))
        )
        snapshots = result.scalars().all()

    # Find all profiles containing this campaign (case-insensitive)
    matches: list[dict] = []
    seen_profiles: set[str] = set()
    for snap in snapshots:
        key = f"{snap.rdp_host}:{snap.profile_id}"
        if key in seen_profiles:
            continue
        for c in snap.campaigns:
            if campaign_name.lower() in (c.get("name") or "").lower():
                matches.append({
                    "rdp_host": snap.rdp_host,
                    "profile_id": snap.profile_id,
                    "profile_name": snap.profile_name or snap.profile_id,
                    "campaign_name": c.get("name", campaign_name),
                })
                seen_profiles.add(key)
                break

    if not matches:
        await _send(chat_id, f"❌ No campaign found matching <b>{campaign_name}</b> in last 24h data.")
        return

    # Queue commands for all matching profiles
    action_word = "activate" if action == "ACTIVATE" else "pause"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            for m in matches:
                await client.post(
                    "http://localhost:8000/api/v1/meta-ads/commands",
                    json={
                        "rdp_host": m["rdp_host"],
                        "profile_id": m["profile_id"],
                        "campaign_name": m["campaign_name"],
                        "action": action,
                    },
                )
    except Exception as e:
        await _send(chat_id, f"❌ Failed to queue command: {e}")
        return

    profiles_str = ", ".join(f"{m['profile_name']} ({m['rdp_host']})" for m in matches)
    await _send(
        chat_id,
        f"⏳ Queued: <b>{action_word}</b> '<b>{matches[0]['campaign_name']}</b>'\n"
        f"Profiles: {profiles_str}\n\n"
        f"<i>Will execute on next scraper run (~5 min). You'll get a confirmation when done.</i>"
    )


async def _handle_workflows(chat_id: int) -> None:
    """Show recent n8n workflow activity stored in Hermes memory."""
    from src.db.connection import AsyncSessionLocal
    from src.db.models import Memory
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Memory)
            .where(Memory.source.ilike("%n8n%"))
            .order_by(Memory.created_at.desc())
            .limit(6)
        )
        memories = result.scalars().all()

    if not memories:
        await _send(chat_id, "No n8n workflow activity recorded yet.")
        return

    lines = ["<b>⚙️ Recent n8n Activity</b>\n"]
    for m in memories:
        ts = m.created_at.strftime("%m/%d %H:%M") if m.created_at else "?"
        preview = m.content[:180].replace("\n", " ")
        lines.append(f"<b>{m.topic or m.type}</b> [{ts}]\n{preview}\n")

    await _send(chat_id, "\n".join(lines))


async def _handle_intel(chat_id: int) -> None:
    """Show recent AI pattern insights."""
    from src.db.connection import AsyncSessionLocal
    from src.db.models import Memory
    from sqlalchemy import select, or_

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Memory)
            .where(or_(Memory.type == "pattern_insight", Memory.type == "weekly_plan"))
            .order_by(Memory.created_at.desc())
            .limit(4)
        )
        memories = result.scalars().all()

    if not memories:
        await _send(chat_id, "No AI insights yet. Pattern analysis runs at 3am daily.")
        return

    lines = ["<b>⚡ AI Insights</b>\n"]
    for m in memories:
        ts = m.created_at.strftime("%m/%d") if m.created_at else "?"
        lines.append(f"[{ts}] {m.content[:300]}\n")

    await _send(chat_id, "\n".join(lines))


_RUN_JOBS = {
    "briefing":  "daily_briefing",
    "health":    "health_check",
    "report":    "weekly_report",
    "pattern":   "pattern_analysis",
    "planning":  "autonomous_planning",
    "memory":    "memory_consolidation",
}


async def _handle_run(chat_id: int, arg: str) -> None:
    """Manually trigger a Hermes scheduler job by short name or ID."""
    job_id = _RUN_JOBS.get(arg.lower(), arg.lower())
    valid = ", ".join(sorted(_RUN_JOBS.keys()))

    if job_id not in _RUN_JOBS.values():
        await _send(chat_id, f"❓ Unknown job: <code>{arg}</code>\nValid: {valid}")
        return

    await _send(chat_id, f"⏳ Triggering <code>{job_id}</code>…")
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"http://localhost:8000/api/v1/scheduler/trigger/{job_id}"
            )
            if resp.status_code == 200:
                data = resp.json()
                await _send(chat_id, f"✅ <b>{data.get('job_name', job_id)}</b> triggered.")
            else:
                await _send(chat_id, f"❌ HTTP {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        await _send(chat_id, f"❌ Error: {e}")


async def _handle_calls(chat_id: int) -> None:
    """Return last 6 VAPI call events from memory."""
    from src.db.connection import AsyncSessionLocal
    from src.db.models import Memory
    from sqlalchemy import select, or_

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Memory)
            .where(or_(
                Memory.source == "vapi_webhook",
                Memory.type.in_(["call_transcript", "call_transfer", "call_status", "vapi_event"]),
            ))
            .order_by(Memory.created_at.desc())
            .limit(6)
        )
        calls = result.scalars().all()

    if not calls:
        await _send(chat_id, "📵 No VAPI call records yet.")
        return

    lines = ["<b>📞 Recent VAPI Calls</b>\n"]
    for c in calls:
        ts = c.created_at.strftime("%m/%d %H:%M") if c.created_at else "?"
        type_icon = {
            "call_transcript": "📞",
            "call_transfer": "🔀",
            "call_status": "📲",
            "vapi_event": "🔧",
            "vapi_tool_call": "🛠",
        }.get(c.type, "📋")
        preview = c.content[:150].replace("\n", " ")
        lines.append(f"{type_icon} <b>{c.type}</b> [{ts}]\n{preview}\n")

    await _send(chat_id, "\n".join(lines))


async def _handle_ai(chat_id: int, text: str) -> None:
    """Pass free-text to JARVIS AI (Groq via ai_client, Anthropic fallback)."""
    from src.core.ai_client import ai_client
    await _send(chat_id, "🤔 Thinking...")
    try:
        reply = await ai_client.chat(
            messages=[{"role": "user", "content": text}],
            model="fast",
            system=(
                "You are JARVIS, the AI chief of staff for Thomas Shelby. "
                "Be concise, direct, and useful. No filler. Plain text only (no markdown)."
            ),
            max_tokens=500,
        )
    except Exception as e:
        reply = f"Error: {e}"
    await _send(chat_id, reply, parse_mode="")


HELP_TEXT = """<b>🤖 JARVIS Commands</b>

/status — infrastructure health
/briefing — today's executive briefing
/memory — last 5 memory entries
/workflows — recent n8n automation activity
/intel — AI pattern insights
/calls — last 6 VAPI call records
/run &lt;job&gt; — trigger a job (briefing, health, report, pattern, planning, memory)
/rdp — RDP machine statuses
/ads — Meta Ads live summary
/ads 2026-07-01 — Meta Ads for a specific date
/pause &lt;campaign name&gt; — pause a campaign via CDP
/activate &lt;campaign name&gt; — activate a campaign via CDP
/help — this message

Or just type anything to ask JARVIS (Groq/Anthropic AI)."""


async def process_updates() -> None:
    """
    Poll Telegram for new messages and dispatch commands.
    Called by APScheduler every 10 seconds.
    """
    global _last_update_id

    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return

    updates = await _get_updates(offset=_last_update_id + 1)

    for update in updates:
        _last_update_id = update["update_id"]

        message = update.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        text = message.get("text", "").strip()

        if not chat_id or not text:
            continue

        # Security: only respond to the configured chat
        if str(chat_id) != str(settings.telegram_chat_id):
            log.warning("telegram_bot.unauthorized", chat_id=chat_id)
            continue

        log.info("telegram_bot.command", chat_id=chat_id, text=text[:50])

        cmd = text.lower().split()[0] if text else ""

        if cmd == "/status":
            await _handle_status(chat_id)
        elif cmd == "/briefing":
            await _handle_briefing(chat_id)
        elif cmd == "/memory":
            await _handle_memory(chat_id)
        elif cmd == "/workflows":
            await _handle_workflows(chat_id)
        elif cmd == "/intel":
            await _handle_intel(chat_id)
        elif cmd in ("/run", "/trigger"):
            args = text.split()
            if len(args) > 1:
                await _handle_run(chat_id, args[1])
            else:
                valid = ", ".join(sorted(_RUN_JOBS.keys()))
                await _send(chat_id, f"Usage: /run &lt;job&gt;\nValid jobs: {valid}")
        elif cmd == "/rdp":
            await _handle_rdp(chat_id)
        elif cmd == "/ads":
            parts = text.split()
            date_arg = parts[1] if len(parts) > 1 else None
            await _handle_ads(chat_id, date_arg)
        elif cmd in ("/pause", "/deactivate"):
            campaign_arg = " ".join(text.split()[1:])
            await _handle_campaign_toggle(chat_id, "PAUSE", campaign_arg)
        elif cmd == "/activate":
            campaign_arg = " ".join(text.split()[1:])
            await _handle_campaign_toggle(chat_id, "ACTIVATE", campaign_arg)
        elif cmd == "/calls":
            await _handle_calls(chat_id)
        elif cmd in ("/help", "/start"):
            await _send(chat_id, HELP_TEXT)
        else:
            await _handle_ai(chat_id, text)
