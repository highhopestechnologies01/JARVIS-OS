"""
Planner Agent — Uses Claude API to reason and generate briefings.

Responsibilities:
- Generate daily executive briefings
- Reason about priorities given context
- Summarize information from multiple sources
"""

from datetime import date
from typing import Any

import structlog
from anthropic import AsyncAnthropic

from src.config import settings

log = structlog.get_logger()

BRIEFING_SYSTEM_PROMPT = """You are Hermes, the personal AI executive assistant for Thomas Shelby.

Your role:
- Synthesize information into clear, actionable executive briefings
- Be concise but complete — no filler, no fluff
- Lead with what matters most
- Flag anything that needs Thomas's attention or a decision
- Use a professional but direct tone

Output format: Markdown with clear sections.
Always include:
1. Priority Today (top 3 items requiring action)
2. Status (infrastructure, automations, ongoing work)
3. Watchlist (anything to monitor but not act on yet)
4. Recommended Actions (specific next steps)
"""


class PlannerAgent:
    """Uses Claude to generate plans and briefings."""

    def __init__(self):
        self._client: AsyncAnthropic | None = None

    @property
    def client(self) -> AsyncAnthropic:
        if not self._client:
            self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        return self._client

    async def generate_briefing(
        self,
        context: dict[str, Any],
        target_date: date | None = None,
    ) -> str:
        """Generate a daily executive briefing given context data."""
        if not settings.anthropic_api_key:
            log.warning("planner.no_api_key")
            return self._fallback_briefing(target_date or date.today())

        target_date = target_date or date.today()

        context_text = self._format_context(context)

        user_message = f"""Generate the executive briefing for {target_date.strftime('%A, %B %d, %Y')}.

Context:
{context_text}

Generate a complete briefing."""

        log.info("planner.generating_briefing", date=str(target_date))

        response = await self.client.messages.create(
            model="claude-opus-4-8",
            max_tokens=2000,
            system=BRIEFING_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        briefing = response.content[0].text
        log.info("planner.briefing_generated", date=str(target_date), tokens=response.usage.output_tokens)
        return briefing

    async def summarize(self, text: str, max_sentences: int = 3) -> str:
        """Summarize a piece of text concisely."""
        if not settings.anthropic_api_key:
            return text[:500] + "..." if len(text) > 500 else text

        response = await self.client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": f"Summarize this in {max_sentences} sentences. Be direct:\n\n{text}"
            }],
        )
        return response.content[0].text

    def _format_context(self, context: dict[str, Any]) -> str:
        """Format context dict into readable text for the prompt."""
        lines = []
        for key, value in context.items():
            if isinstance(value, list):
                lines.append(f"\n{key.upper()}:")
                for item in value:
                    lines.append(f"  - {item}")
            elif isinstance(value, dict):
                lines.append(f"\n{key.upper()}:")
                for k, v in value.items():
                    lines.append(f"  {k}: {v}")
            else:
                lines.append(f"{key.upper()}: {value}")
        return "\n".join(lines)

    def _fallback_briefing(self, target_date: date) -> str:
        """Fallback when Claude API is unavailable."""
        return f"""# Executive Briefing — {target_date.strftime('%A, %B %d, %Y')}

⚠️ Note: Generated without AI (API key not configured).

## Priority Today
- Configure ANTHROPIC_API_KEY to enable AI briefings
- Check infrastructure health: run `./scripts/health-check.sh`

## Status
- Hermes is running (scheduler active)
- AI features disabled until API key provided

## Next Steps
1. Add ANTHROPIC_API_KEY to .env
2. Restart Hermes container
"""


# Singleton
planner = PlannerAgent()
