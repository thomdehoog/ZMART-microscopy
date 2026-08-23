"""Real-browser qualification for manifest-driven live refresh.

These tests intentionally require Chromium in CI. They exercise the shipped
backend, SSE connection, React controller and Neuroglancer rather than mocks.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from urllib.parse import urlsplit

import numpy as np
import live_config
import server as server_module
from pixels import fraction_lit, image_middle
from server import make_server

from zmart_live.coordinator import LivePublisher
from zmart_live.model import GridCell
from zmart_live.profiles import plan_the_writing
from zmart_live.tests.test_coordinator import FRAME, some_specimen
from zmart_live.tests.test_gateway import a_live_run, prepare_without_publishing
from driving import pick_colormap  # noqa: E402

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
        store="views/live/live.ome.zarr",
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
        arg=[dataset, revision],
        timeout=60_000,
    )


def _wait_for_picture(page):
    page.wait_for_function(_SETTLED, timeout=60_000)
    page.wait_for_timeout(1200)


def _set_range(page, label, value):
    page.evaluate(
        """([label, value]) => {
          const element = document.querySelector(`[aria-label="${label}"]`);
          // Say which control is missing. Without this the next line calls a
          // setter on null and the browser reports "Illegal invocation", which
          // names neither the control nor the fact that it was renamed --
          // exactly what happened when the panel's black/white became min/max.
          if (!element) {
            throw new Error(`no control is labelled "${label}"`);
          }
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
          min: Number(document.querySelector(
            '[aria-label="min live (linked) channel 0"]').value),
          max: Number(document.querySelector(
            '[aria-label="max live (linked) channel 0"]').value),
          opacity: Number(document.querySelector(
            '[aria-label="opacity live (linked) channel 0"]').value),
          group: window.zmartConfig.groups[0],
          // What the channel is painted with, read off the square itself.
          // The square IS the control now -- press it and the list of
          // colours opens -- so it carries no words to read, and what it
          // shows is a flat colour or a whole run of them.
          lut: (() => {
            const square = document.querySelector(
              '[aria-label="colour live (linked) channel 0"]');
            const seen = getComputedStyle(square);
            return seen.backgroundImage !== 'none'
              ? seen.backgroundImage : seen.backgroundColor;
          })(),
        })"""
    )


def _tune(page):
    page.locator(
        "[aria-label='toggle live (linked) channel 0']"
    ).locator("xpath=../..").click()
    _set_range(page, "min live (linked) channel 0", 100)
    _set_range(page, "max live (linked) channel 0", 3500)
    _set_range(page, "opacity live (linked) channel 0", 0.83)
    pick_colormap(page, "live (linked) channel 0", "viridis")
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
        }"""
    )
    page.wait_for_timeout(500)


def _assert_operator_state(before, after):
    assert after["layers"] == before["layers"]
    assert after["layerState"] == before["layerState"]
    assert np.allclose(after["position"], before["position"])
    assert after["zoom"] == before["zoom"]
    assert after["perspectiveZoom"] == before["perspectiveZoom"]
    assert after["min"] == 100
    assert after["max"] == 3500
    assert after["opacity"] == 0.83
    assert after["group"] == before["group"]
    # Viridis, said the way the square says it: a run of colours rather than
    # the word. What matters is that the choice made before the commit is
    # still the choice after it, so it is compared against what was read
    # then, with a check that it really is a colour map and not a flat
    # colour left over from the default.
    assert "gradient" in after["lut"], (
        f"the channel is painted {after['lut']}, which is not the colour map "
        "that was chosen before the run moved on"
    )
    assert after["lut"] == before["lut"]


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
            assert initial_lit > 0.04

            _tune(page)
            before = _operator_state(page)
            a_lit = fraction_lit(page)
            assert a_lit > 0.04
            stable_urls = [
                url for row in page.evaluate("() => window.zmartConfig.layers")
                for url in row["sources"]
            ]

            prepare_without_publishing(run, "posB", 3000)
            page.wait_for_timeout(1800)
            still_lit = fraction_lit(page)
            assert abs(still_lit - a_lit) < 0.04
            assert still_lit > 0.04
            assert page.evaluate("() => window.zmartConfig.liveState.runs[0].revision") == 1

            commit_mark = len(requests)
            run.publish("posB")
            _wait_for_revision(page, 2)
            _wait_for_picture(page)
            assert fraction_lit(page) > still_lit + 0.05
            # The one view a commit advances under the current scene model: a
            # run publishes positions and its single linked overview, served
            # from the baked picture (see VIEW_ROLES in zmart_live/scene.py).
            # The earlier model's seamless and non_seamless pair, which this
            # set once named, no longer exists.
            assert set(page.evaluate("() => window.zmartSourceRefreshing.sources")) == {
                "0/gateway-run/linked/live",
            }
            _assert_operator_state(before, _operator_state(page))
            assert [
                url for row in page.evaluate("() => window.zmartConfig.layers")
                for url in row["sources"]
            ] == stable_urls
            affected = [path for path in requests[commit_mark:] if path.startswith("/data/")]
            assert any(live_config.LIVE_PICTURE in path for path in affected)

            mean_before = float(image_middle(page).mean())
            replacement = run.replace_a_position("posA", some_specimen(3500))
            assert replacement.position_generation == 1
            _wait_for_revision(page, 3)
            _wait_for_picture(page)
            assert float(image_middle(page).mean()) > mean_before + 1.0
            assert [
                url for row in page.evaluate("() => window.zmartConfig.layers")
                for url in row["sources"]
            ] == stable_urls
            _assert_operator_state(before, _operator_state(page))
        finally:
            page.close()


def test_time_is_never_offered_on_a_single_moment_run(
    browser, built_dist, tmp_path
):
    """A run with one moment of room has no time axis anywhere on screen.

    Not offered goes further than a missing slider: the engine's own space
    has no time axis at all, so there is no way — not even from a console —
    to steer the view onto a moment that holds nothing. This used to force
    the position to t=1 and watch the picture dim; the axis it forced does
    not exist, which is the stronger form of the same promise.

    A run that keeps room for SEVERAL moments no longer reaches this page
    at all: the declare door refuses it loudly rather than serving its
    first moment as the whole run (see
    test_manifest_driven_refresh.test_a_timelapse_run_is_refused_loudly_not_silently_truncated).
    The moment-by-moment promises this test once carried — uncommitted time
    never offered, committed reach reported, a landing in a time gap never
    flushing the decoded cache — are ordered work of the c-and-t chapter
    (PLAN_the_picture_grows_c_and_t.md) and return with the served axis.
    """
    run = a_live_run(tmp_path)
    run.write_and_publish("posA", some_specimen(1500))
    with _serving(built_dist, run) as address:
        page = browser.new_page(viewport={"width": 1200, "height": 900})
        try:
            _open(page, address, 1)
            _wait_for_picture(page)
            assert fraction_lit(page) > 0.04
            assert page.get_by_label("t position", exact=True).count() == 0
            assert page.evaluate(
                """() => Array.from(
                  window.zmartViewer.navigationState.position.coordinateSpace.value.names
                )"""
            ) == ["z", "y", "x"]
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
        {"path": one.folder, "stores": ["views/live/live.ome.zarr"], "name": "one"},
        {"path": two.folder, "stores": ["views/live/live.ome.zarr"], "name": "two"},
    ]
    with _serving(built_dist, loads=loads) as address:
        page = browser.new_page(viewport={"width": 1200, "height": 900})
        requested = []
        page.on("request", lambda request: requested.append(urlsplit(request.url).path))
        try:
            _open(page, address, 1)
            _wait_for_revision(page, 1, dataset=1)
            _wait_for_picture(page)
            mark = len(requested)
            one.write_and_publish("posB", some_specimen(3000))
            _wait_for_revision(page, 2, dataset=0)
            _wait_for_picture(page)
            after = [path for path in requested[mark:] if path.startswith("/data/")]
            assert after
            assert all(path.startswith("/data/0/") for path in after)
            # The one view a commit advances under the current scene model: a
            # run publishes positions and its single linked overview (see
            # VIEW_ROLES in zmart_live/scene.py), so run-one's commit refreshes
            # exactly that identity and nothing of run-two. The earlier model's
            # seamless and non_seamless pair, which this set once named, no
            # longer exists.
            assert set(page.evaluate("() => window.zmartSourceRefreshing.sources")) == {
                "0/run-one/linked/live",
            }
        finally:
            page.close()


def test_suppressed_sse_hint_is_recovered_by_conditional_check(
    browser, built_dist, tmp_path, monkeypatch
):
    run = a_live_run(tmp_path)
    with _serving(built_dist, run) as address:
        page = browser.new_page(viewport={"width": 1200, "height": 900})
        page.add_init_script("globalThis.zmartLiveCheckMs = 500")
        try:
            _open(page, address, 0)
            monkeypatch.setattr(
                server_module.Announcements,
                "say_something_changed",
                lambda self, **kwargs: 0,
            )
            run.write_and_publish("posA", some_specimen(1700))
            _wait_for_revision(page, 1)
            _wait_for_picture(page)
            assert fraction_lit(page) > 0.04

            run.write_and_publish("posB", some_specimen(2900))
            _wait_for_revision(page, 2)
            _wait_for_picture(page)
            assert fraction_lit(page) > 0.08
        finally:
            page.close()


# A browser gate named test_filling_a_committed_time_gap_does_not_globally
# _flush_decoded_cache lived here until 2026-08-17. Its claim — a landing in
# a committed time gap heals the ranges without tripping the whole-source
# decoded-cache flush (zmartLetGo.times unchanged) — needs a timelapse run
# on screen, and a timelapse run is now refused at the declare door until
# the served picture grows a time axis. The claim is recorded as ordered
# work in PLAN_the_picture_grows_c_and_t.md (the slider section) and the
# gate returns with the axis, asserting pixels as well as ranges.
