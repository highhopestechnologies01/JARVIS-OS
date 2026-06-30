"""
Coolify API integration.
Provides read access to Coolify deployment state for JARVIS context.
Base URL: http://10.0.6.1:8000 (jarvis-net bridge gateway → Coolify port 8000 on host)
"""

import os
from typing import Any

import httpx
import structlog

log = structlog.get_logger()

COOLIFY_API_URL = os.getenv("COOLIFY_API_URL", "http://10.0.6.1:8000")
COOLIFY_API_TOKEN = os.getenv("COOLIFY_API_TOKEN", "")


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {COOLIFY_API_TOKEN}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


async def get_version() -> dict[str, Any]:
    """Get Coolify version info."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        r = await client.get(f"{COOLIFY_API_URL}/api/v1/version", headers=_headers())
        r.raise_for_status()
        return {"version": r.text.strip('"')}


async def get_servers() -> list[dict[str, Any]]:
    """List all servers managed by Coolify."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"{COOLIFY_API_URL}/api/v1/servers", headers=_headers())
        r.raise_for_status()
        return r.json()


async def get_projects() -> list[dict[str, Any]]:
    """List all Coolify projects."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"{COOLIFY_API_URL}/api/v1/projects", headers=_headers())
        r.raise_for_status()
        return r.json()


async def get_services() -> list[dict[str, Any]]:
    """List all Coolify services (e.g. n8n, databases)."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"{COOLIFY_API_URL}/api/v1/services", headers=_headers())
        r.raise_for_status()
        return r.json()


async def get_applications() -> list[dict[str, Any]]:
    """List all Coolify applications."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"{COOLIFY_API_URL}/api/v1/applications", headers=_headers())
        r.raise_for_status()
        return r.json()


async def get_deployment_status() -> dict[str, Any]:
    """
    Aggregate Coolify deployment status for JARVIS context.
    Returns servers, projects, services, and apps in a single call.
    """
    results: dict[str, Any] = {"version": None, "servers": [], "services": [], "applications": []}
    try:
        results["version"] = (await get_version()).get("version")
    except Exception as e:
        log.warning("coolify.version_failed", error=str(e))

    for key, coro_fn in [("servers", get_servers), ("services", get_services), ("applications", get_applications)]:
        try:
            results[key] = await coro_fn()
        except Exception as e:
            log.warning(f"coolify.{key}_failed", error=str(e))

    return results


async def restart_service(service_uuid: str) -> dict[str, Any]:
    """Restart a Coolify service by UUID."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(
            f"{COOLIFY_API_URL}/api/v1/services/{service_uuid}/restart",
            headers=_headers(),
        )
        r.raise_for_status()
        return r.json()
