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
        "n8n":        "http://n8n-n8n-1:5678/healthz",
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


async def _handle_ai(chat_id: int, text: str) -> None:
    """Pass free-text to Claude Haiku and reply."""
    from anthropic import AsyncAnthropic
    await _send(chat_id, "🤔 Thinking...")
    try:
        client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            system=(
                "You are JARVIS, the AI chief of staff for Thomas Shelby. "
                "Be concise, direct, and useful. No filler. Plain text only (no markdown)."
            ),
            messages=[{"role": "user", "content": text}],
        )
        reply = response.content[0].text
    except Exception as e:
        reply = f"Error calling Claude: {e}"
    await _send(chat_id, reply, parse_mode="")


HELP_TEXT = """<b>🤖 JARVIS Commands</b>

/status — infrastructure health
/briefing — today's executive briefing
/memory — last 5 memory entries
/rdp — RDP machine statuses
/help — this message

Or just type anything to ask Claude Haiku."""


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
        elif cmd == "/rdp":
            await _handle_rdp(chat_id)
        elif cmd in ("/help", "/start"):
            await _send(chat_id, HELP_TEXT)
        else:
            await _handle_ai(chat_id, text)
