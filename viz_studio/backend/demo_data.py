"""Make a small pretend microscope volume you can explore without a microscope.

The visualization studio needs *something* to show. In the real workflow that
"something" is a stack of images that the microscope just acquired. For the
demo we conjure one up in software instead — a little three-dimensional,
three-colour volume with blob-like "cells" scattered through it — and save it
in exactly the on-disk shape (OME-Zarr) that the real acquisition writes. That
way the viewer, the controls, and the 3-D view all behave the way they will on
real data, and you can try everything from your laptop with no hardware
attached.

Why OME-Zarr? It is the standard chunked, multi-resolution format for large
microscopy images. "Chunked" means the volume is cut into many small files, so
the viewer only ever fetches the little pieces you are actually looking at.
"Multi-resolution" means we also save shrunk-down copies (a "pyramid"), so when
you are zoomed out the viewer shows a coarse copy instead of hauling every
pixel across. Together those are what make even enormous volumes feel light.

The three channels mirror the rest of ZMART's demo sample:

- ``structure`` — a general stain that fills every cell, your anatomical map.
- ``marker-a`` — lights up in some cells (a first biological marker).
- ``marker-b`` — lights up in a different, partly overlapping set of cells.

The pixel values follow the same convention as the 2-D simulation elsewhere in
the project: 16-bit integers, a small ``800`` background, and signal scaled up
by ``20000`` so the numbers land in a realistic microscope range.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np

# The three channels, in order, and the false colours the viewer will give
# them by default — chosen to read clearly when overlaid (white anatomy, then
# a green and a magenta marker), the same palette the rest of ZMART uses.
CHANNEL_NAMES = ("structure", "marker-a", "marker-b")
CHANNEL_COLORS = ("FFFFFF", "00FF66", "FF33FF")  # hex, no leading '#'

# A deliberately small demo volume so it generates instantly and the browser
# never strains. Shape is (channels, z-planes, height, width). Real volumes are
# far larger; nothing here changes when they grow — that is the whole point of
# the chunked, multi-resolution format.
_CHANNELS = len(CHANNEL_NAMES)
_DEPTH = 48
_HEIGHT = 320
_WIDTH = 320

# The physical size of one voxel (3-D pixel), in micrometres. Microscopes
# usually sample more coarsely along z (between planes) than within a plane, so
# the z spacing is larger. The viewer uses these numbers to show the volume
# with correct proportions instead of a squashed cube.
_VOXEL_UM = (2.0, 0.35, 0.35)  # (z, y, x) micrometres

_BACKGROUND = 800.0
_SIGNAL = 20000.0

# How many shrunk-down copies to save beyond full resolution. Three extra
# levels, each half the size of the last, is plenty for a volume this small and
# keeps the "zoomed-out shows a coarse copy" behaviour honest.
_PYRAMID_LEVELS = 3


def _seeded_cells(rng: np.random.Generator, count: int) -> np.ndarray:
    """Pick random 3-D centres for ``count`` blob-like cells, in voxel units."""
    z = rng.uniform(4, _DEPTH - 4, size=count)
    y = rng.uniform(12, _HEIGHT - 12, size=count)
    x = rng.uniform(12, _WIDTH - 12, size=count)
    return np.stack([z, y, x], axis=1)


def _paint_blobs(volume: np.ndarray, centres: np.ndarray, radius_um: float) -> None:
    """Add soft 3-D gaussian blobs at ``centres`` into ``volume`` (in place).

    Each cell is drawn as a fuzzy ball whose brightness falls off smoothly from
    the centre — a fair stand-in for how a real fluorescent cell looks once the
    microscope's optics have blurred it slightly. We convert the physical blob
    radius (in micrometres) into voxels separately for each axis, because the z
    spacing differs from x and y.
    """
    rz, ry, rx = (radius_um / vx for vx in _VOXEL_UM)
    zz, yy, xx = np.ogrid[0 : volume.shape[0], 0 : volume.shape[1], 0 : volume.shape[2]]
    for cz, cy, cx in centres:
        dist2 = (
            ((zz - cz) / rz) ** 2
            + ((yy - cy) / ry) ** 2
            + ((xx - cx) / rx) ** 2
        )
        volume += np.exp(-0.5 * dist2)


def _build_volume(rng: np.random.Generator) -> np.ndarray:
    """Return the full-resolution (channels, z, y, x) uint16 demo volume.

    The ``structure`` channel fills a shared population of cells. The two marker
    channels each light up a random subset of those same cells, with a
    deliberate overlap — so some cells are single-positive and some are
    double-positive, exactly the kind of pattern the discovery and gating tools
    are meant to tease apart.
    """
    n_cells = 90
    cells = _seeded_cells(rng, n_cells)

    structure = np.zeros((_DEPTH, _HEIGHT, _WIDTH), dtype=np.float32)
    _paint_blobs(structure, cells, radius_um=6.0)

    # marker-a lights up ~55% of the cells; marker-b ~45%; their random subsets
    # overlap, giving a mix of single- and double-positive cells.
    a_mask = rng.random(n_cells) < 0.55
    b_mask = rng.random(n_cells) < 0.45
    marker_a = np.zeros_like(structure)
    marker_b = np.zeros_like(structure)
    _paint_blobs(marker_a, cells[a_mask], radius_um=5.0)
    _paint_blobs(marker_b, cells[b_mask], radius_um=5.0)

    stacked = np.stack([structure, marker_a, marker_b], axis=0)

    # Normalise each channel to 0..1, then map onto the microscope-like range:
    # a small constant background plus signal. Clip and store as 16-bit, which
    # is what real detectors produce.
    out = np.empty_like(stacked, dtype=np.uint16)
    for c in range(_CHANNELS):
        chan = stacked[c]
        peak = float(chan.max()) or 1.0
        scaled = _BACKGROUND + (chan / peak) * _SIGNAL
        out[c] = np.clip(scaled, 0, 65535).astype(np.uint16)
    return out


def _downsample(volume: np.ndarray) -> np.ndarray:
    """Halve a (channels, z, y, x) volume along z, y and x by block-averaging.

    This is how each rung of the resolution pyramid is built from the one above
    it: average each 2x2x2 block of voxels into one. Averaging (rather than just
    dropping voxels) keeps the coarse copy faithful instead of speckly.
    """
    c, z, y, x = volume.shape
    z2, y2, x2 = z // 2, y // 2, x // 2
    trimmed = volume[:, : z2 * 2, : y2 * 2, : x2 * 2].astype(np.float32)
    blocks = trimmed.reshape(c, z2, 2, y2, 2, x2, 2)
    return blocks.mean(axis=(2, 4, 6)).astype(np.uint16)


def _multiscales_metadata(n_levels: int) -> dict:
    """Build the OME-Zarr ``multiscales`` description of the pyramid.

    This is the little manifest the viewer reads to understand the volume: what
    the axes mean (a channel axis plus three spatial axes), what physical size
    each voxel is at every resolution level, and where each level lives on disk
    (the folders ``0``, ``1``, ...). We follow the widely-supported NGFF v0.4
    layout, which is the flavour neuroglancer reads most reliably.
    """
    axes = [
        {"name": "c", "type": "channel"},
        {"name": "z", "type": "space", "unit": "micrometer"},
        {"name": "y", "type": "space", "unit": "micrometer"},
        {"name": "x", "type": "space", "unit": "micrometer"},
    ]
    datasets = []
    for level in range(n_levels):
        factor = 2**level
        vz, vy, vx = _VOXEL_UM
        datasets.append(
            {
                "path": str(level),
                "coordinateTransformations": [
                    {
                        "type": "scale",
                        # No scaling on the channel axis; spatial axes grow by
                        # the level's downsample factor.
                        "scale": [1.0, vz * factor, vy * factor, vx * factor],
                    }
                ],
            }
        )
    return {
        "version": "0.4",
        "axes": axes,
        "datasets": datasets,
        "name": "zmart-demo-volume",
    }


def _omero_metadata() -> dict:
    """Per-channel display hints (names, colours, starting brightness window).

    OME-Zarr carries an optional ``omero`` block describing how each channel
    should first appear — its name, false colour, and the intensity window to
    stretch across. The viewer uses these so the demo opens already looking
    sensible instead of flat grey.
    """
    channels = []
    for name, color in zip(CHANNEL_NAMES, CHANNEL_COLORS):
        channels.append(
            {
                "label": name,
                "color": color,
                "active": True,
                "window": {
                    "min": 0.0,
                    "max": 65535.0,
                    "start": _BACKGROUND,
                    "end": _BACKGROUND + _SIGNAL,
                },
            }
        )
    return {"channels": channels, "rdefs": {"model": "color"}}


def write_demo_zarr(path: str | Path, *, seed: int = 7, overwrite: bool = True) -> Path:
    """Generate the demo volume and save it as an OME-Zarr store at ``path``.

    Call this once before starting the viewer. It writes a full-resolution
    volume plus a few shrunk-down copies, together with the small metadata files
    that tell the viewer how to read it. Returns the path to the store.

    Parameters
    ----------
    path:
        Where to create the ``.zarr`` store (a folder, not a single file).
    seed:
        Fixes the random cell layout so the demo looks the same every run.
    overwrite:
        Replace any existing store at ``path``. On by default so re-running the
        demo always starts clean.
    """
    import zarr

    path = Path(path)
    if path.exists() and overwrite:
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(seed)
    full = _build_volume(rng)

    # Build the pyramid: level 0 is full resolution, each further level halves
    # it, stopping before the volume gets uselessly tiny.
    levels = [full]
    for _ in range(_PYRAMID_LEVELS):
        smaller = _downsample(levels[-1])
        if min(smaller.shape[1:]) < 8:
            break
        levels.append(smaller)

    # Write a zarr v2 group with one array per pyramid level. Chunking one z
    # plane of one channel per file keeps each fetched piece small.
    group = zarr.open_group(str(path), mode="w", zarr_format=2)
    for level, vol in enumerate(levels):
        c, z, y, x = vol.shape
        arr = group.create_array(
            str(level),
            shape=vol.shape,
            chunks=(1, 1, min(y, 256), min(x, 256)),
            dtype="uint16",
        )
        arr[:] = vol

    # The OME-Zarr metadata lives in the group's ``.zattrs``. zarr-python does
    # not know about OME-Zarr, so we attach the standard blocks ourselves.
    attrs = {
        "multiscales": [_multiscales_metadata(len(levels))],
        "omero": _omero_metadata(),
    }
    (path / ".zattrs").write_text(json.dumps(attrs, indent=1), encoding="utf-8")

    return path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Write the demo OME-Zarr volume.")
    parser.add_argument(
        "path",
        nargs="?",
        default="viz_studio/backend/demo_store/demo.zarr",
        help="Where to write the .zarr store.",
    )
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    out = write_demo_zarr(args.path, seed=args.seed)
    print(f"wrote demo volume to {out}")
