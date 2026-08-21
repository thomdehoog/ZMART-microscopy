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
        # Shut down through the started object. Playwright used to offer this
        # on the context manager as well, and dropped it in 1.62; asking the
        # started Playwright to stop works on every version we support.
        pw.stop()


def _open_step(page, step):
    """Make sure one step's section is expanded, however the page left it.

    Two things make this less obvious than clicking the heading. The page
    keeps the sections whose panel stays useful — the map, the cell explorer,
    the gallery — open as the run moves along, so a section may already be
    expanded, and clicking it then folds it away instead of revealing it. And
    the page may still be restoring a run in the background, which opens
    sections a moment after the page first appears; a click aimed at a closed
    section can land just after that restore opened it, and close it again.

    So wait for the restore to finish, then look before clicking, and check
    the section really ended up open.
    """
    # The demo banner is unhidden as the very last act of applying a state
    # snapshot, which makes it a reliable "the page has settled" sign.
    page.wait_for_selector("#demo-banner", state="visible", timeout=30_000)
    page.wait_for_selector(f"#step-{step}", state="attached", timeout=30_000)
    is_open = f"() => document.querySelector('#step-{step}')?.open === true"
    for _ in range(5):
        if page.evaluate(is_open):
            return
        page.locator(f"#step-{step} > summary").click()
        page.wait_for_timeout(250)
    page.wait_for_function(is_open, timeout=10_000)


def test_an_operator_can_click_through_the_whole_demo_run(demo_server, tmp_path):
    base, hub, flow = demo_server
    with _playwright() as pw:
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
        assert "ZMART-microscopy: Target acquisition" in page.content()
        playwright_api.expect(page.locator("#demo-banner")).to_be_visible(timeout=10_000)

        for step in _STEP_ORDER:
            page.click(f'button[data-step="{step}"]')
            page.wait_for_selector(f"#note-{step}.ok", timeout=30_000)

        # The focus widget mounted after load_positions; press ITS button.
        focus = page.locator("#widget-focus")
        focus.locator('button:has-text("Measure focus")').first.click(timeout=30_000)
        page.wait_for_selector('#widget-focus :text("focus surface fitted")', timeout=60_000)

        _open_step(page, "run_overview")
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

        _open_step(page, "discover_targets")
        page.click('button[data-step="discover_targets"]')
        page.wait_for_selector("#note-discover_targets.ok", timeout=120_000)
        page.wait_for_selector("#widget-explorer svg", timeout=30_000)

        _open_step(page, "gallery")
        gallery = page.locator("#widget-gallery")
        gallery.locator("input").first.fill("2")
        gallery.locator('button:has-text("Acquire")').first.click()
        playwright_api.expect(gallery.locator('img[src^="blob:"]')).to_have_count(
            4, timeout=120_000
        )  # 2 pairs
        gallery.locator('button:has-text("✓")').first.click()

        _open_step(page, "save_results")
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


def test_restoring_a_run_keeps_the_panels_worth_reading_open(demo_server):
    """Opening the page mid-run must not fold the map and the cell plot away.

    The page catches up on a run in progress by asking the server for the
    whole state — which also happens on a refresh, and whenever a widget is
    created part-way through a run. Steps that are only a button fold away
    once they are done, but the steps holding a panel the operator reads (the
    overview map, the cell explorer, the acquisition gallery) are meant to
    stay open. Closing those would take the cell plot off the screen at the
    very moment discovery finished making it.
    """
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
        page = browser.new_page()
        page.goto(base, wait_until="domcontentloaded")
        page.wait_for_selector("#demo-banner", state="visible", timeout=30_000)

        def is_open(step):
            return page.evaluate(f"() => document.querySelector('#step-{step}')?.open === true")

        # Nothing is clicked here on purpose: this is the page's own doing.
        assert is_open("run_overview"), "the overview map was folded away"
        assert is_open("discover_targets"), "the cell explorer was folded away"
        playwright_api.expect(page.locator("#widget-explorer svg")).to_be_visible(timeout=30_000)
        # A step that is only a button has no panel to read, so it still folds.
        assert not is_open("set_origin")
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
        page = browser.new_page()
        page.goto(base, wait_until="domcontentloaded")
        _open_step(page, "discover_targets")
        svg = page.locator("#widget-explorer svg")
        playwright_api.expect(svg).to_be_visible(timeout=30_000)
        # The plot is drawn larger than this window is tall, so bring its TOP
        # to the top of the view rather than merely bringing some part of it
        # into sight: the drag below is aimed at coordinates near the plot's
        # upper-left corner, and those have to be somewhere the mouse can
        # actually reach.
        svg.evaluate("el => el.scrollIntoView({ block: 'start' })")
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
        # If the plot ever scrolls out of reach again, say so plainly instead
        # of leaving a later wait to time out with no hint of the cause.
        on_screen = page.evaluate(
            "p => { const e = document.elementFromPoint(p[0], p[1]);"
            " return e ? e.tagName : null; }",
            [x, y],
        )
        assert on_screen is not None, f"the lasso start point {(x, y)} is off screen"

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
