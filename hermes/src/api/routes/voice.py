"""Voice command API route."""

from fastapi import APIRouter
from pydantic import BaseModel

from src.config import settings
from anthropic import AsyncAnthropic
import structlog

log = structlog.get_logger()
router = APIRouter()

VOICE_SYSTEM_PROMPT = """You are JARVIS, Thomas Shelby's personal AI executive assistant.

Respond to voice commands concisely and conversationally — this response will be spoken aloud.
- Keep responses under 3 sentences unless more detail is explicitly requested
- Be direct and actionable
- Address Thomas by name occasionally
- You have access to his infrastructure (JARVIS OS), briefings, and memory system
- If asked about system status, infrastructure is currently running: Hermes, PostgreSQL, Redis, n8n, Prometheus, Grafana
- Speak like a trusted chief of staff, not a chatbot
"""


class VoiceCommandRequest(BaseModel):
    text: str
    context: str | None = None


class VoiceCommandResponse(BaseModel):
    response: str
    action_taken: str | None = None


@router.post("/command", response_model=VoiceCommandResponse)
async def voice_command(body: VoiceCommandRequest) -> VoiceCommandResponse:
    """Process a voice command and return a spoken response."""
    log.info("voice.command_received", text=body.text[:100])

    if not settings.anthropic_api_key:
        return VoiceCommandResponse(
            response="JARVIS is offline. Anthropic API key not configured.",
            action_taken=None,
        )

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    messages = [{"role": "user", "content": body.text}]
    if body.context:
        messages[0]["content"] = f"Context: {body.context}\n\nCommand: {body.text}"

    try:
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=VOICE_SYSTEM_PROMPT,
            messages=messages,
        )
        reply = response.content[0].text
        log.info("voice.command_processed", tokens=response.usage.output_tokens)
        return VoiceCommandResponse(response=reply, action_taken=None)

    except Exception as e:
        log.error("voice.command_failed", error=str(e))
        return VoiceCommandResponse(
            response=f"I encountered an error processing that command: {str(e)[:100]}",
            action_taken=None,
        )
