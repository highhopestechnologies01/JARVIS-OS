"""Diagnostic: what's in the DOM after column headers."""
import asyncio
import json
import httpx
import websockets


async def check():
    port = 50656
    async with httpx.AsyncClient(timeout=5.0) as c:
        tabs = (await c.get(f"http://localhost:{port}/json/list")).json()

    tab = next(
        (t for t in tabs
         if "adsmanager" in t.get("url", "")
         and "login" not in t.get("url", "")),
        None,
    )
    if not tab:
        print(f"No adsmanager tab on port {port}")
        return

    print("Tab:", tab["url"][:100])

    js = """(function(){
    var t = document.body.innerText;
    var idx = t.indexOf('Cost per resu');
    return JSON.stringify({
        total_len: t.length,
        header_at: idx,
        after: idx >= 0 ? t.slice(idx, idx + 1000) : 'NOT_FOUND'
    });
})()"""

    async with websockets.connect(
        tab["webSocketDebuggerUrl"], ping_interval=None, open_timeout=10
    ) as ws:
        # Enable runtime
        await ws.send(json.dumps({"id": 1, "method": "Runtime.enable", "params": {}}))
        while True:
            r = json.loads(await asyncio.wait_for(ws.recv(), 5))
            if r.get("id") == 1:
                break

        # Evaluate
        await ws.send(json.dumps({
            "id": 2,
            "method": "Runtime.evaluate",
            "params": {"expression": js, "returnByValue": True, "awaitPromise": False},
        }))
        while True:
            r = json.loads(await asyncio.wait_for(ws.recv(), 10))
            if r.get("id") == 2:
                val = r.get("result", {}).get("result", {}).get("value", "NO_VALUE")
                try:
                    d = json.loads(val)
                    print(f"Body total length : {d['total_len']}")
                    print(f"'Cost per resu' at: {d['header_at']}")
                    print(f"\n=== 1000 chars after column headers ===")
                    print(d["after"])
                except Exception:
                    print(val)
                break


asyncio.run(check())
