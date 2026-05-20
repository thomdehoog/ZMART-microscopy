"""Tests for workflow._geom.

The load-bearing test here is the no-drift assertion: the centre
panel of Step 5's visualization and the target hijack provider must
crop the overview file at *exactly* the same window for a given
(centroid, source pixel size, target shape, target pixel size).
Independent implementations of this math drifted in the past --
visualize used round + clamp, the hijack used floor + median pad --
and on edge cells they showed different windows. Pinning the shared
helper here makes that class of bug structurally unreachable.

The geometry tests below mostly duplicate the math tests in
test_target_mock.py, which is intentional: those tests exercise the
hijack provider end-to-end (read overview file, crop, resize, write
mock); these tests exercise the crop helper in isolation. If a
future contributor changes the helper signature, these tests fail
loud and tell them exactly which property broke.
"""
from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
import pytest

from workflow._geom import (
    crop_overview_at_target_fov,
    target_fov_window_in_overview,
)


# ─── Helpers ──────────────────────────────────────────────────────


def _uniform(shape, value=10000, dtype=np.uint16):
    return np.full(shape, value, dtype=dtype)


# ─── target_fov_window_in_overview ────────────────────────────────


class TestTargetFovWindow:
    """Window math used by both the crop helper (internally) and the
    left-panel red rectangle in visualize.py. Pinning here means the
    rectangle and the crop are guaranteed to describe the same
    physical region for the same cell.
    """

    def test_centred_window(self):
        x0, y0, w, h = target_fov_window_in_overview(
            centroid_col_row_px=(200.0, 200.0),
            source_pixel_size_um=0.65,
            target_shape_px=(200, 200),
            target_pixel_size_um=0.13,
        )
        # FOV = 200 * 0.13 = 26 µm; crop side = 26 / 0.65 = 40 px.
        assert (w, h) == (40, 40)
        # Centred on (200, 200) -> top-left (180, 180).
        assert (x0, y0) == (180, 180)

    def test_edge_cell_extends_past_overview_bounds(self):
        """For a cell near a tile edge, the window's top-left is
        negative -- honestly representing 'the target FOV extends
        past this tile.' The caller (crop helper or rectangle
        drawer) decides what to do with that."""
        x0, y0, w, h = target_fov_window_in_overview(
            centroid_col_row_px=(2.0, 2.0),
            source_pixel_size_um=1.0,
            target_shape_px=(80, 80),
            target_pixel_size_um=0.25,
        )
        # crop side = 80 * 0.25 / 1.0 = 20. Centred on (2, 2) -> (-8, -8).
        assert (w, h) == (20, 20)
        assert (x0, y0) == (-8, -8)

    def test_non_square_target_shape(self):
        x0, y0, w, h = target_fov_window_in_overview(
            centroid_col_row_px=(512.0, 512.0),
            source_pixel_size_um=0.65,
            target_shape_px=(100, 200),       # H=100, W=200
            target_pixel_size_um=0.13,
        )
        # H window = 100 * 0.13 / 0.65 = 20; W window = 40.
        assert (w, h) == (40, 20)

    def test_window_is_what_crop_helper_uses(self):
        """The crop helper MUST get its window from this function --
        not from its own internal math. Verified by spy: patch
        target_fov_window_in_overview, call crop_overview_at_target_fov,
        assert the spy fired with matching primitives."""
        overview = np.full((400, 400), 10000, dtype=np.uint16)
        sentinel_window = (50, 60, 40, 30)
        with mock.patch(
            "workflow._geom.target_fov_window_in_overview",
            return_value=sentinel_window,
        ) as spy:
            crop_overview_at_target_fov(
                overview,
                centroid_col_row_px=(120.0, 50.0),
                source_pixel_size_um=0.65,
                target_shape_px=(200, 200),
                target_pixel_size_um=0.13,
            )
        assert spy.call_count == 1
        # crop helper delegated; primitives match the user-facing
        # function's inputs.
        assert spy.call_args.kwargs == {
            "centroid_col_row_px": (120.0, 50.0),
            "source_pixel_size_um": 0.65,
            "target_shape_px": (200, 200),
            "target_pixel_size_um": 0.13,
        }


# ─── crop math ────────────────────────────────────────────────────


class TestCropMath:
    def test_crop_size_in_overview_pixels(self):
        """Crop width/height equal floor(target_size * target_px /
        source_px) per axis. Pick sizes that avoid half-pixel ties."""
        overview = _uniform((512, 512))
        crop = crop_overview_at_target_fov(
            overview,
            centroid_col_row_px=(256.0, 256.0),
            source_pixel_size_um=0.65,
            target_shape_px=(200, 200),       # (H, W)
            target_pixel_size_um=0.13,
        )
        # FOV = 200 * 0.13 = 26 µm; in overview px = 26 / 0.65 = 40.
        assert crop.shape == (40, 40)

    def test_crop_centred_on_centroid(self):
        """Unique marker at the centroid in the overview must land at
        the centre of the crop, ±1 px for rounding."""
        overview = _uniform((400, 400))
        overview[50, 120] = 60000           # [row, col] = [cy, cx]
        crop = crop_overview_at_target_fov(
            overview,
            centroid_col_row_px=(120.0, 50.0),   # (cx, cy)
            source_pixel_size_um=1.0,
            target_shape_px=(80, 80),
            target_pixel_size_um=0.25,
        )
        # Crop is 20 overview-px square. Marker at (cy=50, cx=120) -> crop centre (10, 10).
        peak = np.unravel_index(np.argmax(crop), crop.shape)
        assert abs(peak[0] - 10) <= 1
        assert abs(peak[1] - 10) <= 1

    def test_non_square_target_shape(self):
        """Per-axis FOV from per-axis target dimensions; scalar pixel
        size on both axes. 2048x1024 target shape -> 2:1 crop aspect."""
        overview = _uniform((1024, 1024))
        crop = crop_overview_at_target_fov(
            overview,
            centroid_col_row_px=(512.0, 512.0),
            source_pixel_size_um=0.65,
            target_shape_px=(100, 200),       # H=100, W=200
            target_pixel_size_um=0.13,
        )
        # H crop = 100 * 0.13 / 0.65 = 20; W crop = 200 * 0.13 / 0.65 = 40.
        assert crop.shape == (20, 40)

    def test_floor_rounding_not_round(self):
        """math.floor avoids banker's-rounding on .5 ties. Construct
        a case where round would give a different answer than floor."""
        overview = _uniform((512, 512))
        # FOV = 81 * 0.5 = 40.5 µm; in overview px (px=1.0) = 40.5.
        # floor -> 40, round -> 40 (banker's), so we need something
        # that breaks ties unambiguously. Use 41 * 0.5 = 20.5 / 1.0;
        # floor -> 20. round (banker's) -> 20 also (even). Try 0.7.
        # 41 * 0.7 = 28.7; floor -> 28. round -> 29. Different.
        crop = crop_overview_at_target_fov(
            overview,
            centroid_col_row_px=(256.0, 256.0),
            source_pixel_size_um=1.0,
            target_shape_px=(41, 41),
            target_pixel_size_um=0.7,
        )
        # Expected with floor: 28x28 (not 29x29).
        assert crop.shape == (28, 28)

    def test_dtype_preserved(self):
        overview = np.full((128, 128), 12345, dtype=np.uint16)
        crop = crop_overview_at_target_fov(
            overview,
            centroid_col_row_px=(64.0, 64.0),
            source_pixel_size_um=0.65,
            target_shape_px=(64, 64),
            target_pixel_size_um=0.13,
        )
        assert crop.dtype == np.uint16


# ─── edge-cell padding ────────────────────────────────────────────


class TestEdgePadding:
    def test_cell_at_corner_pads_with_median(self):
        """Cell at (cx=2, cy=2): crop window extends past the overview
        bounds. The out-of-bounds region must be filled with the
        overview's median intensity, not clipped or zeroed."""
        overview = np.full((400, 400), 30000, dtype=np.uint16)
        overview[2, 2] = 60000                       # cell centre
        crop = crop_overview_at_target_fov(
            overview,
            centroid_col_row_px=(2.0, 2.0),
            source_pixel_size_um=1.0,
            target_shape_px=(80, 80),
            target_pixel_size_um=0.25,
        )
        # Crop 20x20 centred on (2, 2) -> requested [-8:12, -8:12].
        # Top-left corner of crop is well inside the padded zone.
        assert crop.shape == (20, 20)
        assert crop[0, 0] == 30000

    def test_cell_far_off_overview_returns_all_pad(self):
        """Cell so far off-image the whole crop window is outside.
        Should return an all-pad array, not crash."""
        overview = np.full((100, 100), 5000, dtype=np.uint16)
        crop = crop_overview_at_target_fov(
            overview,
            centroid_col_row_px=(-500.0, -500.0),
            source_pixel_size_um=1.0,
            target_shape_px=(40, 40),
            target_pixel_size_um=0.5,
        )
        assert crop.shape == (20, 20)
        assert np.all(crop == 5000)


# ─── no-drift: hijack provider and visualization use the helper ───


class TestNoDriftAgainstCallers:
    """Pin the convergence: _mockprovider.build_target_provider and
    visualize.py's centre-panel render must both delegate to
    crop_overview_at_target_fov so they cannot disagree on the source
    window for the same cell.

    Two complementary structural pins:
      1. ``test_visualize_centroid_crop_equals_helper_output`` and
         ``test_hijack_provider_crop_step_equals_helper_output``
         compare actual outputs. Pin: visualize/hijack produce the
         same crop the helper would produce. Drift impossible
         regardless of implementation.
      2. ``test_both_call_sites_invoke_helper_with_same_primitives``
         spies on the helper symbol as imported by each module.
         Pin: both call sites delegate via the shared symbol (no
         copy-pasted local implementation), AND pass identical
         primitive arguments derived from the same domain inputs.

    Together: drift class is closed structurally, not just by
    matching test outputs in three lucky cases.
    """

    def _make_layout(self, tmp_dir: Path, hash6: str = "abcdef"):
        data = tmp_dir / "data" / "overview-scan"
        data.mkdir(parents=True, exist_ok=True)

        def _data_dir(kind):
            return tmp_dir / "data" / kind

        return SimpleNamespace(
            hash6=hash6, data_dir=_data_dir,
            metadata_dir=lambda kind: tmp_dir / "metadata" / kind,
        )

    def _write_overview(self, layout, image, *, g=0, p=0):
        import tifffile
        from _shared.output_layout import Naming, build_image_name
        naming = Naming(
            acquisition_type="overview-scan", hash6=layout.hash6,
            g=g, p=p,
        )
        path = layout.data_dir("overview-scan") / build_image_name(naming)
        tifffile.imwrite(path, image, photometric="minisblack")
        return path

    def _make_pick(self, *, centroid, position=0):
        from workflow.overview import Pick
        cx, cy = centroid
        return Pick(
            pick_id=("0", 0, 0, 1),
            tile_stage_xy_um=(0.0, 0.0),
            tile_zwide_um=0.0,
            source_pixel_size_um=(0.65, 0.65),
            source_image_size_px=(400, 400),
            centroid_col_row_px=(cx, cy),
            bbox_px=(0, 0, 10, 10), bbox_um=(0.0, 0.0),
            area_px=100, eccentricity=0.0, mean_intensity=0.0,
            cell_source_stage_xy_um=(0.0, 0.0),
            position=position,
        )

    def _make_target_record(self, *, target_pixel_size_um=0.13):
        from workflow.target import TargetRecord
        return TargetRecord(
            pick_id=("0", 0, 0, 1),
            cell_source_stage_xy_um=(0.0, 0.0),
            source_zwide_um=0.0,
            target_stage_xy_um=(0.0, 0.0),
            target_zwide_um=0.0,
            target_zoom=None,
            target_pixel_size_um=target_pixel_size_um,
            tif_path=None,
            success=True,
            error=None,
        )

    def _dummy_naming(self):
        from _shared.output_layout import Naming
        return Naming(
            acquisition_type="target-acquisition",
            hash6="abcdef", g=0, p=0,
        )

    # ── Output-equality pins (rev2's recommendation) ─────────────

    @pytest.mark.parametrize("centroid", [
        (200.0, 200.0),     # centred
        (120.0, 50.0),      # asymmetric -- fails any (col, row) swap
        (5.0, 5.0),         # near low-low corner (edge padding)
        (395.0, 395.0),     # near high-high corner (edge padding)
    ])
    def test_visualize_centroid_crop_equals_helper_output(
        self, tmp_path, centroid,
    ):
        """Visualize's centre-panel crop MUST go through the shared
        helper on the normal (target-acquired) path. Calls the
        actual visualize entry point and asserts byte-equality
        against the helper called directly with the primitives the
        call site translates from Pick + TargetRecord.

        A future refactor that inlines different crop math in
        visualize fails this test loudly across all four centroids
        (centred works either way; the asymmetric and edge cases
        catch the bugs).
        """
        from workflow.visualize import _centroid_crop_at_target_fov

        overview = np.full((400, 400), 10000, dtype=np.uint16)
        cy, cx = int(centroid[1]), int(centroid[0])
        if 0 <= cy < 400 and 0 <= cx < 400:
            overview[cy, cx] = 50000      # asymmetric sentinel
        pick = self._make_pick(centroid=centroid)
        record = self._make_target_record(target_pixel_size_um=0.13)
        target_img = np.zeros((200, 200), dtype=np.uint16)

        via_visualize = _centroid_crop_at_target_fov(
            overview, pick, record, target_img,
        )
        via_helper = crop_overview_at_target_fov(
            overview,
            centroid_col_row_px=centroid,
            source_pixel_size_um=0.65,
            target_shape_px=(200, 200),
            target_pixel_size_um=0.13,
        )
        assert np.array_equal(via_visualize, via_helper)

    def test_hijack_provider_crop_step_equals_helper_output(self, tmp_path):
        """Hijack provider's crop step (before resize) MUST go
        through the shared helper. Patches ``skimage.transform.resize``
        to identity so the provider's output IS the crop -- directly
        comparable to the helper's output.

        A future refactor that inlines different crop math in
        _mockprovider fails this test loudly.
        """
        from workflow._mockprovider import build_target_provider

        layout = self._make_layout(tmp_path)
        overview = np.full((400, 400), 10000, dtype=np.uint16)
        overview[50, 120] = 50000     # [cy=50, cx=120] sentinel
        self._write_overview(layout, overview)

        pick = self._make_pick(centroid=(120.0, 50.0), position=0)
        provider = build_target_provider(
            pick=pick, target_pixel_size_um=0.13, layout=layout,
        )

        # Identity resize: provider output == crop output. Need a
        # shape that matches the crop dims so identity-resize works
        # without reshape (target_shape = (40, 40) since FOV math
        # gives 40-px crop at this zoom).
        with mock.patch(
            "skimage.transform.resize",
            side_effect=lambda crop, shape, **k: crop,
        ):
            via_provider = provider(
                (40, 40), np.uint16, naming=self._dummy_naming(),
            )

        via_helper = crop_overview_at_target_fov(
            overview,
            centroid_col_row_px=(120.0, 50.0),
            source_pixel_size_um=0.65,
            target_shape_px=(40, 40),
            target_pixel_size_um=0.13,
        )
        assert np.array_equal(via_provider, via_helper)

    # ── Call-args structural pin (rev1's recommendation) ──────────

    def test_both_call_sites_invoke_helper_with_same_primitives(
        self, tmp_path,
    ):
        """Spy on the helper symbol as imported by each module.
        Assert both call sites delegate to it (the spy fires)
        with identical primitive arguments derived from the same
        domain inputs.

        Stronger than the output-comparison tests because it pins
        that the helper is the single source of truth -- a future
        contributor copy-pasting the crop math locally (producing
        identical output by coincidence) would still fail this test.
        """
        from workflow.visualize import _centroid_crop_at_target_fov
        from workflow._mockprovider import build_target_provider

        layout = self._make_layout(tmp_path)
        overview = np.full((400, 400), 10000, dtype=np.uint16)
        self._write_overview(layout, overview)

        pick = self._make_pick(centroid=(120.0, 50.0), position=0)
        record = self._make_target_record(target_pixel_size_um=0.13)
        # In production, target_img.shape == the shape the provider is
        # called with (both derive from the same saved target file).
        # Mirror that here so the primitives end up equal.
        target_shape = (40, 40)
        target_img = np.zeros(target_shape, dtype=np.uint16)

        sentinel = np.zeros(target_shape, dtype=np.uint16)

        # ── visualize side ───────────────────────────────────────
        with mock.patch(
            "workflow.visualize.crop_overview_at_target_fov",
            return_value=sentinel,
        ) as viz_spy:
            _centroid_crop_at_target_fov(
                overview, pick, record, target_img,
            )
        assert viz_spy.call_count == 1, (
            "visualize must delegate to the shared helper "
            "(spy never fired -- likely a local copy-paste)"
        )
        viz_kwargs = viz_spy.call_args.kwargs

        # ── hijack-provider side ─────────────────────────────────
        # build_target_provider returns a closure; calling it
        # invokes the helper. Stub resize to no-op so we don't
        # need a shape-matching sentinel.
        with mock.patch(
            "workflow._mockprovider.crop_overview_at_target_fov",
            return_value=sentinel,
        ) as hijack_spy, mock.patch(
            "skimage.transform.resize",
            side_effect=lambda crop, shape, **k: crop,
        ):
            provider = build_target_provider(
                pick=pick, target_pixel_size_um=0.13, layout=layout,
            )
            provider(target_shape, np.uint16, naming=self._dummy_naming())
        assert hijack_spy.call_count == 1, (
            "_mockprovider must delegate to the shared helper "
            "(spy never fired -- likely a local copy-paste)"
        )
        hijack_kwargs = hijack_spy.call_args.kwargs

        # The structural pin: same primitives derived from the
        # same domain inputs. Tuples and floats compare by value;
        # ndarrays are positional (overview), not kwargs, so this
        # comparison is clean.
        assert viz_kwargs == hijack_kwargs, (
            f"visualize and _mockprovider passed different "
            f"primitives to the shared helper:\n"
            f"  visualize: {viz_kwargs}\n"
            f"  hijack:    {hijack_kwargs}"
        )
