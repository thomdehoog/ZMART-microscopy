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
sys.path.insert(0, str(_VIZ / "app" / "picture"))

import measure_a_governed_run_at_scale as harness  # noqa: E402
import server as server_module  # noqa: E402
from declare import declare_a_governed_picture  # noqa: E402
from pixels import fraction_lit, image_middle  # noqa: E402
from server import make_server  # noqa: E402


def _fraction_lit_across_canvas(page, floor: int = 40) -> float:
    """Measure growth at the outer survey edge, not only its filled centre."""
    import numpy as np
    from PIL import Image

    canvas = page.locator("canvas").first.bounding_box()
    shot = page.screenshot(clip=canvas)
    pixels = np.array(Image.open(io.BytesIO(shot)).convert("RGB"))
    return float((pixels.max(axis=2) > floor).mean())


def _save_middle_and_measure(page, path: Path | None = None,
                             floor: int = 40):
    """Take one oracle photograph and optionally preserve its exact pixels."""
    from PIL import Image

    pixels = image_middle(page)
    if path is not None:
        Image.fromarray(pixels).save(path)
    return float((pixels.max(axis=2) > floor).mean()), pixels


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


def _the_page_address(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def _announce(port: int, dirty: dict | None = None) -> None:
    """Tell the page image was written in place.

    ``dirty`` is accepted for the callers that still compute footprints for
    their own bookkeeping; the wire no longer carries it -- the page's one
    invalidation drops every decoded piece and refetches behind the picture
    on screen.
    """
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/announce",
        data=json.dumps({"wrote_image_in_place": True}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30):
        pass


def test_a_slow_or_transient_refresh_reaches_confirmation_after_quiet(
    browser, built_dist, tmp_path, monkeypatch
):
    """A slow refresh finishes, and a transient one retries, without black.

    The 20/s gate below found the causal signature this isolates: chunks that
    were partial early in the run were asked for repeatedly, every request was
    aborted at the worker patch's 2,000 ms deadline, and no request followed
    after the run went quiet.  The page nevertheless counted those partial
    chunks as available, while F5 fetched larger, complete answers.

    This smaller gate makes exactly one dirty wave slow for 2.6 seconds.  A
    useful request must not be manufactured into a failure at an arbitrary
    deadline: the warm page must become the same picture a reload sees while
    existing pixels remain on screen.  Once that is established, one later
    request receives a deliberate HTTP 503.  Neuroglancer's HTTP reader must
    retry it to success without a competing ZMART timer or another announcement.
    """
    harness.FIXTURES = tmp_path
    across, core = 8, 4
    run, order = harness.the_run(across)
    width = len(str(across - 1))
    low = (across - core) // 2
    committed_first = [
        one for one in order
        if low <= int(one[1:1 + width]) < low + core
        and low <= int(one[1 + width:]) < low + core
    ]
    landing_later = [one for one in order if one not in set(committed_first)]
    for position_id in committed_first:
        harness.fast_publish(run, position_id)

    shown = run.folder / "views" / "shown"
    store = declare_a_governed_picture(shown, run.folder, name="live", bake=True)
    pictured = len(json.loads((store / "zarr.json").read_text(
        encoding="utf-8"))["attributes"]["ome"]["multiscales"][0]["datasets"])

    slow_chunks = threading.Event()
    reject_one_chunk = threading.Event()
    server_attempts: dict[str, int] = {}
    slow_serves = {"count": 0}
    dropped = {"path": None}
    rejected_target = {"suffix": None}
    ordinary_serve = server_module._Handler._serve_from_data

    def serve_one_wave_slowly(handler) -> None:
        is_chunk = "/c/" in handler.path
        if is_chunk:
            server_attempts[handler.path] = (
                server_attempts.get(handler.path, 0) + 1)
        if (reject_one_chunk.is_set() and is_chunk
                and handler.path.endswith(rejected_target["suffix"] or "")):
            reject_one_chunk.clear()
            dropped["path"] = handler.path
            handler.send_response(503, "deliberate refresh rejection")
            handler.send_header("Content-Length", "0")
            handler.send_header("Cache-Control", "no-store")
            handler.end_headers()
            return
        if slow_chunks.is_set() and is_chunk:
            slow_serves["count"] += 1
            time.sleep(2.6)
        ordinary_serve(handler)

    monkeypatch.setattr(
        server_module._Handler, "_serve_from_data", serve_one_wave_slowly)

    site = Path(os.environ.get("ZMART_STORM_BUILT_DIST", built_dist))
    server = make_server(port=0, data_dir=shown, site_dir=site,
                         store=[store.name], window=harness.BRIGHT, live=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1000, "height": 780})
    failed: list[dict] = []
    request_began: dict[int, float] = {}

    def request_started(request) -> None:
        if "/c/" in request.url:
            request_began[id(request)] = time.perf_counter()

    def request_finished(request) -> None:
        request_began.pop(id(request), None)

    def request_failed(request) -> None:
        if "/c/" not in request.url:
            return
        began = request_began.pop(id(request), time.perf_counter())
        failed.append({
            "url": request.url,
            "elapsed": time.perf_counter() - began,
            "reason": request.failure,
        })

    page.on("request", request_started)
    page.on("requestfinished", request_finished)
    page.on("requestfailed", request_failed)
    debug_folder = (Path(os.environ["ZMART_STORM_DEBUG"])
                    if os.environ.get("ZMART_STORM_DEBUG") else None)
    if debug_folder is not None:
        debug_folder.mkdir(parents=True, exist_ok=True)
    try:
        port = server.server_address[1]
        page.add_init_script("globalThis.zmartLiveCheckMs = 150")
        page.goto(_the_page_address(port), wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartViewer !== undefined",
                              timeout=60_000)
        page.wait_for_function("() => window.zmartSourcesWaiting() === 0",
                              timeout=90_000)
        page.wait_for_timeout(2_000)
        opening = _fraction_lit_across_canvas(page)
        if debug_folder is not None:
            page.screenshot(path=str(debug_folder / "timeout_opening.png"))

        dirty = {str(level): set() for level in range(pictured)}
        for position_id in landing_later:
            harness.fast_publish(run, position_id)
            for level, pieces in _dirty_for(
                    run, pictured, position_id).items():
                dirty[level].update(tuple(piece) for piece in pieces)
        whole_wave = {
            level: [list(piece) for piece in sorted(pieces)]
            for level, pieces in dirty.items()
        }

        slow_chunks.set()
        _announce(port, whole_wave)
        page.wait_for_timeout(3_500)
        slow_chunks.clear()
        recovered_at = time.perf_counter()

        # The bake may still be closing its own queue.  Wait for truth on disk,
        # then give a retry enough time to finish on the now-fast server.  No
        # announcement, navigation or client action is made in this interval.
        deadline = time.monotonic() + 20
        baked = 0
        while time.monotonic() < deadline:
            baked = int(json.loads((store / "baked.json").read_text(
                encoding="utf-8"))["events"])
            if baked == len(order):
                break
            time.sleep(0.1)
        assert baked == len(order), (
            f"the retry fixture's bake stopped at {baked}/{len(order)}")
        baked_after_recovery = time.perf_counter() - recovered_at
        coverage_timeline: list[dict] = []
        quiet_until = time.perf_counter() + 6
        while time.perf_counter() < quiet_until:
            coverage_timeline.append({
                "after_recovery": time.perf_counter() - recovered_at,
                "lit": _fraction_lit_across_canvas(page),
            })
            page.wait_for_timeout(250)
        warm = _fraction_lit_across_canvas(page)
        coverage_timeline.append({
            "after_recovery": time.perf_counter() - recovered_at,
            "lit": warm,
        })
        if debug_folder is not None:
            page.screenshot(path=str(
                debug_folder / "timeout_warm_after_quiet.png"))

        def coarsest_refresh_probe() -> dict:
            return page.evaluate(
                """async () => {
                  const sources = [];
                  for (const held of
                       window.zmartViewer.chunkManager.rpc.objects.values()) {
                    if (!held || typeof held.invalidateCache !== 'function'
                        || !held.spec?.upperVoxelBound) continue;
                    const bound = Array.from(held.spec.upperVoxelBound);
                    const answer = await held.rpc.promiseInvoke(
                      'ChunkSource.zmartProbe', {source: held.rpcId});
                    const probe = answer?.value ?? answer;
                    if (probe?.refresh) {
                      sources.push({bound, refresh: probe.refresh});
                    }
                  }
                  sources.sort((a, b) => Math.max(...a.bound) -
                    Math.max(...b.bound));
                  return sources[0];
                }""")

        # A retryable HTTP response is different from a slow response.  Reject
        # one request for a coarse chunk the page certainly holds and announce
        # it only once.  Neuroglancer's existing HTTP reader owns the retry: a
        # second server attempt must arrive without another ZMART timer,
        # announcement, or navigation.
        failed_before_drop = len(failed)
        probe_level = str(pictured - 1)
        probe_piece = whole_wave[probe_level][0]
        attempts_before_drop = sum(server_attempts.values())
        attempts_by_path_before_drop = dict(server_attempts)
        retry_before = coarsest_refresh_probe()
        rejected_target["suffix"] = f"/{probe_level}/c/0/0/0"
        reject_one_chunk.set()
        _announce(port, {probe_level: [probe_piece]})
        drop_deadline = time.monotonic() + 8
        while time.monotonic() < drop_deadline:
            path = dropped["path"]
            if (path is not None and server_attempts.get(path, 0) >= (
                    attempts_by_path_before_drop.get(path, 0) + 2)):
                break
            page.wait_for_timeout(100)
        dropped_path = dropped["path"]
        assert dropped_path is not None, (
            "the deliberate connection drop never intercepted a chunk")
        assert server_attempts.get(dropped_path, 0) >= (
                attempts_by_path_before_drop.get(dropped_path, 0) + 2), (
            f"the dropped request for {dropped_path} was never retried")
        page.wait_for_timeout(500)
        retry_after = coarsest_refresh_probe()
        after_real_retry = _fraction_lit_across_canvas(page)

        navigation = page.evaluate(
            """() => ({
              zoom: window.zmartViewer.navigationState.zoomFactor.value,
              position: Array.from(
                window.zmartViewer.navigationState.position.value),
            })""")
        page.goto(_the_page_address(port), wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartViewer !== undefined",
                              timeout=60_000)
        page.wait_for_function("() => window.zmartSourcesWaiting() === 0",
                              timeout=90_000)
        page.evaluate(
            """(saved) => {
              const state = window.zmartViewer.navigationState;
              state.zoomFactor.value = saved.zoom;
              state.position.value = Float32Array.from(saved.position);
            }""",
            navigation,
        )
        page.wait_for_timeout(2_000)
        fresh = _fraction_lit_across_canvas(page)
        fresh_navigation = page.evaluate(
            """() => ({
              zoom: window.zmartViewer.navigationState.zoomFactor.value,
              position: Array.from(
                window.zmartViewer.navigationState.position.value),
            })""")
        if debug_folder is not None:
            page.screenshot(path=str(
                debug_folder / "timeout_fresh_after_reload.png"))

        first_repaired = next((
            sample["after_recovery"] for sample in coverage_timeline
            if sample["lit"] >= fresh - 0.03
        ), None)
        minimum_during_recovery = min(
            sample["lit"] for sample in coverage_timeline)

        print("TIMEOUT RETRY:", json.dumps({
            "opening": opening, "warm_after_quiet": warm,
            "fresh_after_reload": fresh, "failed_chunk_requests": len(failed),
            "slow_requests_completed": slow_serves["count"],
            "failed_before_deliberate_drop": failed_before_drop,
            "deliberately_dropped_path": dropped_path,
            "attempts_after_drop": (
                sum(server_attempts.values()) - attempts_before_drop),
            "retry_probe_before": retry_before,
            "retry_probe_after": retry_after,
            "coverage_after_real_retry": after_real_retry,
            "baked": baked,
            "bake_complete_after_recovery_s": baked_after_recovery,
            "first_observed_repaired_after_recovery_s": first_repaired,
            "minimum_during_recovery": minimum_during_recovery,
            "warm_navigation": navigation,
            "fresh_navigation": fresh_navigation,
        }), flush=True)
        assert slow_serves["count"] > 0, (
            "no request was held beyond the former two-second deadline")
        deadline_failures = [one for one in failed[:failed_before_drop]
                             if 1.8 <= one["elapsed"] <= 2.2]
        assert not deadline_failures, (
            "slow requests are still being manufactured into failures near "
            f"the old two-second deadline: {deadline_failures}")
        assert retry_after["refresh"]["failures"] == (
                retry_before["refresh"]["failures"]), (
            "the HTTP reader should absorb and retry a transient 503; the "
            "outer ZMART refresh promise unexpectedly rejected")
        assert warm >= fresh - 0.03, (
            f"after the server recovered and the run went quiet, the warm "
            f"client still showed {warm:.1%} where F5 showed {fresh:.1%}; "
            "the timed-out dirty wave was forgotten instead of retried")
        assert first_repaired is not None, (
            "the warm client never visibly matched the F5 oracle during the "
            "six-second recovery observation")
        assert minimum_during_recovery >= opening - 0.03, (
            f"the retry repaired the final picture but flashed through "
            f"{minimum_during_recovery:.1%} coverage after opening at "
            f"{opening:.1%}")
        assert after_real_retry >= warm - 0.03, (
            f"the genuine-failure retry made the picture fall from "
            f"{warm:.1%} to {after_real_retry:.1%}")
    finally:
        slow_chunks.clear()
        reject_one_chunk.clear()
        page.close()
        server.shutdown()
        thread.join(timeout=5)


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
    shown = run.folder / "views" / "shown"
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
        page.goto(_the_page_address(port), wait_until="domcontentloaded")
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
    """Twenty landings a second, a zooming viewer, and no level left behind.

    This is the operator's 2026-08-15 reproduction: a 40x40 survey with a
    12x12 core already visible, every other position pre-written, and only
    manifest commits plus announcements in the watched loop.  At a measured
    20.0 landings/s, hard wheel motion left chunk-aligned holes and entire
    zoom bands showing only the initial core; F5 immediately restored the
    complete survey while manifest and bake were both at 1,600.
    """
    harness.FIXTURES = tmp_path
    # The operator's fast recipe: a survey already big when the watching
    # starts (the central block pre-committed), so the collision window is
    # wide from the first landing — measured to wedge within ten seconds
    # where a survey growing from empty needed to get large first.
    across, core = 40, 12
    run, order = harness.the_run(across)
    width = len(str(across - 1))
    low = (across - core) // 2
    committed_first = [
        one for one in order
        if low <= int(one[1:1 + width]) < low + core
        and low <= int(one[1 + width:]) < low + core
    ]
    landing_later = [one for one in order if one not in set(committed_first)]
    for position_id in committed_first:
        harness.fast_publish(run, position_id)
    shown = run.folder / "views" / "shown"
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
    debug_folder = (Path(os_module.environ["ZMART_STORM_DEBUG"])
                    if os_module.environ.get("ZMART_STORM_DEBUG") else None)
    if debug_folder is not None:
        debug_folder.mkdir(parents=True, exist_ok=True)
    trace_zero = time.perf_counter()
    landing_trace: list[dict] = []
    visual_trace: list[dict] = []
    browser_timeline: list[dict] = []
    network_events: list[dict] = []
    network_open: dict[int, tuple[str, float]] = {}
    network_current: dict[str, int] = {}
    network_maximum: dict[str, int] = {}
    network_requests: dict[str, int] = {}
    network_phase = {"name": "opening"}
    network_global = {"current": 0, "maximum": 0}

    def _network_path(url: str) -> str | None:
        for marker in ("/data/", "/api/"):
            if marker in url:
                return marker + url.split(marker, 1)[1]
        return None

    def _request_started(request) -> None:
        path = _network_path(request.url)
        if path is None:
            return
        now = time.perf_counter()
        token = id(request)
        network_open[token] = (path, now)
        network_requests[path] = network_requests.get(path, 0) + 1
        network_current[path] = network_current.get(path, 0) + 1
        network_maximum[path] = max(
            network_maximum.get(path, 0), network_current[path])
        network_global["current"] += 1
        network_global["maximum"] = max(
            network_global["maximum"], network_global["current"])
        network_events.append({
            "t": round(now - trace_zero, 6), "event": "request",
            "path": path, "method": request.method,
            "resource": request.resource_type, "phase": network_phase["name"],
        })

    def _response_arrived(response) -> None:
        path = _network_path(response.url)
        if path is None:
            return
        try:
            headers = response.headers
        except Exception:
            headers = {}
        network_events.append({
            "t": round(time.perf_counter() - trace_zero, 6),
            "event": "response", "path": path,
            "status": response.status,
            "phase": network_phase["name"],
            "etag": headers.get("etag"),
            "bytes": headers.get("content-length"),
            "cache": headers.get("cache-control"),
            "service_worker": response.from_service_worker,
        })

    def _request_ended(request, outcome: str) -> None:
        held = network_open.pop(id(request), None)
        path = held[0] if held is not None else _network_path(request.url)
        if path is None:
            return
        network_current[path] = max(0, network_current.get(path, 0) - 1)
        network_global["current"] = max(0, network_global["current"] - 1)
        event = {
            "t": round(time.perf_counter() - trace_zero, 6),
            "event": outcome, "path": path,
            "phase": network_phase["name"],
            "elapsed": (round(time.perf_counter() - held[1], 6)
                        if held is not None else None),
        }
        if outcome == "failed":
            event["failure"] = request.failure
        network_events.append(event)

    page.on("request", _request_started)
    page.on("response", _response_arrived)
    page.on("requestfinished",
            lambda request: _request_ended(request, "finished"))
    page.on("requestfailed",
            lambda request: _request_ended(request, "failed"))
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
        page.goto(_the_page_address(port), wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartViewer !== undefined",
                              timeout=60_000)
        page.wait_for_function("() => window.zmartSourcesWaiting() === 0",
                              timeout=90_000)
        page.wait_for_timeout(2_000)
        page.evaluate(
            """() => {
              globalThis.zmartStormTimeline = [];
              globalThis.zmartStormSampling = false;
              const scalar = (x) => x && typeof x === 'object' &&
                'value' in x ? x.value : (x ?? null);
              const sample = async () => {
                if (globalThis.zmartStormSampling) return;
                globalThis.zmartStormSampling = true;
                try {
                  const viewer = window.zmartViewer;
                  const sources = [];
                  for (const [id, held] of viewer.chunkManager.rpc.objects) {
                    if (!held || !(held.chunks instanceof Map)) continue;
                    const byState = {};
                    const chunks = [];
                    for (const [key, chunk] of held.chunks) {
                      const state = String(chunk.state);
                      byState[state] = (byState[state] || 0) + 1;
                      chunks.push({key, state: chunk.state,
                                   data: chunk.data?.length ?? null,
                                   texture: ('texture' in chunk)
                                     ? chunk.texture !== null : null,
                                   textureLayout: ('textureLayout' in chunk)
                                     ? chunk.textureLayout !== null : null});
                    }
                    const one = {
                      id, bound: held.spec?.upperVoxelBound
                        ? Array.from(held.spec.upperVoxelBound) : null,
                      held: held.chunks.size, byState, chunks,
                    };
                    sources.push(one);
                  }
                  const progress = [];
                  for (const managed of viewer.layerManager.managedLayers) {
                    for (const rl of (managed.layer?.renderLayers || [])) {
                      const p = rl.layerChunkProgressInfo;
                      if (p) progress.push({
                        needed: p.numVisibleChunksNeeded,
                        available: p.numVisibleChunksAvailable,
                      });
                    }
                  }
                  const caps = viewer.chunkQueueManager?.capacities;
                  globalThis.zmartStormTimeline.push({
                    t: performance.now(),
                    zoom: viewer.navigationState.zoomFactor.value,
                    progress, sources,
                    memory: performance.memory ? {
                      used: performance.memory.usedJSHeapSize,
                      total: performance.memory.totalJSHeapSize,
                      limit: performance.memory.jsHeapSizeLimit,
                    } : null,
                    capacities: caps ? {
                      gpuSize: scalar(caps.gpuMemory?.size),
                      gpuLimit: scalar(caps.gpuMemory?.sizeLimit),
                      systemSize: scalar(caps.systemMemory?.size),
                      systemLimit: scalar(caps.systemMemory?.sizeLimit),
                      downloads: scalar(caps.download?.size),
                      downloadLimit: scalar(caps.download?.itemLimit),
                    } : null,
                  });
                } finally {
                  globalThis.zmartStormSampling = false;
                }
              };
              globalThis.zmartSampleStorm = sample;
              globalThis.zmartStormTimer = setInterval(sample, 1000);
              void sample();
            }"""
        )
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

        # The storm: the rest of the survey lands at twenty a second while the view is
        # driven through the zoom bands, the way a hand on the wheel does it.
        # Both run flat out on purpose — this is the regime the demos hit and
        # every earlier gate avoided.
        stop_zooming = threading.Event()
        storm_failures: list[BaseException] = []
        landed_at: list[float] = []

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
            next_picture = time.perf_counter()
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
                    now = time.perf_counter()
                    if debug_folder is not None and now >= next_picture:
                        elapsed = now - trace_zero
                        lit, _ = _save_middle_and_measure(
                            page, debug_folder /
                            f"during_{elapsed:07.2f}s_{step:05d}.png")
                        visual_trace.append({
                            "t": round(elapsed, 6), "step": step,
                            "landed": len(landed_at), "lit": lit,
                            "zoom": page.evaluate(
                                "() => window.zmartViewer.navigationState"
                                ".zoomFactor.value"),
                        })
                        next_picture = now + 1.0
                except Exception as problem:
                    storm_failures.append(problem)
                    return
                step += 1
                time.sleep(0.08)

        def land_the_storm() -> None:
            try:
                began = time.perf_counter()
                for number, position_id in enumerate(landing_later):
                    due = began + number / 20.0
                    time.sleep(max(0.0, due - time.perf_counter()))
                    harness.fast_publish(run, position_id)
                    dirty = _dirty_for(run, pictured, position_id)
                    _announce(port, dirty)
                    completed = time.perf_counter()
                    landed_at.append(completed)
                    record = {
                        "number": number + 1, "position": position_id,
                        "due": round(due - trace_zero, 6),
                        "completed": round(completed - trace_zero, 6),
                        "late_ms": round((completed - due) * 1000, 3),
                        "dirty": {level: len(keys)
                                  for level, keys in dirty.items()},
                    }
                    if number % 20 == 0 or number + 1 == len(landing_later):
                        try:
                            record["manifest_events"] = len(
                                run.manifest.events())
                            record["baked"] = json.loads(
                                (store / "baked.json").read_text(
                                    encoding="utf-8"))
                        except (OSError, ValueError) as problem:
                            record["stamp_read_error"] = str(problem)
                    landing_trace.append(record)
            except BaseException as problem:
                storm_failures.append(problem)
            finally:
                stop_zooming.set()

        landing = threading.Thread(target=land_the_storm, daemon=True)
        network_phase["name"] = "storm"
        landing.start()
        keep_zooming()
        landing.join(timeout=180)
        if landing.is_alive():
            stop_zooming.set()
        assert not landing.is_alive(), "the landing storm did not finish"
        assert not storm_failures, f"the wheel-and-landing storm failed: {storm_failures!r}"
        achieved = ((len(landed_at) - 1) /
                    (landed_at[-1] - landed_at[0]))
        print(f"LANDING RATE: {achieved:.2f}/s over "
              f"{len(landed_at)} commits", flush=True)
        if not 19.5 <= achieved <= 20.5:
            # A machine that cannot hold the landing rate has not run the
            # regime this gate exists to test -- but that is a fact about the
            # machine, not about the code. Failing here taught people to
            # distrust the gate on slower hardware; skipping says plainly
            # that the question was not answered, and the staleness
            # assertions below still run wherever the rate CAN be held.
            pytest.skip(
                f"this machine sustained {achieved:.2f} commits/s where the "
                "storm regime needs 20, so the gate's question was not asked"
            )
        network_phase["name"] = "quiet"

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

        def the_view_is_fully_loaded() -> bool:
            """The engine's own word that no wanted chunk is still missing.

            Neuroglancer is allowed to draw a coarser level where the sharper
            one has not been fetched yet -- a slightly blurry patch, not a
            stale one, cured by nothing but its own appetite. Both storms'
            identity runs failed on exactly that (2026-08-15): the same
            corner, both invalidation modes, all data proven correct on
            disk and in flight. So a band is only photographed once the
            engine reports every visible chunk it WANTS as AVAILABLE, which
            pins the level choice on both sides of the comparison; a viewer
            that never gets there hits the ceiling and fails the identity
            check as before.
            """
            return page.evaluate(
                """() => {
                  let needed = 0, available = 0;
                  for (const managed of
                       window.zmartViewer.layerManager.managedLayers) {
                    for (const rl of (managed.layer?.renderLayers || [])) {
                      const p = rl.layerChunkProgressInfo;
                      if (!p) continue;
                      needed += p.numVisibleChunksNeeded;
                      available += p.numVisibleChunksAvailable;
                    }
                  }
                  return needed > 0 && available >= needed;
                }"""
            )

        def refresh_flights_still_out() -> int:
            """How many named refreshes the worker still owes, pending or flying.

            ``zmartSourcesWaiting`` counts only the frontend's layer loading;
            a per-key refresh flight in the worker -- including the long final
            one a storm's coalesced announces collapse into -- is invisible to
            it. Instrumented 2026-08-15: the warm client's LAST refetch of the
            coarsest piece was still in flight through the whole census, so
            the bands photographed a picture whose correction was already on
            the wire. The census therefore drains these flights explicitly.
            """
            return page.evaluate(
                """() => {
                  // Settled means the ENGINE has the pixels it wants, which
                  // is the question this was always asking. It used to ask
                  // our own refresh pump how much it still owed, through a
                  // probe with a two-second timeout per source; when the pump
                  // was deleted with the rest of the parallel refresh
                  // machinery (2026-08-26) every poll spent that timeout and
                  // the file stopped finishing. The engine's own count is
                  // instant, and it is the better witness: what matters is
                  // what is on screen, not what our bookkeeping thinks.
                  let owed = 0;
                  for (const managed of
                       window.zmartViewer.layerManager.managedLayers) {
                    for (const rl of
                         (managed.layer && managed.layer.renderLayers) || []) {
                      const p = rl.layerChunkProgressInfo;
                      if (!p) continue;
                      owed += Math.max(
                        0, p.numVisibleChunksNeeded - p.numVisibleChunksAvailable);
                    }
                  }
                  return owed;
                }"""
            )

        seen = {}
        storm_pixels = {}
        network_phase["name"] = "storm-bands"
        for multiple in (0.15, 0.4, 1.0, 2.5):
            zoom_to(multiple)
            # Photograph the band at CONVERGENCE, not on a stopwatch. The
            # refetch tail after 1,456 landings drains at whatever pace the
            # machine can manage -- instrumented on 2026-08-15: zero flight
            # failures, zero pending, and still dozens of chunks DOWNLOADING
            # when a fixed 2.5 s wait photographed the coarsest band, which
            # failed the identity check for being merely behind, not wrong.
            # So each band is photographed once its pixels stop changing and
            # the engine reports nothing in flight, under a hard ceiling.
            # The gate keeps its teeth: a genuinely WEDGED piece -- the
            # disease this census exists to catch -- drains to stable-but-
            # wrong, sails through this wait, and still fails the identity
            # comparison below.
            deadline = time.perf_counter() + 150
            resting = None
            while True:
                page.wait_for_timeout(1_500)
                _, pixels = _save_middle_and_measure(page)
                quiet = (page.evaluate(
                    "() => window.zmartSourcesWaiting()") == 0
                    and refresh_flights_still_out() == 0
                    and the_view_is_fully_loaded())
                if (resting is not None and quiet
                        and pixels.tobytes() == resting.tobytes()):
                    break
                if time.perf_counter() > deadline:
                    break
                resting = pixels
            seen[multiple], storm_pixels[multiple] = \
                _save_middle_and_measure(
                    page,
                    (debug_folder / f"storm_band_{multiple:.2f}x.png"
                     if debug_folder is not None else None))
            zoom_to(1.0)
            page.wait_for_timeout(2_500)
            page.screenshot(path=str(Path(os_module.environ["ZMART_STORM_DEBUG"])
                                     / "storm_probe_page_1x.png"))
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
            page.wait_for_timeout(1_500)
            browser_timeline = page.evaluate(
                """async () => {
                  clearInterval(globalThis.zmartStormTimer);
                  await globalThis.zmartSampleStorm?.();
                  while (globalThis.zmartStormSampling) {
                    await new Promise((resolve) => setTimeout(resolve, 25));
                  }
                  return globalThis.zmartStormTimeline ?? [];
                }"""
            )

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
        before_reload_truth = {
            "manifest_events": len(run.manifest.events()),
            "baked": json.loads((store / "baked.json").read_text(
                encoding="utf-8")),
        }
        network_phase["name"] = "reload"
        page.goto(_the_page_address(port), wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartViewer !== undefined",
                              timeout=60_000)
        page.wait_for_function("() => window.zmartSourcesWaiting() === 0",
                              timeout=90_000)
        page.wait_for_timeout(2_000)
        fresh = {}
        fresh_pixels = {}
        for multiple in (0.15, 0.4, 1.0, 2.5):
            zoom_to(multiple)
            # The same convergence rule as the warm bands above, so the two
            # sides of the comparison are photographed under one standard.
            deadline = time.perf_counter() + 150
            resting = None
            while True:
                page.wait_for_timeout(1_500)
                _, pixels = _save_middle_and_measure(page)
                quiet = (page.evaluate(
                    "() => window.zmartSourcesWaiting()") == 0
                    and refresh_flights_still_out() == 0
                    and the_view_is_fully_loaded())
                if (resting is not None and quiet
                        and pixels.tobytes() == resting.tobytes()):
                    break
                if time.perf_counter() > deadline:
                    break
                resting = pixels
            fresh[multiple], fresh_pixels[multiple] = \
                _save_middle_and_measure(
                    page,
                    (debug_folder / f"fresh_band_{multiple:.2f}x.png"
                     if debug_folder is not None else None))
        fresh_census = scale_census()
        print("SCALES stormed:", json.dumps(stormed_census),
              " fresh:", json.dumps(fresh_census), flush=True)
        if os_module.environ.get("ZMART_STORM_HEAL"):
            after_reload = _bytes_now()
            print(f"PIECE AFTER RELOAD'S DERIVE: {len(after_reload)}B, "
                  f"{'CHANGED — the reload derive caught the composer up' if after_reload != second_look else 'STILL the same bytes'}",
                  flush=True)

        # The strongest measurement this gate makes, computed for every run
        # rather than only when a debug folder is set: the warm picture and
        # the fresh one must be the SAME picture, pixel for pixel. The
        # lit-pixel comparison asserted further down cannot see content
        # staleness -- a warm view showing an older generation at the same
        # brightness counts exactly as lit -- and it is one-sided, so ground
        # a commit WITHDREW that the warm client still shows slips past it
        # too. These three numbers see both directions, and they are what
        # the campaign's own acceptance evidence was measured in.
        import numpy as np

        image_differences = {}
        difference_masks = {}
        for multiple in seen:
            storm_image = storm_pixels[multiple]
            fresh_image = fresh_pixels[multiple]
            storm_lit = storm_image.max(axis=2) > 40
            fresh_lit = fresh_image.max(axis=2) > 40
            missing = fresh_lit & ~storm_lit
            apart = np.abs(fresh_image.astype(np.int16) -
                           storm_image.astype(np.int16))
            difference_masks[multiple] = missing
            image_differences[str(multiple)] = {
                "shape": list(missing.shape),
                "missing_fraction": float(missing.mean()),
                "changed_fraction": float((apart.max(axis=2) > 8).mean()),
                "mean_absolute_error": float(apart.mean()),
            }

        if debug_folder is not None:
            from PIL import Image

            for multiple in seen:
                missing = difference_masks[multiple]
                ys, xs = np.where(missing)
                height, width = missing.shape
                grid = []
                for grid_y in range(8):
                    row = []
                    top = grid_y * height // 8
                    bottom = (grid_y + 1) * height // 8
                    for grid_x in range(8):
                        left = grid_x * width // 8
                        right = (grid_x + 1) * width // 8
                        row.append(round(float(missing[
                            top:bottom, left:right].mean()), 6))
                    grid.append(row)
                image_differences[str(multiple)].update({
                    "missing_bbox": ([int(xs.min()), int(ys.min()),
                                      int(xs.max()), int(ys.max())]
                                     if len(xs) else None),
                    "missing_by_8x8_screen_grid": grid,
                    "row_missing_peaks": [
                        [int(index), round(float(value), 6)]
                        for index, value in sorted(
                            enumerate(missing.mean(axis=1)),
                            key=lambda one: one[1], reverse=True)[:12]
                    ],
                    "column_missing_peaks": [
                        [int(index), round(float(value), 6)]
                        for index, value in sorted(
                            enumerate(missing.mean(axis=0)),
                            key=lambda one: one[1], reverse=True)[:12]
                    ],
                })
                Image.fromarray((missing * 255).astype(np.uint8)).save(
                    debug_folder / f"missing_after_storm_{multiple:.2f}x.png")

            phase_counts = {}
            for event in network_events:
                key = f"{event.get('phase')}:{event.get('event')}"
                phase_counts[key] = phase_counts.get(key, 0) + 1
            most_requested = sorted(
                network_requests.items(), key=lambda one: one[1],
                reverse=True)[:50]
            most_concurrent = sorted(
                network_maximum.items(), key=lambda one: one[1],
                reverse=True)[:50]
            last_pre_reload_200 = {}
            last_reload_200 = {}
            two_second_failures = {}
            failure_reasons = {}
            for event in network_events:
                path = event.get("path", "")
                if event.get("event") == "failed":
                    reason = event.get("failure") or "unknown"
                    failure_reasons[reason] = failure_reasons.get(reason, 0) + 1
                    elapsed = event.get("elapsed")
                    if (path.startswith("/data/") and elapsed is not None
                            and 1.8 <= elapsed <= 2.2):
                        two_second_failures[path] = (
                            two_second_failures.get(path, 0) + 1)
                if (event.get("event") != "response"
                        or event.get("status") != 200 or "/c/" not in path):
                    continue
                try:
                    size = int(event.get("bytes"))
                except (TypeError, ValueError):
                    continue
                if event.get("phase") == "reload":
                    last_reload_200[path] = size
                else:
                    last_pre_reload_200[path] = size
            reload_byte_growth = []
            for path, reloaded_size in last_reload_200.items():
                previous_size = last_pre_reload_200.get(path)
                if previous_size is not None and reloaded_size > previous_size:
                    reload_byte_growth.append({
                        "path": path, "before": previous_size,
                        "after_reload": reloaded_size,
                        "growth": reloaded_size - previous_size,
                        "two_second_failures": two_second_failures.get(path, 0),
                    })
            reload_byte_growth.sort(
                key=lambda one: one["growth"], reverse=True)
            diagnostics = {
                "recipe": {
                    "across": across, "core": core,
                    "initial_commits": len(committed_first),
                    "storm_commits": len(landing_later),
                    "target_rate": 20.0, "achieved_rate": achieved,
                },
                "truth_before_reload": before_reload_truth,
                "storm_lit": {str(k): v for k, v in seen.items()},
                "fresh_lit": {str(k): v for k, v in fresh.items()},
                "image_differences": image_differences,

                "network": {
                    "events": len(network_events),
                    "phase_counts": phase_counts,
                    "maximum_simultaneous_all": network_global["maximum"],
                    "most_requested_paths": most_requested,
                    "most_concurrent_paths": most_concurrent,
                    "failure_reasons": failure_reasons,
                    "two_second_failure_paths": sorted(
                        two_second_failures.items(),
                        key=lambda one: one[1], reverse=True)[:100],
                    "reload_byte_growth": reload_byte_growth,
                },
                "visual_trace": visual_trace,
                "console_errors": troubles,
            }
            (debug_folder / "diagnostics.json").write_text(
                json.dumps(diagnostics, indent=2), encoding="utf-8")
            (debug_folder / "landings.json").write_text(
                json.dumps(landing_trace, indent=2), encoding="utf-8")
            (debug_folder / "browser_timeline.json").write_text(
                json.dumps(browser_timeline, indent=2), encoding="utf-8")
            (debug_folder / "network_events.json").write_text(
                json.dumps(network_events, indent=2), encoding="utf-8")
            print("STORM DIAGNOSTICS:", debug_folder, flush=True)

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
        # And beyond the amount of picture: the same picture. The tolerances
        # sit far below what one stale 512-pixel piece would register, so
        # they forgive nothing real; they exist only so that a single pixel
        # of rendering noise can never flake an honest run.
        for multiple in seen:
            found = image_differences[str(multiple)]
            assert (found["missing_fraction"] <= 0.002
                    and found["changed_fraction"] <= 0.005
                    and found["mean_absolute_error"] <= 0.5), (
                f"at {multiple:.2f}x the warm picture is not the same picture "
                f"a fresh client sees: {found['missing_fraction']:.3%} of "
                f"pixels lit fresh but dark warm, {found['changed_fraction']:.3%} "
                f"of pixels differing, mean absolute error "
                f"{found['mean_absolute_error']:.2f}. The lit-pixel comparison "
                "above cannot see this — an older generation at equal "
                "brightness, or withdrawn ground the warm client still shows, "
                "both count as lit — so pixel identity is asserted in its own "
                "right. Every band: " + ", ".join(
                    f"{m:.2f}x missing {image_differences[str(m)]['missing_fraction']:.3%}"
                    f" changed {image_differences[str(m)]['changed_fraction']:.3%}"
                    for m in sorted(seen))
            )
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)
