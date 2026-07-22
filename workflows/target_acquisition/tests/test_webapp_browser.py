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
import time
from contextlib import contextmanager

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


@contextmanager
def _playwright():
    """Skip cleanly when Playwright is only partially installed."""
    try:
        from playwright._impl._driver import compute_driver_executable

        compute_driver_executable()
    except Exception as exc:  # pragma: no cover - environment-specific
        pytest.skip(f"Playwright driver is unavailable: {exc}")
    manager = playwright_api.sync_playwright()
    try:
        pw = manager.start()
    except Exception as exc:  # pragma: no cover - environment-specific
        pytest.skip(f"Playwright driver is unavailable: {exc}")
    try:
        yield pw
    finally:
        # ``sync_playwright().start()`` hands back the running Playwright
        # object; stopping THAT is what shuts the driver down. (The context
        # manager itself has no ``stop`` — calling it there raised and
        # masked the test's real failure.)
        pw.stop()


def test_an_operator_can_click_through_the_whole_demo_run(demo_server, tmp_path):
    base, hub, flow = demo_server
    with _playwright() as pw:
        browser = _launch_browser(pw)
        page = browser.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        # Disconnect asks "are you sure?" — accept it, as an operator ending
        # the session would.
        page.on("dialog", lambda dialog: dialog.accept())
        # networkidle never comes: the live event stream stays open by design.
        # Buttons enable only after the state snapshot applied, so waiting
        # for an ENABLED button is waiting for the page to be truly ready.
        page.goto(base, wait_until="domcontentloaded")
        page.wait_for_selector('button[data-step="connect"]:enabled', timeout=30_000)

        # The page is operator language, not code.
        assert "ZMART-microscopy: Target acquisition" in page.content()
        playwright_api.expect(page.locator("#demo-banner")).to_be_visible(timeout=10_000)

        for step in _STEP_ORDER:
            page.click(f'button[data-step="{step}"]')
            page.wait_for_selector(f"#note-{step}.ok", timeout=30_000)

        # The focus widget mounted after load_positions; press ITS button.
        focus = page.locator("#widget-focus")
        focus.locator('button:has-text("Measure focus")').first.click(timeout=30_000)
        page.wait_for_selector('#widget-focus :text("focus surface fitted")', timeout=60_000)

        page.locator("#step-run_overview > summary").click()
        page.click('button[data-step="run_overview"]')
        page.wait_for_selector("#note-run_overview.ok", timeout=120_000)
        # The live map really shows tiles, streamed as binary and mounted
        # as object URLs — the notebook's streaming path, in a plain page.
        # (to_have_count retries: images keep arriving for a moment after
        # the step reports done, exactly like the live notebook.)
        playwright_api.expect(page.locator('#widget-overview img[src^="blob:"]')).to_have_count(
            4, timeout=30_000
        )
        # A replay whose binary buffers have expired must retain the good
        # object URLs already on screen and explain the failed refresh.
        images = page.locator('#widget-overview img[src^="blob:"]')
        previous_sources = images.evaluate_all("els => els.map((el) => el.src)")
        page.route("**/buffer/*", lambda route: route.fulfill(status=404, body="expired"))
        response = page.request.post(
            base + "/msg", data={"widget": "overview", "content": {"type": "sync"}}
        )
        assert response.ok
        page.wait_for_selector('#widget-overview :text("previous copy was kept")', timeout=30_000)
        assert images.evaluate_all("els => els.map((el) => el.src)") == previous_sources
        page.unroute("**/buffer/*")

        page.locator("#step-discover_targets > summary").click()
        page.click('button[data-step="discover_targets"]')
        page.wait_for_selector("#note-discover_targets.ok", timeout=120_000)
        page.wait_for_selector("#widget-explorer svg", timeout=30_000)

        page.locator("#step-gallery > summary").click()
        gallery = page.locator("#widget-gallery")
        gallery.locator("input").first.fill("2")
        gallery.locator('button:has-text("Acquire")').first.click()
        playwright_api.expect(gallery.locator('img[src^="blob:"]')).to_have_count(
            4, timeout=120_000
        )  # 2 pairs
        gallery.locator('button:has-text("✓")').first.click()

        page.locator("#step-save_results > summary").click()
        page.click('button[data-step="save_results"]')
        page.wait_for_selector("#note-save_results.ok", timeout=60_000)
        page.click('button[data-step="disconnect"]')
        page.wait_for_selector("#note-disconnect.ok", timeout=30_000)

        page.screenshot(path=str(tmp_path / "webapp.png"), full_page=True)
        browser.close()

    assert not errors, f"the page threw in the browser: {errors}"
    assert flow.gallery._verdicts[0] == "good"
    assert flow.root.parent == tmp_path / "run"
    assert (flow.root / "curation.json").exists()
    assert flow.session.disconnected and flow.engine.shut_down


def test_a_fresh_tab_opened_mid_run_recovers_the_overview_images(demo_server):
    """A tab first opened after the scan already ran must not be blank.

    Tile pixels travel only over the live stream, never in the /state
    snapshot, so a fresh page (or a second tab) has to ask for the image
    catch-up. Without that it renders tile metadata with no pictures.
    """
    base, hub, flow = demo_server
    for step in _STEP_ORDER:
        flow.run_step(step)
    hub.drain(60)
    hub.dispatch_message("focus", {"type": "measure"})
    flow.run_step("run_overview")
    hub.drain(120)

    with _playwright() as pw:
        browser = _launch_browser(pw)
        # A brand-new page — everConnected starts false, i.e. NOT a reconnect.
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        page.goto(base, wait_until="domcontentloaded")
        page.wait_for_selector("#step-run_overview.done", timeout=30_000)
        page.locator("#step-run_overview > summary").click()
        # The four overview tiles must actually arrive as images.
        playwright_api.expect(page.locator('#widget-overview img[src^="blob:"]')).to_have_count(
            4, timeout=30_000
        )
        browser.close()


def test_live_event_wins_over_an_older_boot_snapshot(demo_server):
    """A new tab must not lose busy/cancel truth while /state is in flight."""
    base, hub, flow = demo_server
    for step in _STEP_ORDER:
        flow.run_step(step)
    hub.drain(60)
    hub.dispatch_message("focus", {"type": "measure"})
    flow.run_step("run_overview")
    flow.run_step("discover_targets")
    hub.drain(120)

    snapshot_captured = threading.Event()
    release_snapshot = threading.Event()
    original_snapshot = hub.state_snapshot
    delayed_once = False

    def _delayed_snapshot():
        nonlocal delayed_once
        snapshot = original_snapshot()  # captures busy=False
        if not delayed_once:
            delayed_once = True
            snapshot_captured.set()
            assert release_snapshot.wait(30)
        return snapshot

    hub.state_snapshot = _delayed_snapshot

    def _start_run_during_snapshot():
        assert snapshot_captured.wait(30)
        flow.gallery._set_busy(True)
        release_snapshot.set()

    mutation = threading.Thread(target=_start_run_during_snapshot, daemon=True)
    mutation.start()
    with _playwright() as pw:
        browser = _launch_browser(pw)
        page = browser.new_page()
        page.goto(base, wait_until="domcontentloaded")
        gallery = page.locator("#widget-gallery")
        playwright_api.expect(gallery.locator('button:has-text("Cancel")')).to_be_visible(
            timeout=30_000
        )
        assert flow.gallery.busy is True
        flow.gallery._set_busy(False)
        browser.close()
    mutation.join(timeout=30)
    assert not mutation.is_alive()


def test_rapid_local_edits_are_not_built_from_stale_browser_state(demo_server):
    """Two focus clicks inside one worker round trip must both survive."""
    base, hub, flow = demo_server
    with _playwright() as pw:
        browser = _launch_browser(pw)
        page = browser.new_page()
        page.goto(base, wait_until="domcontentloaded")
        page.wait_for_selector('button[data-step="connect"]:enabled', timeout=30_000)
        for step in _STEP_ORDER[:-1]:
            page.click(f'button[data-step="{step}"]')
            page.wait_for_selector(f"#note-{step}.ok", timeout=30_000)

        dynamic_snapshots = 0

        def fail_dynamic_snapshot_once(route):
            nonlocal dynamic_snapshots
            dynamic_snapshots += 1
            if dynamic_snapshots == 1:
                route.abort()
            else:
                route.continue_()

        page.route("**/state", fail_dynamic_snapshot_once)
        step = _STEP_ORDER[-1]
        page.click(f'button[data-step="{step}"]')
        page.wait_for_selector(f"#note-{step}.ok", timeout=30_000)

        focus_svg = page.locator("#widget-focus svg")
        playwright_api.expect(focus_svg).to_be_visible(timeout=30_000)
        assert dynamic_snapshots >= 2
        page.unroute("**/state")
        focus_svg.scroll_into_view_if_needed()
        box = focus_svg.bounding_box()
        assert box is not None
        started = threading.Event()
        release = threading.Event()

        def block_worker():
            started.set()
            assert release.wait(30)

        assert hub.submit(block_worker)
        assert started.wait(10)
        try:
            page.mouse.click(box["x"] + 150, box["y"] + 150)
            # Let React render the first local event, but keep Python blocked so
            # neither click can rely on the server echo.
            page.wait_for_timeout(100)
            page.mouse.click(box["x"] + 450, box["y"] + 300)
            playwright_api.expect(
                page.locator("#widget-focus").get_by_text("5 point(s)", exact=True)
            ).to_be_visible(timeout=10_000)
        finally:
            release.set()
        hub.drain(30)
        assert len(flow.picker.points) == 5
        browser.close()


def test_failed_first_snapshot_retries_and_unwedges_the_page(demo_server):
    base, _hub, _flow = demo_server
    with _playwright() as pw:
        browser = _launch_browser(pw)
        page = browser.new_page()
        attempts = 0

        def fail_once(route):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                route.abort()
            else:
                route.continue_()

        page.route("**/state", fail_once)
        page.goto(base, wait_until="domcontentloaded")
        page.wait_for_selector('button[data-step="connect"]:enabled', timeout=30_000)
        assert attempts >= 2
        page.click('button[data-step="connect"]')
        page.wait_for_selector("#note-connect.ok", timeout=30_000)
        browser.close()


def test_explorer_lasso_ignores_slips_and_commits_real_drags(demo_server):
    base, hub, flow = demo_server
    for step in _STEP_ORDER:
        flow.run_step(step)
    hub.drain(60)
    hub.dispatch_message("focus", {"type": "measure"})
    flow.run_step("run_overview")
    flow.run_step("discover_targets")
    hub.drain(120)

    with _playwright() as pw:
        browser = _launch_browser(pw)
        # The explorer plot is 1150x900; mouse drags only land inside the
        # viewport, so use one that shows the whole plot (as a run PC does).
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        page.goto(base, wait_until="domcontentloaded")
        # Wait for the boot snapshot to lay the page out (it marks completed
        # sections done) — a summary click before that would be undone by the
        # boot layout folding completed sections.
        page.wait_for_selector("#step-discover_targets.done", timeout=30_000)
        page.locator("#step-discover_targets > summary").click()
        svg = page.locator("#widget-explorer svg")
        playwright_api.expect(svg).to_be_visible(timeout=30_000)
        svg.scroll_into_view_if_needed()
        box = svg.bounding_box()
        assert box is not None
        # Choose a genuine SVG-background point, away from every target dot,
        # so the dot's intentional pointerdown stop is tested independently.
        start = svg.evaluate(
            """svg => {
              const dots = [...svg.querySelectorAll('circle')].map((c) =>
                [Number(c.getAttribute('cx')), Number(c.getAttribute('cy'))]);
              for (let y = 60; y <= 280; y += 20)
                for (let x = 60; x <= 400; x += 20)
                  if (dots.every(([cx, cy]) => Math.hypot(x - cx, y - cy) > 14)) return [x, y];
              return [70, 70];
            }"""
        )
        x, y = box["x"] + start[0], box["y"] + start[1]

        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x + 2, y + 1, steps=3)
        page.mouse.up()
        hub.drain()
        assert flow.explorer.gate.get("lasso") is None

        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x + 80, y, steps=5)
        page.mouse.move(x + 80, y + 80, steps=5)
        page.mouse.move(x, y + 80, steps=5)
        page.mouse.up()
        page.wait_for_selector("#widget-explorer svg polygon", timeout=10_000)
        deadline = time.monotonic() + 10
        while not flow.explorer.gate.get("lasso") and time.monotonic() < deadline:
            time.sleep(0.01)
        hub.drain()
        assert len(flow.explorer.gate.get("lasso") or []) >= 3
        browser.close()
