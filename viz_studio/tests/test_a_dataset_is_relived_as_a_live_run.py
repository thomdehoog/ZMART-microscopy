"""A finished dataset can be relived as a live run, one position at a time.

The load window's "other" tab offers Replay next to Open. Opening shows the
whole dataset at once; replaying hands the same positions to the very doorway
the microscope uses -- the live writer, its manifest, its announcements -- and
the picture assembles on screen tile by tile. Nothing about the live path is
faked, which is the point: a replay is a dress rehearsal for smart microscopy
that any operator can run on data they already have, with no microscope in
the room.

The dataset must be one whose tiles sit on a regular grid the live writer can
reproduce. Overlapping is fine -- real stage scans overlap -- as long as the
overlap is even; a transfer whose tiles sit at irregular offsets is refused
in plain words. A timelapse replays the way it was acquired: every position
of the first moment, then every position of the next, sweep after sweep, so
the time slider grows on screen exactly as it would during the experiment.
"""

import json
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pytest
import zarr

VIZ = Path(__file__).resolve().parents[1]
# The backend goes in FRONT of the building folder: both hold a server.py,
# and the one with make_server -- the one every other browser test uses --
# is the backend's.
sys.path.insert(0, str(VIZ / "building"))
sys.path.insert(0, str(VIZ / "backend"))
sys.path.insert(0, str(VIZ.parent))

from rehearsal import plan_a_replay, replay_the_dataset  # noqa: E402
from server import make_server  # noqa: E402

# One replay tile: two planes deep, one camera frame square. 384 is the same
# frame the live fixtures elsewhere use -- small enough to write quickly, large
# enough that the planner can give it a real pyramid.
FRAME = 384
PLANES = 2
# How far the stage steps between tiles, in micrometres at one micrometre a
# voxel. 320 leaves 64 pixels of overlap, which is the overlap the live
# planner itself chooses for this frame -- a replay has to reproduce the
# dataset's own spacing, so the fixture uses a spacing that can be reproduced.
STEP_UM = 320.0


def _write_a_grid_tile(store: Path, number: int, at_um: tuple[float, float]) -> None:
    """One position of a raw grid scan, bright enough to tell apart."""
    store.mkdir(parents=True)
    picture = np.full((PLANES, FRAME, FRAME), 1500 + number * 800, "uint16")
    datasets = []
    for level in range(2):
        shrink = 2 ** level
        array = zarr.create_array(
            store=str(store / str(level)),
            shape=(PLANES, FRAME // shrink, FRAME // shrink),
            chunks=(PLANES, FRAME // shrink, FRAME // shrink),
            dtype="uint16", zarr_format=3, dimension_names=["z", "y", "x"],
            overwrite=True,
        )
        array[:] = picture[:, ::shrink, ::shrink]
        datasets.append({
            "path": str(level),
            "coordinateTransformations": [
                {"type": "scale", "scale": [1.0, 1.0 * shrink, 1.0 * shrink]},
                {"type": "translation", "translation": [0.0, at_um[0], at_um[1]]},
            ],
        })
    (store / "zarr.json").write_text(json.dumps({
        "attributes": {"ome": {
            "version": "0.5",
            "multiscales": [{
                "name": store.name, "type": "nearest",
                "axes": [{"name": one, "type": "space", "unit": "micrometer"}
                         for one in ("z", "y", "x")],
                "datasets": datasets,
            }],
        }},
        "zarr_format": 3, "node_type": "group",
    }), encoding="utf-8")


def _a_grid_scan(folder: Path, *, across: int = 2) -> Path:
    """A raw dataset of ``across``-squared positions on a regular grid."""
    folder.mkdir(parents=True)
    number = 0
    for row in range(across):
        for column in range(across):
            _write_a_grid_tile(folder / f"pos{number:02d}.ome.zarr", number,
                               (row * STEP_UM, column * STEP_UM))
            number += 1
    return folder


class TestPlanningAReplay:
    """The plan maps the dataset onto the live writer's grid, or says why not."""

    def test_a_grid_scan_is_mapped_onto_cells(self, tmp_path):
        plan = plan_a_replay(_a_grid_scan(tmp_path / "scan"))
        assert plan.total == 4
        cells = {tuple(cell) if not hasattr(cell, "row") else (cell.row, cell.column)
                 for cell in plan.cells}
        assert cells == {(0, 0), (0, 1), (1, 0), (1, 1)}
        # The plan reproduces the dataset's own spacing, or it is no replay.
        assert plan.geometry.step_shape == (int(STEP_UM), int(STEP_UM))

    def test_uneven_spacing_is_refused_in_plain_words(self, tmp_path):
        folder = tmp_path / "uneven"
        folder.mkdir()
        _write_a_grid_tile(folder / "pos00.ome.zarr", 0, (0.0, 0.0))
        _write_a_grid_tile(folder / "pos01.ome.zarr", 1, (0.0, STEP_UM))
        _write_a_grid_tile(folder / "pos02.ome.zarr", 2, (0.0, STEP_UM * 2 + 17.0))
        with pytest.raises(ValueError, match="grid"):
            plan_a_replay(folder)

    def test_the_replay_publishes_one_position_at_a_time(self, tmp_path):
        """The library-level heart: every beat lands through the live writer."""
        scan = _a_grid_scan(tmp_path / "scan")
        beats = []
        view = replay_the_dataset(
            scan, tmp_path / "run", every_s=0.0,
            told=lambda done, total: beats.append((done, total)),
        )
        assert beats == [(1, 4), (2, 4), (3, 4), (4, 4)]
        assert view.name.endswith(".ome.zarr") and view.exists(), (
            "the replay must leave a live view that any viewer can open"
        )
        # And the pixels, falsified rather than trusted: every published
        # position must hold exactly the source tile's own values. A replay
        # that mapped a position onto the wrong cell, or fed one tile's
        # pixels to another's name, would pass every count above and still
        # be showing the operator a lie.
        survey = tmp_path / "run" / "data" / "survey.ome.zarr"
        for position in ("pos00", "pos01", "pos02", "pos03"):
            published = np.asarray(
                zarr.open_group(str(survey / position), mode="r")["0"]
            ).squeeze()
            source = np.asarray(zarr.open_array(
                str(scan / f"{position}.ome.zarr" / "0"), mode="r")).squeeze()
            assert np.array_equal(published, source), (
                f"{position} was published with pixels that are not its own"
            )


MOMENTS = 2
CHANNELS = 2


def _write_a_timelapse_tile(store: Path, number: int,
                            at_um: tuple[float, float]) -> None:
    """One position of a timelapse scan: two moments, two channels.

    Every (moment, channel) frame carries its own value, so a replay that
    fed one moment's pixels to another's slot would be caught by a single
    comparison rather than slip by as "some bright square landed".
    """
    store.mkdir(parents=True)
    picture = np.empty((MOMENTS, CHANNELS, PLANES, FRAME, FRAME), "uint16")
    for moment in range(MOMENTS):
        for channel in range(CHANNELS):
            picture[moment, channel] = (1000 + number * 100
                                        + moment * 3000 + channel * 400)
    datasets = []
    for level in range(2):
        shrink = 2 ** level
        array = zarr.create_array(
            store=str(store / str(level)),
            shape=(MOMENTS, CHANNELS, PLANES, FRAME // shrink,
                   FRAME // shrink),
            chunks=(1, 1, PLANES, FRAME // shrink, FRAME // shrink),
            dtype="uint16", zarr_format=3,
            dimension_names=["t", "c", "z", "y", "x"], overwrite=True,
        )
        array[:] = picture[..., ::shrink, ::shrink]
        datasets.append({
            "path": str(level),
            "coordinateTransformations": [
                {"type": "scale",
                 "scale": [1.0, 1.0, 1.0, 1.0 * shrink, 1.0 * shrink]},
                {"type": "translation",
                 "translation": [0.0, 0.0, 0.0, at_um[0], at_um[1]]},
            ],
        })
    (store / "zarr.json").write_text(json.dumps({
        "attributes": {"ome": {
            "version": "0.5",
            "multiscales": [{
                "name": store.name, "type": "nearest",
                "axes": [{"name": "t", "type": "time", "unit": "second"},
                         {"name": "c", "type": "channel"}]
                + [{"name": one, "type": "space", "unit": "micrometer"}
                   for one in ("z", "y", "x")],
                "datasets": datasets,
            }],
        }},
        "zarr_format": 3, "node_type": "group",
    }), encoding="utf-8")


def _a_timelapse_scan(folder: Path, *, across: int = 2) -> Path:
    """A raw timelapse of ``across``-squared positions on a regular grid."""
    folder.mkdir(parents=True)
    number = 0
    for row in range(across):
        for column in range(across):
            _write_a_timelapse_tile(folder / f"pos{number:02d}.ome.zarr",
                                    number, (row * STEP_UM, column * STEP_UM))
            number += 1
    return folder


class TestReplayingATimelapse:
    """A timelapse replays sweep by sweep, every frame with its own pixels."""

    def test_the_plan_sweeps_the_grid_once_per_moment(self, tmp_path):
        plan = plan_a_replay(_a_timelapse_scan(tmp_path / "scan"))
        assert plan.total == 4 * MOMENTS
        assert plan.profile.timepoints == MOMENTS
        moments = [beat[-1] for beat in plan.beats]
        assert moments == [0] * 4 + [1] * 4, (
            "a timelapse replays the way it was acquired: every position of "
            "one moment, then every position of the next"
        )
        # Within each sweep the positions land in scan order, and both
        # sweeps walk the same path -- a stage revisits its grid the same
        # way each time.
        names = [beat[0] for beat in plan.beats]
        assert names[:4] == names[4:]

    def test_every_moment_lands_with_its_own_pixels(self, tmp_path):
        scan = _a_timelapse_scan(tmp_path / "scan")
        beats = []
        view = replay_the_dataset(
            scan, tmp_path / "run", every_s=0.0,
            told=lambda done, total: beats.append((done, total)),
        )
        assert beats[-1] == (4 * MOMENTS, 4 * MOMENTS)
        assert view.exists()
        survey = tmp_path / "run" / "data" / "survey.ome.zarr"
        for position in ("pos00", "pos01", "pos02", "pos03"):
            published = np.asarray(
                zarr.open_group(str(survey / position), mode="r")["0"])
            source = np.asarray(zarr.open_array(
                str(scan / f"{position}.ome.zarr" / "0"), mode="r"))
            assert published.shape == source.shape, (
                f"{position} was published into a different (t, c) room "
                f"than the source keeps: {published.shape} against "
                f"{source.shape}"
            )
            assert np.array_equal(published, source), (
                f"{position} was published with pixels that are not its own "
                "-- a moment or channel landed in the wrong slot"
            )


    def test_a_watcher_sees_the_slider_grow_and_follow(
            self, browser, built_dist, tmp_path):
        """On a held page, each sweep offers its moment and the view follows.

        This is the whole point of replaying a timelapse: the time slider
        must offer moment 0 alone while the first sweep lands, grow when
        the second sweep begins, and the view -- left standing on the
        front -- must move to the new moment on its own, exactly as it
        would during the experiment.
        """
        first = tmp_path / "overview"
        first.mkdir()
        from test_open_and_close import _store
        _store(first / "overview_pos001.ome.zarr", channels=1)
        _a_timelapse_scan(tmp_path / "sweeps")
        server = make_server(port=0, data_dir=first, site_dir=built_dist,
                             store="overview_pos001.ome.zarr")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        page = browser.new_page(viewport={"width": 1300, "height": 1000})
        try:
            page.goto(f"http://127.0.0.1:{server.server_address[1]}",
                      wait_until="domcontentloaded")
            page.wait_for_function("() => window.zmartConfig !== undefined",
                                   timeout=30_000)
            page.get_by_label("open images").click()
            window = page.get_by_role("dialog", name="load data")
            window.wait_for(timeout=10_000)
            page.get_by_label("other", exact=True).click()
            box = page.get_by_label("folder path")
            box.fill(str(tmp_path))
            box.press("Enter")
            window.get_by_label("sweeps", exact=True).wait_for(timeout=10_000)
            window.get_by_label("sweeps", exact=True).click()
            page.get_by_label("open as a live run").click()
            page.wait_for_function(
                "() => window.zmartConfig.groups.includes('sweeps replay')",
                timeout=30_000)
            slider = "document.querySelector('input[aria-label=\"t position\"]')"
            # While the first sweep lands, only moment 0 is on offer: the
            # committed ranges stop at 1, and there is nothing to slide yet
            # (a slider already reaching moment 1 would mean the replay is
            # being served as a finished folder, whole room and all).
            page.wait_for_function(f"""() => {{
                const rows = (window.zmartConfig?.layers || []).filter(
                    one => one.group === 'sweeps replay');
                if (!rows.length) return false;
                const ranges = rows[0].committedTimeRanges || [];
                const held = {slider};
                return ranges.length === 1 && ranges[0].start === 0
                    && ranges[0].stop === 1
                    && (!held || held.max === '0');
            }}""", timeout=30_000)
            # The second sweep begins: the slider grows...
            page.wait_for_function(f"() => {slider}?.max === '1'",
                                   timeout=60_000)
            # ...and the watcher, standing on the front, is carried onto
            # the moment that just landed.
            page.wait_for_function("""() => {
                const p = window.zmartViewer.navigationState.position;
                const names = p.coordinateSpace.value.names;
                const i = names.indexOf('t');
                if (i < 0) return false;
                const lower = p.coordinateSpace.value.bounds.lowerBounds[i];
                return Math.abs(p.value[i] - Math.ceil(lower) - 1) <= 0.5;
            }""", timeout=60_000)
            for _ in range(200):
                answer = page.evaluate("""async () => {
                    const r = await fetch('/api/stores/replay-status',
                        {method: 'POST',
                         headers: {'Content-Type': 'application/json'},
                         body: '{}'});
                    return r.json();
                }""")
                if answer.get("state") == "done":
                    break
                page.wait_for_timeout(150)
            assert answer.get("state") == "done"
            assert answer.get("done") == 4 * MOMENTS
            page.screenshot(path=str(tmp_path / "a_timelapse_replay.png"))
        finally:
            page.close()
            server.shutdown()
            thread.join(timeout=5)


def test_a_replay_is_watchable_without_any_clicks(browser, built_dist,
                                                  tmp_path):
    """Starting a replay must show the landing tiles, hands off the mouse.

    Three separate small things used to leave the canvas black until the
    operator intervened: the new layers opened on the camera's full
    brightness range (the pixels sit in its bottom few per cent), the view
    stayed wherever the operator last looked, and the focal plane could
    sit at a depth the replay does not have. This gate presses Replay and
    then touches NOTHING -- no Auto, no Overview, no sliders -- and
    demands that a healthy share of the canvas lights up with the landing
    tiles. Any one of the three old failures keeps that share near zero,
    so one measurement guards all three. The acquisition that was already
    open is hidden first, so the light being measured can only be the
    replay's own.
    """
    import io

    from PIL import Image

    first = tmp_path / "overview"
    first.mkdir()
    from test_open_and_close import _store
    _store(first / "overview_pos001.ome.zarr", channels=1)
    _a_grid_scan(tmp_path / "rehearsal")
    server = make_server(port=0, data_dir=first, site_dir=built_dist,
                         store="overview_pos001.ome.zarr")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1300, "height": 1000})
    try:
        page.goto(f"http://127.0.0.1:{server.server_address[1]}",
                  wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartConfig !== undefined",
                               timeout=30_000)
        # Hide what was already on screen, so any light measured below can
        # only be the replay's own tiles.
        page.get_by_title("Hide this acquisition").first.click()
        page.get_by_label("open images").click()
        window = page.get_by_role("dialog", name="load data")
        window.wait_for(timeout=10_000)
        page.get_by_label("other", exact=True).click()
        box = page.get_by_label("folder path")
        box.fill(str(tmp_path))
        box.press("Enter")
        window.get_by_label("rehearsal", exact=True).wait_for(timeout=10_000)
        window.get_by_label("rehearsal", exact=True).click()
        page.get_by_label("open as a live run").click()
        page.wait_for_function(
            "() => window.zmartConfig.groups.includes('rehearsal replay')",
            timeout=30_000)
        for _ in range(300):
            answer = page.evaluate("""async () => {
                const r = await fetch('/api/stores/replay-status',
                    {method: 'POST',
                     headers: {'Content-Type': 'application/json'},
                     body: '{}'});
                return r.json();
            }""")
            if answer.get("state") == "done":
                break
            page.wait_for_timeout(150)
        assert answer.get("state") == "done"
        # Let the engine finish fetching and drawing what the replay left.
        page.wait_for_timeout(5_000)
        page.screenshot(path=str(tmp_path / "a_replay_hands_off.png"))
        shot = page.locator("canvas").first
        clipped = shot.bounding_box()
        photographed = page.screenshot(clip=clipped)
        pixels = np.array(Image.open(io.BytesIO(photographed)).convert("L"))
        lit = float((pixels > 80).mean())
        assert lit > 0.25, (
            f"after a hands-off replay only {lit:.0%} of the canvas is lit; "
            "the operator is still looking at blackness -- a dark window, an "
            "unmoved view, or a focal plane the replay does not have"
        )
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def test_a_replay_can_be_stopped_from_the_window(browser, built_dist,
                                                 tmp_path):
    """The other tab offers Stop while a replay runs, and it works.

    The window closes when a replay starts (the operator is watching the
    tiles land), so the stop lives where they would go looking: reopening
    the window on the other tab shows that a replay is running, how far it
    is, and a Stop button. Pressing it ends the landings after the
    position in flight; what landed stays on screen. The Replay button is
    held disabled meanwhile, saying why a second replay must wait.
    """
    first = tmp_path / "overview"
    first.mkdir()
    from test_open_and_close import _store
    _store(first / "overview_pos001.ome.zarr", channels=1)
    scan = _a_grid_scan(tmp_path / "rehearsal", across=4)
    server = make_server(port=0, data_dir=first, site_dir=built_dist,
                         store="overview_pos001.ome.zarr")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1300, "height": 1000})
    try:
        page.goto(f"http://127.0.0.1:{server.server_address[1]}",
                  wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartConfig !== undefined",
                               timeout=30_000)
        page.get_by_label("open images").click()
        window = page.get_by_role("dialog", name="load data")
        window.wait_for(timeout=10_000)
        page.get_by_label("other", exact=True).click()
        box = page.get_by_label("folder path")
        box.fill(str(tmp_path))
        box.press("Enter")
        window.get_by_label("rehearsal", exact=True).wait_for(timeout=10_000)
        window.get_by_label("rehearsal", exact=True).click()
        page.get_by_label("open as a live run").click()
        page.wait_for_function(
            "() => window.zmartConfig.groups.includes('rehearsal replay')",
            timeout=30_000)
        # The window closed itself; the operator goes back for the stop.
        page.get_by_label("open images").click()
        window.wait_for(timeout=10_000)
        page.get_by_label("other", exact=True).click()
        stop = page.get_by_label("stop the replay")
        stop.wait_for(timeout=10_000)
        assert page.get_by_label("open as a live run").is_disabled(), (
            "while a replay runs, starting another must wait"
        )
        stop.click()
        page.wait_for_function("""async () => {
            const r = await fetch('/api/stores/replay-status',
                {method: 'POST',
                 headers: {'Content-Type': 'application/json'}, body: '{}'});
            const told = await r.json();
            return told.state === 'cancelled';
        }""", timeout=30_000)
        landed = [one for one
                  in (scan / "replays" / "replay-1" / "data"
                      / "survey.ome.zarr").iterdir()
                  if one.is_dir() and one.name.startswith("pos")]
        assert 1 <= len(landed) < 16, (
            f"a stopped replay should hold some but not all positions; "
            f"found {len(landed)}"
        )
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def _post(address: str, route: str, payload: dict) -> tuple[int, dict]:
    """One JSON request straight to the server, no browser in between."""
    import urllib.error
    import urllib.request

    asked = urllib.request.Request(
        f"{address}{route}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(asked, timeout=180) as answer:
            return answer.status, json.loads(answer.read() or b"{}")
    except urllib.error.HTTPError as refusal:
        return refusal.code, json.loads(refusal.read() or b"{}")


@pytest.fixture
def serving(built_dist, tmp_path):
    """A running server on one ordinary acquisition, and the folder beside it."""
    first = tmp_path / "overview"
    first.mkdir()
    from test_open_and_close import _store
    _store(first / "overview_pos001.ome.zarr", channels=1)
    server = make_server(port=0, data_dir=first, site_dir=built_dist,
                         store="overview_pos001.ome.zarr")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", tmp_path
    finally:
        server.shutdown()
        thread.join(timeout=5)


class TestTheReplayRoutes:
    """The server's own rules for the door, asked without a browser."""

    def test_a_finished_replay_opens_again_later(self, serving):
        """The run a replay wrote is a real run, and the plain door opens it.

        The window promises the replay "writes a real run into a replays
        folder beside the dataset, so it can be opened again later" -- and
        until this gate, later never came: the run's root holds ``data``
        beside ``views`` and no image directly inside, so the plain door
        answered "no OME-Zarr image was found" (workstation, 2026-08-19).
        The root is opened the way the replay door itself opens it, served
        view named, so the live registry binds it and the time slider
        offers exactly the moments that landed.
        """
        address, folder = serving
        scan = _a_grid_scan(folder / "yesterdayscan")
        status, _ = _post(address, "/api/stores/replay",
                          {"path": str(scan), "every": 0.0})
        assert status == 200
        for _ in range(100):
            _, told = _post(address, "/api/stores/replay-status", {})
            if told.get("state") != "running":
                break
            time.sleep(0.2)
        assert told.get("state") == "done"
        kept = scan / "replays" / "replay-1"
        status, answer = _post(address, "/api/stores/open",
                               {"path": str(kept)})
        assert status == 200, answer
        served_rows = [one for one in answer.get("layers", [])
                       if one.get("kind") == "image"
                       and one.get("group") == "replay-1"]
        assert served_rows, (
            "the reopened run must serve its live view as its own group"
        )

    def test_one_replay_at_a_time(self, serving):
        """A second ask while one runs is refused, not queued.

        The same rule the bake follows, for the same reason: the answer to
        "how far along?" has to mean one thing.
        """
        address, folder = serving
        scan = _a_grid_scan(folder / "slowscan")
        status, _ = _post(address, "/api/stores/replay",
                          {"path": str(scan), "every": 0.8})
        assert status == 200
        refused, answer = _post(address, "/api/stores/replay",
                                {"path": str(scan)})
        assert refused == 409 and "already" in answer["error"]
        # Wait the run out, so nothing is still writing when the folder goes.
        for _ in range(100):
            _, told = _post(address, "/api/stores/replay-status", {})
            if told.get("state") != "running":
                break
            time.sleep(0.2)
        assert told.get("state") == "done"

    def test_a_dataset_off_the_grid_is_refused_with_its_reason(self, serving):
        """The refusal crosses the wire whole, so the window can show it."""
        address, folder = serving
        uneven = folder / "uneven"
        uneven.mkdir()
        _write_a_grid_tile(uneven / "pos00.ome.zarr", 0, (0.0, 0.0))
        _write_a_grid_tile(uneven / "pos01.ome.zarr", 1, (0.0, STEP_UM))
        _write_a_grid_tile(uneven / "pos02.ome.zarr", 2,
                           (0.0, STEP_UM * 2 + 17.0))
        status, answer = _post(address, "/api/stores/replay",
                               {"path": str(uneven)})
        assert status == 400
        assert "grid" in answer["error"], answer

    def test_the_replay_routes_obey_the_open_gate(self, built_dist, tmp_path):
        """With opening switched off, the replay doors are not served.

        The replay exists for the operator's load window, exactly like the
        listing; a run-mode page where a workflow decides what is shown
        offers neither.
        """
        first = tmp_path / "overview"
        first.mkdir()
        from test_open_and_close import _store
        _store(first / "overview_pos001.ome.zarr", channels=1)
        server = make_server(port=0, data_dir=first, site_dir=built_dist,
                             store="overview_pos001.ome.zarr", allow_open=False)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            address = f"http://127.0.0.1:{server.server_address[1]}"
            for route in ("/api/stores/replay", "/api/stores/replay-status"):
                status, _ = _post(address, route, {"path": str(tmp_path)})
                assert status == 404, f"{route} answered {status} with opening off"
        finally:
            server.shutdown()
            thread.join(timeout=5)


class TestTheReplayDoor:
    """From the other tab, Replay relives the dataset in front of the operator."""

    def test_a_refusal_reaches_the_operator_in_the_window(
        self, browser, built_dist, tmp_path
    ):
        """An off-grid dataset fails where the operator is looking.

        The window stays open with the refusal's own words in its error box,
        rather than closing on a silent nothing.
        """
        first = tmp_path / "overview"
        first.mkdir()
        from test_open_and_close import _store
        _store(first / "overview_pos001.ome.zarr", channels=1)
        uneven = tmp_path / "uneven"
        uneven.mkdir()
        _write_a_grid_tile(uneven / "pos00.ome.zarr", 0, (0.0, 0.0))
        _write_a_grid_tile(uneven / "pos01.ome.zarr", 1, (0.0, STEP_UM))
        _write_a_grid_tile(uneven / "pos02.ome.zarr", 2,
                           (0.0, STEP_UM * 2 + 17.0))
        server = make_server(port=0, data_dir=first, site_dir=built_dist,
                             store="overview_pos001.ome.zarr")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        page = browser.new_page(viewport={"width": 1300, "height": 1000})
        try:
            page.goto(f"http://127.0.0.1:{server.server_address[1]}",
                      wait_until="domcontentloaded")
            page.wait_for_function("() => window.zmartConfig !== undefined",
                                   timeout=30_000)
            page.get_by_label("open images").click()
            window = page.get_by_role("dialog", name="load data")
            window.wait_for(timeout=10_000)
            page.get_by_label("other", exact=True).click()
            box = page.get_by_label("folder path")
            box.fill(str(tmp_path))
            box.press("Enter")
            window.get_by_label("uneven", exact=True).wait_for(timeout=10_000)
            window.get_by_label("uneven", exact=True).click()
            page.get_by_label("open as a live run").click()
            told = window.get_by_role("alert")
            told.wait_for(timeout=30_000)
            assert "grid" in told.inner_text()
            assert page.get_by_role("dialog", name="load data").count() == 1, (
                "the window must stay open so the refusal can be read"
            )
        finally:
            page.close()
            server.shutdown()
            thread.join(timeout=5)

    def test_the_other_tab_replays_tile_by_tile(self, browser, built_dist, tmp_path):
        first = tmp_path / "overview"
        first.mkdir()
        # The ordinary starting acquisition, so the viewer has something open.
        from test_open_and_close import _store
        _store(first / "overview_pos001.ome.zarr", channels=1)
        scan = _a_grid_scan(tmp_path / "rehearsal")
        server = make_server(port=0, data_dir=first, site_dir=built_dist,
                             store="overview_pos001.ome.zarr")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        page = browser.new_page(viewport={"width": 1300, "height": 1000})
        try:
            page.goto(f"http://127.0.0.1:{server.server_address[1]}",
                      wait_until="domcontentloaded")
            page.wait_for_function("() => window.zmartConfig !== undefined",
                                   timeout=30_000)
            page.get_by_label("open images").click()
            window = page.get_by_role("dialog", name="load data")
            window.wait_for(timeout=10_000)
            page.get_by_label("other", exact=True).click()
            box = page.get_by_label("folder path")
            box.fill(str(tmp_path))
            box.press("Enter")
            window.get_by_label("rehearsal", exact=True).wait_for(timeout=10_000)
            window.get_by_label("rehearsal", exact=True).click()
            page.get_by_label("open as a live run").click()
            # The first position is on screen the moment the door answers; the
            # rest land one at a time behind it. The heading names the
            # dataset being relived, not the view's own file.
            page.wait_for_function(
                "() => window.zmartConfig.groups.includes('rehearsal replay')",
                timeout=30_000)
            status = """async () => {
                const r = await fetch('/api/stores/replay-status',
                    {method: 'POST', headers: {'Content-Type': 'application/json'},
                     body: '{}'});
                return r.json();
            }"""
            seen = []
            for _ in range(200):
                answer = page.evaluate(status)
                seen.append((answer.get("done"), answer.get("state")))
                if answer.get("state") == "done":
                    break
                page.wait_for_timeout(150)
            assert seen[-1][1] == "done", f"the replay never finished: {seen[-3:]}"
            counts = [done for done, _ in seen if isinstance(done, int)]
            assert counts[-1] == 4
            assert any(1 <= done < 4 for done in counts), (
                "the replay must be watchable part-way through -- landing "
                f"everything at once is an open, not a replay (saw {counts})"
            )
            # The run on disk is a real live run in the contract layout: the
            # one collection of positions, and the live view a viewer opens.
            run_folder = scan / "replays" / "replay-1"
            survey = run_folder / "data" / "survey.ome.zarr"
            assert (run_folder / "views" / "live" / "live.ome.zarr").exists()
            landed = [one for one in survey.iterdir()
                      if one.is_dir() and one.name.startswith("pos")]
            assert len(landed) == 4
        finally:
            page.close()
            server.shutdown()
            thread.join(timeout=5)


def test_a_04_dataset_replays_the_same(tmp_path):
    """The older metadata generation replays too, pixels pinned.

    Everything the viewer WRITES is 0.5; this pins the reading side --
    positions somebody converted years ago should relive exactly like
    fresh ones. The fixture mirrors the grid scan above in 0.4 form:
    flat .zattrs beside zarr v2 arrays.
    """
    scan = tmp_path / "older"
    scan.mkdir()
    for number in range(4):
        row, column = divmod(number, 2)
        store = scan / f"pos{number:02d}.ome.zarr"
        store.mkdir()
        group = zarr.open_group(str(store), mode="w", zarr_format=2)
        data = np.full((PLANES, FRAME, FRAME), 1500 + number * 800, "uint16")
        group.create_array("0", shape=data.shape, chunks=data.shape,
                           dtype="uint16")[:] = data
        (store / ".zattrs").write_text(json.dumps({"multiscales": [{
            "version": "0.4",
            "axes": [{"name": one, "type": "space", "unit": "micrometer"}
                     for one in ("z", "y", "x")],
            "datasets": [{"path": "0", "coordinateTransformations": [
                {"type": "scale", "scale": [1.0, 1.0, 1.0]},
                {"type": "translation",
                 "translation": [0.0, row * STEP_UM, column * STEP_UM]},
            ]}],
        }]}), encoding="utf-8")

    view = replay_the_dataset(scan, tmp_path / "run", every_s=0.0)
    assert view.exists()
    survey = tmp_path / "run" / "data" / "survey.ome.zarr"
    for number in range(4):
        published = np.asarray(zarr.open_group(
            str(survey / f"pos{number:02d}"), mode="r")["0"]).squeeze()
        assert published.max() == 1500 + number * 800, (
            f"pos{number:02d} relived with pixels that are not its own"
        )


def _relive(page, folder: Path, name: str) -> None:
    """Drive the load window the way an operator does: other, folder, open."""
    page.get_by_label("open images").click()
    window = page.get_by_role("dialog", name="load data")
    window.wait_for(timeout=10_000)
    page.get_by_label("other", exact=True).click()
    box = page.get_by_label("folder path")
    box.fill(str(folder))
    box.press("Enter")
    window.get_by_label(name, exact=True).wait_for(timeout=10_000)
    window.get_by_label(name, exact=True).click()
    page.get_by_label("open as a live run").click()
    page.wait_for_timeout(4000)
    # The way back to the whole picture, pressed the same way both times: what
    # is compared below is what was drawn, not where the camera happened to be.
    page.get_by_role("button", name="Overview", exact=True).click()


def _what_is_shown(page) -> dict:
    """The picture as an operator sees it: how much is lit, and in what colour."""
    from pixels import fraction_lit
    return {
        "lit": round(fraction_lit(page), 3),
        "colours": page.evaluate(
            "() => (window.zmartConfig?.layers || []).map((one) => one.color)"),
        "sources": page.evaluate(
            "() => (window.zmartConfig?.layers || [])"
            ".map((one) => (one.sources || []).length)"),
    }


def test_closing_one_acquisition_does_not_spoil_the_next(
        browser, built_dist, tmp_path):
    """Close one dataset, open another, and the second one is drawn in full.

    Clearing the screen and loading the next thing is the ordinary rhythm of a
    session at the microscope, and it has to leave the viewer as good as it
    found it. It did not: after a close, whatever was opened next came up with
    most of its tiles missing, and only reloading the page put it right -- so
    what was wrong was what the page had kept, not the data. The server sends
    the same description and the browser fetches the same pieces either way
    (measured 2026-08-21).

    Two different datasets rather than the same one twice, because that is the
    case an operator meets: the second is a different size, so drawing it as
    though it were the first is visible.
    """
    first = tmp_path / "overview"
    first.mkdir()
    from test_open_and_close import _store
    _store(first / "overview_pos001.ome.zarr", channels=1)
    _a_grid_scan(tmp_path / "one", across=2)
    _a_grid_scan(tmp_path / "two", across=3)
    server = make_server(port=0, data_dir=first, site_dir=built_dist,
                         store="overview_pos001.ome.zarr")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1300, "height": 1000})
    try:
        page.goto(f"http://127.0.0.1:{server.server_address[1]}",
                  wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartConfig !== undefined", timeout=30_000)
        page.get_by_title("Hide this acquisition").first.click()
        page.wait_for_timeout(500)

        _relive(page, tmp_path, "one")
        page.wait_for_function(
            "() => (window.zmartConfig.groups || []).some((g) => g.includes('one'))",
            timeout=30_000)
        page.wait_for_timeout(6000)
        assert _what_is_shown(page)["lit"] > 0.05, "the first dataset never drew"

        group = page.evaluate(
            "() => (window.zmartConfig.groups || []).find((g) => g.includes('one'))")
        # Marked so that the engine after the close can be told from the one
        # before it: closing builds a new one, which is the fix for this.
        page.evaluate("() => { window.zmartViewer.zmartMark = 'before'; }")
        page.locator(f'[aria-label="close {group}"]').click()
        page.wait_for_timeout(2500)
        assert page.evaluate("() => window.zmartViewer?.zmartMark") != "before", (
            "closing an acquisition must build the engine again: the one that "
            "drew the closed dataset is still here"
        )

        _relive(page, tmp_path, "two")
        page.wait_for_function(
            "() => (window.zmartConfig.groups || []).some((g) => g.includes('two'))",
            timeout=30_000)
        page.wait_for_timeout(6000)
        after = _what_is_shown(page)
        drawn = page.evaluate(
            "() => (window.zmartScene || []).filter("
            "  (s) => s.type === 'image' && (s.name || '').includes('two'))"
            ".map((s) => (s.source || []).length)")
        assert drawn == [9], f"the second dataset is not all there: {drawn}"
        assert after["lit"] > 0.05, (
            "after closing the first dataset, the second one drew almost "
            f"nothing: {after}"
        )
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def test_opening_it_again_after_closing_it_shows_the_same_picture(
        browser, built_dist, tmp_path):
    """Close an acquisition, open it again, and it comes back as it was.

    Closing is how an operator clears the screen mid-session, and opening the
    same folder again is what they do next. The second showing has to be the
    first one: the same tiles lit, in the same colour.

    It was not. The second open drew half the tiles, in a different colour,
    and only reloading the page put it right -- so whatever was wrong lived in
    what the page had kept, not in the data (2026-08-21). A gate here because
    nothing else exercises the same folder twice in one session: every other
    test opens once and closes at the end.
    """
    first = tmp_path / "overview"
    first.mkdir()
    from test_open_and_close import _store
    _store(first / "overview_pos001.ome.zarr", channels=1)
    _a_grid_scan(tmp_path / "twice", across=2)
    server = make_server(port=0, data_dir=first, site_dir=built_dist,
                         store="overview_pos001.ome.zarr")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1300, "height": 1000})
    try:
        page.goto(f"http://127.0.0.1:{server.server_address[1]}",
                  wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartConfig !== undefined", timeout=30_000)
        # Nothing of the starting acquisition in the measurement: what is
        # counted below has to be the reopened dataset's own pixels.
        page.get_by_title("Hide this acquisition").first.click()
        page.wait_for_timeout(500)

        _relive(page, tmp_path, "twice")
        page.wait_for_function(
            "() => (window.zmartConfig.groups || []).some((g) => g.includes('twice'))",
            timeout=30_000)
        page.wait_for_timeout(6000)
        once = _what_is_shown(page)
        assert once["lit"] > 0.05, f"nothing was drawn the first time: {once}"

        group = page.evaluate(
            "() => (window.zmartConfig.groups || []).find((g) => g.includes('twice'))")
        page.locator(f'[aria-label="close {group}"]').click()
        page.wait_for_timeout(2500)
        assert _what_is_shown(page)["lit"] < 0.02, "closing it left it on screen"

        _relive(page, tmp_path, "twice")
        page.wait_for_function(
            "() => (window.zmartConfig.groups || []).some((g) => g.includes('twice'))",
            timeout=30_000)
        page.wait_for_timeout(6000)
        again = _what_is_shown(page)

        assert again["colours"] == once["colours"], (
            "the same data came back in a different colour: "
            f"{once['colours']} first, {again['colours']} second"
        )
        assert again["sources"] == once["sources"], (
            f"a different number of tiles came back: {once} then {again}")
        assert abs(again["lit"] - once["lit"]) < 0.05, (
            "the second showing is not the first: "
            f"{once['lit']:.1%} of the view lit, then {again['lit']:.1%}"
        )
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)
