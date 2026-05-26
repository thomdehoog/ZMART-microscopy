"""Unit tests for _save_tile_analysis (overview.py).

Tests the save function in isolation — no hardware, no engine, no ctx
beyond the paths it needs.
"""
from __future__ import annotations

import numpy as np

from shared.output_layout.naming import (
    Naming,
    build_position_analysis_name,
)
from pipeline.overview import (
    TileEvent,
    _fire_on_tile,
    _save_tile_analysis,
)


def _make_buffer_entry(
    *,
    tile_id=("0", 0, 0),
    naming_p=0,
    image_2d=None,
    masks=None,
    n_cells=5,
    simulated: bool = False,
):
    """Build a single engine result dict matching the real schema.

    simulated: when True, mirrors the hijack-mode submit payload --
    the pipeline sets `simulated`/`mock_image_source` on the engine
    submission so _save_single_tile_analysis can persist them and
    _fire_on_tile can populate TileEvent. Real runs leave both off.
    """
    if image_2d is None:
        image_2d = np.random.default_rng(42).random((64, 64))
    if masks is None:
        masks = np.zeros((64, 64), dtype=np.int32)
        masks[10:20, 10:20] = 1
        masks[30:40, 30:40] = 2
    inp: dict = {
        "tile_id": tile_id,
        "naming_p": naming_p,
        "image_path": "/fake/tile.ome.tiff",
    }
    if simulated:
        inp["simulated"] = True
        inp["mock_image_source"] = "skimage_human_mitosis"
    return {
        "input": inp,
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
        # Post-cut: the writer persists `simulated` instead of the
        # dropped legacy mock-source key. Even on a non-simulate
        # entry, `simulated` is present (with False) so the loader
        # does not need to fall through to the back-compat seam on
        # post-cut NPZs. Absence of the legacy key is enforced
        # structurally by the single-trace test in
        # test_overview_persistence.py -- no need to repeat the
        # assertion here (which would itself add a string literal
        # the structural test would flag).
        assert "simulated" in data
        assert bool(data["simulated"]) is False

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

    def test_simulated_persisted_to_npz(self, tmp_path):
        # Post-cut: the hijack-mode submit payload carries
        # `simulated=True` and `mock_image_source=<provider>`. The
        # writer persists both so a reload reconstructs the (mock)
        # title prefix and downstream provenance. Replaces the
        # pre-cut `test_analysis_image_source_stored`.
        analysis_dir = tmp_path / "analysis"
        buf = [_make_buffer_entry(simulated=True)]

        _save_tile_analysis(analysis_dir, buf, hash6="abc123",
                            acquisition_type="overview-scan")

        data = np.load(list(analysis_dir.glob("*.npz"))[0], allow_pickle=True)
        assert bool(data["simulated"]) is True
        assert str(data["mock_image_source"]) == "skimage_human_mitosis"

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


class TestFireOnTile:
    def test_calls_callback_with_tile_event(self):
        # Fixture masks have labels 1 and 2 -> n_cells = 2 (masks.max()).
        # Non-simulate path: event.simulated must default to False.
        result = _make_buffer_entry(tile_id=("0", 1, 2), naming_p=0)

        received = []
        _fire_on_tile(lambda e: received.append(e), result)

        assert len(received) == 1
        event = received[0]
        assert isinstance(event, TileEvent)
        assert event.tile_id == ("0", 1, 2)
        assert event.n_cells == 2
        assert event.simulated is False

    def test_calls_callback_with_simulated_flag(self):
        # Hijack-mode path: the submit dict carries `simulated=True`,
        # and _fire_on_tile must surface it on the TileEvent so the
        # default callback prefixes the figure title with "(mock)".
        result = _make_buffer_entry(
            tile_id=("0", 1, 2), naming_p=0, simulated=True,
        )

        received = []
        _fire_on_tile(lambda e: received.append(e), result)

        assert len(received) == 1
        assert received[0].simulated is True
        assert received[0].mock_image_source == "skimage_human_mitosis"

    def test_callback_exception_does_not_propagate(self, capsys):
        result = _make_buffer_entry()

        def _boom(event):
            raise ValueError("display failed")

        _fire_on_tile(_boom, result)

        assert "on_tile callback failed" in capsys.readouterr().out

    def test_none_callback_is_noop(self):
        result = _make_buffer_entry()
        _fire_on_tile(None, result)

    def test_missing_data_skips_callback(self):
        result = {"input": {}, "segment_tile": {}, "pick_targets": {}}
        received = []
        _fire_on_tile(lambda e: received.append(e), result)
        assert len(received) == 0
