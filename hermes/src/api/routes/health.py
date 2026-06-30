"""Health check endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    service: str
    timestamp: str
    version: str = "1.0.0"


@router.get("/health", response_model=HealthResponse)
async def health():
    """Liveness probe — returns 200 if Hermes is running."""
    return HealthResponse(
        status="ok",
        service="hermes",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/health/ready")
async def ready():
    """Readiness probe — checks DB and Redis connectivity."""
    from src.db.connection import engine
    import sqlalchemy

    checks = {}

    # Database
    try:
        async with engine.connect() as conn:
            await conn.execute(sqlalchemy.text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"

    all_ok = all(v == "ok" for v in checks.values())
    status_code = 200 if all_ok else 503

    return {"status": "ready" if all_ok else "not_ready", "checks": checks}
