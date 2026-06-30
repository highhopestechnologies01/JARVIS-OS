"""
Coolify integration API routes.
Exposes Coolify deployment state to the JARVIS dashboard and context builder.
"""

from fastapi import APIRouter, HTTPException
import structlog

from src.integrations.coolify import get_deployment_status, restart_service

router = APIRouter(prefix="/api/v1/coolify", tags=["coolify"])
log = structlog.get_logger()


@router.get("/status")
async def coolify_status():
    """
    GET /api/v1/coolify/status
    Returns aggregated Coolify deployment state: version, servers, services, apps.
    """
    try:
        status = await get_deployment_status()
        return {"ok": True, "data": status}
    except Exception as e:
        log.error("coolify.status_error", error=str(e))
        raise HTTPException(status_code=502, detail=f"Coolify unreachable: {e}")


@router.post("/services/{service_uuid}/restart")
async def restart_coolify_service(service_uuid: str):
    """
    POST /api/v1/coolify/services/{uuid}/restart
    Restart a Coolify-managed service by UUID.
    """
    try:
        result = await restart_service(service_uuid)
        return {"ok": True, "result": result}
    except Exception as e:
        log.error("coolify.restart_error", uuid=service_uuid, error=str(e))
        raise HTTPException(status_code=502, detail=str(e))
