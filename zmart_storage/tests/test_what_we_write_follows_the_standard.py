"""Check what this writer produces against the OME-Zarr standard's own rules.

Every other test here asks whether the pictures come out right. This one asks a
different question: whether what we write is a *proper* OME-Zarr image, so that
somebody else's software — Fiji, napari, a colleague's script, a public archive —
can open it without knowing anything about this project.

That matters more than it might seem. A store that only our own viewer can read is
a store your data is trapped in. And the failure is quiet: a missing field breaks
nothing here and turns up months later on somebody else's machine.

**The rules below are transcribed from the specification, not from this code.**
They were taken from the OME-NGFF specification source (the ``ome/ngff``
repository, ``latest/index.bs``), and each check names the rule it is enforcing so
that a reader can look it up rather than take this file's word for it. Writing the
rules out by hand is the point — a test that asked the writer what it does would
agree with the writer no matter what either of them did.

The standard marks its rules as MUST or SHOULD. Both are checked here, and both
are treated as required by this project: a SHOULD we choose to ignore should be an
argued exception with a comment, not a silent omission nobody noticed.

Two names that are easy to tangle, since this file is where they meet. **Zarr** is
the general way of keeping a large array as many small files, and it knows nothing
about microscopes. **OME-Zarr** is that, plus an agreed description of what the
axes mean, how large a voxel is, and where the picture sits on the stage. The two
generations run in step: OME-Zarr 0.4 is written on zarr version 2, and OME-Zarr
0.5 on zarr version 3. Both are checked, because this writer produces both.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from zmart_storage.canvas import Channel, TileCanvases

# The unit names the standard lists as acceptable, which are the UDUNITS-2 names.
# Only the ones a light microscope plausibly uses are written out; a unit outside
# this set is not necessarily wrong, but it is worth a test failing over, because
# the usual cause is a spelling such as "um" or "micron" that other software will
# not recognise.
SPACE_UNITS = {
    "angstrom", "nanometer", "micrometer", "millimeter", "centimeter", "meter",
}
TIME_UNITS = {
    "nanosecond", "microsecond", "millisecond", "second", "minute", "hour", "day",
}


def _the_description_of(store: Path) -> tuple[dict, str]:
    """The OME description inside a store, and which generation wrote it.

    0.5 keeps it in ``zarr.json`` under an ``ome`` key; 0.4 keeps it in a
    ``.zattrs`` file beside the image. Read here rather than through a library so
    that the test sees exactly what was written to disk.
    """
    newer = store / "zarr.json"
    if newer.is_file():
        held = json.loads(newer.read_text(encoding="utf-8"))
        attributes = held.get("attributes") or {}
        return (attributes.get("ome") or attributes), "0.5"
    return json.loads((store / ".zattrs").read_text(encoding="utf-8")), "0.4"


def _the_array_description_at(level: Path) -> dict:
    """How one level of the image is stored, read straight off disk."""
    for name in ("zarr.json", ".zarray"):
        held = level / name
        if held.is_file():
            return json.loads(held.read_text(encoding="utf-8"))
    raise AssertionError(f"{level} holds no array description")


@pytest.fixture(params=["0.4", "0.5"])
def a_written_image(request, tmp_path) -> tuple[Path, str]:
    """A small but complete acquisition, written in one generation of the format.

    Given more than one moment, more than one colour, and a corner away from the
    origin on purpose: a picture written at nought would let a mistake that lost
    the corner entirely still look right.
    """
    generation = request.param
    folder = tmp_path / generation.replace(".", "_")
    canvas = TileCanvases.create(
        folder,
        name="overview",
        canvas_shape=(4, 256, 256),
        tile_shape=(4, 64, 64),
        tile_step=(4, 64, 64),
        voxel_size_um=(2.0, 0.35, 0.35),
        origin_um=(11.0, 5.5, 7.25),
        channels=[Channel("488", window=(0, 4000)),
                  Channel("561", window=(0, 3000))],
        frames=2,
        chunk=32,
        ome_zarr_version=generation,
    )
    canvas.write(np.full((4, 64, 64), 1200, "uint16"),
                 origin=(0, 0, 0), channel=0, frame=0)
    canvas.close()
    return folder / "overview.ome.zarr", generation


def test_the_version_is_stated_where_the_standard_puts_it(a_written_image):
    """0.5 moved the version into the ``ome`` namespace, and 0.4 keeps it inside
    the multiscale. A reader uses it to decide how to read everything else, so a
    version in the wrong place means the store cannot be interpreted at all.
    """
    store, generation = a_written_image
    described, found = _the_description_of(store)
    assert found == generation
    if generation == "0.5":
        assert described.get("version") == "0.5"
    else:
        assert described["multiscales"][0].get("version") == "0.4"


def test_the_axes_are_named_typed_and_ordered_as_the_standard_requires(
        a_written_image):
    """The axes say what each dimension of the picture means.

    The standard is precise here: names MUST be unique, there MUST be two or three
    axes measuring distance, at most one moment axis and one colour axis, and they
    MUST come in the order moment, colour, distance. A reader relies on that order
    to know which dimension to put on the depth slider, so getting it wrong shows
    the specimen as a thin band rather than reporting anything.
    """
    store, _ = a_written_image
    described, _ = _the_description_of(store)
    axes = described["multiscales"][0]["axes"]

    names = [axis["name"] for axis in axes]
    assert len(names) == len(set(names)), "axis names must be unique"
    assert 2 <= len(axes) <= 5

    kinds = [axis.get("type") for axis in axes]
    assert kinds.count("space") in (2, 3)
    assert kinds.count("time") <= 1
    assert kinds.count("channel") <= 1

    where = {"time": 0, "channel": 1, "space": 2}
    ranked = [where.get(kind, 1) for kind in kinds]
    assert ranked == sorted(ranked), (
        f"axes must run time, then channel, then space; got {kinds}")

    # The units have to be names other software recognises. "um" and "micron" are
    # the usual near-misses and both would be silently ignored elsewhere.
    for axis in axes:
        if axis.get("type") == "space":
            assert axis.get("unit") in SPACE_UNITS
        if axis.get("type") == "time":
            assert axis.get("unit") in TIME_UNITS


def test_every_level_is_described_and_placed(a_written_image):
    """Each copy of the picture says where it is and how large its voxels are.

    The rules checked here are the ones that decide whether the specimen lands in
    the right place: exactly one scale for each level, at most one translation,
    and the translation written *after* the scale, because the standard says the
    offset is given in physical units and reading them the other way round moves
    the picture by the size of the run. The levels must also be listed largest
    first, since a reader trusts the order rather than measuring.
    """
    store, generation = a_written_image
    described, _ = _the_description_of(store)
    multiscale = described["multiscales"][0]
    axes = multiscale["axes"]
    datasets = multiscale["datasets"]
    assert datasets, "an image must say what copies it holds"

    widths = []
    for at, dataset in enumerate(datasets):
        assert "path" in dataset
        array = _the_array_description_at(store / str(dataset["path"]))
        widths.append(array["shape"][-1])
        assert len(array["shape"]) == len(axes), (
            "the number of axes must match the number of dimensions")

        moves = dataset["coordinateTransformations"]
        kinds = [move["type"] for move in moves]
        assert kinds.count("scale") == 1, f"level {at} needs exactly one scale"
        assert kinds.count("translation") <= 1
        if "translation" in kinds:
            assert kinds.index("translation") > kinds.index("scale"), (
                "a translation must be listed after the scale it follows")
        for move in moves:
            assert len(move[move["type"]]) == len(axes)

        if generation == "0.5":
            # Required only by the newer generation, which is the only one with
            # anywhere to put it. It lets a reader open one level on its own and
            # still know which dimension is depth and which is time.
            assert array.get("dimension_names") == [a["name"] for a in axes], (
                f"level {at} must name its dimensions the way the axes do")

    assert widths == sorted(widths, reverse=True), (
        "the copies must be listed largest first")


def test_the_image_says_how_its_smaller_copies_were_made(a_written_image):
    """The standard asks for this, and here it is load-bearing rather than polite.

    The copies are made by keeping every second voxel, not by averaging groups of
    them. Somebody reading the data deserves to know: a zoomed-out picture is a
    sample of the specimen rather than a smoothed version, so a faint object lying
    between two kept rows can vanish as you zoom out, and a bright speck survives
    at every zoom instead of fading.

    It is also the fact the whole no-copying arrangement rests on. Because each
    coarse voxel comes from exactly one fine voxel, a position's own zoomed-out
    copies are already the right answer for that part of the picture, so a view can
    point at them rather than storing a second set.
    """
    store, _ = a_written_image
    described, _ = _the_description_of(store)
    multiscale = described["multiscales"][0]

    assert multiscale.get("name")
    assert multiscale.get("type") == "nearest", (
        "the copies are subsampled rather than averaged, and the image has to say "
        "so — a reader that assumed averaging would trust a zoomed-out picture "
        "more than it should"
    )
    assert multiscale.get("metadata"), (
        "the standard asks for a note about how the copies were made")


def test_the_colours_are_described_the_way_a_reader_expects(a_written_image):
    """A channel needs a colour and a display window, and both have exact shapes.

    The window is the part worth being careful about. ``min`` and ``max`` are the
    camera's whole range; ``start`` and ``end`` are the brightness the run asks to
    be shown between. All four are required, and a reader that opens an
    acquisition on ``min`` and ``max`` shows a nearly black picture that stays that
    way until somebody drags a slider — which is why the distinction is worth a
    test rather than a comment.
    """
    store, _ = a_written_image
    described, _ = _the_description_of(store)
    channels = described["omero"]["channels"]
    assert len(channels) == 2

    for channel in channels:
        colour = channel["color"]
        assert len(colour) == 6 and all(
            digit in "0123456789abcdefABCDEF" for digit in colour), (
            f"a channel's colour must be six hexadecimal digits, got {colour!r}")
        window = channel["window"]
        for named in ("min", "max", "start", "end"):
            assert named in window, f"a channel's window must state {named}"
        assert window["start"] <= window["end"]
        assert window["min"] <= window["start"]
        assert window["end"] <= window["max"]


def test_the_corner_is_stated_once_rather_than_twice(a_written_image):
    """Where the picture sits must not be applied two times over.

    The standard allows an offset on each level and another on the image as a
    whole, and says the second is applied *after* the first. Writing the same
    offset in both places would therefore put the specimen at twice its distance
    from the origin — a mistake that looks entirely reasonable in the file and is
    only visible when two acquisitions fail to line up.
    """
    store, _ = a_written_image
    described, _ = _the_description_of(store)
    multiscale = described["multiscales"][0]

    for_the_whole_image = multiscale.get("coordinateTransformations") or []
    moved_overall = [one for one in for_the_whole_image
                     if one["type"] == "translation"]
    for dataset in multiscale["datasets"]:
        moved_here = [one for one in dataset["coordinateTransformations"]
                      if one["type"] == "translation"]
        assert not (moved_overall and moved_here), (
            "the corner is written both on this level and on the image as a "
            "whole, so it would be applied twice and the picture would sit at "
            "double the distance from the origin"
        )
