"""One refresh that never finishes must not hold up every refresh after it.

The refresh pump deliberately has no deadline: a slow answer is usually the
server doing useful composition, and abandoning it only makes the server do
the same expensive work again. The measured history behind that decision is in
``building/HANDOVER_codex_storm_bake_and_client_staleness.md``. But "no
deadline" must not mean "no liveness": a request that will genuinely never
finish — a stalled socket, a server thread wedged behind a lock — is rare and
real, and an earlier pump serialized whole batches of refreshes, so one such
request quietly starved every later refresh for its source, forever, while
the pump reported itself healthy.

The cure is one flight per chunk, not one batch per source: a stuck chunk
stalls only itself, and every other chunk keeps refreshing around it. This
test holds that promise in place with the real machinery: a real server, a
real browser, and one chunk whose reply is deliberately held open while
another chunk's refresh must still get through.

The scenario reads like this: two positions land, each dirtying its own piece
of the picture. The server is told to hold the reply for the FIRST piece open
indefinitely. The announcement for the first piece therefore starts a refresh
that cannot finish. Then the second position lands and is announced. Under
the old batch pump the second refresh would wait behind the first until the
end of time; under per-key flights it must complete — the second piece's
fresh pixels must reach the screen while the first request is still hanging.
Finally the hold is released, and the first piece's refresh must finish too,
because it was never abandoned, only slow.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

_VIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_VIZ / "building"))

import os  # noqa: E402

import measure_a_governed_run_at_scale as harness  # noqa: E402
import server as server_module  # noqa: E402
from declare import declare_a_governed_picture  # noqa: E402
from server import make_server  # noqa: E402

# The announcement helper and the dirty-footprint arithmetic are the storm
# gate's own, imported rather than copied: which pieces a landing touches
# depends on the profile's per-level downsampling and the frame's full
# footprint, and a simplified re-derivation of it in this file named pieces
# the page never held -- so nothing was requested and the test could not even
# begin. One implementation, shared, kept honest by the gate that uses it
# hardest.
from test_a_commit_storm_under_zooming import _announce, _dirty_for  # noqa: E402

# How long to give the second refresh to arrive while the first hangs, in
# seconds. Generous on purpose: the point is not speed but independence, and
# a slow machine must not turn independence into a flake. Under the old batch
# pump this wait would time out however long it was, because the second
# refresh sat behind a request that never returns at all.
INDEPENDENT_REFRESH_WITHIN_S = 30.0

# How long the held request is allowed to keep hanging after everything else
# is proven, before the test releases it, in seconds. It stays hanging the
# whole time; this is just how long the test chooses to watch.
HOLD_FOR_AT_LEAST_S = 2.0


def test_one_stuck_refresh_stalls_only_itself(
    browser, built_dist, tmp_path, monkeypatch
):
    """While one chunk's reply hangs forever, other chunks still refresh."""
    harness.FIXTURES = tmp_path
    # Twelve across, deliberately: at its opening overview zoom the page
    # draws the pyramid level that roughly fits the window, and only pieces
    # of levels the page actually HOLDS can be refreshed at all. On a small
    # survey that drawn level is a single piece, so the two corner landings
    # collide on it and there is nothing separate to hold. At twelve across
    # the drawn level spans a 2x2 grid of pieces, and opposite corners land
    # in different ones -- measured, not assumed, when this test first ran
    # against a six-wide survey and its held piece was simply never asked
    # for.
    across = 12
    run, order = harness.the_run(across)
    # The two landings are the survey's opposite corners, so at every level
    # fine enough to hold more than one piece their footprints are different
    # pieces -- which is what lets one hang while the other proves itself.
    # At levels coarse enough that both share a piece, that shared piece is
    # simply not held (see below), because a shared piece hanging would make
    # the two flights dependent by construction rather than by defect.
    def corner_distance(position_id: str) -> float:
        origin = run.layout.placement(position_id).origin
        return float(origin.get("y", 0)) + float(origin.get("x", 0))

    first_landing = min(order, key=corner_distance)
    second_landing = max(order, key=corner_distance)
    for position_id in order:
        if position_id not in (first_landing, second_landing):
            harness.fast_publish(run, position_id)

    shown = run.folder / "views" / "shown"
    store = declare_a_governed_picture(shown, run.folder, name="live",
                                       bake=True)
    pictured = len(json.loads((store / "zarr.json").read_text(
        encoding="utf-8"))["attributes"]["ome"]["multiscales"][0]["datasets"])

    first_dirty = _dirty_for(run, pictured, first_landing)
    second_dirty = _dirty_for(run, pictured, second_landing)

    # Which pieces to hold and which to watch is decided LATE, after the
    # page has been zoomed and asked what it actually holds -- an earlier
    # draft chose them from the dirty arithmetic alone, and learnt the hard
    # way that at the opening overview zoom the page draws a level small
    # enough to be a single piece, which both corners share. The server
    # handler therefore reads these sets through this mutable holder, so
    # they can be filled in once the right level is known.
    chosen: dict = {"held": set(), "watch": set()}

    hold = threading.Event()
    release = threading.Event()
    held_requests = {"count": 0}
    ordinary_serve = server_module._Handler._serve_from_data

    def serve_holding_one_corner(handler) -> None:
        if hold.is_set() and any(handler.path.endswith(one)
                                 for one in chosen["held"]):
            held_requests["count"] += 1
            # Hang exactly as a wedged server would: no status line, no
            # body, the socket simply stays open until the test releases
            # it. The client's request has no deadline of its own -- that
            # is the design under test -- so nothing rescues it but us.
            release.wait(timeout=120)
        ordinary_serve(handler)

    monkeypatch.setattr(
        server_module._Handler, "_serve_from_data", serve_holding_one_corner)

    site = Path(os.environ.get("ZMART_STORM_BUILT_DIST", built_dist))
    server = make_server(port=0, data_dir=shown, site_dir=site,
                         store=[store.name], window=harness.BRIGHT, live=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1000, "height": 780})
    try:
        port = server.server_address[1]
        page.add_init_script("globalThis.zmartLiveCheckMs = 150")
        page.goto(f"http://127.0.0.1:{port}", wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartViewer !== undefined",
                              timeout=60_000)
        page.wait_for_function("() => window.zmartSourcesWaiting() === 0",
                              timeout=90_000)
        page.wait_for_timeout(2_500)

        # Only pieces of levels the page actually HOLDS can be refreshed at
        # all, and which pyramid level that is depends on the zoom. So the
        # page is zoomed in until, by its own account, it holds the two
        # corners' pieces of some level as two DIFFERENT chunks. Asked, not
        # assumed: the page lists what every drawn source holds, the sources
        # are laid into a pyramid by their extents exactly the way the
        # engine's own delivery does it, and a level qualifies when both
        # corners' pieces are present and distinct.
        what_is_held = """() => {
          const groups = new Map();
          for (const [, held] of window.zmartViewer.chunkManager.rpc.objects) {
            if (!held || !(held.chunks instanceof Map)) continue;
            if (!held.spec || !held.spec.upperVoxelBound) continue;
            const bound = Array.from(held.spec.upperVoxelBound).join(",");
            if (!groups.has(bound)) groups.set(bound, new Set());
            for (const key of held.chunks.keys()) groups.get(bound).add(key);
          }
          const extent = (bound) => bound.split(",").reduce(
            (all, one) => all * Math.max(1, Number(one)), 1);
          return [...groups.entries()]
            .sort((a, b) => extent(b[0]) - extent(a[0]))
            .map(([, keys]) => [...keys]);
        }"""
        opening_zoom = page.evaluate(
            "() => window.zmartViewer.navigationState.zoomFactor.value")

        def zoom_to(multiple: float) -> None:
            page.evaluate(
                "(wanted) => {"
                "  const state = window.zmartViewer.navigationState;"
                "  state.zoomFactor.value = wanted;"
                "  const position = state.position;"
                "  const space = position.coordinateSpace.value;"
                "  if (!space?.rank) return;"
                "  const moved = Float32Array.from(position.value);"
                "  for (let axis = 0; axis < space.rank; axis += 1) {"
                "    const low = space.bounds.lowerBounds[axis];"
                "    const high = space.bounds.upperBounds[axis];"
                "    if (Number.isFinite(low) && Number.isFinite(high)) {"
                "      moved[axis] = (low + high) / 2;"
                "    }"
                "  }"
                "  position.value = moved;"
                "}",
                opening_zoom * multiple,
            )

        def key_of(piece: list) -> str:
            plane, row, column = piece
            return f"{column},{row},{plane}"

        qualifying_level = None
        for multiple in (0.5, 0.35, 0.7, 0.25, 1.0):
            zoom_to(multiple)
            page.wait_for_timeout(2_000)
            held_by_level = page.evaluate(what_is_held)
            for level in range(min(len(held_by_level), pictured)):
                mine = {key_of(piece)
                        for piece in first_dirty.get(str(level), [])}
                theirs = {key_of(piece)
                          for piece in second_dirty.get(str(level), [])}
                keys = set(held_by_level[level])
                if (mine - theirs) & keys and (theirs - mine) & keys:
                    qualifying_level = level
                    break
            if qualifying_level is not None:
                break
        assert qualifying_level is not None, (
            "no zoom made the page hold the two corners' pieces of one level "
            "as different chunks, so their refreshes cannot be told apart on "
            "this machine and the question cannot be asked"
        )
        level_name = str(qualifying_level)
        shared = ({tuple(one) for one in first_dirty[level_name]}
                  & {tuple(one) for one in second_dirty[level_name]})
        chosen["held"] = {
            f"/{level_name}/c/{piece[0]}/{piece[1]}/{piece[2]}"
            for piece in first_dirty[level_name]
            if tuple(piece) not in shared
        }
        chosen["watch"] = {
            f"/{level_name}/c/{piece[0]}/{piece[1]}/{piece[2]}"
            for piece in second_dirty[level_name]
            if tuple(piece) not in shared
        }
        hold.set()

        # Count the finished piece responses so "the second refresh got
        # through" is measured at the wire, not inferred from pixels -- the
        # two landings may sit at the survey's edge where a screenshot at
        # this zoom would barely register them.
        finished: list[str] = []
        page.on("requestfinished",
                lambda asked: finished.append(asked.url)
                if "/c/" in asked.url else None)

        # The first landing is announced while its piece of the qualifying
        # level is held. Its refresh starts and cannot finish.
        harness.fast_publish(run, first_landing)
        _announce(port, first_dirty)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not held_requests["count"]:
            page.wait_for_timeout(100)
        assert held_requests["count"], (
            "the held piece was never requested, so the stuck flight this "
            "test needs never came into being -- the announcement may not "
            "have reached the page"
        )

        # Now the second landing arrives. Its pieces share a source with the
        # held piece at every level, which is the whole point: under the old
        # batch pump they would queue behind the hanging request.
        finished.clear()
        harness.fast_publish(run, second_landing)
        _announce(port, second_dirty)
        deadline = time.monotonic() + INDEPENDENT_REFRESH_WITHIN_S
        arrived = None
        while time.monotonic() < deadline:
            arrived = next((one for one in finished
                            if any(one.endswith(suffix)
                                   for suffix in chosen["watch"])), None)
            if arrived:
                break
            page.wait_for_timeout(200)
        assert arrived, (
            "none of the second landing's own pieces were fetched within "
            f"{INDEPENDENT_REFRESH_WITHIN_S:.0f} seconds while one unrelated "
            "request hung -- one stuck refresh is starving the refreshes "
            "behind it, which is exactly the batch-barrier behaviour the "
            "per-key pump exists to prevent"
        )

        # The stuck request must still be stuck -- the point was never that
        # it fails, only that it does not take anyone down with it.
        page.wait_for_timeout(int(HOLD_FOR_AT_LEAST_S * 1000))

        # Released, the slow answer completes: slow was never abandoned.
        finished.clear()
        hold.clear()
        release.set()
        deadline = time.monotonic() + 30
        arrived = None
        while time.monotonic() < deadline:
            arrived = next((one for one in finished
                            if any(one.endswith(suffix)
                                   for suffix in chosen["held"])), None)
            if arrived:
                break
            page.wait_for_timeout(200)
        assert arrived, (
            "after the hold was released the first piece's refresh never "
            "completed -- a slow answer is supposed to be delivered late, "
            "not dropped"
        )
    finally:
        release.set()
        page.close()
        server.shutdown()
        thread.join(timeout=5)
