"""Measure every door of the load window at growing scale, as the operator uses it.

The ladder scripts beside this one measure the live path; this one measures
the OPERATOR's path -- the doors the load window drives, over the same HTTP
the page speaks. For each rung of a growing survey it walks the whole story:

- listing the folder the window shows,
- building the scene without the hard copy (the instant, linked build),
- building it again WITH the hard copy (the bake, one file per frame),
- opening each through /api/stores/open, exactly as Show does,
- and, in a real page, the time from opening to a painted picture, plus a
  rough drawn-frame time while panning.

The numbers land in one table per rung, printed as the run goes; whoever
runs it turns them into a MEASURED note beside the others. Drawing here is
software (headless SwiftShader) unless the machine offers better, so treat
the browser columns as shapes, not absolutes -- exactly as the ladders do.

Run it with::

    python viz_studio/building/measure_the_load_doors.py --fixtures /somewhere

Each rung's fixture is written once and kept, so a re-run measures the doors
rather than the fixture writer.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import numpy as np
import zarr

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "backend"))
sys.path.insert(0, str(HERE.parent / "tests"))

FRAME = 384
PLANES = 2
CHANNELS = 2
STEP_UM = 320.0
RUNGS = (16, 64, 256, 1024)


def _write_a_tile(store: Path, number: int, at_um: tuple[float, float]) -> None:
    """One position: two channels, two planes, bright bands so drift shows."""
    store.mkdir(parents=True)
    picture = np.empty((CHANNELS, PLANES, FRAME, FRAME), "uint16")
    for channel in range(CHANNELS):
        base = 900 + 500 * channel + (number % 7) * 300
        picture[channel] = base
        picture[channel, :, : FRAME // 8, :] = base * 3
    datasets = []
    for level in range(2):
        shrink = 2 ** level
        shaped = picture[..., ::shrink, ::shrink]
        array = zarr.create_array(
            store=str(store / str(level)), shape=shaped.shape,
            chunks=(1, 1, FRAME // shrink, FRAME // shrink),
            dtype="uint16", zarr_format=3,
            dimension_names=["c", "z", "y", "x"], overwrite=True)
        array[:] = shaped
        datasets.append({"path": str(level), "coordinateTransformations": [
            {"type": "scale", "scale": [1.0, 1.0, 1.0 * shrink, 1.0 * shrink]},
            {"type": "translation",
             "translation": [0.0, 0.0, at_um[0], at_um[1]]}]})
    (store / "zarr.json").write_text(json.dumps({
        "attributes": {"ome": {"version": "0.5", "multiscales": [{
            "name": store.name, "type": "nearest",
            "axes": [{"name": one} for one in "czyx"],
            "datasets": datasets}]}},
        "zarr_format": 3, "node_type": "group"}), encoding="utf-8")


def _a_survey(folder: Path, positions: int) -> Path:
    if folder.exists():
        return folder
    across = int(round(positions ** 0.5))
    folder.mkdir(parents=True)
    for number in range(positions):
        row, column = divmod(number, across)
        _write_a_tile(folder / f"pos{number:04d}.ome.zarr", number,
                      (row * STEP_UM, column * STEP_UM))
    return folder


def _post(address: str, route: str, payload: dict) -> tuple[int, dict]:
    asked = urllib.request.Request(
        f"{address}{route}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(asked, timeout=3600) as answer:
            return answer.status, json.loads(answer.read() or b"{}")
    except urllib.error.HTTPError as refusal:  # noqa: F821 -- urllib.error via request
        return refusal.code, json.loads(refusal.read() or b"{}")


def _build(address: str, data: Path, viewer: Path, *, bake: bool,
           name: str) -> float:
    """One construction through the door, timed to its own 'done'."""
    started = time.perf_counter()
    status, answer = _post(address, "/api/stores/construct",
                           {"path": str(data), "viewer_folder": str(viewer),
                            "bake": bake, "name": name})
    assert status == 200, answer
    while True:
        _, told = _post(address, "/api/stores/construct-status", {})
        if told.get("state") != "running":
            break
        time.sleep(0.1)
    assert told.get("state") == "done", told
    return time.perf_counter() - started


def _in_a_page(browser_address: str, scene: Path, label: str) -> dict:
    """Open one scene in a real page and time what an operator feels."""
    from conftest import find_a_chromium
    from playwright.sync_api import sync_playwright

    numbers: dict[str, float] = {}
    with sync_playwright() as pw:
        args = ["--use-gl=angle", "--use-angle=swiftshader"]
        try:
            browser = pw.chromium.launch(args=args)
        except Exception:
            browser = pw.chromium.launch(executable_path=find_a_chromium(),
                                         args=args)
        page = browser.new_page(viewport={"width": 1300, "height": 900})
        page.goto(browser_address, wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartViewer !== undefined",
                               timeout=60_000)
        started = time.perf_counter()
        status = page.evaluate(
            """async (path) => {
                 const r = await fetch('/api/stores/open', {method: 'POST',
                   headers: {'Content-Type': 'application/json'},
                   body: JSON.stringify({path})});
                 return r.status;
               }""", str(scene))
        assert status == 200, f"{label}: open answered {status}"
        page.wait_for_function(
            "() => window.zmartConfig && window.zmartConfig.groups.length > 1",
            timeout=120_000)
        numbers["open_to_group_s"] = time.perf_counter() - started
        page.wait_for_function(
            "() => window.zmartSourcesWaiting && window.zmartSourcesWaiting() === 0",
            timeout=600_000)
        numbers["sources_ready_s"] = time.perf_counter() - started
        # Frame everything, then let the first full drawing settle.
        page.get_by_role("button", name="Overview", exact=True).click()
        page.wait_for_timeout(4000)
        numbers["settled_s"] = time.perf_counter() - started
        # A rough drawn-frame time while panning: how long thirty animation
        # frames take with the view gliding. Software rendering makes this
        # pessimistic; the shape across rungs is the signal.
        numbers["pan_frame_ms"] = page.evaluate(
            """async () => {
                 const position = window.zmartViewer.navigationState.position;
                 const started = performance.now();
                 for (let i = 0; i < 30; i++) {
                   const moved = Float32Array.from(position.value);
                   moved[moved.length - 1] += 8;
                   position.value = moved;
                   await new Promise(r => requestAnimationFrame(r));
                 }
                 return (performance.now() - started) / 30;
               }""")
        page.close()
        browser.close()
    return numbers


def main() -> None:
    parsed = argparse.ArgumentParser(description=__doc__)
    parsed.add_argument("--fixtures", type=Path, default=None)
    parsed.add_argument("--rungs", type=int, nargs="*", default=list(RUNGS))
    arguments = parsed.parse_args()

    from server import make_server
    from test_open_and_close import _store

    keep = arguments.fixtures or Path(tempfile.mkdtemp(prefix="load-doors-"))
    keep.mkdir(parents=True, exist_ok=True)
    first = keep / "starting"
    if not first.exists():
        first.mkdir()
        _store(first / "starting_pos001.ome.zarr", channels=1)
    built = HERE.parent / "frontend" / "dist"

    server = make_server(port=0, data_dir=first, site_dir=built,
                         store="starting_pos001.ome.zarr", allow_open=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    address = f"http://127.0.0.1:{server.server_address[1]}"

    print(f"fixtures kept in {keep}")
    print("| positions | write s | list ms | linked build s | baked build s |"
          " open linked s | open baked s | to group s | ready s | settled s |"
          " pan ms |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    try:
        for positions in arguments.rungs:
            survey = keep / f"survey-{positions:04d}"
            started = time.perf_counter()
            _a_survey(survey, positions)
            wrote = time.perf_counter() - started

            started = time.perf_counter()
            status, listing = _post(address, "/api/stores/list",
                                    {"path": str(keep)})
            assert status == 200, listing
            listed = (time.perf_counter() - started) * 1000

            scenes = survey / "scenes"
            linked = _build(address, survey, scenes, bake=False, name="linked")
            baked = _build(address, survey, scenes, bake=True, name="baked")

            opened = {}
            for name in ("linked", "baked"):
                scene = scenes / f"{name}.ome.zarr"
                started = time.perf_counter()
                status, answer = _post(address, "/api/stores/open",
                                       {"path": str(scene)})
                assert status == 200, answer
                opened[name] = time.perf_counter() - started
                _post(address, "/api/stores/close",
                      {"group": scene.stem})

            felt = _in_a_page(address, scenes / "baked.ome.zarr",
                              f"{positions} positions")
            page_status, _ = _post(address, "/api/stores/close",
                                   {"group": "baked"})
            print(f"| {positions} | {wrote:.1f} | {listed:.0f} | {linked:.2f} |"
                  f" {baked:.2f} | {opened['linked']:.2f} |"
                  f" {opened['baked']:.2f} | {felt['open_to_group_s']:.2f} |"
                  f" {felt['sources_ready_s']:.2f} | {felt['settled_s']:.2f} |"
                  f" {felt['pan_frame_ms']:.1f} |", flush=True)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    main()
