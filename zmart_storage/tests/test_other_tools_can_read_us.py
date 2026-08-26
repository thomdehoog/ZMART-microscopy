"""Can somebody else's software open our images and put them in the right place?

Our own viewer reading our own images proves less than it looks. Both halves were
written here, so a misunderstanding shared between them cancels out and nothing
ever looks wrong. The way that misunderstanding shows up is when the images travel:
a colleague opens the run in their own tools and the specimen is somewhere else, or
every acquisition of the run is piled on top of the others at the stage's zero.

That is not a worry — it happened. `zmart-viewer/INTEROP.md` records it. OME-Zarr lets
an image say where it sits in two places: beside each resolution, or once beside the
block listing them all. We used to say it only in the second place. A great many
tools in the Python world read only the first, because it is the one the format makes
compulsory, so to all of them every image in every run began at zero.

So these tests read our images back with somebody else's readers rather than our own.

Most of them use `ngff-zarr`, which is a fair choice of stand-in for two reasons: it
is what `multiview-stitcher` and a good deal of the Python imaging ecosystem read
OME-Zarr through, and it is strict, taking the position only from the compulsory
place. If our images survive it, they will survive most readers.

The last two tests use `ngio` instead, and only ask whether the image opens at all.
That is a different question and worth asking separately, because a reader can be
perfectly happy with where an image sits and still refuse the file for some other
reason — which is precisely what happened with the brightness window on a channel,
and went unnoticed here for exactly as long as nothing in this file opened an image
with ngio.

They ask it of both kinds of image this project writes. One is a **position**: an
ordinary image holding the voxels a camera recorded. The other is a **view**: the
single picture the operator is handed, which holds no full-size voxels of its own
and points at the positions instead, so a run of ten thousand places opens as one
image rather than ten thousand. A view is meant to be an ordinary OME-Zarr image in
every other respect, and that is a promise worth testing rather than assuming — it
has already been broken once, by a view whose every resolution ended up saying
where it sat twice over, which ngio refuses outright.

Neither `ngff-zarr` nor `ngio` is needed to run ZMART, so neither is a required
dependency and these tests simply skip when they are absent. To run them::

    python -m pip install ngff-zarr ngio
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip(
    "ngff_zarr",
    reason="ngff-zarr is an optional check that our images travel; "
           "install it with `python -m pip install ngff-zarr`",
)

import ngff_zarr  # noqa: E402

from zmart_storage.canvas import Channel, TileCanvases  # noqa: E402
from zmart_storage.positions import start_a_run  # noqa: E402

# Where the run was declared to begin, in microns from the stage's zero, as
# ``(z, y, x)``. Deliberately none of them zero and none of them round: a corner of
# zero would pass whether or not the position was written at all, which is precisely
# the fault being guarded against.
CORNER = (10.0, 250.5, 900.25)

# How large one voxel is, in microns, as ``(z, y, x)``. The depth is much larger than
# the width, as it is on a real microscope, so that an axis read back in the wrong
# order is obvious rather than plausible.
VOXEL_UM = (2.0, 0.35, 0.35)

TILE = (2, 128, 128)

# The stage steps by a whole tile, so the tiles sit edge to edge without overlapping.
# That is the rule for a run written into one image, and declaring anything else here
# would be refused before a single file was written.
BUTTED_UP = (2, 128, 128)


def _a_run(folder: Path, version: str) -> TileCanvases:
    """Declare an ordinary little run, at a known corner and a known voxel size.

    Both generations of OME-Zarr are tried, because they keep the description in
    quite different places — 0.4 in a file beside the image, 0.5 inside the image's
    own — and a reader can perfectly well manage one and not the other.
    """
    return TileCanvases.create(
        folder,
        name="overview",
        canvas_shape=(2, 640, 640),
        tile_shape=TILE,
        tile_step=BUTTED_UP,
        voxel_size_um=VOXEL_UM,
        origin_um=CORNER,
        channels=[Channel("488")],
        levels=2,
        chunk=64,
        ome_zarr_version=version,
    )


def _a_run_offered_as_one_picture(folder: Path, version: str) -> Path:
    """Image four places one at a time, and hand back the picture that joins them.

    This is the other kind of image this project writes. Each place becomes an
    ordinary image of its own, and the view is the single picture the operator
    opens: it holds no full-size voxels, and answers every request for one by
    handing over a file that already belongs to a position.

    Four places rather than one, because a view over a single position could
    describe itself correctly by accident, simply by copying what that position
    said about itself.
    """
    run = start_a_run(
        folder,
        name="overview",
        room=(TILE[0], 640, 640),
        tile_shape=TILE,
        voxel_size_um=VOXEL_UM,
        origin_um=CORNER,
        channels=[Channel("488", window=(0, 4000))],
        piece=TILE[1],
        ome_zarr_version=version,
    )
    for at in ((0, 0, 0), (0, 0, 128), (0, 128, 0), (0, 128, 128)):
        run.write(np.zeros(TILE, "uint16"), at=at)
    return run.finish().path


@pytest.mark.parametrize("version", ["0.4", "0.5"])
def test_another_reader_finds_our_image_where_we_put_it(tmp_path, version):
    """The whole point: an outside reader agrees with us about where the image sits.

    If this fails, images written by this run will open in other people's software
    at the stage's zero — every acquisition of the run stacked on the others, which
    looks like a microscope that cannot repeat itself rather than like a file that
    is wrong.
    """
    canvases = _a_run(tmp_path, version)
    (store,) = canvases.paths
    canvases.close()

    multiscales = ngff_zarr.from_ngff_zarr(store)
    finest = multiscales.images[0]

    for axis, expected in zip(("z", "y", "x"), CORNER, strict=True):
        assert finest.translation[axis] == pytest.approx(expected), (
            f"reading {store.name} with ngff-zarr puts its {axis} corner at "
            f"{finest.translation[axis]}, where the run was declared from "
            f"{expected}. An image that says where it sits only in the optional "
            f"place reads as beginning at zero to every tool that looks in the "
            f"compulsory one."
        )


@pytest.mark.parametrize("version", ["0.4", "0.5"])
def test_another_reader_agrees_how_large_a_voxel_is(tmp_path, version):
    """Voxel size travels with the position, and a scale bar rests on it.

    Checked in the same breath because the two are written together and a change to
    one is very likely to disturb the other.
    """
    canvases = _a_run(tmp_path, version)
    (store,) = canvases.paths
    canvases.close()

    multiscales = ngff_zarr.from_ngff_zarr(store)
    finest = multiscales.images[0]

    for axis, expected in zip(("z", "y", "x"), VOXEL_UM, strict=True):
        assert finest.scale[axis] == pytest.approx(expected), (
            f"reading {store.name} with ngff-zarr says its voxels are "
            f"{finest.scale[axis]} microns in {axis}, where the run declared "
            f"{expected}. A specimen measured against this would be the wrong size."
        )


@pytest.mark.parametrize("version", ["0.4", "0.5"])
def test_the_smaller_copies_begin_at_the_same_corner(tmp_path, version):
    """Zooming out must not slide the specimen sideways.

    Each smaller copy covers twice as much ground per voxel, but it still begins at
    the same place on the stage. Were a copy to say otherwise, the specimen would
    appear to shift as the operator zoomed out — a fault that is easy to see and
    very hard to explain, because the picture is perfectly good at every single
    zoom level on its own.

    This is also where this project's choice of the voxel's **corner** over its
    middle would show up if somebody changed it: under the other reading each copy
    carries a translation of half its own voxel, so these numbers would drift apart
    level by level rather than staying put. `zmart_storage/VOXEL_PLACEMENT.md` sets
    out why the corner was chosen, and this test is what would notice the change.
    """
    canvases = _a_run(tmp_path, version)
    (store,) = canvases.paths
    canvases.close()

    multiscales = ngff_zarr.from_ngff_zarr(store)
    assert len(multiscales.images) == 2, "this run was declared with two copies"

    for level, image in enumerate(multiscales.images):
        for axis, expected in zip(("z", "y", "x"), CORNER, strict=True):
            assert image.translation[axis] == pytest.approx(expected), (
                f"copy {level} of {store.name} begins at {image.translation[axis]} "
                f"in {axis}, where the full-size copy begins at {expected}. The "
                f"specimen would appear to move when the operator zooms out."
            )


@pytest.mark.parametrize("version", ["0.4", "0.5"])
def test_ngio_can_open_what_we_wrote(tmp_path, version):
    """A second outside reader, and a stricter one, simply opens our image.

    Writing in a shared format is only worth the trouble if other people's
    software will open the result, and this is the test that notices when it
    stops doing so. It is deliberately not asking anything clever: it opens the
    image and expects to be handed something back. Failing to open at all is the
    way this kind of fault actually arrives, and no amount of checking numbers
    inside a file catches it.

    `ngio` is used here because it is stricter than most readers about the parts
    of the description that are meant to be complete, and it refuses an image
    outright rather than quietly doing something reasonable. That is exactly the
    quality wanted in a test. It is how the channel-window fault was found: an
    image whose describing block names a channel without a full brightness window
    would not open in ngio at all, and nothing in this file noticed, because
    nothing in this file had ever asked ngio to open anything.

    Both generations of OME-Zarr are tried, because ngio reads both and because
    they keep the description in quite different places, so one can be right while
    the other is wrong.

    `ngio` is not needed to run ZMART, so this skips when it is absent, along with
    the rest of this file. To install it::

        python -m pip install ngio
    """
    ngio = pytest.importorskip(
        "ngio",
        reason="ngio is an optional check that our images open elsewhere; "
               "install it with `python -m pip install ngio`",
    )

    canvases = _a_run(tmp_path, version)
    (store,) = canvases.paths
    canvases.close()

    try:
        opened = ngio.open_ome_zarr_container(str(store))
    except Exception as refusal:
        raise AssertionError(
            f"ngio refused to open {store.name}, written as OME-Zarr {version}, "
            f"saying: {refusal}. An image nobody else's software will open is not "
            f"really written in a shared format, whatever it says inside, and a "
            f"colleague handed this run could do nothing with it at all."
        ) from refusal

    assert opened is not None, (
        f"ngio opened {store.name} without complaint but handed back nothing, so "
        f"there is no image there for anyone else to work with."
    )


@pytest.mark.parametrize("version", ["0.4", "0.5"])
def test_ngio_can_open_the_picture_the_operator_is_handed(tmp_path, version):
    """The same strict reader, asked to open a view rather than a single position.

    This is the image that matters most, because it is the one anybody actually
    opens. A run of ten thousand places is offered as a single picture that holds
    no voxels of its own and points at the positions instead — and the whole reason
    that arrangement is worth having is that the picture is still an ordinary
    OME-Zarr image, so the viewer, and a colleague, and a public archive can all
    treat it as one.

    Nothing enforces that on its own. The view is described by first letting the
    ordinary writer describe an image and then correcting where it says it sits, so
    it can drift out of step with that writer without a single voxel changing. That
    is exactly what happened: the writer began stating the place beside each
    resolution, the view went on adding its own beside them, and every resolution
    ended up saying where it sat twice. The standard allows a resolution at most one
    place beside its scale, so ngio stopped opening views altogether — while every
    test in the suite went on passing, because the position beside this one was
    still perfectly well formed.

    So this asks the same question of the view, and asks it of both generations of
    the format, since the description lives in quite different places in each.
    """
    ngio = pytest.importorskip(
        "ngio",
        reason="ngio is an optional check that our images open elsewhere; "
               "install it with `python -m pip install ngio`",
    )

    view = _a_run_offered_as_one_picture(tmp_path, version)

    try:
        opened = ngio.open_ome_zarr_container(str(view))
    except Exception as refusal:
        raise AssertionError(
            f"ngio refused to open the view {view.name}, written as OME-Zarr "
            f"{version}, saying: {refusal}. The view is the picture the operator "
            f"opens, so a run whose view no other software will accept is a run "
            f"that cannot be looked at — even though every position inside it is "
            f"perfectly well written and would open on its own."
        ) from refusal

    assert opened is not None, (
        f"ngio opened the view {view.name} without complaint but handed back "
        f"nothing, so there is no picture there for the operator to look at."
    )
