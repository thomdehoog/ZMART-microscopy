"""Shared fixtures for the viz-studio tests.

The backend is a set of plain modules under ``backend/`` rather than an
installed package (the tool is launched by path, not imported by consumers), so
tests put that directory on ``sys.path`` the same way ``run_demo.py`` does.

The browser-driven tests are opt-out rather than opt-in: they run wherever the
page has been built and a Chromium is available, and skip with a clear reason
where it has not. That keeps a bare checkout green while still failing loudly on
a machine that is supposed to be able to render.
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

_VIZ_ROOT = Path(__file__).resolve().parent.parent
_BACKEND = _VIZ_ROOT / "backend"

# Set this on any machine that is supposed to be able to draw — a CI runner, the
# microscope PC — and the run *fails* if the tests that look at pixels did not run,
# rather than skipping them and reporting a comfortable green.
#
# It exists because the two outcomes are indistinguishable from the outside. About
# a third of this suite opens a real browser and reads the picture it drew, and
# that third is the only part that catches the fault this project keeps meeting: a
# picture that is silently absent, with every piece fetched, every layer built, and
# the engine reporting itself perfectly content. If the browser cannot launch or
# the page was never built, all of those skip, and the run says "passed" — which is
# worse than no run at all, because somebody believes it.
#
# It is opt-in rather than the default so that a plain checkout on somebody's
# laptop still goes green without a browser, which is the promise TESTING.md makes.
REQUIRE_BROWSER = "ZMART_REQUIRE_BROWSER"

# Why the pixel tests could not run, filled in by the fixtures below as they give
# up. Collected rather than raised on the spot because the answer is only wanted
# once, at the end, and because the first fixture to give up is not necessarily the
# most useful thing to report.
_why_the_pixels_were_not_looked_at: list[str] = []
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from demo_data import write_demo_zarr  # noqa: E402
from server import make_server  # noqa: E402

_DIST = _VIZ_ROOT / "frontend" / "dist"


@pytest.fixture(scope="session")
def viz_root() -> Path:
    return _VIZ_ROOT


def _newest_source_change() -> float:
    """When the viewer's own source was last edited."""
    newest = 0.0
    for path in (_VIZ_ROOT / "frontend" / "src").rglob("*"):
        if path.is_file():
            newest = max(newest, path.stat().st_mtime)
    return newest


@pytest.fixture(scope="session")
def built_dist() -> Path:
    """The built viewer page — and a check that it was built from today's source.

    Every test that opens a browser reads the *built* page, not the source beside
    it, and the built page is not kept in the repository because it is generated.
    So it is entirely possible to edit the viewer, run the tests, and be told
    something confident and completely wrong about code that was never running.

    That is not a hypothetical. It cost this project a session: the tests for
    noticing a tile written into an open store were passing and failing against a
    bundle two days older than the source, and the conclusions drawn from them
    were nonsense in both directions.

    A missing build is a *skip*, because a machine that has never built the page
    has simply not been set up for these tests and there is nothing wrong with it.
    A build older than the source is a **failure**, because that machine is about
    to answer questions about the wrong program.
    """
    if not (_DIST / "index.html").exists():
        _why_the_pixels_were_not_looked_at.append(
            "the viewer page has not been built (frontend/dist/index.html is missing)"
        )
        pytest.skip(
            "frontend/dist is not built — run "
            "`npm --prefix frontend install && npm --prefix frontend run build`"
        )
    built = (_DIST / "index.html").stat().st_mtime
    changed = _newest_source_change()
    if changed > built:
        raise AssertionError(
            "the built viewer page is older than the source it was built from, so "
            "these tests would be measuring a program that is no longer the one in "
            "the repository. Rebuild it first:\n\n"
            "    npm --prefix frontend run build\n\n"
            f"(built {time.strftime('%H:%M:%S', time.localtime(built))}, "
            f"source last changed "
            f"{time.strftime('%H:%M:%S', time.localtime(changed))})"
        )
    return _DIST


@pytest.fixture(scope="session")
def demo_store(tmp_path_factory) -> Path:
    """A demo OME-Zarr volume, generated once for the whole session."""
    store = tmp_path_factory.mktemp("demo_store") / "demo.zarr"
    write_demo_zarr(store)
    return store.parent


@pytest.fixture(scope="session")
def live_server(built_dist: Path, demo_store: Path):
    """The real server, on a free port, serving the built page and the volume."""
    # The selection list is off unless asked for, so the shared test server asks
    # for it: most of these tests are about marking places on the image.
    server = make_server(
        port=0, data_dir=demo_store, site_dir=built_dist, allow_selection=True
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.fixture(scope="session")
def _playwright():
    """One Playwright instance for the whole session.

    Playwright's sync API allows only one live context per thread, so every
    browser the tests launch must come from this single instance rather than
    each opening its own — otherwise a second launch fails with an asyncio-loop
    error. Skips (rather than errors) where playwright is not installed.
    """
    try:
        import playwright.sync_api as pw_api
    except ImportError:
        _why_the_pixels_were_not_looked_at.append("playwright is not installed")
        pytest.skip("playwright is not installed")
    with pw_api.sync_playwright() as pw:
        yield pw


@pytest.fixture(scope="session")
def browser(_playwright):
    """A headless Chromium with software GL, or skip if none is usable.

    Software GL is required because neuroglancer needs WebGL2 and CI machines
    have no GPU. A machine whose policy blocks the downloaded browser fails at
    launch rather than at import, so both are treated as "cannot run here".
    """
    gl_args = ["--use-gl=angle", "--use-angle=swiftshader", "--ignore-gpu-blocklist"]
    try:
        launched = _playwright.chromium.launch(args=gl_args)
    except Exception as exc:
        _why_the_pixels_were_not_looked_at.append(f"no usable Chromium: {exc}")
        pytest.skip(f"no usable Chromium: {exc}")
    try:
        yield launched
    finally:
        launched.close()


@pytest.fixture(scope="session")
def gpu_browser(_playwright):
    """A Chromium left to use the machine's real graphics stack, not forced to
    software — so a test can tell whether a GPU is actually present. Shares the
    one session Playwright instance with ``browser`` to avoid a second context.
    """
    args = ["--ignore-gpu-blocklist", "--enable-gpu"]
    try:
        launched = _playwright.chromium.launch(args=args)
    except Exception as exc:
        pytest.skip(f"no usable Chromium: {exc}")
    try:
        yield launched
    finally:
        launched.close()


@pytest.fixture
def viewer_page(browser, live_server: str, demo_store: Path):
    """A page with the viewer booted and the demo volume fully rendered.

    The saved targets are cleared first. Every test here shares one demo volume,
    and targets are saved to a file beside it a moment after they change — so a
    target drawn at the end of one test can be written after its page has closed
    and still be sitting there when the next one opens. Starting from a known
    empty list keeps each test honest about what it drew itself.
    """
    sidecar = demo_store / "zmart-annotations.json"
    if sidecar.exists():
        sidecar.unlink()
    page = browser.new_page(viewport={"width": 1200, "height": 900})
    page.goto(live_server, wait_until="domcontentloaded")
    page.wait_for_function("() => window.zmartViewer !== undefined", timeout=30_000)
    page.wait_for_function(
        """() => {
          const v = window.zmartViewer;
          let needed = 0, available = 0;
          for (const managed of v.layerManager.managedLayers) {
            for (const rl of (managed.layer && managed.layer.renderLayers) || []) {
              const p = rl.layerChunkProgressInfo;
              if (p) { needed += p.numVisibleChunksNeeded; available += p.numVisibleChunksAvailable; }
            }
          }
          return available > 0 && available >= needed;
        }""",
        timeout=60_000,
    )
    try:
        yield page
    finally:
        page.close()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def pytest_sessionfinish(session, exitstatus):
    """Fail a run that never looked at a picture, where it was supposed to.

    A skipped test is not a failure, and on a bare checkout that is exactly right —
    somebody without Node or a browser has simply not set that part up, and there is
    nothing wrong with their machine. But on a machine that *is* meant to draw, the
    same skip is the suite quietly stopping doing the one thing it is here for, and
    it reports the same comfortable green either way.

    So where ``ZMART_REQUIRE_BROWSER`` is set, "the pixel tests did not run" ends the
    run as a failure and says why. Reported here rather than as a test of its own
    because the question is only answerable once everything has been tried: a browser
    that launches and then dies halfway through is worth catching too, and no check
    made at the start would see it.
    """
    if not os.environ.get(REQUIRE_BROWSER):
        return
    if not _why_the_pixels_were_not_looked_at:
        return

    reasons = "\n".join(f"  - {why}" for why in dict.fromkeys(_why_the_pixels_were_not_looked_at))
    print(
        f"\n{REQUIRE_BROWSER} is set, so this machine is supposed to be able to draw "
        "— but the tests that look at the picture did not run:\n"
        f"{reasons}\n\n"
        "About a third of this suite opens a real browser and reads the pixels it "
        "drew, and that third is the only part that catches a picture which is "
        "silently absent. A run without it reports green while never having drawn "
        "anything.\n\n"
        "Either put right whatever is listed above, or unset "
        f"{REQUIRE_BROWSER} if this machine genuinely cannot draw."
    )
    # 1 is pytest's own code for "tests failed", which is what this is: the suite
    # did not do what this machine promised it would.
    session.exitstatus = 1
