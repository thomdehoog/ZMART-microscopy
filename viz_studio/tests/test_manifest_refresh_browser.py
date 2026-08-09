"""The committed marker refreshes the real production page without a reload.

These tests use the shipped backend, its SSE connection, the React controller
and Neuroglancer.  They intentionally skip on a machine without Chromium; the
test summary says plainly that no pixel claim was verified in that case.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from urllib.parse import urlsplit

import numpy as np
from pixels import fraction_lit, image_middle
from server import make_server

from zmart_live.coordinator import LivePublisher
from zmart_live.model import GridCell
from zmart_live.profiles import plan_the_writing
from zmart_live.tests.test_coordinator import FRAME, some_specimen
from zmart_live.tests.test_gateway import a_live_run, prepare_without_publishing

_SETTLED = """() => {
  const v = window.zmartViewer;
  if (!v) return false;
  let needed = 0, available = 0;
  for (const managed of v.layerManager.managedLayers) {
    for (const rl of (managed.layer?.renderLayers || [])) {
      const p = rl.layerChunkProgressInfo;
      if (p) { needed += p.numVisibleChunksNeeded; available += p.numVisibleChunksAvailable; }
    }
  }
  return available > 0 && available >= needed;
}"""


def _run(folder, run_id, *, timepoints=1):
    profile, _ = plan_the_writing("overview", frame=FRAME, z_planes=1)
    return LivePublisher(
        folder,
        profile,
        run_id=run_id,
        cells={GridCell(0, 0): "posA", GridCell(0, 1): "posB"},
        timepoints=timepoints,
    )


@contextmanager
def _serving(built_dist, run=None, *, loads=None):
    server = make_server(
        port=0,
        data_dir=run.folder if run is not None else loads[0]["path"],
        site_dir=built_dist,
        store="views/overview-seamless.ome.zarr",
        loads=loads,
        window=(0, 4095),
        live=True,
        allow_open=False,
        allow_selection=True,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _open(page, address, revision):
    page.goto(address, wait_until="domcontentloaded")
    page.wait_for_function("() => window.zmartViewer !== undefined", timeout=60_000)
    _wait_for_revision(page, revision)


def _wait_for_revision(page, revision, *, dataset=0):
    page.wait_for_function(
        """([dataset, revision]) =>
          window.zmartConfig?.liveState?.runs?.find((run) => run.dataset === dataset)?.revision
            === revision""",
        [dataset, revision],
        timeout=60_000,
    )


def _wait_for_picture(page):
    page.wait_for_function(_SETTLED, timeout=60_000)
    page.wait_for_timeout(1200)


def _set_range(page, label, value):
    page.evaluate(
        """([label, value]) => {
          const element = document.querySelector(`[aria-label="${label}"]`);
          const set = Object.getOwnPropertyDescriptor(
            window.HTMLInputElement.prototype, "value").set;
          set.call(element, String(value));
          element.dispatchEvent(new Event("input", {bubbles: true}));
          element.dispatchEvent(new Event("change", {bubbles: true}));
        }""",
        [label, value],
    )


def _operator_state(page):
    return page.evaluate(
        """() => ({
          position: Array.from(window.zmartViewer.navigationState.position.value),
          zoom: window.zmartViewer.navigationState.zoomFactor.value,
          perspectiveZoom: window.zmartViewer.perspectiveNavigationState.zoomFactor.value,
          layers: window.zmartViewer.layerManager.managedLayers.map((managed) => managed.name),
          layerState: JSON.parse(JSON.stringify(window.zmartLayerState)),
          black: Number(document.querySelector(
            '[aria-label="black overview (seamless) channel 0"]').value),
          white: Number(document.querySelector(
            '[aria-label="white overview (seamless) channel 0"]').value),
          opacity: Number(document.querySelector(
            '[aria-label="opacity overview (seamless) channel 0"]').value),
          groupOpacity: Number(document.querySelector(
            '[aria-label="opacity group overview"]').value),
          lut: document.querySelector(
            '[aria-label="colour map overview (seamless) channel 0"]').value,
          target: window.zmartAnnotationSource?.get("publication-target") !== undefined,
          targetSourceKept: window.zmartAnnotationSource?.__publicationKeeper === true,
          markedLayers: window.zmartViewer.layerManager.managedLayers
            .filter((managed) => managed.__publicationKeeper).length,
        })"""
    )


def _tune_and_mark(page):
    seamless = page.locator(
        "[aria-label='toggle overview (seamless) channel 0']"
    ).locator("xpath=../..")
    seamless.click()
    _set_range(page, "black overview (seamless) channel 0", 100)
    _set_range(page, "white overview (seamless) channel 0", 3500)
    _set_range(page, "opacity overview (seamless) channel 0", 0.83)
    _set_range(page, "opacity group overview", 0.91)
    page.get_by_label("colour map overview (seamless) channel 0").select_option("viridis")
    page.wait_for_function("() => window.zmartAnnotationSource !== undefined")
    page.evaluate(
        """() => {
          const position = window.zmartViewer.navigationState.position;
          const space = position.coordinateSpace.value;
          const moved = Float32Array.from(position.value);
          const x = space.names.indexOf("x");
          if (x >= 0) moved[x] += 32;
          position.value = moved;
          window.zmartViewer.navigationState.zoomFactor.value *= 1.08;
          const reference = window.zmartAnnotationSource.add({
            id: "publication-target", type: 2, description: "keep me",
            pointA: Float32Array.from(position.value),
            pointB: Float32Array.from(position.value, (value) => value + 1),
            properties: [],
          }, true);
          reference.dispose();
          window.zmartAnnotationSource.__publicationKeeper = true;
          for (const managed of window.zmartViewer.layerManager.managedLayers) {
            managed.__publicationKeeper = true;
          }
        }"""
    )
    page.wait_for_timeout(500)


def _assert_operator_state_is(the_same, before):
    assert the_same["layers"] == before["layers"]
    assert the_same["layerState"] == before["layerState"]
    assert np.allclose(the_same["position"], before["position"])
    assert the_same["zoom"] == before["zoom"]
    assert the_same["perspectiveZoom"] == before["perspectiveZoom"]
    assert the_same["black"] == 100
    assert the_same["white"] == 3500
    assert the_same["opacity"] == 0.83
    assert the_same["groupOpacity"] == 0.91
    assert the_same["lut"] == "viridis"
    assert the_same["target"] and the_same["targetSourceKept"]
    assert the_same["markedLayers"] == len(before["layers"])


def test_positions_and_replacement_appear_from_commits_and_keep_operator_state(
    browser, built_dist, tmp_path
):
    run = a_live_run(tmp_path)
    with _serving(built_dist, run) as address:
        page = browser.new_page(viewport={"width": 1200, "height": 900})
        requests = []
        page.on("request", lambda request: requests.append(urlsplit(request.url).path))
        page.add_init_script("globalThis.zmartLiveCheckMs = 500")
        try:
            _open(page, address, 0)

            run.write_and_publish("posA", some_specimen(1700))
            _wait_for_revision(page, 1)
            _wait_for_picture(page)
            initial_lit = fraction_lit(page)
            assert initial_lit > 0.04, (
                "position A was committed but the production page remained black "
                f"({initial_lit:.3f})"
            )

            _tune_and_mark(page)
            before = _operator_state(page)
            a_lit = fraction_lit(page)
            assert a_lit > 0.04, "the operator's settings must leave A measurably bright"
            stable_urls = [url for row in page.evaluate("() => window.zmartConfig.layers")
                           for url in row["sources"]]

            # Several unchanged conditional checks must be entirely invisible to
            # Neuroglancer: no metadata, no chunk and no refresh pass.
            idle_mark = len(requests)
            refresh_before = page.evaluate("() => window.zmartSourceRefreshing.passes")
            page.wait_for_timeout(1800)
            assert not [path for path in requests[idle_mark:] if path.startswith("/data/")]
            assert page.evaluate("() => window.zmartSourceRefreshing.passes") == refresh_before
            assert any(path == "/api/live-state" for path in requests[idle_mark:])

            prepare_without_publishing(run, "posB", 3000)
            page.wait_for_timeout(1800)
            still_lit = fraction_lit(page)
            assert abs(still_lit - a_lit) < 0.04, (
                "uncommitted B changed the picture, or A disappeared: "
                f"{a_lit:.3f} -> {still_lit:.3f}"
            )
            assert still_lit > 0.04, "A must remain measurably bright while B is withheld"
            assert page.evaluate(
                "() => window.zmartConfig.liveState.runs[0].revision"
            ) == 1

            commit_mark = len(requests)
            run.publish("posB")
            _wait_for_revision(page, 2)
            _wait_for_picture(page)
            both_lit = fraction_lit(page)
            assert both_lit > still_lit + 0.05, (
                f"committed B did not appear automatically: {still_lit:.3f} -> {both_lit:.3f}"
            )
            refreshed = set(page.evaluate("() => window.zmartSourceRefreshing.sources"))
            assert refreshed == {
                "0/gateway-run/non_seamless/overview",
                "0/gateway-run/seamless/overview",
            }, "raw and seamless must advance together, and nothing else may refresh"
            assert page.evaluate("() => window.zmartLayersReshaped") == 0
            _assert_operator_state_is(_operator_state(page), before)
            assert [url for row in page.evaluate("() => window.zmartConfig.layers")
                    for url in row["sources"]] == stable_urls
            affected = [path for path in requests[commit_mark:] if path.startswith("/data/")]
            assert any("overview-raw.zarr" in path for path in affected)
            assert any("overview-seamless.ome.zarr" in path for path in affected)

            # Replacement is another explicit publication generation, not a new
            # URL or layer. It must drive the identical narrow refresh path.
            mean_before = float(image_middle(page).mean())
            replacement = run.replace_a_position("posA", some_specimen(3500))
            assert replacement.position_generation == 1
            _wait_for_revision(page, 3)
            _wait_for_picture(page)
            assert float(image_middle(page).mean()) > mean_before + 1.0
            assert [url for row in page.evaluate("() => window.zmartConfig.layers")
                    for url in row["sources"]] == stable_urls
            assert set(page.evaluate("() => window.zmartSourceRefreshing.sources")) == refreshed
            assert page.evaluate("() => window.zmartLayersReshaped") == 0
            _assert_operator_state_is(_operator_state(page), before)
        finally:
            page.close()


def test_uncommitted_time_is_not_offered_and_cached_empty_time_refreshes(
    browser, built_dist, tmp_path
):
    run = a_live_run(tmp_path, timepoints=2)
    run.write_and_publish("posA", some_specimen(1500))
    with _serving(built_dist, run) as address:
        page = browser.new_page(viewport={"width": 1200, "height": 900})
        try:
            _open(page, address, 1)
            _wait_for_picture(page)
            t0_lit = fraction_lit(page)
            assert t0_lit > 0.04, "committed t=0 must be a real bright positive control"
            assert page.get_by_label("t position").count() == 0

            # Ask Neuroglancer for the declared-but-uncommitted moment directly.
            # This deliberately caches an empty spatial answer before publication.
            page.evaluate(
                """() => {
                  const position = window.zmartViewer.navigationState.position;
                  const space = position.coordinateSpace.value;
                  const t = space.names.indexOf("t");
                  const moved = Float32Array.from(position.value);
                  moved[t] = 1;
                  position.value = moved;
                }"""
            )
            page.wait_for_timeout(1500)
            empty = fraction_lit(page)
            assert empty < t0_lit - 0.03
            page.evaluate(
                """() => {
                  const position = window.zmartViewer.navigationState.position;
                  const t = position.coordinateSpace.value.names.indexOf("t");
                  const moved = Float32Array.from(position.value); moved[t] = 0;
                  position.value = moved;
                }"""
            )
            page.wait_for_timeout(1000)
            assert fraction_lit(page) > 0.04

            prepare_without_publishing(run, "posA", 2800, moment=1)
            page.wait_for_timeout(1500)
            assert page.get_by_label("t position").count() == 0
            assert page.evaluate(
                "() => window.zmartConfig.layers[0].committedTimeRanges"
            ) == [{"start": 0, "stop": 1}]

            run.publish("posA", timepoint=1)
            _wait_for_revision(page, 2)
            page.get_by_label("t position").wait_for(timeout=30_000)
            assert page.get_by_label("t position").get_attribute("max") == "1"
            assert page.evaluate(
                "() => window.zmartConfig.layers[0].committedTimeRanges"
            ) == [{"start": 0, "stop": 2}]
            _set_range(page, "t position", 1)
            _wait_for_picture(page)
            assert fraction_lit(page) > 0.04, (
                "t=1 stayed cached as empty after its committed source revision advanced"
            )
        finally:
            page.close()


def test_one_run_commit_makes_no_requests_for_an_unrelated_live_run(
    browser, built_dist, tmp_path
):
    one = _run(tmp_path / "one", "run-one")
    two = _run(tmp_path / "two", "run-two")
    one.write_and_publish("posA", some_specimen(1200))
    two.write_and_publish("posA", some_specimen(2200))
    loads = [
        {"path": one.folder, "stores": ["views/overview-seamless.ome.zarr"], "name": "one"},
        {"path": two.folder, "stores": ["views/overview-seamless.ome.zarr"], "name": "two"},
    ]
    with _serving(built_dist, loads=loads) as address:
        page = browser.new_page(viewport={"width": 1200, "height": 900})
        requested = []
        page.on("request", lambda request: requested.append(urlsplit(request.url).path))
        try:
            _open(page, address, 1)
            _wait_for_revision(page, 1, dataset=1)
            _wait_for_picture(page)
            page.wait_for_timeout(1000)
            mark = len(requested)

            one.write_and_publish("posB", some_specimen(3000))
            _wait_for_revision(page, 2, dataset=0)
            _wait_for_picture(page)
            after = [path for path in requested[mark:] if path.startswith("/data/")]
            assert after, "the affected aggregate sources were never fetched"
            assert all(path.startswith("/data/0/") for path in after), (
                f"an unrelated acquisition was fetched after run-one committed: {after[:5]}"
            )
            assert set(page.evaluate("() => window.zmartSourceRefreshing.sources")) == {
                "0/run-one/non_seamless/overview",
                "0/run-one/seamless/overview",
            }
        finally:
            page.close()


def test_lost_sse_hint_is_recovered_by_conditional_check_and_eventsource_reconnects(
    browser, built_dist, tmp_path
):
    run = a_live_run(tmp_path)
    with _serving(built_dist, run) as address:
        page = browser.new_page(viewport={"width": 1200, "height": 900})
        events = []
        page.on(
            "request",
            lambda request: events.append(request.url)
            if urlsplit(request.url).path == "/api/events" else None,
        )
        page.add_init_script("globalThis.zmartLiveCheckMs = 500")
        try:
            _open(page, address, 0)
            assert events, "the immediate SSE path was never opened"

            # Drop the established SSE socket while the commit lands, then keep
            # only its reconnect request blocked. Ordinary HTTP is back online,
            # so the conditional revision check must recover publication without
            # receiving a hint.
            page.context.set_offline(True)
            run.write_and_publish("posA", some_specimen(1700))
            page.route("**/api/events", lambda route: route.abort())
            page.context.set_offline(False)
            _wait_for_revision(page, 1)
            _wait_for_picture(page)
            assert fraction_lit(page) > 0.04

            # EventSource retries the broken connection on its own. Releasing the
            # route proves it becomes healthy again; the state above was already
            # recovered from committed truth by the fallback.
            page.unroute("**/api/events")
            page.wait_for_timeout(3500)
            assert len(events) >= 2, "EventSource did not attempt to reconnect"

            run.write_and_publish("posB", some_specimen(2900))
            _wait_for_revision(page, 2)
            _wait_for_picture(page)
            assert fraction_lit(page) > 0.08
        finally:
            page.close()
