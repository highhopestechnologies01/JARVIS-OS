"""
JARVIS Meta Ads Scraper — runs on RDP machines (Windows).

Strategy:
  1. Query Ads Power local API for active browser profiles
  2. For each profile: get CDP debug port, find Ads Manager tab
  3. Use raw CDP websockets — enable Network domain, reload page
  4. BYPASS SERVICE WORKER so graph.facebook.com requests are visible
  5. Intercept graph.facebook.com requests to capture access_token
  6. JS injection backup: override fetch/XHR in page context
  7. Call Meta Marketing API with captured token for clean data
  8. Fallback: DOM scrape with broad selectors
  9. POST results to Hermes

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

async def scan_chrome_ports(port_start: int = 52000, port_end: int = 54500) -> list[dict]:
    """
    Scan port range for active Chrome CDP endpoints.
    Ads Power typically uses 52000-54500. Timeout 0.3s — local ports respond instantly.
    """
    found = []
    async with httpx.AsyncClient(timeout=0.3) as client:
        async def check_port(port: int):
            try:
                r = await client.get(f"http://localhost:{port}/json/list")
                if r.status_code == 200:
                    tabs = r.json()
                    if isinstance(tabs, list):
                        fb_tabs = [t for t in tabs if "facebook.com" in t.get("url", "")]
                        return {"user_id": f"port_{port}", "name": f"port_{port}",
                                "debug_port": str(port), "tabs": tabs, "fb_tabs": len(fb_tabs)}
            except Exception:
                pass
            return None

        tasks = [check_port(p) for p in range(port_start, port_end)]
        results = await asyncio.gather(*tasks)
        for r in results:
            if r:
                found.append(r)

    found.sort(key=lambda x: x.get("fb_tabs", 0), reverse=True)
    print(f"  Port scan found {len(found)} Chrome instances: {[x['debug_port'] for x in found]}")
    return found

async def get_active_profiles(adspower_url: str, fixed_ports: list[int] = None) -> list[dict]:
    """
    Get active profiles.
    1. Check fixed_ports from config (explicit, fast, reliable)
    2. Ads Power API
    3. Port scan fallback
    """
    active = []
    known_ports: set[str] = set()

    # ── Fixed ports (highest priority — user-specified from netstat) ──────
    if fixed_ports:
        print(f"Checking fixed ports: {fixed_ports}")
        async with httpx.AsyncClient(timeout=2.0) as client:
            for port in fixed_ports:
                try:
                    r = await client.get(f"http://localhost:{port}/json/list")
                    if r.status_code == 200:
                        tabs = r.json()
                        fb_tabs = [t for t in tabs if "facebook.com" in t.get("url", "")]
                        port_str = str(port)
                        active.append({
                            "user_id": f"port_{port}",
                            "name": f"port_{port}",
                            "debug_port": port_str,
                        })
                        known_ports.add(port_str)
                        print(f"  port {port}: {len(tabs)} tabs, {len(fb_tabs)} Facebook tabs")
                except Exception as e:
                    print(f"  port {port}: unreachable ({e})")

    # ── Ads Power API ─────────────────────────────────────────────────────
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
                    port_str = str(data.get("debug_port", ""))
                    if port_str and port_str not in known_ports:
                        active.append({
                            "user_id": uid,
                            "name": p.get("name", uid),
                            "debug_port": port_str,
                        })
                        known_ports.add(port_str)
    except Exception as e:
        print(f"[WARN] Ads Power API error: {e}")

    # ── Port scan fallback (if nothing found yet) ─────────────────────────
    if not active:
        print("Scanning ports for active Chrome instances...")
        port_results = await scan_chrome_ports(50000, 58000)
        for pr in port_results:
            if pr["debug_port"] not in known_ports:
                active.append({
                    "user_id": pr["user_id"],
                    "name": pr["name"],
                    "debug_port": pr["debug_port"],
                })

    return active

# ── Raw CDP helpers ───────────────────────────────────────────────────────────

async def cdp_get_tabs(debug_port: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=5.0) as client:
        r = await client.get(f"http://localhost:{debug_port}/json/list")
        return r.json()

_cmd_id = 0

def _next_id() -> int:
    global _cmd_id
    _cmd_id += 1
    return _cmd_id

async def cdp_send(ws, method: str, params: dict = None) -> dict:
    """Send one CDP command and wait for its response (ignores events)."""
    cmd_id = _next_id()
    msg = {"id": cmd_id, "method": method, "params": params or {}}
    await ws.send(json.dumps(msg))
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

# ── JS token capture script (injected before page loads) ─────────────────────

JS_TOKEN_CAPTURE = """
window.__jarvis_captured_token = null;
(function() {
    function captureToken(url, headers) {
        try {
            if (!url || typeof url !== 'string') return;
            if (!url.includes('graph.facebook.com')) return;
            // From URL param
            try {
                var u = new URL(url);
                var t = u.searchParams.get('access_token');
                if (t && t.length > 30) { window.__jarvis_captured_token = t; return; }
            } catch(e) {}
            // From Authorization header
            if (headers) {
                var h = headers;
                if (typeof h.get === 'function') {
                    var auth = h.get('Authorization') || h.get('authorization');
                    if (auth && auth.startsWith('Bearer ')) {
                        var t = auth.substring(7);
                        if (t.length > 30) { window.__jarvis_captured_token = t; return; }
                    }
                } else if (typeof h === 'object') {
                    var auth = h['Authorization'] || h['authorization'];
                    if (auth && auth.startsWith('Bearer ')) {
                        var t = auth.substring(7);
                        if (t.length > 30) { window.__jarvis_captured_token = t; return; }
                    }
                }
            }
        } catch(e) {}
    }
    // Override fetch
    var origFetch = window.fetch;
    window.fetch = function(input, init) {
        try {
            var url = typeof input === 'string' ? input : (input && input.url);
            captureToken(url, init && init.headers);
        } catch(e) {}
        return origFetch.apply(this, arguments);
    };
    // Override XHR open
    var origOpen = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function(method, url) {
        try { captureToken(url, null); } catch(e) {}
        this.__jarvis_url = url;
        return origOpen.apply(this, arguments);
    };
    // Override XHR setRequestHeader
    var origSetHeader = XMLHttpRequest.prototype.setRequestHeader;
    XMLHttpRequest.prototype.setRequestHeader = function(name, value) {
        try {
            if (name && name.toLowerCase() === 'authorization' && value && value.startsWith('Bearer ')) {
                var t = value.substring(7);
                if (t.length > 30 && this.__jarvis_url && this.__jarvis_url.includes('graph.facebook.com')) {
                    window.__jarvis_captured_token = t;
                }
            }
        } catch(e) {}
        return origSetHeader.apply(this, arguments);
    };
})();
"""

# ── CDP Network interception for access token ─────────────────────────────────

async def intercept_access_token(ws, reload: bool = True, timeout: float = 35.0) -> str | None:
    """
    Enable CDP Network domain with service worker bypass, optionally reload,
    and listen for graph.facebook.com requests to extract access_token.
    Also injects JS as a backup capture method.
    """
    await cdp_send(ws, "Network.enable")
    await cdp_send(ws, "Page.enable")

    # KEY FIX: bypass service worker so all requests hit the network
    # (service workers intercept graph.facebook.com requests silently)
    await cdp_send(ws, "Network.setBypassServiceWorker", {"bypass": True})
    print("    Service worker bypass: ON")

    # JS injection backup — captures tokens in page context
    await cdp_send(ws, "Page.addScriptToEvaluateOnNewDocument", {"source": JS_TOKEN_CAPTURE})

    token = None

    if reload:
        reload_id = _next_id()
        await ws.send(json.dumps({"id": reload_id, "method": "Page.reload", "params": {}}))
        print("    Reloading page to intercept API calls...")

    page_loaded = False
    deadline = asyncio.get_event_loop().time() + timeout

    while asyncio.get_event_loop().time() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
            data = json.loads(raw)
        except asyncio.TimeoutError:
            # Poll JS-injected token every second
            if page_loaded:
                js_token = await cdp_evaluate(ws, "window.__jarvis_captured_token || ''")
                if js_token and len(js_token) > 30:
                    token = js_token
                    print(f"    Token captured via JS injection ({len(token)} chars)")
                    break
            continue
        except Exception:
            break

        method = data.get("method", "")
        params = data.get("params", {})

        # ── requestWillBeSent: check URL for access_token param ──────────
        if method == "Network.requestWillBeSent":
            url = params.get("request", {}).get("url", "")
            if "graph.facebook.com" in url:
                if "access_token=" in url:
                    parsed = urlparse(url)
                    qs = parse_qs(parsed.query)
                    if "access_token" in qs:
                        token = qs["access_token"][0]
                        print(f"    Token captured from URL param ({len(token)} chars)")
                        break

                headers = params.get("request", {}).get("headers", {})
                for k, v in headers.items():
                    if k.lower() == "authorization" and v.startswith("Bearer "):
                        candidate = v[7:]
                        if len(candidate) > 30:
                            token = candidate
                            print(f"    Token captured from Authorization header ({len(token)} chars)")
                            break
                if token:
                    break

        # ── Page loaded: wait a bit then check JS token ──────────────────
        if method == "Page.loadEventFired":
            page_loaded = True
            print("    Page loaded — waiting for async API calls...")
            await asyncio.sleep(3)
            js_token = await cdp_evaluate(ws, "window.__jarvis_captured_token || ''")
            if js_token and len(js_token) > 30:
                token = js_token
                print(f"    Token captured via JS after page load ({len(token)} chars)")
                break

    # Final JS check before giving up
    if not token:
        js_token = await cdp_evaluate(ws, "window.__jarvis_captured_token || ''")
        if js_token and len(js_token) > 30:
            token = js_token
            print(f"    Token captured via JS final check ({len(token)} chars)")

    return token

# ── DOM extraction JS (broad selectors for Meta Ads Manager) ──────────────────

DOM_EXTRACT_JS = r"""
(function() {
    try {
        var rows = Array.from(document.querySelectorAll('[role="row"]'));
        var dataRows = rows.filter(function(r) {
            return r.querySelectorAll('[role="cell"], [role="gridcell"]').length >= 3;
        });

        if (dataRows.length === 0) {
            return JSON.stringify({
                found: false,
                url: window.location.href,
                title: document.title,
                bodySnippet: document.body ? document.body.innerText.slice(0, 500) : ''
            });
        }

        var campaigns = dataRows.map(function(row) {
            var cells = Array.from(row.querySelectorAll('[role="cell"], [role="gridcell"], td'));
            var texts = cells.map(function(c) { return c.innerText.trim(); });
            return {
                name: texts[0] || '',
                status: texts[1] || '',
                budget: texts[2] || '',
                impressions: texts[4] || '',
                clicks: texts[5] || '',
                ctr: texts[6] || '',
                cpc: texts[7] || '',
                spend: texts[texts.length - 1] || '',
            };
        }).filter(function(c) { return c.name && c.name.length > 1; });

        var urlMatch = window.location.href.match(/act[_=](\d+)/);
        return JSON.stringify({
            found: campaigns.length > 0,
            campaigns: campaigns,
            accountId: urlMatch ? urlMatch[1] : null,
            accountName: document.title,
            url: window.location.href,
        });
    } catch(e) {
        return JSON.stringify({found: false, error: e.message, url: window.location.href});
    }
})()
"""

# ── Meta Marketing API ────────────────────────────────────────────────────────

async def fetch_via_meta_api(token: str) -> list[dict]:
    results = []
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(
                "https://graph.facebook.com/v19.0/me/adaccounts",
                params={"access_token": token, "fields": "id,name,account_status", "limit": 100},
            )
            if r.status_code != 200:
                print(f"    Meta API accounts error: {r.status_code} {r.text[:200]}")
                return []
            accounts = r.json().get("data", [])
            if not accounts:
                print("    Meta API: no ad accounts returned")
                return []

            print(f"    Meta API: {len(accounts)} ad accounts")
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
                total_spend = total_impr = total_clicks = 0
                for ins in insights_data:
                    spend = float(ins.get("spend", 0))
                    impressions = int(ins.get("impressions", 0))
                    clicks = int(ins.get("clicks", 0))
                    total_spend += spend
                    total_impr += impressions
                    total_clicks += clicks
                    campaigns.append({
                        "name": ins.get("campaign_name", ""),
                        "status": "ACTIVE",
                        "spend": f"${spend:.2f}",
                        "impressions": str(impressions),
                        "clicks": str(clicks),
                        "ctr": ins.get("ctr", ""),
                        "cpm": ins.get("cpm", ""),
                        "cpc": ins.get("cpc", ""),
                        "reach": ins.get("reach", ""),
                    })

                avg_ctr = round(total_clicks / total_impr * 100, 2) if total_impr > 0 else 0
                results.append({
                    "account_id": aid,
                    "account_name": account_name,
                    "campaigns": campaigns,
                    "summary": {
                        "total_spend": round(total_spend, 2),
                        "total_impressions": total_impr,
                        "total_clicks": total_clicks,
                        "active_campaigns": len(campaigns),
                        "avg_ctr": avg_ctr,
                    },
                })
    except Exception as e:
        print(f"    [ERROR] Meta API: {e}")
    return results

# ── DOM campaign parser ───────────────────────────────────────────────────────

def parse_dom_campaigns(raw: list[dict]) -> tuple[list[dict], dict]:
    campaigns = []
    total_spend = total_impr = total_clicks = active_count = 0
    for c in raw:
        name = c.get("name", "")
        status = c.get("status", "")
        spend_str = c.get("spend", "")
        impressions_str = c.get("impressions", "")
        clicks_str = c.get("clicks", "")

        def parse_num(s):
            s = re.sub(r"[^\d.]", "", str(s)) if s else ""
            try:
                return float(s) if "." in s else int(s)
            except Exception:
                return 0

        spend_val = float(parse_num(spend_str))
        impr_val = int(parse_num(impressions_str))
        clicks_val = int(parse_num(clicks_str))
        total_spend += spend_val
        total_impr += impr_val
        total_clicks += clicks_val
        if "active" in status.lower() or "delivering" in status.lower():
            active_count += 1
        campaigns.append({
            "name": name, "status": status,
            "budget": c.get("budget", ""),
            "spend": spend_str, "impressions": impressions_str,
            "clicks": clicks_str, "ctr": c.get("ctr", ""),
            "cpm": c.get("cpm", ""), "cpc": c.get("cpc", ""),
        })

    avg_ctr = round(total_clicks / total_impr * 100, 2) if total_impr > 0 else 0
    return campaigns, {
        "total_spend": round(total_spend, 2),
        "total_impressions": total_impr,
        "total_clicks": total_clicks,
        "active_campaigns": active_count,
        "avg_ctr": avg_ctr,
    }

# ── Profile scraper ───────────────────────────────────────────────────────────

BAD_URL_PATTERNS = [
    "loginpage", "/login", "chrome-error", "about:blank",
    "newtab", "chromewebdata", "business.facebook.com/business",
]

async def scrape_profile(profile: dict) -> dict:
    uid = profile["user_id"]
    name = profile["name"]
    debug_port = profile["debug_port"]

    print(f"\n[{name}] Scraping (port {debug_port})...")

    result = {
        "profile_id": uid, "profile_name": name,
        "ad_account_id": None, "ad_account_name": None,
        "campaigns": [], "summary": {}, "error": None,
    }

    try:
        tabs = await cdp_get_tabs(debug_port)
        print(f"  {len(tabs)} tabs open")

        # ── Find Ads Manager tab ──────────────────────────────────────────
        # Only use tabs already on adsmanager.facebook.com (authenticated session)
        # Do NOT navigate login pages — they lead to chrome-error on blocked domains
        ads_tab = None
        for t in tabs:
            url = t.get("url", "")
            if "adsmanager.facebook.com" in url:
                is_bad = any(p in url for p in BAD_URL_PATTERNS)
                if not is_bad:
                    ads_tab = t
                    print(f"  Found Ads Manager tab: {url[:80]}")
                    break

        if not ads_tab:
            # Check if any Facebook tab is not a login/error page
            for t in tabs:
                url = t.get("url", "")
                if "facebook.com" in url:
                    is_bad = any(p in url for p in BAD_URL_PATTERNS)
                    if not is_bad:
                        ads_tab = t
                        print(f"  Using Facebook tab (not login): {url[:80]}")
                        break

        if not ads_tab:
            # All Facebook tabs are login/blocked — skip this profile
            fb_tabs = [t.get("url", "")[:60] for t in tabs if "facebook.com" in t.get("url", "")]
            result["error"] = f"No usable Ads Manager tab (all tabs are login/blocked). FB tabs: {fb_tabs}"
            print(f"  Skipping — only login/blocked tabs found")
            return result

        ws_url = ads_tab.get("webSocketDebuggerUrl")
        if not ws_url:
            result["error"] = "No webSocketDebuggerUrl"
            return result

        print(f"  Connecting via CDP WS...")

        async with websockets.connect(
            ws_url,
            ping_interval=None,
            open_timeout=15,
            close_timeout=5,
        ) as ws:
            await cdp_send(ws, "Runtime.enable")

            current_url = ads_tab.get("url", "")
            ads_manager_url = "https://adsmanager.facebook.com/adsmanager/manage/campaigns"

            # ── Strategy 1: Network interception (with SW bypass + JS backup) ──
            if "adsmanager.facebook.com" in current_url:
                print("  Intercepting network: reloading Ads Manager...")
                token = await intercept_access_token(ws, reload=True, timeout=35.0)
            else:
                print(f"  Navigating to Ads Manager (current: {current_url[:60]})...")
                await cdp_send(ws, "Page.enable")
                nav_id = _next_id()
                await ws.send(json.dumps({
                    "id": nav_id, "method": "Page.navigate",
                    "params": {"url": ads_manager_url}
                }))
                token = await intercept_access_token(ws, reload=False, timeout=40.0)

            if token:
                print(f"  Token captured — querying Meta Marketing API...")
                api_data = await fetch_via_meta_api(token)
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
                        "total_spend": round(total_spend, 2),
                        "total_impressions": total_impr,
                        "total_clicks": total_clicks,
                        "active_campaigns": active,
                        "avg_ctr": round(total_clicks / total_impr * 100, 2) if total_impr > 0 else 0,
                    }
                    result["ad_account_name"] = (
                        api_data[0]["account_name"] if len(api_data) == 1
                        else f"{len(api_data)} accounts"
                    )
                    result["ad_account_id"] = api_data[0]["account_id"] if len(api_data) == 1 else None
                    print(f"  ✓ {len(all_campaigns)} campaigns, ${total_spend:.2f} total spend")
                    return result
                else:
                    print("  Meta API returned no data — falling back to DOM")
            else:
                print("  No token intercepted — trying DOM scrape")

            # ── Strategy 2: DOM scrape ────────────────────────────────────
            await asyncio.sleep(5)
            dom_raw = await cdp_evaluate(ws, DOM_EXTRACT_JS)

            if dom_raw:
                try:
                    dom = json.loads(dom_raw)
                except Exception:
                    dom = {"found": False}

                if dom.get("found"):
                    result["ad_account_id"] = dom.get("accountId")
                    result["ad_account_name"] = dom.get("accountName")
                    campaigns, summary = parse_dom_campaigns(dom.get("campaigns", []))
                    result["campaigns"] = campaigns
                    result["summary"] = summary
                    print(f"  DOM: {len(campaigns)} campaigns")
                else:
                    snippet = dom.get("bodySnippet", "")[:100]
                    url = dom.get("url", "")
                    result["error"] = f"DOM: no table. URL={url} Page={snippet}"
                    print(f"  DOM failed — URL: {url}")
                    print(f"  Page snippet: {snippet}")
            else:
                result["error"] = "Empty DOM result"

    except Exception as e:
        result["error"] = str(e)
        print(f"  ERROR: {e}")
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

    fixed_ports = config.get("fixed_ports", [])
    profiles = await get_active_profiles(adspower_url, fixed_ports=fixed_ports)
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
            r = await client.post(
                f"{hermes_url}/api/v1/meta-ads/ingest",
                json=payload,
                headers=headers,
            )
            if r.status_code == 200:
                print(f"\n✓ Ingested {r.json().get('profiles_ingested')} profiles into Hermes")
            else:
                print(f"\n✗ Hermes ingest failed: HTTP {r.status_code} — {r.text[:200]}")
    except Exception as e:
        print(f"\n✗ Failed to POST to Hermes: {e}")

    print("=== Done ===")

if __name__ == "__main__":
    asyncio.run(main())
