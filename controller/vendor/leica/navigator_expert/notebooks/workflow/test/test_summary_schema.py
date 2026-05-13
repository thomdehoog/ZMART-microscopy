"""Summary schema migration tests (rev7).

n_picks_* fields move from `summary["overview"]` to `summary["selection"]`.
Other top-level keys must be preserved.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import numpy as np
import pytest

from workflow.overview import OverviewResult, Picks
from workflow.selection import MODE_THRESHOLD, SelectionResult
from workflow.summary import write_summary


def _build_ctx_like(out_dir: Path, *, scan_field=None):
    cfg = mock.MagicMock()
    cfg.acquisition_job = "Overview"
    cfg.target_job = "HiRes"
    cfg.af_job = "AF Job"
    cfg.analysis_repo = Path("/fake/smart-analysis")
    cfg.experiment = "test"
    cfg.fov_bbox_margin = 1.5
    cfg.settle_after_job_switch_s = 3.0
    cfg.restore_template_after_af = True
    cfg.restore_source_at_end = True
    cfg.smoke_test_pipeline = False
    cfg.analysis_image_source = "acquired"
    cfg.limit_margin_um = 500.0
    cfg.stage_x_min_um = None
    cfg.stage_x_max_um = None
    cfg.stage_y_min_um = None
    cfg.stage_y_max_um = None
    # asdict() walks fields via __dataclass_fields__, so use a real Config
    from workflow.context import Config
    cfg = Config(
        acquisition_job="Overview",
        target_job="HiRes",
        af_job="AF Job",
        analysis_repo=Path("/fake/smart-analysis"),
        experiment="test",
    )

    ctx = mock.MagicMock()
    ctx.cfg = cfg
    ctx.out_dir = out_dir
    ctx.source_slot = 1
    ctx.target_slot = 2
    ctx.scan_field = scan_field or {
        "n_tiles": 3,
        "tile_positions": {"0": {"positions": [{"row": 0, "col": 0, "x_um": 0, "y_um": 0}]}},
    }
    ctx.source_zgalvo_um = 0.0
    ctx.source_zgalvo_warning = False
    ctx.cellpose_env_present = True
    from workflow.context import TargetState
    ctx.target_state = TargetState()
    return ctx


def _make_focus_map():
    fm = mock.MagicMock()
    fm.model = "constant"
    fm.origin_xy_um = (0.0, 0.0)
    fm.measured = [{"zwide_um": 0.0}]
    fm.coeffs = [0.0]
    fm.residuals_um = np.array([0.0])
    return fm


def _make_overview_result():
    return OverviewResult(
        all_picks=[],
        tile_acquire_failures=[{"tile_id": ["0", 0, 0], "error": "boom"}],
        engine_failures=[],
        npz_save_failures=[],
        tile_cell_counts={("0", 0, 0): 12, ("0", 0, 1): 0},
        n_tiles_planned=3,
        n_tiles_submitted=2,
        completed=True,
    )


def _make_picks():
    return Picks(
        items=[],
        n_picks_raw=12,
        n_picks_removed_duplicate=0,
        n_picks_out_of_limits_xy=0,
        n_picks_out_of_limits_z=0,
        removed_picks=[],
        tile_acquire_failures=[{"tile_id": ["0", 0, 0], "error": "boom"}],
        engine_failures=[],
    )


def _make_selection():
    return SelectionResult(
        all_cells_area=np.array([100, 200]),
        all_cells_intensity=np.array([50, 75]),
        all_cells_labels=np.array([1, 2]),
        all_cells_tile_ids=[("0", 0, 0), ("0", 0, 0)],
        qualifying_mask=np.array([False, True]),
        area_threshold=150.0,
        intensity_threshold=62.5,
        area_threshold_auto=True,
        intensity_threshold_auto=True,
        seed_material="seed=auto",
        mode=MODE_THRESHOLD,
        n_total=12,
        n_qualifying=6,
        n_selected_pre_dedup=4,
        n_removed_duplicate=0,
        n_removed_out_of_limits_xy=0,
        n_removed_out_of_limits_z=0,
        n_removed_translation=0,
        n_final=4,
        n_tiles_below_sparse_cutoff=0,
        n_tiles_empty=1,
        selected_picks=[],
    )


class TestSummarySchemaMigration:
    def test_pick_fields_moved_from_overview_to_selection(self, tmp_path):
        ctx = _build_ctx_like(tmp_path)
        write_summary(
            ctx, _make_focus_map(),
            _make_overview_result(), _make_picks(), _make_selection(),
            records=[],
        )
        summary = json.loads((tmp_path / "run_summary.json").read_text())

        # overview block no longer has n_picks_* keys
        for stale in ("n_picks_raw", "n_picks_removed_duplicate",
                      "n_picks_out_of_limits_xy", "n_picks_out_of_limits_z",
                      "n_picks_final"):
            assert stale not in summary["overview"], (
                f"{stale} should have moved to summary['selection']"
            )

        # selection block has them (or their renamed equivalents)
        assert "n_total" in summary["selection"]
        assert "n_final" in summary["selection"]
        assert summary["selection"]["n_total"] == 12
        assert summary["selection"]["n_final"] == 4

    def test_top_level_keys_preserved(self, tmp_path):
        ctx = _build_ctx_like(tmp_path)
        write_summary(
            ctx, _make_focus_map(),
            _make_overview_result(), _make_picks(), _make_selection(),
            records=[],
        )
        summary = json.loads((tmp_path / "run_summary.json").read_text())

        for expected in ("timestamp", "config", "source_slot", "target_slot",
                         "scan_field", "focus_map", "preflight", "overview",
                         "selection", "removed_picks", "target_state",
                         "picks", "targets"):
            assert expected in summary, f"top-level key {expected!r} missing"

    def test_overview_block_uses_persisted_counters_not_n_tiles(self, tmp_path):
        """summary.overview.n_tiles_acquired must come from
        OverviewResult.n_tiles_acquired (= submitted - acquire_failed),
        NOT from OverviewResult.n_tiles (= drained-and-saved)."""
        ctx = _build_ctx_like(tmp_path)
        overview = _make_overview_result()
        # overview.n_tiles (= drained+saved) is 1 (only tile (0,0,0) has count>=0
        # but the fixture has 2 entries) -- but n_tiles_acquired must be
        # n_tiles_submitted (2) - len(tile_acquire_failures) (1) = 1.
        # The test isn't about agreement; it's about NOT pulling from n_tiles.
        write_summary(
            ctx, _make_focus_map(),
            overview, _make_picks(), _make_selection(),
            records=[],
        )
        summary = json.loads((tmp_path / "run_summary.json").read_text())

        assert summary["overview"]["n_tiles_planned"] == 3
        assert summary["overview"]["n_tiles_submitted"] == 2
        assert summary["overview"]["n_tiles_acquired"] == 1   # submitted - acquire_failed
        assert summary["overview"]["n_tiles_acquire_failed"] == 1
        assert summary["overview"]["completed"] is True
