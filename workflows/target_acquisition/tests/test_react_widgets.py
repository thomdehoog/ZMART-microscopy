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


def test_every_widget_ships_the_vendored_react_runtime():
    """React is vendored, not fetched: the notebooks work fully offline.

    Every widget's module must carry the embedded MIT-licensed builds and
    must NOT reach for a CDN — third-party code has no place in a page
    whose buttons drive a real microscope.
    """
    for cls in (
        wreact.OverviewViewerReact,
        wreact.FocusPickerReact,
        wreact.TargetExplorerReact,
        wreact.AcquisitionGalleryReact,
        wreact.RunStatusReact,
        wreact.CalibrationReportReact,
    ):
        assert "react.production.min.js" in cls._esm  # the vendored build's header
        assert "react-dom.production.min.js" in cls._esm
        assert "createRoot" in cls._esm
        assert "esm.sh" not in cls._esm  # no CDN fetch anywhere
        assert "new Map()" in cls._esm  # object URLs are owned per entry/key
        assert "URL.revokeObjectURL(old)" in cls._esm  # replacement cannot leak the old URL
        assert "${messageType}:reset" in cls._esm  # bounded snapshot replay starts cleanly
        assert "!view.byteLength" in cls._esm  # empty buffers stay empty fields, not broken icons
        assert "export default" in cls._esm


def test_vendored_react_is_the_official_mit_build():
    from pathlib import Path

    vendor = Path(wreact.__file__).parent / "vendor"
    assert (vendor / "LICENSE").exists()
    react_js = (vendor / "react.production.min.js").read_text(encoding="utf-8")
    assert "@license React" in react_js and "MIT license" in react_js


# --- overview viewer ---------------------------------------------------------


def test_overview_tiles_stream_as_messages_not_trait_resends(tmp_path):
    """Each new tile travels ONCE, as a message — the map so far is never resent.

    A trait update always retransmits the whole list, so appending tile 25
    to a trait would resend tiles 1-24 too: megabytes per update, growing
    with the square of the tile count, on the very channel the operator is
    watching. A freshly opened view catches up via the ``sync`` snapshot.
    """
    viewer = wreact.view_overview()
    sent = []
    viewer.send = lambda content, buffers=None, **_kw: sent.append((content, buffers))

    record = {"images": [str(_ome(tmp_path / "t1.ome.tif"))]}  # 30x20 px at 2 um
    viewer.add_acquisition(1, {"x": 0.0, "y": 0.0}, record)
    record2 = {"images": [str(_ome(tmp_path / "t2.ome.tif"))]}
    viewer.add_acquisition(2, {"x": 100.0, "y": 0.0}, record2)

    assert [m[0]["type"] for m in sent] == ["tile", "tile"]
    assert [m[0]["index"] for m in sent] == [0, 1]
    assert viewer.tiles == []  # nothing resent mid-stream

    # A browser view mounting (or re-mounting) asks for the full picture.
    viewer._route_message(None, {"type": "sync"}, None)
    assert [m[0]["type"] for m in sent[2:]] == ["tile:reset", "tile", "tile"]
    assert len(viewer.tiles) == 2
    tile = viewer.tiles[0]
    assert tile["src"] == ""  # pixels stay out of the JSON trait
    assert sent[3][1][0][:8] == b"\x89PNG\r\n\x1a\n"
    assert (tile["x0"], tile["y0"], tile["w"], tile["h"]) == (-30.0, -20.0, 60.0, 40.0)
    assert viewer.tiles[1]["x0"] == 70.0


def test_overview_channel_edit_recomposites(tmp_path):
    viewer = wreact.view_overview()
    viewer.add_acquisition(1, {"x": 0.0, "y": 0.0}, {"images": [str(_ome(tmp_path / "t.ome.tif"))]})
    sent = []
    viewer.send = lambda content, buffers=None, **_kw: sent.append((content, buffers))
    viewer.push_snapshot()
    before = sent[-1][1][0]
    channels = [dict(viewer.channels[0])]
    channels[0]["visible"] = False
    viewer.channels = channels  # what the browser does on an eye toggle
    assert sent[-1][1][0] != before


def test_overview_bogus_channel_contents_degrade_instead_of_raising(tmp_path):
    """The channels trait is browser-writable: junk must not freeze the map.

    An exception inside the recomposite would leave the tiles at a stale
    state with no message — so a colour that does not parse or a range
    that is not numbers falls back to safe defaults instead.
    """
    viewer = wreact.view_overview()
    viewer.add_acquisition(1, {"x": 0.0, "y": 0.0}, {"images": [str(_ome(tmp_path / "t.ome.tif"))]})
    viewer.channels = [{"color": "not-a-colour", "lo": None, "hi": "abc", "visible": True}]
    sent = []
    viewer.send = lambda content, buffers=None, **_kw: sent.append((content, buffers))
    viewer.push_snapshot()
    assert viewer.tiles[0]["src"] == ""
    assert sent[-1][1][0][:8] == b"\x89PNG\r\n\x1a\n"


def test_non_dict_messages_are_ignored(tmp_path):
    viewer = wreact.view_overview()
    viewer._route_message(None, "junk", None)  # any page JS can send this
    viewer._route_message(None, ["still", "junk"], None)
    assert viewer.status == ""


def test_overview_channel_mismatch_is_refused(tmp_path):
    viewer = wreact.view_overview()
    viewer.add_acquisition(1, {"x": 0.0, "y": 0.0}, {"images": [str(_ome(tmp_path / "a.ome.tif"))]})
    with pytest.raises(ValueError, match="channel count"):
        viewer.add_acquisition(
            2,
            {"x": 100.0, "y": 0.0},
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

    # The map refits after EVERY point, plus one final render on commit
    # (which is also what serves a re-measure that reuses every point).
    assert heatmap_states == [1, 2, 3, 3]
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

    sent = []
    gallery.send = lambda content, buffers=None, **_kw: sent.append((content, buffers))
    gallery.handle_message({"type": "acquire", "count": "2"})

    # One message per acquisition draws live; commit replays bounded binary
    # chunks after a reset so a newly mounted view has the complete result.
    assert [m[0]["type"] for m in sent] == ["row:reset", "row", "row", "row:reset", "row", "row"]
    assert [m[0]["index"] for m in sent if m[0]["type"] == "row"] == [0, 1, 0, 1]
    assert [m[0]["entry"]["stream_index"] for m in sent if m[0]["type"] == "row"] == [0, 1, 0, 1]
    assert len(gallery.records) == 2 == len(gallery.picked)
    assert len(gallery.rows) == 2
    assert gallery.rows[0]["low_src"] == ""
    assert sent[-1][1][0][:8] == b"\x89PNG\r\n\x1a\n"
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


def test_gallery_scripted_run_arms_the_click_debounce(tmp_path):
    """A click queued behind a SCRIPTED run must be eaten like any other.

    ``gallery.acquire(...)`` in a cell is a documented pattern; while it
    runs, the browser button stays clickable and clicks queue. Without the
    same bookkeeping as the button path, the queued click would start a
    second hardware run the instant the cell finishes.
    """
    session = _AcqSession(tmp_path)
    gallery = wreact.acquire_gallery(session, _targets(3), [_overview(tmp_path)])
    gallery.acquire(1)  # scripted, not a button press
    before = session.count
    gallery.handle_message({"type": "acquire", "count": "1"})  # the queued click
    assert session.count == before
    assert "ignored a click" in gallery.status


def test_gallery_failed_second_run_uncommits_the_first_result(tmp_path):
    """A failed re-run must not leave the previous run posing as the result."""

    class _FailsLater(_AcqSession):
        def acquire(self, **kwargs):
            if self.count >= 2:  # run 1 acquires 2; run 2 fails at once
                raise RuntimeError("stage stalled")
            return super().acquire(**kwargs)

    gallery = wreact.acquire_gallery(_FailsLater(tmp_path), _targets(4), [_overview(tmp_path)])
    first = gallery.acquire(2)
    assert gallery.records == first
    gallery._last_run_ended = None  # bypass the click debounce in the test
    gallery.handle_message({"type": "acquire", "count": "2"})
    assert "failed: stage stalled" in gallery.status
    assert gallery.picked == [] and gallery.records == []


def test_gallery_refused_run_does_not_arm_the_debounce(tmp_path):
    """After "the gate is empty", a corrective click must work immediately.

    A refusal never touched the hardware, so treating the operator's next
    click as "queued during the previous run" would just be confusing.
    """
    explorer = wreact.explore_targets(_targets(3), [_overview(tmp_path)])
    explorer.gate = {"x": [99.0, 100.0]}  # nothing passes
    session = _AcqSession(tmp_path)
    gallery = wreact.acquire_gallery(session, explorer, [_overview(tmp_path)])
    gallery.handle_message({"type": "acquire", "count": "1"})
    assert "the gate is empty" in gallery.status
    explorer.gate = {}  # the operator fixes the gate and clicks again at once
    gallery.handle_message({"type": "acquire", "count": "1"})
    assert session.count == 1  # the second click ran


def test_forged_gated_mask_cannot_widen_the_gate(tmp_path):
    """The synced mask is display output; acquisition recomputes the truth.

    Anything running in the browser page can write traits, so a crafted
    ``gated_mask`` of all-True must not make the acquisition sample
    targets outside the drawn gate.
    """
    explorer = wreact.explore_targets(_targets(4), [_overview(tmp_path)])
    explorer.gate = {"x": [2.0, 3.0]}
    explorer.gated_mask = [True, True, True, True]  # forged from the page
    assert {t["x"] for t in explorer.gated} == {2.0, 3.0}
    assert explorer.gated_mask == [False, False, True, True]  # display healed


def test_malformed_gate_contents_degrade_instead_of_raising(tmp_path):
    """A half-typed threshold (null/NaN from the browser) must not raise.

    An exception inside the gate observer would freeze ``gated_mask`` at a
    stale state while the stored gate says something else — the next
    Acquire would then sample from a gate the operator is not seeing.
    """
    explorer = wreact.explore_targets(_targets(4), [_overview(tmp_path)])
    explorer.gate = {"x": [None, 100], "lasso": "not-a-lasso"}
    assert explorer.gated_mask == [True] * 4  # unparseable pieces do not gate
    explorer.gate = {"x": [2.0, 3.0]}
    assert [t["x"] for t in explorer.gated] == [2.0, 3.0]  # still fully alive


def test_explorer_hover_crops_are_cached(tmp_path, monkeypatch):
    """A fast mouse over many dots must not queue seconds of disk reads."""
    import workflow.react._widgets as widgets_module

    calls = []
    real = widgets_module.crop_for_target

    def _counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(widgets_module, "crop_for_target", _counting)
    explorer = wreact.explore_targets(_targets(2), [_overview(tmp_path)])
    explorer.handle_message({"type": "hover", "index": 1})
    explorer.handle_message({"type": "hover", "index": 1})
    explorer.handle_message({"type": "hover", "index": 1})
    assert len(calls) == 1


def test_focus_failed_measure_does_not_expose_a_partial_surface():
    """A mid-run failure must invalidate the streamed partial fit."""

    class _FailsOnSecond(_FocusSession):
        def __init__(self):
            super().__init__()
            self.autofocus_runs = 0

        def run_procedure(self, procedure):
            if procedure["name"] == "autofocus":
                self.autofocus_runs += 1
                if self.autofocus_runs >= 2:
                    raise RuntimeError("autofocus lost")
            return super().run_procedure(procedure)

    picker = wreact.pick_focus_points(_FailsOnSecond(), seed=False)
    picker.points = [{"x": 0.0, "y": 0.0}, {"x": 10.0, "y": 0.0}]
    picker.handle_message({"type": "measure"})
    assert "failed: autofocus lost" in picker.status
    assert picker.focus is None and picker.heatmap == {}
    with pytest.raises(RuntimeError, match="not been measured"):
        picker.require_focus()


def test_focus_measure_fresh_forgets_the_cache():
    """'Measure fresh' re-drives every point — for when the focus drifted."""

    class _Counting(_FocusSession):
        def __init__(self):
            super().__init__()
            self.autofocus_runs = 0

        def run_procedure(self, procedure):
            if procedure["name"] == "autofocus":
                self.autofocus_runs += 1
            return super().run_procedure(procedure)

    session = _Counting()
    picker = wreact.pick_focus_points(session, seed=False)
    picker.points = [{"x": 0.0, "y": 0.0}, {"x": 10.0, "y": 0.0}]
    picker.handle_message({"type": "measure"})
    assert session.autofocus_runs == 2
    picker._last_run_ended = None  # bypass the click debounce in the test
    picker.handle_message({"type": "measure", "fresh": True})
    assert session.autofocus_runs == 4  # every point measured again


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
    sent = []
    viewer.send = lambda content, buffers=None, **_kw: sent.append((content, buffers))
    viewer.push_snapshot()
    assert viewer.downsample == 2
    assert viewer._stacks[0].shape == (1, 1000, 1000)
    from io import BytesIO

    from PIL import Image

    snapshot_png = next(buffers[0] for content, buffers in sent if content["type"] == "tile")
    with Image.open(BytesIO(snapshot_png)) as image:
        assert image.width * image.height <= 250_000
    # ...while the physical extent stays exact.
    assert (viewer.tiles[0]["w"], viewer.tiles[0]["h"]) == (2000.0, 2000.0)


def test_gallery_row_images_respect_the_pixel_budget():
    """Full-resolution target images must be shrunk before travelling."""
    from workflow.react._support import shrink_to_budget

    big = np.zeros((2400, 2400), dtype=np.uint16)  # 5.8 Mpx, gallery budget 250k
    small = shrink_to_budget(big, 250_000)
    assert small.shape == (480, 480)
    tiny = np.zeros((40, 40), dtype=np.uint16)
    assert shrink_to_budget(tiny, 250_000) is tiny  # small images untouched


def test_worst_case_snapshot_payloads_stay_bounded():
    """Noisy images approximate PNG's incompressible upper-cost case."""
    from workflow.react._support import png_bytes, shrink_to_budget
    from workflow.react._widgets import (
        _GALLERY_IMAGE_PIXEL_BUDGET,
        _SNAPSHOT_IMAGE_PIXEL_BUDGET,
    )

    rng = np.random.default_rng(44)
    noisy_rgb = rng.random((1000, 1000, 3), dtype=np.float32)
    tile_png = png_bytes(shrink_to_budget(noisy_rgb, _SNAPSHOT_IMAGE_PIXEL_BUDGET))
    assert len(tile_png) * 25 < 20 * 1024 * 1024

    noisy_gray = rng.integers(0, 65536, size=(2400, 2400), dtype=np.uint16)
    row_png = png_bytes(shrink_to_budget(noisy_gray, _GALLERY_IMAGE_PIXEL_BUDGET))
    assert len(row_png) * 2 * 10 < 8 * 1024 * 1024


def test_explorer_ignores_bogus_hover_indices(tmp_path):
    explorer = wreact.explore_targets(_targets(2), [_overview(tmp_path)])
    for bogus in (99, -1, "nope", None, 1e999):  # 1e999 -> inf -> OverflowError
        explorer.handle_message({"type": "hover", "index": bogus})
    assert explorer.hover == {}


def test_react_remeasure_only_visits_new_points():
    class _Counting(_FocusSession):
        def __init__(self):
            super().__init__()
            self.autofocus_runs = 0

        def run_procedure(self, procedure):
            if procedure["name"] == "autofocus":
                self.autofocus_runs += 1
            return super().run_procedure(procedure)

    session = _Counting()
    picker = wreact.pick_focus_points(session, seed=False)
    picker.points = [{"x": 0.0, "y": 0.0}, {"x": 10.0, "y": 0.0}]
    picker.handle_message({"type": "measure"})
    assert session.autofocus_runs == 2

    picker._last_run_ended = None  # bypass the click debounce in the test
    picker.points = picker.points + [{"x": 5.0, "y": 5.0}]
    picker.handle_message({"type": "measure"})
    assert session.autofocus_runs == 3  # only the new point drove the stage
    assert "1 new, 2 reused" in picker.status
    assert len(picker.require_focus().measured) == 3


def test_react_tiles_wear_the_heatmap_colours():
    picker = wreact.pick_focus_points(
        _FocusSession(), [{"x": 0.0, "y": 0.0}, {"x": 100.0, "y": 0.0}], seed=False
    )
    assert all(q["fill"] == "" for q in picker.squares)
    picker.points = [{"x": 0.0, "y": 0.0}, {"x": 100.0, "y": 0.0}, {"x": 0.0, "y": 100.0}]
    picker.handle_message({"type": "measure"})
    fills = [q["fill"] for q in picker.squares]
    assert all(f.startswith("#") for f in fills)
    assert fills[0] != fills[1]  # different fitted z -> different colours
    # Editing points clears the tint with the surface.
    picker._last_run_ended = None
    picker.points = picker.points + [{"x": 7.0, "y": 7.0}]
    assert all(q["fill"] == "" for q in picker.squares)


# --- expansion wave 2: buffers, marks, cancel, observer, curation, presets ---


def test_stream_messages_carry_pixels_as_binary_buffers(tmp_path):
    """Image pixels ride as raw PNG buffers, not base64 text in the JSON."""
    viewer = wreact.view_overview()
    sent = []
    viewer.send = lambda content, buffers=None, **_kw: sent.append((content, buffers))
    viewer.add_acquisition(1, {"x": 0.0, "y": 0.0}, {"images": [str(_ome(tmp_path / "t.ome.tif"))]})
    content, buffers = sent[0]
    assert content["buffer_keys"] == ["src"]
    assert content["entry"]["src"] == ""  # no base64 in the JSON part
    assert buffers[0][:8] == b"\x89PNG\r\n\x1a\n"  # a real PNG in the buffer
    viewer.push_snapshot()  # snapshot catch-up is binary too, never base64
    reset, snapshot = sent[-2:]
    assert reset[0]["type"] == "tile:reset"
    assert snapshot[0]["type"] == "tile"
    assert snapshot[1][0][:8] == b"\x89PNG\r\n\x1a\n"
    assert viewer.tiles[0]["src"] == ""


def test_targets_overlay_on_the_map_and_follow_the_gate(tmp_path):
    explorer = wreact.explore_targets(_targets(4), [_overview(tmp_path)])
    viewer = wreact.view_overview()
    viewer.add_acquisition(1, {"x": 0.0, "y": 0.0}, {"images": [str(_ome(tmp_path / "t.ome.tif"))]})
    viewer.show_targets(_targets(4), explorer)
    assert [m["gated"] for m in viewer.marks] == [True] * 4
    explorer.gate = {"x": [2.0, 3.0]}  # the operator edits the gate...
    assert [m["gated"] for m in viewer.marks] == [False, False, True, True]  # ...map recolours
    viewer.show_targets(None)
    assert viewer.marks == []


def test_mark_hover_serves_the_cell_crop(tmp_path):
    viewer = wreact.view_overview()
    overview = _overview(tmp_path)
    viewer.add_tile(overview)
    viewer.show_targets(_targets(2))
    viewer.handle_message({"type": "mark", "index": 1})
    assert viewer.mark_hover["index"] == 1
    assert viewer.mark_hover["src"].startswith("data:image/png")
    for bogus in (99, -1, "nope", 1e999):
        viewer.handle_message({"type": "mark", "index": bogus})
    assert viewer.mark_hover["index"] == 1  # bogus indices change nothing


def test_cancel_stops_a_gallery_run_between_targets(tmp_path):
    """A requested cancel ends the run cleanly at a site boundary."""

    class _CancelAfterFirst(_AcqSession):
        def __init__(self, image_dir, gallery_ref):
            super().__init__(image_dir)
            self.gallery_ref = gallery_ref

        def acquire(self, **kwargs):
            record = super().acquire(**kwargs)
            self.gallery_ref.append(record)  # signal: first acquisition done
            return record

    acquired = []
    session = _CancelAfterFirst(tmp_path, acquired)
    gallery = wreact.acquire_gallery(session, _targets(3), [_overview(tmp_path)])

    real_send = gallery.send

    def _cancel_after_first(content, buffers=None, **kw):
        if content.get("type") == "row" and content["index"] == 0:
            gallery.request_cancel()  # as if the Cancel click arrived now

    gallery.send = _cancel_after_first

    gallery.handle_message({"type": "acquire", "count": "3"})
    assert "cancelled" in gallery.status  # shown via the failed: wrapper
    assert session.count == 1  # nothing acquired after the request
    assert gallery.picked == [] and gallery.records == []  # nothing committed
    gallery.send = real_send


def test_cancel_without_a_run_says_so(tmp_path):
    gallery = wreact.acquire_gallery(_AcqSession(tmp_path), _targets(2), [_overview(tmp_path)])
    gallery._route_message(None, {"type": "cancel"}, None)
    assert "no run is in progress" in gallery.status


def test_read_only_view_refuses_hardware_but_still_watches(tmp_path):
    session = _AcqSession(tmp_path)
    gallery = wreact.acquire_gallery(session, _targets(2), [_overview(tmp_path)])
    gallery.make_read_only()
    gallery._route_message(None, {"type": "acquire", "count": "1"}, None)
    assert session.count == 0
    assert "read-only" in gallery.status
    with pytest.raises(RuntimeError, match="read-only"):
        gallery.acquire(1)  # the scripted path is locked too
    gallery.busy = True
    gallery._route_message(None, {"type": "cancel"}, None)
    assert not gallery._cancel_requested  # a locked display cannot stop somebody else's run
    gallery.request_cancel()
    assert not gallery._cancel_requested  # direct/scripted cancellation is locked too
    gallery._route_message(None, {"type": "sync"}, None)  # watching still works
    assert gallery.rows == []


def test_read_only_model_restores_browser_writable_state(tmp_path):
    """The model-wide freeze covers traits, not just hardware messages."""
    viewer = wreact.view_overview()
    viewer.add_tile(_overview(tmp_path))
    original_channels = [dict(channel) for channel in viewer.channels]
    viewer.make_read_only()
    viewer.read_only = False  # forged display trait cannot hide the lock
    assert viewer.read_only is True
    viewer.channels = [{"color": "#ff0000", "lo": 0.0, "hi": 1.0}]
    assert viewer.channels == original_channels

    explorer = wreact.explore_targets(_targets(3), [_overview(tmp_path)])
    original_axes = (explorer.x_feature, explorer.y_feature)
    explorer.make_read_only()
    explorer.x_feature = explorer.features[-1]
    explorer.gate = {"x": [999.0, 1000.0]}
    assert (explorer.x_feature, explorer.y_feature) == original_axes
    assert explorer.gate == {}

    picker = wreact.pick_focus_points(_FocusSession(), seed=False)
    picker.points = [{"x": 0.0, "y": 0.0}]
    picker.handle_message({"type": "measure"})
    focus = picker.focus
    picker.make_read_only()
    picker.points = [{"x": 10.0, "y": 10.0}]
    assert picker.points == [{"x": 0.0, "y": 0.0}]
    assert picker.focus is focus  # a forged edit did not invalidate the fit


def test_read_only_locks_the_scripted_curation_path_too(tmp_path):
    """Frozen means frozen: verdicts refuse, and display equals truth."""
    gallery = wreact.acquire_gallery(
        _AcqSession(tmp_path), _targets(3), [_overview(tmp_path)], seed=1
    )
    gallery.acquire(2)
    gallery.set_verdict(0, "good")
    gallery.make_read_only()
    with pytest.raises(RuntimeError, match="read-only"):
        gallery.set_verdict(1, "bad")
    assert gallery._verdicts == ["good", None]
    # The synced trait (what every tab displays) matches the private truth
    # and matches what save_curation would write.
    assert list(gallery.verdicts) == gallery._verdicts

    import json

    saved = json.loads(gallery.save_curation(tmp_path / "run").read_text(encoding="utf-8"))
    assert [row["verdict"] for row in saved] == ["good", None]


def test_forged_read_only_true_is_healed_on_a_live_widget(tmp_path):
    """The mirror is honest in both directions, not only when frozen."""
    gallery = wreact.acquire_gallery(
        _AcqSession(tmp_path), _targets(2), [_overview(tmp_path)], seed=1
    )
    gallery.read_only = True  # a page script cannot blind every tab's buttons
    assert gallery.read_only is False
    gallery.make_read_only()
    assert gallery.read_only is True


def test_read_only_widgets_still_serve_hover_previews(tmp_path):
    """An observer may browse: display-only messages keep working."""
    explorer = wreact.explore_targets(_targets(2), [_overview(tmp_path)])
    explorer.make_read_only()
    explorer._route_message(None, {"type": "hover", "index": 0}, None)
    assert explorer.hover.get("index") == 0
    assert "read-only" not in explorer.status
    explorer._route_message(None, {"type": "pick", "index": 0}, None)  # state change
    assert "read-only" in explorer.status
    assert explorer.picked_indices == []

    viewer = wreact.view_overview()
    viewer.add_tile(_overview(tmp_path))
    viewer.show_targets(_targets(2))
    viewer.make_read_only()
    viewer._route_message(None, {"type": "mark", "index": 0}, None)
    assert viewer.mark_hover.get("index") == 0


def test_channels_initialise_on_a_viewer_frozen_while_empty(tmp_path):
    """Trusted Python-side display setup survives the freeze.

    Freezing an empty viewer and then streaming a scripted overview into it
    must not leave the channel controls empty (every tile would composite
    to black); the browser still cannot edit them.
    """
    viewer = wreact.view_overview()
    viewer.make_read_only()
    viewer.add_tile(_overview(tmp_path))
    assert viewer.channels and viewer.channels[0]["visible"] is True
    initialised = [dict(channel) for channel in viewer.channels]
    viewer.channels = [{"color": "#ff0000", "lo": 0.0, "hi": 1.0}]  # forged edit
    assert viewer.channels == initialised  # healed back to the trusted setup


def test_forged_busy_trait_neither_blocks_nor_cancels_runs(tmp_path):
    """``busy`` is a healed display mirror; the interlock reads Python truth.

    A page script faking a run must not block every real one behind
    "a run is already in progress", must not make Cancel claim it stopped
    something, and (on a concurrent host) must not be able to hide a real
    run from the overlap guard.
    """
    gallery = wreact.acquire_gallery(
        _AcqSession(tmp_path), _targets(3), [_overview(tmp_path)], seed=1
    )
    gallery.busy = True  # page-script forgery
    assert gallery.busy is False  # healed immediately
    gallery.request_cancel()
    assert not gallery._cancel_requested  # there was no run to cancel
    assert "no run is in progress" in gallery.status
    gallery.acquire(1)  # and the interlock did not believe the forgery
    assert len(gallery.records) == 1


def test_forged_unknown_axis_is_healed_instead_of_crashing(tmp_path):
    """An axis name that is not a feature must degrade, never raise.

    Unknown names arrive only from page scripts or stale gate files; they
    would plot every dot at NaN and crash the histogram mid-update,
    leaving the explorer half-updated — the exact failure the module's
    trust boundary promises cannot happen.
    """
    import math

    explorer = wreact.explore_targets(_targets(3), [_overview(tmp_path)])
    explorer.x_feature = explorer.features[-1]
    explorer.x_feature = "no_such_feature"  # page-script forgery
    assert explorer.x_feature == explorer.features[-1]  # previous axis restored
    assert "unknown feature" in explorer.status
    assert all(math.isfinite(d["fx"]) for d in explorer.dots)


def test_forged_pick_and_gate_display_traits_are_healed(tmp_path):
    """Picks, acquired marks and the gate display heal from Python truth.

    A forged ``acquired_indices`` could hide an already-imaged cell and
    invite a second exposure; a forged ``picked_indices`` relabels the
    "Acquire selected" button while the run would image different cells.
    """
    explorer = wreact.explore_targets(_targets(4), [_overview(tmp_path)])
    explorer.toggle_pick(1)
    explorer.note_acquired([explorer.targets[2]])
    explorer.picked_indices = [0, 3]  # forgery: relabel the picks
    assert explorer.picked_indices == [1]
    explorer.acquired_indices = []  # forgery: hide an imaged cell
    assert explorer.acquired_indices == [2]
    explorer.gated_mask = [False] * 4  # forgery: blank the gate display
    assert explorer.gated_mask == explorer._mask_from_gate()


def test_gallery_verdicts_record_curation(tmp_path):
    session = _AcqSession(tmp_path)
    gallery = wreact.acquire_gallery(session, _targets(3), [_overview(tmp_path)], seed=1)
    gallery.acquire(2)
    assert gallery.verdicts == [None, None]
    gallery.handle_message({"type": "verdict", "index": 0, "value": "good"})
    gallery.handle_message({"type": "verdict", "index": 1, "value": "bad"})
    gallery.handle_message({"type": "verdict", "index": 99, "value": "good"})  # ignored
    gallery.handle_message({"type": "verdict", "index": 0, "value": "sideways"})  # ignored
    assert gallery.verdicts == ["good", "bad"]

    import json

    path = gallery.save_curation(tmp_path / "run")
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert [r["verdict"] for r in saved] == ["good", "bad"]
    assert all(r["position_label"] for r in saved)


def test_forged_verdict_trait_cannot_truncate_curation(tmp_path):
    gallery = wreact.acquire_gallery(
        _AcqSession(tmp_path), _targets(3), [_overview(tmp_path)], seed=1
    )
    gallery.acquire(2)
    gallery.set_verdict(0, "good")
    gallery.verdicts = []  # forged browser trait write
    assert gallery.verdicts == ["good", None]

    import json

    saved = json.loads(gallery.save_curation(tmp_path / "run").read_text(encoding="utf-8"))
    assert len(saved) == 2
    assert [row["verdict"] for row in saved] == ["good", None]


def test_cancelled_run_leaves_an_honest_empty_curation(tmp_path):
    """Nothing commits on cancel — so nothing can be judged or saved wrong.

    The streamed rows stay on screen (their files ARE saved on disk), but
    verdicts, records and curation.json must keep describing the same
    committed rows: none.
    """
    gallery = wreact.acquire_gallery(_AcqSession(tmp_path), _targets(3), [_overview(tmp_path)])

    def _cancel_after_first(content, buffers=None, **_kw):
        if content.get("type") == "row" and content["index"] == 0:
            gallery.request_cancel()

    gallery.send = _cancel_after_first
    gallery.handle_message({"type": "acquire", "count": "3"})
    assert "cancelled" in gallery.status
    assert gallery.records == [] and gallery._verdicts == []
    assert list(gallery.verdicts) == []

    with pytest.raises(ValueError, match="cancelled or failed"):
        gallery.set_verdict(0, "good")  # the row on screen was never committed
    gallery.handle_message({"type": "verdict", "index": 0, "value": "good"})
    assert "not committed" in gallery.status  # a browser click gets an explanation

    import json

    saved = json.loads(gallery.save_curation(tmp_path / "run").read_text(encoding="utf-8"))
    assert saved == []  # honest empty record, not a crash and not stale rows


def test_after_acquire_failure_rolls_back_curation_truth(tmp_path):
    """The simulation/image-rewrite hook is part of the uncommitted run."""

    def _fail_after_acquire(_records):
        raise RuntimeError("image rewrite failed")

    gallery = wreact.acquire_gallery(
        _AcqSession(tmp_path),
        _targets(3),
        [_overview(tmp_path)],
        after_acquire=_fail_after_acquire,
    )
    with pytest.raises(RuntimeError, match="image rewrite failed"):
        gallery.acquire(2)

    assert gallery.records == []
    assert len(gallery._row_entries) == 2  # saved images remain visible
    assert gallery._verdicts == [] and list(gallery.verdicts) == []
    with pytest.raises(ValueError, match="cancelled or failed"):
        gallery.set_verdict(0, "good")

    import json

    saved = json.loads(gallery.save_curation(tmp_path / "run").read_text(encoding="utf-8"))
    assert saved == []


def test_sparse_midrun_row_keeps_its_authoritative_verdict_index(tmp_path):
    gallery = wreact.acquire_gallery(
        _AcqSession(tmp_path), _targets(6), [_overview(tmp_path)], seed=2
    )
    sent = []
    gallery.send = lambda content, buffers=None, **_kw: sent.append((content, buffers))
    gallery.acquire(6)

    row_five = next(
        content["entry"]
        for content, _buffers in sent
        if content["type"] == "row" and content["index"] == 5
    )
    sparse = [None] * 6
    sparse[5] = row_five
    displayed = [entry for entry in sparse if entry is not None]
    assert displayed[0]["stream_index"] == 5
    assert "verdictBtn(rowIndex" in wreact.AcquisitionGalleryReact._esm

    gallery.handle_message(
        {"type": "verdict", "index": displayed[0]["stream_index"], "value": "good"}
    )
    assert gallery.verdicts == [None, None, None, None, None, "good"]


def test_gate_presets_round_trip(tmp_path):
    explorer = wreact.explore_targets(_targets(4), [_overview(tmp_path)])
    explorer.x_feature = "area_px"
    explorer.gate = {"x": [15.0, 35.0]}  # thresholds on the area feature
    explorer.save_gate(tmp_path / "gate.json")

    again = wreact.explore_targets(_targets(4), [_overview(tmp_path)])
    again.load_gate(tmp_path / "gate.json")
    assert again.x_feature == "area_px"
    assert [t["x"] for t in again.gated] == [1.0, 2.0]  # areas 20 and 30 pass

    few = wreact.explore_targets(
        [{"x": 1.0, "y": 2.0, "source": {"naming_p": 0, "centroid_col_row_px": (1.0, 1.0)}}]
    )
    with pytest.raises(ValueError, match="do not have"):
        few.load_gate(tmp_path / "gate.json")  # saved axes may not exist here


def test_explorer_histograms_follow_the_axes(tmp_path):
    explorer = wreact.explore_targets(_targets(6), [_overview(tmp_path)])
    assert len(explorer.hist["x"]) == 20 and max(explorer.hist["x"]) == 1.0
    before = list(explorer.hist["x"])
    explorer.x_feature = "y"  # three repeated values, a different shape
    assert explorer.hist["x"] != before  # a new feature, a new distribution


def test_display_settings_round_trip(tmp_path):
    viewer = wreact.view_overview()
    viewer.add_acquisition(1, {"x": 0.0, "y": 0.0}, {"images": [str(_ome(tmp_path / "t.ome.tif"))]})
    viewer.channels = [dict(viewer.channels[0], color="#ff0000", lo=5.0, hi=99.0)]
    viewer.save_display(tmp_path / "display.json")

    again = wreact.view_overview()
    again.add_acquisition(1, {"x": 0.0, "y": 0.0}, {"images": [str(_ome(tmp_path / "t2.ome.tif"))]})
    again.load_display(tmp_path / "display.json")
    assert again.channels[0]["color"] == "#ff0000"
    assert (again.channels[0]["lo"], again.channels[0]["hi"]) == (5.0, 99.0)


def test_focus_status_names_the_worst_fit_residual():
    picker = wreact.pick_focus_points(_FocusSession(), seed=False)
    picker.points = [{"x": 0.0, "y": 0.0}, {"x": 10.0, "y": 0.0}, {"x": 0.0, "y": 10.0}]
    picker.handle_message({"type": "measure"})
    assert "largest fit residual" in picker.status
    assert all("residual_um" in m for m in picker.measured)


def test_run_status_reports_the_steps():
    status = wreact.run_status()
    status.refresh({})  # a fresh notebook: everything still to do
    assert all(r["state"] == "todo" for r in status.rows)
    ns = {
        "zmart_controller": type("Session", (), {"closed": False})(),
        "engine": object(),
        "ROOT": "/tmp/run",
        "overview_state": {
            "changeable": {"job": "Over"},
            "observed": {"limits": {"source": "machine", "is_fallback": False}},
        },
        "target_state": {"changeable": {"job": "Over"}},  # same job: worth a look
        "positions": [1, 2],
    }
    status.refresh(ns)
    by_label = {r["label"]: r for r in status.rows}
    assert by_label["Microscope"]["state"] == "ok"
    assert by_label["Overview job"]["state"] == "ok"
    assert by_label["Target job"]["state"] == "warn"  # same as the overview job
    assert by_label["Focus surface"]["state"] == "todo"


def test_run_status_does_not_call_dead_or_unknown_objects_connected():
    from workflow._run_status import run_status_rows

    dead = type("Session", (), {"closed": True})()
    stopped = type("Engine", (), {"shut_down": True})()
    rows = {
        row["label"]: row for row in run_status_rows({"zmart_controller": dead, "engine": stopped})
    }
    assert rows["Microscope"]["state"] == "warn"
    assert "disconnected" in rows["Microscope"]["detail"]
    assert rows["Analysis engine"]["state"] == "warn"

    unknown = {row["label"]: row for row in run_status_rows({"zmart_controller": object()})}
    assert unknown["Microscope"]["state"] == "warn"
    assert "unknown" in unknown["Microscope"]["detail"]


def test_calibration_report_panel_wraps_the_check_report():
    report = {
        "n_sites": 4,
        "n_trusted": 4,
        "radius_um": 100.0,
        "mean_dx_um": 3.0,
        "mean_dy_um": -2.0,
        "mean_offset_um": 3.6,
        "stage_scatter_rms_um": 0.2,
        "max_offset_um": 3.9,
        "sites": [
            {"x": 100.0, "y": 0.0, "dx_um": 3.0, "dy_um": -2.0, "trusted": True, "confidence": 4}
        ],
    }
    panel = wreact.calibration_report(report, acceptable_um=2.0)
    assert panel.report["mean_dx_um"] == 3.0
    assert panel.acceptable_um == 2.0


# --- UX wave 3: pick-to-acquire, cross-links, ETA, scale bars, palette -------


def test_click_to_pick_and_acquire_selected(tmp_path):
    """Point at the cells you want: picks acquire exactly, and only, them."""
    explorer = wreact.explore_targets(_targets(4), [_overview(tmp_path)])
    explorer.handle_message({"type": "pick", "index": 1})
    explorer.handle_message({"type": "pick", "index": 3})
    assert explorer.picked_indices == [1, 3]
    explorer.handle_message({"type": "pick", "index": 3})  # click again = un-pick
    assert explorer.picked_indices == [1]
    explorer.handle_message({"type": "pick", "index": 99})  # bogus: ignored
    assert explorer.picked_indices == [1]

    session = _AcqSession(tmp_path)
    gallery = wreact.acquire_gallery(session, explorer, [_overview(tmp_path)])
    assert gallery.selected_count == 1
    records = gallery.acquire_selected()
    assert len(records) == 1
    assert gallery.picked == [explorer.targets[1]]
    # The acquired cell is remembered and leaves the pick set.
    assert explorer.acquired_indices == [1]
    assert explorer.picked_indices == []
    assert gallery.selected_count == 0


def test_acquire_selected_refuses_a_pick_outside_the_gate(tmp_path):
    """A pick the gate excludes refuses the run loudly — never quiet imaging."""
    explorer = wreact.explore_targets(_targets(4), [_overview(tmp_path)])
    explorer.handle_message({"type": "pick", "index": 0})
    explorer.gate = {"x": [2.0, 3.0]}  # the pick (x=0) is now gated out
    session = _AcqSession(tmp_path)
    gallery = wreact.acquire_gallery(session, explorer, [_overview(tmp_path)])
    gallery.handle_message({"type": "acquire_selected"})
    assert "outside the current gate" in gallery.status
    assert session.count == 0


def test_acquire_selected_needs_picks_and_an_explorer(tmp_path):
    session = _AcqSession(tmp_path)
    explorer = wreact.explore_targets(_targets(2), [_overview(tmp_path)])
    gallery = wreact.acquire_gallery(session, explorer, [_overview(tmp_path)])
    with pytest.raises(RuntimeError, match="no cells are picked"):
        gallery.acquire_selected()
    plain = wreact.acquire_gallery(session, _targets(2), [_overview(tmp_path)])
    with pytest.raises(RuntimeError, match="explorer as the gallery's source"):
        plain.acquire_selected()
    assert session.count == 0


def test_forged_picked_indices_trait_cannot_choose_targets(tmp_path):
    """The pick set lives in Python; a page script writing the trait is display noise."""
    explorer = wreact.explore_targets(_targets(3), [_overview(tmp_path)])
    explorer.picked_indices = [0, 1, 2]  # forged from the page
    assert explorer.picked_targets == []  # Python's truth is empty
    gallery = wreact.acquire_gallery(_AcqSession(tmp_path), explorer, [_overview(tmp_path)])
    with pytest.raises(RuntimeError, match="no cells are picked"):
        gallery.acquire_selected()


def test_map_ring_click_forwards_the_pick_to_the_explorer(tmp_path):
    explorer = wreact.explore_targets(_targets(3), [_overview(tmp_path)])
    viewer = wreact.view_overview()
    viewer.add_acquisition(1, {"x": 0.0, "y": 0.0}, {"images": [str(_ome(tmp_path / "t.ome.tif"))]})
    viewer.show_targets(_targets(3), explorer)
    viewer.handle_message({"type": "pick", "index": 2})
    assert explorer.picked_indices == [2]
    assert viewer.marks[2]["picked"] is True  # the map shows it immediately
    explorer.note_acquired([explorer.targets[2]])
    assert viewer.marks[2]["acquired"] is True and viewer.marks[2]["picked"] is False


def test_duplicate_valued_targets_are_each_marked_acquired(tmp_path):
    first = _targets(1)[0]
    second = {
        **first,
        "source": dict(first["source"]),
    }
    explorer = wreact.explore_targets([first, second], [_overview(tmp_path)])
    explorer.toggle_pick(0)
    explorer.toggle_pick(1)
    explorer.note_acquired([first, second])
    assert explorer.acquired_indices == [0, 1]
    assert explorer.picked_indices == []


def test_react_copied_duplicates_resolve_across_calls_idempotently(tmp_path):
    first = _targets(1)[0]
    second = {**first, "source": dict(first["source"])}
    explorer = wreact.explore_targets([first, second], [_overview(tmp_path)])
    copied_first = {**first, "source": dict(first["source"])}
    copied_second = {**second, "source": dict(second["source"])}

    explorer.note_acquired([copied_first])
    assert explorer.acquired_indices == [0]
    explorer.note_acquired([first])
    assert explorer.acquired_indices == [0]
    explorer.note_acquired([copied_second])
    assert explorer.acquired_indices == [0, 1]


def test_react_copy_cannot_steal_an_original_index_in_the_same_call(tmp_path):
    """Identity wins even when the copy comes first in the call.

    A copied record and an original of two equal-valued cells arrive in one
    ``note_acquired`` call, copy first: both cells must end up marked, or
    one stays available for accidental re-acquisition.
    """
    first = _targets(1)[0]
    second = {**first, "source": dict(first["source"])}
    explorer = wreact.explore_targets([first, second], [_overview(tmp_path)])
    copied_second = {**second, "source": dict(second["source"])}

    explorer.note_acquired([copied_second, first])
    assert explorer.acquired_indices == [0, 1]


def test_hover_cross_highlights_between_explorer_and_map(tmp_path):
    explorer = wreact.explore_targets(_targets(2), [_overview(tmp_path)])
    viewer = wreact.view_overview()
    viewer.add_tile(_overview(tmp_path))
    viewer.show_targets(_targets(2), explorer)
    explorer.handle_message({"type": "hover", "index": 1})
    assert viewer.mark_hover.get("index") == 1  # explorer -> map
    viewer.handle_message({"type": "mark", "index": 0})
    assert explorer.hover.get("index") == 0  # map -> explorer


def test_eta_text_is_honest():
    import time as _time

    from workflow._acquisition_widget import _eta_text

    now = _time.monotonic()
    assert _eta_text(0, 10, now) == ""  # nothing done: no basis
    assert _eta_text(5, None, now) == ""  # no total: no basis
    assert _eta_text(10, 10, now) == ""  # finished: nothing left
    started = now - 10.0  # 2 s per site, 3 of 8 done -> ~10 s... scaled below
    text = _eta_text(2, 8, started)  # 5 s/site, 6 left -> ~30 s
    assert "s left" in text
    text = _eta_text(1, 100, now - 60.0)  # 60 s/site, 99 left -> minutes
    assert "min left" in text


def test_overview_expect_tiles_gives_progress_status(tmp_path):
    viewer = wreact.view_overview()
    viewer.expect_tiles(3)
    viewer.add_acquisition(1, {"x": 0.0, "y": 0.0}, {"images": [str(_ome(tmp_path / "a.ome.tif"))]})
    assert viewer.status.startswith("tile 1 of 3")


def test_gallery_rows_carry_width_for_the_scale_bar(tmp_path):
    session = _AcqSession(tmp_path)
    gallery = wreact.acquire_gallery(session, _targets(2), [_overview(tmp_path)], seed=1)
    gallery.acquire(1)
    assert gallery.rows[0]["width_um"] == pytest.approx(10.0)  # 40 px * 0.25 um


def test_ranged_crop_encoding_uses_the_display_window():
    from workflow.react._support import png_data_url, png_data_url_ranged

    dim = np.full((8, 8), 10, dtype=np.uint16)
    dim[0, 0] = 20  # min-max would stretch 10..20 to full black..white
    auto = png_data_url(dim)
    ranged = png_data_url_ranged(dim, (0.0, 1000.0))  # the map's window: all dark
    assert auto != ranged
    assert png_data_url_ranged(dim, None) == auto  # no window: honest fallback


def test_colorblind_palette_is_available(tmp_path):
    from workflow.react._support import CHANNEL_HEX_COLORBLIND

    viewer = wreact.view_overview(palette="colorblind")
    viewer.add_acquisition(1, {"x": 0.0, "y": 0.0}, {"images": [str(_ome(tmp_path / "t.ome.tif"))]})
    assert viewer.channels[0]["color"] == CHANNEL_HEX_COLORBLIND[0]
    assert viewer.channels[0]["palette"] == list(CHANNEL_HEX_COLORBLIND)
