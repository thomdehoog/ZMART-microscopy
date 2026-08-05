"""Can somebody else's software open our images and put them in the right place?

Our own viewer reading our own images proves less than it looks. Both halves were
written here, so a misunderstanding shared between them cancels out and nothing
ever looks wrong. The way that misunderstanding shows up is when the images travel:
a colleague opens the run in their own tools and the specimen is somewhere else, or
every acquisition of the run is piled on top of the others at the stage's zero.

That is not a worry — it happened. `viz_studio/INTEROP.md` records it. OME-Zarr lets
an image say where it sits in two places: beside each resolution, or once beside the
block listing them all. We used to say it only in the second place. A great many
tools in the Python world read only the first, because it is the one the format makes
compulsory, so to all of them every image in every run began at zero.

So this test reads our images back with somebody else's reader rather than our own.
It uses `ngff-zarr`, which is a fair choice of stand-in for two reasons: it is what
`multiview-stitcher` and a good deal of the Python imaging ecosystem read OME-Zarr
through, and it is strict, taking the position only from the compulsory place. If our
images survive it, they will survive most readers.

`ngff-zarr` is not needed to run ZMART, so it is not a required dependency and these
tests simply skip when it is absent. To run them::

    python -m pip install ngff-zarr
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip(
    "ngff_zarr",
    reason="ngff-zarr is an optional check that our images travel; "
           "install it with `python -m pip install ngff-zarr`",
)

import ngff_zarr  # noqa: E402

from zmart_storage.canvas import Channel, TileCanvases  # noqa: E402

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
