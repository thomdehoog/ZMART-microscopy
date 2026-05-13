"""Unit tests for visualize.py — overview triptych and target pairs.

All tests use synthetic npz files and mock images on disk.
No hardware, no engine, no ctx.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

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


# ─── Style-token coverage (Bundle D / D6 #5) ─────────────────────


class TestStyleTokenCoverage:
    """Pin the design intent at workflow/visualize.py line 62:
    'Anything not on this scale is a bug.' Walk the visualize.py source,
    strip the sentinel-bracketed style-tokens block, and assert no hex
    color or fontsize integer literal survives outside.

    Failures here usually mean a new renderer was added with literals;
    add a named token inside the BEGIN/END VISUALIZE STYLE TOKENS
    block and reference it instead. Docstring examples that need to
    mention a hex color or fontsize value should use a placeholder
    like 'fontsize=<size>' (not a literal integer) to avoid
    false-positives.
    """
    _BEGIN_SENTINEL = "# BEGIN VISUALIZE STYLE TOKENS"
    _END_SENTINEL = "# END VISUALIZE STYLE TOKENS"
    _HEX_COLOR_RE = re.compile(r"#[0-9A-Fa-f]{6}\b")
    _FONTSIZE_RE = re.compile(r"\bfontsize\s*=\s*\d+(?:\.\d+)?\b")

    def _read_source(self) -> str:
        import workflow.visualize as viz_mod
        return inspect.getsource(viz_mod)

    def test_exactly_one_begin_and_one_end_sentinel(self):
        src = self._read_source()
        assert src.count(self._BEGIN_SENTINEL) == 1, (
            f"expected exactly one {self._BEGIN_SENTINEL!r} in visualize.py"
        )
        assert src.count(self._END_SENTINEL) == 1, (
            f"expected exactly one {self._END_SENTINEL!r} in visualize.py"
        )

    def test_begin_appears_before_end(self):
        src = self._read_source()
        begin = src.index(self._BEGIN_SENTINEL)
        end = src.index(self._END_SENTINEL)
        assert begin < end, "BEGIN sentinel must appear before END sentinel"

    def test_no_hex_color_literal_outside_style_block(self):
        src = self._read_source()
        outside = self._strip_style_block(src)
        violations = self._HEX_COLOR_RE.findall(outside)
        assert not violations, (
            f"hex color literals found OUTSIDE the style-tokens block: "
            f"{violations!r}. Add a named token to "
            f"BEGIN/END VISUALIZE STYLE TOKENS and reference it. "
            f"If the literal is in a docstring example, change it to a "
            f"placeholder (e.g. '#<hex>') to avoid this check."
        )

    def test_no_fontsize_integer_literal_outside_style_block(self):
        src = self._read_source()
        outside = self._strip_style_block(src)
        violations = self._FONTSIZE_RE.findall(outside)
        assert not violations, (
            f"fontsize=<integer> literals found OUTSIDE the style-tokens "
            f"block: {violations!r}. Use one of the _FONT_* tokens. "
            f"If the literal is in a docstring example, change it to a "
            f"placeholder (e.g. 'fontsize=<size>') to avoid this check."
        )

    def _strip_style_block(self, src: str) -> str:
        begin = src.index(self._BEGIN_SENTINEL)
        end = src.index(self._END_SENTINEL)
        return src[:begin] + src[end + len(self._END_SENTINEL):]


# ─── display_tile flags (Bundle A / A2) ──────────────────────────


def _make_tile_event(n_cells: int = 0):
    """Minimal TileEvent for testing display_tile flag behavior."""
    from workflow.overview import TileEvent
    return TileEvent(
        image_2d=np.zeros((8, 8)),
        masks=np.zeros((8, 8), dtype=np.int32),
        tile_id=("0", 0, 0),
        n_cells=n_cells,
        analysis_image_source="acquired",
    )


def _make_target_record(*, tif_path=None, success: bool = True):
    """Minimal TargetRecord for display_target flag tests. No tile_data
    will be found (analysis_dir empty), so the renderer falls back to
    its "N/A" placeholders without touching tile npz files.
    """
    from workflow.target import TargetRecord
    return TargetRecord(
        pick_id=("0", 0, 0, 1),
        cell_source_stage_xy_um=(1005.0, 2005.0),
        source_zwide_um=100.0,
        target_stage_xy_um=(1005.0, 2005.0),
        target_zwide_um=100.0,
        target_zoom=None,
        target_pixel_size_um=0.25,
        tif_path=tif_path,
        success=success,
        error=None,
    )


class TestDisplayTileFlags:
    def test_live_display_false_skips_inline_display(self, monkeypatch, tmp_path):
        """display_tile with live_display=False must build the figure and
        skip the IPython.display() call so the notebook does not show a
        figure. The figure is still saved when save_png=True.
        """
        import IPython.display as ipy_display
        fake_display = MagicMock(name="ipy_display")
        monkeypatch.setattr(ipy_display, "display", fake_display)

        from workflow.visualize import display_tile
        display_tile(
            _make_tile_event(),
            feedback_dir=tmp_path,
            live_display=False,
            save_png=True,
        )

        fake_display.assert_not_called()
        # save_png=True with a feedback_dir still produces the PNG.
        assert list(tmp_path.glob("live_tile_R*.png"))

    def test_save_png_false_skips_savefig(self, monkeypatch, tmp_path):
        """display_tile with save_png=False must skip fig.savefig even
        when feedback_dir is set; the inline display still fires.
        """
        import IPython.display as ipy_display
        fake_display = MagicMock(name="ipy_display")
        monkeypatch.setattr(ipy_display, "display", fake_display)

        from workflow.visualize import display_tile
        display_tile(
            _make_tile_event(),
            feedback_dir=tmp_path,
            live_display=True,
            save_png=False,
        )

        assert list(tmp_path.glob("*.png")) == []
        fake_display.assert_called_once()


class TestDisplayTileSaveQueue:
    """Bundle A / A4b: per-tile savefig routes through _FigureSaveQueue.

    Pins three contracts:
      - Callback latency: display_tile returns before the save completes
        when the worker is gated.
      - Close exactly once on the sync path (no _save_queue, no save_png).
      - Close exactly once on the queued path (worker takes ownership of
        plt.close; producer's finally must not double-close).
    """
    def test_callback_returns_promptly_when_save_queue_worker_is_gated(
        self, monkeypatch, tmp_path,
    ):
        """With the worker blocked, display_tile returns immediately --
        it submits to the queue and proceeds without waiting for savefig.
        Event-gated, no time.sleep.
        """
        import threading
        import IPython.display as ipy_display
        from workflow._save_queue import _FigureSaveQueue
        from workflow.visualize import display_tile

        monkeypatch.setattr(ipy_display, "display", MagicMock())

        queue = _FigureSaveQueue(max_queued=4)
        # Block the worker by submitting a gated "first" save.
        gate = threading.Event()
        queue.submit(lambda: gate.wait(timeout=5.0))

        display_tile(
            _make_tile_event(),
            feedback_dir=tmp_path,
            live_display=False,
            save_png=True,
            _save_queue=queue,
        )

        # display_tile has returned. The worker is still gated, so the
        # second save (display_tile's own) has not been processed yet --
        # the PNG must not exist on disk.
        assert list(tmp_path.glob("*.png")) == []

        # Release the worker and drain.
        gate.set()
        queue.shutdown()

        # After drain, display_tile's PNG is on disk.
        assert list(tmp_path.glob("live_tile_R*.png"))

    def test_closes_figure_exactly_once_on_sync_path(
        self, monkeypatch, tmp_path,
    ):
        """No _save_queue, save_png=False: figure is built on the
        producer thread and closed by its finally block. plt.close
        must be called exactly once for that figure.
        """
        import matplotlib.pyplot as plt
        import IPython.display as ipy_display

        monkeypatch.setattr(ipy_display, "display", MagicMock())

        close_calls: list = []
        real_close = plt.close

        def counting_close(fig=None):
            close_calls.append(id(fig) if fig is not None else None)
            real_close(fig)

        monkeypatch.setattr(plt, "close", counting_close)

        from workflow.visualize import display_tile
        display_tile(
            _make_tile_event(),
            save_png=False,
            live_display=False,
        )

        # Exactly one close, for one figure (no plt.close("all") leak).
        assert len(close_calls) == 1

    def test_closes_figure_exactly_once_on_queued_path(
        self, monkeypatch, tmp_path,
    ):
        """With _save_queue, ownership transfers to the worker. The
        worker calls plt.close after savefig; the producer's finally
        must NOT also close (no double-close).
        """
        import matplotlib.pyplot as plt
        import IPython.display as ipy_display

        monkeypatch.setattr(ipy_display, "display", MagicMock())

        close_calls: list = []
        real_close = plt.close

        def counting_close(fig=None):
            close_calls.append(id(fig) if fig is not None else None)
            real_close(fig)

        monkeypatch.setattr(plt, "close", counting_close)

        from workflow._save_queue import _FigureSaveQueue
        from workflow.visualize import display_tile

        with _FigureSaveQueue() as queue:
            display_tile(
                _make_tile_event(),
                feedback_dir=tmp_path,
                live_display=False,
                save_png=True,
                _save_queue=queue,
            )
            # Queue exit -> shutdown -> drain -> worker closes the fig.

        # Exactly one close, performed by the worker.
        assert len(close_calls) == 1
        # And the PNG made it to disk.
        assert list(tmp_path.glob("live_tile_R*.png"))


class TestDisplayTargetSaveQueue:
    """Bundle A / A4b coverage symmetry: pin display_target's queued-
    save ownership-transfer contract. display_target mirrors
    display_tile's figure-ownership semantics -- when _save_queue is
    provided and save_png=True, the worker takes ownership and closes
    the figure; the producer's finally must not also close.

    A4b initially shipped only the display_tile close-once test; this
    closes the documented coverage gap for display_target.
    """
    def test_closes_figure_exactly_once_on_queued_path(
        self, monkeypatch, tmp_path,
    ):
        """display_target with _save_queue + save_png=True transfers
        figure ownership to the worker. The worker calls plt.close once
        after savefig; the producer's finally must not also close.
        """
        import matplotlib.pyplot as plt
        import IPython.display as ipy_display

        monkeypatch.setattr(ipy_display, "display", MagicMock())

        close_calls: list = []
        real_close = plt.close

        def counting_close(fig=None):
            close_calls.append(id(fig) if fig is not None else None)
            real_close(fig)

        monkeypatch.setattr(plt, "close", counting_close)

        from workflow._save_queue import _FigureSaveQueue
        from workflow.visualize import display_target

        analysis_dir = tmp_path / "analysis"
        analysis_dir.mkdir()
        feedback_dir = tmp_path / "feedback"

        with _FigureSaveQueue() as queue:
            display_target(
                pick=None,                       # falls back to "N/A" panels
                record=_make_target_record(),
                analysis_dir=analysis_dir,
                feedback_dir=feedback_dir,
                live_display=False,
                save_png=True,
                _save_queue=queue,
            )
            # Queue __exit__ -> shutdown -> drain -> worker closes the fig.

        # Exactly one close, performed by the worker.
        assert len(close_calls) == 1
        # And the PNG made it to disk.
        assert list(feedback_dir.glob("live_target_R*.png"))


class TestDisplayTargetFlags:
    def test_live_display_false_skips_inline_display(self, monkeypatch, tmp_path):
        """display_target with live_display=False builds the figure but
        skips display(). save_png still produces the PNG.
        """
        import IPython.display as ipy_display
        fake_display = MagicMock(name="ipy_display")
        monkeypatch.setattr(ipy_display, "display", fake_display)

        from workflow.visualize import display_target
        analysis_dir = tmp_path / "analysis"
        analysis_dir.mkdir()
        feedback_dir = tmp_path / "feedback"

        display_target(
            pick=None,                          # falls back to "N/A" panels
            record=_make_target_record(),
            analysis_dir=analysis_dir,
            feedback_dir=feedback_dir,
            live_display=False,
            save_png=True,
        )

        fake_display.assert_not_called()
        assert list(feedback_dir.glob("live_target_R*.png"))

    def test_save_png_false_skips_savefig(self, monkeypatch, tmp_path):
        """display_target with save_png=False skips fig.savefig even
        when feedback_dir is provided. The inline display still fires.
        """
        import IPython.display as ipy_display
        fake_display = MagicMock(name="ipy_display")
        monkeypatch.setattr(ipy_display, "display", fake_display)

        from workflow.visualize import display_target
        analysis_dir = tmp_path / "analysis"
        analysis_dir.mkdir()
        feedback_dir = tmp_path / "feedback"

        display_target(
            pick=None,
            record=_make_target_record(),
            analysis_dir=analysis_dir,
            feedback_dir=feedback_dir,
            live_display=True,
            save_png=False,
        )

        # feedback_dir may or may not exist (mkdir is gated by save_png),
        # but in any case there must be no PNG.
        if feedback_dir.exists():
            assert list(feedback_dir.glob("*.png")) == []
        fake_display.assert_called_once()


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


# ─── _centroid_crop_at_target_fov ─────────────────────────────────


class TestCentroidCropAtTargetFov:
    def _make_rec(self, target_pixel_size_um=0.25):
        from workflow.target import TargetRecord
        return TargetRecord(
            pick_id=("0", 0, 0, 1),
            cell_source_stage_xy_um=(0.0, 0.0),
            source_zwide_um=0.0,
            target_stage_xy_um=None,
            target_zwide_um=None,
            target_zoom=None,
            target_pixel_size_um=target_pixel_size_um,
            tif_path=None,
            success=True,
            error=None,
        )

    def test_center_crop_correct_size(self):
        from workflow.visualize import _centroid_crop_at_target_fov
        image = np.zeros((100, 100))
        # target: 20x20 px at 0.25 um/px = 5x5 um FOV
        # source: 0.5 um/px → crop = 5/0.5 = 10x10 px
        target_img = np.zeros((20, 20))
        pick = _make_pick(("0", 0, 0), label=1,
                          centroid_rc=(50.0, 50.0),
                          bbox=(45, 45, 55, 55))
        rec = self._make_rec(target_pixel_size_um=0.25)

        crop = _centroid_crop_at_target_fov(image, pick, rec, target_img)
        assert crop.shape == (10, 10)

    def test_center_crop_centered_on_centroid(self):
        from workflow.visualize import _centroid_crop_at_target_fov
        image = np.arange(10000).reshape(100, 100).astype(float)
        target_img = np.zeros((20, 20))
        # centroid at (col=60, row=40)
        pick = _make_pick(("0", 0, 0), label=1,
                          centroid_rc=(60.0, 40.0),
                          bbox=(35, 55, 45, 65))
        rec = self._make_rec(target_pixel_size_um=0.25)

        crop = _centroid_crop_at_target_fov(image, pick, rec, target_img)
        # crop should be rows 35:45, cols 55:65 (centered on row=40, col=60)
        assert crop.shape == (10, 10)
        expected = image[35:45, 55:65]
        np.testing.assert_array_equal(crop, expected)

    def test_corner_clamp_shifts_window(self):
        from workflow.visualize import _centroid_crop_at_target_fov
        image = np.zeros((100, 100))
        target_img = np.zeros((20, 20))
        # centroid near top-left corner — crop would go negative
        pick = _make_pick(("0", 0, 0), label=1,
                          centroid_rc=(2.0, 2.0),
                          bbox=(0, 0, 5, 5))
        rec = self._make_rec(target_pixel_size_um=0.25)

        crop = _centroid_crop_at_target_fov(image, pick, rec, target_img)
        # Should shift to (0,0) but keep the 10x10 size
        assert crop.shape == (10, 10)

    def test_bottom_right_clamp(self):
        from workflow.visualize import _centroid_crop_at_target_fov
        image = np.zeros((100, 100))
        target_img = np.zeros((20, 20))
        # centroid near bottom-right corner
        pick = _make_pick(("0", 0, 0), label=1,
                          centroid_rc=(98.0, 98.0),
                          bbox=(93, 93, 100, 100))
        rec = self._make_rec(target_pixel_size_um=0.25)

        crop = _centroid_crop_at_target_fov(image, pick, rec, target_img)
        assert crop.shape == (10, 10)

    def test_fallback_to_bbox_when_no_target(self):
        from workflow.visualize import _centroid_crop_at_target_fov
        image = np.zeros((100, 100))
        pick = _make_pick(("0", 0, 0), label=1,
                          centroid_rc=(50.0, 50.0),
                          bbox=(40, 42, 60, 58))
        rec = self._make_rec(target_pixel_size_um=None)

        crop = _centroid_crop_at_target_fov(image, pick, rec, None)
        # Falls back to bbox size: (60-40) x (58-42) = 20 x 16
        assert crop.shape == (20, 16)

    def test_col_row_mapping(self):
        """Verify col maps to x-axis and row maps to y-axis."""
        from workflow.visualize import _centroid_crop_at_target_fov
        image = np.zeros((200, 300))
        image[50, 150] = 1.0  # marker at row=50, col=150
        target_img = np.zeros((4, 4))
        # centroid at (col=150, row=50) → crop should contain the marker
        pick = _make_pick(("0", 0, 0), label=1,
                          centroid_rc=(150.0, 50.0),
                          bbox=(48, 148, 52, 152))
        rec = self._make_rec(target_pixel_size_um=0.25)

        crop = _centroid_crop_at_target_fov(image, pick, rec, target_img)
        assert crop.sum() == 1.0, "Marker should be inside the crop"


# ─── _ensure_2d ──────────────────────────────────────────────────


class TestEnsure2D:
    def test_2d_passthrough(self):
        from workflow.visualize import _ensure_2d
        img = np.zeros((64, 64))
        assert _ensure_2d(img).shape == (64, 64)

    def test_3d_first_plane(self):
        from workflow.visualize import _ensure_2d
        img = np.zeros((5, 64, 64))
        assert _ensure_2d(img).shape == (64, 64)

    def test_3d_channel_last(self):
        from workflow.visualize import _ensure_2d
        img = np.zeros((64, 64, 3))
        assert _ensure_2d(img).shape == (64, 64)

    def test_4d_tczyx_style(self):
        from workflow.visualize import _ensure_2d
        img = np.zeros((2, 3, 64, 64))
        assert _ensure_2d(img).shape == (64, 64)

    def test_4d_channel_last(self):
        from workflow.visualize import _ensure_2d
        img = np.zeros((5, 64, 64, 3))
        result = _ensure_2d(img)
        assert result.shape == (64, 64)


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


# ─── Bundle D / D6 remaining tests (#1-#4) ────────────────────────


class TestDisplayTileWideField:
    """D6 #1: aspect-driven width_ratios from D4a. A wide-format scan
    field must produce a field-position panel wider than the tile +
    segmentation panels. Regression-pins the previous [1, 1, 1] bug.
    """
    def test_wide_field_yields_wider_field_panel(self, monkeypatch, tmp_path):
        import matplotlib.pyplot as plt
        import IPython.display as ipy_display
        monkeypatch.setattr(ipy_display, "display", MagicMock())

        # 10:1 wide scan field (single row of 10 tiles).
        scan_field = {
            "tile_positions": {
                "0": {
                    "job_name": "Overview",
                    "tile_size_um": 100,
                    "positions": [
                        {"row": 0, "col": c, "x_um": c * 100, "y_um": 0}
                        for c in range(10)
                    ],
                }
            },
        }

        captured: list = []
        real_subplots = plt.subplots

        def capture_subplots(*args, **kwargs):
            captured.append(kwargs.get("gridspec_kw"))
            return real_subplots(*args, **kwargs)

        monkeypatch.setattr(plt, "subplots", capture_subplots)

        from workflow.visualize import display_tile
        display_tile(
            _make_tile_event(),
            scan_field=scan_field,
            live_display=False,
            save_png=False,
        )

        # First (and only) subplots call is the 3-panel field-aware layout.
        gskw = captured[0]
        assert gskw is not None
        ratios = gskw["width_ratios"]
        assert len(ratios) == 3
        # Wide field -> field panel share > 1.
        assert ratios[0] > 1.0, (
            f"width_ratios[0] must be > 1 for a 10:1 wide field, got {ratios}"
        )
        # Clamped at 2.5 per the D4a aspect cap.
        assert ratios[0] <= 2.5
        # Tile + segmentation panels stay equal-width to each other.
        assert ratios[1] == ratios[2]


class TestSharedScanFieldRenderer:
    """D6 #2: render_scan_field_panel produces consistent geometry
    regardless of whether the caller is the Step 3 path (highlight only)
    or the Step 2b/2c path (tile_styles supplied). Catches future
    divergence of the renderer's geometry behavior.
    """
    def test_context_matches_across_call_styles(self):
        import matplotlib.pyplot as plt
        from workflow.visualize import render_scan_field_panel, TileStyle

        scan_field = {
            "tile_positions": {
                "0": {
                    "tile_size_um": 100,
                    "positions": [
                        {"row": 0, "col": 0, "x_um": 0, "y_um": 0},
                        {"row": 0, "col": 1, "x_um": 100, "y_um": 0},
                    ],
                }
            },
        }

        fig1, ax1 = plt.subplots()
        rc1 = render_scan_field_panel(
            ax1, scan_field, None, highlight_tile_id=("0", 0, 0),
        )
        plt.close(fig1)

        styles = {
            ("0", 0, 0): TileStyle(facecolor="red", edgecolor="red"),
            ("0", 0, 1): TileStyle(facecolor="blue", edgecolor="blue"),
        }
        fig2, ax2 = plt.subplots()
        rc2 = render_scan_field_panel(
            ax2, scan_field, None, tile_styles=styles,
        )
        plt.close(fig2)

        # Geometry context is identical regardless of styling.
        assert rc1.tile_bounds == rc2.tile_bounds
        assert rc1.extent_x == rc2.extent_x
        assert rc1.extent_y == rc2.extent_y
        assert rc1.max_tile_size_um == rc2.max_tile_size_um


class TestLoadTileNpzWarning:
    """D6 #3: _load_tile_npz logs a warning and returns None on a
    corrupt / unreadable npz, not silently swallowed. Per D5a's
    log-and-skip pattern.
    """
    def test_warns_on_unreadable_file(self, tmp_path, capsys):
        from workflow.visualize import _load_tile_npz

        bad_npz = tmp_path / "corrupt.npz"
        bad_npz.write_bytes(b"not a valid npz file")

        result = _load_tile_npz(bad_npz)

        assert result is None
        captured = capsys.readouterr()
        assert "[visualize] WARNING" in captured.out
        assert "corrupt.npz" in captured.out


class TestRenderCropBoundary:
    """D6 #4: _render_crop / _safe_crop_window behavior when the image
    is smaller than _CROP_SIZE_PX. Per the D4a docstring-honesty fix:
    smaller images yield a smaller crop (no zero-padding, no exception).
    """
    def test_image_smaller_than_crop_size_renders_whole_image(self):
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
        from workflow.overview import Pick
        from workflow.visualize import _render_crop

        # 32x32 image << _CROP_SIZE_PX (96).
        img = np.zeros((32, 32), dtype=np.uint8)
        img[10:20, 10:20] = 200

        pick = Pick(
            pick_id=("0", 0, 0, 1),
            tile_stage_xy_um=(0.0, 0.0), tile_zwide_um=0.5,
            source_pixel_size_um=(0.65, 0.65),
            source_image_size_px=(32, 32),
            centroid_col_row_px=(16.0, 16.0),
            bbox_px=(10, 10, 20, 20), bbox_um=(13.0, 13.0),
            area_px=100, eccentricity=0.5, mean_intensity=100.0,
            cell_source_stage_xy_um=(0.5, 0.5),
        )

        fig, ax = plt.subplots()
        try:
            _render_crop(ax, pick, ("0", 0, 0), img, Rectangle)
            images = ax.get_images()
            assert len(images) == 1, (
                "expected exactly one imshow on the crop axes"
            )
            displayed = images[0].get_array()
            # Whole image is shown (smaller-than-_CROP_SIZE_PX path).
            assert displayed.shape == (32, 32), (
                f"expected 32x32 fallback, got {displayed.shape}"
            )
        finally:
            plt.close(fig)
