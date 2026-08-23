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
- ``test_grid/`` — a **raw run**: a folder of four position stores laid out
  two by two, each carrying its own stage offset, overlapping their
  neighbours the way a survey's tiles do. This is the shape the build door
  links into one picture and the sequential door replays position by
  position.

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


def _tiny_volume(seed: int, shape: tuple[int, int, int, int] = _SHAPE) -> np.ndarray:
    """A small two-channel volume with a few soft blobs, different per seed."""
    rng = np.random.default_rng(seed)
    channels, planes, height, width = shape
    z, y, x = np.meshgrid(
        np.arange(planes), np.arange(height), np.arange(width), indexing="ij"
    )
    volume = np.zeros(shape, dtype=np.float32)
    # A bigger canvas gets more blobs, and bigger ones, so every frame size
    # looks about as busy as the little default.
    grown = height / _SHAPE[2]
    for channel in range(channels):
        for _ in range(max(4, round(4 * grown**2))):
            cz, cy, cx = rng.uniform([0, 8, 8], [planes, height - 8, width - 8])
            spread = rng.uniform(3, 7) * grown
            volume[channel] += np.exp(
                -(((z - cz) * 4) ** 2 + (y - cy) ** 2 + (x - cx) ** 2)
                / (2 * spread**2)
            )
    # Realistic counts: background around 800, blobs a few thousand.
    counts = 800 + volume * 8000 + rng.normal(0, 30, shape)
    return np.clip(counts, 0, 65535).astype(np.uint16)


def _dress_the_channels(path: Path, version: str) -> None:
    """Write the display dressing: each channel's name, colour and window.

    ngff-zarr writes the image's geometry but nothing about how it should
    first look, and undressed channels arrive white, on the camera's whole
    range — two of them summed to pure clipping on screen (seen 2026-08-23).
    The dressing is the small ``omero`` block: green and magenta, windows
    from the background to the brightest blob, exactly as a well-behaved
    acquisition writes for itself.
    """
    window = {"min": 0.0, "max": 65535.0, "start": 780.0, "end": 8800.0}
    omero = {
        "channels": [
            {"label": "marker-a", "color": "00FF66", "active": True,
             "window": dict(window)},
            {"label": "marker-b", "color": "FF33FF", "active": True,
             "window": dict(window)},
        ],
        "rdefs": {"model": "color"},
    }
    described = path / (".zattrs" if version == "0.4" else "zarr.json")
    attrs = json.loads(described.read_text(encoding="utf-8"))
    if version == "0.4":
        attrs["omero"] = omero
    else:
        attrs.setdefault("attributes", {}).setdefault("ome", {})["omero"] = omero
    described.write_text(json.dumps(attrs, indent=1), encoding="utf-8")


def _write_image(path: Path, version: str, seed: int) -> None:
    """Write one plain multiscale image store in the asked-for format version."""
    import ngff_zarr

    image = ngff_zarr.to_ngff_image(
        _tiny_volume(seed), dims=("c", "z", "y", "x"), scale=_SCALE
    )
    multiscales = ngff_zarr.to_multiscales(image, scale_factors=[2])
    ngff_zarr.to_ngff_zarr(str(path), multiscales, version=version, overwrite=True)
    _dress_the_channels(path, version)


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


def _write_grid(path: Path, seed: int) -> None:
    """Write a two-by-two raw run: four position stores, each knowing its place.

    Every position carries its own stage offset in its metadata — a
    translation, in micrometres — and steps 256 of its 320 pixels each way,
    so neighbouring positions overlap by a fifth, the way a survey's tiles
    do. That overlap is what lets the build door link them into one seamless
    picture, and the sequential door replay them through the live writer's
    own grid arithmetic. The frame is bigger than the other test stores'
    because the live planner needs the frame and the overlap to halve
    cleanly through its zero-copy pyramid with chunks worth reading — 320
    with 64 of overlap is the smallest comfortable pair, and it was chosen
    by asking the planner rather than guessing.
    """
    import ngff_zarr

    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    frame = (2, 4, 320, 320)
    step_px = 256  # of a 320-pixel frame: a fifth of overlap with each neighbour
    for row in range(2):
        for column in range(2):
            image = ngff_zarr.to_ngff_image(
                _tiny_volume(seed + row * 2 + column, frame),
                dims=("c", "z", "y", "x"),
                scale=_SCALE,
                translation={
                    "z": 0.0,
                    "y": row * step_px * _SCALE["y"],
                    "x": column * step_px * _SCALE["x"],
                },
            )
            multiscales = ngff_zarr.to_multiscales(image, scale_factors=[2])
            ngff_zarr.to_ngff_zarr(
                str(path / f"pos_{row}{column}.ome.zarr"), multiscales,
                version="0.4", overwrite=True,
            )
            _dress_the_channels(path / f"pos_{row}{column}.ome.zarr", "0.4")


def main() -> None:
    _STORES.mkdir(parents=True, exist_ok=True)
    _write_image(_STORES / "test_image_v04.zarr", "0.4", seed=11)
    _write_image(_STORES / "test_image_v05.zarr", "0.5", seed=11)
    _write_plate(_STORES / "test_plate_v04.zarr", "0.4", seed=21)
    _write_plate(_STORES / "test_plate_v05.zarr", "0.5", seed=21)
    _write_grid(_STORES / "test_grid", seed=31)

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
    corners = set()
    for position in sorted((_STORES / "test_grid").glob("*.ome.zarr")):
        opened = ngff_zarr.from_ngff_zarr(str(position))
        image = opened.images[0]
        assert image.data.shape == (2, 4, 320, 320), position.name
        corners.add((image.translation["y"], image.translation["x"]))
    assert len(corners) == 4, "every grid position should sit somewhere of its own"
    print(f"Five test stores written and re-read in {_STORES}")


if __name__ == "__main__":
    main()
