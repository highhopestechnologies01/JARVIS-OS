"""
RDP machine monitoring.
Checks TCP port 3389 reachability for Windows RDP hosts.
"""

import asyncio
import os
from typing import Any

import structlog

log = structlog.get_logger()

# RDP machines — override via env vars if needed
RDP_HOSTS: list[dict[str, Any]] = [
    {
        "id": "rdp1",
        "name": "RDP-1",
        "ip": os.getenv("RDP1_IP", "162.35.164.39"),
        "port": int(os.getenv("RDP1_PORT", "3389")),
        "username": os.getenv("RDP1_USER", "Administrator"),
    },
    {
        "id": "rdp2",
        "name": "RDP-2",
        "ip": os.getenv("RDP2_IP", "163.245.215.175"),
        "port": int(os.getenv("RDP2_PORT", "3389")),
        "username": os.getenv("RDP2_USER", "administrator"),
    },
]


async def check_rdp_host(host: dict[str, Any], timeout: float = 5.0) -> dict[str, Any]:
    """
    TCP connect check on port 3389.
    Returns status dict with online/offline and latency.
    """
    ip = host["ip"]
    port = host["port"]
    try:
        start = asyncio.get_event_loop().time()
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port),
            timeout=timeout,
        )
        latency_ms = round((asyncio.get_event_loop().time() - start) * 1000)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        log.info("rdp.check.online", name=host["name"], ip=ip, latency_ms=latency_ms)
        return {
            "id": host["id"],
            "name": host["name"],
            "ip": ip,
            "port": port,
            "username": host.get("username", ""),
            "online": True,
            "latency_ms": latency_ms,
            "error": None,
        }
    except asyncio.TimeoutError:
        log.warning("rdp.check.timeout", name=host["name"], ip=ip)
        return {
            "id": host["id"],
            "name": host["name"],
            "ip": ip,
            "port": port,
            "username": host.get("username", ""),
            "online": False,
            "latency_ms": None,
            "error": "timeout",
        }
    except Exception as e:
        log.warning("rdp.check.error", name=host["name"], ip=ip, error=str(e))
        return {
            "id": host["id"],
            "name": host["name"],
            "ip": ip,
            "port": port,
            "username": host.get("username", ""),
            "online": False,
            "latency_ms": None,
            "error": str(e),
        }


async def check_all_rdp_hosts() -> list[dict[str, Any]]:
    """Check all configured RDP hosts concurrently."""
    results = await asyncio.gather(*[check_rdp_host(h) for h in RDP_HOSTS])
    return list(results)
