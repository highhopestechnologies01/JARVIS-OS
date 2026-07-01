"""Scan for active Ads Power profiles and their Chrome debug ports."""
import asyncio
import httpx
import json


ADSPOWER_URL = "http://localhost:50325"


async def main():
    print("=== Ads Power Active Profile Scanner ===\n")

    # Method 1: Ads Power API
    print("--- Querying Ads Power API ---")
    found_via_api = []
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{ADSPOWER_URL}/api/v1/user/list",
                            params={"page": 1, "page_size": 100})
            profiles = r.json().get("data", {}).get("list", [])
            print(f"Total profiles in Ads Power: {len(profiles)}")
            for p in profiles:
                uid = p.get("user_id") or p.get("id")
                name = p.get("name", uid)
                try:
                    r2 = await c.get(f"{ADSPOWER_URL}/api/v1/browser/active",
                                     params={"user_id": uid})
                    data = r2.json().get("data", {})
                    if data.get("status") == "Active":
                        port = data.get("debug_port", "N/A")
                        ws = data.get("ws", {}).get("puppeteer", "")
                        print(f"  ACTIVE: {name} ({uid}) → debug port {port}")
                        found_via_api.append({"name": name, "uid": uid, "port": port})
                except Exception:
                    pass
    except Exception as e:
        print(f"  Ads Power API error: {e}")

    if not found_via_api:
        print("  No active profiles via API — falling back to port scan")

    # Method 2: Port scan 50000-58000 for Chrome instances with Facebook tabs
    print("\n--- Port scan (50000–58000) for Ads Manager tabs ---")
    async with httpx.AsyncClient(timeout=0.4) as c:
        for port in range(50000, 58000):
            try:
                r = await c.get(f"http://localhost:{port}/json/list")
                if r.status_code != 200:
                    continue
                tabs = r.json()
                ads_tabs = [
                    t for t in tabs
                    if "adsmanager.facebook.com" in t.get("url", "")
                    and "login" not in t.get("url", "")
                ]
                if ads_tabs:
                    for t in ads_tabs:
                        url = t.get("url", "")
                        print(f"  PORT {port}: {url[:100]}")
            except Exception:
                pass

    print("\nDone.")


asyncio.run(main())
