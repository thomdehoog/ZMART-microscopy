"""Tests for the rev7 NPZ v2 schema + overview_meta.json + load_overview_result.

These tests exercise the persistence layer in isolation -- no hardware,
no full run_overview. The same-kernel == load_overview_result invariant
is enforced at the building-block level here; the end-to-end check lives
in smoke_visualization.py.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import numpy as np
import pytest

from workflow.overview import (
    OverviewResult,
    Pick,
    Picks,
    _build_npz_extra_arrays,
    _picks_from_result,
    _save_single_tile_analysis,
    _write_overview_meta,
    load_overview_result,
    run_overview_with_picks,
)


def _make_pick(
    rid="0", row=0, col=0, label=1,
    *,
    area=42, intensity=100.0, x_um=10.0, y_um=20.0,
) -> Pick:
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
        cell_source_stage_xy_um=(x_um + 0.5, y_um + 0.5),
    )


def _make_result(
    *,
    tile_id=("0", 0, 0),
    naming_p=0,
    picks=None,
    image_2d=None,
    masks=None,
):
    if image_2d is None:
        image_2d = np.zeros((16, 16), dtype=np.float64)
    if masks is None:
        masks = np.zeros((16, 16), dtype=np.int32)
    return {
        "input": {
            "tile_id": tile_id,
            "naming_p": naming_p,
            "image_path": "/fake.tiff",
            "analysis_image_source": "acquired",
        },
        "segment_tile": {
            "image_2d": image_2d,
            "masks": masks,
            "n_cells": len(picks) if picks else 0,
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
                    "cell_source_stage_xy_um": list(p.cell_source_stage_xy_um),
                }
                for p in (picks or [])
            ],
        },
    }


def _save_tile_with_picks(
    analysis_dir: Path,
    result: dict,
    *,
    hash6: str = "abc123",
) -> bool:
    """Save a tile through _save_single_tile_analysis with extra_arrays."""
    analysis_dir.mkdir(parents=True, exist_ok=True)
    tile_picks = _picks_from_result(result)
    return _save_single_tile_analysis(
        result, analysis_dir,
        hash6=hash6,
        acquisition_type="overview-scan",
        extra_arrays=_build_npz_extra_arrays(tile_picks),
    )


# ─── NPZ schema v2 round-trip ──────────────────────────────────────


class TestPicksRoundtripThroughNPZ:
    def test_shapes_and_values_round_trip(self, tmp_path):
        analysis_dir = tmp_path / "analysis"
        picks = [
            _make_pick(label=1, area=100, intensity=50.0, x_um=10, y_um=20),
            _make_pick(label=2, area=200, intensity=75.0, x_um=11, y_um=21),
            _make_pick(label=3, area=300, intensity=99.0, x_um=12, y_um=22),
        ]
        result = _make_result(tile_id=("0", 0, 0), naming_p=0, picks=picks)
        assert _save_tile_with_picks(analysis_dir, result)

        npz = list(analysis_dir.glob("*.npz"))[0]
        with np.load(npz, allow_pickle=True) as data:
            assert int(data["schema_version"]) == 2
            n = 3
            assert data["cell_labels"].shape == (n,)
            assert data["cell_area_px"].shape == (n,)
            assert data["cell_mean_intensity"].shape == (n,)
            assert data["pick_tile_stage_xy_um"].shape == (n, 2)
            assert data["pick_tile_zwide_um"].shape == (n,)
            assert data["pick_source_pixel_size_um"].shape == (n, 2)
            assert data["pick_source_image_size_px"].shape == (n, 2)
            assert data["pick_centroid_col_row_px"].shape == (n, 2)
            assert data["pick_bbox_px"].shape == (n, 4)
            assert data["pick_bbox_um"].shape == (n, 2)
            assert data["pick_eccentricity"].shape == (n,)
            assert data["pick_cell_source_stage_xy_um"].shape == (n, 2)

        # Full reconstruction via load_overview_result
        ov = load_overview_result(analysis_dir)
        assert len(ov.all_picks) == 3
        for orig, loaded in zip(picks, ov.all_picks):
            assert orig.pick_id == loaded.pick_id
            assert orig.tile_stage_xy_um == loaded.tile_stage_xy_um
            assert orig.bbox_px == loaded.bbox_px
            assert orig.bbox_um == loaded.bbox_um
            assert orig.area_px == loaded.area_px
            assert orig.eccentricity == pytest.approx(loaded.eccentricity)
            assert orig.mean_intensity == pytest.approx(loaded.mean_intensity)
            assert orig.cell_source_stage_xy_um == loaded.cell_source_stage_xy_um


class TestEmptyTileNPZHasCorrectShapes:
    def test_empty_tile_uses_K_shape_not_1d(self, tmp_path):
        analysis_dir = tmp_path / "analysis"
        result = _make_result(tile_id=("0", 0, 0), naming_p=0, picks=[])
        assert _save_tile_with_picks(analysis_dir, result)

        npz = list(analysis_dir.glob("*.npz"))[0]
        with np.load(npz, allow_pickle=True) as data:
            # (0, K) preserved -- not flattened to (0,)
            assert data["pick_bbox_px"].shape == (0, 4)
            assert data["pick_tile_stage_xy_um"].shape == (0, 2)
            assert data["pick_bbox_um"].shape == (0, 2)
            assert data["pick_centroid_col_row_px"].shape == (0, 2)
            assert data["pick_source_image_size_px"].shape == (0, 2)
            assert data["pick_source_pixel_size_um"].shape == (0, 2)
            assert data["pick_cell_source_stage_xy_um"].shape == (0, 2)
            assert data["cell_labels"].shape == (0,)
            assert data["cell_area_px"].shape == (0,)
            assert data["cell_mean_intensity"].shape == (0,)
            assert data["pick_tile_zwide_um"].shape == (0,)
            assert data["pick_eccentricity"].shape == (0,)

    def test_empty_tile_loader_round_trips_without_crash(self, tmp_path):
        analysis_dir = tmp_path / "analysis"
        result = _make_result(tile_id=("0", 0, 0), naming_p=0, picks=[])
        assert _save_tile_with_picks(analysis_dir, result)

        ov = load_overview_result(analysis_dir)
        assert ov.all_picks == []
        assert ov.tile_cell_counts == {("0", 0, 0): 0}
        assert ov.n_tiles == 1
        assert ov.n_tiles_empty == 1


# ─── load_overview_result ──────────────────────────────────────────


class TestLoadOverviewResultSkipsOldSchema:
    def test_v1_files_excluded_from_picks_and_tile_cell_counts(
        self, tmp_path, capsys,
    ):
        """v1 NPZs (without schema_version key) must NOT contribute to
        either the picks list or tile_cell_counts. Loader warns per file."""
        analysis_dir = tmp_path / "analysis"
        analysis_dir.mkdir(parents=True)

        # v1 NPZ -- no schema_version key
        np.savez_compressed(
            analysis_dir / "v1_tile.npz",
            image_2d=np.zeros((4, 4)),
            masks=np.zeros((4, 4), dtype=np.int32),
            tile_id=np.array(("0", "0", "0"), dtype=str),
        )

        # v2 NPZ with 1 pick
        result = _make_result(
            tile_id=("0", 1, 1), naming_p=1,
            picks=[_make_pick(rid="0", row=1, col=1, label=5)],
        )
        assert _save_tile_with_picks(analysis_dir, result)

        ov = load_overview_result(analysis_dir)

        assert len(ov.all_picks) == 1
        assert ov.all_picks[0].pick_id == ("0", 1, 1, 5)
        assert ov.tile_cell_counts == {("0", 1, 1): 1}
        assert ov.n_tiles == 1   # v1 file did NOT inflate count

        out = capsys.readouterr().out
        assert "schema v1" in out


class TestLoadOverviewResultPopulatesTileCellCounts:
    def test_three_tiles_mixed_counts_including_empty(self, tmp_path):
        analysis_dir = tmp_path / "analysis"
        # tile A: 5 picks
        a_picks = [_make_pick(rid="0", row=0, col=0, label=i) for i in range(1, 6)]
        _save_tile_with_picks(
            analysis_dir, _make_result(tile_id=("0", 0, 0), naming_p=0, picks=a_picks),
        )
        # tile B: 0 picks
        _save_tile_with_picks(
            analysis_dir, _make_result(tile_id=("0", 0, 1), naming_p=1, picks=[]),
        )
        # tile C: 12 picks
        c_picks = [_make_pick(rid="0", row=1, col=0, label=i) for i in range(1, 13)]
        _save_tile_with_picks(
            analysis_dir, _make_result(tile_id=("0", 1, 0), naming_p=2, picks=c_picks),
        )

        ov = load_overview_result(analysis_dir)

        assert ov.tile_cell_counts == {
            ("0", 0, 0): 5,
            ("0", 0, 1): 0,
            ("0", 1, 0): 12,
        }
        assert ov.n_tiles == 3
        assert ov.n_tiles_empty == 1
        assert len(ov.all_picks) == 17


# ─── overview_meta.json ────────────────────────────────────────────


class TestOverviewMetaPersistedAndLoaded:
    def test_round_trip_through_disk(self, tmp_path):
        analysis_dir = tmp_path / "analysis"
        # Use lists, not tuples: JSON round-trip collapses tuples to lists.
        # The production writer (run_overview) does `list(tile_id)` for
        # exactly this reason.
        tile_acquire_failures = [
            {"tile_id": ["0", 0, 0], "error": "stage_xy"},
            {"tile_id": ["0", 0, 1], "error": "z_clip"},
        ]
        engine_failures = [{"job_id": 7, "error": "engine_oops"}]
        npz_save_failures = [{"tile_id": ["0", 1, 1], "reason": "save_returned_false"}]

        _write_overview_meta(
            analysis_dir,
            n_tiles_planned=10,
            n_tiles_submitted=8,
            tile_acquire_failures=tile_acquire_failures,
            engine_failures=engine_failures,
            npz_save_failures=npz_save_failures,
            completed=True,
        )

        ov = load_overview_result(analysis_dir)

        assert ov.tile_acquire_failures == tile_acquire_failures
        assert ov.engine_failures == engine_failures
        assert ov.npz_save_failures == npz_save_failures
        assert ov.n_tiles_planned == 10
        assert ov.n_tiles_submitted == 8
        assert ov.completed is True


class TestOverviewMetaCorruptJsonTolerated:
    def test_truncated_json_does_not_crash_loader(self, tmp_path, capsys):
        analysis_dir = tmp_path / "analysis"
        analysis_dir.mkdir(parents=True)

        # Write a valid v2 NPZ
        result = _make_result(
            tile_id=("0", 0, 0), naming_p=0,
            picks=[_make_pick(rid="0", row=0, col=0, label=1)],
        )
        _save_tile_with_picks(analysis_dir, result)

        # Write truncated meta JSON
        (analysis_dir / "overview_meta.json").write_text('{"completed": tru')

        ov = load_overview_result(analysis_dir)
        out = capsys.readouterr().out

        # Loader warned + defaulted
        assert "unreadable" in out or "WARNING" in out
        assert ov.tile_acquire_failures == []
        assert ov.engine_failures == []
        assert ov.npz_save_failures == []
        assert ov.completed is False
        # NPZ data still loaded
        assert len(ov.all_picks) == 1
        assert ov.n_tiles == 1


class TestOverviewMetaMissingMarkedIncomplete:
    def test_missing_meta_warns_and_loads_npz_only(self, tmp_path, capsys):
        analysis_dir = tmp_path / "analysis"
        result = _make_result(
            tile_id=("0", 0, 0), naming_p=0,
            picks=[_make_pick(rid="0", row=0, col=0, label=1)],
        )
        _save_tile_with_picks(analysis_dir, result)

        # No meta file written
        ov = load_overview_result(analysis_dir)
        out = capsys.readouterr().out

        assert "no overview_meta.json" in out
        assert ov.completed is False
        assert len(ov.all_picks) == 1


class TestOverviewMetaPersistsAcquireLoopCounters:
    def test_planned_and_submitted_round_trip(self, tmp_path):
        analysis_dir = tmp_path / "analysis"
        _write_overview_meta(
            analysis_dir,
            n_tiles_planned=10,
            n_tiles_submitted=8,
            tile_acquire_failures=[{"tile_id": ("0", 0, 0), "error": "x"}],
            engine_failures=[{"job_id": 1, "error": "y"}],
            npz_save_failures=[],
            completed=True,
        )

        ov = load_overview_result(analysis_dir)

        assert ov.n_tiles_planned == 10
        assert ov.n_tiles_submitted == 8
        assert ov.n_tiles_acquired == 7   # 8 submitted - 1 acquire_failed


# ─── run_overview_with_picks compat wrapper ────────────────────────


class TestRunOverviewWithPicksWrapperPopulatesAllPicksFields:
    """The wrapper consumes OverviewResult and must produce a Picks that
    populates every legacy field downstream callers rely on."""

    def test_all_picks_fields_populated_from_overview_result(self, monkeypatch):
        # Build an OverviewResult with 3 picks across 2 tiles
        picks_a = [_make_pick(rid="0", row=0, col=0, label=i,
                              area=100 + i, x_um=10.0 + i, y_um=20.0)
                   for i in range(1, 3)]
        picks_b = [_make_pick(rid="0", row=0, col=1, label=1,
                              area=500, x_um=50.0, y_um=20.0)]
        fake_overview = OverviewResult(
            all_picks=picks_a + picks_b,
            tile_acquire_failures=[{"tile_id": ("0", 0, 2), "error": "x"}],
            engine_failures=[{"job_id": 5, "error": "boom"}],
            npz_save_failures=[],
            tile_cell_counts={("0", 0, 0): 2, ("0", 0, 1): 1},
            n_tiles_planned=3,
            n_tiles_submitted=2,
            completed=True,
        )

        # Stub out run_overview and the dedup/filter helpers (the wrapper
        # under test is the orchestration; correctness of the helpers is
        # tested elsewhere)
        monkeypatch.setattr(
            "workflow.overview.run_overview",
            lambda *a, **k: fake_overview,
        )
        monkeypatch.setattr(
            "workflow.overview._dedup_picks",
            lambda picks: (picks, []),
        )
        monkeypatch.setattr(
            "workflow.overview._filter_out_of_limits",
            lambda picks, ctx: (picks, [], [], []),
        )
        # Suppress the intermediate-state print path by keeping <50 picks

        result = run_overview_with_picks(ctx=mock.MagicMock(), focus_map=mock.MagicMock())

        assert isinstance(result, Picks)
        assert len(result.items) == 3
        assert result.n_picks_raw == 3
        assert result.n_picks_removed_duplicate == 0
        assert result.n_picks_out_of_limits_xy == 0
        assert result.n_picks_out_of_limits_z == 0
        assert result.removed_picks == []
        assert result.tile_acquire_failures == fake_overview.tile_acquire_failures
        assert result.engine_failures == fake_overview.engine_failures

    def test_wrapper_returns_overview_result_attribute_chain(self, monkeypatch):
        """Sanity: confirm `run_overview` is called and its result drives the wrapper."""
        marker = OverviewResult(
            all_picks=[], tile_acquire_failures=[],
            engine_failures=[], npz_save_failures=[],
            tile_cell_counts={}, n_tiles_planned=0,
            n_tiles_submitted=0, completed=True,
        )
        called = {}

        def _fake_run_overview(ctx, focus_map, *, on_tile=None):
            called["ran"] = True
            return marker

        monkeypatch.setattr("workflow.overview.run_overview", _fake_run_overview)
        monkeypatch.setattr(
            "workflow.overview._dedup_picks",
            lambda picks: (picks, []),
        )
        monkeypatch.setattr(
            "workflow.overview._filter_out_of_limits",
            lambda picks, ctx: (picks, [], [], []),
        )

        result = run_overview_with_picks(ctx=mock.MagicMock(), focus_map=mock.MagicMock())

        assert called["ran"] is True
        assert isinstance(result, Picks)
        assert result.items == []
