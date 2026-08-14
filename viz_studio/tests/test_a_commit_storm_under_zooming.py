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

import io
import json
import os
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


def _fraction_lit_across_canvas(page, floor: int = 40) -> float:
    """Measure growth at the outer survey edge, not only its filled centre."""
    import numpy as np
    from PIL import Image

    canvas = page.locator("canvas").first.bounding_box()
    shot = page.screenshot(clip=canvas)
    pixels = np.array(Image.open(io.BytesIO(shot)).convert("RGB"))
    return float((pixels.max(axis=2) > floor).mean())


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


def test_tiles_advance_before_a_commit_storm_quiets(
    browser, built_dist, tmp_path
):
    """The live picture advances in batches; it must not appear only at EOF."""
    harness.FIXTURES = tmp_path
    run, order = harness.the_run(12)
    width = len(str(12 - 1))
    middle = (12 - 1) / 2
    committed_first = [one for one in order
                       if abs(int(one[1:1 + width]) - middle) <= 3.5
                       and abs(int(one[1 + width:]) - middle) <= 3.5]
    landing_later = [one for one in order if one not in set(committed_first)]
    for position_id in committed_first:
        harness.fast_publish(run, position_id)
    shown = tmp_path / "live-progress" / "shown"
    store = declare_a_governed_picture(shown, run.folder, name="live",
                                       bake=True)
    pictured = len(json.loads((store / "zarr.json").read_text(
        encoding="utf-8"))["attributes"]["ome"]["multiscales"][0]["datasets"])
    site = Path(os.environ.get("ZMART_STORM_BUILT_DIST", built_dist))
    server = make_server(port=0, data_dir=shown, site_dir=site,
                         store=[store.name], window=harness.BRIGHT, live=True)
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    page = browser.new_page(viewport={"width": 1000, "height": 780})
    failures: list[BaseException] = []
    finished = threading.Event()
    landed = {"count": 0}
    samples: list[tuple[int, int, float]] = []
    try:
        port = server.server_address[1]
        page.add_init_script("globalThis.zmartLiveCheckMs = 150")
        page.goto(f"http://127.0.0.1:{port}", wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartViewer !== undefined",
                               timeout=60_000)
        page.wait_for_function("() => window.zmartSourcesWaiting() === 0",
                               timeout=90_000)
        page.wait_for_timeout(2_000)
        opening = _fraction_lit_across_canvas(page)

        def publish() -> None:
            try:
                for number, position_id in enumerate(landing_later, 1):
                    harness.fast_publish(run, position_id)
                    _announce(port, _dirty_for(run, pictured, position_id))
                    landed["count"] = number
                    time.sleep(0.05)
            except BaseException as problem:
                failures.append(problem)
            finally:
                finished.set()

        publishing = threading.Thread(target=publish, daemon=True)
        publishing.start()
        stamp_path = store / "baked.json"
        while not finished.is_set():
            stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
            samples.append((landed["count"], int(stamp["events"]),
                            _fraction_lit_across_canvas(page)))
            page.wait_for_timeout(200)
        publishing.join(timeout=30)
        assert not publishing.is_alive(), "the live-progress storm did not finish"
        assert not failures, f"the live-progress publisher failed: {failures!r}"

        high = opening
        visible_steps = 0
        for published, _stamped, lit in samples:
            if published >= len(landing_later):
                continue
            if lit >= high + 0.01:
                visible_steps += 1
                high = lit
        print("LIVE PROGRESS:", json.dumps({
            "opening": opening,
            "positions": len(landing_later),
            "samples": [(n, stamp, round(lit, 4))
                        for n, stamp, lit in samples],
            "visible_steps": visible_steps,
        }), flush=True)
        assert visible_steps >= 2, (
            "the acquisition made no visible progress before it went quiet; "
            "published/stamped/lit timeline: "
            + ", ".join(f"{n}/{stamp}/{lit:.1%}"
                        for n, stamp, lit in samples)
        )
    finally:
        page.close()
        server.shutdown()
        serving.join(timeout=5)


def test_every_zoom_shows_the_survey_after_a_storm_of_landings(
    browser, built_dist, tmp_path
):
    """Ten landings a second, a zooming viewer, and no level left behind."""
    harness.FIXTURES = tmp_path
    # The operator's fast recipe: a survey already big when the watching
    # starts (the central block pre-committed), so the collision window is
    # wide from the first landing — measured to wedge within ten seconds
    # where a survey growing from empty needed to get large first.
    run, order = harness.the_run(14)
    width = len(str(14 - 1))
    middle = (14 - 1) / 2
    committed_first = [one for one in order
                       if abs(int(one[1:1 + width]) - middle) <= 4
                       and abs(int(one[1 + width:]) - middle) <= 4]
    landing_later = [one for one in order if one not in set(committed_first)]
    for position_id in committed_first:
        harness.fast_publish(run, position_id)
    shown = tmp_path / "gov6x6" / "shown"
    store = declare_a_governed_picture(shown, run.folder, name="live", bake=True)
    pictured = len(json.loads((store / "zarr.json").read_text(
        encoding="utf-8"))["attributes"]["ome"]["multiscales"][0]["datasets"])

    site = Path(os.environ.get("ZMART_STORM_BUILT_DIST", built_dist))
    server = make_server(port=0, data_dir=shown, site_dir=site,
                         store=[store.name], window=harness.BRIGHT, live=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1000, "height": 780})
    import os as os_module
    if os_module.environ.get("ZMART_STORM_NO_HTTP_CACHE"):
        session = page.context.new_cdp_session(page)
        session.send("Network.enable")
        session.send("Network.setCacheDisabled", {"cacheDisabled": True})
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
        if os_module.environ.get("ZMART_STORM_HIGH_MEMORY"):
            raised = page.evaluate(
                """() => {
                  const capacities = window.zmartViewer.chunkQueueManager
                    .capacities;
                  capacities.gpuMemory.sizeLimit.value = 8e9;
                  capacities.systemMemory.sizeLimit.value = 8e9;
                  capacities.download.itemLimit.value = 400;
                  return {
                    gpu: capacities.gpuMemory.sizeLimit.value,
                    system: capacities.systemMemory.sizeLimit.value,
                    download: capacities.download.itemLimit.value,
                  };
                }"""
            )
            print("RAISED MEMORY:", json.dumps(raised), flush=True)
        opening_zoom = page.evaluate(
            "() => window.zmartViewer.navigationState.zoomFactor.value")

        # The storm: half the survey lands at ten a second while the view is
        # driven through the zoom bands, the way a hand on the wheel does it.
        # Both run flat out on purpose — this is the regime the demos hit and
        # every earlier gate avoided.
        stop_zooming = threading.Event()
        storm_failures: list[BaseException] = []

        def zoom_to(multiple: float) -> None:
            # Centre as well as zoom: the storm's driver PANS, and a
            # photograph taken off-centre counts honest out-of-canvas ground
            # as missing picture — the first draft of this gate measured its
            # own pan offset for an evening and called it staleness.
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

        def keep_zooming() -> None:
            # A hand on the wheel, not a switch between presets: many small
            # multiplicative zoom steps, and the view PANNED while it moves —
            # wheel-zoom at a cursor pans too, and panning is what drags new
            # chunks into view and evicts others mid-storm. The walk is a
            # fixed sequence, so the storm is the same storm every run.
            canvas = page.locator("canvas").first.bounding_box()
            centre_x = canvas["x"] + canvas["width"] * 0.48
            centre_y = canvas["y"] + canvas["height"] * 0.52
            drifts = ((45, -25), (-35, 30), (25, 20), (-40, -20))
            step = 0
            while not stop_zooming.is_set():
                try:
                    page.mouse.move(centre_x, centre_y)
                    direction = -1 if (step // 18) % 2 == 0 else 1
                    page.mouse.wheel(0, direction * 180)
                    if step % 9 == 8:
                        dx, dy = drifts[(step // 9) % len(drifts)]
                        page.mouse.down()
                        page.mouse.move(centre_x + dx, centre_y + dy,
                                        steps=4)
                        page.mouse.up()
                except Exception as problem:
                    storm_failures.append(problem)
                    return
                step += 1
                time.sleep(0.08)

        def land_the_storm() -> None:
            try:
                for position_id in landing_later:
                    harness.fast_publish(run, position_id)
                    _announce(port, _dirty_for(run, pictured, position_id))
                    time.sleep(0.05)
            except BaseException as problem:
                storm_failures.append(problem)
            finally:
                stop_zooming.set()

        landing = threading.Thread(target=land_the_storm, daemon=True)
        landing.start()
        keep_zooming()
        landing.join(timeout=60)
        if landing.is_alive():
            stop_zooming.set()
        assert not landing.is_alive(), "the landing storm did not finish"
        assert not storm_failures, f"the wheel-and-landing storm failed: {storm_failures!r}"

        def scale_census() -> dict:
            return page.evaluate(
                """() => {
                  const out = { renderLayers: 0, progress: [] };
                  for (const managed of
                       window.zmartViewer.layerManager.managedLayers) {
                    for (const rl of (managed.layer?.renderLayers || [])) {
                      out.renderLayers += 1;
                      const p = rl.layerChunkProgressInfo;
                      if (p) out.progress.push(
                        [p.numVisibleChunksNeeded,
                         p.numVisibleChunksAvailable]);
                    }
                  }
                  const shared =
                    window.zmartViewer.chunkManager.rpc.objects;
                  out.backendSources = 0;
                  for (const [, held] of shared) {
                    if (held && typeof held.invalidateCache === 'function'
                        && held.spec && held.spec.upperVoxelBound) {
                      out.backendSources += 1;
                    }
                  }
                  return out;
                }"""
            )

        stormed_census = scale_census()

        if os_module.environ.get("ZMART_STORM_HEAL"):
            # The splitting experiment: name EVERY piece of EVERY level dirty
            # in one announcement. If the picture heals without a reload, the
            # delivery machinery is sound and the per-landing dirty naming is
            # what navigation defeats; if it stays wedged, delivery itself
            # loses refreshes despite correct names.
            page.wait_for_timeout(4_000)
            zoom_to(1.0)
            page.wait_for_timeout(2_000)
            before_heal = fraction_lit(page)
            answered: list[tuple[int, str]] = []
            page.on("response",
                    lambda told: answered.append((told.status, told.url))
                    if "/data/" in told.url else None)
            everything = {}
            for level in range(pictured):
                described = json.loads(
                    (store / str(level) / "zarr.json").read_text(
                        encoding="utf-8"))
                depth, height, wide = described["shape"]
                everything[str(level)] = [
                    [0, r, c]
                    for r in range((height + 511) // 512)
                    for c in range((wide + 511) // 512)
                ]
            _announce(port, everything)
            page.wait_for_timeout(6_000)
            after_heal = fraction_lit(page)
            print(f"HEAL TEST at 1.0x: before {before_heal:.1%} "
                  f"after full-dirty {after_heal:.1%}", flush=True)
            from collections import Counter
            statuses = Counter(status for status, _ in answered)
            print(f"HEAL NETWORK: {len(answered)} /data/ responses, "
                  f"statuses {dict(statuses)}", flush=True)
            print("SWAP LEDGER:", json.dumps(page.evaluate(
                "() => globalThis.zmartSwapLedger ?? 'never touched'")),
                flush=True)
            print("TWINNING:", json.dumps(page.evaluate(
                "() => window.zmartTwinning")), flush=True)
            print("FRONTEND SOURCES:", json.dumps(page.evaluate(
                """() => {
                  const out = [];
                  const registry =
                    window.zmartViewer.chunkManager.rpc.objects;
                  for (const [id, held] of registry) {
                    if (held && held.chunks instanceof Map) {
                      out.push({ id, holds: held.chunks.size,
                                 sample: [...held.chunks.keys()].slice(0, 4) });
                    }
                  }
                  return out;
                }""")), flush=True)
            print("CHUNK DATA MEANS:", json.dumps(page.evaluate(
                """() => {
                  const out = [];
                  const registry =
                    window.zmartViewer.chunkManager.rpc.objects;
                  for (const [id, held] of registry) {
                    if (held && held.chunks instanceof Map) {
                      for (const [key, chunk] of held.chunks) {
                        const data = chunk.data ?? null;
                        let mean = null;
                        if (data && data.length) {
                          let sum = 0, n = 0;
                          const step = Math.max(1, (data.length / 2000) | 0);
                          for (let i = 0; i < data.length; i += step) {
                            sum += data[i]; n += 1;
                          }
                          mean = Math.round(sum / n);
                        }
                        out.push({ id, key,
                                   held: data ? data.length : null, mean });
                      }
                    }
                  }
                  return out.slice(0, 12);
                }""")), flush=True)
            print("LAYERS NOW:", json.dumps(page.evaluate(
                """() => window.zmartViewer.layerManager.managedLayers
                     .map((m) => ({ name: m.name,
                                    ready: m.isReady ?? null }))""")),
                flush=True)
            for status, url in answered[:10]:
                print(f"   {status} {url.split('/data/')[-1]}", flush=True)

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
        debug_folder = (Path(os_module.environ["ZMART_STORM_DEBUG"])
                        if os_module.environ.get("ZMART_STORM_DEBUG") else None)
        for multiple in (0.15, 0.4, 1.0, 2.5):
            zoom_to(multiple)
            page.wait_for_timeout(2_500)
            seen[multiple] = fraction_lit(page)
            if debug_folder is not None:
                page.screenshot(path=str(
                    debug_folder / f"storm_band_{multiple:.2f}x.png"))
        if os_module.environ.get("ZMART_STORM_DEBUG"):
            print("CLIENT INVALIDATION:", json.dumps(page.evaluate(
                "() => window.zmartChunkInvalidation")), flush=True)
            worker_probes = page.evaluate(
                """async () => {
                  const out = [];
                  for (const [id, held] of
                       window.zmartViewer.chunkManager.rpc.objects) {
                    if (!held || typeof held.invalidateCache !== 'function'
                        || !held.spec?.upperVoxelBound) continue;
                    const answer = await Promise.race([
                      held.rpc.promiseInvoke(
                        'ChunkSource.zmartProbe', { source: held.rpcId }),
                      new Promise((resolve) => setTimeout(
                        () => resolve({probeTimeout: true}), 2_000)),
                    ]);
                    out.push({ id, bound: Array.from(held.spec.upperVoxelBound),
                               probe: answer?.value ?? answer });
                  }
                  return out;
                }"""
            )
            print("WORKER PROBES:", json.dumps(worker_probes), flush=True)
            zoom_to(1.0)
            page.wait_for_timeout(2_500)
            page.screenshot(path=str(Path(os_module.environ["ZMART_STORM_DEBUG"])
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
            ledger = page.evaluate(
                """() => {
                  const q = window.zmartViewer.chunkQueueManager ??
                            window.zmartViewer.chunkManager?.chunkQueueManager;
                  if (!q) return "no queue manager reachable";
                  const read = (cap) => cap ? {
                    total: cap.capacity ?? cap.sizeLimit ?? null,
                    used: cap.size ?? cap.currentSize ?? null,
                    items: cap.itemLimit ?? null,
                  } : null;
                  return {
                    gpu: read(q.capacities?.gpuMemory ?? q.gpuMemoryCapacity),
                    system: read(q.capacities?.systemMemory
                                 ?? q.systemMemoryCapacity),
                    download: read(q.capacities?.download
                                   ?? q.downloadCapacity),
                    keys: Object.keys(q),
                  };
                }"""
            )
            print("MEMORY LEDGER:", json.dumps(ledger))
            backlog = page.evaluate(
                """() => {
                  const q = window.zmartViewer.chunkQueueManager ??
                            window.zmartViewer.chunkManager?.chunkQueueManager;
                  if (!q) return "no queue manager";
                  let length = 0;
                  let walk = q.pendingChunkUpdates;
                  const kinds = {};
                  while (walk && length < 100000) {
                    length += 1;
                    const kind = walk.state !== undefined
                      ? `state=${walk.state}` : (walk.new ? "new" : "update");
                    kinds[kind] = (kinds[kind] || 0) + 1;
                    walk = walk.nextUpdate ?? walk.next ?? null;
                  }
                  return { pending: length, kinds,
                           deadline: q.chunkUpdateDeadline,
                           delay: q.chunkUpdateDelay };
                }"""
            )
            print("PENDING UPDATES:", json.dumps(backlog))

        if os_module.environ.get("ZMART_STORM_HEAL"):
            probe_piece = f"http://127.0.0.1:{port}/data/0/{store.name}/0/c/0/0/8"
            def _bytes_now() -> bytes:
                request = urllib.request.Request(probe_piece)
                try:
                    with urllib.request.urlopen(request, timeout=30) as answer:
                        return answer.read()
                except urllib.error.HTTPError:
                    return b""
            first_look = _bytes_now()
            time.sleep(6)
            second_look = _bytes_now()
            print(f"BAKE LAG PROBE: piece 0/c/0/0/8 "
                  f"{len(first_look)}B then {len(second_look)}B, "
                  f"{'CHANGED while quiet' if first_look != second_look else 'identical'}",
                  flush=True)
            _announce(port, {"0": [[0, 0, 8]]})
            time.sleep(4)
            third_look = _bytes_now()
            print(f"AFTER A POKE DERIVE: {len(third_look)}B, "
                  f"{'CHANGED — the composer was behind' if third_look != second_look else 'still identical'}",
                  flush=True)

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
            if debug_folder is not None:
                page.screenshot(path=str(
                    debug_folder / f"fresh_band_{multiple:.2f}x.png"))
        fresh_census = scale_census()
        print("SCALES stormed:", json.dumps(stormed_census),
              " fresh:", json.dumps(fresh_census), flush=True)
        if os_module.environ.get("ZMART_STORM_HEAL"):
            after_reload = _bytes_now()
            print(f"PIECE AFTER RELOAD'S DERIVE: {len(after_reload)}B, "
                  f"{'CHANGED — the reload derive caught the composer up' if after_reload != second_look else 'STILL the same bytes'}",
                  flush=True)

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
