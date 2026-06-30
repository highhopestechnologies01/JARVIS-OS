"""
RDP machine status routes.
"""

from fastapi import APIRouter
import structlog

from src.integrations.rdp import check_all_rdp_hosts, RDP_HOSTS

router = APIRouter(prefix="/api/v1/rdp", tags=["rdp"])
log = structlog.get_logger()


@router.get("/status")
async def rdp_status():
    """
    GET /api/v1/rdp/status
    Returns online/offline status for all configured RDP machines.
    """
    results = await check_all_rdp_hosts()
    online_count = sum(1 for r in results if r["online"])
    return {
        "ok": True,
        "summary": f"{online_count}/{len(results)} online",
        "hosts": results,
    }


@router.get("/hosts")
async def rdp_hosts():
    """
    GET /api/v1/rdp/hosts
    Returns the list of configured RDP machines (no connectivity check).
    """
    return {
        "ok": True,
        "hosts": [{"id": h["id"], "name": h["name"], "ip": h["ip"], "port": h["port"]} for h in RDP_HOSTS],
    }
