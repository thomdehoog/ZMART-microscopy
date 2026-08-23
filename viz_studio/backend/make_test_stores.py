"""Make a small family of test stores, one for each shape a store can take.

The demo volume (``demo_data.py``) covers the ordinary case: one image, three
channels, saved as OME-Zarr version 0.4. But stores arrive in more shapes than
that, and the viewer should open all of them. This script writes one small
store for each shape we want to keep working:

- ``test_image_v04.zarr`` — a plain image, format version 0.4 (the version
  most tools write today; stored as Zarr format 2).
- ``test_image_v05.zarr`` — the same image, format version 0.5 (the newer
  revision of the standard, stored as Zarr format 3). Same picture, different
  bones — opening both proves the viewer reads either.
- ``test_plate_v04.zarr`` — a **plate**: the layout a screening microscope
  writes, where one store holds a grid of wells (A/1, B/2, ...) and each well
  holds its own little image. Version 0.4.
- ``test_plate_v05.zarr`` — the same plate in version 0.5.

Every store is deliberately tiny — a few dozen kilobytes, two channels, a
handful of planes — because these exist to exercise the *opening* of each
shape, not to look impressive once open. Run it with::

    python make_test_stores.py

The stores land in ``test_stores/``, a sibling of the demo volume's folder —
deliberately NOT inside ``demo_store/`` itself, because the demo server
live-watches that folder for arriving acquisitions and would helpfully open
every test store on its own the moment it appeared (which is exactly what
happened on 2026-08-23). The load window reaches them one step up.

The pixel values follow the demo's convention: 16-bit integers, a background
of about 800 counts and blobs reaching a few thousand, so every store lands
in a realistic microscope range rather than a synthetic 0-to-1 one.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
_STORES = _HERE / "test_stores"

# Two channels are enough to see colour blending work; four planes are enough
# for the Z slider to have something to slide through.
_SHAPE = (2, 4, 64, 64)  # channel, z, y, x
_SCALE = {"z": 2.0, "y": 0.5, "x": 0.5}  # micrometres per pixel, anisotropic
                                         # like a real stack


def _tiny_volume(seed: int) -> np.ndarray:
    """A small two-channel volume with a few soft blobs, different per seed."""
    rng = np.random.default_rng(seed)
    channels, planes, height, width = _SHAPE
    z, y, x = np.meshgrid(
        np.arange(planes), np.arange(height), np.arange(width), indexing="ij"
    )
    volume = np.zeros(_SHAPE, dtype=np.float32)
    for channel in range(channels):
        for _ in range(4):
            cz, cy, cx = rng.uniform([0, 8, 8], [planes, height - 8, width - 8])
            spread = rng.uniform(3, 7)
            volume[channel] += np.exp(
                -(((z - cz) * 4) ** 2 + (y - cy) ** 2 + (x - cx) ** 2)
                / (2 * spread**2)
            )
    # Realistic counts: background around 800, blobs a few thousand.
    counts = 800 + volume * 8000 + rng.normal(0, 30, _SHAPE)
    return np.clip(counts, 0, 65535).astype(np.uint16)


def _write_image(path: Path, version: str, seed: int) -> None:
    """Write one plain multiscale image store in the asked-for format version."""
    import ngff_zarr

    image = ngff_zarr.to_ngff_image(
        _tiny_volume(seed), dims=("c", "z", "y", "x"), scale=_SCALE
    )
    multiscales = ngff_zarr.to_multiscales(image, scale_factors=[2])
    ngff_zarr.to_ngff_zarr(str(path), multiscales, version=version, overwrite=True)


def _write_plate(path: Path, version: str, seed: int) -> None:
    """Write a two-well plate, each well holding one small image.

    A plate is a store whose root only says which wells exist; the images live
    further down, one per well at ``<row>/<column>/<field>``. The well images
    are ordinary multiscale images (written by the same helper as above), and
    the plate and well descriptions around them are small JSON documents this
    function writes by hand — there is no plate writer in the library we use,
    and the documents are short enough that writing them plainly is clearer
    than depending on one.
    """
    import zarr

    if path.exists():
        shutil.rmtree(path)

    # Version 0.4 lives in Zarr format 2, where a group's description is a
    # ``.zattrs`` file; version 0.5 lives in Zarr format 3, where it is a
    # ``zarr.json`` with everything under an "ome" key.
    zarr_format = 2 if version == "0.4" else 3
    wells = [("A", "1"), ("B", "2")]

    plate_description = {
        "acquisitions": [{"id": 0}],
        "rows": [{"name": "A"}, {"name": "B"}],
        "columns": [{"name": "1"}, {"name": "2"}],
        "wells": [
            {"path": f"{row}/{column}", "rowIndex": index, "columnIndex": index}
            for index, (row, column) in enumerate(wells)
        ],
        "field_count": 1,
    }
    well_description = {"images": [{"path": "0", "acquisition": 0}]}

    root = zarr.create_group(str(path), zarr_format=zarr_format)
    if version == "0.4":
        plate_description["version"] = version
        root.attrs["plate"] = plate_description
    else:
        root.attrs["ome"] = {"version": version, "plate": plate_description}

    for index, (row, column) in enumerate(wells):
        well = root.create_group(f"{row}/{column}")
        if version == "0.4":
            well.attrs["well"] = {**well_description, "version": version}
        else:
            well.attrs["ome"] = {"version": version, "well": well_description}
        # The field image is written straight into its place in the plate,
        # a different seed per well so the wells are tellingly different.
        _write_image(path / row / column / "0", version, seed + index)


def main() -> None:
    _STORES.mkdir(parents=True, exist_ok=True)
    _write_image(_STORES / "test_image_v04.zarr", "0.4", seed=11)
    _write_image(_STORES / "test_image_v05.zarr", "0.5", seed=11)
    _write_plate(_STORES / "test_plate_v04.zarr", "0.4", seed=21)
    _write_plate(_STORES / "test_plate_v05.zarr", "0.5", seed=21)

    # The check that matters: somebody else's reader can open every store and
    # finds the shape we meant to write. A store that only our own code can
    # read would be exactly the kind of misunderstanding these exist to catch.
    import ngff_zarr

    for name in ("test_image_v04.zarr", "test_image_v05.zarr"):
        opened = ngff_zarr.from_ngff_zarr(str(_STORES / name))
        assert opened.images[0].data.shape == _SHAPE, name
    for name in ("test_plate_v04.zarr", "test_plate_v05.zarr"):
        for well in ("A/1", "B/2"):
            opened = ngff_zarr.from_ngff_zarr(str(_STORES / name / well / "0"))
            assert opened.images[0].data.shape == _SHAPE, f"{name}/{well}"
        plate_json = json.loads(
            (_STORES / name / ".zattrs").read_text()
            if (_STORES / name / ".zattrs").exists()
            else (_STORES / name / "zarr.json").read_text()
        )
        assert "plate" in json.dumps(plate_json), name
    print(f"Four test stores written and re-read in {_STORES}")


if __name__ == "__main__":
    main()
