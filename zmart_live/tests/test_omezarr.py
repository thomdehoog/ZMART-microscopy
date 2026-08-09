"""Is a live-written position really an image anybody else could open?

A run writes each position as a folder of numbers and nothing more. That folder
is not an image until somebody writes a description over it, and
:mod:`zmart_live.omezarr` is what writes it. This file asks whether the
description it writes is a *proper* one — the kind napari, Fiji, a colleague's
script or a public archive will accept without knowing anything about this
project.

It matters more than it might look. Everything about a run can be right — the
stage went where it was told, the camera exposed correctly, every voxel landed
on disk — and the run can still be one that nobody but us can open. The failure
is quiet: a missing line breaks nothing here and turns up months later on
somebody else's machine, usually the machine of the person who was hoping to
analyse the data.

**The rules checked below are transcribed from the specification, not read back
out of the writer.** They follow
``zmart_storage/tests/test_what_we_write_follows_the_standard.py``, which is
where this project first wrote them down, so that the two halves of the project
share one understanding of the format rather than two. A test that asked the
writer what it does would agree with the writer no matter what either of them
did.

Two names that are easy to tangle, since this is where they meet. **Zarr** is the
general way of keeping a large array as many small files, and it knows nothing
about microscopes. **OME-Zarr** is that, plus an agreed description of what the
axes mean, how large a voxel is, and where the picture sits on the stage. Only
OME-Zarr 0.5 is written here, which is the generation built on zarr version 3 and
keeps its description inside the image's own ``zarr.json``.

The last few tests hand the image to somebody else's reader instead of looking at
the file ourselves. That is a different question and worth asking separately: our
own code reading our own images proves little, because a misunderstanding shared
between the two halves cancels out and nothing ever looks wrong. Those tests skip
when the outside reader is not installed, and say so rather than quietly passing.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
import zarr

from zmart_live.identity import name_for_a_profile
from zmart_live.model import (
    AcquisitionProfile,
    GridCell,
    LevelGeometry,
    ZmartLiveError,
)
from zmart_live.omezarr import (
    OME_ZARR_VERSION,
    SPACE_UNITS,
    TIME_UNITS,
    describe_the_position,
    the_image_description,
)

# How the little acquisition below is set up. The numbers are chosen so that a
# mistake shows rather than hides.
#
# The depth of a voxel is much larger than its width, as it is on a real
# microscope, so an axis read back in the wrong order is obvious rather than
# plausible. The frame is small enough to keep the test quick and still divides
# into whole chunks, which is what a tiled run needs.
FRAME = 512
Z_PLANES = 2
CHUNK = 128
OVERLAP = 128
VOXEL_UM = (2.0, 0.35, 0.35)
MOMENTS = 2
COLOURS = ("488", "561")


def _a_profile() -> AcquisitionProfile:
    """Seal the way one ordinary tiled acquisition is written.

    The profile is built here by hand rather than asked for from
    :mod:`zmart_live.profiles`, so that these tests describe exactly the image
    they are checking and do not change meaning when the planner's preferences
    change. Everything about it is nevertheless ordinary: a square frame of a few
    hundred pixels, a quarter of it overlapping its neighbour, and three copies
    of the picture, each half the width and height of the one before it, with the
    depth never reduced.
    """
    profile = AcquisitionProfile(
        profile_id="overview-512-128",
        acquisition_type="overview",
        axes=("t", "c", "z", "y", "x"),
        frame_shape={"z": Z_PLANES, "y": FRAME, "x": FRAME},
        dtype="uint16",
        voxel_size={"z": VOXEL_UM[0], "y": VOXEL_UM[1], "x": VOXEL_UM[2]},
        voxel_unit="micrometer",
        overlap_pixels={"y": OVERLAP, "x": OVERLAP},
        channels=COLOURS,
        levels=tuple(
            LevelGeometry(
                level=step,
                downsampling={"z": 1, "y": 2**step, "x": 2**step},
                inner_chunk={"z": 1, "y": CHUNK, "x": CHUNK},
                # Only the full-size copy lines up with the grid step here, so it
                # is the only one a seamless view could point straight at. That
                # has nothing to do with the description being tested, but a
                # profile that claimed otherwise would be refused when it was
                # made.
                linkable=step == 0,
            )
            for step in range(3)
        ),
    )
    return replace(
        profile,
        profile_id=name_for_a_profile(profile, readable_prefix="overview-512-128"),
    )


def _write_the_copies(store: Path, profile, *, value: int = 0) -> None:
    """Put a position's pictures on disk the way a live run does, and no more.

    Deliberately only the arrays: a full-size copy in a folder called ``0``, a
    half-size one in ``1``, and so on. Nothing here says what the axes mean or
    where the picture sits, because that is exactly the state a position is in
    before :func:`zmart_live.omezarr.describe_the_position` runs, and it is the
    state the fault this file exists for left every position in.
    """
    store.mkdir(parents=True, exist_ok=True)
    for level in profile.levels:
        shrink = level.downsampling
        shape = (
            MOMENTS,
            len(COLOURS),
            max(1, Z_PLANES // shrink.get("z", 1)),
            max(1, FRAME // shrink.get("y", 1)),
            max(1, FRAME // shrink.get("x", 1)),
        )
        chunks = tuple(
            min(piece, size)
            for piece, size in zip(
                (1, 1, level.inner_chunk["z"], level.inner_chunk["y"], level.inner_chunk["x"]),
                shape,
                strict=True,
            )
        )
        array = zarr.create_array(
            store=str(store / str(level.level)),
            shape=shape,
            chunks=chunks,
            dtype=profile.dtype,
            zarr_format=3,
            overwrite=True,
        )
        if value:
            array[:] = value


# Where this position's first voxel sits, counted in full-resolution pixels from
# the corner of the run. None of the numbers is nought, on purpose: a position
# written at the origin would look right whether or not its corner was recorded
# at all, which is precisely the fault being guarded against.
CORNER_PIXELS = {"z": 0, "y": 384, "x": 768}


@pytest.fixture
def a_described_position(tmp_path):
    """One position, written and then described, exactly as a run would do it."""
    profile = _a_profile()
    store = tmp_path / "pos00007.ome.zarr"
    _write_the_copies(store, profile)
    describe_the_position(
        store,
        profile,
        name="pos00007",
        channels=COLOURS,
        origin_pixels=CORNER_PIXELS,
    )
    return store, profile


def _the_description_of(store: Path) -> dict:
    """The OME description inside a store, read straight off disk.

    Read as plain text rather than through a library, so that the test sees
    exactly what was written and not a library's helpful interpretation of it.
    """
    held = json.loads((store / "zarr.json").read_text(encoding="utf-8"))
    return (held.get("attributes") or {}).get("ome") or {}


def _the_array_description_at(level: Path) -> dict:
    """How one copy of the picture is stored, again read straight off disk."""
    return json.loads((level / "zarr.json").read_text(encoding="utf-8"))


# -- the headline -------------------------------------------------------------


def test_zarr_can_open_the_position_at_all(a_described_position):
    """The whole point, and the thing that used to fail outright.

    A position folder has to be marked as a *group* — a folder that holds arrays
    — and the mark is a small file at its top. Without it every reader stops at
    the first step: ``zarr.open_group`` refuses the folder, and so a colleague
    handed this run is told there is no image there, which from the format's
    point of view is true.

    It is opened read-only on purpose. Asked for a folder in the ordinary way,
    zarr helpfully *creates* the missing group rather than complaining, so a test
    that opened it any other way would report success while proving nothing at
    all — it would have written the very thing it was checking for.
    """
    store, profile = a_described_position

    opened = zarr.open_group(str(store), mode="r")

    assert sorted(opened.array_keys(), key=int) == [
        str(level.level) for level in profile.levels
    ], (
        "the image opened but does not hold the copies the profile promised, so a "
        "viewer zooming out would find nothing there"
    )


def test_a_position_nobody_has_described_cannot_be_opened(tmp_path):
    """The state a position is in before this module runs, stated as a test.

    This is here so that the test above is known to be doing work. A folder of
    arrays with no description is not an image, and if that ever stopped being
    true the headline test would pass for a reason that has nothing to do with
    what this module writes.

    This is also the exact state every position of a live run used to be left
    in: the pixels all present, and the folder refused by every reader.
    """
    from zarr.errors import GroupNotFoundError

    profile = _a_profile()
    store = tmp_path / "undescribed.ome.zarr"
    _write_the_copies(store, profile)

    with pytest.raises(GroupNotFoundError):
        zarr.open_group(str(store), mode="r")


# -- what the description has to say ------------------------------------------


def test_the_version_is_stated_where_the_standard_puts_it(a_described_position):
    """0.5 moved the version into the ``ome`` namespace, and it has to be there.

    A reader uses the version to decide how to interpret everything else, so a
    version in the wrong place, or missing, means the store cannot be read at all
    rather than being read slightly wrongly.
    """
    store, _ = a_described_position

    described = _the_description_of(store)

    assert described.get("version") == OME_ZARR_VERSION


def test_the_axes_are_named_typed_and_ordered_as_the_standard_requires(
    a_described_position,
):
    """The axes say what each dimension of the picture means.

    The standard is precise here: names MUST be unique, there MUST be two or
    three axes measuring distance, at most one moment axis and one colour axis,
    and they MUST come in the order moment, colour, distance. A reader relies on
    that order to know which dimension to put on the depth slider, so getting it
    wrong shows the specimen as a thin band rather than reporting anything.
    """
    store, profile = a_described_position

    axes = _the_description_of(store)["multiscales"][0]["axes"]

    names = [axis["name"] for axis in axes]
    assert names == list(profile.axes), (
        f"the image declares its axes as {names}, and the pictures are stored as "
        f"{list(profile.axes)}. A reader believes the declaration."
    )
    assert len(names) == len(set(names)), "axis names must be unique"
    assert 2 <= len(axes) <= 5

    kinds = [axis.get("type") for axis in axes]
    assert kinds.count("space") in (2, 3)
    assert kinds.count("time") <= 1
    assert kinds.count("channel") <= 1

    where = {"time": 0, "channel": 1, "space": 2}
    ranked = [where.get(kind, 1) for kind in kinds]
    assert ranked == sorted(ranked), (
        f"axes must run time, then channel, then space; got {kinds}"
    )


def test_the_units_are_names_other_software_will_recognise(a_described_position):
    """A unit is only useful if the reader on the other side knows the word.

    ``um`` and ``micron`` are the usual near-misses and both would be silently
    ignored elsewhere, which leaves a scale bar quietly absent rather than
    obviously wrong. The names the standard accepts are the UDUNITS-2 ones.
    """
    store, profile = a_described_position

    axes = _the_description_of(store)["multiscales"][0]["axes"]

    for axis in axes:
        if axis["type"] == "space":
            assert axis.get("unit") in SPACE_UNITS, (
                f"the {axis['name']} axis is measured in {axis.get('unit')!r}, which "
                f"other readers do not recognise; the run declared "
                f"{profile.voxel_unit!r}"
            )
        if axis["type"] == "time":
            assert axis.get("unit") in TIME_UNITS
        if axis["type"] == "channel":
            assert "unit" not in axis, (
                "a colour is not measured in anything, so it should carry no unit"
            )


def test_every_copy_is_listed_and_placed(a_described_position):
    """Each copy of the picture says how large its voxels are and where it sits.

    The rules checked here are the ones that decide whether the specimen lands in
    the right place: exactly one scale for each copy, at most one translation,
    and the translation written *after* the scale, because the offset is given in
    real distance and reading the two the other way round moves the picture by the
    size of the run. The copies must also be listed largest first, since a reader
    trusts the order rather than measuring.
    """
    store, profile = a_described_position
    multiscale = _the_description_of(store)["multiscales"][0]
    axes = multiscale["axes"]
    datasets = multiscale["datasets"]

    assert datasets, "an image must say what copies it holds"
    assert len(datasets) == len(profile.levels)

    widths = []
    for at, dataset in enumerate(datasets):
        assert "path" in dataset
        array = _the_array_description_at(store / str(dataset["path"]))
        widths.append(array["shape"][-1])
        assert len(array["shape"]) == len(axes), (
            "the number of axes must match the number of dimensions of the picture"
        )

        moves = dataset["coordinateTransformations"]
        kinds = [move["type"] for move in moves]
        assert kinds.count("scale") == 1, f"copy {at} needs exactly one scale"
        assert kinds.count("translation") <= 1, (
            f"copy {at} says where it sits {kinds.count('translation')} times over, "
            f"and a strict reader refuses such an image outright rather than "
            f"drawing it"
        )
        if "translation" in kinds:
            assert kinds.index("translation") > kinds.index("scale"), (
                "a translation must be listed after the scale it follows"
            )
        for move in moves:
            assert len(move[move["type"]]) == len(axes)

    assert widths == sorted(widths, reverse=True), (
        "the copies must be listed largest first"
    )


def test_the_voxel_size_grows_only_in_the_axes_the_copies_shrink(
    a_described_position,
):
    """Zooming out makes a voxel cover more ground, but only across the picture.

    Each zoomed-out copy is half the width and half the height of the one before
    it, so one of its voxels covers twice as much ground in y and in x. The depth
    is never reduced — scrolling a stack should show the planes that were really
    acquired — so the depth of a voxel is the same at every level, and so is the
    step between moments and between colours.

    This is the check that would notice a scale applied to the wrong axis, which
    is a fault nothing else here would see: the picture still draws, and the
    specimen is simply the wrong size in one direction.
    """
    store, profile = a_described_position
    datasets = _the_description_of(store)["multiscales"][0]["datasets"]
    axes = [axis["name"] for axis in _the_description_of(store)["multiscales"][0]["axes"]]

    for level, dataset in zip(profile.levels, datasets, strict=True):
        (scale,) = [
            move["scale"]
            for move in dataset["coordinateTransformations"]
            if move["type"] == "scale"
        ]
        stated = dict(zip(axes, scale, strict=True))

        for axis in ("z", "y", "x"):
            shrank_by = level.downsampling.get(axis, 1)
            expected = VOXEL_UM["zyx".index(axis)] * shrank_by
            assert stated[axis] == pytest.approx(expected), (
                f"copy {level.level} says one voxel is {stated[axis]} microns in "
                f"{axis}, where the run declared {VOXEL_UM['zyx'.index(axis)]} "
                f"microns shrunk {shrank_by} times. A specimen measured against "
                f"this would be the wrong size."
            )

        assert stated["t"] == pytest.approx(1.0)
        assert stated["c"] == pytest.approx(1.0)

    # And the shape of the thing overall: the tiled axes double each time, the
    # rest hold still. Stated separately from the arithmetic above because it is
    # the property an operator would describe, and because a scale that was right
    # at every level individually but did not double would be a different fault.
    across = [
        dict(zip(axes, move["scale"], strict=True))
        for dataset in datasets
        for move in dataset["coordinateTransformations"]
        if move["type"] == "scale"
    ]
    for finer, coarser in zip(across, across[1:], strict=False):
        assert coarser["y"] == pytest.approx(finer["y"] * 2)
        assert coarser["x"] == pytest.approx(finer["x"] * 2)
        assert coarser["z"] == pytest.approx(finer["z"])
        assert coarser["t"] == pytest.approx(finer["t"])
        assert coarser["c"] == pytest.approx(finer["c"])


def test_the_corner_is_where_the_run_put_this_position(a_described_position):
    """The position has to say where on the stage it was imaged, in real distance.

    The run keeps a position's place as a count of pixels, because that is what
    the tiling arithmetic needs. A reader needs a distance. If the count is
    written straight into the file the position lands at a plausible-looking but
    quite wrong place — here it would sit 768 microns out instead of 268.8 — and
    the two tiles either side of it would not meet.
    """
    store, _ = a_described_position
    datasets = _the_description_of(store)["multiscales"][0]["datasets"]
    axes = [axis["name"] for axis in _the_description_of(store)["multiscales"][0]["axes"]]

    for at, dataset in enumerate(datasets):
        (corner,) = [
            move["translation"]
            for move in dataset["coordinateTransformations"]
            if move["type"] == "translation"
        ]
        stated = dict(zip(axes, corner, strict=True))
        for axis in ("z", "y", "x"):
            expected = CORNER_PIXELS[axis] * VOXEL_UM["zyx".index(axis)]
            assert stated[axis] == pytest.approx(expected), (
                f"copy {at} begins at {stated[axis]} in {axis}, where the run put "
                f"this position at {expected} microns. Every acquisition would be "
                f"piled on the others at the wrong place."
            )
        assert stated["t"] == pytest.approx(0.0)
        assert stated["c"] == pytest.approx(0.0)


def test_every_copy_begins_at_the_same_corner(a_described_position):
    """Zooming out must not slide the specimen sideways.

    Each smaller copy covers twice as much ground per voxel, but it still begins
    at the same place on the stage. Were a copy to say otherwise, the specimen
    would appear to shift as the operator zoomed out — a fault that is easy to
    see and very hard to explain, because the picture is perfectly good at every
    single zoom on its own.
    """
    store, _ = a_described_position
    datasets = _the_description_of(store)["multiscales"][0]["datasets"]

    corners = {
        tuple(move["translation"])
        for dataset in datasets
        for move in dataset["coordinateTransformations"]
        if move["type"] == "translation"
    }

    assert len(corners) == 1, (
        f"the copies of this picture claim {len(corners)} different corners "
        f"({corners}), so the specimen would move as the operator zoomed out"
    )


def test_the_corner_is_stated_once_rather_than_twice(a_described_position):
    """Where the picture sits must not be applied two times over.

    The standard allows an offset beside each copy and another for the image as a
    whole, and a reader applies the second on top of the first. Writing the same
    offset in both places therefore puts the specimen at twice its distance from
    the origin — a mistake that looks entirely reasonable in the file and is only
    visible when two acquisitions fail to line up. This project states it beside
    each copy, because that is the place the format makes compulsory and the one
    every reader looks at.
    """
    store, _ = a_described_position
    multiscale = _the_description_of(store)["multiscales"][0]

    for_the_whole_image = multiscale.get("coordinateTransformations") or []
    moved_overall = [one for one in for_the_whole_image if one["type"] == "translation"]

    for dataset in multiscale["datasets"]:
        moved_here = [
            one for one in dataset["coordinateTransformations"]
            if one["type"] == "translation"
        ]
        assert not (moved_overall and moved_here), (
            "the corner is written both beside this copy and for the image as a "
            "whole, so it would be applied twice and the picture would sit at "
            "double the distance from the origin"
        )


def test_a_position_that_was_never_placed_says_nothing_about_where_it_sits(tmp_path):
    """Silence is the honest answer for a position that was never part of a mosaic.

    Writing a corner of nought would be a claim rather than an absence, and a
    stitcher told every position begins at the stage's zero would pile them all
    on top of one another. So a position described without a place carries a
    scale and no translation at all.
    """
    profile = _a_profile()
    store = tmp_path / "alone.ome.zarr"
    _write_the_copies(store, profile)

    describe_the_position(store, profile, channels=COLOURS)

    for dataset in _the_description_of(store)["multiscales"][0]["datasets"]:
        kinds = [move["type"] for move in dataset["coordinateTransformations"]]
        assert kinds == ["scale"], (
            f"a position with no declared place still says {kinds}, so it is "
            f"claiming to sit somewhere it was never put"
        )


def test_every_copy_names_its_own_dimensions(a_described_position):
    """Version 0.5 requires each copy to name its dimensions, and to match the axes.

    The specification is explicit: the names "MUST be included in the zarr.json of
    the Zarr array of a multiscale level and MUST match the names in the axes
    metadata". It is also plainly useful. An analysis script that opens one
    zoomed-out copy on its own would otherwise be handed five anonymous dimensions
    with no way to tell depth from time.
    """
    store, profile = a_described_position
    axes = [axis["name"] for axis in _the_description_of(store)["multiscales"][0]["axes"]]

    for level in profile.levels:
        held = _the_array_description_at(store / str(level.level))
        assert held.get("dimension_names") == axes, (
            f"copy {level.level} names its dimensions "
            f"{held.get('dimension_names')}, where the image's axes are {axes}"
        )
        # And read back through zarr as well as off disk, because a name written
        # in a form zarr does not recognise would be no name at all.
        opened = zarr.open_array(str(store / str(level.level)), mode="r")
        assert list(opened.metadata.dimension_names or []) == axes


def test_the_image_says_how_its_smaller_copies_were_made(a_described_position):
    """The standard asks for this, and an operator deserves to know the answer.

    A live run builds each zoomed-out copy by averaging two-by-two blocks of
    voxels, so a zoomed-out picture is a smoothed version of the specimen. That
    has a visible consequence worth stating: a single bright speck fades as you
    zoom out, because it is being averaged with its dark neighbours. A reader told
    nothing would have to guess, and the other common answer — keeping every
    second voxel — behaves in the opposite way.
    """
    store, _ = a_described_position
    multiscale = _the_description_of(store)["multiscales"][0]

    assert multiscale.get("name")
    assert multiscale.get("type") == "mean", (
        "a live run averages each two-by-two block of voxels to make the next "
        "copy, and the image has to say so — a reader told the copies were "
        "sampled would trust a faint object at low zoom more than it should"
    )
    assert multiscale.get("metadata"), (
        "the standard asks for a note about how the copies were made"
    )
    assert multiscale["metadata"].get("description")


def test_the_colours_are_described_the_way_a_reader_expects(a_described_position):
    """A channel needs a colour and a display window, and both have exact shapes.

    The window is the part worth being careful about. ``min`` and ``max`` are the
    camera's whole range; ``start`` and ``end`` are the brightness the run asks to
    be shown between. All four are required, and a description naming a channel
    with an incomplete window is refused outright by strict readers — the image
    then fails to open at all, which is a good deal worse than opening dim.
    """
    store, _ = a_described_position

    channels = _the_description_of(store)["omero"]["channels"]

    assert len(channels) == len(COLOURS)
    for channel, expected_name in zip(channels, COLOURS, strict=True):
        assert channel["label"] == expected_name
        colour = channel["color"]
        assert len(colour) == 6 and all(
            digit in "0123456789abcdefABCDEF" for digit in colour
        ), f"a channel's colour must be six hexadecimal digits, got {colour!r}"
        window = channel["window"]
        for named in ("min", "max", "start", "end"):
            assert named in window, f"a channel's window must state {named}"
        assert window["min"] <= window["start"] <= window["end"] <= window["max"]


# -- the pixels themselves ----------------------------------------------------


def test_describing_a_position_does_not_disturb_its_pixels(tmp_path):
    """Describing is meant to add words, never to touch the picture.

    The description is written over a position that already holds a night's
    imaging, so the one thing this module absolutely must not do is empty the
    folder on its way in. That is not a hypothetical: the ordinary way to make a
    zarr group asks for a fresh one and clears whatever was there first, and
    doing that here would destroy every voxel of the acquisition in a few
    milliseconds.
    """
    profile = _a_profile()
    store = tmp_path / "precious.ome.zarr"
    _write_the_copies(store, profile, value=1234)

    describe_the_position(store, profile, channels=COLOURS, origin_pixels=CORNER_PIXELS)

    for level in profile.levels:
        held = zarr.open_array(str(store / str(level.level)), mode="r")[:]
        assert held.size > 0
        assert np.all(held == 1234), (
            f"copy {level.level} no longer holds the pixels that were written to "
            f"it, so describing the image destroyed the acquisition"
        )


def test_describing_the_same_position_twice_is_harmless(tmp_path):
    """A resumed run describes a position it has already described, and should.

    Nothing about the second attempt should differ from the first, and nothing
    should be lost. If it were not safe to repeat, a run picking up where it left
    off would have to remember which positions it had already finished, which is
    exactly the kind of bookkeeping that goes wrong after a power cut.
    """
    profile = _a_profile()
    store = tmp_path / "again.ome.zarr"
    _write_the_copies(store, profile, value=7)

    first = describe_the_position(
        store, profile, channels=COLOURS, origin_pixels=CORNER_PIXELS
    )
    second = describe_the_position(
        store, profile, channels=COLOURS, origin_pixels=CORNER_PIXELS
    )

    assert first == second
    assert _the_description_of(store) == first
    assert np.all(zarr.open_array(str(store / "0"), mode="r")[:] == 7)


def test_a_copy_kept_in_bundled_files_is_described_just_the_same(tmp_path):
    """A real run bundles its full-size copy, and that must not change the words.

    A long run leaves millions of tiny files behind unless many of them are
    packed into one, which most filesystems and most backup software handle very
    badly. OME-Zarr 0.5 allows that packing, and a position written by a live run
    normally uses it for the full-size copy.

    It is worth a test of its own because a bundled copy keeps its description in
    a different shape from an ordinary one — the size written at the top is the
    size of the bundle, and the size of the pieces inside it is recorded further
    down. The dimension names sit above all of that and are unaffected, and this
    is what would notice if that ever stopped being true.
    """
    profile = _a_profile()
    store = tmp_path / "bundled.ome.zarr"
    _write_the_copies(store, profile)
    zarr.create_array(
        store=str(store / "0"),
        shape=(MOMENTS, len(COLOURS), Z_PLANES, FRAME, FRAME),
        chunks=(1, 1, 1, CHUNK, CHUNK),
        shards=(1, 1, Z_PLANES, FRAME, FRAME),
        dtype=profile.dtype,
        zarr_format=3,
        overwrite=True,
    )

    describe_the_position(store, profile, channels=COLOURS, origin_pixels=CORNER_PIXELS)

    axes = [axis["name"] for axis in _the_description_of(store)["multiscales"][0]["axes"]]
    assert _the_array_description_at(store / "0")["dimension_names"] == axes
    opened = zarr.open_group(str(store), mode="r")
    assert list(opened["0"].metadata.dimension_names or []) == axes


# -- what it refuses to do ----------------------------------------------------


def test_a_position_that_was_never_written_is_refused(tmp_path):
    """Describing a folder that is not there would produce a promise, not an image."""
    profile = _a_profile()

    with pytest.raises(ZmartLiveError, match="no position at"):
        describe_the_position(tmp_path / "nothing.ome.zarr", profile, channels=COLOURS)


def test_a_position_missing_one_of_its_copies_is_refused(tmp_path):
    """An image that lists a copy nobody can find fails later, somewhere else.

    Refusing here is kinder than describing what is there. A half-written
    position that announces itself as a complete image opens perfectly well and
    then fails the moment somebody zooms out, by which time the run is over and
    nobody can tell where the fault came from.
    """
    profile = _a_profile()
    store = tmp_path / "unfinished.ome.zarr"
    _write_the_copies(store, profile)
    last = profile.levels[-1].level
    for leftover in sorted((store / str(last)).rglob("*"), reverse=True):
        leftover.unlink() if leftover.is_file() else leftover.rmdir()
    (store / str(last)).rmdir()

    with pytest.raises(ZmartLiveError, match="have not been written"):
        describe_the_position(store, profile, channels=COLOURS)


def test_axes_in_the_wrong_order_are_refused(tmp_path):
    """A profile that stores its axes out of order cannot be described honestly.

    The standard fixes the order — time, then colour, then the axes that measure
    distance — and a reader trusts it rather than measuring. An image that
    declared them any other way would show the specimen as a thin band and report
    nothing wrong, so it is refused before it is written.
    """
    from dataclasses import replace

    profile = _a_profile()
    muddled = replace(profile, axes=("c", "t", "z", "y", "x"))

    with pytest.raises(ZmartLiveError, match="time first"):
        the_image_description(muddled, name="muddled")


def test_an_axis_nobody_can_interpret_is_refused():
    """An axis this module has never heard of cannot be given a meaning."""
    from dataclasses import replace

    profile = _a_profile()
    strange = replace(profile, axes=("t", "c", "z", "y", "x", "q"))

    with pytest.raises(ZmartLiveError, match="no way to tell"):
        the_image_description(strange, name="strange")


def test_a_unit_other_software_will_not_recognise_is_refused():
    """``um`` looks right to a person and means nothing to a reader."""
    from dataclasses import replace

    profile = _a_profile()
    misspelt = replace(profile, voxel_unit="um")

    with pytest.raises(ZmartLiveError, match="not a name other software"):
        the_image_description(misspelt, name="misspelt")


def test_an_unexplained_way_of_shrinking_the_picture_is_refused():
    """Saying nothing about how the copies were made is not an option."""
    profile = _a_profile()

    with pytest.raises(ZmartLiveError, match="not a way of building"):
        the_image_description(profile, name="odd", smaller_copies_made_by="magic")


def test_a_picture_whose_shape_does_not_match_its_axes_is_refused(tmp_path):
    """Five declared axes and four stored dimensions cannot both be right."""
    profile = _a_profile()
    store = tmp_path / "mismatched.ome.zarr"
    _write_the_copies(store, profile)
    zarr.create_array(
        store=str(store / "0"),
        shape=(len(COLOURS), Z_PLANES, FRAME, FRAME),
        chunks=(1, 1, 128, 128),
        dtype=profile.dtype,
        zarr_format=3,
        overwrite=True,
    )

    with pytest.raises(ZmartLiveError, match="have to agree"):
        describe_the_position(store, profile, channels=COLOURS)


# -- somebody else's reader ---------------------------------------------------


def test_another_reader_opens_the_position_and_agrees_where_it_sits(
    a_described_position, tmp_path, monkeypatch
):
    """The question that actually matters: does this travel?

    Our own code reading our own images proves little, because a misunderstanding
    shared between the two halves cancels out and nothing looks wrong. So the
    image is handed to ``ngff-zarr``, which is what ``multiview-stitcher`` and
    much of the Python imaging world read OME-Zarr through, and it is asked where
    it thinks the picture sits and how large a voxel is.
    """
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    ngff_zarr = pytest.importorskip(
        "ngff_zarr",
        reason="ngff-zarr is an optional check that our images travel; "
        "install it with `python -m pip install ngff-zarr`",
    )
    store, profile = a_described_position

    multiscales = ngff_zarr.from_ngff_zarr(store)

    assert len(multiscales.images) == len(profile.levels)
    finest = multiscales.images[0]
    assert tuple(finest.dims) == profile.axes
    for axis, size in zip(("z", "y", "x"), VOXEL_UM, strict=True):
        assert finest.scale[axis] == pytest.approx(size), (
            f"ngff-zarr reads this position's voxels as {finest.scale[axis]} "
            f"microns in {axis}, where the run declared {size}. A specimen "
            f"measured against this would be the wrong size."
        )
        assert finest.translation[axis] == pytest.approx(
            CORNER_PIXELS[axis] * size
        ), (
            f"ngff-zarr puts this position's {axis} corner at "
            f"{finest.translation[axis]}, where the run put it at "
            f"{CORNER_PIXELS[axis] * size} microns. Every acquisition of the run "
            f"would be stacked on the others in the wrong place."
        )


def test_another_reader_agrees_the_copies_nest(
    a_described_position, tmp_path, monkeypatch
):
    """Read from outside, each copy is coarser and still begins in the same place."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    ngff_zarr = pytest.importorskip("ngff_zarr", reason="an optional outside reader")
    store, _ = a_described_position

    images = ngff_zarr.from_ngff_zarr(store).images

    for at, image in enumerate(images):
        for axis, size in zip(("z", "y", "x"), VOXEL_UM, strict=True):
            assert image.translation[axis] == pytest.approx(CORNER_PIXELS[axis] * size)
        assert image.scale["y"] == pytest.approx(VOXEL_UM[1] * 2**at)
        assert image.scale["x"] == pytest.approx(VOXEL_UM[2] * 2**at)
        assert image.scale["z"] == pytest.approx(VOXEL_UM[0])


def test_the_description_satisfies_the_published_schema(
    a_described_position, tmp_path, monkeypatch
):
    """Checked against the specification's own machine-readable rules.

    This is the closest thing to an impartial opinion available: the OME-NGFF
    project publishes a schema for a 0.5 image, and ``ngff-zarr`` carries a copy
    and will check a description against it.

    Be clear about what it does and does not prove. The schema enforces the shape
    of the document — that a version is present, that a lone translation is
    refused, that the required blocks exist. It does **not** enforce the rules
    written in the specification's prose, and several of those matter most here:
    the axis order, the unit names, and whether the copies are listed largest
    first all pass the schema whatever they say. Those are the rules the tests
    above transcribe by hand, and this check stands beside them rather than in
    place of them.
    """
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    ngff_zarr = pytest.importorskip("ngff_zarr", reason="an optional outside reader")
    pytest.importorskip(
        "jsonschema",
        reason="ngff-zarr checks against the published schema through jsonschema; "
        "install it with `python -m pip install ngff-zarr[validate]`",
    )
    store, _ = a_described_position

    attributes = json.loads((store / "zarr.json").read_text(encoding="utf-8"))["attributes"]

    ngff_zarr.validate(attributes, version=OME_ZARR_VERSION, model="image")


# -- and the same thing, written by a real run --------------------------------


def test_a_position_a_live_run_actually_wrote_can_be_opened(tmp_path):
    """The whole path, end to end, with the run's own writer producing the pixels.

    Every test above builds a position's copies itself, which keeps them quick
    and independent. This one lets :class:`zmart_live.coordinator.LivePublisher`
    write a position exactly as a run does, then describes it, and asks the same
    headline question. It is here because the defect this module fixes was a real
    one on real positions, and a test that only ever describes its own inventions
    could go on passing while the run wrote something else entirely.
    """
    from zmart_live.coordinator import LivePublisher

    profile = _a_profile()
    publisher = LivePublisher(
        folder=tmp_path,
        profile=profile,
        run_id="a-run",
        cells={GridCell(0, 0): "pos00000", GridCell(0, 1): "pos00001"},
        channels=COLOURS,
        timepoints=MOMENTS,
    )
    publisher.write_a_position(
        "pos00001", np.full((len(COLOURS), Z_PLANES, FRAME, FRAME), 900, "uint16")
    )
    store = publisher.position_store("pos00001")

    opened = zarr.open_group(str(store), mode="r")
    assert sorted(opened.array_keys(), key=int) == [
        str(level.level) for level in profile.levels
    ]

    axes = [axis["name"] for axis in _the_description_of(store)["multiscales"][0]["axes"]]
    assert axes == list(profile.axes)

    # And the corner the run itself recorded for this tile, turned into microns.
    placed = publisher.layout.placement("pos00001").origin
    (corner,) = [
        move["translation"]
        for move in _the_description_of(store)["multiscales"][0]["datasets"][0][
            "coordinateTransformations"
        ]
        if move["type"] == "translation"
    ]
    stated = dict(zip(axes, corner, strict=True))
    assert stated["x"] == pytest.approx(placed["x"] * VOXEL_UM[2])
    assert stated["y"] == pytest.approx(placed["y"] * VOXEL_UM[1])


def test_the_live_seamless_view_is_also_opened_by_the_outside_reader(
    tmp_path, monkeypatch
):
    """The operator-facing multiscale image is not merely a folder of arrays."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    ngff_zarr = pytest.importorskip("ngff_zarr", reason="an optional outside reader")
    from zmart_live.coordinator import LivePublisher

    profile = _a_profile()
    publisher = LivePublisher(
        folder=tmp_path / "run",
        profile=profile,
        run_id="a-view-run",
        cells={GridCell(0, 0): "pos00000"},
        channels=COLOURS,
        timepoints=MOMENTS,
    )
    publisher.write_a_position(
        "pos00000", np.full((len(COLOURS), Z_PLANES, FRAME, FRAME), 900, "uint16")
    )
    publisher.write_the_seamless_view(frozenset({("pos00000", 0)}))

    multiscales = ngff_zarr.from_ngff_zarr(publisher.seamless_store)
    assert len(multiscales.images) == len(profile.levels)
    assert tuple(multiscales.images[0].dims) == profile.axes

    attributes = json.loads(
        (publisher.seamless_store / "zarr.json").read_text(encoding="utf-8")
    )["attributes"]
    ngff_zarr.validate(attributes, version=OME_ZARR_VERSION, model="image")
