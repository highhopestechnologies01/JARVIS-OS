"""Scan for active Ads Power profiles and their Chrome debug ports.
Uses concurrent scanning — much faster than sequential."""
import asyncio
import httpx
import json

ADSPOWER_URL = "http://localhost:50325"


async def check_port(client, port):
    """Return (port, ads_manager_url) if port has an adsmanager tab, else None."""
    try:
        r = await client.get(f"http://localhost:{port}/json/list")
        if r.status_code != 200:
            return None
        tabs = r.json()
        for t in tabs:
            url = t.get("url", "")
            if "adsmanager.facebook.com" in url and "login" not in url:
                return (port, url)
    except Exception:
        pass
    return None


async def main():
    print("=== Ads Power Active Profile Scanner ===\n")

    # ── Method 1: Ads Power API (list all profiles + check active status) ──
    print("--- Querying Ads Power API ---")
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{ADSPOWER_URL}/api/v1/user/list",
                            params={"page": 1, "page_size": 100})
            rj = r.json()
            profiles = rj.get("data", {}).get("list", [])
            print(f"Total profiles: {len(profiles)}")

            for p in profiles:
                uid = p.get("user_id") or p.get("id")
                name = p.get("name", uid)
                try:
                    r2 = await c.get(f"{ADSPOWER_URL}/api/v1/browser/active",
                                     params={"user_id": uid})
                    data = r2.json()
                    # Print raw for first profile to see field names
                    inner = data.get("data", {})
                    status = inner.get("status", "?")
                    port = inner.get("debug_port", "")
                    if port or status not in ("", "Inactive", "inactive", "?"):
                        print(f"  ACTIVE: {name} ({uid}) → port={port} status={status}")
                except Exception as ex:
                    print(f"  Error checking {uid}: {ex}")
    except Exception as e:
        print(f"  API error: {e}")

    # ── Method 2: Fast parallel port scan 50000–58000 ─────────────────────
    print("\n--- Parallel port scan (50000–58000) ---")
    print("(this takes ~15 seconds concurrently)")

    BATCH = 500  # scan 500 ports at a time
    found = []

    async with httpx.AsyncClient(timeout=0.5) as client:
        for start in range(50000, 58000, BATCH):
            end = min(start + BATCH, 58000)
            tasks = [check_port(client, p) for p in range(start, end)]
            results = await asyncio.gather(*tasks)
            for res in results:
                if res:
                    port, url = res
                    print(f"  PORT {port}: {url[:100]}")
                    found.append({"port": port, "url": url})

    print(f"\n=== Found {len(found)} adsmanager tabs ===")
    for f in found:
        import re
        acct = re.findall(r'act[_=](\d+)', f["url"])
        print(f"  Port {f['port']} → account {acct}")
    print("\nDone. Update config.json with the correct port(s).")


asyncio.run(main())
