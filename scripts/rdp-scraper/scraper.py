"""
JARVIS Meta Ads Scraper — runs on RDP machines (Windows).

Strategy:
  1. Query Ads Power local API for active browser profiles
  2. For each profile: connect via Playwright CDP, open a new tab
  3. Navigate to Meta Ads Manager
  4. Intercept graph.facebook.com requests to capture the access token
  5. Use token to call Meta Marketing API for structured campaign data
  6. Fallback: scrape the visible Ads Manager table via DOM
  7. Close the tab, POST results to Hermes

Run every 5 minutes via Windows Task Scheduler.
Configure via config.json in this directory.
"""

import asyncio
import json
import re
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import httpx
from playwright.async_api import async_playwright

# ── Config ────────────────────────────────────────────────────────────────────

CONFIG_PATH = Path(__file__).parent / "config.json"

def load_config() -> dict:
    if not CONFIG_PATH.exists():
        print("[ERROR] config.json not found. Copy config.example.json to config.json and fill it in.")
        raise SystemExit(1)
    with open(CONFIG_PATH) as f:
        return json.load(f)

# ── Ads Power API ─────────────────────────────────────────────────────────────

async def get_active_profiles(adspower_url: str) -> list[dict]:
    """Return list of profiles that currently have a browser open."""
    active = []
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # List all profiles
            r = await client.get(f"{adspower_url}/api/v1/user/list", params={"page": 1, "page_size": 100})
            profiles = r.json().get("data", {}).get("list", [])

            for p in profiles:
                uid = p.get("user_id") or p.get("id")
                if not uid:
                    continue
                # Check if browser is open
                r2 = await client.get(f"{adspower_url}/api/v1/browser/active", params={"user_id": uid})
                data = r2.json().get("data", {})
                if data.get("status") == "Active":
                    active.append({
                        "user_id": uid,
                        "name": p.get("name", uid),
                        "debug_port": str(data.get("debug_port", "")),
                        "ws": data.get("ws", {}).get("puppeteer", ""),
                    })
    except Exception as e:
        print(f"[ERROR] Ads Power API: {e}")
    return active

# ── Token interception ────────────────────────────────────────────────────────

def extract_token_from_url(url: str) -> str | None:
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        if "access_token" in params:
            return params["access_token"][0]
    except Exception:
        pass
    return None

# ── Meta Marketing API ────────────────────────────────────────────────────────

async def fetch_via_meta_api(token: str) -> list[dict]:
    """
    Use intercepted token to query Meta Marketing API directly.
    Returns list of profile-level dicts with campaigns + summary.
    """
    results = []
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Get all ad accounts the user has access to
            r = await client.get(
                "https://graph.facebook.com/v19.0/me/adaccounts",
                params={
                    "access_token": token,
                    "fields": "id,name,account_status,currency",
                    "limit": 100,
                },
            )
            accounts = r.json().get("data", [])

            for account in accounts:
                aid = account["id"]  # already includes "act_" prefix
                account_name = account.get("name", aid)

                # Get today's insights per campaign
                insights_r = await client.get(
                    f"https://graph.facebook.com/v19.0/{aid}/insights",
                    params={
                        "access_token": token,
                        "date_preset": "today",
                        "level": "campaign",
                        "fields": "campaign_id,campaign_name,spend,impressions,clicks,ctr,cpm,cpc,reach,actions,action_values",
                        "limit": 100,
                    },
                )
                insights_data = insights_r.json().get("data", [])

                # Get active campaigns list (for status + budget)
                campaigns_r = await client.get(
                    f"https://graph.facebook.com/v19.0/{aid}/campaigns",
                    params={
                        "access_token": token,
                        "effective_status": '["ACTIVE","PAUSED","CAMPAIGN_PAUSED"]',
                        "fields": "id,name,status,daily_budget,lifetime_budget,objective",
                        "limit": 100,
                    },
                )
                campaigns_list = {c["id"]: c for c in campaigns_r.json().get("data", [])}

                # Merge insights + campaign info
                campaigns = []
                total_spend = 0.0
                total_impressions = 0
                total_clicks = 0
                active_count = 0

                for ins in insights_data:
                    cid = ins.get("campaign_id", "")
                    campaign_info = campaigns_list.get(cid, {})
                    spend = float(ins.get("spend", 0))
                    impressions = int(ins.get("impressions", 0))
                    clicks = int(ins.get("clicks", 0))
                    status = campaign_info.get("status", "UNKNOWN")

                    total_spend += spend
                    total_impressions += impressions
                    total_clicks += clicks
                    if status == "ACTIVE":
                        active_count += 1

                    campaigns.append({
                        "name": ins.get("campaign_name", campaign_info.get("name", cid)),
                        "status": status,
                        "budget": campaign_info.get("daily_budget") or campaign_info.get("lifetime_budget"),
                        "spend": f"${spend:.2f}",
                        "impressions": str(impressions),
                        "clicks": str(clicks),
                        "ctr": ins.get("ctr", ""),
                        "cpm": ins.get("cpm", ""),
                        "cpc": ins.get("cpc", ""),
                        "reach": ins.get("reach", ""),
                        "campaign_id": cid,
                    })

                avg_ctr = round(total_clicks / total_impressions * 100, 2) if total_impressions > 0 else 0

                results.append({
                    "account_id": aid,
                    "account_name": account_name,
                    "campaigns": campaigns,
                    "summary": {
                        "total_spend": round(total_spend, 2),
                        "total_impressions": total_impressions,
                        "total_clicks": total_clicks,
                        "active_campaigns": active_count,
                        "avg_ctr": avg_ctr,
                    },
                })
    except Exception as e:
        print(f"[ERROR] Meta API: {e}")
    return results

# ── DOM scraping fallback ─────────────────────────────────────────────────────

DOM_EXTRACT_JS = """
() => {
    // Find the campaign table — try multiple selectors
    const table = document.querySelector('table') ||
                  document.querySelector('[role="grid"]') ||
                  document.querySelector('[data-testid*="campaign"]');
    if (!table) return { found: false, headers: [], campaigns: [] };

    // Extract headers
    const headerEls = table.querySelectorAll('th, [role="columnheader"]');
    const headers = Array.from(headerEls).map(h => h.innerText.trim().toLowerCase().replace(/\\s+/g, '_'));

    // Extract data rows
    const rows = Array.from(
        table.querySelectorAll('tbody tr, [role="row"]:not(:first-child)')
    ).filter(r => r.querySelectorAll('td, [role="cell"]').length > 2);

    const campaigns = rows.map(row => {
        const cells = Array.from(row.querySelectorAll('td, [role="cell"]'));
        const obj = {};
        // Map by header if available
        headers.forEach((h, i) => {
            if (cells[i]) obj[h] = cells[i].innerText.trim();
        });
        // Always include raw fallback
        if (Object.keys(obj).length === 0) {
            const raw = cells.map(c => c.innerText.trim());
            return {
                name: raw[0] || '',
                status: raw[1] || '',
                budget: raw[2] || '',
                results: raw[3] || '',
                reach: raw[4] || '',
                impressions: raw[5] || '',
                spend: raw[raw.length - 1] || '',
                raw_cells: raw,
            };
        }
        return obj;
    }).filter(c => c.name || (c.raw_cells && c.raw_cells[0]));

    // Try to find account name
    const accountEl = document.querySelector('[data-testid="account-selector"] span, .x1i10hfl span');
    const accountName = accountEl ? accountEl.innerText.trim() : null;

    // Current account from URL
    const urlMatch = window.location.href.match(/act_?(\\d+)/);
    const accountId = urlMatch ? urlMatch[1] : null;

    return { found: true, headers, campaigns, accountName, accountId };
}
"""

def parse_dom_campaigns(raw: list[dict]) -> tuple[list[dict], dict]:
    """Normalize DOM-scraped campaigns and compute summary."""
    campaigns = []
    total_spend = 0.0
    total_impressions = 0
    total_clicks = 0
    active_count = 0

    for c in raw:
        name = c.get("campaign_name") or c.get("campaign") or c.get("name", "")
        status = c.get("delivery") or c.get("status", "")
        spend_str = c.get("amount_spent") or c.get("spend", "")
        impressions_str = c.get("impressions", "")
        clicks_str = c.get("link_clicks") or c.get("clicks", "")

        # Parse numeric values
        spend_val = float(re.sub(r"[^\d.]", "", spend_str)) if spend_str else 0.0
        impressions_val = int(re.sub(r"[^\d]", "", impressions_str)) if impressions_str else 0
        clicks_val = int(re.sub(r"[^\d]", "", clicks_str)) if clicks_str else 0

        total_spend += spend_val
        total_impressions += impressions_val
        total_clicks += clicks_val
        if "active" in status.lower() or "delivering" in status.lower():
            active_count += 1

        campaigns.append({
            "name": name,
            "status": status,
            "budget": c.get("budget", ""),
            "results": c.get("results", ""),
            "reach": c.get("reach", ""),
            "impressions": impressions_str,
            "clicks": clicks_str,
            "ctr": c.get("ctr", ""),
            "cpm": c.get("cpm", ""),
            "cpc": c.get("cpc", ""),
            "spend": spend_str,
        })

    avg_ctr = round(total_clicks / total_impressions * 100, 2) if total_impressions > 0 else 0

    summary = {
        "total_spend": round(total_spend, 2),
        "total_impressions": total_impressions,
        "total_clicks": total_clicks,
        "active_campaigns": active_count,
        "avg_ctr": avg_ctr,
    }
    return campaigns, summary

# ── Profile scraper ───────────────────────────────────────────────────────────

async def scrape_profile(playwright, profile: dict) -> dict:
    """
    Connect to one Ads Power profile via CDP and scrape Meta Ads Manager.
    Returns a ProfilePayload dict.
    """
    uid = profile["user_id"]
    name = profile["name"]
    debug_port = profile["debug_port"]

    print(f"[{name}] Connecting via CDP (port {debug_port})...")

    result = {
        "profile_id": uid,
        "profile_name": name,
        "ad_account_id": None,
        "ad_account_name": None,
        "campaigns": [],
        "summary": {},
        "error": None,
    }

    try:
        browser = await playwright.chromium.connect_over_cdp(
            f"http://localhost:{debug_port}",
            timeout=10_000,
        )

        # Use existing context (the logged-in session)
        contexts = browser.contexts
        context = contexts[0] if contexts else await browser.new_context()

        # Open a new tab — don't disturb existing tabs
        page = await context.new_page()

        try:
            captured_token: list[str] = []
            api_data_from_token: list[dict] = []

            # Intercept outgoing requests to capture access token
            async def on_request(req):
                if "graph.facebook.com" in req.url and not captured_token:
                    token = extract_token_from_url(req.url)
                    if token:
                        captured_token.append(token)
                    # Also check POST body
                    auth = req.headers.get("Authorization", "")
                    if auth.startswith("OAuth ") and not captured_token:
                        captured_token.append(auth.replace("OAuth ", "").strip())

            page.on("request", on_request)

            # Navigate to Ads Manager
            print(f"[{name}] Navigating to Ads Manager...")
            await page.goto(
                "https://adsmanager.facebook.com/adsmanager/manage/campaigns",
                wait_until="domcontentloaded",
                timeout=45_000,
            )

            # Wait for table or timeout
            try:
                await page.wait_for_selector(
                    'table, [role="grid"], [data-testid*="campaign"]',
                    timeout=20_000,
                )
            except Exception:
                print(f"[{name}] Table selector timeout — trying DOM anyway")

            # Extra settle time for JS to render
            await asyncio.sleep(3)

            # If we captured a token, use Meta API (much better data)
            if captured_token:
                print(f"[{name}] Token captured — using Meta Marketing API")
                api_data_from_token = await fetch_via_meta_api(captured_token[0])

            if api_data_from_token:
                # One token can have multiple ad accounts
                for acc_data in api_data_from_token:
                    result["ad_account_id"] = acc_data["account_id"]
                    result["ad_account_name"] = acc_data["account_name"]
                    result["campaigns"] = acc_data["campaigns"]
                    result["summary"] = acc_data["summary"]
                    print(f"[{name}] API: {acc_data['account_name']} — "
                          f"{len(acc_data['campaigns'])} campaigns, "
                          f"${acc_data['summary']['total_spend']:.2f} spend")
                # If multiple accounts, store them all in campaigns with account label
                if len(api_data_from_token) > 1:
                    all_campaigns = []
                    total_spend = 0.0
                    total_impr = 0
                    total_clicks = 0
                    active = 0
                    for acc in api_data_from_token:
                        for c in acc["campaigns"]:
                            c["ad_account"] = acc["account_name"]
                            all_campaigns.append(c)
                        total_spend += acc["summary"].get("total_spend", 0)
                        total_impr += acc["summary"].get("total_impressions", 0)
                        total_clicks += acc["summary"].get("total_clicks", 0)
                        active += acc["summary"].get("active_campaigns", 0)
                    result["campaigns"] = all_campaigns
                    result["summary"] = {
                        "total_spend": round(total_spend, 2),
                        "total_impressions": total_impr,
                        "total_clicks": total_clicks,
                        "active_campaigns": active,
                        "avg_ctr": round(total_clicks / total_impr * 100, 2) if total_impr > 0 else 0,
                    }
                    result["ad_account_name"] = f"{len(api_data_from_token)} accounts"

            else:
                # Fallback: DOM scrape
                print(f"[{name}] No token — falling back to DOM scraping")
                dom = await page.evaluate(DOM_EXTRACT_JS)

                if dom.get("found"):
                    result["ad_account_id"] = dom.get("accountId")
                    result["ad_account_name"] = dom.get("accountName")
                    campaigns, summary = parse_dom_campaigns(dom.get("campaigns", []))
                    result["campaigns"] = campaigns
                    result["summary"] = summary
                    print(f"[{name}] DOM: {len(campaigns)} campaigns found")
                else:
                    result["error"] = "Ads Manager table not found (not logged in or wrong page)"
                    print(f"[{name}] DOM scrape: table not found")

        finally:
            await page.close()

    except Exception as e:
        result["error"] = str(e)
        print(f"[{name}] ERROR: {e}")
        traceback.print_exc()

    return result

# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    config = load_config()
    hermes_url = config["hermes_url"].rstrip("/")
    scraper_token = config.get("scraper_token", "")
    rdp_host = config["rdp_host"]
    adspower_url = config.get("adspower_url", "http://localhost:50325")
    max_concurrent = config.get("max_concurrent_profiles", 3)

    print(f"=== JARVIS Meta Ads Scraper — {rdp_host} ===")
    print(f"Hermes: {hermes_url}")
    print(f"Ads Power: {adspower_url}")

    # 1. Get active profiles
    profiles = await get_active_profiles(adspower_url)
    if not profiles:
        print("[WARN] No active Ads Power profiles found. Make sure browsers are open.")
        return

    print(f"Found {len(profiles)} active profiles: {[p['name'] for p in profiles]}")

    # 2. Scrape all profiles (with concurrency limit)
    scraped_profiles = []
    sem = asyncio.Semaphore(max_concurrent)

    async with async_playwright() as pw:
        async def scrape_with_sem(profile):
            async with sem:
                return await scrape_profile(pw, profile)

        tasks = [scrape_with_sem(p) for p in profiles]
        scraped_profiles = await asyncio.gather(*tasks)

    # 3. POST to Hermes
    payload = {
        "rdp_host": rdp_host,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "profiles": scraped_profiles,
    }

    headers = {"Content-Type": "application/json"}
    if scraper_token:
        headers["X-Scraper-Token"] = scraper_token

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"{hermes_url}/api/v1/meta-ads/ingest",
                json=payload,
                headers=headers,
            )
            if r.status_code == 200:
                resp = r.json()
                print(f"✓ Ingested {resp.get('profiles_ingested')} profiles into Hermes")
            else:
                print(f"✗ Hermes ingest failed: HTTP {r.status_code} — {r.text[:200]}")
    except Exception as e:
        print(f"✗ Failed to POST to Hermes: {e}")

    print("=== Done ===")


if __name__ == "__main__":
    asyncio.run(main())
