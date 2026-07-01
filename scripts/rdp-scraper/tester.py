"""
JARVIS Meta Ads Profile Tester — run on RDP machines to discover logged-in profiles.

Usage: python tester.py
Output: logged-in profile IDs + ports to paste into config.json fixed_ports
"""

import asyncio
import httpx

ADSPOWER = "http://localhost:50325"


async def test_profile(uid: str, name: str) -> int | None:
    async with httpx.AsyncClient(timeout=15.0) as c:
        r = await c.get(
            f"{ADSPOWER}/api/v1/browser/start",
            params={"user_id": uid, "open_tabs": 1},
        )
        d = r.json()
        if d.get("code") != 0:
            print(f"  [{name}] Failed: {d.get('msg', '')}")
            return None
        port = d["data"]["debug_port"]
        await asyncio.sleep(4)
        await c.put(
            f"http://localhost:{port}/json/new"
            "?https://adsmanager.facebook.com/adsmanager/manage/campaigns"
        )
        await asyncio.sleep(6)
        tabs = (await c.get(f"http://localhost:{port}/json/list")).json()
        for t in tabs:
            url = t.get("url", "")
            if "adsmanager.facebook.com" in url and "login" not in url:
                print(f"  [{name}] LOGGED IN on port {port}: {url[:80]}")
                return port
        print(f"  [{name}] Not logged in")
        await c.get(f"{ADSPOWER}/api/v1/browser/stop", params={"user_id": uid})
        return None


async def main() -> None:
    r = httpx.get(f"{ADSPOWER}/api/v1/user/list?page=1&page_size=100")
    profiles = r.json().get("data", {}).get("list", [])
    print(f"Testing {len(profiles)} profiles...")
    ports: list[int] = []
    for p in profiles:
        port = await test_profile(p["user_id"], p["name"])
        if port:
            ports.append(port)
    print(f"\nUse ports {ports} in config.json")


if __name__ == "__main__":
    asyncio.run(main())
