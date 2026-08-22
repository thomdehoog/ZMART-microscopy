"""Making the small JPEGs a scan of ten thousand fields can actually be drawn from.

No microscope here, so the exported files are written by hand in exactly the
shape the Leica driver writes them: one plane per file, everything flat, the
channel and depth in the name, and the size of a pixel in the description.
That is the whole of what comes off a microscope, and it is deliberately all
these tests give the helper.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
tifffile = pytest.importorskip("tifffile")
pytest.importorskip("PIL")

from viz_studio.backend.jpeg_tiles import (  # noqa: E402
    group_by_field,
    make_small_pictures,
    pixel_size_um,
    read_planes,
)


def _export_a_plane(folder: Path, label: str, *, c: int = 0, z: int = 0, t: int = 0,
                    size: int = 128, um_per_pixel: float = 0.5, seed: int = 0) -> Path:
    """Write one plane the way the microscope exports it."""
    folder.mkdir(parents=True, exist_ok=True)
    name = f"overview_a1b2c3_{label}_T{t:06d}_C{c:02d}_Z{z:05d}.ome.tiff"
    described = (
        '<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2016-06">'
        f'<Image><Pixels DimensionOrder="XYCZT" Type="uint16" SizeX="{size}" SizeY="{size}" '
        'SizeC="1" SizeZ="1" SizeT="1" '
        f'PhysicalSizeX="{um_per_pixel}" PhysicalSizeY="{um_per_pixel}"/></Image></OME>'
    )
    rng = np.random.default_rng(seed)
    frame = (rng.random((size, size)) * 3000).astype(np.uint16)
    frame[size // 2, size // 2] = 65535  # something unmistakable in the middle
    path = folder / name
    tifffile.imwrite(path, frame, description=described)
    return path


def test_the_exported_names_are_read_without_asking_the_driver(tmp_path):
    """A folder copied off a microscope is all there is to go on.

    The plane's colour, depth and moment are in its name, and reading them
    here rather than importing the vendor's package is what lets these files
    be looked at anywhere they have been copied to.
    """
    _export_a_plane(tmp_path, "P0001", c=0, z=0)
    _export_a_plane(tmp_path, "P0001", c=1, z=0)
    _export_a_plane(tmp_path, "P0002", c=0, z=3)
    (tmp_path / "acquisition.log").write_text("not a plane", encoding="utf-8")

    planes = read_planes(tmp_path)
    assert len(planes) == 3, "the log file should have been passed over, not refused"
    assert {p.label for p in planes} == {"P0001", "P0002"}
    assert sorted(p.c for p in planes if p.label == "P0001") == [0, 1]
    assert next(p for p in planes if p.label == "P0002").z == 3

    fields = group_by_field(planes)
    assert sorted(fields) == ["P0001", "P0002"]
    assert len(fields["P0001"]) == 2, "both colours belong to the one field"


def test_the_size_of_a_pixel_comes_from_the_file_itself(tmp_path):
    """It is the one thing an exported TIFF really does say about the world."""
    path = _export_a_plane(tmp_path, "P0001", um_per_pixel=0.325)
    assert pixel_size_um(path) == pytest.approx(0.325)


def test_a_field_with_no_stated_place_is_left_out_and_named(tmp_path):
    """A TIFF does not say where it was taken, so a guess would be a fiction.

    This is invisible on one field and ruinous on two: a scan taken from the
    stage's zero lands correctly whether or not anybody read a position, and
    the second scan then appears at the first one's corner. So a field whose
    place nobody stated is left undrawn and reported, never placed somewhere
    invented.
    """
    exported = tmp_path / "exported"
    _export_a_plane(exported, "P0001")
    _export_a_plane(exported, "P0002")

    note = make_small_pictures(
        exported, {"P0001": (0.0, 0.0)}, tmp_path / "small"
    )
    assert [t["label"] for t in note["tiles"]] == ["P0001"]
    assert note["fields_with_no_stated_place"] == ["P0002"]
    assert not (tmp_path / "small" / "P0002.jpg").exists()


def test_each_field_becomes_one_small_picture_in_its_place(tmp_path):
    """The note beside the pictures is everything a viewer needs to draw them.

    A viewer that had to open a TIFF to find out where a picture belongs would
    be back to reading ten thousand large files, which is the whole thing this
    exists to avoid.
    """
    exported = tmp_path / "exported"
    for index, label in enumerate(["P0001", "P0002", "P0003", "P0004"]):
        _export_a_plane(exported, label, size=128, um_per_pixel=0.5, seed=index)

    places = {
        "P0001": (0.0, 0.0),
        "P0002": (64.0, 0.0),
        "P0003": (0.0, 64.0),
        "P0004": (64.0, 64.0),
    }
    small = tmp_path / "small"
    note = make_small_pictures(exported, places, small)

    assert len(note["tiles"]) == 4
    assert note["units"] == "um"
    # A 128 pixel field at half a micrometre a pixel is 64 micrometres across,
    # and the middle of the first one is the stage's zero.
    first = next(t for t in note["tiles"] if t["label"] == "P0001")
    assert (first["w"], first["h"]) == pytest.approx((64.0, 64.0))
    assert (first["x0"], first["y0"]) == pytest.approx((-32.0, -32.0))
    # Its neighbour sits exactly one field to the right, with no gap and no overlap.
    second = next(t for t in note["tiles"] if t["label"] == "P0002")
    assert second["x0"] == pytest.approx(first["x0"] + first["w"])

    # The note is written beside the pictures, so the folder is self-contained.
    written = json.loads((small / "tiles.json").read_text(encoding="utf-8"))
    assert written == note
    for tile in note["tiles"]:
        assert (small / tile["src"]).exists()


def test_the_pictures_are_small_enough_that_ten_thousand_is_workable(tmp_path):
    """This is the whole reason the helper exists.

    A scan of ten thousand fields has to become something a browser can hold
    and draw. Each small picture is a couple of kilobytes, so the whole scan
    is tens of megabytes rather than the tens of gigabytes the TIFFs weigh.
    """
    exported = tmp_path / "exported"
    _export_a_plane(exported, "P0001", size=512, um_per_pixel=0.25)
    note = make_small_pictures(exported, {"P0001": (0.0, 0.0)}, tmp_path / "small")

    picture = (tmp_path / "small" / note["tiles"][0]["src"]).read_bytes()
    assert picture[:3] == b"\xff\xd8\xff", "not a JPEG"
    assert len(picture) < 4_000, f"a field's picture is {len(picture)} bytes, too heavy at scale"

    # Ten thousand of those is a few tens of megabytes, which is the point.
    assert len(picture) * 10_000 < 60_000_000

    # The original is untouched: the real pixels are still where they were.
    original = tifffile.imread(exported / next(exported.iterdir()).name)
    assert original.dtype == np.uint16 and original.shape == (512, 512)


def test_everything_taken_at_one_place_shows_in_its_picture(tmp_path):
    """A cell seen in any colour or at any depth should be visible at a glance.

    The small picture is for finding things, so it shows the brightest of
    whatever was taken there rather than one channel of it. Anything that
    needs the channels apart wants the TIFFs, not this.
    """
    exported = tmp_path / "exported"
    # Two colours: the first dim everywhere, the second holding the bright spot.
    dim = np.full((64, 64), 100, dtype=np.uint16)
    bright = np.full((64, 64), 100, dtype=np.uint16)
    bright[10, 10] = 60000
    described = (
        '<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2016-06">'
        '<Image><Pixels DimensionOrder="XYCZT" Type="uint16" SizeX="64" SizeY="64" '
        'SizeC="1" SizeZ="1" SizeT="1" PhysicalSizeX="1.0" PhysicalSizeY="1.0"/></Image></OME>'
    )
    exported.mkdir()
    tifffile.imwrite(
        exported / "overview_a1b2c3_P0001_T000000_C00_Z00000.ome.tiff", dim, description=described
    )
    tifffile.imwrite(
        exported / "overview_a1b2c3_P0001_T000000_C01_Z00000.ome.tiff",
        bright,
        description=described,
    )

    make_small_pictures(exported, {"P0001": (0.0, 0.0)}, tmp_path / "small", budget_px=64 * 64)

    from PIL import Image

    with Image.open(tmp_path / "small" / "P0001.jpg") as picture:
        seen = np.asarray(picture.convert("L"))
    assert seen.max() > 200, "the bright spot from the second colour never reached the picture"
