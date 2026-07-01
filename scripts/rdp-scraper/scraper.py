"""
JARVIS Meta Ads Scraper — runs on RDP machines (Windows).

Strategy:
  1. Query Ads Power local API for active browser profiles
  2. For each profile: get CDP debug port, find any authenticated Facebook tab
  3. Connect via raw CDP websockets
  4. Extract access_token from page JS memory (NO reload, NO navigation)
     - Search <script> tags for EAA... token pattern
     - Try Facebook's require('AccessToken') module
     - Search window globals and JSON structures
  5. If no memory token: inject fetch override, trigger UI refresh, wait
  6. Call Meta Marketing API with captured token
  7. Fallback: DOM scrape the current page
  8. POST results to Hermes

NO RELOADS. NO NAVIGATION. Working with the page as-is preserves auth.
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

# ── Ads Power / Port discovery ────────────────────────────────────────────────

async def get_active_profiles(adspower_url: str, fixed_ports: list[int] = None) -> list[dict]:
    active = []
    known_ports: set[str] = set()

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

    if not active:
        print("Scanning ports 50000-58000 for Chrome instances...")
        async with httpx.AsyncClient(timeout=0.4) as client:
            async def check(port):
                try:
                    r = await client.get(f"http://localhost:{port}/json/list")
                    if r.status_code == 200:
                        tabs = r.json()
                        fb = [t for t in tabs if "facebook.com" in t.get("url", "")]
                        if fb:
                            return {"user_id": f"port_{port}", "name": f"port_{port}",
                                    "debug_port": str(port), "_fb": len(fb)}
                except Exception:
                    pass
                return None
            results = await asyncio.gather(*[check(p) for p in range(50000, 58000)])
            for r in results:
                if r and r["debug_port"] not in known_ports:
                    active.append(r)

    return active

# ── CDP helpers ───────────────────────────────────────────────────────────────

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
    cmd_id = _next_id()
    await ws.send(json.dumps({"id": cmd_id, "method": method, "params": params or {}}))
    deadline = asyncio.get_event_loop().time() + 20.0
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

async def cdp_eval(ws, js: str) -> str | None:
    result = await cdp_send(ws, "Runtime.evaluate", {
        "expression": js,
        "returnByValue": True,
        "awaitPromise": False,
        "timeout": 10000,
    })
    val = result.get("result", {})
    if val.get("type") == "string":
        return val["value"]
    if "value" in val:
        v = val["value"]
        return json.dumps(v) if not isinstance(v, str) else v
    return None

# ── JS: extract ALL EAA tokens from page memory ──────────────────────────────

JS_EXTRACT_ALL_TOKENS = r"""
(function() {
    // Collect ALL EAA tokens — we'll try each one via the API
    var pat = /EAA[A-Za-z0-9+\/=_\-]{50,}/g;
    var found = new Set();

    // 1. All <script> tag contents
    var scripts = document.querySelectorAll('script');
    for (var i = 0; i < scripts.length; i++) {
        var ms = scripts[i].textContent.match(pat) || [];
        for (var m of ms) found.add(m);
    }

    // 2. Facebook module system
    var moduleNames = ['AccessToken', 'UserAuthData', 'CurrentUserInitialData'];
    for (var mn of moduleNames) {
        try {
            var mod = require(mn);
            if (mod) {
                var t = mod.getAccessToken ? mod.getAccessToken() :
                        mod.access_token || mod.accessToken || mod.token;
                if (t && /^EAA/.test(t)) found.add(t);
            }
        } catch(e) {}
    }

    // 3. Window globals
    var globals = ['__accessToken', 'accessToken', '__FB_TOKEN', '_token', 'FB_TOKEN'];
    for (var g of globals) {
        if (window[g] && /^EAA/.test(window[g])) found.add(window[g]);
    }

    // 4. Large JSON structures
    var objs = [window.__FB_DATA, window.__PRELOADED_STATE__, window.__RELAY_BOOTSTRAP_DATA__,
                window.__RELAY_STORE__, window.AdsManagerBoot, window.__BootloaderConfig];
    for (var o of objs) {
        try {
            var ms2 = JSON.stringify(o).match(pat) || [];
            for (var m2 of ms2) found.add(m2);
        } catch(e) {}
    }

    // Sort by length desc (longer tokens tend to be more permissioned)
    var arr = Array.from(found).sort(function(a,b){ return b.length - a.length; });
    return JSON.stringify(arr);
})()
"""

# ── JS: install fetch/XHR override to capture next token ─────────────────────

JS_INSTALL_OVERRIDE = r"""
(function() {
    if (window.__jarvis_override_installed) return 'already_installed';
    window.__jarvis_captured_token = null;
    window.__jarvis_override_installed = true;

    function capture(url, headers) {
        try {
            if (!url || !url.includes('graph.facebook.com')) return;
            // From URL param
            try {
                var u = new URL(url);
                var t = u.searchParams.get('access_token');
                if (t && t.length > 30) { window.__jarvis_captured_token = t; return; }
            } catch(e) {}
            // From Authorization header
            function checkAuth(h) {
                if (!h) return;
                var auth = (typeof h.get === 'function') ? h.get('Authorization') : h['Authorization'];
                if (!auth) auth = (typeof h.get === 'function') ? h.get('authorization') : h['authorization'];
                if (auth && auth.startsWith('Bearer ')) {
                    var t = auth.substring(7);
                    if (t.length > 30) { window.__jarvis_captured_token = t; }
                }
            }
            checkAuth(headers);
        } catch(e) {}
    }

    var origFetch = window.fetch;
    window.fetch = function(input, init) {
        try {
            var url = typeof input === 'string' ? input : (input && input.url);
            capture(url, init && init.headers);
        } catch(e) {}
        return origFetch.apply(this, arguments);
    };

    var origOpen = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function(method, url) {
        try { capture(url, null); } catch(e) {}
        this._url = url;
        return origOpen.apply(this, arguments);
    };

    var origSetHeader = XMLHttpRequest.prototype.setRequestHeader;
    XMLHttpRequest.prototype.setRequestHeader = function(name, value) {
        try {
            if (name && name.toLowerCase() === 'authorization' && value && value.startsWith('Bearer ')) {
                if (this._url && this._url.includes('graph.facebook.com')) {
                    window.__jarvis_captured_token = value.substring(7);
                }
            }
        } catch(e) {}
        return origSetHeader.apply(this, arguments);
    };

    return 'installed';
})()
"""

# ── JS: trigger UI refresh to cause new API calls ────────────────────────────

JS_TRIGGER_REFRESH = r"""
(function() {
    var results = [];

    // 1. Click "Campaigns" nav link — triggers full campaign data reload
    try {
        var links = Array.from(document.querySelectorAll('a, [role="tab"], [role="menuitem"], [role="link"]'));
        var campaignLink = links.find(function(l) {
            var txt = (l.textContent || l.innerText || '').trim();
            return txt === 'Campaigns' || l.getAttribute('data-key') === 'campaigns';
        });
        if (campaignLink) { campaignLink.click(); results.push('clicked:campaigns'); }
    } catch(e) {}

    // 2. Click "Today" preset in date selector
    try {
        var todayBtn = Array.from(document.querySelectorAll('[role="option"], [role="button"], button')).find(function(b) {
            var txt = (b.textContent || '').trim();
            return txt === 'Today' || txt === 'Last 7 days';
        });
        if (todayBtn) { todayBtn.click(); results.push('clicked:today'); }
    } catch(e) {}

    // 3. Click date range button to open picker (triggers data load on close)
    try {
        var dateBtn = document.querySelector('[data-testid="date-range-selector"]') ||
                      document.querySelector('[aria-label*="date range"]') ||
                      document.querySelector('[aria-label*="Date range"]');
        if (dateBtn) { dateBtn.click(); results.push('clicked:date_range'); }
    } catch(e) {}

    // 4. Click any visible filter or column header to force table reload
    try {
        var colHeader = document.querySelector('[role="columnheader"]');
        if (colHeader) { colHeader.click(); results.push('clicked:column'); }
    } catch(e) {}

    // 5. Scroll to trigger lazy-load
    window.scrollBy(0, 100);
    window.scrollBy(0, -100);
    results.push('scrolled');

    return results.join(',') || 'no_trigger';
})()
"""

# ── Service worker: find its CDP session and intercept real API tokens ────────

async def find_sw_ws_url(debug_port: str) -> str | None:
    """Find the Ads Manager service worker's CDP WebSocket URL."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"http://localhost:{debug_port}/json/list")
            targets = r.json()
            # Look for SW targets for adsmanager.facebook.com
            for t in targets:
                ttype = t.get("type", "")
                url = t.get("url", "")
                ws = t.get("webSocketDebuggerUrl", "")
                if ttype == "service_worker" and "adsmanager.facebook.com" in url and ws:
                    print(f"  Found SW: {url[:70]}")
                    return ws
            # Also check worker type
            for t in targets:
                ttype = t.get("type", "")
                url = t.get("url", "")
                ws = t.get("webSocketDebuggerUrl", "")
                if ttype == "worker" and "adsmanager" in url and ws:
                    print(f"  Found worker: {url[:70]}")
                    return ws
    except Exception as e:
        print(f"  [WARN] SW discovery: {e}")
    return None


async def listen_for_graph_token(ws, timeout: float = 30.0) -> str | None:
    """Listen on a CDP WebSocket for graph.facebook.com requests and extract access_token."""
    token = None
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
            data = json.loads(raw)
        except asyncio.TimeoutError:
            continue
        except Exception:
            break

        method = data.get("method", "")
        params = data.get("params", {})

        if method == "Network.requestWillBeSent":
            url = params.get("request", {}).get("url", "")
            if "graph.facebook.com" in url:
                # From URL param
                if "access_token=" in url:
                    parsed = urlparse(url)
                    qs = parse_qs(parsed.query)
                    if "access_token" in qs:
                        candidate = qs["access_token"][0]
                        if len(candidate) > 50:
                            token = candidate
                            print(f"  ✓ Token from SW URL param ({len(token)} chars)")
                            break
                # From Authorization header
                headers = params.get("request", {}).get("headers", {})
                for k, v in headers.items():
                    if k.lower() == "authorization" and v.startswith("Bearer "):
                        candidate = v[7:]
                        if len(candidate) > 50:
                            token = candidate
                            print(f"  ✓ Token from SW Authorization header ({len(token)} chars)")
                            break
                if token:
                    break

    return token


# ── Meta Marketing API ────────────────────────────────────────────────────────

async def fetch_via_meta_api(token: str, known_account_ids: list[str] = None) -> list[dict]:
    results = []
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:

            # ── Validate token with /me ────────────────────────────────────
            me_r = await client.get(
                "https://graph.facebook.com/v19.0/me",
                params={"access_token": token, "fields": "id,name"},
            )
            me_data = me_r.json()
            if "error" in me_data:
                print(f"    Token validation failed: {me_data['error'].get('message','?')} (code {me_data['error'].get('code','?')})")
                print(f"    Token is invalid or wrong type — will try account-direct call")
            else:
                print(f"    Token valid — user: {me_data.get('name','?')} ({me_data.get('id','?')})")

            # ── Try /me/adaccounts ─────────────────────────────────────────
            r = await client.get(
                "https://graph.facebook.com/v19.0/me/adaccounts",
                params={"access_token": token, "fields": "id,name,account_status", "limit": 100},
            )
            rj = r.json()
            accounts = rj.get("data", [])

            if "error" in rj or not accounts:
                err = rj.get("error", {})
                print(f"    /me/adaccounts failed: {err.get('message','no data')} (code {err.get('code','?')})")

                # ── Try account-direct endpoint using known account IDs ────
                if known_account_ids:
                    print(f"    Trying direct account call for: {known_account_ids}")
                    for aid_raw in known_account_ids:
                        aid = f"act_{aid_raw}" if not aid_raw.startswith("act_") else aid_raw
                        # Test if token works for this specific account
                        acc_r = await client.get(
                            f"https://graph.facebook.com/v19.0/{aid}",
                            params={"access_token": token, "fields": "id,name,account_status"},
                        )
                        acc_data = acc_r.json()
                        if "error" not in acc_data:
                            accounts = [{"id": aid, "name": acc_data.get("name", aid)}]
                            print(f"    Direct account access OK: {accounts[0]['name']}")
                        else:
                            print(f"    Direct account {aid} also failed: {acc_data['error'].get('message','?')}")

                if not accounts:
                    return []

            print(f"    Meta API: {len(accounts)} ad accounts found")
            for account in accounts:
                aid = account["id"]
                account_name = account.get("name", aid)

                ins_r = await client.get(
                    f"https://graph.facebook.com/v19.0/{aid}/insights",
                    params={
                        "access_token": token,
                        "date_preset": "today",
                        "level": "campaign",
                        "fields": "campaign_id,campaign_name,spend,impressions,clicks,ctr,cpm,cpc,reach",
                        "limit": 100,
                    },
                )
                ins_data = ins_r.json().get("data", [])

                campaigns = []
                total_spend = total_impr = total_clicks = 0
                for ins in ins_data:
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

                avg_ctr = round(total_clicks / total_impr * 100, 2) if total_impr else 0
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

# ── DOM extraction ────────────────────────────────────────────────────────────

DOM_EXTRACT_JS = r"""
(function() {
    try {
        var rows = Array.from(document.querySelectorAll('[role="row"]'));
        var dataRows = rows.filter(function(r) {
            return r.querySelectorAll('[role="cell"],[role="gridcell"]').length >= 3;
        });
        if (!dataRows.length) {
            return JSON.stringify({found:false, url:location.href, title:document.title,
                snippet:(document.body||{}).innerText?document.body.innerText.slice(0,500):''});
        }
        var campaigns = dataRows.map(function(row) {
            var cells = Array.from(row.querySelectorAll('[role="cell"],[role="gridcell"],td'));
            var t = cells.map(function(c){return c.innerText.trim();});
            return {name:t[0]||'',status:t[1]||'',budget:t[2]||'',impressions:t[4]||'',
                    clicks:t[5]||'',ctr:t[6]||'',cpc:t[7]||'',spend:t[t.length-1]||''};
        }).filter(function(c){return c.name&&c.name.length>1;});
        var urlMatch = location.href.match(/act[_=](\d+)/);
        return JSON.stringify({found:campaigns.length>0, campaigns:campaigns,
            accountId:urlMatch?urlMatch[1]:null, accountName:document.title, url:location.href});
    } catch(e) {
        return JSON.stringify({found:false, error:e.message, url:location.href});
    }
})()
"""

def parse_dom_campaigns(raw: list[dict]):
    campaigns = []
    total_spend = total_impr = total_clicks = active_count = 0
    for c in raw:
        def pn(s):
            s = re.sub(r"[^\d.]", "", str(s) if s else "")
            try:
                return float(s) if "." in s else int(s)
            except Exception:
                return 0
        spend_val = float(pn(c.get("spend", "")))
        impr_val = int(pn(c.get("impressions", "")))
        clicks_val = int(pn(c.get("clicks", "")))
        total_spend += spend_val
        total_impr += impr_val
        total_clicks += clicks_val
        if "active" in (c.get("status") or "").lower() or "delivering" in (c.get("status") or "").lower():
            active_count += 1
        campaigns.append(c)
    avg_ctr = round(total_clicks / total_impr * 100, 2) if total_impr else 0
    return campaigns, {"total_spend": round(total_spend, 2), "total_impressions": total_impr,
                       "total_clicks": total_clicks, "active_campaigns": active_count, "avg_ctr": avg_ctr}

# ── Bad URL detection ─────────────────────────────────────────────────────────

BAD_PATTERNS = [
    "loginpage", "/login?", "chrome-error", "about:blank",
    "newtab", "chromewebdata",
]

def is_bad_url(url: str) -> bool:
    return any(p in url for p in BAD_PATTERNS)

# ── Profile scraper ───────────────────────────────────────────────────────────

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

        # ── Pick best tab: adsmanager.facebook.com preferred ─────────────
        # Accept any authenticated Facebook tab (not login/error)
        ads_tab = None
        for t in tabs:
            url = t.get("url", "")
            if "adsmanager.facebook.com" in url and not is_bad_url(url):
                ads_tab = t
                print(f"  Found Ads Manager tab: {url[:80]}")
                break

        if not ads_tab:
            for t in tabs:
                url = t.get("url", "")
                if "facebook.com" in url and not is_bad_url(url):
                    ads_tab = t
                    print(f"  Using Facebook tab: {url[:80]}")
                    break

        if not ads_tab:
            fb_urls = [t.get("url", "")[:60] for t in tabs if "facebook.com" in t.get("url", "")]
            result["error"] = f"No usable Facebook tab (all login/blocked): {fb_urls}"
            print(f"  Skipping — all Facebook tabs are login/blocked")
            print(f"  ACTION NEEDED: Open adsmanager.facebook.com in this profile manually")
            return result

        ws_url = ads_tab.get("webSocketDebuggerUrl")
        if not ws_url:
            result["error"] = "No webSocketDebuggerUrl"
            return result

        current_url = ads_tab.get("url", "")
        print(f"  Connecting to tab: {current_url[:80]}")

        # Extract account ID from URL (used for direct API fallback)
        account_ids_from_url = re.findall(r'act[_=](\d+)', current_url)
        if account_ids_from_url:
            print(f"  Account ID from URL: {account_ids_from_url}")

        token = None

        # ── Strategy 1: Service worker CDP interception ───────────────────
        # The SW (www-service-worker.js) is what actually calls graph.facebook.com
        # with real auth. Connect to SW's CDP, enable Network events, trigger
        # a page UI action, and capture the token from SW network events.
        sw_ws_url = await find_sw_ws_url(debug_port)

        if sw_ws_url:
            print("  Connecting to service worker CDP session...")
            try:
                async with websockets.connect(
                    sw_ws_url, ping_interval=None, open_timeout=10, close_timeout=3
                ) as sw_ws:
                    await cdp_send(sw_ws, "Network.enable")
                    print("  SW network monitoring active. Triggering UI to force API call...")

                    # Connect to page and trigger UI refresh concurrently
                    async def trigger_page():
                        await asyncio.sleep(0.5)
                        try:
                            async with websockets.connect(
                                ws_url, ping_interval=None, open_timeout=10, close_timeout=3
                            ) as pw:
                                await cdp_send(pw, "Runtime.enable")
                                r = await cdp_eval(pw, JS_TRIGGER_REFRESH)
                                print(f"  Page trigger: {r}")
                                # Also install JS override on page for its own calls
                                await cdp_eval(pw, JS_INSTALL_OVERRIDE)
                        except Exception as te:
                            print(f"  Page trigger error: {te}")

                    trigger_task = asyncio.create_task(trigger_page())
                    token = await listen_for_graph_token(sw_ws, timeout=30.0)
                    await asyncio.gather(trigger_task, return_exceptions=True)

            except Exception as e:
                print(f"  SW connection failed: {e}")

        # ── Strategy 2: Page JS override + page Network events ────────────
        # If SW interception didn't work, try from the page context
        if not token:
            print("  SW interception failed — trying page-level capture...")
            async with websockets.connect(
                ws_url, ping_interval=None, open_timeout=15, close_timeout=5
            ) as ws:
                await cdp_send(ws, "Runtime.enable")
                await cdp_send(ws, "Network.enable")
                await cdp_eval(ws, JS_INSTALL_OVERRIDE)

                trigger_result = await cdp_eval(ws, JS_TRIGGER_REFRESH)
                print(f"  Page trigger: {trigger_result}")

                deadline = asyncio.get_event_loop().time() + 25.0
                while asyncio.get_event_loop().time() < deadline:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                        data = json.loads(raw)
                    except asyncio.TimeoutError:
                        captured = await cdp_eval(ws, "window.__jarvis_captured_token || ''")
                        if captured and len(captured) > 50:
                            token = captured
                            print(f"  ✓ Token via JS override ({len(token)} chars)")
                            break
                        continue
                    except Exception:
                        break

                    method = data.get("method", "")
                    params = data.get("params", {})
                    if method == "Network.requestWillBeSent":
                        url = params.get("request", {}).get("url", "")
                        if "graph.facebook.com" in url and "access_token=" in url:
                            parsed = urlparse(url)
                            qs = parse_qs(parsed.query)
                            if "access_token" in qs:
                                candidate = qs["access_token"][0]
                                if len(candidate) > 50:
                                    token = candidate
                                    print(f"  ✓ Token from page Network event ({len(token)} chars)")
                                    break

        # ── Strategy 3: Try ALL EAA tokens from page memory ──────────────
        # The script-tag tokens are SDK/client tokens (code 1 error) but
        # there might be more — try all of them with a quick /me check
        if not token:
            print("  Trying all EAA tokens from page memory...")
            async with websockets.connect(
                ws_url, ping_interval=None, open_timeout=15, close_timeout=5
            ) as ws:
                await cdp_send(ws, "Runtime.enable")
                raw_tokens = await cdp_eval(ws, JS_EXTRACT_ALL_TOKENS)
                if raw_tokens:
                    try:
                        all_tokens = json.loads(raw_tokens)
                        print(f"  Found {len(all_tokens)} EAA tokens: {[t[:15]+'...' for t in all_tokens[:5]]}")
                        async with httpx.AsyncClient(timeout=10.0) as hclient:
                            for t in all_tokens:
                                me_r = await hclient.get(
                                    "https://graph.facebook.com/v19.0/me",
                                    params={"access_token": t, "fields": "id,name"},
                                )
                                me_data = me_r.json()
                                if "error" not in me_data:
                                    token = t
                                    print(f"  ✓ Valid user token found: {me_data.get('name')} ({len(t)} chars)")
                                    break
                                else:
                                    code = me_data.get("error", {}).get("code")
                                    if code != 1:  # Code 1 = invalid; other codes = different issue
                                        print(f"  Token {t[:20]}... → code {code} (might be valid with right perms)")
                    except Exception as e:
                        print(f"  Token scan error: {e}")

        # ── Use token with Meta Marketing API ─────────────────────────────
        if token:
            api_data = await fetch_via_meta_api(token, known_account_ids=account_ids_from_url)
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
                    "avg_ctr": round(total_clicks / total_impr * 100, 2) if total_impr else 0,
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
            print("  No token found — falling back to DOM scrape")

        # ── Strategy 4: DOM scrape (open fresh connection) ─────────────────
        await asyncio.sleep(3)
        async with websockets.connect(
            ws_url, ping_interval=None, open_timeout=15, close_timeout=5
        ) as ws:
            await cdp_send(ws, "Runtime.enable")
            dom_raw = await cdp_eval(ws, DOM_EXTRACT_JS)
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
                    print(f"  DOM: {len(campaigns)} campaigns extracted")
                else:
                    url = dom.get("url", "")
                    snippet = dom.get("snippet", dom.get("bodySnippet", ""))[:100]
                    result["error"] = f"DOM no table. URL={url}"
                    print(f"  DOM failed. URL: {url}")
                    print(f"  Snippet: {snippet}")
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
