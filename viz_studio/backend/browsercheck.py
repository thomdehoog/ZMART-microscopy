"""Acceptance test: does the built viewer actually render the demo volume?

This is the automated safety net for the whole tool. It stands in for opening
the app on the microscope PC: it serves the built page and the demo volume,
drives a real headless Chromium (the same engine the Windows window uses), and
checks — strictly — that the volume is not just *loaded* but actually *rendered*:
the image chunks are fetched, decoded, and available to the GPU. That last check
is the important one: the viewer once looked fine (correct outline, scale bar)
while showing flat grey because no pixels ever loaded, and this test exists to
catch exactly that regression.

Run it after building the frontend::

    python backend/browsercheck.py

Exit codes: 0 = rendered (pass), 1 = did not render (fail), 2 = could not run
(the page is not built, or no browser is available).
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from demo_data import write_demo_zarr  # noqa: E402
from server import _DEMO_STORE, _FRONTEND_DIST, make_server  # noqa: E402

# Where the screenshot lands, and how long we allow for a cold start (the engine
# must boot, spawn its workers, fetch the chunks, and decode them).
_OUT = Path(__file__).resolve().parent / "_check"
_RENDER_TIMEOUT_S = 25.0
# Software GL so neuroglancer's WebGL2 works on a headless machine with no GPU.
_GL_ARGS = ["--use-gl=angle", "--use-angle=swiftshader", "--ignore-gpu-blocklist"]


def _launch_browser(pw):
    """Launch Chromium, falling back to the system build some machines ship.

    Playwright normally downloads its own Chromium; some environments instead
    provide one system Chromium at a known path. We try the normal way first
    and fall back, matching the pattern the main ZMART webapp tests use.
    """
    try:
        return pw.chromium.launch(args=_GL_ARGS)
    except Exception:
        chromium = os.environ.get("ZMART_CHROMIUM", "/opt/pw-browsers/chromium")
        if not Path(chromium).exists():
            raise
        return pw.chromium.launch(executable_path=chromium, args=_GL_ARGS)


def _render_progress(page) -> dict:
    """Ask the live viewer how many image chunks it needs and how many it has.

    neuroglancer only fetches the chunks needed to draw the current view, and
    reports, per image layer, how many are needed versus available. Summing
    those tells us whether pixels have actually arrived: ``available > 0`` means
    the volume is on screen, not grey.
    """
    return page.evaluate(
        """() => {
          const v = window.zmartViewer;
          let needed = 0, available = 0, layers = 0, loadError = null;
          for (const managed of v.layerManager.managedLayers) {
            const layer = managed.layer;
            layers += 1;
            const ds = layer && layer.dataSources && layer.dataSources[0];
            if (ds && ds.loadState && ds.loadState.error) {
              loadError = String(ds.loadState.error.message || ds.loadState.error);
            }
            for (const rl of (layer && layer.renderLayers) || []) {
              const p = rl.layerChunkProgressInfo;
              if (p) { needed += p.numVisibleChunksNeeded; available += p.numVisibleChunksAvailable; }
            }
          }
          const canvas = document.querySelector('canvas');
          return { layers, needed, available, loadError,
                   canvasHeight: canvas ? canvas.height : 0 };
        }"""
    )


def run_check() -> int:
    # 1. The page must be built first — a fresh checkout has no dist/.
    if not (_FRONTEND_DIST / "index.html").exists():
        print(
            "The viewer page is not built. Build it first:\n"
            "    npm --prefix frontend install && npm --prefix frontend run build"
        )
        return 2

    # 2. Make sure there is a volume to render — generate the demo one if a
    # fresh checkout has none, so the test is self-contained.
    demo = _DEMO_STORE / "demo.zarr"
    if not (demo / ".zattrs").exists():
        print("Generating the demo volume for the test...")
        write_demo_zarr(demo)

    _OUT.mkdir(exist_ok=True)
    server = make_server(port=0)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright is not installed; cannot run the render check (skipping).")
        server.shutdown()
        return 2

    page_errors: list[str] = []
    failed_requests: list[str] = []

    try:
        with sync_playwright() as pw:
            try:
                browser = _launch_browser(pw)
            except Exception as exc:  # no usable browser on this machine
                print(f"No Chromium available for the render check (skipping): {exc}")
                return 2

            page = browser.new_page(viewport={"width": 1200, "height": 900})
            page.on("pageerror", lambda e: page_errors.append(str(e)))
            page.on("requestfailed", lambda r: failed_requests.append(r.url.replace(base, "")))

            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_function("() => window.zmartViewer !== undefined", timeout=30000)

            # Poll until the volume has actually rendered (chunks available and
            # the demand satisfied), or we hit the timeout.
            deadline = time.monotonic() + _RENDER_TIMEOUT_S
            progress = _render_progress(page)
            while time.monotonic() < deadline:
                progress = _render_progress(page)
                if progress["available"] > 0 and progress["available"] >= progress["needed"]:
                    break
                if progress["loadError"]:
                    break
                time.sleep(0.5)

            page.screenshot(path=str(_OUT / "render.png"))
            browser.close()
    finally:
        server.shutdown()

    # A missing zarr chunk is normal (sparse volume), so /data 404s are not real
    # failures; anything else failing to load is.
    real_failed = [u for u in failed_requests if not u.startswith("/data/")]

    # The strict gate: the viewer booted, the canvas has real height, the layer
    # loaded without error, AND pixels actually arrived (chunks available and
    # demand met), with no page or resource errors.
    checks = {
        "viewer booted": progress["layers"] >= 1,
        "canvas has height": progress["canvasHeight"] > 0,
        "data source loaded": progress["loadError"] is None,
        "chunks rendered": progress["available"] > 0
        and progress["available"] >= progress["needed"],
        "no page errors": not page_errors,
        "no failed requests": not real_failed,
    }

    print("Render acceptance check")
    for name, passed in checks.items():
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
    print(f"  chunks needed/available: {progress['needed']}/{progress['available']}")
    if progress["loadError"]:
        print(f"  data source error: {progress['loadError']}")
    if page_errors:
        print(f"  page errors: {page_errors[:3]}")
    if real_failed:
        print(f"  failed requests: {real_failed[:5]}")

    ok = all(checks.values())
    print(f"\nRESULT: {'PASS — the volume renders' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(run_check())
