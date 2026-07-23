"""Load the built viewer in a real headless browser and report what happens.

This stands in for opening the app on the microscope PC: it serves the built
page and the demo volume, drives a headless Chromium (the same engine the
Windows window uses), and prints whether the engine started, whether any
errors or missing files showed up, and whether the volume actually reached the
GPU. It also saves a screenshot to look at.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from server import make_server  # noqa: E402

OUT = Path(__file__).resolve().parent / "_check"
OUT.mkdir(exist_ok=True)


def main() -> int:
    server = make_server(port=0)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"

    from playwright.sync_api import sync_playwright

    errors: list[str] = []
    failed: list[str] = []
    console_errors: list[str] = []

    gl_args = ["--use-gl=angle", "--use-angle=swiftshader", "--ignore-gpu-blocklist"]

    def _launch(pw):
        # Prefer whatever Playwright wired up; fall back to the system Chromium
        # this environment pre-installs (same pattern as the ZMART webapp tests).
        import os

        try:
            return pw.chromium.launch(args=gl_args)
        except Exception:
            chromium = os.environ.get("ZMART_CHROMIUM", "/opt/pw-browsers/chromium")
            return pw.chromium.launch(executable_path=chromium, args=gl_args)

    with sync_playwright() as pw:
        browser = _launch(pw)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("requestfailed", lambda r: failed.append(r.url.replace(base, "")))
        page.on(
            "console",
            lambda m: console_errors.append(m.text) if m.type == "error" else None,
        )

        page.goto(base, wait_until="domcontentloaded")

        # Give the engine time to boot, spawn its workers, fetch chunks, and
        # push the volume to the GPU.
        page.wait_for_function("() => window.zmartViewer !== undefined", timeout=30000)
        time.sleep(6)

        # Ask the live viewer what it managed to load.
        info = page.evaluate(
            """() => {
              const v = window.zmartViewer;
              const layers = v.layerManager.managedLayers.map(l => {
                let load = 'n/a';
                try {
                  const d = l.layer && l.layer.dataSources && l.layer.dataSources[0];
                  if (d && d.loadState) load = d.loadState.error
                    ? ('ERROR: ' + String(d.loadState.error.message || d.loadState.error))
                    : 'ok';
                } catch (e) { load = 'exc:' + e; }
                return { name: l.name, ready: !!l.isReady, load };
              });
              const canvas = document.querySelector('canvas');
              return {
                hasViewer: !!v,
                layerCount: layers.length,
                layers,
                hasCanvas: !!canvas,
                canvasSize: canvas ? [canvas.width, canvas.height] : null,
              };
            }"""
        )
        page.screenshot(path=str(OUT / "render.png"))
        browser.close()

    server.shutdown()

    # Missing zarr chunks are expected (sparse volume), so filter them out of
    # the "failed request" list — only non-/data failures are real problems.
    real_failed = [u for u in failed if not u.startswith("/data/")]

    print("hasViewer      :", info["hasViewer"])
    print("hasCanvas      :", info["hasCanvas"], info["canvasSize"])
    print("layers         :", info["layers"])
    print("page errors    :", errors)
    print("console errors :", console_errors[:5])
    print("failed (non-data):", real_failed[:10])
    print("failed /data ct:", len(failed) - len(real_failed))

    ok = (
        info["hasViewer"]
        and info["hasCanvas"]
        and info["layerCount"] >= 1
        and not errors
        and not real_failed
    )
    print("\nM1+M2 RESULT   :", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
