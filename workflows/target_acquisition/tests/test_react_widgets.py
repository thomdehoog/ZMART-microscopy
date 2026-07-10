"""The React widgets' Python side: traits, messages, streaming, parity.

The browser half (the ESM/React code) cannot run offline; these tests
drive the same Python state machine the browser talks to — trait updates,
message handlers, gating and image plumbing — plus a light structural
check on each widget's embedded module code.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
import tifffile  # noqa: E402

anywidget = pytest.importorskip("anywidget")

from workflow import react as wreact  # noqa: E402


def _ome(path, shape=(20, 30), ps=2.0, value=200, channels=1):
    h, w = shape
    desc = (
        '<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2016-06">'
        f'<Image><Pixels DimensionOrder="XYCZT" Type="uint16" SizeX="{w}" SizeY="{h}" '
        f'SizeC="{channels}" SizeZ="1" SizeT="1" PhysicalSizeX="{ps}" PhysicalSizeY="{ps}"/>'
        "</Image></OME>"
    )
    data = np.full((h, w), value, dtype=np.uint16)
    if channels > 1:
        data = np.stack([data * (c + 1) for c in range(channels)])
    tifffile.imwrite(path, data, description=desc)
    return path


def _overview(tmp_path, name="ov.tif", center=(0.0, 0.0)):
    path = tmp_path / name
    tifffile.imwrite(path, np.arange(100 * 100, dtype=np.uint16).reshape(100, 100))
    return {
        "image_path": path,
        "center_frame_um": center,
        "pixel_size_um": 1.0,
        "image_size_px": (100, 100),
        "label": 0,
    }


def _targets(n):
    return [
        {
            "x": float(i),
            "y": float(i % 3),
            "source": {
                "naming_p": 0,
                "centroid_col_row_px": (50.0, 50.0),
                "area_px": 10.0 * (i + 1),
                "mean_intensity": float(i),
            },
        }
        for i in range(n)
    ]


def test_every_widget_ships_a_react_module():
    for cls in (
        wreact.OverviewViewerReact,
        wreact.FocusPickerReact,
        wreact.TargetExplorerReact,
        wreact.AcquisitionGalleryReact,
    ):
        assert "esm.sh/react" in cls._esm
        assert "export default" in cls._esm


# --- overview viewer ---------------------------------------------------------


def test_overview_tiles_stream_and_extents_are_physical(tmp_path):
    viewer = wreact.view_overview()
    record = {"images": [str(_ome(tmp_path / "t1.ome.tif"))]}  # 30x20 px at 2 um
    viewer.add_acquisition(1, {"x": 0.0, "y": 0.0}, record)
    record2 = {"images": [str(_ome(tmp_path / "t2.ome.tif"))]}
    viewer.add_acquisition(2, {"x": 100.0, "y": 0.0}, record2)

    assert len(viewer.tiles) == 2
    tile = viewer.tiles[0]
    assert tile["src"].startswith("data:image/png;base64,")
    assert (tile["x0"], tile["y0"], tile["w"], tile["h"]) == (-30.0, -20.0, 60.0, 40.0)
    assert viewer.tiles[1]["x0"] == 70.0


def test_overview_channel_edit_recomposites(tmp_path):
    viewer = wreact.view_overview()
    viewer.add_acquisition(1, {"x": 0.0, "y": 0.0}, {"images": [str(_ome(tmp_path / "t.ome.tif"))]})
    before = viewer.tiles[0]["src"]
    channels = [dict(viewer.channels[0])]
    channels[0]["visible"] = False
    viewer.channels = channels  # what the browser does on an eye toggle
    assert viewer.tiles[0]["src"] != before


def test_overview_channel_mismatch_is_refused(tmp_path):
    viewer = wreact.view_overview()
    viewer.add_acquisition(1, {"x": 0.0, "y": 0.0}, {"images": [str(_ome(tmp_path / "a.ome.tif"))]})
    with pytest.raises(ValueError, match="channel count"):
        viewer.add_acquisition(
            2, {"x": 100.0, "y": 0.0},
            {"images": [str(_ome(tmp_path / "b.ome.tif", channels=3))]},
        )


# --- focus picker ------------------------------------------------------------


class _FocusSession:
    def __init__(self, seed_points=None):
        self.seed_points = seed_points

    def get_xyz(self):
        return {"z": {"value": 0.0}}

    def get_procedures(self):
        return {"get_focus_points": {}, "autofocus": {}}

    def set_xyz(self, x, y, z, **_kw):
        self._pos = (x, y)

    def run_procedure(self, procedure):
        if procedure["name"] == "get_focus_points":
            return {"positions": [dict(p) for p in (self.seed_points or [])]}
        x, y = self._pos
        return {"frame_z_um": 1.0 + 0.01 * x - 0.02 * y}


def test_focus_measure_streams_points_and_heatmap():
    picker = wreact.pick_focus_points(_FocusSession(), seed=False)
    picker.points = [{"x": 0.0, "y": 0.0}, {"x": 10.0, "y": 0.0}, {"x": 0.0, "y": 10.0}]

    heatmap_states = []
    original = picker._render_heatmap

    def _spy():
        result = original()
        heatmap_states.append(len(picker.measured))
        return result

    picker._render_heatmap = _spy
    picker.handle_message({"type": "measure"})

    assert heatmap_states == [1, 2, 3]  # the map refit after EVERY point
    assert picker.require_focus().z_at(0.0, 0.0) == pytest.approx(1.0)
    assert picker.heatmap["src"].startswith("data:image/png")
    assert not picker.busy


def test_focus_editing_points_invalidates():
    picker = wreact.pick_focus_points(_FocusSession(), seed=False)
    picker.points = [{"x": 0.0, "y": 0.0}]
    picker.handle_message({"type": "measure"})
    assert picker.focus is not None
    picker.points = picker.points + [{"x": 5.0, "y": 5.0}]  # browser adds a point
    with pytest.raises(RuntimeError, match="not been measured"):
        picker.require_focus()
    assert picker.heatmap == {}


def test_focus_seeds_from_lasx():
    picker = wreact.pick_focus_points(_FocusSession(seed_points=[{"x": 1.0, "y": 2.0}]))
    assert picker.points == [{"x": 1.0, "y": 2.0}]


def test_focus_measure_without_points_reports_on_status():
    picker = wreact.pick_focus_points(_FocusSession(), seed=False)
    picker.handle_message({"type": "measure"})
    assert "failed: no focus points" in picker.status


# --- target explorer -----------------------------------------------------------


def test_explorer_gates_with_thresholds_and_lasso(tmp_path):
    explorer = wreact.explore_targets(_targets(4), [_overview(tmp_path)])
    assert explorer.features == ["x", "y", "area_px", "mean_intensity"]
    assert explorer.gated_mask == [True] * 4

    explorer.gate = {"x": [1.0, 3.0]}  # thresholds on the x feature (frame x)
    assert [t["x"] for t in explorer.gated] == [1.0, 2.0, 3.0]

    # AND a lasso around x <= 2 (drawn by the browser in data coords)
    explorer.gate = {"x": [1.0, 3.0], "lasso": [[-1, -1], [2.5, -1], [2.5, 3], [-1, 3]]}
    assert [t["x"] for t in explorer.gated] == [1.0, 2.0]

    # switching an axis clears the whole gate
    explorer.x_feature = "area_px"
    assert explorer.gate == {}
    assert len(explorer.gated) == 4


def test_explorer_hover_serves_the_cell_crop(tmp_path):
    explorer = wreact.explore_targets(_targets(2), [_overview(tmp_path)], crop_um=20.0)
    explorer.handle_message({"type": "hover", "index": 1})
    assert explorer.hover["index"] == 1
    assert explorer.hover["src"].startswith("data:image/png")
    assert "target 1" in explorer.hover["title"]


def test_explorer_refuses_empty_targets():
    with pytest.raises(ValueError, match="no targets"):
        wreact.explore_targets([])


# --- acquisition gallery ---------------------------------------------------------


class _AcqSession:
    def __init__(self, image_dir):
        self.image_dir = image_dir
        self.count = 0
        self.states = []

    def set_state(self, state):
        self.states.append(state)

    def set_xyz(self, x, y, z, **_kw):
        pass

    def acquire(self, *, acquisition_type, position_label, options=None):
        self.count += 1
        path = _ome(self.image_dir / f"t{self.count}.ome.tif", shape=(40, 40), ps=0.25)
        return {"position_label": position_label, "images": [str(path)]}


def test_gallery_streams_rows_and_commits_on_success(tmp_path):
    session = _AcqSession(tmp_path)
    gallery = wreact.acquire_gallery(session, _targets(5), [_overview(tmp_path)], seed=3)

    rows_seen = []
    gallery.observe(lambda change: rows_seen.append(len(change["new"])), names="rows")
    gallery.handle_message({"type": "acquire", "count": "2"})

    # One trait push per acquisition — the browser draws each pair the
    # moment it exists. (The initial clear is silent when rows was empty.)
    assert rows_seen == [1, 2]
    assert len(gallery.records) == 2 == len(gallery.picked)
    assert gallery.rows[0]["low_src"].startswith("data:image/png")
    assert "same window" in gallery.rows[0]["high_title"]
    assert not gallery.busy


def test_gallery_bad_count_never_acquires(tmp_path):
    session = _AcqSession(tmp_path)
    gallery = wreact.acquire_gallery(session, _targets(3), [_overview(tmp_path)])
    for bad in ("0", "-2", "1.5", "many"):
        gallery.handle_message({"type": "acquire", "count": bad})
        assert "positive whole number" in gallery.status
    assert session.count == 0


def test_gallery_failure_commits_nothing(tmp_path):
    class _Fails(_AcqSession):
        def acquire(self, **kwargs):
            raise RuntimeError("hardware stopped")

    gallery = wreact.acquire_gallery(_Fails(tmp_path), _targets(3), [_overview(tmp_path)])
    gallery.handle_message({"type": "acquire", "count": "2"})
    assert "failed: hardware stopped" in gallery.status
    assert gallery.picked == [] and gallery.records == []
    assert not gallery.busy


def test_gallery_queued_click_is_ignored(tmp_path):
    session = _AcqSession(tmp_path)
    gallery = wreact.acquire_gallery(session, _targets(3), [_overview(tmp_path)])
    gallery.handle_message({"type": "acquire", "count": "1"})
    first = session.count
    gallery.handle_message({"type": "acquire", "count": "1"})  # queued double-click
    assert session.count == first
    assert "ignored a click" in gallery.status


def test_gallery_samples_from_an_explorer_gate(tmp_path):
    explorer = wreact.explore_targets(_targets(4), [_overview(tmp_path)])
    explorer.gate = {"x": [2.0, 3.0]}
    session = _AcqSession(tmp_path)
    gallery = wreact.acquire_gallery(session, explorer, [_overview(tmp_path)])
    gallery.acquire(10)
    assert {t["x"] for t in gallery.picked} == {2.0, 3.0}


def test_overview_auto_downsample_respects_the_pixel_budget(tmp_path):
    """Big tiles are shrunk for display so trait payloads stay manageable."""
    h, w = 2000, 2000  # 4 M pixels, budget is 1.5 M -> step 2
    desc = (
        '<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2016-06">'
        f'<Image><Pixels DimensionOrder="XYCZT" Type="uint16" SizeX="{w}" SizeY="{h}" '
        'SizeC="1" SizeZ="1" SizeT="1" PhysicalSizeX="1.0" PhysicalSizeY="1.0"/>'
        "</Image></OME>"
    )
    path = tmp_path / "big.ome.tif"
    tifffile.imwrite(path, np.zeros((h, w), dtype=np.uint16), description=desc)

    viewer = wreact.view_overview()
    viewer.add_acquisition(1, {"x": 0.0, "y": 0.0}, {"images": [str(path)]})
    assert viewer.downsample == 2
    assert viewer._stacks[0].shape == (1, 1000, 1000)
    # ...while the physical extent stays exact.
    assert (viewer.tiles[0]["w"], viewer.tiles[0]["h"]) == (2000.0, 2000.0)


def test_explorer_ignores_bogus_hover_indices(tmp_path):
    explorer = wreact.explore_targets(_targets(2), [_overview(tmp_path)])
    for bogus in (99, -1, "nope", None):
        explorer.handle_message({"type": "hover", "index": bogus})
    assert explorer.hover == {}
