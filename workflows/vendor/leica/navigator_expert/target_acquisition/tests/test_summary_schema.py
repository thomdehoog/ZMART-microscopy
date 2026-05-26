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

from workflow.context import LimitsContext
from workflow.overview import OverviewResult, Pick, Picks
from workflow.selection import (
    MODE_NO_QUALIFYING, MODE_THRESHOLD, SelectionResult, select_targets,
)
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
    # Plan 2: n_tiles_acquired is a stored counter now (was derived
    # `submitted - acquire_failed`). On a non-simulate run with no
    # hijack-failure path, acquired = submitted + acquire_failed = the
    # number of tiles where acquire_and_save returned. With 1
    # acquire_failure and 2 submitted, that's 2 (acquire_failed tiles
    # don't reach the n_tiles_acquired += 1 line). The legacy value 1
    # under the derived rule is preserved here for back-compat.
    return OverviewResult(
        all_picks=[],
        tile_acquire_failures=[{"tile_id": ["0", 0, 0], "error": "boom"}],
        engine_failures=[],
        npz_save_failures=[],
        tile_cell_counts={("0", 0, 0): 12, ("0", 0, 1): 0},
        n_tiles_planned=3,
        n_tiles_submitted=2,
        n_tiles_acquired=1,
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
        near_border_mask=np.array([False, False]),
        area_threshold=150.0,
        intensity_threshold=62.5,
        area_threshold_auto=True,
        intensity_threshold_auto=True,
        border_margin_px=64,
        seed_material="seed=auto",
        mode=MODE_THRESHOLD,
        n_total=12,
        n_near_border=0,
        n_qualifying=6,
        n_selected_pre_dedup=4,
        n_removed_duplicate=0,
        n_removed_out_of_limits_xy=0,
        n_removed_out_of_limits_z=0,
        n_removed_translation=0,
        n_final=4,
        n_tiles_below_eligible_cutoff=0,
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

    def test_eligible_cutoff_key_is_serialized(self, tmp_path):
        """The schema rename from n_tiles_below_sparse_cutoff to
        n_tiles_below_eligible_cutoff is load-bearing: downstream readers
        index this key directly. Pin both the new name's presence and the
        old name's absence so a future refactor cannot silently revert.
        """
        ctx = _build_ctx_like(tmp_path)
        write_summary(
            ctx, _make_focus_map(),
            _make_overview_result(), _make_picks(), _make_selection(),
            records=[],
        )
        summary = json.loads((tmp_path / "run_summary.json").read_text())

        selection = summary["selection"]
        assert "n_tiles_below_eligible_cutoff" in selection
        assert selection["n_tiles_below_eligible_cutoff"] == 0
        assert "n_tiles_below_sparse_cutoff" not in selection

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


# ─── JSON strictness (Bundle C / task C1+C4) ──────────────────────


class TestSelectionJsonStrictness:
    def test_all_near_border_produces_json_strict_safe_thresholds(
        self, tmp_path, monkeypatch,
    ):
        """All cells near-border -> n_eligible == 0 -> MODE_NO_QUALIFYING
        with 0.0 sentinel thresholds. Drive the full write_summary path
        and strict-parse the on-disk JSON with parse_constant set to
        raise on NaN/Infinity/-Infinity tokens.

        Before C1's empty-eligible guard, the threshold branch computed
        np.median([]) -> NaN, which Python's json.dumps emits as the
        literal token "NaN" (non-RFC-compliant). This test pins the
        on-disk artifact's RFC-strictness end-to-end.
        """
        # Identity translation so picks survive the limits filter.
        monkeypatch.setattr(
            "workflow.overview.drv.translate_xyz_between_objectives",
            lambda x, y, z, calibration, *, from_slot, to_slot: (x, y, z),
        )

        # 12 picks all at top-left corner (within margin=64 of two edges)
        # in a 2048x2048 image -> all near-border.
        picks = [
            Pick(
                pick_id=("0", 0, 0, i),
                tile_stage_xy_um=(0.0, 0.0),
                tile_zwide_um=0.5,
                source_pixel_size_um=(0.65, 0.65),
                source_image_size_px=(2048, 2048),
                centroid_col_row_px=(15.0, 15.0),
                bbox_px=(5, 5, 25, 25),
                bbox_um=(13.0, 13.0),
                area_px=200,
                eccentricity=0.5,
                mean_intensity=100.0,
                cell_source_stage_xy_um=(0.5 + i * 100.0, 0.5),
            )
            for i in range(1, 13)
        ]
        overview = OverviewResult(
            all_picks=picks,
            tile_acquire_failures=[],
            engine_failures=[],
            npz_save_failures=[],
            tile_cell_counts={("0", 0, 0): 12},
            n_tiles_planned=1,
            n_tiles_submitted=1,
            completed=True,
        )
        limits = LimitsContext(
            calibration={},
            stage_config={"limits_um": {"z_wide": (-1e6, 1e6)}},
            boundary_limits=None,
            source_slot=1,
            target_slot=1,
        )

        sel_picks, selection = select_targets(
            overview, limits,
            border_margin_px=64,
            min_cells_for_threshold=10,
        )

        # In-process state assertions (cheap; pin sentinel + mode).
        assert selection.mode == MODE_NO_QUALIFYING
        assert selection.n_near_border == 12
        assert selection.n_qualifying == 0
        assert selection.area_threshold == 0.0
        assert selection.intensity_threshold == 0.0

        # End-to-end: write to disk, strict-parse the on-disk artifact.
        ctx = _build_ctx_like(tmp_path)
        out_path = write_summary(
            ctx, _make_focus_map(), overview, sel_picks, selection,
            records=[],
        )

        def _reject_nonrfc(token):
            raise ValueError(
                f"non-RFC JSON token in {out_path.name}: {token!r}"
            )

        text = out_path.read_text()
        summary = json.loads(text, parse_constant=_reject_nonrfc)

        # Cross-check the selection block in the on-disk artifact.
        assert summary["selection"]["mode"] == MODE_NO_QUALIFYING
        assert summary["selection"]["area_threshold"] == 0.0
        assert summary["selection"]["intensity_threshold"] == 0.0
        assert summary["selection"]["n_near_border"] == 12
        assert summary["selection"]["n_qualifying"] == 0
