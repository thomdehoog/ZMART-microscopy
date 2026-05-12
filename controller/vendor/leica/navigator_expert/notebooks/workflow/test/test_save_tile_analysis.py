"""Unit tests for _save_tile_analysis (overview.py).

Tests the save function in isolation — no hardware, no engine, no ctx
beyond the paths it needs.
"""
from __future__ import annotations

import numpy as np

from _shared.output_layout.naming import (
    Naming,
    build_position_analysis_name,
)
from workflow.overview import (
    MODE_EMPTY,
    MODE_NO_QUALIFYING,
    MODE_SPARSE,
    MODE_THRESHOLD,
    Pick,
    TileEvent,
    _apply_threshold_and_sample,
    _fire_on_tile,
    _picks_from_result,
    _save_tile_analysis,
)


def _make_buffer_entry(
    *,
    tile_id=("0", 0, 0),
    naming_p=0,
    image_2d=None,
    masks=None,
    n_cells=5,
    analysis_image_source="acquired",
):
    """Build a single engine result dict matching the real schema."""
    if image_2d is None:
        image_2d = np.random.default_rng(42).random((64, 64))
    if masks is None:
        masks = np.zeros((64, 64), dtype=np.int32)
        masks[10:20, 10:20] = 1
        masks[30:40, 30:40] = 2
    return {
        "input": {
            "tile_id": tile_id,
            "naming_p": naming_p,
            "image_path": "/fake/tile.ome.tiff",
            "analysis_image_source": analysis_image_source,
        },
        "segment_tile": {
            "image_2d": image_2d,
            "masks": masks,
            "n_cells": n_cells,
        },
        "pick_targets": {"picks": []},
    }


class TestSaveTileAnalysis:
    def test_saves_npz_with_expected_keys(self, tmp_path):
        analysis_dir = tmp_path / "overview-scan" / "analysis"
        buf = [_make_buffer_entry(tile_id=("0", 1, 2), naming_p=3)]

        _save_tile_analysis(analysis_dir, buf, hash6="abc123",
                            acquisition_type="overview-scan")

        npz_files = list(analysis_dir.glob("*.npz"))
        assert len(npz_files) == 1

        data = np.load(npz_files[0], allow_pickle=True)
        assert "image_2d" in data
        assert "masks" in data
        assert "tile_id" in data
        assert "analysis_image_source" in data

    def test_npz_filename_matches_naming_convention(self, tmp_path):
        analysis_dir = tmp_path / "analysis"
        buf = [_make_buffer_entry(tile_id=("2", 0, 0), naming_p=7)]

        _save_tile_analysis(analysis_dir, buf, hash6="abc123",
                            acquisition_type="overview-scan")

        expected_name = build_position_analysis_name(
            Naming(acquisition_type="overview-scan", hash6="abc123", g=2, p=7)
        )
        assert (analysis_dir / expected_name).exists()

    def test_image_and_masks_round_trip(self, tmp_path):
        analysis_dir = tmp_path / "analysis"
        image = np.arange(100, dtype=np.float64).reshape(10, 10)
        masks = np.arange(100, dtype=np.int32).reshape(10, 10)
        buf = [_make_buffer_entry(image_2d=image, masks=masks)]

        _save_tile_analysis(analysis_dir, buf, hash6="abc123",
                            acquisition_type="overview-scan")

        npz_files = list(analysis_dir.glob("*.npz"))
        data = np.load(npz_files[0], allow_pickle=True)
        np.testing.assert_array_equal(data["image_2d"], image)
        np.testing.assert_array_equal(data["masks"], masks)

    def test_tile_id_stored_as_metadata(self, tmp_path):
        analysis_dir = tmp_path / "analysis"
        buf = [_make_buffer_entry(tile_id=("3", 4, 5), naming_p=0)]

        _save_tile_analysis(analysis_dir, buf, hash6="abc123",
                            acquisition_type="overview-scan")

        npz_files = list(analysis_dir.glob("*.npz"))
        data = np.load(npz_files[0], allow_pickle=True)
        assert tuple(data["tile_id"]) == ("3", "4", "5")

    def test_multiple_tiles(self, tmp_path):
        analysis_dir = tmp_path / "analysis"
        buf = [
            _make_buffer_entry(tile_id=("0", 0, 0), naming_p=0),
            _make_buffer_entry(tile_id=("0", 0, 1), naming_p=1),
            _make_buffer_entry(tile_id=("0", 1, 0), naming_p=2),
        ]

        _save_tile_analysis(analysis_dir, buf, hash6="abc123",
                            acquisition_type="overview-scan")

        assert len(list(analysis_dir.glob("*.npz"))) == 3

    def test_creates_analysis_dir(self, tmp_path):
        analysis_dir = tmp_path / "deep" / "nested" / "analysis"
        assert not analysis_dir.exists()

        buf = [_make_buffer_entry()]
        _save_tile_analysis(analysis_dir, buf, hash6="abc123",
                            acquisition_type="overview-scan")

        assert analysis_dir.exists()

    def test_skips_missing_masks(self, tmp_path):
        analysis_dir = tmp_path / "analysis"
        buf = [{
            "input": {"tile_id": ("0", 0, 0), "naming_p": 0},
            "segment_tile": {"image_2d": np.zeros((4, 4))},
            "pick_targets": {"picks": []},
        }]

        _save_tile_analysis(analysis_dir, buf, hash6="abc123",
                            acquisition_type="overview-scan")

        assert len(list(analysis_dir.glob("*.npz"))) == 0

    def test_skips_missing_image(self, tmp_path):
        analysis_dir = tmp_path / "analysis"
        buf = [{
            "input": {"tile_id": ("0", 0, 0), "naming_p": 0},
            "segment_tile": {"masks": np.zeros((4, 4), dtype=np.int32)},
            "pick_targets": {"picks": []},
        }]

        _save_tile_analysis(analysis_dir, buf, hash6="abc123",
                            acquisition_type="overview-scan")

        assert len(list(analysis_dir.glob("*.npz"))) == 0

    def test_per_tile_failure_does_not_raise(self, tmp_path):
        analysis_dir = tmp_path / "analysis"
        good = _make_buffer_entry(tile_id=("0", 0, 0), naming_p=0)
        # Bad entry: tile_id with non-int region triggers int() conversion error
        bad = _make_buffer_entry(tile_id=("not/valid", 0, 1), naming_p=1)

        _save_tile_analysis(analysis_dir, [good, bad], hash6="abc123",
                            acquisition_type="overview-scan")

        assert len(list(analysis_dir.glob("*.npz"))) == 1

    def test_empty_buffer(self, tmp_path):
        analysis_dir = tmp_path / "analysis"
        _save_tile_analysis(analysis_dir, [], hash6="abc123",
                            acquisition_type="overview-scan")
        assert not analysis_dir.exists()

    def test_analysis_image_source_stored(self, tmp_path):
        analysis_dir = tmp_path / "analysis"
        buf = [_make_buffer_entry(analysis_image_source="skimage_human_mitosis")]

        _save_tile_analysis(analysis_dir, buf, hash6="abc123",
                            acquisition_type="overview-scan")

        data = np.load(list(analysis_dir.glob("*.npz"))[0], allow_pickle=True)
        assert str(data["analysis_image_source"]) == "skimage_human_mitosis"

    def test_missing_naming_p_skips_with_warning(self, tmp_path, capsys):
        analysis_dir = tmp_path / "analysis"
        entry = _make_buffer_entry(tile_id=("0", 0, 0), naming_p=0)
        entry["input"].pop("naming_p")

        _save_tile_analysis(analysis_dir, [entry], hash6="abc123",
                            acquisition_type="overview-scan")

        assert len(list(analysis_dir.glob("*.npz"))) == 0
        assert "missing naming_p" in capsys.readouterr().out

    def test_mkdir_failure_does_not_raise(self, tmp_path):
        # Point analysis_dir at an existing file — mkdir will fail
        blocker = tmp_path / "analysis"
        blocker.write_text("not a directory")

        buf = [_make_buffer_entry()]
        _save_tile_analysis(blocker, buf, hash6="abc123",
                            acquisition_type="overview-scan")
        # No exception raised

    def test_missing_segment_data_warns(self, tmp_path, capsys):
        analysis_dir = tmp_path / "analysis"
        buf = [{
            "input": {"tile_id": ("0", 0, 0), "naming_p": 0},
            "segment_tile": {"image_2d": np.zeros((4, 4))},
            "pick_targets": {"picks": []},
        }]

        _save_tile_analysis(analysis_dir, buf, hash6="abc123",
                            acquisition_type="overview-scan")

        assert "missing masks" in capsys.readouterr().out

    def test_missing_tile_id_warns(self, tmp_path, capsys):
        analysis_dir = tmp_path / "analysis"
        buf = [{
            "input": {"naming_p": 0},
            "segment_tile": {
                "image_2d": np.zeros((4, 4)),
                "masks": np.zeros((4, 4), dtype=np.int32),
            },
            "pick_targets": {"picks": []},
        }]

        _save_tile_analysis(analysis_dir, buf, hash6="abc123",
                            acquisition_type="overview-scan")

        assert "missing tile_id" in capsys.readouterr().out


def _make_pick(label, area_px=100, mean_intensity=50.0):
    """Build a minimal Pick for threshold tests."""
    return Pick(
        pick_id=("0", 0, 0, label),
        tile_stage_xy_um=(0.0, 0.0),
        tile_zwide_um=0.0,
        source_pixel_size_um=(0.5, 0.5),
        source_image_size_px=(64, 64),
        centroid_col_row_px=(32.0, 32.0),
        bbox_px=(28, 28, 36, 36),
        bbox_um=(4.0, 4.0),
        area_px=area_px,
        eccentricity=0.3,
        mean_intensity=mean_intensity,
        cell_source_stage_xy_um=(0.0, 0.0),
    )


class TestFireOnTile:
    def test_calls_callback_with_tile_event(self):
        result = _make_buffer_entry(
            tile_id=("0", 1, 2), naming_p=0,
            analysis_image_source="acquired",
        )
        selected = [_make_pick(5), _make_pick(10)]
        all_picks = selected + [_make_pick(15)]

        received = []
        _fire_on_tile(lambda e: received.append(e), result,
                      selected, all_picks, 80.0, 40.0, MODE_THRESHOLD)

        assert len(received) == 1
        event = received[0]
        assert isinstance(event, TileEvent)
        assert event.tile_id == ("0", 1, 2)
        assert event.picked_labels == (5, 10)
        assert event.mode == MODE_THRESHOLD
        assert len(event.all_cells_area) == 3

    def test_callback_exception_does_not_propagate(self, capsys):
        result = _make_buffer_entry()

        def _boom(event):
            raise ValueError("display failed")

        _fire_on_tile(_boom, result, [], [], 0.0, 0.0, MODE_EMPTY)

        assert "on_tile callback failed" in capsys.readouterr().out

    def test_none_callback_is_noop(self):
        result = _make_buffer_entry()
        _fire_on_tile(None, result, [], [], 0.0, 0.0, MODE_EMPTY)

    def test_missing_data_skips_callback(self):
        result = {"input": {}, "segment_tile": {}, "pick_targets": {}}
        received = []
        _fire_on_tile(lambda e: received.append(e), result,
                      [], [], 0.0, 0.0, MODE_EMPTY)
        assert len(received) == 0


class TestApplyThresholdAndSample:
    def test_median_threshold_correct(self):
        picks = [_make_pick(i, area_px=i * 10, mean_intensity=float(i * 5))
                 for i in range(1, 21)]
        selected, a_thresh, i_thresh, n_qual, mode = _apply_threshold_and_sample(
            picks, n_random=4, seed_material="test",
        )
        assert a_thresh == float(np.median([p.area_px for p in picks]))
        assert i_thresh == float(np.median([p.mean_intensity for p in picks]))
        assert mode == MODE_THRESHOLD

    def test_filter_both_axes(self):
        picks = [
            _make_pick(1, area_px=200, mean_intensity=200.0),
            _make_pick(2, area_px=50, mean_intensity=200.0),
            _make_pick(3, area_px=200, mean_intensity=10.0),
            _make_pick(4, area_px=50, mean_intensity=10.0),
        ] * 3  # 12 cells to exceed min_cells_for_threshold
        selected, a_thresh, i_thresh, n_qual, mode = _apply_threshold_and_sample(
            picks, n_random=4, min_cells_for_threshold=5, seed_material="test",
        )
        for p in selected:
            assert p.area_px >= a_thresh
            assert p.mean_intensity >= i_thresh

    def test_random_sample_count(self):
        picks = [_make_pick(i, area_px=100 + i, mean_intensity=100.0 + i)
                 for i in range(20)]
        selected, _, _, _, _ = _apply_threshold_and_sample(
            picks, n_random=4, seed_material="test",
        )
        assert len(selected) <= 4

    def test_sparse_fallback_below_min_cells(self):
        picks = [_make_pick(i) for i in range(5)]
        selected, a_thresh, i_thresh, n_qual, mode = _apply_threshold_and_sample(
            picks, n_random=4, min_cells_for_threshold=10, seed_material="test",
        )
        assert mode == MODE_SPARSE
        assert a_thresh == 0.0
        assert len(selected) == 4

    def test_zero_cells_returns_empty(self):
        selected, _, _, _, mode = _apply_threshold_and_sample(
            [], seed_material="test",
        )
        assert mode == MODE_EMPTY
        assert selected == []

    def test_no_qualifying_returns_no_qualifying(self):
        picks = [
            _make_pick(1, area_px=200, mean_intensity=10.0),
            _make_pick(2, area_px=10, mean_intensity=200.0),
        ] * 6  # 12 cells, negatively correlated
        selected, a_thresh, i_thresh, n_qual, mode = _apply_threshold_and_sample(
            picks, n_random=4, min_cells_for_threshold=5, seed_material="test",
        )
        assert mode == MODE_NO_QUALIFYING
        assert n_qual == 0
        assert len(selected) > 0

    def test_seed_reproducible(self):
        picks = [_make_pick(i, area_px=100 + i, mean_intensity=50.0 + i)
                 for i in range(20)]
        s1, *_ = _apply_threshold_and_sample(picks, seed_material="abc_0_0_0")
        s2, *_ = _apply_threshold_and_sample(picks, seed_material="abc_0_0_0")
        assert [p.pick_id for p in s1] == [p.pick_id for p in s2]

    def test_seed_differs_per_tile(self):
        picks = [_make_pick(i, area_px=100 + i, mean_intensity=50.0 + i)
                 for i in range(20)]
        s1, *_ = _apply_threshold_and_sample(picks, seed_material="abc_0_0_0")
        s2, *_ = _apply_threshold_and_sample(picks, seed_material="abc_0_0_1")
        assert [p.pick_id for p in s1] != [p.pick_id for p in s2]

    def test_ge_not_gt(self):
        picks = [_make_pick(i, area_px=100, mean_intensity=50.0)
                 for i in range(20)]
        selected, a_thresh, i_thresh, n_qual, mode = _apply_threshold_and_sample(
            picks, n_random=4, min_cells_for_threshold=10, seed_material="test",
        )
        assert mode == MODE_THRESHOLD
        assert n_qual == 20


class TestPicksFromResult:
    def test_happy_path(self):
        result = _make_buffer_entry(tile_id=("0", 0, 0), naming_p=0)
        result["pick_targets"]["picks"] = [{
            "pick_id": ("0", 0, 0, 1),
            "tile_stage_xy_um": (100.0, 200.0),
            "tile_zwide_um": 50.0,
            "source_pixel_size_um": (0.5, 0.5),
            "source_image_size_px": (64, 64),
            "centroid_col_row_px": (32.0, 32.0),
            "bbox_px": (28, 28, 36, 36),
            "bbox_um": (4.0, 4.0),
            "area_px": 100,
            "eccentricity": 0.3,
            "mean_intensity": 128.0,
            "cell_source_stage_xy_um": (100.0, 200.0),
        }]

        picks = _picks_from_result(result)
        assert len(picks) == 1
        assert picks[0].pick_id == ("0", 0, 0, 1)
        assert picks[0].area_px == 100

    def test_empty_picks(self):
        result = _make_buffer_entry()
        result["pick_targets"]["picks"] = []
        assert _picks_from_result(result) == []

    def test_order_preserved(self):
        result = _make_buffer_entry()
        result["pick_targets"]["picks"] = [
            {**_full_pick_dict(label=3)},
            {**_full_pick_dict(label=1)},
            {**_full_pick_dict(label=2)},
        ]
        picks = _picks_from_result(result)
        assert [p.pick_id[3] for p in picks] == [3, 1, 2]


def _full_pick_dict(label=1):
    return {
        "pick_id": ("0", 0, 0, label),
        "tile_stage_xy_um": (0.0, 0.0),
        "tile_zwide_um": 0.0,
        "source_pixel_size_um": (0.5, 0.5),
        "source_image_size_px": (64, 64),
        "centroid_col_row_px": (32.0, 32.0),
        "bbox_px": (28, 28, 36, 36),
        "bbox_um": (4.0, 4.0),
        "area_px": 100,
        "eccentricity": 0.3,
        "mean_intensity": 50.0,
        "cell_source_stage_xy_um": (0.0, 0.0),
    }
