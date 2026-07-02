"""
JARVIS Meta Ads Scraper v4 — runs on RDP machines (Windows).

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
  9. Send Telegram summary to JARVIS bot

v4 improvements:
  - Retry failed profiles (configurable count + delay)
  - Smarter session health detection (logged-out, checkpoint, blocked)
  - Telegram summary after every run (spend, campaigns, profile status)
  - Better error categorization — tells you exactly WHY a profile failed
  - Timeout guard on each profile scrape (3 min max)

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
    with open(CONFIG_PATH, encoding="utf-8-sig") as f:  # utf-8-sig strips BOM if present
        return json.load(f)


# ── Session health detection ──────────────────────────────────────────────────

SESSION_BAD_PATTERNS = [
    "loginpage", "/login?", "checkpoint", "recover", "two_step",
    "unsupportedbrowser", "blocked", "disabled", "suspended",
    "chrome-error://", "about:blank", "newtab", "chromewebdata",
]

SESSION_LOGGED_OUT_KEYWORDS = [
    "Log in to Facebook", "Create new account", "Forgotten password",
    "Email or phone number", "Enter your password", "Log into Facebook",
    "Sign up for Facebook",
]

SESSION_CHECKPOINT_KEYWORDS = [
    "We noticed unusual activity", "Your account has been locked",
    "Confirm your identity", "Security check required",
    "We need to verify", "account is temporarily locked",
]


def classify_session(url: str, body_text: str = "") -> str:
    """
    Returns: 'ok' | 'logged_out' | 'checkpoint' | 'bad_url' | 'no_fb_tab'
    """
    url_lower = url.lower()
    if any(p in url_lower for p in SESSION_BAD_PATTERNS):
        return "bad_url"
    for kw in SESSION_LOGGED_OUT_KEYWORDS:
        if kw in body_text:
            return "logged_out"
    for kw in SESSION_CHECKPOINT_KEYWORDS:
        if kw in body_text:
            return "checkpoint"
    return "ok"


# ── Telegram notifications ────────────────────────────────────────────────────

async def send_telegram(bot_token: str, chat_id: str, message: str) -> bool:
    """Send a message directly to Telegram from the scraper."""
    if not bot_token or not chat_id:
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
            )
            return r.status_code == 200
    except Exception as e:
        print(f"[WARN] Telegram send failed: {e}")
        return False


def build_scrape_summary(rdp_host: str, scraped: list[dict], elapsed: float) -> str:
    """Build a Telegram-formatted summary of the scrape run."""
    total_spend = 0.0
    total_campaigns = 0
    total_active = 0
    ok_profiles = []
    failed_profiles = []

    for p in scraped:
        name = p.get("profile_name") or p.get("profile_id", "?")
        err = p.get("error")
        campaigns = p.get("campaigns", [])
        summary = p.get("summary", {})

        spend = summary.get("total_spend", 0) or 0
        active = summary.get("active_campaigns", 0) or 0

        if err and not campaigns:
            # Classify the failure
            if "logged_out" in str(err):
                failed_profiles.append(f"🔐 {name} — logged out")
            elif "checkpoint" in str(err):
                failed_profiles.append(f"🚫 {name} — checkpoint/blocked")
            elif "No usable Facebook tab" in str(err) or "no_fb_tab" in str(err):
                failed_profiles.append(f"🌐 {name} — no FB tab open")
            elif "empty account" in str(err):
                failed_profiles.append(f"📭 {name} — empty account")
            else:
                short_err = str(err)[:60]
                failed_profiles.append(f"❌ {name} — {short_err}")
        else:
            total_spend += spend
            total_campaigns += len(campaigns)
            total_active += active
            ok_profiles.append(f"✅ {name} — ${spend:,.2f} | {active} active")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"📊 <b>Meta Ads Scrape — {rdp_host}</b>",
        f"<i>{now} · {elapsed:.0f}s</i>",
        "",
        f"💰 Total Spend: <b>${total_spend:,.2f}</b>",
        f"▶️ Active Campaigns: <b>{total_active}</b>",
        f"📋 Total Campaigns: <b>{total_campaigns}</b>",
        "",
    ]

    if ok_profiles:
        lines.append("<b>Profiles:</b>")
        lines.extend(ok_profiles)

    if failed_profiles:
        lines.append("")
        lines.append("<b>⚠️ Issues:</b>")
        lines.extend(failed_profiles)

    return "\n".join(lines)

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
        # Use local-active endpoint — returns all open browsers + their debug ports in one call
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{adspower_url}/api/v1/browser/local-active")
            data = r.json()
            if data.get("code") == 0:
                for p in data.get("data", {}).get("list", []):
                    uid = p.get("user_id", "")
                    port_str = str(p.get("debug_port", ""))
                    if port_str and port_str not in known_ports:
                        active.append({
                            "user_id": uid,
                            "name": p.get("name", uid),
                            "debug_port": port_str,
                        })
                        known_ports.add(port_str)
                        print(f"  AdsPower: user {uid} → port {port_str}")
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

async def cdp_eval(ws, js: str, await_promise: bool = False, timeout: int = 10) -> str | None:
    result = await cdp_send(ws, "Runtime.evaluate", {
        "expression": js,
        "returnByValue": True,
        "awaitPromise": await_promise,
        "timeout": timeout * 1000,
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
    window.__jarvis_all_tokens = [];
    window.__jarvis_override_installed = true;

    function capture(url, headers) {
        try {
            if (!url || !url.includes('graph.facebook.com')) return;
            var found = null;
            // From URL param
            try {
                var u = new URL(url);
                var t = u.searchParams.get('access_token');
                if (t && t.length > 30) { found = t; }
            } catch(e) {}
            // From Authorization header
            if (!found && headers) {
                var auth = (typeof headers.get === 'function') ?
                    (headers.get('Authorization') || headers.get('authorization')) :
                    (headers['Authorization'] || headers['authorization']);
                if (auth && auth.startsWith('Bearer ')) {
                    var t2 = auth.substring(7);
                    if (t2.length > 30) { found = t2; }
                }
            }
            if (found && !window.__jarvis_all_tokens.includes(found)) {
                window.__jarvis_all_tokens.push(found);
                window.__jarvis_captured_token = found;
            }
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

# ── JS: dismiss stale-session / error modals without reloading ───────────────

JS_DISMISS_MODALS = r"""
(function() {
    var dismissed = [];
    // Dismiss Facebook's "You've been away" / "sort timed out" / "connection lost" modals
    // by clicking their "Close" button (NOT "Refresh" — that reloads the page)
    var buttons = Array.from(document.querySelectorAll('[role="button"], button'));
    for (var b of buttons) {
        var txt = (b.textContent || b.innerText || '').trim();
        if (txt === 'Close' || txt === '×' || txt === 'x') {
            try { b.click(); dismissed.push('closed:' + txt); } catch(e) {}
        }
    }
    // Also try aria-label dismiss buttons
    var dismissBtns = document.querySelectorAll('[aria-label="Close"],[aria-label="Dismiss"],[aria-label="close"]');
    for (var d of dismissBtns) {
        try { d.click(); dismissed.push('aria:closed'); } catch(e) {}
    }
    return dismissed.join(',') || 'nothing_dismissed';
})()
"""

# ── JS: quick page state check — is there actual campaign data? ───────────────

JS_CHECK_PAGE_STATE = r"""
(function() {
    var t = document.body.innerText || '';
    var hasEmpty = t.includes('Get set up to run ads') ||
                   t.includes('publish your first ad campaign') ||
                   t.includes('No campaigns') ||
                   t.includes('No results');
    var hasStale = t.includes("You've been away") ||
                   t.includes('sort request timed out') ||
                   t.includes('internet connection was lost');
    var hasCampaigns = t.includes('Active') || t.includes('Not delivering') ||
                       t.includes('Paused') || t.includes('Inactive');
    var spends = (t.match(/\$[\d,]+\.?\d*/g) || []);
    return JSON.stringify({
        empty_account: hasEmpty,
        stale_session: hasStale,
        has_campaign_keywords: hasCampaigns,
        spend_amounts: spends.slice(0, 10),
        body_len: t.length,
        url: location.href
    });
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

    // NOTE: Do NOT click column headers — causes "sort request timed out" on stale sessions
    // Just scroll to trigger lazy-load
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
                        "campaign_id": ins.get("campaign_id", ""),
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

# ── Network response body capture ─────────────────────────────────────────────

def parse_fb_graphql_for_campaigns(body: str) -> list[dict]:
    """Parse campaign data from Facebook's internal GraphQL or Marketing API responses."""
    if not body:
        return []
    campaigns = []
    try:
        # Strip JSONP prefix Facebook sometimes adds
        if body.startswith("for (;;);"):
            body = body[9:]
        data = json.loads(body)

        def search(obj, depth=0):
            if depth > 20:
                return
            if isinstance(obj, dict):
                # Public Marketing API: campaign_name + spend/impressions
                if "campaign_name" in obj and ("spend" in obj or "impressions" in obj):
                    campaigns.append({
                        "name": obj.get("campaign_name", ""),
                        "status": obj.get("effective_status", obj.get("status", "")),
                        "spend": f"${float(obj.get('spend', 0)):.2f}" if obj.get("spend") else "",
                        "impressions": str(obj.get("impressions", "")),
                        "clicks": str(obj.get("clicks", "")),
                        "ctr": str(obj.get("ctr", "")),
                        "cpm": str(obj.get("cpm", "")),
                        "cpc": str(obj.get("cpc", "")),
                    })
                    return
                # Internal GraphQL: name + delivery_status or insights
                name = obj.get("name")
                if isinstance(name, str) and len(name) > 2:
                    has_delivery = "delivery_status" in obj or "effective_status" in obj
                    has_insights = "insights" in obj
                    if has_delivery or has_insights:
                        c = {
                            "name": name,
                            "status": "",
                            "spend": "", "impressions": "", "clicks": "",
                            "ctr": "", "cpm": "", "cpc": "",
                        }
                        ds = obj.get("delivery_status")
                        if isinstance(ds, dict):
                            c["status"] = ds.get("text", "")
                        elif obj.get("effective_status"):
                            c["status"] = obj["effective_status"]
                        insights = obj.get("insights")
                        if isinstance(insights, dict):
                            # edges or data list
                            items = insights.get("data") or insights.get("edges", [])
                            if isinstance(items, list) and items:
                                ins = items[0]
                                if isinstance(ins, dict) and "node" in ins:
                                    ins = ins["node"]
                                c["spend"] = f"${float(ins.get('spend', 0)):.2f}" if ins.get("spend") else ""
                                c["impressions"] = str(ins.get("impressions", ""))
                                c["clicks"] = str(ins.get("clicks", ""))
                                c["ctr"] = str(ins.get("ctr", ""))
                                c["cpm"] = str(ins.get("cpm", ""))
                                c["cpc"] = str(ins.get("cpc", ""))
                            elif "spend" in insights:
                                c["spend"] = f"${float(insights.get('spend', 0)):.2f}" if insights.get("spend") else ""
                        campaigns.append(c)
                        return
                for v in obj.values():
                    search(v, depth + 1)
            elif isinstance(obj, list):
                for item in obj:
                    search(item, depth + 1)

        search(data)
    except Exception:
        pass
    return campaigns


async def capture_network_responses(ws_url: str, timeout: float = 35.0) -> list[dict]:
    """
    Enable Network on page CDP, trigger UI, capture response bodies from
    ALL graph.facebook.com calls. Returns campaign data parsed from responses.
    Bypasses token entirely — we read data the browser already received.
    """
    all_campaigns: list[dict] = []
    try:
        async with websockets.connect(
            ws_url, ping_interval=None, open_timeout=15, close_timeout=5
        ) as ws:
            await cdp_send(ws, "Runtime.enable")
            await cdp_send(ws, "Network.enable")
            trigger = await cdp_eval(ws, JS_TRIGGER_REFRESH)
            print(f"  Network capture trigger: {trigger}")

            pending: dict[str, str] = {}
            bodies_checked = 0

            deadline = asyncio.get_event_loop().time() + timeout
            while asyncio.get_event_loop().time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    evt = json.loads(raw)
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    break

                method = evt.get("method", "")
                params = evt.get("params", {})

                if method == "Network.responseReceived":
                    url = params.get("response", {}).get("url", "")
                    req_id = params.get("requestId", "")
                    if req_id and (
                        "graph.facebook.com" in url
                        or "facebook.com/api/graphql" in url
                    ):
                        pending[req_id] = url
                        print(f"  → FB response: {url[:80]}")

                if method == "Network.loadingFinished":
                    req_id = params.get("requestId", "")
                    if req_id in pending:
                        url = pending.pop(req_id)
                        try:
                            br = await cdp_send(ws, "Network.getResponseBody", {"requestId": req_id})
                            body = br.get("body", "")
                            if br.get("base64Encoded"):
                                import base64 as _b64
                                body = _b64.b64decode(body).decode("utf-8", errors="replace")
                            if body:
                                bodies_checked += 1
                                parsed = parse_fb_graphql_for_campaigns(body)
                                if parsed:
                                    print(f"  ✓ {len(parsed)} campaigns from response body")
                                    all_campaigns.extend(parsed)
                        except Exception as ex:
                            print(f"  Body extract error: {ex}")

                # Have enough data — stop early
                if all_campaigns and bodies_checked >= 3:
                    break

            print(f"  Network capture: {bodies_checked} bodies, {len(all_campaigns)} campaigns")
    except Exception as e:
        print(f"  Network capture error: {e}")
    return all_campaigns


# ── DOM extraction ────────────────────────────────────────────────────────────

DOM_EXTRACT_JS = r"""
(function() {
    try {
        var urlMatch = location.href.match(/act[_=](\d+)/);
        var accountId = urlMatch ? urlMatch[1] : null;

        // --- Strategy A: role="row" grid (standard ARIA table) ---
        var rows = Array.from(document.querySelectorAll('[role="row"]'));
        var dataRows = rows.filter(function(r) {
            return r.querySelectorAll('[role="cell"],[role="gridcell"]').length >= 3;
        });
        if (dataRows.length) {
            var campaigns = dataRows.map(function(row) {
                var cells = Array.from(row.querySelectorAll('[role="cell"],[role="gridcell"],td'));
                var t = cells.map(function(c){return c.innerText.trim();});
                return {name:t[0]||'',status:t[1]||'',budget:t[2]||'',impressions:t[4]||'',
                        clicks:t[5]||'',ctr:t[6]||'',cpc:t[7]||'',spend:t[t.length-1]||''};
            }).filter(function(c){return c.name&&c.name.length>1;});
            if (campaigns.length > 0)
                return JSON.stringify({found:true, source:'role_row', campaigns:campaigns,
                    accountId:accountId, url:location.href});
        }

        // --- Strategy B: aria-rowindex elements ---
        var ariaRows = Array.from(document.querySelectorAll('[aria-rowindex]'));
        if (ariaRows.length) {
            var campaigns2 = ariaRows.map(function(row) {
                var t = row.innerText.split('\n').map(function(s){return s.trim();}).filter(Boolean);
                return {name:t[0]||'',status:t[1]||'',spend:t[t.length-1]||''};
            }).filter(function(c){return c.name&&c.name.length>1;});
            if (campaigns2.length > 0)
                return JSON.stringify({found:true, source:'aria_rowindex', campaigns:campaigns2,
                    accountId:accountId, url:location.href});
        }

        // --- Strategy C: data-testid rows ---
        var testidRows = Array.from(document.querySelectorAll(
            '[data-testid*="campaign-row"],[data-testid*="adset-row"],[data-testid*="ad-row"]'
        ));
        if (testidRows.length) {
            var campaigns3 = testidRows.map(function(row) {
                var t = row.innerText.split('\n').map(function(s){return s.trim();}).filter(Boolean);
                return {name:t[0]||'',status:t[1]||'',spend:t[t.length-1]||''};
            }).filter(function(c){return c.name&&c.name.length>1;});
            if (campaigns3.length > 0)
                return JSON.stringify({found:true, source:'testid', campaigns:campaigns3,
                    accountId:accountId, url:location.href});
        }

        // --- Strategy D: body text campaign parser ---
        var bodyText = document.body.innerText || '';
        var spendMatches = bodyText.match(/\$[\d,]+\.?\d*/g) || [];

        // After the last column header "Cost per resu[lt]", campaign rows follow:
        // each row is: name → status → metrics
        var STATUS_WORDS = ['Active','Not delivering','Inactive','Off','Paused','Scheduled','Learning','Error','Pending review'];
        var headerIdx = bodyText.indexOf('Cost per resu');
        var parsedCampaigns = [];

        if (headerIdx >= 0) {
            var afterHeaders = bodyText.slice(headerIdx + 15);
            var lines = afterHeaders.split('\n')
                .map(function(l){ return l.trim(); })
                .filter(function(l){ return l.length > 0; });

            var UI_CHROME = ['Compare','Export','Create','Duplicate','Edit','Analyze','A/B test','More',
                             'Actions','Breakdown','Reports','Columns','See more','All ads',
                             'Had delivery','Active ads','Open Dropdown','Search to filter','Campaigns',
                             'Ad sets','Ads','Settings','Create a view','Review and publish','Menu'];
            function isUiChrome(s) {
                for (var ci = 0; ci < UI_CHROME.length; ci++) { if (s === UI_CHROME[ci]) return true; }
                return s.length <= 1;
            }
            function isStatus(s) {
                for (var si = 0; si < STATUS_WORDS.length; si++) {
                    if (s.indexOf(STATUS_WORDS[si]) === 0) return true;
                }
                return false;
            }

            var i = 0;
            while (i < lines.length && parsedCampaigns.length < 30) {
                var l = lines[i];
                if (isUiChrome(l)) { i++; continue; }
                // Find next non-chrome line
                var j = i + 1;
                while (j < lines.length && isUiChrome(lines[j])) j++;
                var nextMeaningful = j < lines.length ? lines[j] : '';

                if (nextMeaningful && isStatus(nextMeaningful) && l.length >= 3 && !isStatus(l)) {
                    var name = l;
                    var status = nextMeaningful;
                    var spend = '';
                    var results = '';
                    // Scan next 15 lines for $ metrics
                    var end = Math.min(j + 15, lines.length);
                    var spendCount = 0;
                    for (var k = j + 1; k < end; k++) {
                        var ml = lines[k];
                        if (isStatus(ml) && ml !== status) break; // next campaign
                        if (ml.match(/^\$[\d,]+\.?\d*$/)) {
                            if (spendCount === 0) { results = ml; spendCount++; }
                            else if (spendCount === 1) { spend = ml; spendCount++; break; }
                        } else if (!results && ml.match(/^[\d,]+$/) && parseInt(ml.replace(/,/g,''),10) > 0) {
                            results = ml;
                        }
                    }
                    parsedCampaigns.push({name:name, status:status, spend:spend, results:results});
                    i = end;
                } else {
                    i++;
                }
            }
        }

        // Extract total spend summary from page footer (e.g. "$422.55 Total spent")
        var totalSpend = null;
        var totalMatch = bodyText.match(/\$([\d,]+\.?\d*)\s*\n?Total spent/i);
        if (!totalMatch) { totalMatch = bodyText.match(/Total spent\s*\n?\$([\d,]+\.?\d*)/i); }
        if (totalMatch) { totalSpend = totalMatch[1].replace(/,/g,''); }

        // Count of campaigns from summary row
        var campaignCount = null;
        var countMatch = bodyText.match(/Results from (\d+) campaigns?/i);
        if (countMatch) { campaignCount = parseInt(countMatch[1]); }

        if (parsedCampaigns.length > 0) {
            return JSON.stringify({found:true, source:'body_text', campaigns:parsedCampaigns,
                totalSpend:totalSpend, campaignCount:campaignCount,
                accountId:accountId, url:location.href});
        }

        // Return raw text for further diagnosis
        return JSON.stringify({
            found: false,
            url: location.href,
            title: document.title,
            bodyLength: bodyText.length,
            spendAmounts: spendMatches.slice(0, 20),
            bodyText: bodyText.slice(0, 2000),
            afterHeaders: headerIdx >= 0 ? bodyText.slice(headerIdx, headerIdx + 1500) : 'NOT_FOUND',
            accountId: accountId,
        });
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

        # ── Collect ALL Ads Manager tabs (try each account, skip empty ones) ──
        ads_tabs = [t for t in tabs
                    if "adsmanager.facebook.com" in t.get("url", "")
                    and not is_bad_url(t.get("url", ""))]

        # Fallback: any authenticated Facebook tab
        if not ads_tabs:
            ads_tabs = [t for t in tabs
                        if "facebook.com" in t.get("url", "")
                        and not is_bad_url(t.get("url", ""))]

        if not ads_tabs:
            fb_urls = [t.get("url", "")[:60] for t in tabs if "facebook.com" in t.get("url", "")]
            result["error"] = "no_fb_tab"
            print(f"  Skipping — no usable Facebook tabs")
            print(f"  ACTION NEEDED: Open adsmanager.facebook.com in this profile manually")
            return result

        print(f"  Found {len(ads_tabs)} Ads Manager tab(s) — will try each")

        # Try each tab; skip empty/logged-out accounts, use first one with campaign data
        ads_tab = None
        for candidate in ads_tabs:
            cand_url = candidate.get("url", "")
            cand_ws = candidate.get("webSocketDebuggerUrl")
            if not cand_ws:
                continue

            # Quick URL-level session check
            session_status = classify_session(cand_url)
            if session_status == "bad_url":
                print(f"  SKIP tab (bad URL): {cand_url[:60]}")
                continue

            acct_ids = re.findall(r'act[_=](\d+)', cand_url)
            print(f"  Checking tab: act={acct_ids} — {cand_url[:80]}")
            try:
                async with websockets.connect(
                    cand_ws, ping_interval=None, open_timeout=10, close_timeout=3
                ) as pw_check:
                    await cdp_send(pw_check, "Runtime.enable")

                    # Check session health via page body text
                    body_text_raw = await cdp_eval(pw_check, "(function(){return document.body.innerText.slice(0,2000);})()")
                    if body_text_raw:
                        session_status = classify_session(cand_url, body_text_raw)
                        if session_status == "logged_out":
                            print(f"  SKIP: profile is logged out — open AdsPower and log back in")
                            result["error"] = "logged_out"
                            continue
                        if session_status == "checkpoint":
                            print(f"  SKIP: Facebook checkpoint/security check — manual action needed")
                            result["error"] = "checkpoint"
                            continue

                    dismissed = await cdp_eval(pw_check, JS_DISMISS_MODALS)
                    if dismissed and dismissed != "nothing_dismissed":
                        print(f"    Dismissed modals: {dismissed}")
                        await asyncio.sleep(1)
                    state_raw = await cdp_eval(pw_check, JS_CHECK_PAGE_STATE)
                    if state_raw:
                        state = json.loads(state_raw)
                        print(f"    State: empty={state.get('empty_account')}, "
                              f"has_campaigns={state.get('has_campaign_keywords')}, "
                              f"spends={state.get('spend_amounts','[]')}, "
                              f"body_len={state.get('body_len')}")
                        if state.get("empty_account") and not state.get("spend_amounts"):
                            print(f"    SKIP: empty account")
                            continue  # try next tab
                    ads_tab = candidate
                    break
            except Exception as e:
                print(f"    Page state check error: {e}")
                ads_tab = candidate  # try it anyway
                break

        if not ads_tab:
            result["error"] = "All Ads Manager tabs are empty accounts"
            print(f"  All tabs are empty accounts — no campaign data")
            return result

        ws_url = ads_tab.get("webSocketDebuggerUrl")
        current_url = ads_tab.get("url", "")
        print(f"  Connecting to tab: {current_url[:80]}")

        account_ids_from_url = re.findall(r'act[_=](\d+)', current_url)
        if account_ids_from_url:
            print(f"  Account ID from URL: {account_ids_from_url}")

        token = None

        # ── Strategy 1: Wake SW via page trigger, then intercept SW's API calls ──
        # Chrome terminates idle service workers. Correct order:
        #   1) Trigger page UI → page fetch wakes the SW
        #   2) Poll for SW to appear in CDP target list
        #   3) Connect to SW, enable Network, trigger again, capture token

        print("  Step 1: Triggering page to wake service worker...")
        try:
            async with websockets.connect(
                ws_url, ping_interval=None, open_timeout=15, close_timeout=5
            ) as pw:
                await cdp_send(pw, "Runtime.enable")
                await cdp_eval(pw, JS_INSTALL_OVERRIDE)
                trigger = await cdp_eval(pw, JS_TRIGGER_REFRESH)
                print(f"  Page trigger: {trigger}")
        except Exception as e:
            print(f"  Page trigger error: {e}")

        # Poll for SW to appear (up to 5s after trigger)
        print("  Step 2: Polling for service worker target (5s)...")
        sw_ws_url = None
        for attempt in range(10):
            sw_ws_url = await find_sw_ws_url(debug_port)
            if sw_ws_url:
                print(f"  SW found after {attempt * 0.5:.1f}s")
                break
            await asyncio.sleep(0.5)

        if sw_ws_url:
            print("  Step 3: Connecting to SW CDP, enabling Network...")
            try:
                async with websockets.connect(
                    sw_ws_url, ping_interval=None, open_timeout=10, close_timeout=3
                ) as sw_ws:
                    await cdp_send(sw_ws, "Network.enable")
                    print("  SW network monitoring active. Triggering page again...")

                    # Trigger page again so SW makes fresh API calls while we listen
                    try:
                        async with websockets.connect(
                            ws_url, ping_interval=None, open_timeout=10, close_timeout=3
                        ) as pw2:
                            await cdp_send(pw2, "Runtime.enable")
                            await cdp_eval(pw2, JS_TRIGGER_REFRESH)
                    except Exception:
                        pass

                    # Listen for SW's real graph.facebook.com calls (25s)
                    token = await listen_for_graph_token(sw_ws, timeout=25.0)
            except Exception as e:
                print(f"  SW connection error: {e}")
        else:
            print("  SW not found after trigger — SW may be dormant or not used by this profile")

        # ── Strategy 2: Page JS override (page's own fetches to graph.facebook.com) ──
        if not token:
            print("  Checking page JS override for captured tokens...")
            try:
                async with websockets.connect(
                    ws_url, ping_interval=None, open_timeout=15, close_timeout=5
                ) as ws:
                    await cdp_send(ws, "Runtime.enable")
                    # Collect ALL unique tokens captured since override was installed
                    all_captured = await cdp_eval(ws, """
                        (function() {
                            var t = window.__jarvis_captured_token || '';
                            var all = window.__jarvis_all_tokens || [];
                            if (t && !all.includes(t)) all.push(t);
                            return JSON.stringify(all.filter(function(x){ return x && x.length > 50; }));
                        })()
                    """)
                    if all_captured:
                        captured_list = json.loads(all_captured)
                        if captured_list:
                            print(f"  Page captured {len(captured_list)} token(s) — validating...")
                            async with httpx.AsyncClient(timeout=10.0) as hc:
                                for ct in captured_list:
                                    me_r = await hc.get(
                                        "https://graph.facebook.com/v19.0/me",
                                        params={"access_token": ct, "fields": "id,name"},
                                    )
                                    me_d = me_r.json()
                                    if "error" not in me_d:
                                        token = ct
                                        print(f"  ✓ Valid token from page: {me_d.get('name')} ({len(ct)} chars)")
                                        break
                                    else:
                                        code = me_d.get("error", {}).get("code", "?")
                                        print(f"  Page token {ct[:20]}... → code {code}")
            except Exception as e:
                print(f"  Page capture check error: {e}")

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

        # ── Strategy 3: Network response body capture ─────────────────────
        # The page makes internal GraphQL calls to graph.facebook.com — we read
        # their response bodies directly. No access token needed.
        if not result["campaigns"]:
            print("  Strategy 3: Capturing network response bodies...")
            net_campaigns = await capture_network_responses(ws_url, timeout=35.0)
            if net_campaigns:
                # Deduplicate by name
                seen: set[str] = set()
                unique = []
                for c in net_campaigns:
                    if c["name"] not in seen:
                        seen.add(c["name"])
                        unique.append(c)
                net_campaigns = unique

                result["ad_account_id"] = account_ids_from_url[0] if account_ids_from_url else None
                result["ad_account_name"] = "Ads Manager"
                result["campaigns"] = net_campaigns

                t_spend = t_impr = t_clicks = t_active = 0
                for c in net_campaigns:
                    sp = re.sub(r"[^\d.]", "", c.get("spend", "") or "")
                    try: t_spend += float(sp) if sp else 0
                    except: pass
                    try: t_impr += int(re.sub(r"[^\d]", "", c.get("impressions", "") or "0") or "0")
                    except: pass
                    try: t_clicks += int(re.sub(r"[^\d]", "", c.get("clicks", "") or "0") or "0")
                    except: pass
                    if "active" in (c.get("status") or "").lower() or "delivering" in (c.get("status") or "").lower():
                        t_active += 1

                result["summary"] = {
                    "total_spend": round(t_spend, 2),
                    "total_impressions": t_impr,
                    "total_clicks": t_clicks,
                    "active_campaigns": t_active,
                    "avg_ctr": round(t_clicks / t_impr * 100, 2) if t_impr else 0,
                }
                print(f"  ✓ Network capture: {len(net_campaigns)} campaigns, ${t_spend:.2f} spend")
                return result

        # ── Strategy 4: DOM scrape (open fresh connection) ─────────────────
        if not result["campaigns"]:
            await asyncio.sleep(2)
            async with websockets.connect(
                ws_url, ping_interval=None, open_timeout=15, close_timeout=5
            ) as ws:
                await cdp_send(ws, "Runtime.enable")
                # Scroll through the campaign table in steps to expose more virtual rows
                try:
                    for step in range(0, 12000, 700):
                        await cdp_eval(ws, f"(function(){{window.scrollTo(0,{step});return 1;}})()")
                        await asyncio.sleep(0.25)
                    await cdp_eval(ws, "(function(){window.scrollTo(0,0);return 1;})()")
                    await asyncio.sleep(0.5)
                    body_len_after = await cdp_eval(ws, "(function(){return document.body.innerText.length;})()")
                    print(f"  Scroll-loaded body length: {body_len_after}")
                except Exception as se:
                    print(f"  Scroll error (continuing): {se}")
                dom_raw = await cdp_eval(ws, DOM_EXTRACT_JS)
                if dom_raw:
                    try:
                        dom = json.loads(dom_raw)
                    except Exception:
                        dom = {"found": False}

                    if dom.get("found"):
                        result["ad_account_id"] = dom.get("accountId")
                        result["ad_account_name"] = dom.get("accountName", dom.get("title", ""))
                        campaigns, summary = parse_dom_campaigns(dom.get("campaigns", []))
                        result["campaigns"] = campaigns
                        result["summary"] = summary
                        # Inject page-footer total spend if available (covers all 35 campaigns)
                        if dom.get("totalSpend"):
                            summary["total_spend_all"] = float(dom["totalSpend"])
                            print(f"  Total spend (all campaigns): ${dom['totalSpend']}")
                        if dom.get("campaignCount"):
                            summary["total_campaigns"] = dom["campaignCount"]
                        print(f"  DOM: {len(campaigns)} campaigns from {dom.get('source','?')} "
                              f"(page total: {dom.get('campaignCount','?')} campaigns, "
                              f"${dom.get('totalSpend','?')} spent)")
                    else:
                        url = dom.get("url", "")
                        body_text = dom.get("bodyText", "")
                        after_headers = dom.get("afterHeaders", "")
                        spend_amounts = dom.get("spendAmounts", [])
                        result["error"] = f"DOM no table. URL={url}"
                        print(f"  DOM failed. URL: {url}")
                        print(f"  Body length: {dom.get('bodyLength', 0)}")
                        if spend_amounts:
                            print(f"  Spend amounts in DOM: {spend_amounts}")
                        # KEY: print what comes AFTER the column headers
                        if after_headers and after_headers != "NOT_FOUND":
                            print(f"  === AFTER HEADERS (1500 chars) ===\n{after_headers[:1500]}")
                        elif after_headers == "NOT_FOUND":
                            print("  'Cost per resu' column header NOT FOUND in body text")
                            if body_text:
                                print(f"  Body text tail (last 500):\n{body_text[-500:]}")
                else:
                    result["error"] = "Empty DOM result"

    except Exception as e:
        result["error"] = str(e)
        print(f"  ERROR: {e}")
        traceback.print_exc()

    return result

# ── Retry wrapper ─────────────────────────────────────────────────────────────

async def scrape_profile_with_retry(profile: dict, retry_count: int = 2, retry_delay: int = 30) -> dict:
    """
    Scrape a profile with automatic retry on failure.
    Skips retry for unrecoverable errors (logged_out, checkpoint, no_fb_tab).
    """
    NO_RETRY_ERRORS = {"logged_out", "checkpoint", "no_fb_tab", "All Ads Manager tabs are empty accounts"}

    last_result = None
    for attempt in range(retry_count + 1):
        if attempt > 0:
            print(f"\n  [RETRY {attempt}/{retry_count}] Waiting {retry_delay}s before retry...")
            await asyncio.sleep(retry_delay)
            print(f"  [RETRY {attempt}/{retry_count}] Retrying {profile['name']}...")

        try:
            result = await asyncio.wait_for(
                scrape_profile(profile),
                timeout=180.0,  # 3 min hard cap per profile
            )
        except asyncio.TimeoutError:
            result = {
                "profile_id": profile["user_id"],
                "profile_name": profile["name"],
                "ad_account_id": None,
                "ad_account_name": None,
                "campaigns": [],
                "summary": {},
                "error": "Timeout (3 min) — profile scrape took too long",
            }

        last_result = result

        # If we got campaign data, we're done
        if result.get("campaigns"):
            if attempt > 0:
                print(f"  ✓ Retry {attempt} succeeded for {profile['name']}")
            return result

        # Check if error is unrecoverable — don't retry
        err = result.get("error", "")
        if any(no_retry in str(err) for no_retry in NO_RETRY_ERRORS):
            print(f"  ✗ Not retrying {profile['name']}: {err}")
            return result

        if attempt < retry_count:
            print(f"  ✗ Attempt {attempt + 1} failed for {profile['name']}: {err}")

    return last_result


# ── Campaign Command Execution ────────────────────────────────────────────────

JS_TOGGLE_CAMPAIGN = """
(function(campaignName, targetAction) {
    var targetOn = (targetAction === 'ACTIVATE');

    function findRowForCampaign(name) {
        // Primary: [role="row"] elements — works with React virtual tables
        var rows = Array.from(document.querySelectorAll('[role="row"], tr'));
        for (var i = 0; i < rows.length; i++) {
            if (rows[i].textContent.indexOf(name) !== -1) {
                return rows[i];
            }
        }
        // Fallback: text node walk → parent row
        var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
        var node;
        while (node = walker.nextNode()) {
            var t = node.textContent.trim();
            if (t === name || (name.length > 4 && t.indexOf(name) !== -1)) {
                var el = node.parentElement;
                for (var j = 0; j < 15; j++) {
                    if (!el) break;
                    if (el.tagName === 'TR' || el.getAttribute('role') === 'row') return el;
                    el = el.parentElement;
                }
            }
        }
        return null;
    }

    var row = findRowForCampaign(campaignName);
    if (!row) {
        return JSON.stringify({ok: false, error: 'campaign_not_found_in_dom'});
    }

    // Scroll row into view so React renders the toggle controls
    row.scrollIntoView({behavior: 'instant', block: 'center'});

    // Find toggle — prefer role=switch, then aria-checked, then checkbox
    // Explicitly exclude the hardcoded FB class which rotates on deploys
    var toggles = row.querySelectorAll('[role="switch"], [aria-checked], input[type="checkbox"]');
    if (toggles.length === 0) {
        return JSON.stringify({ok: false, error: 'no_toggle_in_row', rowText: row.textContent.slice(0, 80)});
    }

    var toggle = toggles[0];
    var isOn = false;
    if (toggle.tagName === 'INPUT' && toggle.type === 'checkbox') {
        isOn = toggle.checked;
    } else {
        isOn = toggle.getAttribute('aria-checked') === 'true';
    }

    if (isOn === targetOn) {
        return JSON.stringify({ok: true, already: true, state: isOn ? 'on' : 'off'});
    }

    // Use native .click() — triggers React synthetic event handlers
    toggle.click();
    return JSON.stringify({ok: true, clicked: true, from: isOn ? 'on' : 'off'});
})(%s, %s)
"""

# Handles Meta's "Are you sure?" confirmation modals that appear after clicking a toggle
JS_CONFIRM_DIALOG = """
(function() {
    var keywords = ['turn off', 'pause', 'confirm', 'ok', 'yes', 'deactivate'];
    var btns = Array.from(document.querySelectorAll('button, [role="button"]'));
    for (var i = 0; i < btns.length; i++) {
        var text = btns[i].textContent.trim().toLowerCase();
        if (keywords.some(function(k) { return text === k || text.indexOf(k) === 0; })) {
            // Make sure it's visible
            var rect = btns[i].getBoundingClientRect();
            if (rect.width > 0 && rect.height > 0) {
                btns[i].click();
                return JSON.stringify({ok: true, confirmed: true, btn: btns[i].textContent.trim()});
            }
        }
    }
    return JSON.stringify({ok: true, no_dialog: true});
})()
"""


async def toggle_campaign_via_cdp(debug_port: str, campaign_name: str, action: str) -> dict:
    """
    Connect to a Chrome debug port, find the Ads Manager tab, and click
    the campaign's On/Off toggle via CDP Runtime.evaluate.

    Two-step process:
      1. JS_TOGGLE_CAMPAIGN — scroll row into view, click the toggle
      2. JS_CONFIRM_DIALOG  — dismiss Meta's "Are you sure?" modal if it appears
    """
    import asyncio
    import websockets as _ws

    try:
        tabs = await cdp_get_tabs(debug_port)
    except Exception as e:
        return {"ok": False, "error": f"cdp_get_tabs failed: {e}"}

    # Find an Ads Manager campaigns tab — accept any ads manager URL
    am_tab = None
    for tab in tabs:
        url = tab.get("url", "")
        if "adsmanager.facebook.com" in url or "business.facebook.com" in url:
            if "campaigns" in url or "ads" in url:
                am_tab = tab
                break
    # Broader fallback: any Ads Manager tab
    if not am_tab:
        for tab in tabs:
            if "adsmanager.facebook.com" in tab.get("url", ""):
                am_tab = tab
                break

    if not am_tab:
        return {"ok": False, "error": "no_ads_manager_tab"}

    ws_url = am_tab.get("webSocketDebuggerUrl")
    if not ws_url:
        return {"ok": False, "error": "no_ws_url"}

    try:
        async with _ws.connect(ws_url, ping_interval=None, close_timeout=10) as ws:
            # Step 1: click the toggle
            js = JS_TOGGLE_CAMPAIGN % (
                json.dumps(campaign_name),
                json.dumps(action),
            )
            raw = await cdp_eval(ws, js, timeout=15)
            if not raw:
                return {"ok": False, "error": "no_result_from_toggle_js"}

            result = json.loads(raw)

            if not result.get("ok"):
                return result   # campaign not found or other error

            if result.get("already"):
                return result   # already in correct state, no confirm needed

            # Step 2: wait for Meta's confirmation modal, then dismiss it
            await asyncio.sleep(1.5)
            conf_raw = await cdp_eval(ws, JS_CONFIRM_DIALOG, timeout=10)
            conf = json.loads(conf_raw) if conf_raw else {"ok": True, "no_dialog": True}
            result["confirm"] = conf

            # Brief pause to let the UI update
            await asyncio.sleep(0.5)
            return result

    except Exception as e:
        return {"ok": False, "error": str(e)}


async def execute_pending_commands(
    hermes_url: str,
    scraper_token: str,
    rdp_host: str,
    active_profiles: list[dict],
) -> None:
    """Fetch pending campaign commands from Hermes and execute them via CDP."""
    headers = {"Content-Type": "application/json"}
    if scraper_token:
        headers["X-Scraper-Token"] = scraper_token

    # Build profile_id → debug_port map
    port_map: dict[str, str] = {
        p["user_id"]: p["debug_port"] for p in active_profiles
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{hermes_url}/api/v1/meta-ads/commands/pending",
                params={"rdp_host": rdp_host},
                headers=headers,
            )
            if r.status_code != 200:
                return
            commands = r.json().get("commands", [])
    except Exception as e:
        print(f"[WARN] Could not fetch pending commands: {e}")
        return

    if not commands:
        return

    print(f"\n[Commands] {len(commands)} pending command(s) to execute")

    async with httpx.AsyncClient(timeout=10.0) as client:
        for cmd in commands:
            cmd_id = cmd["id"]
            profile_id = cmd["profile_id"]
            campaign_name = cmd["campaign_name"]
            action = cmd["action"]

            debug_port = port_map.get(profile_id)
            if not debug_port:
                # Try matching by port_XXXXX format too
                for p in active_profiles:
                    if p.get("name") == profile_id or p.get("user_id") == profile_id:
                        debug_port = p["debug_port"]
                        break

            if not debug_port:
                print(f"  [CMD] {action} '{campaign_name}' → profile {profile_id} not active, skipping")
                await client.patch(
                    f"{hermes_url}/api/v1/meta-ads/commands/{cmd_id}/result",
                    json={"status": "failed", "error": f"profile {profile_id} not active on {rdp_host}"},
                    headers=headers,
                )
                continue

            print(f"  [CMD] {action} '{campaign_name}' via port {debug_port}...")
            result = await toggle_campaign_via_cdp(debug_port, campaign_name, action)

            if result.get("ok"):
                if result.get("already"):
                    status = "done"
                    print(f"  [CMD] ✓ Already {result.get('state', 'set')}")
                else:
                    status = "done"
                    print(f"  [CMD] ✓ Clicked toggle ({result.get('from')} → {action.lower()}d)")
                await client.patch(
                    f"{hermes_url}/api/v1/meta-ads/commands/{cmd_id}/result",
                    json={"status": status},
                    headers=headers,
                )
            else:
                err = result.get("error", "unknown")
                print(f"  [CMD] ✗ Failed: {err}")
                await client.patch(
                    f"{hermes_url}/api/v1/meta-ads/commands/{cmd_id}/result",
                    json={"status": "failed", "error": err},
                    headers=headers,
                )


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    config = load_config()
    hermes_url = config["hermes_url"].rstrip("/")
    scraper_token = config.get("scraper_token", "")
    rdp_host = config["rdp_host"]
    adspower_url = config.get("adspower_url", "http://localhost:50325")
    max_concurrent = config.get("max_concurrent_profiles", 3)
    retry_count = config.get("retry_count", 2)
    retry_delay = config.get("retry_delay_seconds", 30)
    tg_token = config.get("telegram_bot_token", "")
    tg_chat_id = config.get("telegram_chat_id", "")

    start_time = asyncio.get_event_loop().time()
    print(f"=== JARVIS Meta Ads Scraper v4 — {rdp_host} ===")
    print(f"Hermes: {hermes_url} | Retries: {retry_count} | Delay: {retry_delay}s")

    # ── Control check: bail out if dashboard has disabled the scraper ──────────
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            ctrl = await client.get(f"{hermes_url}/api/v1/meta-ads/control")
            if ctrl.status_code == 200 and not ctrl.json().get("enabled", True):
                print("[INFO] Scraper disabled via dashboard. Exiting.")
                return
    except Exception as e:
        print(f"[WARN] Could not reach control endpoint ({e}) — proceeding.")

    fixed_ports = config.get("fixed_ports", [])
    profiles = await get_active_profiles(adspower_url, fixed_ports=fixed_ports)
    if not profiles:
        print("[WARN] No active Ads Power profiles found.")
        if tg_token and tg_chat_id:
            await send_telegram(tg_token, tg_chat_id,
                f"⚠️ <b>Meta Scraper — {rdp_host}</b>\n\nNo active AdsPower profiles found.\nOpen AdsPower and start your browser profiles.")
        return

    print(f"Found {len(profiles)} active profiles: {[p['name'] for p in profiles]}")

    sem = asyncio.Semaphore(max_concurrent)

    async def scrape_with_sem(p):
        async with sem:
            return await scrape_profile_with_retry(p, retry_count=retry_count, retry_delay=retry_delay)

    scraped = await asyncio.gather(*[scrape_with_sem(p) for p in profiles])
    scraped = list(scraped)

    elapsed = asyncio.get_event_loop().time() - start_time

    # ── Ingest to Hermes ───────────────────────────────────────────────────────
    payload = {
        "rdp_host": rdp_host,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "profiles": scraped,
    }

    headers = {"Content-Type": "application/json"}
    if scraper_token:
        headers["X-Scraper-Token"] = scraper_token

    ingest_ok = False
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"{hermes_url}/api/v1/meta-ads/ingest",
                json=payload,
                headers=headers,
            )
            if r.status_code == 200:
                ingested = r.json().get("profiles_ingested", "?")
                print(f"\n✓ Ingested {ingested} profiles into Hermes")
                ingest_ok = True
            else:
                print(f"\n✗ Hermes ingest failed: HTTP {r.status_code} — {r.text[:200]}")
    except Exception as e:
        print(f"\n✗ Failed to POST to Hermes: {e}")

    # ── Telegram summary ───────────────────────────────────────────────────────
    if tg_token and tg_chat_id:
        summary_msg = build_scrape_summary(rdp_host, scraped, elapsed)
        if not ingest_ok:
            summary_msg += "\n\n⚠️ <i>Hermes ingest failed — data not stored</i>"
        sent = await send_telegram(tg_token, tg_chat_id, summary_msg)
        if sent:
            print("✓ Telegram summary sent to JARVIS")
        else:
            print("✗ Telegram summary failed")
    else:
        print("[INFO] No telegram_bot_token/telegram_chat_id in config — skipping notification")

    # ── Execute pending campaign commands (after regular scrape) ──────────────
    await execute_pending_commands(hermes_url, scraper_token, rdp_host, profiles)

    print(f"=== Done in {elapsed:.0f}s ===")

if __name__ == "__main__":
    asyncio.run(main())
