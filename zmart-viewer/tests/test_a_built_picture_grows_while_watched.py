"""A block landing in a watched built picture appears without being asked for.

The fault this pins was found by an operator, twice, before it was understood
once: a built picture served live, growing block by block, and the growth
invisible from where they stood — in the flat view and the volume view alike —
while a reload showed everything. Every plane was frozen at whatever moment it
was first visited; only navigation, which asks fresh questions, ever showed a
landed block.

What it turned out to be is almost embarrassing, which is exactly why it needs
a gate: the announcement endpoint reads the microscope-side word
``wrote_image_in_place``, and the announcing script sent the page-side word it
had seen in the frontend. The endpoint answered politely, told every open
page "something changed", and no page ever heard the one detail — written in
place — that makes it let go of what it has decoded. Two plausible server-side
mechanisms were designed, one was fully built, and this test then proved the
repository innocent of both: with the right word on the wire, the whole chain
— announce, let go, refetch, recompose, replace in place — works as shipped,
404-branded empty ground included.

So this gate drives the whole chain in a real browser: open the picture, hold
perfectly still, land a block in ground already on screen, and require it to
appear with no navigation, no reload, and no help — and then require the held
page to show no less than a freshly reloaded one, so F5 can never quietly
become a repair tool again.
"""
from __future__ import annotations

import io
import json
import sys
import threading
import urllib.request
from pathlib import Path

import numpy as np

VIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(VIZ / "app" / "picture"))

import served  # noqa: E402
from declare import declare_a_built_picture  # noqa: E402
from PIL import Image  # noqa: E402
from test_a_transfer_is_built_into_one_picture import PIECE, STEP_UM, _write_a_tile  # noqa: E402

sys.path.insert(0, str(VIZ / "app" / "server"))
from server import make_server  # noqa: E402


def _lit_fraction(shot: bytes) -> float:
    """How much of a screenshot holds picture rather than background."""
    grey = np.asarray(Image.open(io.BytesIO(shot)).convert("L"))
    return float((grey > 40).mean())


def _announced(port: int) -> int:
    # The wire word is the microscope-side one, ``wrote_image_in_place`` --
    # the page-side ``imageWrittenInPlace`` is what the broadcast becomes,
    # not what the endpoint reads. Sending the page's word here is a silent
    # no-op that cost a real evening: every announcement answered, nothing
    # ever refreshed.
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/announce",
        data=json.dumps({"wrote_image_in_place": True}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=5) as answer:
        return json.load(answer).get("told", 0)


def test_a_landing_appears_at_a_held_view(browser, built_dist, tmp_path):
    """Held view, hands off: a landed block must appear on its own."""
    transfer = tmp_path / "transfer"
    transfer.mkdir()
    # Three of four tiles: both far corners are down, so the picture's shape
    # is already final and the missing tile's ground is on screen from the
    # first frame -- asked about, answered, and held. Exactly the ground the
    # 404 branded unaskable.
    for number, (row, column) in [(0, (0, 0)), (2, (1, 0)), (3, (1, 1))]:
        _write_a_tile(transfer / f"Tile{number}.ome.zarr", number,
                      (row * STEP_UM, column * STEP_UM))
    shown = tmp_path / "shown"
    picture = declare_a_built_picture(shown, transfer, name="grown",
                                      piece=PIECE)
    server = make_server(port=0, data_dir=shown, site_dir=built_dist,
                         store=[picture.name], window=(0.0, 4000.0), live=True)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    page = browser.new_page(viewport={"width": 800, "height": 700})
    try:
        page.goto(f"http://127.0.0.1:{port}", wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartViewer !== undefined",
                               timeout=30_000)
        # Settled: every piece the view needs has been asked and answered.
        page.wait_for_function(
            """() => {
              const v = window.zmartViewer;
              let needed = 0, available = 0;
              for (const managed of v.layerManager.managedLayers)
                for (const rl of (managed.layer && managed.layer.renderLayers) || []) {
                  const p = rl.layerChunkProgressInfo;
                  if (p) { needed += p.numVisibleChunksNeeded;
                           available += p.numVisibleChunksAvailable; }
                }
              return needed > 0 && available >= needed;
            }""", timeout=30_000)
        page.wait_for_timeout(1_500)
        before = _lit_fraction(page.screenshot())

        _write_a_tile(transfer / "Tile1.ome.zarr", 1, (0.0, STEP_UM))
        declare_a_built_picture(shown, transfer, name="grown", piece=PIECE)
        assert _announced(port) == 1, "the page under test heard nothing"

        # Hands off from here: no navigation, no reload, no evaluate that
        # could nudge the engine. The landing has fifteen seconds -- an age
        # against the bound the flat picture holds -- to appear on its own.
        grown = before
        for _ in range(30):
            page.wait_for_timeout(500)
            grown = _lit_fraction(page.screenshot())
            if grown > before * 1.15:
                break
        assert grown > before * 1.15, (
            f"a block landed in watched ground and never appeared: the view "
            f"lit {before:.1%} before and {grown:.1%} after fifteen seconds. "
            f"A reload would show it -- which is the fault, not the fix."
        )

        # The stricter half, the operator's own instrument: what the held
        # page shows must be what a reload shows. F5 is the gold standard --
        # one coherent ask of everything -- and the moment it reveals MORE
        # than the warm page, the warm page was stale and the operator is
        # back to reloading as a repair tool.
        warm = np.asarray(Image.open(io.BytesIO(page.screenshot())).convert("L"))
        page.reload(wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartViewer !== undefined",
                               timeout=30_000)
        page.wait_for_function(
            """() => {
              const v = window.zmartViewer;
              let needed = 0, available = 0;
              for (const managed of v.layerManager.managedLayers)
                for (const rl of (managed.layer && managed.layer.renderLayers) || []) {
                  const p = rl.layerChunkProgressInfo;
                  if (p) { needed += p.numVisibleChunksNeeded;
                           available += p.numVisibleChunksAvailable; }
                }
              return needed > 0 && available >= needed;
            }""", timeout=30_000)
        page.wait_for_timeout(1_500)
        fresh = np.asarray(Image.open(io.BytesIO(page.screenshot())).convert("L"))
        warm_lit = float((warm > 40).mean())
        fresh_lit = float((fresh > 40).mean())
        assert warm_lit >= fresh_lit - 0.02, (
            f"the reload revealed ground the held page was not showing: "
            f"warm {warm_lit:.1%} lit against fresh {fresh_lit:.1%} -- "
            f"stale pieces, the exact fault this gate exists to hold shut."
        )
    finally:
        page.close()
        server.shutdown()
        served.forget(picture)
