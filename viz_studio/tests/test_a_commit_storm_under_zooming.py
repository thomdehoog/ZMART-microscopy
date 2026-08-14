"""A commit storm with an operator zooming through it, gated at every level.

The ladder's recorder watches one zoom level, and every transient gate so far
inherited that blind spot. The first evening of *watching* runs grow found
what slipped through it: driving commits at ten a second while zooming left
the page holding stale pieces — black stripes over freshly-landed ground at
some zooms, sometimes whole levels of nothing — cured only by a reload, while
the server answered every disputed piece fresh. This file is the gate that
regime was missing: a real storm, a real zooming viewer, and afterwards the
picture is photographed at EVERY zoom band and each must show the survey the
server holds. The browser's console is captured too, because a thrown
exception in the chunk-delivery path kills everything after it far more
quietly than a wrong pixel.
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
from pixels import fraction_lit  # noqa: E402
from server import make_server  # noqa: E402


def _dirty_for(run, pictured: int, position_id: str) -> dict:
    origin = run.layout.placement(position_id).origin
    y, x = int(origin.get("y", 0)), int(origin.get("x", 0))
    piece = 512
    dirty = {}
    for number in range(pictured):
        deepest = min(number, len(run.profile.levels) - 1)
        rung = run.profile.level(deepest)
        extended = 2 ** (number - deepest)
        down_y = int(rung.downsampling.get("y", 1)) * extended
        down_x = int(rung.downsampling.get("x", 1)) * extended
        top, left = y // down_y, x // down_x
        bottom = (y + harness.FRAME - 1) // down_y
        right = (x + harness.FRAME - 1) // down_x
        dirty[str(number)] = [
            [0, row, column]
            for row in range(top // piece, bottom // piece + 1)
            for column in range(left // piece, right // piece + 1)
        ]
    return dirty


def _announce(port: int, dirty: dict) -> None:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/announce",
        data=json.dumps({"wrote_image_in_place": True, "dirty": dirty}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30):
        pass


@pytest.mark.xfail(
    strict=True,
    reason="reproduces the open storm-staleness finding: after ten landings a "
    "second under panning and zooming, some zoom bands show less than their "
    "own reload — the engine settles on the coarsest scale (needed==available"
    "==2 chunks) with mid-storm content and never asks again. Bounds proven "
    "correct, server proven correct, browser and GPU exonerated. When the "
    "mechanism is fixed this xfail turns to XPASS and must be removed — "
    "see the MEASURED doc's storm section.",
)
def test_every_zoom_shows_the_survey_after_a_storm_of_landings(
    browser, built_dist, tmp_path
):
    """Ten landings a second, a zooming viewer, and no level left behind."""
    harness.FIXTURES = tmp_path
    run, order = harness.the_run(6)
    width = len(str(6 - 1))
    committed_first = [one for one in order
                       if int(one[1:1 + width]) < 3]
    landing_later = [one for one in order if one not in set(committed_first)]
    for position_id in committed_first:
        harness.fast_publish(run, position_id)
    shown = tmp_path / "gov6x6" / "shown"
    store = declare_a_governed_picture(shown, run.folder, name="live", bake=True)
    pictured = len(json.loads((store / "zarr.json").read_text(
        encoding="utf-8"))["attributes"]["ome"]["multiscales"][0]["datasets"])

    server = make_server(port=0, data_dir=shown, site_dir=built_dist,
                         store=[store.name], window=harness.BRIGHT, live=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1000, "height": 780})
    # The eager check interval every demonstration runs with — the stock
    # page's ten-second rhythm coalesces the storm into a handful of quiet
    # catch-ups, and the regime under test is the loud one.
    page.add_init_script("globalThis.zmartLiveCheckMs = 150")
    troubles: list[str] = []
    page.on("console", lambda told: troubles.append(told.text)
            if told.type in ("error",) else None)
    page.on("pageerror", lambda told: troubles.append(str(told)))
    try:
        port = server.server_address[1]
        page.goto(f"http://127.0.0.1:{port}", wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartViewer !== undefined",
                              timeout=60_000)
        page.wait_for_function("() => window.zmartSourcesWaiting() === 0",
                              timeout=90_000)
        page.wait_for_timeout(2_000)
        opening_zoom = page.evaluate(
            "() => window.zmartViewer.navigationState.zoomFactor.value")

        # The storm: half the survey lands at ten a second while the view is
        # driven through the zoom bands, the way a hand on the wheel does it.
        # Both run flat out on purpose — this is the regime the demos hit and
        # every earlier gate avoided.
        stop_zooming = threading.Event()

        def zoom_to(multiple: float) -> None:
            page.evaluate(
                "(wanted) => {"
                "  window.zmartViewer.navigationState.zoomFactor.value = wanted;"
                "}",
                opening_zoom * multiple,
            )

        def keep_zooming() -> None:
            # A hand on the wheel, not a switch between presets: many small
            # multiplicative zoom steps, and the view PANNED while it moves —
            # wheel-zoom at a cursor pans too, and panning is what drags new
            # chunks into view and evicts others mid-storm. The walk is a
            # fixed sequence, so the storm is the same storm every run.
            drift = (0.35, -0.2, 0.15, -0.4, 0.25, -0.1, 0.3, -0.35)
            step = 0
            while not stop_zooming.is_set():
                factor = 0.12 * (1.28 ** (step % 26))
                try:
                    page.evaluate(
                        "([wanted, sideways]) => {"
                        "  const state = window.zmartViewer.navigationState;"
                        "  state.zoomFactor.value = wanted;"
                        "  const position = state.position;"
                        "  const space = position.coordinateSpace.value;"
                        "  if (!space?.rank) return;"
                        "  const moved = Float32Array.from(position.value);"
                        "  const wide = space.bounds.upperBounds[space.rank - 1];"
                        "  moved[space.rank - 1] = wide * (0.5 + sideways);"
                        "  moved[space.rank - 2] = wide * (0.5 - sideways);"
                        "  position.value = moved;"
                        "}",
                        [opening_zoom * factor, drift[step % len(drift)]],
                    )
                except Exception:
                    return
                step += 1
                time.sleep(0.08)

        zooming = threading.Thread(target=keep_zooming, daemon=True)
        zooming.start()
        try:
            for position_id in landing_later:
                harness.fast_publish(run, position_id)
                _announce(port, _dirty_for(run, pictured, position_id))
                time.sleep(0.1)
        finally:
            stop_zooming.set()
            zooming.join(timeout=5)

        # Let every staged push, flush timeout and refetch settle.
        page.wait_for_timeout(6_000)

        assert not troubles, (
            "the storm broke the page itself — everything after an exception "
            f"in the delivery path stays stale quietly: {troubles[:5]}"
        )

        # Photograph every zoom band. The survey is fully landed, so every
        # band must show it essentially complete; a band markedly darker than
        # its neighbours is holding pieces the server no longer agrees with.
        seen = {}
        for multiple in (0.15, 0.4, 1.0, 2.5):
            zoom_to(multiple)
            page.wait_for_timeout(2_500)
            seen[multiple] = fraction_lit(page)
        import os
        if os.environ.get("ZMART_STORM_DEBUG"):
            zoom_to(1.0)
            page.wait_for_timeout(2_500)
            page.screenshot(path=str(Path(os.environ["ZMART_STORM_DEBUG"])
                                     / "storm_band_1x.png"))
            wanting = page.evaluate(
                """() => {
                  const out = [];
                  for (const managed of
                       window.zmartViewer.layerManager.managedLayers) {
                    for (const rl of (managed.layer?.renderLayers || [])) {
                      const p = rl.layerChunkProgressInfo;
                      if (p) out.push({
                        needed: p.numVisibleChunksNeeded,
                        available: p.numVisibleChunksAvailable,
                      });
                    }
                  }
                  return out;
                }"""
            )
            print("WANTED VS HELD AT 1.0x:", json.dumps(wanting))
            believed = page.evaluate(
                """() => {
                  const out = [];
                  for (const managed of
                       window.zmartViewer.layerManager.managedLayers) {
                    for (const source of
                         (managed.layer?.dataSources || [])) {
                      const space =
                        source.loadState?.transform?.value?.outputSpace ??
                        source.loadState?.dataSource?.modelTransform
                          ?.outputSpace;
                      const bounds = space?.bounds ??
                        source.loadState?.dataSource?.subsources?.[0]
                          ?.subsource?.volume?.rank !== undefined
                          ? null : null;
                      out.push({
                        name: managed.name,
                        url: source.spec?.url,
                        lower: space ? Array.from(space.bounds.lowerBounds)
                                     : null,
                        upper: space ? Array.from(space.bounds.upperBounds)
                                     : null,
                      });
                    }
                  }
                  const global = window.zmartViewer.navigationState.position
                    .coordinateSpace.value;
                  out.push({ name: "GLOBAL",
                             lower: Array.from(global.bounds.lowerBounds),
                             upper: Array.from(global.bounds.upperBounds) });
                  return out;
                }"""
            )
            print("BELIEVED BOUNDS:", json.dumps(believed))

        # The oracle is the operator's own cure: a reload builds a fresh
        # client over the very same server, so whatever a reload would fix
        # WAS staleness, and each zoom band after the storm must match the
        # same band seen fresh. Comparing bands against each other measured
        # geometry (how much of the frame the survey occupies at that zoom),
        # which is how this gate's first draft fooled itself.
        page.goto(f"http://127.0.0.1:{port}", wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartViewer !== undefined",
                              timeout=60_000)
        page.wait_for_function("() => window.zmartSourcesWaiting() === 0",
                              timeout=90_000)
        page.wait_for_timeout(2_000)
        fresh = {}
        for multiple in (0.15, 0.4, 1.0, 2.5):
            zoom_to(multiple)
            page.wait_for_timeout(2_500)
            fresh[multiple] = fraction_lit(page)

        for multiple in seen:
            stormy, reloaded = seen[multiple], fresh[multiple]
            assert stormy >= reloaded - 0.03, (
                f"at {multiple:.2f}x the storm session shows {stormy:.1%} lit "
                f"where a fresh client over the same server shows "
                f"{reloaded:.1%} — the difference is exactly what a reload "
                "cures, which is to say: stale pieces. All bands, storm vs "
                "fresh: " + ", ".join(
                    f"{m:.2f}x {seen[m]:.1%} vs {fresh[m]:.1%}"
                    for m in sorted(seen))
            )
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)
