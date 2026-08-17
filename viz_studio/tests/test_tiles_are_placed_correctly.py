"""Is each tile drawn in the place its own metadata says it belongs?

A mesoSPIM does not record one image. It records a family of sibling OME-Zarr
stores — one per tile and channel — and each store carries the stage position it
was taken at, written into its own description as a ``translation``. The viewer
hands the whole family to the engine at once, and the engine is expected to put
each piece where its translation says. That single step is what turns a pile of
separate tiles into one specimen on screen.

Everything else in this suite checks that *something* was drawn. That is a
genuinely useful question, and it was missing for a long time, but it cannot tell
the difference between a specimen assembled correctly and a specimen assembled
wrongly. A viewer that ignored translations altogether and stacked every tile at
the origin would draw a perfectly convincing picture: bright, full of structure,
one tile's worth of specimen where there should have been forty. A viewer that
read the y translation into the x place, or got the sign the wrong way round,
would draw a mosaic scrambled or mirrored. All of those look healthy to a test
that only asks whether the panel is blank.

That is the worst kind of fault a microscopy viewer can have, because the
operator has no way of knowing. They are looking at a picture, judging their
experiment from it, and it is not the picture their specimen would make. So the
tests here ask a narrower and more awkward question: **where** on screen did each
tile land, and is that where its translation put it?

Two rules are followed throughout, and both of them are there because this
project has been caught by the alternative before.

*The verdict always comes from the photograph.* Nothing here asks the engine where
it thinks a tile is, reads a layer's transform, or inspects the coordinate space.
Those numbers are the very thing under test — they are the engine's own account of
its work, and a viewer that mis-read a translation would report its mistake to us
in a perfectly self-consistent way. The engine's state is used in one place only,
to decide *when* it is fair to take the photograph.

*Only relationships between tiles are asserted, never absolute screen positions.*
How far the engine chooses to zoom in, and where it chooses to centre the view,
are its own business and may reasonably change. What may not change is that two
tiles recorded one tile-width apart are drawn one tile-width apart, that the one
recorded further along an axis is drawn further along that axis, and that a
coarser acquisition takes up proportionally more room. Those statements survive
any zoom, so they can be asserted firmly instead of loosely.

One finding along the way is worth knowing, because for a while it was written
down here as a curiosity and it was in fact a fault. The flat view used to draw
the picture as a mirror image left to right: the axis the data calls x increased
towards the *left* of the screen. It applied to the pixels inside a single tile
exactly as it applied to the placement of tiles, so a mosaic still assembled
seamlessly and nothing here noticed — but every picture an operator looked at was
reflected. That has been put right; ``CONTROLS.md`` §1a says what was changed and
``test_the_picture_is_not_mirrored.py`` keeps it that way.

The tests below were written before it was, and they are deliberately left as
they were. The one that cares about direction takes its bearings from the image
itself rather than from an assumption about which way the screen runs — see
``test_a_tile_further_along_the_stage_is_drawn_further_along_the_picture`` — and
that remains the right way to write a test about metadata, because it asks only
that the placing of tiles agrees with the pixels inside them. Which way round the
screen itself is drawn is a separate question, and it now has a file of its own.
"""

from __future__ import annotations

import io
import json
import threading
from pathlib import Path

import numpy as np
from server import make_server

# The size of one tile, in voxels and in micrometres. Small enough that several of
# them fit on screen at once with clear space in between, which is what makes the
# gaps measurable; large enough that a tile is an unmistakable patch of light
# rather than a handful of pixels.
SIDE = 96
VOXEL_UM = (2.0, 0.5, 0.5)
TILE_UM = SIDE * VOXEL_UM[2]

# The intensity window every store here declares, and the two brightnesses used to
# tell one tile from another in a photograph. The format lets a store say how it
# would like to be displayed, and the viewer honours that in preference to
# measuring the pixels, so these come out at predictable shades of grey: the
# bright value saturates to white and the dim value lands a little under a third of
# the way up. There is a wide, empty band between them, which is what makes "which
# of the two tiles is this patch?" a safe question to ask of a screenshot.
WINDOW = (0, 4000)
BRIGHT = 3900
DIM = 1300

# Where the two brightnesses sit once drawn, on the usual 0-255 scale, and the
# level below which a pixel counts as unimaged ground rather than specimen. The
# floor is the same one the rest of the suite uses (see ``pixels.py``): well above
# the near-black of an empty region and well below any real signal, so nothing here
# is sensitive to exactly where it is set.
GROUND = 40
BRIGHT_ENOUGH = 170


def write_tile(
    store: Path,
    *,
    y_um: float = 0.0,
    x_um: float = 0.0,
    voxel_um: tuple[float, float, float] = VOXEL_UM,
    side: int = SIDE,
    value: int = BRIGHT,
    ramp: bool = False,
) -> Path:
    """Write one single-tile OME-Zarr store, placed on the stage where asked.

    ``y_um`` and ``x_um`` are the stage position this tile was taken at, in
    micrometres, and they are written into the store's description as a
    ``translation`` beside the ``scale`` that says how big a voxel is. That pair is
    the whole subject of this file: the scale says how large the tile is, the
    translation says where it sits, and between them they decide where on screen
    the engine should draw it.

    ``value`` is the brightness to fill the tile with, which is how one tile is
    told from another in a photograph. With ``ramp`` the tile instead gets a
    gradient that grows along its own x axis, from dim at the first voxel to bright
    at the last. That is used by exactly one test, which needs the tile to say
    which way round the picture is drawn.

    The files are written by hand rather than through the zarr library, for the
    same reason the other tests here do it: the tile is a single small plane, so
    writing four short files is quicker and much more direct than persuading a
    library to produce the translation we want.

    Returns the path to the store it wrote.
    """
    level = store / "0"
    level.mkdir(parents=True, exist_ok=True)
    (store / ".zgroup").write_text('{"zarr_format": 2}', encoding="utf-8")
    (level / ".zarray").write_text(
        json.dumps(
            {
                "zarr_format": 2,
                "shape": [1, 1, side, side],
                "chunks": [1, 1, side, side],
                "dtype": "<u2",
                "compressor": None,
                "fill_value": 0,
                "order": "C",
                "filters": None,
                "dimension_separator": ".",
            }
        ),
        encoding="utf-8",
    )
    if ramp:
        across = np.linspace(DIM, BRIGHT, side)
        plane = np.tile(across, (side, 1)).astype("<u2")
    else:
        plane = np.full((side, side), value, dtype="<u2")
    (level / "0.0.0.0").write_bytes(plane.tobytes())
    (store / ".zattrs").write_text(
        json.dumps(
            {
                "multiscales": [
                    {
                        "version": "0.4",
                        "axes": [
                            {"name": "c", "type": "channel"},
                            {"name": "z", "type": "space", "unit": "micrometer"},
                            {"name": "y", "type": "space", "unit": "micrometer"},
                            {"name": "x", "type": "space", "unit": "micrometer"},
                        ],
                        "datasets": [
                            {
                                "path": "0",
                                "coordinateTransformations": [
                                    # How big a voxel is. There is no channel
                                    # spacing to speak of, so that entry is 1.
                                    {"type": "scale", "scale": [1.0, *voxel_um]},
                                    # And where the tile sits on the stage. This is
                                    # the line every test in this file is about.
                                    {
                                        "type": "translation",
                                        "translation": [0.0, 0.0, y_um, x_um],
                                    },
                                ],
                            }
                        ],
                    }
                ],
                "omero": {
                    "channels": [
                        {
                            "label": "ch0",
                            "color": "FFFFFF",
                            "window": {
                                "min": 0,
                                "max": 65535,
                                "start": WINDOW[0],
                                "end": WINDOW[1],
                            },
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    return store


# ---------------------------------------------------------------------------
# Opening the viewer, and knowing when it is fair to photograph it
# ---------------------------------------------------------------------------

# The engine's own account of how far it has got with the view in front of it: how
# many pieces of image the view needs, and how many it has fetched and decoded.
# Everything the first view needs having arrived is as close as the engine comes to
# saying "I have finished drawing for now".
#
# This is the one place in this file where the engine is asked anything, and it is
# worth being clear about why that is not a contradiction. A viewer that has not
# drawn yet looks *exactly* like a viewer that drew nothing: both are a flat, empty
# panel. Photographing too early would therefore give a result that is not merely
# wrong but wrong in the most convincing possible way. So the engine is asked when
# to look — a question it can answer honestly, because it makes no claim at all
# about what is in the picture — and the photograph is left to say what is there.
#
# The same pattern, and the same reasoning, is in ``test_canvas_written_live.py``.
_FIRST_DRAW_IS_DONE = """() => {
  let layers = 0, needed = 0, available = 0;
  for (const m of window.zmartViewer.layerManager.managedLayers)
    for (const rl of (m.layer?.renderLayers) || []) {
      layers += 1;
      const p = rl.layerChunkProgressInfo;
      if (p) { needed += p.numVisibleChunksNeeded; available += p.numVisibleChunksAvailable; }
    }
  return layers > 0 && available > 0 && available >= needed;
}"""

# How many stores the engine is holding. The viewer hands them over in groups so
# that a run of many thousands of positions does not overwhelm the browser (see
# ``test_many_positions_arrive.py``), which means that early on it may legitimately
# be holding only some of them. Waiting until it holds them all, and until nothing
# is left in the queue, keeps a photograph from being taken of a half-delivered
# mosaic — a picture that would be missing a tile through no fault of the placing.
_STORES_HELD = """() => window.zmartViewer.layerManager.managedLayers
     .filter((m) => m.layer && m.layer.type === 'image')
     .reduce((total, m) => total + m.layer.dataSources.length, 0)"""


def open_the_viewer(browser, built_dist, folder: Path, *, stores: int, loads=None):
    """A viewer open on ``folder``, which has finished drawing what is there.

    ``stores`` is how many stores are expected to reach the engine, which is what
    the wait below is for. ``loads`` opens several folders as separate
    acquisitions, which one test needs; leaving it out opens everything in
    ``folder`` as a single acquisition, the way a run's tiles are opened.

    The viewport is deliberately roomy. Everything here is measured in screen
    pixels, and a bigger drawing surface means tiles placed well apart still land
    inside the picture with space to spare, rather than being clipped by the edge
    and reported as the wrong size.

    Returns the server, its thread and the page, all of which the caller closes.
    """
    if loads is None:
        store = sorted(p.name for p in folder.glob("*.ome.zarr"))
        server = make_server(
            port=0, data_dir=folder, site_dir=built_dist, store=store, live=False
        )
    else:
        server = make_server(
            port=0, data_dir=folder, site_dir=built_dist, loads=loads, live=False
        )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1400, "height": 1000})
    page.goto(
        f"http://127.0.0.1:{server.server_address[1]}", wait_until="domcontentloaded"
    )
    page.wait_for_function("() => window.zmartViewer !== undefined", timeout=60_000)
    page.wait_for_function(f"{_STORES_HELD} === {stores}", timeout=90_000)
    page.wait_for_function("() => window.zmartSourcesWaiting() === 0", timeout=90_000)
    page.wait_for_function(_FIRST_DRAW_IS_DONE, timeout=90_000)
    # Holding the pieces is a step ahead of having painted with them, and the
    # painting happens on the engine's own schedule rather than ours. A short
    # settle covers that gap; it is short because the waiting above has already
    # done the part that takes an unpredictable length of time.
    page.wait_for_timeout(2000)
    return server, thread, page


# ---------------------------------------------------------------------------
# Measuring where things are in the picture
# ---------------------------------------------------------------------------

# How much of the drawing surface to photograph, as fractions of its width and
# height. The viewer draws its own controls *on top of* the image — the 2D/3D
# buttons in the top left corner, the scale bar in the top right, the depth slider
# down the right-hand edge, the time slider along the bottom — and every one of
# them is bright enough to be mistaken for specimen. Trimming those edges away
# leaves a field containing nothing but what the engine drew, which is what makes
# "these are the lit patches" a trustworthy statement.
#
# ``pixels.py`` has a helper that does something similar, but it keeps only the
# middle half of the surface. That is the right choice for asking whether anything
# was drawn at all, and the wrong one here: a tile placed away from the centre —
# which is the entire subject of this file — would fall outside the middle half and
# be reported as missing.
_KEEP = {"left": 0.03, "right": 0.90, "top": 0.15, "bottom": 0.85}


def the_drawing(page) -> np.ndarray:
    """The picture the engine drew, as a height x width array of brightness.

    One number per pixel rather than three, because everything here is drawn in
    shades of grey and the brightest of the three colour channels is a faithful
    summary of it. Working with one number makes the measurements below much easier
    to read.
    """
    from PIL import Image

    canvas = page.locator("canvas").first.bounding_box()
    shot = page.screenshot(
        clip={
            "x": canvas["x"] + canvas["width"] * _KEEP["left"],
            "y": canvas["y"] + canvas["height"] * _KEEP["top"],
            "width": canvas["width"] * (_KEEP["right"] - _KEEP["left"]),
            "height": canvas["height"] * (_KEEP["bottom"] - _KEEP["top"]),
        }
    )
    return np.array(Image.open(io.BytesIO(shot)).convert("RGB")).max(axis=2)


# The narrowest run of blank pixels that counts as real space between two patches
# of specimen. A single blank column can appear inside a patch for uninteresting
# reasons — a seam where the engine sampled the image, a rounding difference at an
# edge — and splitting a patch in two over one such column would turn a correct
# picture into a failure. Eight is comfortably wider than any such artefact and far
# narrower than the gaps these tests arrange, which are a whole tile across.
_REAL_GAP = 8


def runs_of_lit(present: np.ndarray, gap: int = _REAL_GAP) -> list[tuple[int, int]]:
    """Group a row of yes/no answers into stretches, ignoring narrow interruptions.

    Given, for each column of the picture, whether that column has any specimen in
    it, this returns the stretches of columns that do — ``[(first, last), ...]`` —
    treating a blank stretch narrower than ``gap`` as no real separation at all.

    This is how "how many separate patches of specimen are on screen, and where
    are they?" gets answered. It is a modest measurement and that is deliberate:
    tiles placed apart along one axis show up as patches with clear space between
    them, and counting those stretches is enough to tell one tile drawn twice in
    the same place from two tiles drawn where they belong. If the two are drawn on
    top of each other, there is one stretch instead of two, and no amount of
    brightness or structure in the image can disguise that.
    """
    found: list[tuple[int, int]] = []
    start = None
    for at, lit in enumerate(present):
        if lit and start is None:
            start = at
        elif not lit and start is not None:
            found.append((start, at - 1))
            start = None
    if start is not None:
        found.append((start, len(present) - 1))
    # Join up neighbours that are not really separated.
    joined = [found[0]] if found else []
    for first, last in found[1:]:
        if first - joined[-1][1] - 1 < gap:
            joined[-1] = (joined[-1][0], last)
        else:
            joined.append((first, last))
    return joined


def patches_across(picture: np.ndarray) -> list[tuple[int, int]]:
    """The stretches of columns holding specimen — patches lying side by side."""
    return runs_of_lit((picture > GROUND).any(axis=0))


def patches_down(picture: np.ndarray) -> list[tuple[int, int]]:
    """The stretches of rows holding specimen — patches lying one above another."""
    return runs_of_lit((picture > GROUND).any(axis=1))


def middle_of_the_light(picture: np.ndarray, mask: np.ndarray) -> tuple[float, float]:
    """Where the lit pixels of ``mask`` sit, on average, as (row, column).

    This is the centre of mass of the specimen: add up the positions of every
    pixel that has something in it and divide by how many there were. It answers
    "whereabouts in the picture is this piece of specimen" with a single pair of
    numbers, which is what makes comparisons between two tiles — is this one
    further left, did this one move — simple to state and simple to read in a
    failure message.
    """
    where = np.argwhere(mask & (picture > GROUND))
    assert len(where), "asked where a piece of specimen is when none was drawn"
    row, column = where.mean(axis=0)
    return float(row), float(column)


def only_the_bright(picture: np.ndarray) -> np.ndarray:
    """The pixels belonging to a tile written at the bright value."""
    return picture >= BRIGHT_ENOUGH


def only_the_dim(picture: np.ndarray) -> np.ndarray:
    """The pixels belonging to a tile written at the dim value."""
    return (picture > GROUND) & (picture < BRIGHT_ENOUGH)


def describe(picture: np.ndarray) -> str:
    """A short account of the picture, for a failure message to carry.

    A test that fails here is saying something about geometry, and "there was one
    patch where there should have been two" is far more use to whoever reads it
    with the actual numbers attached.
    """
    lit = picture > GROUND
    return (
        f"{picture.shape[1]}x{picture.shape[0]} picture, "
        f"{lit.mean():.1%} of it lit, "
        f"patches side by side at {patches_across(picture)}, "
        f"patches one above another at {patches_down(picture)}"
    )


# ---------------------------------------------------------------------------
# The tests
# ---------------------------------------------------------------------------


def test_two_tiles_recorded_apart_are_drawn_apart(browser, built_dist, tmp_path):
    """Two tiles, two stage positions, two separate patches of specimen on screen.

    This is the plainest possible statement of the thing the viewer exists to do,
    and until now nothing checked it. Two single-tile stores are written two tile
    widths apart along the stage's x axis, so between them there is exactly one
    tile width of ground that was never imaged. Drawn correctly that is two patches
    of light with a gap between them as wide as either patch.

    The failure this is really here to catch is a viewer that ignores translations
    and draws every tile at the origin. That viewer produces a bright, structured,
    entirely plausible picture — and one patch instead of two. Counting the patches
    is what separates the two cases, and nothing about how bright or how detailed
    the image is can disguise the difference.

    The width of the gap is checked as well as the number of patches, because it
    ties the picture to the numbers in the metadata rather than merely to their
    being different. The tiles were recorded one tile width apart, so the space
    between them must be about one tile wide — whatever zoom the engine happened to
    choose, since a zoom scales the gap and the patches together and leaves their
    ratio alone.
    """
    write_tile(tmp_path / "overview_pos00000.ome.zarr", x_um=0.0)
    write_tile(tmp_path / "overview_pos00001.ome.zarr", x_um=2 * TILE_UM)
    server, thread, page = open_the_viewer(browser, built_dist, tmp_path, stores=2)
    try:
        picture = the_drawing(page)
        side_by_side = patches_across(picture)
        assert len(side_by_side) == 2, (
            "two tiles recorded two tile widths apart were not drawn as two "
            "separate patches of specimen. One patch means every tile landed in "
            "the same place, which is what a viewer that ignored the translations "
            f"in the stores would draw: {describe(picture)}"
        )

        # Both patches should be a tile, so they should be about the same width. A
        # lopsided pair would mean one of them was clipped by the edge of the
        # picture, and a measurement taken on a clipped patch would not mean what
        # the rest of this test assumes it means.
        (first_start, first_end), (second_start, second_end) = side_by_side
        widths = (first_end - first_start + 1, second_end - second_start + 1)
        assert 0.75 < widths[0] / widths[1] < 1.33, (
            "the two patches are not the same size, so at least one of them is "
            f"running off the edge of the picture: widths {widths}"
        )

        # And they should be one tile width apart, because that is what the stores
        # say. Compared as a ratio to the width of a patch so that the answer does
        # not depend on how far the engine chose to zoom in.
        gap = second_start - first_end - 1
        apart = gap / (sum(widths) / 2)
        assert 0.7 < apart < 1.3, (
            "the two tiles were recorded two tile widths apart, so one tile width "
            "of unimaged ground should sit between them on screen. The gap that is "
            f"actually there is {apart:.2f} of a tile: {describe(picture)}"
        )
        print(
            f"\n  two patches at {side_by_side}, "
            f"{gap} blank columns between them, {apart:.2f} of a tile"
        )
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def test_a_tile_further_along_the_stage_is_drawn_further_along_the_picture(
    browser, built_dist, tmp_path
):
    """The direction the stage moved in is the direction the picture moves in.

    This is the test that catches a sign the wrong way round: a viewer that read a
    translation and then applied it backwards would place the second tile on the
    wrong side of the first, and a mosaic built that way comes out inside out. The
    picture would still be bright and still be made of tiles, so nothing else in
    this suite would notice.

    Saying "further along" needs a reference, and this test is careful not to
    borrow one from the screen. Whether the axis the data calls x runs to the
    right or to the left is a question about how the view is set up, and it is
    asked and answered elsewhere — in ``test_the_picture_is_not_mirrored.py``,
    which is where it belongs. Baking either answer in here would mean this test
    started failing the day somebody changed the view, for a reason that has
    nothing to do with the translations it is actually about.

    So the reference comes from the image itself. The first tile is filled with a
    gradient that grows along its *own* x axis, from dim at its first voxel to
    bright at its last. Wherever that tile's bright end is drawn, that is the
    direction x runs on screen — and it is settled by the order the voxels sit in
    the file, which no reading of a translation can change. The second tile,
    recorded further along x, must then be drawn on that same side. This holds
    whichever way round the screen happens to be, and fails the moment the sign or
    the axis of a translation is wrong.
    """
    # The gradient tile at the origin, and a plain one two tile widths further
    # along x. The plain one is written at the dim value so that neither tile can
    # be mistaken for the other by brightness alone; they are told apart below by
    # whether the patch varies across its width, which is a property of what was
    # written rather than of where it was put.
    write_tile(tmp_path / "overview_pos00000.ome.zarr", x_um=0.0, ramp=True)
    write_tile(tmp_path / "overview_pos00001.ome.zarr", x_um=2 * TILE_UM, value=DIM)
    server, thread, page = open_the_viewer(browser, built_dist, tmp_path, stores=2)
    try:
        picture = the_drawing(page)
        side_by_side = patches_across(picture)
        assert len(side_by_side) == 2, (
            "the two tiles were not drawn as two separate patches, so there is no "
            f"question of which side either of them is on: {describe(picture)}"
        )

        # Which patch is the gradient one. A gradient varies a great deal across
        # its width and a plain fill does not vary at all, so comparing the two is
        # not a close call.
        def variation(patch: tuple[int, int]) -> float:
            first, last = patch
            column = picture[:, first : last + 1]
            lit = column[column > GROUND]
            return float(lit.std()) if len(lit) else 0.0

        varies = [variation(patch) for patch in side_by_side]
        gradient_at = int(np.argmax(varies))
        plain_at = 1 - gradient_at
        assert varies[gradient_at] > 5 * max(varies[plain_at], 1.0), (
            "one tile was written as a gradient and the other as a plain fill, but "
            "the two patches on screen vary by about the same amount, so which is "
            f"which cannot be read off the picture: variation {varies}"
        )

        # Which way the gradient runs on screen. Its dim end is the tile's first
        # voxel along x and its bright end is the tile's last, so the brighter side
        # is the direction in which x increases.
        first, last = side_by_side[gradient_at]
        halfway = (first + last) // 2
        left_half = picture[:, first : halfway + 1]
        right_half = picture[:, halfway + 1 : last + 1]
        brightness = (
            float(left_half[left_half > GROUND].mean()),
            float(right_half[right_half > GROUND].mean()),
        )
        x_grows_rightwards = brightness[1] > brightness[0]
        assert abs(brightness[1] - brightness[0]) > 10, (
            "the gradient tile looks the same on both sides, so it cannot say "
            f"which way x runs on screen: mean brightness {brightness}"
        )

        # And the other tile, recorded further along x, must be on that side.
        gradient_middle = sum(side_by_side[gradient_at]) / 2
        plain_middle = sum(side_by_side[plain_at]) / 2
        drawn_rightwards = plain_middle > gradient_middle
        assert drawn_rightwards == x_grows_rightwards, (
            "the second tile was recorded further along x than the first, but it "
            "was drawn on the opposite side — the side x decreases towards, "
            "measured from the gradient inside the first tile itself. A mosaic "
            "assembled this way comes out inside out. x grows towards the "
            f"{'right' if x_grows_rightwards else 'left'} of the picture "
            f"(the gradient tile's halves average {brightness[0]:.0f} and "
            f"{brightness[1]:.0f}), yet the further tile was drawn to the "
            f"{'right' if drawn_rightwards else 'left'}: {describe(picture)}"
        )
        print(
            f"\n  x grows towards the "
            f"{'right' if x_grows_rightwards else 'left'}; gradient tile centred "
            f"at column {gradient_middle:.0f}, the tile further along x at "
            f"{plain_middle:.0f}"
        )
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def test_two_tiles_recorded_apart_in_y_are_drawn_one_above_the_other(
    browser, built_dist, tmp_path
):
    """A step along y moves the tile up or down the picture, not across it.

    Together with the two tests above this is what pins the axes to each other. A
    step along x drew the tiles side by side; a step along y of the same size must
    draw them one above the other and leave them lined up across. A viewer that
    read the y part of a translation into the x place would swap those two
    outcomes and would look entirely healthy in every other test in the suite,
    since it would still be drawing tiles in different places — just not the right
    ones.

    A specimen assembled with y and x exchanged is transposed: recognisable as
    tissue, wrong in every measurement anybody would take from it.
    """
    write_tile(tmp_path / "overview_pos00000.ome.zarr", y_um=0.0, x_um=0.0)
    write_tile(tmp_path / "overview_pos00001.ome.zarr", y_um=2 * TILE_UM, x_um=0.0)
    server, thread, page = open_the_viewer(browser, built_dist, tmp_path, stores=2)
    try:
        picture = the_drawing(page)
        one_above_another = patches_down(picture)
        assert len(one_above_another) == 2, (
            "two tiles recorded two tile widths apart along y were not drawn one "
            "above the other. One patch means they landed on top of each other; "
            "the test below says what it means if they landed side by side "
            f"instead: {describe(picture)}"
        )
        assert len(patches_across(picture)) == 1, (
            "two tiles differing only in their y position were drawn side by side "
            "rather than one above the other, which is what a viewer that had "
            "exchanged the y and x parts of a translation would draw. A specimen "
            f"assembled that way is transposed: {describe(picture)}"
        )

        # The same tie back to the metadata as the side-by-side test makes: two
        # tile widths apart means one tile width of unimaged ground between them.
        (first_start, first_end), (second_start, second_end) = one_above_another
        heights = (first_end - first_start + 1, second_end - second_start + 1)
        assert 0.75 < heights[0] / heights[1] < 1.33, (
            "the two patches are not the same size, so at least one is running off "
            f"the edge of the picture: heights {heights}"
        )
        # The tile's size on screen is read from the ACROSS axis, where nothing
        # is clipped, rather than from the stacked patches themselves. The view
        # opens fitted to the whole picture, and on this stacked scene that
        # leaves the outer edge of each tile past the photographed field's top
        # and bottom -- a patch height is then the surviving middle of a tile,
        # not a tile. The tiles are square, and the one patch the across axis
        # holds (asserted just above) is a whole tile wide.
        ((across_start, across_end),) = patches_across(picture)
        tile_on_screen = across_end - across_start + 1
        apart = (second_start - first_end - 1) / tile_on_screen
        assert 0.7 < apart < 1.3, (
            "the two tiles were recorded two tile widths apart along y, so one "
            "tile width of unimaged ground should sit between them. What is there "
            f"is {apart:.2f} of a tile: {describe(picture)}"
        )
        print(
            f"\n  two patches stacked at {one_above_another}, "
            f"{apart:.2f} of a tile between them, and only "
            f"{len(patches_across(picture))} patch across"
        )
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def test_a_tile_recorded_twice_as_far_away_is_drawn_twice_as_far_away(
    browser, built_dist, tmp_path
):
    """Change only the translation, and only where the tile is drawn changes.

    The tests above show that tiles with different translations land in different
    places. This one isolates the translation as the *cause*, and asks for
    something quantitative while it is at it: the same two stores are written
    twice, identical in every respect except that the second tile's recorded
    position is twice as far from the first, and the space between them on screen
    should double to match.

    Doubling is asked for rather than a particular number of pixels because a
    number of pixels would be a statement about how far the engine chose to zoom
    in, which is its own business. And because the engine fits each opening to
    the whole of what it was given -- so the two runs, holding different
    extents, open at different magnifications, and a distance in raw pixels
    would compare two different rulers. The separation is therefore measured in
    the one unit both runs share: the tile's own width on the same screen. In
    tile widths the recorded positions say the separation must go from two to
    four, whatever magnification either run opened at, and that is the stronger
    claim in any case: the viewer places tiles *in proportion* to the positions
    recorded in them, not merely somewhere different.

    A tile is kept at the origin in both runs on purpose. It is the reference the
    measurement is made against — a single tile on its own would be drawn in the
    middle of the panel wherever it claimed to be, since the view is framed around
    whatever is there, and the distance between two tiles is the thing that does
    not depend on the framing.
    """
    separations = []
    for run, apart in enumerate((2 * TILE_UM, 4 * TILE_UM), start=1):
        folder = tmp_path / f"run{run}"
        folder.mkdir()
        write_tile(folder / "overview_pos00000.ome.zarr", x_um=0.0)
        write_tile(folder / "overview_pos00001.ome.zarr", x_um=apart)
        server, thread, page = open_the_viewer(browser, built_dist, folder, stores=2)
        try:
            picture = the_drawing(page)
            side_by_side = patches_across(picture)
            assert len(side_by_side) == 2, (
                f"with the tiles recorded {apart / TILE_UM:.0f} tile widths apart "
                "they were not drawn as two separate patches, so there is no "
                f"separation to measure: {describe(picture)}"
            )
            middles = [sum(patch) / 2 for patch in side_by_side]
            widths = [last - first + 1 for first, last in side_by_side]
            separations.append(abs(middles[1] - middles[0]) / (sum(widths) / 2))
        finally:
            page.close()
            server.shutdown()
            thread.join(timeout=5)

    grew = separations[1] / separations[0]
    assert 1.8 < grew < 2.2, (
        "the second tile's recorded position was moved from two tile widths away "
        "to four, so the separation between the two tiles, measured in tile "
        f"widths on their own screen, should have doubled. It changed by a factor "
        f"of {grew:.2f} instead ({separations[0]:.1f} then {separations[1]:.1f} "
        "tile widths apart). A factor near one would mean the recorded position "
        "is not what decides where a tile is drawn."
    )
    print(
        f"\n  tiles drawn {separations[0]:.1f} tile widths apart at two recorded "
        f"tile widths and {separations[1]:.1f} at four, a factor of {grew:.2f}"
    )


def test_a_coarser_acquisition_takes_up_more_room_on_screen(
    browser, built_dist, tmp_path
):
    """The same number of voxels at a bigger voxel covers more of the specimen.

    A tile's ``translation`` says where it sits and its ``scale`` says how big its
    voxels are, and the two have to be read in the same units for either to mean
    anything. Getting those units wrong is a particularly easy mistake to make and
    a particularly bad one to have: micrometres read as metres change a specimen's
    size by a factor of a million, so a tile is drawn either as a speck or as
    something vastly larger than the screen. The viewer has been caught by exactly
    this before — for a while it drew the demo volume about a ten-thousandth of a
    pixel wide, with every piece of image loaded and the engine perfectly satisfied.

    Two acquisitions of the same specimen are opened side by side, which is an
    ordinary thing to do: a coarse overview to find the region and a fine scan of
    the region itself. Both are the same number of voxels across, but one has
    voxels three times the size, so it covers three times as much specimen and must
    be drawn three times as large. Anything else — the same size, or a size out by
    a factor of a million — means the scales are not being honoured.

    They are opened as two acquisitions rather than two tiles of one because the
    viewer quite deliberately refuses to treat two magnifications as one
    acquisition. That refusal is checked elsewhere; here it simply decides how the
    two stores are handed over.
    """
    fine, coarse = tmp_path / "fine", tmp_path / "coarse"
    fine.mkdir()
    coarse.mkdir()
    # The fine acquisition at the origin, bright; the coarse one placed clear of it
    # and dim, so the two can be told apart in the photograph.
    write_tile(fine / "overview_pos00000.ome.zarr", x_um=0.0, value=BRIGHT)
    write_tile(
        coarse / "overview_pos00000.ome.zarr",
        x_um=2.5 * TILE_UM,
        voxel_um=(6.0, 1.5, 1.5),
        value=DIM,
    )
    server, thread, page = open_the_viewer(
        browser,
        built_dist,
        tmp_path,
        stores=2,
        loads=[
            {"path": str(fine), "name": "fine"},
            {"path": str(coarse), "name": "coarse"},
        ],
    )
    try:
        picture = the_drawing(page)
        bright, dim = only_the_bright(picture), only_the_dim(picture)
        assert bright.any(), (
            "the fine acquisition was not drawn at all, so there is nothing to "
            f"compare the coarse one against: {describe(picture)}"
        )
        assert dim.any(), (
            "the coarse acquisition was not drawn at all: " f"{describe(picture)}"
        )

        # How wide each patch is, in columns. Measured across rather than by
        # counting pixels because a patch clipped at the top or bottom would still
        # give its true width, and width is all this comparison needs.
        def width(mask: np.ndarray) -> int:
            columns = np.flatnonzero(mask.any(axis=0))
            return int(columns.max() - columns.min() + 1)

        def height(mask: np.ndarray) -> int:
            rows = np.flatnonzero(mask.any(axis=1))
            return int(rows.max() - rows.min() + 1)

        fine_width, coarse_width = width(bright), width(dim)
        larger = coarse_width / fine_width
        assert 2.4 < larger < 3.6, (
            "the coarse acquisition has voxels three times the size of the fine "
            "one and the same number of them, so it covers three times as much "
            "specimen and should be drawn three times as wide. It was drawn "
            f"{larger:.2f} times as wide instead ({fine_width} columns against "
            f"{coarse_width}). A factor near one means the voxel sizes are being "
            "ignored; a factor wildly away from three means they are being read "
            f"in the wrong units: {describe(picture)}"
        )
        # And the same in the other direction, since a voxel size read into the
        # wrong axis would stretch one way only.
        taller = height(dim) / height(bright)
        assert 2.4 < taller < 3.6, (
            "the coarse acquisition was drawn three times as wide as the fine one "
            f"but {taller:.2f} times as tall, so its voxel size is being honoured "
            f"across the picture and not down it: {describe(picture)}"
        )
        print(
            f"\n  fine tile {fine_width} columns wide, coarse tile "
            f"{coarse_width}, a factor of {larger:.2f} across and {taller:.2f} down"
        )
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)
