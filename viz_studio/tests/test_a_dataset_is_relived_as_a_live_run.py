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
overlap is even; a transfer whose tiles sit at irregular offsets, or one that
holds several moments in time, is refused in plain words. Both of those are
their own later chapters.
"""

import json
import sys
import threading
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


class TestTheReplayDoor:
    """From the other tab, Replay relives the dataset in front of the operator."""

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
            page.get_by_label("replay as a live run").click()
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
