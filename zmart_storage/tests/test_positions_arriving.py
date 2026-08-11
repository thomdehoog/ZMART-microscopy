"""A run written one position at a time, watched while it fills in.

This is the smallest thing that gives an operator a live picture: hand a position
to the writer as it comes off the camera, and the image the viewer already has
open grows to include it. Nothing is copied and no second image is written.

The tests below are about the three properties that make that worth having — the
viewer is offered one image however many positions there are, every position stays
an ordinary image somebody else can open, and the picture on disk holds no
full-size voxels of its own — and about the one thing a run genuinely has to
decide before it starts.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from zmart_storage.canvas import Channel
from zmart_storage.linked import the_map_inside
from zmart_storage.positions import (
    how_many_copies_a_position_can_keep,
    start_a_run,
)

# Small on purpose. These tests are about how a run is arranged, not about how a
# picture looks, so the pictures only have to differ from one another.
TILE = (1, 64, 64)
PIECE = 64
ACROSS = 3
VOXEL_UM = (2.0, 0.35, 0.35)

# Deliberately not the origin: a run at nought would let a mistake that lost the
# corner entirely still look right.
ORIGIN_UM = (11.0, 5.5, 7.25)


def _the_positions_in(view: Path) -> list[Path]:
    """The position images inside a picture.

    The positions sit **directly inside** the picture, among its levels, with
    nothing between — the layout `PLAN_live_smart_microscopy.md` settles. They
    are told apart from everything else by their name: every child ending
    ``.ome.zarr`` is a position, and only positions are named that way.
    """
    return sorted(one for one in view.iterdir()
                  if one.name.endswith(".ome.zarr"))


def _a_picture(seed: int) -> np.ndarray:
    """One position's picture, noisy so that two of them cannot be confused."""
    rng = np.random.default_rng(seed)
    return (400 + rng.normal(0, 50, TILE)).clip(0, 4000).astype("uint16")


def _a_run(folder: Path, *, room_across: int = 8 * 64, channels: int = 1,
           frames: int = 1):
    """Image a small raster, one position at a time, and hand back the run."""
    colours = [Channel("488", window=(0, 4000)), Channel("561", window=(0, 3000))]
    with start_a_run(
        folder, name="overview",
        room=(TILE[0], room_across, room_across), tile_shape=TILE,
        voxel_size_um=VOXEL_UM, origin_um=ORIGIN_UM,
        channels=colours[:channels], frames=frames, piece=PIECE,
    ) as run:
        for row in range(ACROSS):
            for column in range(ACROSS):
                for colour in range(channels):
                    for moment in range(frames):
                        run.write(
                            _a_picture(row * ACROSS + column + colour * 9 + moment * 81),
                            at=(0, row * TILE[1], column * TILE[2]),
                            channel=colour, frame=moment,
                        )
        view = run.path
        imaged = run.positions
    return view, imaged


def test_the_run_writes_one_image_per_position_and_one_picture_to_open(tmp_path):
    """Three things at the top, and each of them is one idea.

    The image to open, the positions, and our own two folders. Anything else at
    the top would be something an operator has to ask about.
    """
    folder = tmp_path / "experiment"
    view, imaged = _a_run(folder)

    assert imaged == ACROSS * ACROSS
    assert view == folder / "overview.ome.zarr"

    stored = _the_positions_in(view)
    assert len(stored) == ACROSS * ACROSS, (
        "one image per place on the stage, and nothing else in the positions folder"
    )


def test_the_picture_holds_no_full_size_voxels_of_its_own(tmp_path):
    """Nothing is copied, which is the whole reason for this arrangement.

    The view's full-size level is a description and nothing else: every voxel of
    it is answered by handing over a position's own file.

    Only the full-size level is checked here, because the positions in this
    particular run are exactly one piece across and so can carry no zoomed-out
    copies of their own — the view has to make those. The test below,
    ``test_each_position_carries_its_own_zoomed_out_copies``, uses positions large
    enough to keep their own and shows the view then writing nothing whatever, at
    any zoom, which is the arrangement a real run gets.
    """
    folder = tmp_path / "experiment"
    view, _ = _a_run(folder)

    describing = {".zarray", ".zattrs", "zarr.json"}
    full_size = [one.name for one in (view / "0").rglob("*")
                 if one.is_file() and one.name not in describing]
    assert full_size == [], (
        f"the view wrote {len(full_size)} pieces of full-size picture, so the run "
        "has been copied after all"
    )


def test_every_position_opens_on_its_own(tmp_path):
    """A position is an ordinary OME-Zarr image, not a fragment of ours.

    This is what keeps the data yours rather than ours. Nothing about being
    pointed at changes a position, so it opens in napari, in Fiji, or in anything
    else, and it carries its own true place on the stage.
    """
    folder = tmp_path / "experiment"
    view, _ = _a_run(folder)
    positions = _the_positions_in(view)

    corners = []
    for store in positions:
        described = json.loads((store / "zarr.json").read_text(encoding="utf-8"))
        multiscale = described["attributes"]["ome"]["multiscales"][0]
        assert multiscale["datasets"], f"{store.name} describes no picture"
        # Where a position sits is written beside each copy of its picture, which
        # is the place OME-Zarr makes compulsory and so the place another reader
        # looks. The full-size copy is the one asked here.
        full_size = multiscale["datasets"][0]
        moved = [one for one in full_size["coordinateTransformations"]
                 if one["type"] == "translation"]
        assert moved, f"{store.name} does not say where on the stage it was imaged"
        corners.append(tuple(moved[0]["translation"][-2:]))

    assert len(set(corners)) == len(positions), (
        "two positions claim the same place on the stage, so they would be piled "
        "on top of one another when the folder is opened"
    )
    # The run's own corner is where the first position sits, not nought.
    assert min(corners) == (ORIGIN_UM[1], ORIGIN_UM[2])


def test_zarr_itself_is_happy_with_everything_inside_the_picture(tmp_path):
    """Opening the run in other software must produce no complaints at all.

    This is the check that keeps the data yours rather than ours, and the rule is
    narrower than it first looks. Zarr does not mind what a group *contains* — it
    minds finding something that is not part of the hierarchy. A loose file, or a
    plain folder, gets *"Object at ... is not recognized as a component of a Zarr
    hierarchy"*. A proper group does not, which is why the positions live in one.

    So this asks zarr directly rather than guessing from names, which is how the
    earlier version of this got it wrong and pushed everything out of the picture
    that did not need to leave.
    """
    import warnings

    import zarr

    folder = tmp_path / "experiment"
    view, _ = _a_run(folder)

    for image in [view, *_the_positions_in(view)]:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            list(zarr.open_group(str(image), mode="r").members())
        complaints = [str(one.message) for one in caught]
        assert complaints == [], (
            f"opening {image.name} made zarr complain: {complaints}"
        )


def test_a_run_leaves_nothing_behind_that_nothing_reads(tmp_path):
    """Four things in the folder, and each of them earns its place.

    The picture to open, the positions, the list of pointers that joins them, and
    the note saying a writer has the run open. Anything else would be something an
    operator has to ask about.

    A coverage record used to be kept for the picture as well, and it was worse
    than useless: a view never has a tile written into it, so the record said
    ``tiles_written: 0`` for ever. A reader bounding itself to that would have
    shown an empty screen over a run that imaged perfectly well.
    """
    folder = tmp_path / "experiment"
    _a_run(folder)

    left = sorted(one.name for one in folder.iterdir())
    assert left == ["overview.ome.zarr", "overview.writing"], (
        f"something unexpected was left behind: {left}")

    assert not (folder / "zmart-coverage").exists(), (
        "a view kept a record of what it imaged, which for a view is always "
        "nothing, and would tell a reader the run was empty"
    )


def test_the_picture_is_what_lets_the_viewer_open_the_run_at_all(tmp_path):
    """Why the picture cannot simply be deleted, which is a fair thing to ask.

    It holds no voxels, so it is tempting to think the positions alone would do.
    They would not. The viewer draws with neuroglancer, which builds drawing
    layers for every image it is handed, so a folder of positions is a folder of
    layers — a few thousand of them for a real run, which never opens in any
    useful sense.

    Handed the picture instead, the viewer sees **one** image and does not care
    what is underneath. That is the whole mechanism, and this is what it looks
    like from the viewer's own side.
    """
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "viz_studio" / "backend"))
    from stores import discover

    folder = tmp_path / "experiment"
    view, _ = _a_run(folder)

    _, offered = discover(folder)
    assert offered == ["overview.ome.zarr"], (
        "opening the run should offer exactly one image to draw"
    )

    # The positions sit directly inside that one image, and the viewer must
    # *not* be handed them as images of their own — a real run holds thousands,
    # and one drawing layer each is the arrangement that never opens. An image
    # is an image because of its own description, so discovery stops at the
    # picture and what is underneath stays underneath.
    _, inside = discover(view)
    assert inside == [view.name], (
        "the picture should be one image to the viewer however many positions "
        "it holds inside"
    )
    assert len(_the_positions_in(view)) == ACROSS * ACROSS, (
        "the positions should really be there, directly inside the picture"
    )


def test_a_position_imaged_again_goes_into_the_image_it_already_had(tmp_path):
    """A second colour or a later moment is the same place, not a new one.

    Everything recorded of one field of view belongs together, and the view must
    be told about that place once rather than once per picture — otherwise the
    same position appears twice in the list of pointers.
    """
    folder = tmp_path / "experiment"
    view, imaged = _a_run(folder, channels=2, frames=2)

    assert imaged == ACROSS * ACROSS, (
        "imaging a place in two colours and two moments made more than one image "
        "of it"
    )
    assert len(_the_positions_in(view)) == ACROSS * ACROSS

    listed = the_map_inside(view)
    places = [tuple(one["at"]) for one in listed["tiles"]]
    assert len(places) == len(set(places)) == ACROSS * ACROSS, (
        "a place was written into the list of pointers more than once"
    )


def test_declaring_generous_room_costs_almost_nothing(tmp_path):
    """The one thing a run has to decide before it starts, and what it really costs.

    A run cannot work out its own extent as it goes, because the viewer may be
    reading the description throughout and the number of zoomed-out copies is
    fixed when the picture is declared. So the room is stated up front.

    That sounds worse than it is. Room nothing is imaged into holds no voxels and
    costs no disk; what a larger room buys is *more* zoomed-out copies, which is
    what keeps a big picture opening quickly. So the honest advice is to declare
    the stage's travel range and stop thinking about it — which is what this
    measures rather than asserts.
    """
    # A stage's whole travel range against just the ground these nine positions
    # cover. Three copies is the floor whatever the size, so the generous room has
    # to be genuinely large for the difference to show at all.
    tight, _ = _a_run(tmp_path / "tight", room_across=ACROSS * TILE[1])
    generous, _ = _a_run(tmp_path / "generous", room_across=256 * TILE[1])

    def levels(view: Path) -> int:
        described = json.loads((view / "zarr.json").read_text(encoding="utf-8"))
        return len(described["attributes"]["ome"]["multiscales"][0]["datasets"])

    assert levels(generous) > levels(tight), (
        "a larger picture should keep more zoomed-out copies, which is the whole "
        "reason the room is worth declaring generously"
    )

    def bytes_in(folder: Path) -> int:
        return sum(one.stat().st_size for one in folder.rglob("*") if one.is_file())

    tight_run = bytes_in(tmp_path / "tight")
    generous_run = bytes_in(tmp_path / "generous")
    assert generous_run < tight_run * 1.5, (
        f"declaring 64 times the room cost {generous_run / tight_run:.1f} times the "
        "disk, so empty room is not free after all and the advice above is wrong"
    )


def test_each_position_carries_its_own_zoomed_out_copies(tmp_path):
    """A position is self-contained: the whole pyramid is inside the position file.

    This is what lets the picture the viewer opens store nothing at all, at any
    zoom. It also means a position handed to somebody on its own opens and zooms
    like a proper image rather than a single flat plane.

    How many copies a position can keep is decided by its own size: halving stops
    when a copy would be smaller than one piece, since a piece is the smallest
    thing that can be handed to the browser.
    """
    folder = tmp_path / "experiment"
    tile = (1, 512, 512)
    piece = 128
    expected = how_many_copies_a_position_can_keep(tile, piece)
    assert expected == 3, "512 halves to 256 and 128 before reaching one piece"

    with start_a_run(
        folder, name="overview", room=(1, 4096, 4096), tile_shape=tile,
        voxel_size_um=VOXEL_UM, origin_um=ORIGIN_UM,
        channels=[Channel("488", window=(0, 4000))], piece=piece,
    ) as run:
        for row in range(2):
            for column in range(2):
                rng = np.random.default_rng(row * 2 + column)
                run.write((400 + rng.normal(0, 300, tile)).clip(0, 4000).astype("uint16"),
                          at=(0, row * 512, column * 512))
        view = run.path

    for store in _the_positions_in(view):
        described = json.loads((store / "zarr.json").read_text(encoding="utf-8"))
        levels = described["attributes"]["ome"]["multiscales"][0]["datasets"]
        assert [one["path"] for one in levels] == ["0", "1", "2"], (
            f"{store.name} does not carry its own zoomed-out copies"
        )

    # And the picture the viewer opens writes nothing, at any zoom, because every
    # level of it is answered by pointing at a position.
    describing = {".zarray", ".zattrs", "zarr.json"}
    # Everything in the picture except the positions, which are inside it and are
    # where the voxels are supposed to be.
    written = [one.name for level in range(3)
               for one in (view / str(level)).rglob("*")
               if one.is_file() and one.name not in describing]
    assert written == [], (
        f"the picture wrote {len(written)} pieces of its own even though the "
        "positions carry their own copies, so the run is being held twice over"
    )


def test_a_zoomed_out_picture_holds_the_voxels_it_should(tmp_path):
    """The copies inside the positions really are the picture's own copies.

    This is the claim the whole arrangement rests on, so it is checked against the
    specimen rather than argued. A position's zoomed-out copy is read back and
    compared with the picture that was written shrunk by the same amount — every
    voxel, not a sample.

    It holds because shrinking keeps every second voxel counted from the image's
    own corner, and a position begins on a whole number of pieces times the largest
    shrink. Average four voxels instead and this stops being true at once, because
    a coarse voxel near the edge of a position would be made partly of its
    neighbour's specimen.
    """
    import zarr

    folder = tmp_path / "experiment"
    tile = (1, 512, 512)
    rng = np.random.default_rng(0)
    picture = (400 + rng.normal(0, 300, tile)).clip(0, 4000).astype("uint16")

    with start_a_run(
        folder, name="overview", room=(1, 2048, 2048), tile_shape=tile,
        voxel_size_um=VOXEL_UM, origin_um=ORIGIN_UM,
        channels=[Channel("488", window=(0, 4000))], piece=128,
    ) as run:
        run.write(picture, at=(0, 0, 0))
        view = run.path

    store = _the_positions_in(view)[0]
    held = zarr.open_group(str(store), mode="r")
    for level in range(3):
        factor = 2 ** level
        should_be = picture[:, ::factor, ::factor]
        found = np.asarray(held[str(level)][0, 0])
        assert found.shape == should_be.shape, (
            f"level {level} is {found.shape} and shrinking gives {should_be.shape}"
        )
        assert np.array_equal(found, should_be), (
            f"level {level} of the position is not the picture shrunk by {factor}; "
            "the viewer would show something the microscope never recorded"
        )


def test_a_run_can_be_added_to_after_it_has_started(tmp_path):
    """The four things a smart experiment does to a run already going.

    A colour, a moment, and a slab of depth are three different questions and it
    is worth being exact about which of them makes a new image and which does not.

    A place imaged **again** — in another colour, at a later moment, or simply
    written over — goes into the image that place already has, because everything
    recorded of one field of view belongs together. A slab of depth **above** a
    place is somewhere else on the stage, so it is a position of its own.

    Which of the two happened matters for more than tidiness: the picture is told
    about a *place*, so a second colour must not add a second entry to the map,
    while a slab must.
    """
    folder = tmp_path / "experiment"
    deep = (4, 128, 128)
    piece = 128

    with start_a_run(
        folder, name="experiment",
        # Room for two slabs of depth, so the slab below has somewhere to land.
        room=(2 * deep[0], 512, 512), tile_shape=deep,
        voxel_size_um=VOXEL_UM, origin_um=ORIGIN_UM,
        channels=[Channel("488", window=(100, 4000)),
                  Channel("561", window=(100, 4000))],
        frames=3, piece=piece,
    ) as run:
        here = (0, 0, 0)
        run.write(np.full(deep, 1000, "uint16"), at=here, channel=0, frame=0)
        assert run.positions == 1

        run.write(np.full(deep, 2000, "uint16"), at=here, channel=1, frame=0)
        run.write(np.full(deep, 3000, "uint16"), at=here, channel=0, frame=2)
        run.write(np.full(deep, 1500, "uint16"), at=here, channel=0, frame=0)
        assert run.positions == 1, (
            "imaging a place again made a second image of it; everything recorded "
            "of one field of view should stay together"
        )

        # A slab of depth above the same y and x is a different place.
        run.write(np.full(deep, 4000, "uint16"), at=(deep[0], 0, 0))
        assert run.positions == 2
        view = run.path

    stored = _the_positions_in(view)
    assert len(stored) == 2

    # Everything written at the first place is in its image, in the right slots,
    # and the rewrite replaced what was there rather than landing beside it.
    import zarr
    held = zarr.open_array(str(stored[0] / "0"), mode="r")
    assert held.shape[:2] == (3, 2), "room for three moments and two colours"
    assert int(np.asarray(held[0, 0]).max()) == 1500, "the rewrite did not take"
    assert int(np.asarray(held[0, 1]).max()) == 2000, "the second colour is missing"
    assert int(np.asarray(held[2, 0]).max()) == 3000, "the later moment is missing"

    # And the map holds one entry per place, not one per picture written.
    listed = the_map_inside(view)
    places = [tuple(one["at"]) for one in listed["tiles"]]
    assert len(places) == len(set(places)) == 2, (
        f"the map holds {places}, so a place was written into it more than once"
    )
    assert (0, 0, 0) in places
    assert (deep[0], 0, 0) in places


def test_a_position_of_the_wrong_size_is_refused(tmp_path):
    """Refused rather than drawn in the wrong place.

    The view works out where each position lands from the size the run declared,
    so a position of another size would be placed wrongly with nothing on screen
    to say so.
    """
    folder = tmp_path / "experiment"
    with start_a_run(
        folder, name="overview", room=(TILE[0], 512, 512), tile_shape=TILE,
        voxel_size_um=VOXEL_UM, channels=[Channel("488", window=(0, 4000))],
        piece=PIECE,
    ) as run:
        run.write(_a_picture(0), at=(0, 0, 0))
        with pytest.raises(ValueError) as refused:
            run.write(np.zeros((1, 32, 32), "uint16"), at=(0, 0, 64))
    assert "declared" in str(refused.value)
