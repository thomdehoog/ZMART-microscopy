"""Unit tests for visualize.py — overview triptych and target pairs.

All tests use synthetic npz files and mock images on disk.
No hardware, no engine, no ctx.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from _shared.output_layout.naming import Naming, build_position_analysis_name


# ─── Fixtures ────────────────────────────────────────────────────


def _make_npz(
    analysis_dir: Path,
    *,
    naming: Naming,
    n_cells: int = 5,
    image_size: tuple[int, int] = (64, 64),
    tile_id: tuple = ("0", 0, 0),
    analysis_image_source: str = "acquired",
) -> Path:
    """Write a synthetic tile analysis npz matching the real schema."""
    analysis_dir.mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(42)
    image_2d = rng.random(image_size)
    masks = np.zeros(image_size, dtype=np.int32)
    cell_size = 8
    for label in range(1, n_cells + 1):
        r = (label * 10) % (image_size[0] - cell_size)
        c = (label * 12) % (image_size[1] - cell_size)
        masks[r:r + cell_size, c:c + cell_size] = label

    dest = analysis_dir / build_position_analysis_name(naming)
    np.savez_compressed(
        dest,
        image_2d=image_2d,
        masks=masks,
        tile_id=np.array(tile_id, dtype=str),
        analysis_image_source=np.array(analysis_image_source),
    )
    return dest


def _make_pick(tile_id, label, centroid_rc=(15.0, 15.0), bbox=(10, 10, 20, 20)):
    """Build a minimal Pick-like object with the fields visualize.py needs."""
    from workflow.overview import Pick
    return Pick(
        pick_id=(str(tile_id[0]), int(tile_id[1]), int(tile_id[2]), label),
        tile_stage_xy_um=(1000.0, 2000.0),
        tile_zwide_um=100.0,
        source_pixel_size_um=(0.5, 0.5),
        source_image_size_px=(64, 64),
        centroid_col_row_px=centroid_rc,
        bbox_px=bbox,
        bbox_um=(5.0, 5.0),
        area_px=100,
        eccentricity=0.3,
        mean_intensity=128.0,
        cell_source_stage_xy_um=(1005.0, 2005.0),
    )


def _make_picks(items, **kwargs):
    """Build a Picks container from a list of Pick objects."""
    from workflow.overview import Picks
    return Picks(items=items, n_picks_raw=len(items), **kwargs)


def _make_target_tif(path: Path, size=(32, 32)):
    """Write a synthetic target TIFF."""
    import tifffile
    path.parent.mkdir(parents=True, exist_ok=True)
    image = np.random.default_rng(99).integers(0, 255, size, dtype=np.uint16)
    tifffile.imwrite(str(path), image)
    return path


# ─── plot_overview_tiles ─────────────────────────────────────────


class TestPlotOverviewTiles:
    def test_renders_triptych_for_each_tile(self, tmp_path):
        import matplotlib
        matplotlib.use("Agg")
        from workflow.visualize import plot_overview_tiles

        analysis_dir = tmp_path / "analysis"
        n0 = Naming(acquisition_type="overview-scan", hash6="abc123", g=0, p=0)
        n1 = Naming(acquisition_type="overview-scan", hash6="abc123", g=0, p=1)
        _make_npz(analysis_dir, naming=n0, tile_id=("0", 0, 0))
        _make_npz(analysis_dir, naming=n1, tile_id=("0", 0, 1))

        picks = _make_picks([
            _make_pick(("0", 0, 0), label=1),
            _make_pick(("0", 0, 1), label=2),
        ])

        feedback_dir = tmp_path / "feedback"
        plot_overview_tiles(analysis_dir, picks, feedback_dir=feedback_dir)

        pngs = list(feedback_dir.glob("*.png"))
        assert len(pngs) == 2

    def test_zero_pick_tile_renders(self, tmp_path):
        import matplotlib
        matplotlib.use("Agg")
        from workflow.visualize import plot_overview_tiles

        analysis_dir = tmp_path / "analysis"
        naming = Naming(acquisition_type="overview-scan", hash6="abc123", g=0, p=0)
        _make_npz(analysis_dir, naming=naming, tile_id=("0", 0, 0))

        picks = _make_picks([])
        feedback_dir = tmp_path / "feedback"
        plot_overview_tiles(analysis_dir, picks, feedback_dir=feedback_dir)

        assert len(list(feedback_dir.glob("*.png"))) == 1

    def test_missing_npz_skipped(self, tmp_path):
        import matplotlib
        matplotlib.use("Agg")
        from workflow.visualize import plot_overview_tiles

        analysis_dir = tmp_path / "analysis"
        analysis_dir.mkdir(parents=True)

        picks = _make_picks([])
        plot_overview_tiles(analysis_dir, picks)
        # No error, no output

    def test_mock_mode_title_contains_mock(self, tmp_path, monkeypatch):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from workflow.visualize import plot_overview_tiles

        analysis_dir = tmp_path / "analysis"
        naming = Naming(acquisition_type="overview-scan", hash6="abc123", g=0, p=0)
        _make_npz(analysis_dir, naming=naming, tile_id=("0", 0, 0),
                  analysis_image_source="skimage_human_mitosis")

        captured_titles = []
        _orig_close = plt.close
        def _spy_close(fig):
            if hasattr(fig, '_suptitle') and fig._suptitle is not None:
                captured_titles.append(fig._suptitle.get_text())
            _orig_close(fig)
        monkeypatch.setattr(plt, "close", _spy_close)

        picks = _make_picks([])
        plot_overview_tiles(analysis_dir, picks)

        assert len(captured_titles) == 1
        assert "mock" in captured_titles[0].lower()

    def test_creates_feedback_dir(self, tmp_path):
        import matplotlib
        matplotlib.use("Agg")
        from workflow.visualize import plot_overview_tiles

        analysis_dir = tmp_path / "analysis"
        naming = Naming(acquisition_type="overview-scan", hash6="abc123", g=0, p=0)
        _make_npz(analysis_dir, naming=naming, tile_id=("0", 0, 0))

        feedback_dir = tmp_path / "deep" / "nested" / "feedback"
        assert not feedback_dir.exists()

        plot_overview_tiles(analysis_dir, _make_picks([]),
                           feedback_dir=feedback_dir)
        assert feedback_dir.exists()

    def test_picked_labels_from_pick_id(self, tmp_path):
        """Verify that pick_id[3] is used as the label for the red overlay."""
        import matplotlib
        matplotlib.use("Agg")
        from workflow.visualize import _picked_overlay

        image_2d = np.zeros((64, 64), dtype=np.float64)
        masks = np.zeros((64, 64), dtype=np.int32)
        masks[10:20, 10:20] = 3
        masks[30:40, 30:40] = 7

        import matplotlib.pyplot as plt
        fig, ax = plt.subplots()
        _picked_overlay(ax, image_2d, masks, [3])

        # Check that only label 3 region is overlaid
        images = ax.get_images()
        overlay = images[-1].get_array()
        # Red channel should be nonzero in label-3 region
        assert overlay[15, 15, 0] > 0   # label 3 area
        assert overlay[35, 35, 0] == 0  # label 7 area (not picked)
        plt.close("all")

    def test_picked_overlay_rendered_end_to_end(self, tmp_path, monkeypatch):
        """Integration: picks with (str, int, int) tile_key match all-str npz tile_id."""
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from workflow.visualize import plot_overview_tiles

        analysis_dir = tmp_path / "analysis"
        naming = Naming(acquisition_type="overview-scan", hash6="abc123", g=0, p=0)
        _make_npz(analysis_dir, naming=naming, n_cells=3,
                  tile_id=("0", 0, 0), image_size=(64, 64))

        # pick_id is (str, int, int, int) — mixed types, must still match
        pick = _make_pick(("0", 0, 0), label=1)
        picks = _make_picks([pick])

        captured = []
        _orig_close = plt.close
        def _spy(fig):
            ax_right = fig.axes[2]
            images = ax_right.get_images()
            if len(images) >= 2:
                overlay = images[-1].get_array()
                captured.append(overlay[:, :, 0].sum())
            _orig_close(fig)
        monkeypatch.setattr(plt, "close", _spy)

        plot_overview_tiles(analysis_dir, picks)

        assert len(captured) == 1
        assert captured[0] > 0, "Red overlay should have nonzero pixels for picked cell"


# ─── plot_target_pairs ───────────────────────────────────────────


class TestPlotTargetPairs:
    def test_renders_pairs_for_successful_targets(self, tmp_path):
        import matplotlib
        matplotlib.use("Agg")
        from workflow.visualize import plot_target_pairs
        from workflow.target import TargetRecord

        analysis_dir = tmp_path / "analysis"
        naming = Naming(acquisition_type="overview-scan", hash6="abc123", g=0, p=0)
        _make_npz(analysis_dir, naming=naming, tile_id=("0", 0, 0))

        pick = _make_pick(("0", 0, 0), label=1, bbox=(10, 10, 20, 20))
        picks = _make_picks([pick])

        target_tif = _make_target_tif(tmp_path / "target" / "target.tif")
        records = [TargetRecord(
            pick_id=("0", 0, 0, 1),
            cell_source_stage_xy_um=(1005.0, 2005.0),
            source_zwide_um=100.0,
            target_stage_xy_um=(2000.0, 3000.0),
            target_zwide_um=100.0,
            target_zoom=None,
            target_pixel_size_um=0.1,
            tif_path=target_tif,
            success=True,
            error=None,
        )]

        feedback_dir = tmp_path / "feedback"
        plot_target_pairs(analysis_dir, picks, records,
                          feedback_dir=feedback_dir)

        assert len(list(feedback_dir.glob("*.png"))) == 1

    def test_skips_failed_targets(self, tmp_path):
        import matplotlib
        matplotlib.use("Agg")
        from workflow.visualize import plot_target_pairs
        from workflow.target import TargetRecord

        analysis_dir = tmp_path / "analysis"
        naming = Naming(acquisition_type="overview-scan", hash6="abc123", g=0, p=0)
        _make_npz(analysis_dir, naming=naming, tile_id=("0", 0, 0))

        pick = _make_pick(("0", 0, 0), label=1)
        picks = _make_picks([pick])

        records = [TargetRecord(
            pick_id=("0", 0, 0, 1),
            cell_source_stage_xy_um=(1005.0, 2005.0),
            source_zwide_um=100.0,
            target_stage_xy_um=None,
            target_zwide_um=None,
            target_zoom=None,
            target_pixel_size_um=None,
            tif_path=None,
            success=False,
            error="translate failed",
            failure_stage="translate",
        )]

        feedback_dir = tmp_path / "feedback"
        plot_target_pairs(analysis_dir, picks, records,
                          feedback_dir=feedback_dir)

        assert len(list(feedback_dir.glob("*.png"))) == 0

    def test_no_successful_targets(self, tmp_path):
        import matplotlib
        matplotlib.use("Agg")
        from workflow.visualize import plot_target_pairs

        analysis_dir = tmp_path / "analysis"
        picks = _make_picks([])

        plot_target_pairs(analysis_dir, picks, [])
        # No error, no output
