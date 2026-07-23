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

import socket
import sys
import threading
from pathlib import Path

import pytest

_VIZ_ROOT = Path(__file__).resolve().parent.parent
_BACKEND = _VIZ_ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from demo_data import write_demo_zarr  # noqa: E402
from server import make_server  # noqa: E402

_DIST = _VIZ_ROOT / "frontend" / "dist"


@pytest.fixture(scope="session")
def viz_root() -> Path:
    return _VIZ_ROOT


@pytest.fixture(scope="session")
def built_dist() -> Path:
    """The built viewer page, or skip if the frontend has not been built."""
    if not (_DIST / "index.html").exists():
        pytest.skip(
            "frontend/dist is not built — run "
            "`npm --prefix frontend install && npm --prefix frontend run build`"
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
    server = make_server(port=0, data_dir=demo_store, site_dir=built_dist)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.fixture(scope="session")
def browser():
    """A headless Chromium with software GL, or skip if none is usable.

    Software GL is required because neuroglancer needs WebGL2 and CI machines
    have no GPU. A machine whose policy blocks the downloaded browser fails at
    launch rather than at import, so both are treated as "cannot run here".
    """
    playwright = pytest.importorskip(
        "playwright.sync_api", reason="playwright is not installed"
    )
    gl_args = ["--use-gl=angle", "--use-angle=swiftshader", "--ignore-gpu-blocklist"]
    with playwright.sync_playwright() as pw:
        try:
            launched = pw.chromium.launch(args=gl_args)
        except Exception as exc:
            pytest.skip(f"no usable Chromium: {exc}")
        try:
            yield launched
        finally:
            launched.close()


@pytest.fixture
def viewer_page(browser, live_server: str):
    """A page with the viewer booted and the demo volume fully rendered."""
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
