"""Tests for the target mock-image provider.

Two surfaces under test:

  build_target_provider math + error paths
    - The provider reads the source overview tile from disk, crops a
      window around the picked cell sized to the target job's FOV,
      and resamples up to the target image's pixel dimensions. So
      the high-res target frame shows a zoomed-in view of the cell
      cellpose detected in the overview -- the "feels like real
      microscope" property.
    - Tests pin: zoom factor (crop size in overview pixels),
      orientation (asymmetric centroid lands at target centre, fails
      hard on any (col, row) <-> (x, y) swap), output shape/dtype,
      silent median-padding for cells near the overview's tile edge,
      and the per-tile (not run-fatal) error paths.

  acquire_targets integration
    - The per-pick provider is built INSIDE the ``if cfg.simulate:``
      gate -- not at the top of acquire_targets, and never on a
      real-hardware run.
    - Each pick gets its own provider closure; hijack_frame receives
      a different callable per pick.
    - Real-hardware regression: a sentinel that raises if called
      proves the provider construction path is structurally
      unreachable when cfg.simulate is False.

The provider's content source is the saved overview file (already
hijacked one step earlier in the same simulate run); this test file
synthesizes those overview files on disk with tifffile so the
target provider has something to read from. Pixel sizes are scalar
end-to-end (the rest of the pipeline does the same); non-square
images are exercised, non-square pixels are out of scope.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
import pytest
import tifffile

from shared.output_layout import Naming, build_image_name
from pipeline._hijack import NonSimulatorFrameError
from pipeline._mock_provider import build_target_provider
from pipeline.overview import Pick
from support import minimal_calibration


# ─── Helpers ──────────────────────────────────────────────────────


def _make_layout(tmp_dir: Path, *, hash6: str = "abcdef") -> SimpleNamespace:
    """Layout stub matching the LayoutPlan surface the provider needs:
    ``hash6``, ``run_dir``, ``data_dir(kind)``, ``metadata_dir(kind)``.
    The directory shape matches LayoutPlan: run/kind/data/metadata."""
    run_dir = tmp_dir
    (run_dir / "overview-scan" / "data").mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        hash6=hash6,
        run_dir=run_dir,
        data_dir=lambda kind: run_dir / kind / "data",
        metadata_dir=lambda kind: run_dir / kind / "data" / "metadata",
    )


def _write_overview_file(
    layout: SimpleNamespace,
    image: np.ndarray,
    *,
    g: int = 0,
    p: int = 0,
) -> Path:
    """Write a synthetic overview tile to disk at the canonical
    pipeline path. The provider reads this with tifffile.imread."""
    naming = Naming(
        acquisition_type="overview-scan",
        hash6=layout.hash6,
        g=g, p=p,
    )
    path = layout.data_dir("overview-scan") / build_image_name(naming)
    tifffile.imwrite(path, image, photometric="minisblack")
    return path


def _make_pick(
    *,
    centroid_col_row_px: tuple[float, float],
    source_pixel_size_um: tuple[float, float] = (0.65, 0.65),
    source_image_size_px: tuple[int, int] = (512, 512),
    position: int | None = 0,
    rid: str = "0",
    label: int = 1,
) -> Pick:
    """Build a Pick with just the fields build_target_provider reads
    (centroid_col_row_px, source_pixel_size_um, position, pick_id[0]).
    Other fields filled with defaults so dataclass construction works."""
    cx, cy = centroid_col_row_px
    return Pick(
        pick_id=(rid, 0, 0, label),
        tile_stage_xy_um=(0.0, 0.0),
        tile_zwide_um=0.0,
        source_pixel_size_um=source_pixel_size_um,
        source_image_size_px=source_image_size_px,
        centroid_col_row_px=(cx, cy),
        bbox_px=(0, 0, 10, 10),
        bbox_um=(0.0, 0.0),
        area_px=100,
        eccentricity=0.0,
        mean_intensity=0.0,
        cell_source_stage_xy_um=(0.0, 0.0),
        position=position,
    )


def _dummy_naming() -> Naming:
    """The target provider ignores the `naming` kwarg (content is
    determined entirely by the closed-over pick) but the signature
    contract still requires one for parity with the overview
    provider. Tests pass this stub."""
    return Naming(
        acquisition_type="target-acquisition",
        hash6="abcdef", g=0, p=0,
    )


# ─── Provider math: zoom factor, centring, shape, dtype, padding ──


class TestTargetProviderMath:
    def test_zoom_factor_correct(self, tmp_path):
        """Crop dimensions in overview pixels equal floor(target_shape
        * target_pixel_size / overview_pixel_size). Picks sizes that
        avoid half-pixel ties so banker's-rounding is not in play."""
        layout = _make_layout(tmp_path)
        # Overview: 0.65 µm/px, 512x512. Target: 0.13 µm/px, 200x200.
        # Zoom ratio = 0.65 / 0.13 = 5. Crop side in overview px =
        # floor(200 * 0.13 / 0.65) = floor(40.0) = 40.
        overview = np.zeros((512, 512), dtype=np.uint16)
        _write_overview_file(layout, overview)
        pick = _make_pick(
            centroid_col_row_px=(256.0, 256.0),
            source_pixel_size_um=(0.65, 0.65),
            source_image_size_px=(512, 512),
        )
        provider = build_target_provider(
            pick=pick, target_pixel_size_um=0.13, layout=layout,
        )
        # If the provider correctly crops 40x40 from the overview and
        # resamples to 200x200, the output shape is 200x200 regardless
        # of crop math correctness -- but we can detect a wrong crop
        # size by inspecting the call chain. Easiest pin: place a
        # unique marker in the overview at the crop's expected
        # boundary (centred crop = overview[236:276, 236:276]) and
        # check the marker lands at the target's boundary.
        overview[236, 236] = 60000  # corner of expected crop
        _write_overview_file(layout, overview)  # rewrite with marker
        out = provider((200, 200), np.uint16, naming=_dummy_naming())
        # The (236, 236) marker is at (0, 0) of the crop, which maps
        # to (0, 0) of the resized 200x200 output (resize preserves
        # corners). Marker should still be a local max there.
        assert out[0, 0] > out[5, 5], (
            "expected the overview pixel at the crop's top-left to "
            "land at the target's top-left after resize -- if it "
            "doesn't, the crop size in overview pixels is wrong"
        )

    def test_centroid_lands_at_target_center(self, tmp_path):
        """Asymmetric centroid (cx=120, cy=50) fails hard on any
        (col, row) <-> (x, y) swap. Marker at the pick's centroid
        in the overview must land at the centre of the target."""
        layout = _make_layout(tmp_path)
        overview = np.zeros((400, 400), dtype=np.uint16)
        # Place a unique bright marker at (cx=120, cy=50) -- so
        # overview[row=50, col=120] = 60000. NumPy indexing is
        # [row, col], so the swap risk is real.
        overview[50, 120] = 60000
        _write_overview_file(layout, overview)
        pick = _make_pick(
            centroid_col_row_px=(120.0, 50.0),
            source_pixel_size_um=(1.0, 1.0),
            source_image_size_px=(400, 400),
        )
        provider = build_target_provider(
            pick=pick, target_pixel_size_um=0.25, layout=layout,
        )
        # Target: 0.25 µm/px, 80x80 -> FOV 20x20 µm -> crop 20x20
        # overview px. Centred on (cx=120, cy=50), crop is
        # overview[40:60, 110:130]. Marker at (50, 120) is at the
        # crop's centre (10, 10), which maps to (40, 40) in the
        # resized 80x80 output.
        out = provider((80, 80), np.uint16, naming=_dummy_naming())
        # Find the brightest pixel; assert it's at the target's centre
        # (within +/- 1 pixel for rounding).
        peak_row, peak_col = np.unravel_index(np.argmax(out), out.shape)
        assert abs(peak_row - 40) <= 1, (
            f"marker landed at row={peak_row}, expected 40 (= H_tg/2). "
            f"Possible (row, col) <-> (col, row) swap in the crop math."
        )
        assert abs(peak_col - 40) <= 1, (
            f"marker landed at col={peak_col}, expected 40 (= W_tg/2). "
            f"Possible (x, y) <-> (y, x) swap in the crop math."
        )

    def test_output_shape_matches_target(self, tmp_path):
        """Shape is the requested target shape. Exercise non-square
        target image to confirm aspect ratio is honoured."""
        layout = _make_layout(tmp_path)
        overview = np.zeros((512, 512), dtype=np.uint16)
        _write_overview_file(layout, overview)
        pick = _make_pick(centroid_col_row_px=(256.0, 256.0))
        provider = build_target_provider(
            pick=pick, target_pixel_size_um=0.13, layout=layout,
        )
        # Non-square target: 200 tall, 100 wide.
        out = provider((200, 100), np.uint16, naming=_dummy_naming())
        assert out.shape == (200, 100)

    def test_output_dtype_matches_target(self, tmp_path):
        """Dtype matches the requested dtype. uint16 is the LAS X
        norm; pin it explicitly so a future change to resize() doesn't
        silently return float64."""
        layout = _make_layout(tmp_path)
        overview = np.full((128, 128), 12345, dtype=np.uint16)
        _write_overview_file(layout, overview)
        pick = _make_pick(centroid_col_row_px=(64.0, 64.0))
        provider = build_target_provider(
            pick=pick, target_pixel_size_um=0.13, layout=layout,
        )
        out = provider((64, 64), np.uint16, naming=_dummy_naming())
        assert out.dtype == np.uint16

    def test_edge_cell_pads_with_median_no_crash(self, tmp_path):
        """Cell at (2, 2) in overview pixels: crop extends well into
        negative coordinates. Provider must not crash; the padded
        region must carry the overview's median intensity (not zeros,
        not the unstoppable IndexError of slicing past array bounds)."""
        layout = _make_layout(tmp_path)
        # Overview with median intensity 30000 (uniform fill so median
        # is unambiguous), one small bright spot at the cell location
        # so the cell-content vs padding distinction is observable.
        overview = np.full((400, 400), 30000, dtype=np.uint16)
        overview[2, 2] = 60000  # cell centre
        _write_overview_file(layout, overview)
        pick = _make_pick(
            centroid_col_row_px=(2.0, 2.0),
            source_pixel_size_um=(1.0, 1.0),
            source_image_size_px=(400, 400),
        )
        provider = build_target_provider(
            pick=pick, target_pixel_size_um=0.25, layout=layout,
        )
        # Same geometry as test_centroid_lands_at_target_center: crop
        # is 20x20 centred on (cx=2, cy=2), so requested crop window
        # extends to (-8, -8) -> (12, 12). The provider must pad the
        # top-left padding zone with median (30000), not crash.
        out = provider((80, 80), np.uint16, naming=_dummy_naming())
        assert out.shape == (80, 80)
        # The top-left corner of the output is well inside the padded
        # zone (which started outside the overview). It should equal
        # the median, not anything from overview content.
        assert out[0, 0] == 30000


# ─── Provider error paths (per-tile, never NonSimulatorFrameError) ─


class TestTargetProviderErrors:
    def test_missing_overview_file_raises_per_tile_not_nsfe(self, tmp_path):
        """If the source overview file is missing (data integrity
        failure), the provider must raise something the acquisition
        loop records as a per-tile failure -- NOT NonSimulatorFrameError
        (which would hard-abort the run). Plan §Edge cases."""
        layout = _make_layout(tmp_path)
        # Pick references position=7, but no overview file was written.
        pick = _make_pick(centroid_col_row_px=(100.0, 100.0), position=7)
        provider = build_target_provider(
            pick=pick, target_pixel_size_um=0.13, layout=layout,
        )
        with pytest.raises(Exception) as exc_info:
            provider((128, 128), np.uint16, naming=_dummy_naming())
        assert not isinstance(exc_info.value, NonSimulatorFrameError), (
            "missing overview file is a per-tile data integrity issue, "
            "not a safety-allowlist failure -- must not propagate as "
            "NonSimulatorFrameError or it'd hard-abort the run"
        )

    def test_pick_without_position_raises_clearly(self, tmp_path):
        """A Pick reconstructed from a pre-`position` NPZ has
        position=None. In simulator mode that means we can't find the
        source overview file. Raise a RuntimeError with a message
        naming the contract -- not an opaque AttributeError."""
        layout = _make_layout(tmp_path)
        pick = _make_pick(centroid_col_row_px=(100.0, 100.0), position=None)
        provider = build_target_provider(
            pick=pick, target_pixel_size_um=0.13, layout=layout,
        )
        with pytest.raises(RuntimeError, match="position"):
            provider((128, 128), np.uint16, naming=_dummy_naming())

    def test_multi_plane_overview_raises_clearly(self, tmp_path):
        """The target mock requires a 2-D overview. hijack_frame
        already blocks multi-plane saved files upstream, so a fresh
        simulator run is 2-D by construction. This test pins the
        scope boundary structurally -- defends against stale /
        reused / hand-corrupted overview files where the upstream
        invariant doesn't hold. Per-tile RuntimeError, not
        NonSimulatorFrameError (which would hard-abort the run)."""
        layout = _make_layout(tmp_path)
        # Write a 3-D overview (2 planes) directly, bypassing the
        # hijack_frame 2-D guard. Reproduces the "stale file"
        # scenario the check defends against.
        overview = np.zeros((2, 64, 64), dtype=np.uint16)
        _write_overview_file(layout, overview)
        pick = _make_pick(
            centroid_col_row_px=(32.0, 32.0),
            source_pixel_size_um=(0.65, 0.65),
            source_image_size_px=(64, 64),
        )
        provider = build_target_provider(
            pick=pick, target_pixel_size_um=0.13, layout=layout,
        )
        # The shared geometry helper raises ValueError (more honest
        # for "bad input shape") rather than RuntimeError; either
        # would land in acquire_targets' per-pick failure path. What
        # matters is it's NOT a NonSimulatorFrameError (which would
        # hard-abort the whole run).
        with pytest.raises((ValueError, RuntimeError), match=r"2-D"):
            provider((64, 64), np.uint16, naming=_dummy_naming())


class TestTargetMockHonestResolution:
    """Pin the operator's directive: 'image quality must reflect actual
    resolution in the picture'. The hijack must NOT bilinear-upsample
    the overview crop -- doing so produces a target file whose visual
    smoothness misrepresents the actual information content (only
    overview-resolution info, stretched to target pixel count).

    Nearest-neighbour upsampling (order=0) is the honest fix: the file
    has the right target shape but each block of pixels carries the
    same value as one overview pixel, visibly signalling 'no new
    information added at the target step.'
    """

    def test_hijack_resize_uses_nearest_neighbour(self, tmp_path):
        """Pin that build_target_provider passes order=0 to
        skimage.transform.resize. A future contributor removing
        order=0 (e.g. via 'cleanup' that drops what looks like a
        default arg) silently re-introduces the dishonest bilinear
        smoothing. Spy catches it loudly."""
        from pipeline._mock_provider import build_target_provider

        layout = _make_layout(tmp_path)
        overview = np.full((64, 64), 10000, dtype=np.uint16)
        _write_overview_file(layout, overview)
        pick = _make_pick(
            centroid_col_row_px=(32.0, 32.0),
            source_pixel_size_um=(0.65, 0.65),
            source_image_size_px=(64, 64),
        )
        provider = build_target_provider(
            pick=pick, target_pixel_size_um=0.13, layout=layout,
        )

        # The lazy `from skimage.transform import resize` inside the
        # closure rebinds the name to whatever skimage.transform.resize
        # currently is, so patching the module attribute does
        # intercept the call.
        with mock.patch(
            "skimage.transform.resize",
            side_effect=lambda crop, shape, **k: np.zeros(shape, dtype=crop.dtype),
        ) as resize_spy:
            provider((64, 64), np.uint16, naming=_dummy_naming())

        assert resize_spy.call_count == 1
        assert resize_spy.call_args.kwargs.get("order") == 0, (
            f"hijack must pass order=0 (nearest-neighbour) to "
            f"skimage.transform.resize -- got kwargs "
            f"{resize_spy.call_args.kwargs}. Bilinear (order=1, "
            f"the default) is dishonest: it makes the target file "
            f"look smoother than its information content warrants."
        )

    def test_hijack_output_is_blocky_in_simulator_mode(self, tmp_path):
        """End-to-end pin: a 4x4 overview crop upsampled to 8x8 target
        must contain visible 2x2 blocks of identical values (nearest-
        neighbour), not gradients (bilinear). Catches order=0 being
        dropped even if the spy test above somehow misses it."""
        from pipeline._mock_provider import build_target_provider

        layout = _make_layout(tmp_path)
        # Construct an overview where each pixel has a distinct value
        # so any interpolation across pixels is visible. 8x8 overview;
        # crop will be ~4x4 (target 8x8 at 1x zoom would be 8x8, so we
        # need target larger than source for upsampling).
        overview = (np.arange(64, dtype=np.uint16).reshape(8, 8)
                    * 1000)
        _write_overview_file(layout, overview)
        pick = _make_pick(
            centroid_col_row_px=(4.0, 4.0),
            source_pixel_size_um=(1.0, 1.0),
            source_image_size_px=(8, 8),
        )
        provider = build_target_provider(
            # 2x zoom: target 8x8 covers same FOV as 4x4 overview pixels.
            pick=pick, target_pixel_size_um=0.5, layout=layout,
        )
        out = provider((8, 8), np.uint16, naming=_dummy_naming())

        # Each 2x2 block in the output should contain identical values
        # (nearest-neighbour upsampling: each overview pixel becomes a
        # 2x2 block of itself). Bilinear would interpolate ->
        # different values in the block.
        for r in range(0, 8, 2):
            for c in range(0, 8, 2):
                block = out[r:r+2, c:c+2]
                assert len(set(block.flatten().tolist())) == 1, (
                    f"2x2 block at ({r},{c}) has multiple distinct "
                    f"values {block.tolist()} -- nearest-neighbour "
                    f"upsampling should produce uniform blocks; "
                    f"bilinear was likely re-introduced"
                )


# ─── acquire_targets integration (wiring + simulate-gate) ─────────


def _integration_ctx(tmp_path, *, simulate: bool):
    """Build the minimal Context + Config + driver mocks that
    acquire_targets needs to run through one pick. Real-driver calls
    are patched at the module level in the test; this helper only
    sets up the data structures."""
    from pipeline.context import Config, Context, TargetState
    cfg = Config(
        acquisition_job="Overview", target_job="HiRes", af_job="AF",
        analysis_repo=Path("/fake"),
        experiment="t",
        simulate=simulate,
        mock_image_source="skimage_human_mitosis" if simulate else None,
    )
    layout = _make_layout(tmp_path)
    ctx = Context(
        cfg=cfg, client=mock.MagicMock(), hw=mock.MagicMock(),
        calibration=minimal_calibration(source_slot=2, target_slot=1),
        stage_config={"stage_um": {"z_wide": (0.0, 1000.0)}},
        engine=mock.MagicMock(),
        out_dir=tmp_path, run=SimpleNamespace(layout=layout),
        templates_dir=tmp_path / "templates",
        source_slot=2, target_slot=1,
        target_state=TargetState(),
    )
    return ctx


class TestAcquireTargetsIntegration:
    """Pin the wiring: build_target_provider lives inside the
    `if cfg.simulate:` gate, and each pick gets its own provider
    closure. Without these pins the math could be green while
    acquire_targets still calls the wrong provider, or worse, runs
    target-mock code on a real-hardware run."""

    def _drv_mocks(self, monkeypatch, tmp_path):
        """Patch out all driver calls acquire_targets makes.
        save writes a real fake target TIFF that
        hijack_frame can read."""
        from pipeline import target as target_mod
        import navigator_expert as drv

        monkeypatch.setattr(target_mod, "drv", drv)
        monkeypatch.setattr(
            "pipeline.target.calib.translate_xyz_between_objectives",
            lambda x, y, z, cal, **k: (x, y, z),
        )

        # Job settings → minimal parse_tile_geometry output.
        monkeypatch.setattr(drv, "get_job_settings",
                            lambda c, j, **_kwargs: {"_": "stub"})
        monkeypatch.setattr(drv, "parse_tile_geometry",
                            lambda s: {
                                "pixel_w_um": 0.13, "pixel_h_um": 0.13,
                                "pixels_x": 64, "pixels_y": 64,
                            })
        monkeypatch.setattr(drv, "make_changeable_copy",
                            lambda s: {"zPosition": {"z-galvo": 0.0}})

        # ensure_job_state: silent noop.
        monkeypatch.setattr(target_mod, "ensure_job_state",
                            lambda ctx, job: None)
        # acquire(): also a noop (driver call). Patch the module-level
        # import in target.py.
        monkeypatch.setattr(target_mod, "acquire",
                            lambda ctx, job, x, y, z: None)

        # acquire/save: write a real fake target TIFF + companion XML
        # that hijack_frame can read and the SystemTypeName guard will
        # accept (SIMULATOR).
        from shared.output_layout import build_xml_name

        def _fake_driver_acquire(client, job):
            return SimpleNamespace(job=job, command_result={"success": True})

        def _fake_save(client, acq, output_root, naming, lineage=None, **kw):
            data_dir = Path(output_root) / "target-acquisition" / "data"
            meta_dir = data_dir / "metadata"
            data_dir.mkdir(parents=True, exist_ok=True)
            meta_dir.mkdir(parents=True, exist_ok=True)
            image_path = data_dir / build_image_name(naming)
            xml_path = meta_dir / build_xml_name(naming)
            # 64x64 placeholder target frame.
            tifffile.imwrite(
                image_path, np.zeros((64, 64), dtype=np.uint16),
                description=(
                    '<?xml version="1.0"?>'
                    '<OME xmlns="http://example.org/o">'
                    '<OriginalMetadata '
                    'Name="Data - Image - Attachment - SystemTypeName" '
                    'Value="SIMULATOR"/>'
                    '</OME>'
                ),
                ome=False, photometric="minisblack",
            )
            xml_path.write_bytes(
                b'<?xml version="1.0"?>'
                b'<OME xmlns="http://example.org/o">'
                b'<OriginalMetadata '
                b'Name="Data - Image - Attachment - SystemTypeName" '
                b'Value="SIMULATOR"/>'
                b'</OME>'
            )
            return SimpleNamespace(
                image_paths={drv.PlaneIndex(t=0, z=0, c=0): image_path},
                xml_paths={drv.PositionIndex(t=0, v=0): xml_path},
                naming=naming,
            )

        monkeypatch.setattr(drv, "acquire", _fake_driver_acquire)
        monkeypatch.setattr(drv, "save", _fake_save)

    def _two_picks(self, tmp_path, layout):
        """Build a Picks container with 2 picks at distinct centroids,
        each referencing a (distinct) source overview tile we've
        written."""
        from pipeline.selection import Picks
        # Two overview tiles, two distinct picks.
        ov_a = np.full((400, 400), 10000, dtype=np.uint16)
        ov_a[100, 200] = 50000     # pick A's centroid
        ov_b = np.full((400, 400), 20000, dtype=np.uint16)
        ov_b[50, 50] = 60000       # pick B's centroid
        _write_overview_file(layout, ov_a, g=0, p=0)
        _write_overview_file(layout, ov_b, g=0, p=1)
        picks_a = _make_pick(
            centroid_col_row_px=(200.0, 100.0),
            source_pixel_size_um=(0.65, 0.65),
            source_image_size_px=(400, 400),
            position=0, label=1,
        )
        picks_b = _make_pick(
            centroid_col_row_px=(50.0, 50.0),
            source_pixel_size_um=(0.65, 0.65),
            source_image_size_px=(400, 400),
            position=1, label=2,
        )
        return Picks(items=[picks_a, picks_b], simulated=True)

    def test_acquire_targets_uses_per_pick_target_provider_on_simulate(
        self, tmp_path, monkeypatch,
    ):
        """The integration test: simulate=True yields N hijack_frame
        calls, each with a different provider closure. Catches the
        bug where math is green but the loop still uses the wrong
        provider (e.g., re-uses get_provider("skimage_human_mitosis")
        which yields identical content per (g, p))."""
        self._drv_mocks(monkeypatch, tmp_path)
        ctx = _integration_ctx(tmp_path, simulate=True)
        picks = self._two_picks(tmp_path, ctx.run.layout)

        # Spy on hijack_frame: capture the provider arg per call.
        from pipeline import target as target_mod
        seen_providers = []
        real_hijack = target_mod.hijack_frame

        def _spy(result, *, kind, layout, provider):
            seen_providers.append(provider)
            real_hijack(result, kind=kind, layout=layout, provider=provider)

        monkeypatch.setattr(target_mod, "hijack_frame", _spy)

        from pipeline.target import acquire_targets
        records = acquire_targets(
            ctx, picks,
            live_display=False, save_png=False, on_target=None,
        )

        assert len(records) == 2
        assert all(r.success for r in records), (
            f"expected both records to succeed; got "
            f"{[(r.success, r.error) for r in records]}"
        )
        assert len(seen_providers) == 2, (
            f"expected 2 hijack_frame calls (one per pick); "
            f"got {len(seen_providers)}"
        )
        # Distinct closure objects -- each pick gets its own provider.
        # `is not` rather than `!=` because closures don't compare by
        # value; the per-iteration construction is what we're pinning.
        assert seen_providers[0] is not seen_providers[1], (
            "both hijack calls received the same provider object -- "
            "looks like a shared/top-of-function provider was passed "
            "instead of a per-pick closure"
        )

    def test_acquire_targets_does_not_build_target_provider_when_simulate_is_false(
        self, tmp_path, monkeypatch,
    ):
        """Real-hardware regression: simulate=False must not build
        the target provider OR call hijack_frame. If it does, the
        sentinel raises -- structurally pins that the new code is
        gated to simulate mode."""
        self._drv_mocks(monkeypatch, tmp_path)
        ctx = _integration_ctx(tmp_path, simulate=False)
        # Picks with simulated=False; one pick is enough.
        from pipeline.selection import Picks
        pick = _make_pick(
            centroid_col_row_px=(100.0, 100.0),
            source_pixel_size_um=(0.65, 0.65),
            source_image_size_px=(400, 400),
            position=0,
        )
        picks = Picks(items=[pick], simulated=False)

        # Sentinel: any call to build_target_provider or hijack_frame
        # on a non-simulate run is a regression.
        from pipeline import target as target_mod
        from pipeline import _mock_provider as mp_mod

        def _build_sentinel(*args, **kwargs):
            raise AssertionError(
                "build_target_provider must not run when cfg.simulate "
                "is False -- regression in the simulate gate"
            )

        def _hijack_sentinel(*args, **kwargs):
            raise AssertionError(
                "hijack_frame must not run when cfg.simulate is "
                "False -- regression in the simulate gate"
            )

        monkeypatch.setattr(mp_mod, "build_target_provider", _build_sentinel)
        # Patch the name target.py imported into its namespace.
        monkeypatch.setattr(
            target_mod, "build_target_provider", _build_sentinel,
            raising=False,
        )
        monkeypatch.setattr(target_mod, "hijack_frame", _hijack_sentinel)

        from pipeline.target import acquire_targets
        records = acquire_targets(
            ctx, picks,
            live_display=False, save_png=False, on_target=None,
        )
        # The acquisition ran (no sentinel raised) and produced one
        # successful record. No hijack, no provider, real-hardware path
        # is intact.
        assert len(records) == 1
        assert records[0].success
        assert records[0].simulated is False
