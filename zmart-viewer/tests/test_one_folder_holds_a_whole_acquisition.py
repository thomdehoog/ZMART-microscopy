"""One folder is a whole acquisition: open it, move it, copy it, nothing is lost.

A run leaves one OME-Zarr image per position on disk, each complete in itself. That
is the right thing to store and the wrong thing to hand a viewer: neuroglancer
builds a drawing layer for every image it is given, so a few thousand positions do
not open in any useful sense.

The answer is a **view** — a small file saying which piece of one big picture is
which piece of which position. The viewer opens the view and sees a single ordinary
image, and not one voxel has been copied to make it.

**The runs here are smart experiments rather than plates**, and the difference is
worth holding in mind. A plate is a regular grid of wells, imaged the same way
throughout. A smart experiment is a wide survey at low magnification followed by
detailed scans whereever the survey found something worth a closer look — so the
positions are scattered rather than a raster, and one experiment usually holds more
than one *kind* of scan, at different magnifications. Each kind is a picture in its
own right and gets a view of its own; the last test is about exactly that.

These tests are about *where all that sits on disk*. The view can be a folder beside
the positions, which is the older arrangement and still the default, or it can hold
the positions inside itself::

    overview.ome.zarr/       <- open this; it is one whole picture
      .zattrs .zgroup        <- what the picture is
      0/ 1/ 2/               <- descriptions only, no picture at all
      zmart-links.json       <- which piece is which piece of which position
      positions/
        pos00000.ome.zarr/   <- a complete image in its own right
        pos00001.ome.zarr/

The second is worth having because there is then one thing to open and one thing to
copy, and no part of an acquisition can be separated from the rest of it by
accident. What it costs is that deleting that folder now deletes the acquisition
rather than only the view, so the tests below are careful about the one case the
writer *can* protect: throwing the view away deliberately must leave every position
exactly where it was.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import linking
import numpy as np
import pytest
from stores import discover

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from zmart_storage.canvas import Channel  # noqa: E402
from zmart_storage.cropped import TilesAndCanvas  # noqa: E402
from zmart_storage.linked import (  # noqa: E402
    PlacedTile,
    link_the_tiles,
    start_a_growing_view,
)

# Small on purpose: these tests are about where folders sit, not about how a
# picture looks, so the pictures only have to be different from one another.
TILE = (2, 64, 64)
GRID = 2
PIECE = 32
VOXEL_UM = (2.0, 0.35, 0.35)
ORIGIN_UM = (11.0, 5.5, 7.25)
VIEW_SHAPE = (TILE[0], GRID * TILE[1], GRID * TILE[2])

# The name of the subfolder the positions go in. One name, used by the tests and
# by the calls they make, so that a change to it cannot make a test pass by
# checking the wrong folder.
POSITIONS = "positions"


def _a_picture(seed: int) -> np.ndarray:
    """One position's picture, noisy so that two of them cannot be confused.

    A flat block would compare equal to another flat block, and a test comparing
    the bytes handed over against the bytes on disk would then pass whatever the
    pointers said.
    """
    rng = np.random.default_rng(seed)
    return (400 + rng.normal(0, 50, TILE)).clip(0, 4000).astype("uint16")


def _positions_written_inside(run: Path,
                              ome_zarr_version: str = "0.4") -> list[PlacedTile]:
    """Write a small raster of positions inside what will become the view's folder.

    This is the order an acquisition would use: the folder that will be the view is
    chosen first, and every position is written into ``positions`` inside it.

    ``ome_zarr_version`` chooses which generation of the format the positions are
    written in. The view is never told: it reads it out of the positions and
    matches them, because a view stored differently from what it points at would
    hand the browser bytes it cannot unpack.
    """
    inside = run / "plate.ome.zarr" / POSITIONS
    inside.mkdir(parents=True)
    writer = TilesAndCanvas.create(
        inside,
        name="pos",
        canvas_shape=VIEW_SHAPE,
        tile_shape=TILE,
        tile_step=TILE,
        tile_grid=(1, GRID, GRID),
        voxel_size_um=VOXEL_UM,
        origin_um=ORIGIN_UM,
        channels=[Channel("488", window=(0, 4000))],
        frames=1,
        chunk=PIECE,
        ome_zarr_version=ome_zarr_version,
    )
    placed = []
    for row in range(GRID):
        for column in range(GRID):
            where = writer.write(
                _a_picture(row * GRID + column),
                origin=(0, row * TILE[1], column * TILE[2]),
                channel=0,
                frame=0,
                tile_index=(0, row, column),
            )
            placed.append(PlacedTile(
                store=where, lands_at=(0, row * TILE[1], column * TILE[2])))
    writer.close()
    return placed


def _a_plate_in_one_folder(run: Path):
    """A finished plate whose view holds its positions inside itself."""
    placed = _positions_written_inside(run)
    view = link_the_tiles(run, name="plate", tiles=placed,
                          view_shape=VIEW_SHAPE, keeps_its_tiles_in=POSITIONS)
    return placed, view


def test_the_viewer_is_offered_one_image_rather_than_every_position(tmp_path):
    """The whole point: however many positions there are, the viewer sees one image.

    This is what makes a large plate open at all. Neuroglancer builds a drawing
    layer per image, so being handed the positions themselves is what does not
    scale — and the check that it is handed exactly one is therefore the check that
    the arrangement is doing its job.
    """
    placed, view = _a_plate_in_one_folder(tmp_path / "run")
    assert len(placed) == GRID * GRID

    root, images = discover(view.path)
    assert images == ["plate.ome.zarr"], (
        "the viewer should be offered the view alone; the positions inside it are "
        "where the picture lives and are not layers of their own"
    )
    assert root == view.path.parent


def test_nothing_of_ours_is_left_inside_an_image_folder(tmp_path):
    """Every ``.ome.zarr`` folder holds zarr's own files and nothing else.

    This is what keeps the run readable by other people's software. Anything at all
    added inside an image folder makes zarr complain the moment another program
    asks the image what it contains — *"Object at zmart-links.json is not
    recognized as a component of a Zarr hierarchy"*. Nothing breaks and every
    picture still reads, but a colleague opening the run in napari or Fiji should
    not have to work out whether a warning about a file of ours matters.

    Our own files live beside the images instead, in ``zmart-links`` and
    ``zmart-coverage``, where zarr has no opinion about them. The same reasoning
    is set out in :mod:`zmart_storage.coverage`, which measured it first.
    """
    placed, view = _a_plate_in_one_folder(tmp_path / "run")

    # What zarr itself puts in an image folder: the descriptions, and the numbered
    # levels. Anything else is ours and should not be here.
    belongs_to_zarr = {".zattrs", ".zgroup", ".zarray", "zarr.json"}

    for image in [view.path, *(tile.store for tile in placed)]:
        for child in image.iterdir():
            if child.name in belongs_to_zarr:
                continue
            # A level of the image, named in its own description.
            if child.is_dir() and child.name.lstrip("0123456789") == "":
                continue
            # The positions subfolder is the one deliberate exception, and it holds
            # images rather than files of ours. It is what this arrangement is for.
            if child.name == POSITIONS:
                continue
            raise AssertionError(
                f"{child.name} sits inside the image {image.name}, where zarr will "
                "complain about it to anyone who opens the run in other software"
            )


def test_every_position_is_still_a_complete_image_on_its_own(tmp_path):
    """A position inside the view is an ordinary OME-Zarr image, not a fragment.

    This is the property that makes the arrangement safe to adopt. Nothing about
    being pointed at changes a position, so it can be opened on its own, handed to
    somebody else, or read by any other tool.
    """
    placed, _ = _a_plate_in_one_folder(tmp_path / "run")
    for tile in placed:
        described = json.loads((tile.store / ".zattrs").read_text(encoding="utf-8"))
        assert described.get("multiscales"), (
            f"{tile.store.name} should describe itself as an image in its own right"
        )
        assert (tile.store / "0").is_dir()


def test_the_view_holds_no_picture_and_hands_over_the_position_s_own_bytes(tmp_path):
    """Nothing is copied: the bytes served are the position's own file, untouched.

    Compared byte for byte against the file on disk rather than by looking at the
    picture, because that is the actual claim — the server hands the file over
    without decoding anything.
    """
    placed, view = _a_plate_in_one_folder(tmp_path / "run")

    found = linking.the_bytes_behind(view.path, "0/0/0/0/0/0")
    assert found is not None, (
        "with no pointer the view would answer 'nothing here' and draw blank at "
        "full size"
    )

    root = view.path.parent
    served = (root / found.path).resolve()
    assert served.exists()
    # The guard the server relies on: a pointer can no more reach out of the
    # opened folder than any other request can.
    assert root in served.parents

    its_own = placed[0].store / "0" / "0" / "0" / "0" / "0" / "0"
    assert served.read_bytes() == its_own.read_bytes()

    # And the view's own full-size copy really is empty — it holds descriptions
    # and nothing else, which is what "nothing is copied" means on disk. A piece
    # of picture is any file that is not one of the two that describe the array.
    describing = {".zarray", ".zattrs", "zarr.json"}
    picture = [one.name for one in (view.path / "0").rglob("*")
               if one.is_file() and one.name not in describing]
    assert picture == [], (
        f"the view's full-size copy should hold no picture at all, found {picture}"
    )


def test_the_view_describes_itself_the_way_the_positions_are_actually_stored(tmp_path):
    """What the description *says*, not merely that a description is there.

    This is the check that matters most and is the easiest to skip. Handing over a
    position's file untouched only works if the view has told the browser to
    expect exactly that: the same kind of number in a voxel, the same compression,
    and above all the same piece size. A view that declared a different piece size
    would still open, still draw, and show a picture of noise — nothing anywhere
    would report a fault.

    So the two descriptions are read off disk and compared with each other, rather
    than either being compared against a number written into this test. A number
    written here would only say what somebody once believed.
    """
    placed, view = _a_plate_in_one_folder(tmp_path / "run")

    of_the_view = json.loads((view.path / "0" / ".zarray").read_text(encoding="utf-8"))
    of_a_position = json.loads(
        (placed[0].store / "0" / ".zarray").read_text(encoding="utf-8"))

    for said in ("chunks", "dtype", "compressor", "filters", "dimension_separator"):
        assert of_the_view[said] == of_a_position[said], (
            f"the view and the positions disagree about {said}, so the bytes handed "
            "over would be unpacked wrongly and drawn as noise"
        )

    # The view covers the whole raster; each position covers its own part of it.
    assert of_the_view["shape"][-2:] == [GRID * TILE[1], GRID * TILE[2]]
    assert of_a_position["shape"][-2:] == [TILE[1], TILE[2]]

    # And the view has to sit where the positions sit, in micrometres, or the
    # specimen would be drawn away from where the stage recorded it.
    described = json.loads((view.path / ".zattrs").read_text(encoding="utf-8"))
    multiscale = described["multiscales"][0]
    full_size = multiscale["datasets"][0]["coordinateTransformations"]
    scale = next(one for one in full_size if one["type"] == "scale")["scale"]
    corner = next(
        one for one in full_size if one["type"] == "translation")["translation"]
    assert scale[-3:] == list(VOXEL_UM)
    assert corner[-3:] == list(ORIGIN_UM)

    # Every zoomed-out copy sits at that same corner and doubles the voxel size,
    # because shrinking counts from the picture's corner and leaves it where it is.
    for level, dataset in enumerate(multiscale["datasets"]):
        this = dataset["coordinateTransformations"]
        its_scale = next(one for one in this if one["type"] == "scale")["scale"]
        its_corner = next(
            one for one in this if one["type"] == "translation")["translation"]
        assert its_corner[-3:] == list(ORIGIN_UM)
        assert its_scale[-2:] == [VOXEL_UM[1] * 2 ** level, VOXEL_UM[2] * 2 ** level]

    # The colours the view offers are the ones the positions recorded, including
    # the display window. Reading start and end matters: min and max are the
    # camera's whole range, and opening a run with those shows a nearly black
    # picture that stays that way until somebody drags a slider.
    channel = described["omero"]["channels"][0]
    assert channel["label"] == "488"
    assert (channel["window"]["start"], channel["window"]["end"]) == (0, 4000)


def test_throwing_the_view_away_leaves_every_position_where_it_was(tmp_path):
    """The one danger of this arrangement, and the half of it the writer can control.

    Declaring an image normally empties its folder, which would take the positions
    with it — and since the view holds no picture of its own, that would be the
    whole acquisition gone with nothing to say so. Rebuilding the view must cost a
    few kilobytes of description and not a single voxel.
    """
    placed, view = _a_plate_in_one_folder(tmp_path / "run")
    positions = view.path / POSITIONS
    before = sorted(str(one.relative_to(positions)) for one in positions.rglob("*"))
    assert before, "the positions should be there to begin with"

    link_the_tiles(tmp_path / "run", name="plate", tiles=placed,
                   view_shape=VIEW_SHAPE, keeps_its_tiles_in=POSITIONS,
                   discard_existing_run=True)

    after = sorted(str(one.relative_to(positions)) for one in positions.rglob("*"))
    assert after == before


def test_rebuilding_the_view_clears_what_the_last_one_wrote(tmp_path):
    """Sparing the positions must not also spare a stale copy of the view.

    Stepping around the positions is deliberate; leaving an old zoomed-out copy
    behind would not be. A copy left from a longer pyramid would still be served,
    and an operator would see a picture that no run had produced.
    """
    placed, view = _a_plate_in_one_folder(tmp_path / "run")
    left_behind = view.path / "9"
    left_behind.mkdir()
    (left_behind / "stale").write_bytes(b"from a view that no longer exists")

    link_the_tiles(tmp_path / "run", name="plate", tiles=placed,
                   view_shape=VIEW_SHAPE, keeps_its_tiles_in=POSITIONS,
                   discard_existing_run=True)

    assert not left_behind.exists()
    assert (view.path / POSITIONS).is_dir()


def test_a_position_left_outside_the_folder_is_refused(tmp_path):
    """A view claiming to hold its positions must really hold them.

    If it did not, the folder would copy without complaint and the picture would
    come out with holes in it at the far end, with nothing on screen to say which
    positions had been left behind. Refusing is the only honest answer.
    """
    run = tmp_path / "run"
    placed = _positions_written_inside(run)

    elsewhere = run / "somewhere_else"
    elsewhere.mkdir(parents=True)
    moved = elsewhere / placed[0].store.name
    shutil.copytree(placed[0].store, moved)
    astray = [PlacedTile(store=moved, lands_at=placed[0].lands_at), *placed[1:]]

    with pytest.raises(ValueError) as refused:
        link_the_tiles(run, name="plate", tiles=astray,
                       view_shape=VIEW_SHAPE, keeps_its_tiles_in=POSITIONS)
    said = str(refused.value)
    assert POSITIONS in said
    assert str(moved) in said, "the position in the wrong place should be named"


def test_a_run_still_arriving_can_be_built_this_way_too(tmp_path):
    """The order a microscope actually works in: declare the view, then image.

    This is the comfortable way round. The view is declared while its folder is
    still empty, so nothing has to be moved afterwards, and each position is
    written inside it and handed over as it lands. An operator can open the folder
    at any point and watch the picture fill in.
    """
    run = tmp_path / "run"
    placed = _positions_written_inside(run)

    growing = start_a_growing_view(
        run, like=placed[0], view_shape=VIEW_SHAPE, name="plate",
        keeps_its_tiles_in=POSITIONS, discard_existing_run=True,
    )
    with growing as view:
        for tile in placed:
            view.add(tile)
        assert view.tiles == len(placed)
    assert (run / "plate.ome.zarr" / POSITIONS).is_dir()

    found = linking.the_bytes_behind(run / "plate.ome.zarr", "0/0/0/0/0/0")
    assert found is not None
    served = (run / found.path).resolve()
    assert served.read_bytes() == (
        placed[0].store / "0" / "0" / "0" / "0" / "0" / "0").read_bytes()


def test_the_newer_format_works_in_one_folder_too(tmp_path):
    """The same arrangement, written as OME-Zarr 0.5 rather than 0.4.

    Worth stating plainly, because the two names are easy to tangle. **Zarr** is
    the general way of keeping a large array as many small files; it knows nothing
    about microscopes. **OME-Zarr** is that, plus a short agreed description saying
    what the axes mean, how large a voxel is in micrometres, and where the picture
    sits on the stage. The versions run in step: OME-Zarr 0.4 is written on zarr
    version 2, and OME-Zarr 0.5 on zarr version 3. Choosing "0.5" and choosing
    "zarr 3" are the same choice said two ways.

    What actually differs on disk is where the description lives and what the
    pieces of picture are called — ``zarr.json`` rather than ``.zattrs``, and a
    ``c`` in front of a piece's numbers. Both matter here, because pointing at a
    piece means naming it exactly right; a spelling that is nearly right gives a
    file that exists nowhere, and the picture comes out blank at full size with
    nothing to say why.
    """
    run = tmp_path / "run"
    placed = _positions_written_inside(run, ome_zarr_version="0.5")
    view = link_the_tiles(run, name="plate", tiles=placed,
                          view_shape=VIEW_SHAPE, keeps_its_tiles_in=POSITIONS)

    # The newer generation keeps its description here, and the older one does not.
    assert (view.path / "zarr.json").is_file()
    assert not (view.path / ".zattrs").exists()

    root, images = discover(view.path)
    assert images == ["plate.ome.zarr"]

    # The list of pointers records the spelling rather than assuming one, so the
    # test reads it from there instead of hard-coding what it expects to find.
    listed = linking.the_map_inside(view.path)
    assert listed["prefix"] == "c", (
        "0.5 files a piece under a 'c' part of its own; without that recorded, "
        "every request would be answered 'nothing here'"
    )

    asked_for = f"0/{listed['prefix']}/0/0/0/0/0"
    found = linking.the_bytes_behind(view.path, asked_for)
    assert found is not None, f"no pointer for {asked_for}"
    served = (root / found.path).resolve()
    assert served.exists()
    assert served.read_bytes() == (
        placed[0].store / "0" / "c" / "0" / "0" / "0" / "0" / "0").read_bytes()

    # A requirement of the 0.5 specification, and one that is easy to miss because
    # nothing complains when it is absent: each level of the image has to name its
    # own dimensions, and those names have to be the ones the group's axes give.
    # It is what lets a reader open a single level and still know which dimension
    # is depth and which is time. Checked against each other rather than against a
    # list written here, since the point is that the two agree.
    described = json.loads((view.path / "zarr.json").read_text(encoding="utf-8"))
    axes = [one["name"]
            for one in described["attributes"]["ome"]["multiscales"][0]["axes"]]
    assert described["attributes"]["ome"]["version"] == "0.5"
    for level in range(view.levels):
        array = json.loads(
            (view.path / str(level) / "zarr.json").read_text(encoding="utf-8"))
        assert array.get("dimension_names") == axes, (
            f"level {level} of the view does not name its dimensions the way the "
            "axes do, which the specification requires"
        )

    # The positions the view points at have to satisfy it too — they are ordinary
    # images that somebody may open on their own.
    of_a_position = json.loads(
        (placed[0].store / "0" / "zarr.json").read_text(encoding="utf-8"))
    assert of_a_position.get("dimension_names") == axes

    # Sparing the positions has to work the same way whichever generation is used.
    positions = view.path / POSITIONS
    before = sorted(str(one.relative_to(positions)) for one in positions.rglob("*"))
    link_the_tiles(run, name="plate", tiles=placed, view_shape=VIEW_SHAPE,
                   keeps_its_tiles_in=POSITIONS, discard_existing_run=True)
    after = sorted(str(one.relative_to(positions)) for one in positions.rglob("*"))
    assert after == before


def test_the_view_beside_its_positions_still_works_exactly_as_before(tmp_path):
    """Leaving the option out must change nothing at all.

    The older arrangement — a view in a folder beside the positions — is still the
    default, and a great deal is measured against it. This is the check that the
    new option is an option rather than a change.
    """
    run = tmp_path / "run"
    run.mkdir(parents=True)
    writer = TilesAndCanvas.create(
        run, name="pos", canvas_shape=VIEW_SHAPE, tile_shape=TILE,
        tile_step=TILE, tile_grid=(1, GRID, GRID), voxel_size_um=VOXEL_UM,
        origin_um=ORIGIN_UM, channels=[Channel("488", window=(0, 4000))],
        frames=1, chunk=PIECE,
    )
    placed = []
    for row in range(GRID):
        for column in range(GRID):
            where = writer.write(
                _a_picture(row * GRID + column),
                origin=(0, row * TILE[1], column * TILE[2]),
                channel=0, frame=0, tile_index=(0, row, column))
            placed.append(PlacedTile(
                store=where, lands_at=(0, row * TILE[1], column * TILE[2])))
    writer.close()

    view = link_the_tiles(run, name="plate", tiles=placed, view_shape=VIEW_SHAPE)

    assert view.path == run / "plate.ome.zarr"
    assert not (view.path / POSITIONS).exists()
    found = linking.the_bytes_behind(view.path, "0/0/0/0/0/0")
    assert found is not None
    assert (run / found.path).resolve().exists()
