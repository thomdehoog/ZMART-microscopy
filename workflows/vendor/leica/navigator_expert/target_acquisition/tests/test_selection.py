"""Tests for pipeline/selection.py: select_targets, SelectionResult,
load_overview_result re-homing, LimitsContext-typed filter signature.

Display tests (display_selection) and example-crops are covered in
test_visualize.py; this file is unit-level.
"""
from __future__ import annotations

import numpy as np
import pytest

from pipeline.context import LimitsContext
from pipeline.overview import (
    OverviewResult, Pick, _filter_out_of_limits,
)
from pipeline.selection import (
    MODE_EMPTY, MODE_NO_QUALIFYING, MODE_SPARSE, MODE_THRESHOLD,
    SelectionResult, load_overview_result, select_targets,
)


def _make_pick(rid="0", row=0, col=0, label=1, *,
               area=100, intensity=50.0, x_um=10.0, y_um=20.0) -> Pick:
    return Pick(
        pick_id=(rid, row, col, label),
        tile_stage_xy_um=(x_um, y_um),
        tile_zwide_um=0.5,
        source_pixel_size_um=(0.65, 0.65),
        source_image_size_px=(2048, 2048),
        centroid_col_row_px=(1000.0, 1000.0),
        bbox_px=(990, 990, 1010, 1010),
        bbox_um=(13.0, 13.0),
        area_px=area,
        eccentricity=0.5,
        mean_intensity=intensity,
        cell_source_stage_xy_um=(x_um + 0.5 + label * 100.0, y_um + 0.5),
    )


def _edge_pick(label, bbox, *, size=(2048, 2048)) -> Pick:
    """Pick with custom bbox and (optionally) custom image size."""
    p = _make_pick(label=label, area=200, intensity=100.0)
    return Pick(
        pick_id=p.pick_id,
        tile_stage_xy_um=p.tile_stage_xy_um,
        tile_zwide_um=p.tile_zwide_um,
        source_pixel_size_um=p.source_pixel_size_um,
        source_image_size_px=size,
        centroid_col_row_px=(
            (bbox[1] + bbox[3]) / 2,
            (bbox[0] + bbox[2]) / 2,
        ),
        bbox_px=bbox,
        bbox_um=p.bbox_um,
        area_px=p.area_px,
        eccentricity=p.eccentricity,
        mean_intensity=p.mean_intensity,
        cell_source_stage_xy_um=p.cell_source_stage_xy_um,
    )


def _make_overview(*, picks: list[Pick], tile_cell_counts: dict | None = None,
                   n_planned: int = 0, n_submitted: int = 0) -> OverviewResult:
    if tile_cell_counts is None:
        tile_cell_counts = {}
        for p in picks:
            key = (p.pick_id[0], p.pick_id[1], p.pick_id[2])
            tile_cell_counts[key] = tile_cell_counts.get(key, 0) + 1
    return OverviewResult(
        all_picks=picks,
        tile_acquire_failures=[],
        engine_failures=[],
        npz_save_failures=[],
        tile_cell_counts=tile_cell_counts,
        n_tiles_planned=n_planned or len(tile_cell_counts),
        n_tiles_submitted=n_submitted or len(tile_cell_counts),
        completed=True,
    )


def _make_limits() -> LimitsContext:
    """Permissive limits: nothing falls out by XY/Z."""
    return LimitsContext(
        calibration={},          # unused once drv is patched
        stage_config={"limits_um": {"z_wide": (-1e6, 1e6)}},
        boundary_limits=None,    # no XY box -> all picks survive
        source_slot=1,
        target_slot=1,            # identity translation
    )


@pytest.fixture(autouse=True)
def _patch_translate(monkeypatch):
    """Patch calib.translate_xyz_between_objectives to an identity function
    so the filter exercises only the limits-checking branches, not the
    driver-internal calibration math.

    Patched at the import site (pipeline.overview) because that's where
    _filter_out_of_limits looks it up via `calib.translate_xyz_between_objectives`.
    """
    monkeypatch.setattr(
        "pipeline.overview.calib.translate_xyz_between_objectives",
        lambda x, y, z, calibration, *, from_slot, to_slot: (x, y, z),
    )


# ─── TestSelectTargets ─────────────────────────────────────────────


class TestSelectTargets:
    def test_global_mode_threshold_when_qualifying_cells_exist(self):
        # 12 cells, all above median area & intensity get selected
        picks = [_make_pick(label=i, area=100 + i * 10, intensity=50.0 + i)
                 for i in range(1, 13)]
        ov = _make_overview(picks=picks)
        _, sel = select_targets(ov, _make_limits(), n_per_tile=4, seed=42)

        assert sel.mode == MODE_THRESHOLD
        assert sel.n_total == 12
        assert sel.n_qualifying > 0   # median split -> roughly half qualify
        assert sel.area_threshold_auto is True
        assert sel.intensity_threshold_auto is True

    def test_global_mode_empty_when_zero_cells(self):
        ov = _make_overview(picks=[], tile_cell_counts={("0", 0, 0): 0})
        _, sel = select_targets(ov, _make_limits())

        assert sel.mode == MODE_EMPTY
        assert sel.n_total == 0
        assert sel.n_final == 0
        assert sel.selected_picks == []

    def test_global_mode_sparse_when_below_cutoff(self):
        # 5 cells globally with min_cells_for_threshold=10 -> SPARSE
        picks = [_make_pick(label=i, area=100, intensity=50.0)
                 for i in range(1, 6)]
        ov = _make_overview(picks=picks)
        _, sel = select_targets(
            ov, _make_limits(), n_per_tile=4, min_cells_for_threshold=10,
        )

        assert sel.mode == MODE_SPARSE
        # In sparse mode, all cells qualify (no threshold applied)
        assert sel.n_qualifying == 5

    def test_global_mode_no_qualifying_returns_zero_picks_no_fallback(self):
        # 15 cells, threshold override puts everyone below -> NO_QUALIFYING
        picks = [_make_pick(label=i, area=100, intensity=50.0)
                 for i in range(1, 16)]
        ov = _make_overview(picks=picks)
        result_picks, sel = select_targets(
            ov, _make_limits(),
            area_threshold=999999, intensity_threshold=999999,
        )

        assert sel.mode == MODE_NO_QUALIFYING
        assert sel.n_qualifying == 0
        assert sel.n_final == 0
        assert result_picks.items == []   # NO random fallback

    def test_override_one_threshold_sets_auto_flag_per_axis(self):
        picks = [_make_pick(label=i, area=100 + i, intensity=50.0 + i)
                 for i in range(1, 13)]
        ov = _make_overview(picks=picks)
        _, sel = select_targets(
            ov, _make_limits(),
            area_threshold=105,   # override
            # intensity_threshold left None -> auto
        )

        assert sel.area_threshold_auto is False
        assert sel.area_threshold == 105.0
        assert sel.intensity_threshold_auto is True

    def test_seed_zero_does_not_collide_with_auto(self):
        # seed=0 must produce reproducible-but-distinct seed material from
        # the seed=None ("auto") case
        picks = [_make_pick(label=i, area=200, intensity=100.0)
                 for i in range(1, 13)]
        ov = _make_overview(picks=picks)
        _, sel_zero = select_targets(ov, _make_limits(), seed=0)
        _, sel_auto = select_targets(ov, _make_limits(), seed=None)

        assert "seed=0" in sel_zero.seed_material
        assert "seed=auto" in sel_auto.seed_material
        assert sel_zero.seed_material != sel_auto.seed_material

    def test_per_stage_counts_sum_correctly(self):
        picks = [_make_pick(label=i, area=200, intensity=100.0)
                 for i in range(1, 13)]
        ov = _make_overview(picks=picks)
        _, sel = select_targets(ov, _make_limits(), n_per_tile=4, seed=1)

        # n_final + removed should equal n_selected_pre_dedup
        total_removed = (
            sel.n_removed_duplicate
            + sel.n_removed_out_of_limits_xy
            + sel.n_removed_out_of_limits_z
            + sel.n_removed_translation
        )
        assert sel.n_final + total_removed == sel.n_selected_pre_dedup
        assert sel.n_selected_pre_dedup <= sel.n_qualifying

    def test_selected_pick_ids_use_full_pick_id_tuple(self):
        picks = [_make_pick(rid="2", row=3, col=4, label=i,
                            area=200, intensity=100.0)
                 for i in range(1, 13)]
        ov = _make_overview(picks=picks)
        _, sel = select_targets(ov, _make_limits(), seed=1)

        for pid in sel.selected_pick_ids:
            assert len(pid) == 4
            assert pid[0] == "2"
            assert pid[1] == 3
            assert pid[2] == 4


# ─── Border-margin filter ─────────────────────────────────────────


class TestBorderMarginFilter:
    def _edge_pick(self, label, bbox):
        return _edge_pick(label, bbox)

    def test_cells_touching_top_edge_excluded(self):
        picks = (
            [self._edge_pick(i, (10, 500, 30, 520)) for i in range(1, 6)]
            + [self._edge_pick(i, (500, 500, 520, 520)) for i in range(6, 16)]
        )
        ov = _make_overview(picks=picks)
        _, sel = select_targets(ov, _make_limits(), border_margin_px=64)
        assert sel.n_near_border == 5
        assert sel.near_border_mask[:5].all()
        assert not sel.near_border_mask[5:].any()
        # Excluded from qualifying
        assert not (sel.qualifying_mask & sel.near_border_mask).any()

    def test_zero_margin_is_allowed_and_disables_filter(self):
        """Regression: border_margin_px == 0 is the explicit disable path.
        It must NOT raise (despite the negative-margin guard) and must
        produce zero near-border cells even when picks are at the tile
        edge. Prevents a future 'tightening' from breaking the disable
        path.
        """
        picks = (
            [self._edge_pick(i, (10, 500, 30, 520)) for i in range(1, 6)]
            + [self._edge_pick(i, (500, 500, 520, 520)) for i in range(6, 16)]
        )
        ov = _make_overview(picks=picks)
        # Must not raise: 0 is the documented disable sentinel.
        _, sel = select_targets(ov, _make_limits(), border_margin_px=0)
        assert sel.n_near_border == 0
        assert not sel.near_border_mask.any()
        assert sel.border_margin_px == 0

    def test_cells_touching_right_edge_excluded(self):
        picks = (
            # near right edge
            [self._edge_pick(i, (500, 2030, 520, 2048)) for i in range(1, 4)]
            + [self._edge_pick(i, (500, 500, 520, 520)) for i in range(4, 15)]
        )
        ov = _make_overview(picks=picks)
        _, sel = select_targets(ov, _make_limits(), border_margin_px=64)
        assert sel.n_near_border == 3
        assert sel.near_border_mask[:3].all()

    def test_boundary_equality_at_x1_equals_width_minus_margin_kept(self):
        """skimage bbox is half-open [min, max). At x1 == width - margin
        the pick is KEPT; at x1 == width - margin + 1 it flips to
        near-border. Pins the off-by-one semantics.
        """
        # width=2048, margin=64 -> threshold at x1=1984.
        # 12 picks total to keep the threshold-mode path active.
        boundary = self._edge_pick(1, (500, 500, 520, 1984))   # x1 == 1984
        one_past = self._edge_pick(2, (500, 500, 520, 1985))   # x1 == 1985
        middles = [self._edge_pick(i, (500, 500, 520, 520))
                   for i in range(3, 13)]
        ov = _make_overview(picks=[boundary, one_past, *middles])
        _, sel = select_targets(ov, _make_limits(), border_margin_px=64)

        assert not sel.near_border_mask[0]    # boundary kept
        assert sel.near_border_mask[1]        # one-past excluded
        assert not sel.near_border_mask[2:].any()
        assert sel.n_near_border == 1


# ─── Input validation ─────────────────────────────────────────────


class TestInputValidation:
    def test_negative_margin_raises_value_error(self):
        """Negative border_margin_px is rejected at the function boundary;
        zero is the explicit disable sentinel, so the predicate is < 0.
        """
        picks = [_make_pick(label=i, area=200, intensity=100.0)
                 for i in range(1, 5)]
        ov = _make_overview(picks=picks)
        with pytest.raises(ValueError, match=r"border_margin_px must be >= 0"):
            select_targets(ov, _make_limits(), border_margin_px=-1)

    def test_degenerate_image_size_raises_value_error_per_axis(self):
        """All three degenerate variants (0,H), (W,0), (0,0) trip the
        same predicate (width <= 0 or height <= 0) in
        _compute_near_border_mask and fail-fast with pick_id in the
        message. (border_margin_px > 0 so the validator is actually run.)
        """
        for bad_size in [(0, 2048), (2048, 0), (0, 0)]:
            bad_pick = _edge_pick(1, (5, 5, 25, 25), size=bad_size)
            ov = _make_overview(picks=[bad_pick])
            with pytest.raises(
                ValueError, match=r"invalid source_image_size_px",
            ):
                select_targets(ov, _make_limits(), border_margin_px=64)

    def test_degenerate_image_size_raises_even_when_margin_zero(self):
        """The size-validity contract is unconditional: it does not
        depend on whether the border filter is active. Regression
        against a Bundle C bug where _compute_near_border_mask short-
        circuited at border_margin_px == 0 BEFORE running the size
        check, silently accepting degenerate input when the filter
        was disabled.
        """
        bad_pick = _edge_pick(1, (5, 5, 25, 25), size=(0, 0))
        ov = _make_overview(picks=[bad_pick])
        with pytest.raises(
            ValueError, match=r"invalid source_image_size_px",
        ):
            select_targets(ov, _make_limits(), border_margin_px=0)


# ─── Eligible-population edge cases ───────────────────────────────


class TestEligibleEdgeCases:
    def test_n_eligible_below_cutoff_triggers_sparse_when_n_total_above(self):
        """Two-population regression: n_total >= min_cells_for_threshold,
        but n_eligible < min_cells_for_threshold (most picks excluded by
        the border filter). Sparse gate must use n_eligible, not n_total.
        """
        # 12 corner picks (near-border at margin=64) + 5 middle picks.
        # n_total=17 (>=10), n_eligible=5 (<10).
        corners = [_edge_pick(i, (5, 5, 25, 25)) for i in range(1, 13)]
        middles = [_edge_pick(i, (500, 500, 520, 520)) for i in range(13, 18)]
        ov = _make_overview(picks=[*corners, *middles])
        _, sel = select_targets(
            ov, _make_limits(),
            border_margin_px=64, min_cells_for_threshold=10,
        )

        assert sel.n_total == 17
        assert sel.n_near_border == 12
        assert sel.mode == MODE_SPARSE
        assert sel.n_qualifying == 5
        # Scalar finite check (file-strict JSON pinned by all-near-border test)
        import math
        assert math.isfinite(sel.area_threshold)
        assert math.isfinite(sel.intensity_threshold)

    def test_huge_margin_excludes_all_lands_in_no_qualifying(self):
        """border_margin_px larger than the tile excludes every cell, so
        n_eligible == 0 -> MODE_NO_QUALIFYING with 0.0 sentinels (no
        np.median([]) -> NaN contamination).
        """
        picks = [_make_pick(label=i, area=200, intensity=100.0)
                 for i in range(1, 16)]
        ov = _make_overview(picks=picks)
        _, sel = select_targets(ov, _make_limits(), border_margin_px=2000)

        assert sel.n_near_border == 15
        assert sel.mode == MODE_NO_QUALIFYING
        assert sel.area_threshold == 0.0
        assert sel.intensity_threshold == 0.0
        import math
        assert math.isfinite(sel.area_threshold)
        assert math.isfinite(sel.intensity_threshold)

    def test_sparse_and_border_compose_without_double_exclusion(self):
        """Sparse path + border filter compose cleanly: each non-border
        cell counts exactly once in qualifying, and qualifying_mask and
        near_border_mask are disjoint.
        """
        corners = [_edge_pick(i, (5, 5, 25, 25)) for i in range(1, 6)]
        middles = [_edge_pick(i, (500, 500, 520, 520)) for i in range(6, 9)]
        ov = _make_overview(picks=[*corners, *middles])
        _, sel = select_targets(
            ov, _make_limits(),
            border_margin_px=64, min_cells_for_threshold=10,
        )

        # 8 total, 5 near-border, 3 eligible -> sparse (3 < 10)
        assert sel.n_total == 8
        assert sel.n_near_border == 5
        assert sel.mode == MODE_SPARSE
        assert sel.n_qualifying == 3
        assert not (sel.qualifying_mask & sel.near_border_mask).any()


# ─── Per-tile sparseness + empty counters ─────────────────────────


class TestSparseAndEmptyCounters:
    def test_n_tiles_below_eligible_cutoff_counts_sparse_and_empty_tiles(self):
        """Counter uses post-border eligible counts per tile; predicate
        eligible_count < min_cells_for_threshold INCLUDES eligible == 0,
        so raw-empty tiles count too. n_tiles_empty (raw) is a separate
        counter and is NOT mutually exclusive with this one.
        """
        # Tile A: 30 picks (eligible=30); Tile B: 5 picks (eligible=5);
        # Tile C: 0 picks (eligible=0). All bbox=(990,990,1010,1010), so
        # none are near border in a 2048x2048 image -> eligible == raw.
        picks = (
            [_make_pick(rid="0", row=0, col=0, label=i, area=200, intensity=100.0)
             for i in range(1, 31)]
            + [_make_pick(rid="0", row=0, col=1, label=i, area=200, intensity=100.0)
               for i in range(1, 6)]
        )
        tile_counts = {("0", 0, 0): 30, ("0", 0, 1): 5, ("0", 0, 2): 0}
        ov = _make_overview(picks=picks, tile_cell_counts=tile_counts)

        _, sel = select_targets(
            ov, _make_limits(), n_per_tile=4, min_cells_for_threshold=10, seed=1,
        )

        assert sel.mode == MODE_THRESHOLD   # 35 cells total >= 10
        # Tile B (5 eligible < 10) AND tile C (0 eligible < 10) both count.
        assert sel.n_tiles_below_eligible_cutoff == 2
        # n_tiles_empty still tracks raw-empty only.
        assert sel.n_tiles_empty == 1


# ─── LimitsContext signature ──────────────────────────────────────


class TestFilterOutOfLimitsTakesLimitsContext:
    def test_works_with_limits_context_no_full_context_mock(self):
        """Construct LimitsContext directly; _filter_out_of_limits accepts it."""
        limits = _make_limits()
        # In the permissive setup all picks survive
        picks = [_make_pick(rid="0", row=0, col=0, label=i, area=200,
                            intensity=100.0)
                 for i in range(1, 5)]
        surviving, removed_xy, removed_z, removed_xlat = _filter_out_of_limits(
            picks, limits,
        )
        assert len(surviving) == 4
        assert removed_xy == [] and removed_z == [] and removed_xlat == []


# ─── load_overview_result import path ─────────────────────────────


class TestLoadOverviewResultFromSelectionModule:
    def test_import_path_is_selection(self):
        """load_overview_result lives in pipeline.selection, no underscore."""
        from pipeline.selection import load_overview_result as f
        assert callable(f)

    def test_load_overview_picks_is_not_importable(self):
        """The legacy name was deleted, not retained as a compat helper."""
        from pipeline import selection as sel_mod
        assert not hasattr(sel_mod, "load_overview_picks")


# ─── Kernel-restart safety (selection-only kernel) ─────────────────


class TestKernelRestartSelectionLoadsFromDisk:
    def test_selection_cell_works_without_prior_run_overview(self, tmp_path):
        """Simulate fresh kernel: write npz + meta manually, then run only
        load_overview_result + select_targets. The test does NOT import or
        call run_overview anywhere."""
        from pipeline.overview import (
            _build_npz_extra_arrays, _save_single_tile_analysis,
            _write_overview_meta,
        )

        analysis_dir = tmp_path / "overview-scan"
        analysis_dir.mkdir(parents=True)

        # Tile A: 12 picks (above threshold), Tile B: 0 cells, Tile C: 5 picks
        a_picks = [_make_pick(rid="0", row=0, col=0, label=i,
                              area=300 + i, intensity=200.0 + i)
                   for i in range(1, 13)]
        c_picks = [_make_pick(rid="0", row=0, col=2, label=i,
                              area=300, intensity=200.0)
                   for i in range(1, 6)]
        for tile_id, picks in [(("0", 0, 0), a_picks),
                               (("0", 0, 1), []),
                               (("0", 0, 2), c_picks)]:
            result = {
                "input": {
                    "tile_id": tile_id,
                    "naming_p": tile_id[2],
                    "image_path": "/fake.tiff",
                },
                "segment_tile": {
                    "image_2d": np.zeros((8, 8)),
                    "masks": np.zeros((8, 8), dtype=np.int32),
                    "n_cells": len(picks),
                },
                "pick_targets": {
                    "picks": [
                        {
                            "pick_id": list(p.pick_id),
                            "tile_stage_xy_um": list(p.tile_stage_xy_um),
                            "tile_zwide_um": p.tile_zwide_um,
                            "source_pixel_size_um": list(p.source_pixel_size_um),
                            "source_image_size_px": list(p.source_image_size_px),
                            "centroid_col_row_px": list(p.centroid_col_row_px),
                            "bbox_px": list(p.bbox_px),
                            "bbox_um": list(p.bbox_um),
                            "area_px": p.area_px,
                            "eccentricity": p.eccentricity,
                            "mean_intensity": p.mean_intensity,
                            "cell_source_stage_xy_um":
                                list(p.cell_source_stage_xy_um),
                        }
                        for p in picks
                    ],
                },
            }
            from pipeline.overview import _picks_from_result
            assert _save_single_tile_analysis(
                result, analysis_dir, hash6="abc123",
                acquisition_type="overview-scan",
                extra_arrays=_build_npz_extra_arrays(_picks_from_result(result)),
            )

        _write_overview_meta(
            analysis_dir,
            n_tiles_planned=3,
            n_tiles_submitted=3,
            tile_acquire_failures=[],
            engine_failures=[],
            npz_save_failures=[],
            completed=True,
        )

        # === Simulate the selection cell, no prior run_overview ===
        overview = load_overview_result(analysis_dir)
        picks, selection = select_targets(
            overview, _make_limits(),
            n_per_tile=4, min_cells_for_threshold=10, seed=42,
        )

        assert overview.completed is True
        assert overview.n_tiles == 3
        assert overview.n_tiles_empty == 1
        assert overview.tile_cell_counts == {
            ("0", 0, 0): 12, ("0", 0, 1): 0, ("0", 0, 2): 5,
        }
        # 12 + 5 = 17 cells, >= 10, so MODE_THRESHOLD
        assert selection.mode == MODE_THRESHOLD
        # Tile B (0 eligible < 10) AND tile C (5 eligible < 10) both count.
        assert selection.n_tiles_below_eligible_cutoff == 2
        assert selection.n_tiles_empty == 1
        assert selection.n_final > 0   # selection produced picks
