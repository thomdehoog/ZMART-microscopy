"""The web interface in a REAL browser: Chromium clicks through the demo run.

This is the closest test to an operator at the microscope PC: a headless
Chromium loads the page, presses every step button in order, presses
Measure and Acquire inside the actual React widgets, judges a pair, and
saves. It proves the whole seam — page ↔ event stream ↔ widget host ↔
simulated microscope — not just the Python halves.

Entirely optional: it skips unless the ``playwright`` package (and a
Chromium it can find) is available. The suite's coverage of the web
interface does not depend on it — ``test_webapp.py`` tests the same
layers headlessly — so CI without a browser loses breadth, not truth.
"""

from __future__ import annotations

import threading

import matplotlib

matplotlib.use("Agg")

import pytest  # noqa: E402

pytest.importorskip("anywidget")
playwright_api = pytest.importorskip("playwright.sync_api")

from workflow.webapp import make_server  # noqa: E402

_STEP_ORDER = [
    "connect",
    "set_origin",
    "capture_overview_job",
    "capture_target_job",
    "load_positions",
]


@pytest.fixture()
def demo_server(tmp_path):
    server, hub, flow = make_server(port=0, demo=True, demo_root=tmp_path / "run")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", hub, flow
    finally:
        server.shutdown()
        server.server_close()


def _launch_browser(pw):
    try:
        return pw.chromium.launch()
    except Exception as first_error:  # pragma: no cover - environment-specific
        # Some machines ship one system Chromium instead of the per-version
        # download Playwright expects; use it when it is there.
        import os
        from pathlib import Path

        chromium = os.environ.get("ZMART_CHROMIUM", "/opt/pw-browsers/chromium")
        if Path(chromium).exists():
            try:
                return pw.chromium.launch(executable_path=chromium)
            except Exception:
                pass
        pytest.skip(f"no Chromium available for Playwright: {first_error}")


def test_an_operator_can_click_through_the_whole_demo_run(demo_server, tmp_path):
    base, hub, flow = demo_server
    with playwright_api.sync_playwright() as pw:
        browser = _launch_browser(pw)
        page = browser.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        # networkidle never comes: the live event stream stays open by design.
        # Buttons enable only after the state snapshot applied, so waiting
        # for an ENABLED button is waiting for the page to be truly ready.
        page.goto(base, wait_until="domcontentloaded")
        page.wait_for_selector('button[data-step="connect"]:enabled', timeout=30_000)

        # The page is operator language, not code.
        assert "ZMART target acquisition" in page.content()
        playwright_api.expect(page.locator("#demo-banner")).to_be_visible(timeout=10_000)

        for step in _STEP_ORDER:
            page.click(f'button[data-step="{step}"]')
            page.wait_for_selector(f"#note-{step}.ok", timeout=30_000)

        # The focus widget mounted after load_positions; press ITS button.
        focus = page.locator("#widget-focus")
        focus.locator('button:has-text("Measure focus")').first.click(timeout=30_000)
        page.wait_for_selector('#widget-focus :text("focus surface fitted")', timeout=60_000)

        page.click('button[data-step="run_overview"]')
        page.wait_for_selector("#note-run_overview.ok", timeout=120_000)
        # The live map really shows tiles, streamed as binary and mounted
        # as object URLs — the notebook's streaming path, in a plain page.
        # (to_have_count retries: images keep arriving for a moment after
        # the step reports done, exactly like the live notebook.)
        playwright_api.expect(page.locator('#widget-overview img[src^="blob:"]')).to_have_count(
            4, timeout=30_000
        )

        page.click('button[data-step="discover_targets"]')
        page.wait_for_selector("#note-discover_targets.ok", timeout=120_000)
        page.wait_for_selector("#widget-explorer svg", timeout=30_000)

        gallery = page.locator("#widget-gallery")
        gallery.locator("input").first.fill("2")
        gallery.locator('button:has-text("Acquire")').first.click()
        playwright_api.expect(gallery.locator('img[src^="blob:"]')).to_have_count(
            4, timeout=120_000
        )  # 2 pairs
        gallery.locator('button:has-text("✓")').first.click()

        page.click('button[data-step="save_results"]')
        page.wait_for_selector("#note-save_results.ok", timeout=60_000)
        page.click('button[data-step="disconnect"]')
        page.wait_for_selector("#note-disconnect.ok", timeout=30_000)

        page.screenshot(path=str(tmp_path / "webapp.png"), full_page=True)
        browser.close()

    assert not errors, f"the page threw in the browser: {errors}"
    assert flow.gallery._verdicts[0] == "good"
    assert (tmp_path / "run" / "curation.json").exists()
    assert flow.session.disconnected and flow.engine.shut_down
