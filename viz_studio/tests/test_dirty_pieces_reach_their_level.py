"""An announcement's dirty pieces must reach the level they name.

The surgical refresh path hands each commit's dirty piece coordinates to the
engine, keyed by resolution level, and the engine must retire exactly those
chunks of exactly those levels. Getting the LEVEL wrong is the failure this
file exists for, because it is invisible from every counter: keys are sent,
sources are touched, the announcement is accounted for — and the level that
actually changed keeps drawing what it held. An operator first met it as
black stripes over freshly-landed ground, stuck at middle zooms until a
reload, while the server answered every disputed piece fresh and complete.

The mechanism was a one-layer assumption: dirty levels were matched to chunk
sources by sorting every source in the engine's shared table by voxel extent
and indexing by level number. The moment the table holds more than one source
per level — a twin mid-refresh, or the same store opened as two datasets —
the sort interleaves them and every level below the duplicate is shifted onto
the wrong source. Opening one store twice reproduces that table shape
deterministically, with no race to lose, which is what these tests do.
"""

from __future__ import annotations

import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest

_VIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_VIZ / "building"))

import measure_a_governed_run_at_scale as harness  # noqa: E402
from declare import declare_a_governed_picture  # noqa: E402
from server import make_server  # noqa: E402


@pytest.fixture
def a_baked_survey(tmp_path):
    """A small governed survey, fully committed and baked, ready to serve."""
    harness.FIXTURES = tmp_path
    run, order = harness.the_run(4)
    for position_id in order:
        harness.fast_publish(run, position_id)
    shown = tmp_path / "gov4x4" / "shown"
    store = declare_a_governed_picture(shown, run.folder, name="live", bake=True)
    return run, shown, store


def _levels_of(store: Path) -> dict[str, list[int]]:
    """Each level's declared shape, straight from its own description."""
    shapes = {}
    for level in sorted(
        (d.name for d in store.iterdir() if d.is_dir() and (d / "zarr.json").is_file()),
        key=int,
    ):
        described = json.loads((store / level / "zarr.json").read_text(encoding="utf-8"))
        shapes[level] = list(described["shape"])
    return shapes


def _announce(port: int, dirty: dict) -> None:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/announce",
        data=json.dumps({"wrote_image_in_place": True, "dirty": dirty}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30):
        pass


def test_dirty_levels_land_on_sources_of_that_level_even_with_a_double(
    browser, built_dist, a_baked_survey
):
    """One store opened as two datasets, and every level still gets its own.

    Two datasets over one store is the deterministic stand-in for the shape
    the table has whenever more than one source per level exists — which a
    twin refresh creates on every announcement that cannot be answered
    surgically. Every delivery the engine makes must land on a source whose
    own bounds are the named level's shape; landing anywhere else is how a
    changed level goes on showing its past.
    """
    run, shown, store = a_baked_survey
    server = make_server(
        port=0,
        data_dir=shown,
        site_dir=built_dist,
        loads=[
            {"path": shown, "stores": [store.name], "name": "one"},
            {"path": shown, "stores": [store.name], "name": "two"},
        ],
        window=harness.BRIGHT,
        live=True,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1000, "height": 780})
    try:
        port = server.server_address[1]
        page.goto(f"http://127.0.0.1:{port}", wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartViewer !== undefined",
                              timeout=60_000)
        page.wait_for_function("() => window.zmartSourcesWaiting() === 0",
                              timeout=90_000)
        page.wait_for_timeout(2_000)

        shapes = _levels_of(store)
        dirty = {level: [[0, 0, 0]] for level in shapes}
        before = page.evaluate("() => window.zmartChunkInvalidation.announcements")
        _announce(port, dirty)
        page.wait_for_function(
            "(before) => window.zmartChunkInvalidation.announcements > before",
            arg=before, timeout=30_000,
        )
        delivered = page.evaluate("() => window.zmartChunkInvalidation.delivered")

        assert delivered, "nothing was delivered at all"
        for record in delivered:
            named = sorted(shapes[record["level"]])
            landed = sorted(record["bound"])
            assert landed == named, (
                f"level {record['level']} (shape {named}) was delivered to a "
                f"source whose bounds are {landed} — those chunks were retired "
                "on the wrong level, and the level that changed keeps drawing "
                "its past"
            )
        reached = {record["level"] for record in delivered}
        assert reached == set(shapes), (
            f"levels {sorted(set(shapes) - reached)} were named dirty and "
            "reached no source at all"
        )
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)
