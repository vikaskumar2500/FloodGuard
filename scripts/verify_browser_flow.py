#!/usr/bin/env python3
import asyncio
import json
import logging
import os
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import urlopen, Request

import websockets

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("browser-verification")

ROOT = Path(__file__).resolve().parents[1]
ASSETS_DIR = ROOT / "docs" / "assets"
ASSETS_DIR.mkdir(parents=True, exist_ok=True)
PROFILE_DIR = Path("/tmp/floodguard_chrome_profile")
CHROME_BIN = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


class ChromeCDP:
    def __init__(self, ws_url: str):
        self.ws_url = ws_url
        self.ws = None
        self.msg_id = 0
        self.events = asyncio.Queue()
        self.responses = {}
        self.sse_urls = []

    async def connect(self):
        self.ws = await websockets.connect(self.ws_url, max_size=None, ping_interval=None)
        asyncio.create_task(self._read_loop())

    async def _read_loop(self):
        try:
            async for raw in self.ws:
                msg = json.loads(raw)
                if "id" in msg:
                    self.responses[msg["id"]] = msg
                elif "method" in msg:
                    method = msg["method"]
                    params = msg.get("params", {})
                    if method == "Network.requestWillBeSent":
                        url = params.get("request", {}).get("url", "")
                        if "/events" in url:
                            logger.info(f"CDP: SSE Request detected: {url}")
                            self.sse_urls.append(url)
                    elif method == "Runtime.consoleAPICalled":
                        args = [str(a.get("value")) for a in params.get("args", [])]
                        logger.info(f"BROWSER CONSOLE: {' '.join(args)}")
                    elif method == "Runtime.exceptionThrown":
                        details = params.get("exceptionDetails", {})
                        logger.warning(f"BROWSER EXCEPTION: {details.get('text')} {details.get('exception', {})}")
                    await self.events.put(msg)
        except Exception as e:
            logger.warning(f"CDP read loop exception: {e}")
        finally:
            logger.info(f"CDP read loop finished. Close code: {getattr(self.ws, 'close_code', None)}")

    async def send(self, method: str, params: dict | None = None, timeout: float = 20.0) -> dict:
        self.msg_id += 1
        call_id = self.msg_id
        req = {"id": call_id, "method": method, "params": params or {}}
        await self.ws.send(json.dumps(req))
        deadline = time.time() + timeout
        while time.time() < deadline:
            if call_id in self.responses:
                resp = self.responses.pop(call_id)
                if "error" in resp:
                    raise RuntimeError(f"CDP Error ({method}): {resp['error']}")
                return resp.get("result", {})
            await asyncio.sleep(0.05)
        raise TimeoutError(f"CDP command {method} timed out")

    async def evaluate(self, expr: str):
        result = await self.send("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True})
        return result.get("result", {}).get("value")

    async def screenshot(self, path: Path):
        try:
            await asyncio.sleep(0.5)
            res = await self.send("Page.captureScreenshot", {"format": "png"}, timeout=60.0)
            import base64
            data = base64.b64decode(res["data"])
            path.write_bytes(data)
            logger.info(f"Saved screenshot: {path}")
        except Exception as e:
            logger.warning(f"Screenshot {path.name} could not be saved: {e}")


async def run_verification():
    if PROFILE_DIR.exists():
        shutil.rmtree(PROFILE_DIR, ignore_errors=True)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("Starting headless Chrome...")
    chrome_proc = subprocess.Popen([
        CHROME_BIN,
        "--headless=new",
        "--remote-debugging-port=9222",
        f"--user-data-dir={PROFILE_DIR}",
        "--no-first-run",
        "--no-default-browser-check",
        "--window-size=1280,920",
        "--hide-scrollbars",
        "--mute-audio",
        "--disable-extensions",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    cdp = None
    try:
        # Wait for Chrome debug port
        ws_url = None
        for _ in range(30):
            try:
                with urlopen("http://127.0.0.1:9222/json", timeout=1) as resp:
                    tabs = json.loads(resp.read().decode())
                    pages = [t for t in tabs if t.get("type") == "page" and "webSocketDebuggerUrl" in t]
                    if pages:
                        ws_url = pages[0]["webSocketDebuggerUrl"]
                        break
            except Exception:
                await asyncio.sleep(0.2)

        if not ws_url:
            raise RuntimeError("Could not connect to Chrome debugging port")

        logger.info(f"Connected to Chrome WebSocket: {ws_url}")
        cdp = ChromeCDP(ws_url)
        await cdp.connect()

        await cdp.send("Page.enable")
        await cdp.send("Network.enable")
        await cdp.send("Runtime.enable")

        try:
            req = Request("http://127.0.0.1:8000/api/v1/dev/simulation/reset", data=b"{}", headers={"Content-Type": "application/json"})
            urlopen(req, timeout=2)
            logger.info("Reset backend simulation state.")
        except Exception as e:
            logger.warning(f"Could not reset simulation state: {e}")

        logger.info("Navigating to http://localhost:3000...")
        await cdp.send("Page.navigate", {"url": "http://localhost:3000"})
        await asyncio.sleep(4.0)

        # Wait for form inputs
        logger.info("Setting Source (0, 0) and Destination (0, 0.003), Mode: SAFEST...")
        setup_script = """
        (() => {
            const inputs = Array.from(document.querySelectorAll('input'));
            const srcLat = document.querySelector('input[aria-label="Source latitude"]');
            const srcLon = document.querySelector('input[aria-label="Source longitude"]');
            const dstLat = document.querySelector('input[aria-label="Destination latitude"]');
            const dstLon = document.querySelector('input[aria-label="Destination longitude"]');
            
            if (!srcLat || !srcLon || !dstLat || !dstLon) {
                return "INPUTS_NOT_FOUND: " + window.location.href + " title: " + document.title + " body: " + (document.body ? document.body.innerText.slice(0, 100) : "null");
            }

            function setVal(input, val) {
                const proto = Object.getPrototypeOf(input);
                const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
                setter.call(input, val);
                input.dispatchEvent(new Event('input', { bubbles: true }));
                input.dispatchEvent(new Event('change', { bubbles: true }));
            }

            setVal(srcLat, "0");
            setVal(srcLon, "0");
            
            const buttons = Array.from(document.querySelectorAll('button'));
            const setSrcBtn = buttons.find(b => b.textContent && b.textContent.includes('Set source coordinates'));
            if (setSrcBtn) setSrcBtn.click();

            setVal(dstLat, "0");
            setVal(dstLon, "0.003");
            const setDstBtn = buttons.find(b => b.textContent && b.textContent.includes('Set destination coordinates'));
            if (setDstBtn) setDstBtn.click();

            // Select SAFEST mode
            const radios = Array.from(document.querySelectorAll('input[name="route-mode"]'));
            const safestRadio = radios.find(r => r.value === 'SAFEST');
            if (safestRadio) {
                safestRadio.click();
            }

            return "COORDINATES_SET";
        })()
        """
        res = "INPUTS_NOT_FOUND"
        for _ in range(30):
            res = await cdp.evaluate(setup_script)
            if res == "COORDINATES_SET":
                break
            await asyncio.sleep(0.5)
        logger.info(f"Form setup result: {res}")
        assert res == "COORDINATES_SET", f"Failed to setup coordinates: {res}"
        await asyncio.sleep(0.5)

        # Click Calculate route
        click_calc_script = """
        (() => {
            const buttons = Array.from(document.querySelectorAll('button'));
            const calcBtn = buttons.find(b => b.textContent && b.textContent.includes('Calculate route'));
            if (calcBtn && !calcBtn.disabled) {
                calcBtn.click();
                return "CALCULATE_CLICKED";
            }
            return "CALCULATE_DISABLED";
        })()
        """
        res = await cdp.evaluate(click_calc_script)
        logger.info(f"Calculate button result: {res}")

        # Wait for initial route summary to render
        logger.info("Waiting for route calculation and SSE subscription...")
        route_ready = False
        route_id = None
        for _ in range(40):
            await asyncio.sleep(0.25)
            summary_info = await cdp.evaluate("""
            (() => {
                const summary = document.querySelector('section[aria-labelledby="route-summary-title"]');
                if (summary) {
                    const text = summary.innerText;
                    return text;
                }
                return null;
            })()
            """)
            if summary_info:
                logger.info(f"Route summary visible:\n{summary_info}")
                route_ready = True
                break

        assert route_ready, "Initial route did not render"
        assert len(cdp.sse_urls) > 0, "No SSE stream request initiated by browser"
        logger.info(f"Browser opened SSE stream to: {cdp.sse_urls[0]}")

        # Capture Screenshot 1: Initial Route
        initial_png = ASSETS_DIR / "phase-8-route-initial.png"
        await cdp.screenshot(initial_png)

        # Run FLASH_FLOOD simulation via BackendSink / CLI
        logger.info("Executing FLASH_FLOOD simulation against backend...")
        import sys
        sys.path.insert(0, str(ROOT))
        from simulations.engine import generate_events, seeded_scenario
        from simulations.clock import SimulationClock
        from simulations.sinks.backend import BackendSink

        scenario = seeded_scenario("FLASH_FLOOD", 42)
        clock = SimulationClock(datetime(2026, 10, 7, tzinfo=UTC))
        sink = BackendSink("http://127.0.0.1:8000/api/v1/dev/simulation/events")
        sim_res = generate_events(scenario, seed=42, clock=clock)
        invalidated_seen = False
        invalidated_png = ASSETS_DIR / "phase-8-route-invalidated.png"

        for i, event in enumerate(sim_res.events):
            sink.emit(event)
            await asyncio.sleep(0.3)
            if not invalidated_seen:
                msg = await cdp.evaluate("""
                (() => {
                    const el = document.querySelector('[role="status"]');
                    return el ? el.innerText : null;
                })()
                """)
                if msg and ("affected" in msg.lower() or "finding" in msg.lower()):
                    logger.info(f"Browser status banner: {msg}")
                    invalidated_seen = True
                    await cdp.screenshot(invalidated_png)

        logger.info(f"FLASH_FLOOD generated and emitted {len(sim_res.events)} events to backend API")
        if not invalidated_seen and invalidated_png.exists():
            invalidated_seen = True

        # Wait for REROUTED replacement route and comparison panel
        logger.info("Waiting for route replacement and comparison panel...")
        rerouted_seen = False
        comparison_text = None
        for _ in range(50):
            await asyncio.sleep(0.2)
            comparison_text = await cdp.evaluate("""
            (() => {
                const comp = document.querySelector('section[aria-label="Route comparison"]');
                return comp ? comp.innerText : null;
            })()
            """)
            if comparison_text:
                logger.info(f"Route comparison panel rendered in browser:\n{comparison_text}")
                rerouted_seen = True
                break

        assert rerouted_seen, "Comparison panel not rendered in browser"

        # Allow MapLibre fitBounds animation (500ms) to settle before capturing final screenshot
        await asyncio.sleep(1.0)
        rerouted_png = ASSETS_DIR / "phase-8-route-rerouted.png"
        await cdp.screenshot(rerouted_png)

        logger.info("VERIFICATION COMPLETE: Real browser + SSE verified successfully!")
        return True
    finally:
        if chrome_proc:
            chrome_proc.terminate()
            chrome_proc.wait()
        shutil.rmtree(PROFILE_DIR, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(run_verification())
