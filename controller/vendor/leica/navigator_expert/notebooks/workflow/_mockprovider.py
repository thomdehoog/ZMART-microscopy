"""Mock image providers for simulation mode (Plan 2 §4b + target zoom).

Two flavours of provider, distinguished by what determines the mock
content:

  Overview providers (``get_provider(name)``):
    Invent content from scratch, deterministic from (Naming.g,
    Naming.p). The returned array becomes the pixel content of the
    canonical overview .ome.tiff in simulation mode -- see
    workflow/_hijack.py for the OME-preserving overwrite. Each
    overview tile gets distinct content; that's what an overview
    looks like in reality.

  Target provider (``build_target_provider(...)``):
    Derives content from the saved overview tile this pick came from
    -- reads the source overview file, crops a window around the
    picked cell sized to match the target job's FOV, resamples up to
    the target image's pixel dimensions. The high-res target frame
    then shows a zoomed-in view of the same cell cellpose detected
    in the overview, instead of arbitrary mock content. Closes over
    the per-pick context (centroid + lineage); cheap to construct,
    re-built per iteration in acquire_targets.

The two builders are intentionally separate functions because they
do structurally different things (one invents content, the other
derives it from a saved file). Both return callables matching the
same ``(shape, dtype, *, naming) -> ndarray`` contract so the
generic ``hijack_frame`` can call either without branching.

Providers must never raise on a sensible (shape, dtype, naming);
shape/dtype mismatches are caught by the hijack and recorded as a
per-tile hijack failure. Genuine data-integrity errors (e.g.,
missing source overview file for the target provider) raise as
``RuntimeError``/``OSError`` -- per-tile, never
``NonSimulatorFrameError``.
"""
from __future__ import annotations

from typing import Any, Callable

import numpy as np

from _shared.output_layout import Naming, build_image_name

from ._geom import crop_overview_at_target_fov


def get_provider(name: str) -> Callable:
    """Look up an overview mock provider by name. Raises ValueError on unknown."""
    if name == "skimage_human_mitosis":
        return _skimage_human_mitosis
    raise ValueError(
        f"Unknown mock_image_source: {name!r}. "
        f"Known providers: skimage_human_mitosis."
    )


def _skimage_human_mitosis(
    shape: tuple, dtype, *, naming,
) -> np.ndarray:
    """Tile skimage's human_mitosis() image by (g, p), cropped to
    `shape` and cast to `dtype`. Deterministic from (naming.g, naming.p).
    """
    # Lazy: skimage import is heavy and only needed when the provider
    # is actually selected.
    from skimage.data import human_mitosis

    src = human_mitosis()                    # uint8, typically 512x512
    sh, sw = src.shape
    th, tw = shape[:2]
    g, p = int(naming.g), int(naming.p)

    # Deterministic per-(g, p) origin within the source, modulo the
    # available slack. The exact stride does not matter -- the goal is
    # only "different tiles get different content".
    y0 = ((g * 41 + p * 17) * th) % max(1, sh - th + 1) if sh > th else 0
    x0 = ((g * 73 + p * 29) * tw) % max(1, sw - tw + 1) if sw > tw else 0
    tile = src[y0:y0 + th, x0:x0 + tw]

    # If the source is smaller than the target in either dim, repeat.
    if tile.shape[0] < th or tile.shape[1] < tw:
        ry = -(-th // max(1, tile.shape[0]))
        rx = -(-tw // max(1, tile.shape[1]))
        tile = np.tile(tile, (ry, rx))[:th, :tw]

    # Cast to the target dtype. For unsigned-int targets wider than 8
    # bits, scale 0..255 → 0..max so the image uses the dynamic range.
    if np.issubdtype(dtype, np.unsignedinteger):
        info = np.iinfo(dtype)
        scaled = tile.astype(np.float64) * (info.max / 255.0)
        return scaled.astype(dtype)
    return tile.astype(dtype)


def build_target_provider(
    *,
    pick: Any,
    target_pixel_size_um: float,
    layout: Any,
) -> Callable:
    """Build a per-pick target mock provider.

    Returns a callable matching the standard provider contract
    ``(shape, dtype, *, naming) -> ndarray``. The returned callable
    is a closure over the source pick + layout + scalar target pixel
    size; the ``naming`` argument is **ignored** at call time because
    the content source is determined entirely by the closed-over
    ``pick`` (it identifies which overview file to read from and
    where the cell is in that file).

    Plan §"Geometry" defines the math. Summary:
      1. Read source overview tile (``layout.data_dir("overview-scan")
         / build_image_name(overview_naming)``).
      2. Crop a window centred on ``pick.centroid_col_row_px``, sized
         in overview pixels to match the target job's physical FOV
         (``W_tg * target_pixel_size_um / overview_pixel_size_um``;
         per-axis from per-axis target dimensions, scalar pixel size
         on both axes per the rest-of-pipeline contract).
      3. Pad with overview's median intensity for any area that
         falls outside the overview's bounds (cell near tile edge --
         silent padding; this is normal, not an error).
      4. Resample to ``shape`` (the target's pixel dimensions) using
         ``skimage.transform.resize`` with ``anti_aliasing=False``
         (scaling up, no aliasing concern).
      5. Cast back to ``dtype``.

    Errors:
      ``RuntimeError`` -- ``pick.position`` is None (pre-`position`
      NPZ reload -- the source overview tile can't be identified).
      Per-tile, never ``NonSimulatorFrameError``.

      ``OSError`` / ``FileNotFoundError`` -- source overview file
      missing on disk. Per-tile data integrity issue -- caller
      records as a hijack failure and the loop continues.
    """
    # Construction is always safe -- failures (missing `position`,
    # missing overview file) surface at call time, where the existing
    # per-pick try/except in acquire_targets handles them uniformly.
    # Capture pick attributes that the closure needs; resolve the
    # overview path lazily so a None `position` raises a clear
    # RuntimeError on call rather than an opaque NoneType-in-int()
    # error here.
    px_tg = float(target_pixel_size_um)

    def _target_mock(shape, dtype, *, naming):
        # naming is ignored -- documented in the function docstring
        # above. The content source is entirely the closed-over pick.
        del naming
        if pick.position is None:
            raise RuntimeError(
                "build_target_provider: pick.position is None -- the "
                "source overview tile index is missing (likely a "
                "pre-`position` NPZ reload). Target mock cannot be "
                "derived without it."
            )

        # Resolve overview file path from the pick's lineage.
        overview_naming = Naming(
            acquisition_type="overview-scan",
            hash6=layout.hash6,
            g=int(pick.pick_id[0]),
            p=int(pick.position),
        )
        overview_path = (
            layout.data_dir("overview-scan")
            / build_image_name(overview_naming)
        )

        # Lazy: tifffile + skimage.transform are both lazy-imported so
        # the cost is paid only when simulation mode actually fires.
        import tifffile
        from skimage.transform import resize

        overview = tifffile.imread(overview_path)
        # Shared geometry helper: same crop math as visualize.py's
        # centre panel -- structurally enforces "what the operator
        # sees in the Overview-crop panel matches what's in the saved
        # target file." See workflow/_geom.py. Helper also enforces
        # the 2-D-overview scope boundary (raises ValueError on
        # ndim != 2 -- per-tile failure, not run-fatal).
        crop = crop_overview_at_target_fov(
            overview,
            centroid_col_row_px=pick.centroid_col_row_px,
            # Scalar pixel size (col-axis) -- rest of the pipeline
            # treats it the same. See plan §"Pixel-size model".
            source_pixel_size_um=float(pick.source_pixel_size_um[0]),
            target_shape_px=(int(shape[0]), int(shape[1])),
            target_pixel_size_um=px_tg,
        )

        # Resample to target dimensions (zoom up). order=0 -- nearest-
        # neighbour, NOT bilinear. The file shape matches what a real
        # high-mag acquisition would produce (so the OME envelope,
        # downstream consumers, and Step 5 visualization see the
        # right shape), but each (target_pixel_size / source_pixel_size)-
        # sized block carries the same value as one overview pixel.
        # Visually-blocky pixels in the target file honestly signal
        # "the simulator added no information at the target step --
        # this is the overview's pixels stretched to the target's
        # pixel count, not new measurements."
        #
        # Bilinear here was the dishonest choice: it produced visually-
        # smooth target pixels that misrepresented the information
        # content as if it were a real high-res capture. See the
        # operator's "image quality must reflect actual resolution"
        # directive. The long-term clean answer for a realistic
        # simulator is a synthetic high-res specimen scene that both
        # overview and target sample from at their own pixel sizes
        # (not derive-from-overview); until then nearest is the
        # honest fix.
        #
        # anti_aliasing=False because we're scaling up (the kwarg is
        # a no-op for order=0 but documents intent for any future
        # downscale path).
        # preserve_range=True keeps intensity values in their original
        # numeric range rather than skimage's default [0, 1].
        mock = resize(
            crop, (int(shape[0]), int(shape[1])),
            order=0,
            preserve_range=True, anti_aliasing=False,
        )
        return mock.astype(dtype)

    return _target_mock
