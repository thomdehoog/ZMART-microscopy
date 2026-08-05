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
from zmart_storage.positions import POSITIONS_FOLDER, start_a_run

# Small on purpose. These tests are about how a run is arranged, not about how a
# picture looks, so the pictures only have to differ from one another.
TILE = (1, 64, 64)
PIECE = 64
ACROSS = 3
VOXEL_UM = (2.0, 0.35, 0.35)

# Deliberately not the origin: a run at nought would let a mistake that lost the
# corner entirely still look right.
ORIGIN_UM = (11.0, 5.5, 7.25)


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

    positions = folder / POSITIONS_FOLDER / "overview"
    stored = sorted(one.name for one in positions.iterdir())
    assert len(stored) == ACROSS * ACROSS, (
        "one image per place on the stage, and nothing else in the positions folder"
    )
    assert all(name.endswith(".ome.zarr") for name in stored), (
        f"something that is not a position was left in the positions folder: {stored}"
    )


def test_the_picture_holds_no_full_size_voxels_of_its_own(tmp_path):
    """Nothing is copied, which is the whole reason for this arrangement.

    The view's full-size level is a description and nothing else: every voxel of
    it is answered by handing over a position's own file. The smaller copies *are*
    written, because these positions keep none of their own to point at, and they
    come to about a quarter of one picture rather than a second copy of the run.
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
    _a_run(folder)
    positions = sorted((folder / POSITIONS_FOLDER / "overview").iterdir())

    corners = []
    for store in positions:
        described = json.loads((store / "zarr.json").read_text(encoding="utf-8"))
        multiscale = described["attributes"]["ome"]["multiscales"][0]
        assert multiscale["datasets"], f"{store.name} describes no picture"
        moved = [one for one in multiscale.get("coordinateTransformations") or []
                 if one["type"] == "translation"]
        assert moved, f"{store.name} does not say where on the stage it was imaged"
        corners.append(tuple(moved[0]["translation"][-2:]))

    assert len(set(corners)) == len(positions), (
        "two positions claim the same place on the stage, so they would be piled "
        "on top of one another when the folder is opened"
    )
    # The run's own corner is where the first position sits, not nought.
    assert min(corners) == (ORIGIN_UM[1], ORIGIN_UM[2])


def test_nothing_of_ours_is_inside_an_image(tmp_path):
    """Every ``.ome.zarr`` folder holds zarr's own files and the levels, nothing else.

    Anything else in there makes zarr complain to whoever opens the run in other
    software, which is most of the reason for writing OME-Zarr at all.
    """
    folder = tmp_path / "experiment"
    view, _ = _a_run(folder)
    belongs_to_zarr = {".zattrs", ".zgroup", ".zarray", "zarr.json"}

    images = [view, *(folder / POSITIONS_FOLDER / "overview").iterdir()]
    for image in images:
        for child in image.iterdir():
            if child.name in belongs_to_zarr:
                continue
            if child.is_dir() and child.name.lstrip("0123456789") == "":
                continue
            raise AssertionError(
                f"{child.name} sits inside the image {image.name}, where zarr "
                "warns anyone who opens it"
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
    stored = list((folder / POSITIONS_FOLDER / "overview").iterdir())
    assert len(stored) == ACROSS * ACROSS

    listed = json.loads(
        (folder / "zmart-links" / "overview.ome.zarr.json").read_text(encoding="utf-8"))
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
