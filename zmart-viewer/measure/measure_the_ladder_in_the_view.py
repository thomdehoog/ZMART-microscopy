"""What opening a survey costs the browser, up a ladder of rung sizes.

The viewer opens a folder of positions by composing them into one picture
(`_the_scene_behind_a_run` in the server), so however many positions the
survey holds, the browser is handed a single image. The claim behind that
door is that the browser's work then follows the *screen*, not the survey —
and a claim is worth a measurement, so this climbs a ladder of square grids
(4, 16, 64, 256, 1024 positions, written by `app/server/make_ladder_stores.py`,
each position three channels and four planes) and counts, at every rung:

  1. how long the server takes to compose and open the folder,
  2. how long until the first pixels are on screen,
  3. how long until the picture has settled — every source resolved and no
     new request for two seconds,
  4. how many ``/data/`` requests the page made getting there, and that
     count divided by the positions: **the churn number**, requests a
     position.

After settling, the view is zoomed out until the whole survey fits, the
requests that zoom sets off are counted separately, and what the engine is
then holding is read through the ZMART chunk probe. A screenshot of the
fitted view lands in ``/tmp/ladder_rung_<N>.png`` — look at them, because a
request count can be satisfied by a black screen and an inspected picture
cannot.

Run it from the top of the repository, whole ladder or chosen rungs::

    python zmart-viewer/measure_the_ladder_in_the_view.py
    python zmart-viewer/measure_the_ladder_in_the_view.py 4 64

Each rung gets a server of its own on a free port and a browser of its own,
so no rung is warmed by the one before it. Absolute seconds belong to the
machine that measured them; the shape — whether the churn number falls as
the survey grows — is what carries.
"""

from __future__ import annotations

import json
import sys
import threading
import time
import traceback
import urllib.request
from pathlib import Path

_VIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_VIZ / "app" / "server"))
sys.path.insert(0, str(_VIZ / "tests"))

from playwright.sync_api import sync_playwright  # noqa: E402

from make_ladder_stores import RUNGS, a_rung_of  # noqa: E402
from pixels import fraction_lit  # noqa: E402
from server import make_server  # noqa: E402

# The picture has settled when nothing new has been asked for this long.
QUIET_S = 2.0

# The longest a rung may take from page load to settled before it is called
# a failure and the ladder moves on.
PATIENCE_S = 600

# Whether every source the viewer holds has been resolved — read, or failed —
# rather than merely handed over. The composing door hands the page ONE
# picture, so this list is short whatever the rung; waiting on it as well as
# on `zmartSourcesWaiting()` is the honest pair of conditions, for the reason
# measured in `measure_the_frame_rate_of_a_linked_view.py`: the waiting count
# empties when the last source is handed to the engine, not when it is read.
SETTLED_STATE = """() => {
  if (window.zmartViewer === undefined) return {ready: false};
  const sources = window.zmartViewer.layerManager.managedLayers
    .filter((managed) => managed.layer && managed.layer.type === 'image')
    .flatMap((managed) => managed.layer.dataSources);
  return {
    ready: true,
    waiting: window.zmartSourcesWaiting ? window.zmartSourcesWaiting() : null,
    sources: sources.length,
    resolved: sources.length > 0
      && sources.every((s) => s.loadState !== undefined),
  };
}"""

# Zoom out until the whole picture fits on the screen, read from the
# coordinate space the picture itself declared rather than computed from the
# rung size here — so the same lines work whatever the rung. The zoom factor
# is in voxels to the screen pixel, the same convention
# `measure_a_run_of_positions._show_the_whole_run` uses, so the span is left
# in voxels rather than converted to micrometres.
FIT_THE_WHOLE_PICTURE = """() => {
  const view = window.zmartViewer;
  const space = view.navigationState.position.coordinateSpace.value;
  const position = view.navigationState.position.value;
  let widest = 0;
  for (const axis of ['x', 'y']) {
    const at = space.names.indexOf(axis);
    if (at < 0) continue;
    const span = space.bounds.upperBounds[at] - space.bounds.lowerBounds[at];
    position[at] = space.bounds.lowerBounds[at] + span / 2;
    widest = Math.max(widest, span);
  }
  view.navigationState.position.changed.dispatch();
  const canvas = view.display.canvas;
  const room = Math.min(canvas.width, canvas.height);
  view.navigationState.zoomFactor.value = (widest / room) * 1.1;
  return widest;
}"""

# What the engine's chunk sources are actually holding, summed across every
# source, through the read-only probe the neuroglancer patch installs
# (`ChunkSource.zmartProbe` in `frontend/scripts/patch_neuroglancer.mjs`).
# `held` is chunks the worker knows; `byState` says how many of those are
# downloaded, on the GPU, or merely queued.
WHAT_IS_HELD = """async () => {
  const together = {sources: 0, held: 0, byState: {}};
  for (const held of window.zmartViewer.chunkManager.rpc.objects.values()) {
    if (!held || typeof held.invalidateCache !== 'function') continue;
    let answer;
    try {
      answer = await held.rpc.promiseInvoke(
        'ChunkSource.zmartProbe', {source: held.rpcId});
    } catch { continue; }
    const probe = answer?.value ?? answer;
    if (!probe || probe.held === undefined) continue;
    together.sources += 1;
    together.held += probe.held;
    for (const [state, count] of Object.entries(probe.byState || {})) {
      together.byState[state] = (together.byState[state] || 0) + count;
    }
  }
  return together;
}"""


def _post_open(port: int, folder: Path) -> dict:
    """Ask the server to open the folder, the way a workflow would."""
    body = json.dumps({"path": str(folder)}).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/stores/open", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=PATIENCE_S) as answer:
        return json.loads(answer.read())


def _wait_until_quiet(page, sink: dict, since: float, patience: float) -> None:
    """Wait until nothing new has been asked for in QUIET_S seconds."""
    deadline = time.perf_counter() + patience
    while time.perf_counter() < deadline:
        if time.perf_counter() - max(sink["last"], since) >= QUIET_S:
            return
        page.wait_for_timeout(150)
    raise TimeoutError(f"requests were still arriving after {patience:.0f}s")


def measure_a_rung(count: int, built: Path) -> dict:
    """Open one rung in a fresh server and browser, and say what it cost."""
    rung = a_rung_of(count)

    # Nothing is opened at startup (`loads=[]`): the rung goes in through
    # `/api/stores/open`, the same door a workflow uses, so the compose is
    # part of what is timed. Static mode, because the rung is finished data.
    server = make_server(port=0, data_dir=rung, site_dir=built, loads=[],
                         live=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    row: dict = {"positions": count}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            args=["--use-gl=angle", "--use-angle=swiftshader",
                  "--ignore-gpu-blocklist"])
        page = browser.new_page(viewport={"width": 900, "height": 700})
        # Every request for picture, and when the last one was heard. The
        # page asks for descriptions and pieces alike under ``/data/``, so
        # this count is the whole of what opening cost the wire.
        sink = {"data": 0, "last": 0.0}

        def heard(request) -> None:
            if "/data/" in request.url:
                sink["data"] += 1
                sink["last"] = time.perf_counter()

        page.on("request", heard)
        try:
            began = time.perf_counter()
            _post_open(port, rung)
            row["composed_s"] = time.perf_counter() - began

            page.goto(f"http://127.0.0.1:{port}", wait_until="domcontentloaded")

            # One polling loop watches for both moments: the first pixels
            # brighter than background in the middle of the panel, and the
            # settling — every source resolved, then two quiet seconds.
            first_pixels = None
            deadline = began + PATIENCE_S
            while True:
                if time.perf_counter() > deadline:
                    raise TimeoutError(
                        f"the picture had not settled after {PATIENCE_S}s "
                        f"(state {page.evaluate(SETTLED_STATE)}, "
                        f"{sink['data']} data requests)")
                state = page.evaluate(SETTLED_STATE)
                if first_pixels is None and state["ready"] \
                        and fraction_lit(page) > 0.01:
                    first_pixels = time.perf_counter() - began
                arrived = (state["ready"] and state["waiting"] == 0
                           and state["resolved"])
                if arrived and first_pixels is not None \
                        and time.perf_counter() - sink["last"] >= QUIET_S:
                    break
                page.wait_for_timeout(150)

            row["first_pixels_s"] = first_pixels
            # Settled is when the last request was heard, not when the two
            # quiet seconds finished confirming it — except on a rung small
            # enough that the last request lands before the first pixels do,
            # where the painting is the later of the two moments.
            row["settled_s"] = max(sink["last"] - began, first_pixels)
            row["open_requests"] = sink["data"]
            row["churn"] = sink["data"] / count

            # Now show the whole survey: zoom out until it fits, count what
            # that costs separately, and photograph what an operator would
            # see. This is also what makes the screenshots inspectable — at
            # one voxel to the pixel a large rung shows only its corner.
            before_fit = sink["data"]
            page.evaluate(FIT_THE_WHOLE_PICTURE)
            _wait_until_quiet(page, sink, time.perf_counter(), PATIENCE_S)
            row["fit_requests"] = sink["data"] - before_fit
            row["lit"] = fraction_lit(page)
            row["chunks"] = page.evaluate(WHAT_IS_HELD)
            page.screenshot(path=f"/tmp/ladder_rung_{count}.png")
        except Exception as why:  # noqa: BLE001 -- reported per rung, ladder goes on
            row["error"] = f"{type(why).__name__}: {why}"
            row["trace"] = traceback.format_exc()
            try:
                page.screenshot(path=f"/tmp/ladder_rung_{count}_failed.png")
            except Exception:  # noqa: BLE001 -- the page may be gone entirely
                pass
        finally:
            page.close()
            browser.close()
            server.shutdown()
            thread.join(timeout=5)
    return row


def main() -> int:
    built = _VIZ / "app" / "page" / "dist"
    if not (built / "index.html").is_file():
        raise SystemExit(
            "the viewer page has not been built, so there is nothing for a "
            "browser to open. Build it with:\n"
            "  npm --prefix zmart-viewer/frontend install\n"
            "  npm --prefix zmart-viewer/frontend run build")

    asked = [int(one) for one in sys.argv[1:]] or list(RUNGS)
    rows = []
    for count in asked:
        print(f"rung {count} ...", flush=True)
        row = measure_a_rung(count, built)
        rows.append(row)
        if "error" in row:
            print(f"  FAILED: {row['error']}", flush=True)
        else:
            print(f"  composed {row['composed_s']:.2f}s, first pixels "
                  f"{row['first_pixels_s']:.2f}s, settled {row['settled_s']:.2f}s, "
                  f"{row['open_requests']} requests "
                  f"({row['churn']:.2f} a position), lit {row['lit']:.3f}",
                  flush=True)

    print()
    print("| positions | composed | first pixels | settled | /data/ requests | "
          "churn (req/position) | fit requests | chunks held | lit |")
    print("|---|---|---|---|---|---|---|---|---|")
    for row in rows:
        if "error" in row:
            print(f"| {row['positions']} | failed: {row['error']} "
                  f"| | | | | | | |")
            continue
        held = row["chunks"]["held"]
        print(f"| {row['positions']} | {row['composed_s']:.2f} s | "
              f"{row['first_pixels_s']:.2f} s | {row['settled_s']:.2f} s | "
              f"{row['open_requests']} | {row['churn']:.2f} | "
              f"{row['fit_requests']} | {held} | {row['lit']:.3f} |")
    print()
    print("The churn number is /data/ requests from opening until the picture "
          "settled, divided by the rung's positions. The composing door's "
          "claim is that it FALLS as the survey grows: the browser fetches "
          "the screen, not the survey. 'fit requests' is what zooming out to "
          "the whole survey then cost on top; 'chunks held' is what the "
          "engine's worker was holding afterwards, read through the ZMART "
          "probe. Check 'lit' is well above nought before believing a row, "
          "and look at /tmp/ladder_rung_<N>.png — a request count can be "
          "satisfied by a black screen, an inspected picture cannot.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
