"""
JARVIS Meta Ads Scraper — runs on RDP machines (Windows).

Strategy:
  1. Query Ads Power local API for active browser profiles
  2. For each profile: get CDP debug port, find/open Ads Manager tab
  3. Use raw CDP websockets (no Playwright — version-agnostic)
  4. Navigate to Ads Manager, extract campaign data via JS evaluation
  5. Fallback: intercept graph.facebook.com for access token → Marketing API
  6. POST results to Hermes

Run every 5 minutes via Windows Task Scheduler.
Configure via config.json in this directory.
"""

import asyncio
import json
import re
import traceback
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import httpx
import websockets

# ── Config ────────────────────────────────────────────────────────────────────

CONFIG_PATH = Path(__file__).parent / "config.json"

def load_config() -> dict:
    if not CONFIG_PATH.exists():
        print("[ERROR] config.json not found.")
        raise SystemExit(1)
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)

# ── Ads Power API ─────────────────────────────────────────────────────────────

async def get_active_profiles(adspower_url: str) -> list[dict]:
    """Return profiles that currently have a browser open."""
    active = []
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{adspower_url}/api/v1/user/list",
                                 params={"page": 1, "page_size": 100})
            profiles = r.json().get("data", {}).get("list", [])

            for p in profiles:
                uid = p.get("user_id") or p.get("id")
                if not uid:
                    continue
                r2 = await client.get(f"{adspower_url}/api/v1/browser/active",
                                      params={"user_id": uid})
                data = r2.json().get("data", {})
                if data.get("status") == "Active":
                    active.append({
                        "user_id": uid,
                        "name": p.get("name", uid),
                        "debug_port": str(data.get("debug_port", "")),
                    })
    except Exception as e:
        print(f"[ERROR] Ads Power API: {e}")
    return active

# ── Raw CDP helpers ───────────────────────────────────────────────────────────

async def cdp_get_tabs(debug_port: str) -> list[dict]:
    """Get all open tabs via Chrome's REST debug API."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        r = await client.get(f"http://localhost:{debug_port}/json/list")
        return r.json()

async def cdp_new_tab(debug_port: str, url: str) -> dict:
    async with httpx.AsyncClient(timeout=5.0) as client:
        r = await client.get(f"http://localhost:{debug_port}/json/new?{url}")
        return r.json()

async def cdp_close_tab(debug_port: str, tab_id: str) -> None:
    async with httpx.AsyncClient(timeout=5.0) as client:
        await client.get(f"http://localhost:{debug_port}/json/close/{tab_id}")

_cmd_id = 0

def _next_id() -> int:
    global _cmd_id
    _cmd_id += 1
    return _cmd_id

async def cdp_send(ws, method: str, params: dict = None) -> dict:
    """Send one CDP command and wait for its response."""
    cmd_id = _next_id()
    msg = {"id": cmd_id, "method": method, "params": params or {}}
    await ws.send(json.dumps(msg))
    # Read messages until we get the matching response
    deadline = asyncio.get_event_loop().time() + 30.0
    while asyncio.get_event_loop().time() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            data = json.loads(raw)
            if data.get("id") == cmd_id:
                return data.get("result", {})
        except asyncio.TimeoutError:
            continue
        except Exception:
            break
    return {}

async def cdp_evaluate(ws, expression: str) -> str | None:
    """Evaluate JS expression in the page, return string result."""
    result = await cdp_send(ws, "Runtime.evaluate", {
        "expression": expression,
        "returnByValue": True,
        "awaitPromise": True,
        "timeout": 15000,
    })
    val = result.get("result", {})
    if val.get("type") == "string":
        return val["value"]
    if val.get("type") in ("object", "undefined") and "value" in val:
        return json.dumps(val["value"])
    return None

async def cdp_navigate_and_wait(ws, url: str, wait_s: float = 8.0) -> None:
    """Navigate to URL, wait for load."""
    await cdp_send(ws, "Page.enable")
    await cdp_send(ws, "Page.navigate", {"url": url})
    await asyncio.sleep(wait_s)  # wait for page to render

# ── DOM extraction JS ─────────────────────────────────────────────────────────

DOM_EXTRACT_JS = r"""
(function() {
    try {
        var table = document.querySelector('table') ||
                    document.querySelector('[role="grid"]') ||
                    document.querySelector('[data-testid*="campaign"]');
        if (!table) return JSON.stringify({found: false, campaigns: [], headers: []});

        var headerEls = table.querySelectorAll('th, [role="columnheader"]');
        var headers = Array.from(headerEls).map(function(h) {
            return h.innerText.trim().toLowerCase().replace(/\s+/g, '_');
        });

        var rows = Array.from(
            table.querySelectorAll('tbody tr, [role="row"]:not(:first-child)')
        ).filter(function(r) {
            return r.querySelectorAll('td, [role="cell"]').length > 2;
        });

        var campaigns = rows.map(function(row) {
            var cells = Array.from(row.querySelectorAll('td, [role="cell"]'));
            var obj = {};
            headers.forEach(function(h, i) {
                if (cells[i]) obj[h] = cells[i].innerText.trim();
            });
            if (Object.keys(obj).length === 0) {
                var raw = cells.map(function(c) { return c.innerText.trim(); });
                obj = {name: raw[0]||'', status: raw[1]||'', budget: raw[2]||'',
                       impressions: raw[5]||'', spend: raw[raw.length-1]||''};
            }
            return obj;
        }).filter(function(c) { return c.name; });

        var urlMatch = window.location.href.match(/act_?(\d+)/);
        var accountEl = document.querySelector('[aria-label*="account"], [data-testid*="account"]');

        return JSON.stringify({
            found: true,
            campaigns: campaigns,
            headers: headers,
            accountId: urlMatch ? urlMatch[1] : null,
            accountName: accountEl ? accountEl.innerText.trim() : document.title,
            url: window.location.href
        });
    } catch(e) {
        return JSON.stringify({found: false, error: e.message, campaigns: []});
    }
})()
"""

TOKEN_EXTRACT_JS = r"""
(function() {
    // Try to find access token in page JS globals
    try {
        if (window.__accessToken) return window.__accessToken;
        if (window.require) {
            try { var s = window.require('SessionToken'); if(s&&s.getToken) return s.getToken(); } catch(e) {}
        }
        // Check localStorage/sessionStorage for token hints
        for (var i = 0; i < localStorage.length; i++) {
            var k = localStorage.key(i);
            if (k && k.toLowerCase().includes('token')) {
                var v = localStorage.getItem(k);
                if (v && v.length > 20 && !v.startsWith('{')) return v;
            }
        }
    } catch(e) {}
    return null;
})()
"""

# ── Meta Marketing API ────────────────────────────────────────────────────────

async def fetch_via_meta_api(token: str) -> list[dict]:
    """Use intercepted token to query Meta Marketing API."""
    results = []
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(
                "https://graph.facebook.com/v19.0/me/adaccounts",
                params={"access_token": token, "fields": "id,name,account_status", "limit": 100},
            )
            accounts = r.json().get("data", [])
            for account in accounts:
                aid = account["id"]
                account_name = account.get("name", aid)

                insights_r = await client.get(
                    f"https://graph.facebook.com/v19.0/{aid}/insights",
                    params={
                        "access_token": token, "date_preset": "today", "level": "campaign",
                        "fields": "campaign_id,campaign_name,spend,impressions,clicks,ctr,cpm,cpc,reach",
                        "limit": 100,
                    },
                )
                insights_data = insights_r.json().get("data", [])

                campaigns = []
                total_spend = total_impr = total_clicks = active_count = 0
                for ins in insights_data:
                    spend = float(ins.get("spend", 0))
                    impressions = int(ins.get("impressions", 0))
                    clicks = int(ins.get("clicks", 0))
                    total_spend += spend; total_impr += impressions; total_clicks += clicks
                    campaigns.append({
                        "name": ins.get("campaign_name", ""),
                        "status": "ACTIVE", "spend": f"${spend:.2f}",
                        "impressions": str(impressions), "clicks": str(clicks),
                        "ctr": ins.get("ctr", ""), "cpm": ins.get("cpm", ""),
                        "cpc": ins.get("cpc", ""), "reach": ins.get("reach", ""),
                    })

                avg_ctr = round(total_clicks / total_impr * 100, 2) if total_impr > 0 else 0
                results.append({
                    "account_id": aid, "account_name": account_name,
                    "campaigns": campaigns,
                    "summary": {"total_spend": round(total_spend, 2), "total_impressions": total_impr,
                                "total_clicks": total_clicks, "active_campaigns": len(campaigns), "avg_ctr": avg_ctr},
                })
    except Exception as e:
        print(f"[ERROR] Meta API: {e}")
    return results

# ── DOM campaign parser ───────────────────────────────────────────────────────

def parse_dom_campaigns(raw: list[dict]) -> tuple[list[dict], dict]:
    campaigns = []
    total_spend = total_impr = total_clicks = active_count = 0
    for c in raw:
        name = c.get("campaign_name") or c.get("campaign") or c.get("name", "")
        status = c.get("delivery") or c.get("status", "")
        spend_str = c.get("amount_spent") or c.get("spend", "")
        impressions_str = c.get("impressions", "")
        clicks_str = c.get("link_clicks") or c.get("clicks", "")

        def parse_num(s):
            s = re.sub(r"[^\d.]", "", str(s)) if s else ""
            try: return float(s) if "." in s else int(s)
            except: return 0

        spend_val = float(parse_num(spend_str))
        impr_val = int(parse_num(impressions_str))
        clicks_val = int(parse_num(clicks_str))
        total_spend += spend_val; total_impr += impr_val; total_clicks += clicks_val
        if "active" in status.lower() or "delivering" in status.lower():
            active_count += 1
        campaigns.append({"name": name, "status": status, "budget": c.get("budget", ""),
                          "spend": spend_str, "impressions": impressions_str, "clicks": clicks_str,
                          "ctr": c.get("ctr", ""), "cpm": c.get("cpm", ""), "cpc": c.get("cpc", "")})

    avg_ctr = round(total_clicks / total_impr * 100, 2) if total_impr > 0 else 0
    return campaigns, {"total_spend": round(total_spend, 2), "total_impressions": total_impr,
                       "total_clicks": total_clicks, "active_campaigns": active_count, "avg_ctr": avg_ctr}

# ── Profile scraper ───────────────────────────────────────────────────────────

async def scrape_profile(profile: dict) -> dict:
    uid = profile["user_id"]
    name = profile["name"]
    debug_port = profile["debug_port"]

    print(f"[{name}] Scraping (debug port {debug_port})...")

    result = {
        "profile_id": uid, "profile_name": name,
        "ad_account_id": None, "ad_account_name": None,
        "campaigns": [], "summary": {}, "error": None,
    }

    try:
        # ── Step 1: get open tabs ──────────────────────────────────────────
        tabs = await cdp_get_tabs(debug_port)
        print(f"[{name}] {len(tabs)} tabs open")

        # Find existing Ads Manager tab or create one
        ads_tab = None
        for t in tabs:
            if "adsmanager.facebook.com" in t.get("url", ""):
                ads_tab = t
                break

        opened_new = False
        if not ads_tab:
            print(f"[{name}] No Ads Manager tab found — opening new tab")
            ads_tab = await cdp_new_tab(debug_port, "about:blank")
            opened_new = True

        ws_url = ads_tab.get("webSocketDebuggerUrl")
        if not ws_url:
            result["error"] = "No webSocketDebuggerUrl in tab"
            return result

        print(f"[{name}] Connecting to tab via CDP WS...")

        # ── Step 2: connect raw CDP ────────────────────────────────────────
        async with websockets.connect(
            ws_url,
            ping_interval=None,
            open_timeout=15,
            close_timeout=5,
        ) as ws:
            # Enable domains
            await cdp_send(ws, "Runtime.enable")
            await cdp_send(ws, "Page.enable")

            # Navigate if needed
            current_url = ads_tab.get("url", "")
            if "adsmanager.facebook.com" not in current_url:
                print(f"[{name}] Navigating to Ads Manager...")
                await cdp_navigate_and_wait(ws, "https://adsmanager.facebook.com/adsmanager/manage/campaigns", wait_s=10)
            else:
                print(f"[{name}] Ads Manager already open — extracting data")
                await asyncio.sleep(2)  # brief settle

            # ── Step 3: try token extraction ──────────────────────────────
            token_raw = await cdp_evaluate(ws, TOKEN_EXTRACT_JS)
            if token_raw and len(token_raw) > 30:
                print(f"[{name}] Token found — calling Meta API")
                api_data = await fetch_via_meta_api(token_raw)
                if api_data:
                    all_campaigns = []
                    total_spend = total_impr = total_clicks = active = 0
                    for acc in api_data:
                        for c in acc["campaigns"]:
                            c["ad_account"] = acc["account_name"]
                            all_campaigns.append(c)
                        total_spend += acc["summary"].get("total_spend", 0)
                        total_impr += acc["summary"].get("total_impressions", 0)
                        total_clicks += acc["summary"].get("total_clicks", 0)
                        active += acc["summary"].get("active_campaigns", 0)

                    result["campaigns"] = all_campaigns
                    result["summary"] = {
                        "total_spend": round(total_spend, 2), "total_impressions": total_impr,
                        "total_clicks": total_clicks, "active_campaigns": active,
                        "avg_ctr": round(total_clicks / total_impr * 100, 2) if total_impr > 0 else 0,
                    }
                    result["ad_account_name"] = api_data[0]["account_name"] if len(api_data) == 1 else f"{len(api_data)} accounts"
                    result["ad_account_id"] = api_data[0]["account_id"] if len(api_data) == 1 else None
                    print(f"[{name}] API: {len(all_campaigns)} campaigns, ${total_spend:.2f} spend")
                    if opened_new:
                        await cdp_close_tab(debug_port, ads_tab.get("id", ""))
                    return result

            # ── Step 4: DOM scrape fallback ───────────────────────────────
            print(f"[{name}] DOM scraping...")
            dom_raw = await cdp_evaluate(ws, DOM_EXTRACT_JS)

            if opened_new:
                await cdp_close_tab(debug_port, ads_tab.get("id", ""))

            if dom_raw:
                try:
                    dom = json.loads(dom_raw)
                except Exception:
                    dom = {"found": False, "campaigns": []}

                if dom.get("found"):
                    result["ad_account_id"] = dom.get("accountId")
                    result["ad_account_name"] = dom.get("accountName")
                    campaigns, summary = parse_dom_campaigns(dom.get("campaigns", []))
                    result["campaigns"] = campaigns
                    result["summary"] = summary
                    print(f"[{name}] DOM: {len(campaigns)} campaigns")
                else:
                    err = dom.get("error", "table not found")
                    result["error"] = f"DOM: {err}"
                    print(f"[{name}] DOM failed: {err}")
            else:
                result["error"] = "Empty DOM result"

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

    profiles = await get_active_profiles(adspower_url)
    if not profiles:
        print("[WARN] No active Ads Power profiles found.")
        return

    print(f"Found {len(profiles)} active profiles: {[p['name'] for p in profiles]}")

    sem = asyncio.Semaphore(max_concurrent)
    async def scrape_with_sem(p):
        async with sem:
            return await scrape_profile(p)

    scraped = await asyncio.gather(*[scrape_with_sem(p) for p in profiles])

    payload = {
        "rdp_host": rdp_host,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "profiles": list(scraped),
    }

    headers = {"Content-Type": "application/json"}
    if scraper_token:
        headers["X-Scraper-Token"] = scraper_token

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(f"{hermes_url}/api/v1/meta-ads/ingest", json=payload, headers=headers)
            if r.status_code == 200:
                print(f"✓ Ingested {r.json().get('profiles_ingested')} profiles into Hermes")
            else:
                print(f"✗ Hermes ingest failed: HTTP {r.status_code} — {r.text[:200]}")
    except Exception as e:
        print(f"✗ Failed to POST to Hermes: {e}")

    print("=== Done ===")

if __name__ == "__main__":
    asyncio.run(main())
