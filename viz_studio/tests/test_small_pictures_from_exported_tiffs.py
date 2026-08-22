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
    and draw, and the TIFFs it came from weigh tens of gigabytes. Each small
    picture is a few kilobytes, so the whole scan is a folder of about a
    hundred megabytes.

    The bound below is loose on purpose. It is not trying to pin down the exact
    size of a JPEG, which depends on how busy the sample is; it is there to
    catch somebody quietly raising the size of a field and turning that
    hundred-megabyte folder into a four-hundred-megabyte one without noticing.
    """
    exported = tmp_path / "exported"
    _export_a_plane(exported, "P0001", size=512, um_per_pixel=0.25)
    note = make_small_pictures(exported, {"P0001": (0.0, 0.0)}, tmp_path / "small")

    picture = (tmp_path / "small" / note["tiles"][0]["src"]).read_bytes()
    assert picture[:3] == b"\xff\xd8\xff", "not a JPEG"
    assert len(picture) < 20_000, (
        f"a field's picture is {len(picture)} bytes; ten thousand of those would be "
        f"{len(picture) * 10_000 / 1e6:.0f} MB, which is more than a scan folder should weigh"
    )

    # Ten thousand of those is a couple of hundred megabytes at the very most,
    # against the tens of gigabytes the TIFFs weigh. That is the point.
    assert len(picture) * 10_000 < 200_000_000

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


def _export_a_flat_field(folder: Path, label: str, value: int, *, size: int = 64) -> None:
    """One field of a single, known brightness, so brightness can be reasoned about."""
    folder.mkdir(parents=True, exist_ok=True)
    described = (
        '<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2016-06">'
        f'<Image><Pixels DimensionOrder="XYCZT" Type="uint16" SizeX="{size}" SizeY="{size}" '
        'SizeC="1" SizeZ="1" SizeT="1" PhysicalSizeX="1.0" PhysicalSizeY="1.0"/></Image></OME>'
    )
    tifffile.imwrite(
        folder / f"overview_a1b2c3_{label}_T000000_C00_Z00000.ome.tiff",
        np.full((size, size), value, dtype=np.uint16),
        description=described,
    )


def test_a_dim_field_stays_dimmer_than_a_bright_one(tmp_path):
    """The whole scan is brightened the same way, so fields can be compared.

    This is the mistake that makes a scan read like a chessboard. If each field
    were brightened over its own range, an empty field would have its faint
    background stretched until it filled the grey scale and came out *bright*,
    while a field holding brilliant cells would have everything but those cells
    squashed to black. The scan would say the opposite of the truth, and an
    operator would go looking in exactly the wrong places.
    """
    exported = tmp_path / "exported"
    _export_a_flat_field(exported, "P0001", 300)     # nearly empty
    _export_a_flat_field(exported, "P0002", 8000)    # plenty of signal
    _export_a_flat_field(exported, "P0003", 20000)   # more still

    note = make_small_pictures(
        exported,
        {"P0001": (0.0, 0.0), "P0002": (64.0, 0.0), "P0003": (128.0, 0.0)},
        tmp_path / "small",
    )
    by_label = {t["label"]: t for t in note["tiles"]}
    assert by_label["P0001"]["grey"] < by_label["P0002"]["grey"] < by_label["P0003"]["grey"], (
        "brighter fields must read brighter — each field brightened over its own "
        "range would put them in the wrong order"
    )

    from PIL import Image

    seen = {}
    for label in by_label:
        with Image.open(tmp_path / "small" / f"{label}.jpg") as picture:
            seen[label] = float(np.asarray(picture.convert("L"), dtype=np.float32).mean())
    assert seen["P0001"] < seen["P0002"] < seen["P0003"], (
        "the pictures themselves must be in the same order as their summary colours"
    )
    assert seen["P0001"] < 60, "a nearly empty field should still look nearly empty"


def test_the_summary_colour_is_what_the_field_looks_like_from_far_away(tmp_path):
    """Nothing should visibly change when a field's real picture arrives.

    Zoomed out, a field is drawn as the one colour its note gives for it; zoom
    in a little and the real picture is fetched and drawn instead. If those two
    disagree the scan lurches as pictures land, and an operator reads that as a
    fault even though every field is in its right place. So the colour is the
    field's own average, which is exactly what a picture shrunk to a few pixels
    looks like.
    """
    from PIL import Image

    exported = tmp_path / "exported"
    for index, label in enumerate(["P0001", "P0002", "P0003", "P0004"]):
        _export_a_plane(exported, label, size=128, seed=index)
    places = {f"P{n:04d}": (float(n) * 64.0, 0.0) for n in range(1, 5)}

    note = make_small_pictures(exported, places, tmp_path / "small")
    for tile in note["tiles"]:
        with Image.open(tmp_path / "small" / tile["src"]) as picture:
            average = float(np.asarray(picture.convert("L"), dtype=np.float32).mean())
        assert abs(average - tile["grey"]) <= 3, (
            f"{tile['label']}: the colour standing for the field is {tile['grey']} but the "
            f"picture averages {average:.1f}, so the scan would change as it arrives"
        )


def test_the_note_says_how_the_scan_was_brightened(tmp_path):
    """Whoever looks at these later should be able to see what was done to them.

    These are display copies, and every one of them has been stretched and
    lifted to make it legible. Saying so beside the pictures is what keeps
    somebody from mistaking them for measurements later on.
    """
    exported = tmp_path / "exported"
    _export_a_flat_field(exported, "P0001", 500)
    _export_a_flat_field(exported, "P0002", 9000)

    note = make_small_pictures(
        exported, {"P0001": (0.0, 0.0), "P0002": (64.0, 0.0)}, tmp_path / "small"
    )
    low, high = note["brightened_between"]
    assert low < high
    assert 0.0 < note["dim_end_lifted_by"] <= 1.0
    assert "display only" in note["made_for"]
