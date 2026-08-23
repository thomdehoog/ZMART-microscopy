"""Make deliberately awkward OME-Zarr stores, to find where the viewer breaks.

Real data does not arrive in the demo's tidy shape. It arrives with a time
axis of one, with no pyramid at all, as eight-bit or floating-point numbers,
with a channel axis holding a single channel, flat with no depth, wrapped in
a bare group, as a plate with holes in it, or under a filename with spaces
in it. The viewer's promise is to figure these out rather than refuse them
(the operator's rule, 2026-08-23) — and a promise is only worth what tests
it, so this writes one small store per awkwardness, in both format versions
where the awkwardness allows.

Run it with::

    python make_awkward_stores.py

The stores land in ``test_stores/awkward/``. Each is tiny — the point is
the shape, not the pixels. The companion sweep (``sweep_awkward_stores.py``
beside this file) opens every one through the server's own doors and
reports which of them break.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np

from make_test_stores import _SCALE, _dress_the_channels, _tiny_volume

_HERE = Path(__file__).resolve().parent
_AWKWARD = _HERE / "test_stores" / "awkward"


def _write(path: Path, data, dims, version: str, *, scale=None,
           scale_factors=(2,), dressed: bool = False) -> None:
    """One store, written the ordinary way and optionally dressed."""
    import ngff_zarr

    scale = scale or {axis: _SCALE.get(axis, 1.0) for axis in dims
                      if axis in ("z", "y", "x")}
    image = ngff_zarr.to_ngff_image(data, dims=dims, scale=scale)
    multiscales = ngff_zarr.to_multiscales(image,
                                           scale_factors=list(scale_factors))
    ngff_zarr.to_ngff_zarr(str(path), multiscales, version=version,
                           overwrite=True)
    if dressed:
        _dress_the_channels(path, version)


def main() -> None:
    if _AWKWARD.exists():
        shutil.rmtree(_AWKWARD)
    _AWKWARD.mkdir(parents=True)

    volume = _tiny_volume(41)          # (2, 4, 64, 64): c, z, y, x
    plane = volume[:, :1]              # one z
    lone = volume[:1]                  # one channel, axis kept
    flat = volume[0, 0]                # y, x only

    for version in ("0.4", "0.5"):
        v = version.replace(".", "")
        # A timelapse axis holding a single moment: t is there, and t is 1.
        _write(_AWKWARD / f"t_of_one_v{v}.zarr", volume[None],
               ("t", "c", "z", "y", "x"), version)
        # No pyramid at all: one level is a legal image.
        _write(_AWKWARD / f"no_pyramid_v{v}.zarr", volume,
               ("c", "z", "y", "x"), version, scale_factors=())
        # A channel axis holding a single channel (the demo drops the axis
        # instead; both spellings occur in the wild).
        _write(_AWKWARD / f"one_channel_kept_axis_v{v}.zarr", lone,
               ("c", "z", "y", "x"), version)
        # One plane of depth under a full channel axis. Written without a
        # pyramid: the downsampler cannot halve a one-deep axis, which is
        # itself the awkwardness worth keeping.
        _write(_AWKWARD / f"one_plane_v{v}.zarr", plane,
               ("c", "z", "y", "x"), version, scale_factors=(), dressed=True)
        # No depth and no channels: a plain flat picture.
        _write(_AWKWARD / f"flat_v{v}.zarr", flat, ("y", "x"), version)
        # Eight-bit and floating-point numbers.
        _write(_AWKWARD / f"uint8_v{v}.zarr", (volume // 256).astype("uint8"),
               ("c", "z", "y", "x"), version)
        _write(_AWKWARD / f"float32_v{v}.zarr",
               (volume.astype("float32") / 65535.0),
               ("c", "z", "y", "x"), version)

    # Undressed several-channel store: no omero anywhere, which is what the
    # never-only-white rule exists for.
    _write(_AWKWARD / "undressed_v04.zarr", volume, ("c", "z", "y", "x"),
           "0.4")

    # A bare group wrapping one image — the wrapper itself declares nothing.
    wrapper = _AWKWARD / "wrapped_group"
    wrapper.mkdir()
    _write(wrapper / "inner.zarr", volume, ("c", "z", "y", "x"), "0.4",
           dressed=True)

    # Names the file system allows and code forgets: spaces and unicode.
    _write(_AWKWARD / "awkward name with spaces.zarr", volume,
           ("c", "z", "y", "x"), "0.4", dressed=True)
    _write(_AWKWARD / "münster_ω.zarr", volume, ("c", "z", "y", "x"), "0.4",
           dressed=True)

    made = sorted(p.name for p in _AWKWARD.iterdir())
    print(f"{len(made)} awkward stores in {_AWKWARD}:")
    for name in made:
        print(" ", name)


if __name__ == "__main__":
    main()
