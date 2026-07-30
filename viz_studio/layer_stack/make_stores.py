"""The little acquisitions the layer-stack measurements are made against.

Every one of them is written by this project's own writer,
:class:`zmart_storage.TileCanvases`, rather than being assembled by hand. That
matters more than it might sound. The whole point of these measurements is to
find out how the images *this project writes* behave when several of them are
stacked on top of one another in the viewer — how their transparency combines,
whether a coarse one lands in the right place against a fine one, what a
plate-sized one costs. An answer obtained on a made-up image would say nothing
about any of that, because it would have skipped the very things that make a
real store what it is: the pyramid of progressively smaller copies, the chunk
size, the sparseness, and the description of physical size that the viewer uses
to place everything.

The stores are grouped below by the question they were made for. Each group has
its own comment explaining what it is shaped the way it is.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

# The writer lives at the top of the repository, beside viz_studio.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from zmart_storage import Channel, TileCanvases  # noqa: E402

# The brightness the shaders in the probe page are set up against. The page maps
# the range 0 to 4095 onto nothing-to-full, so a tile written at this value comes
# out as a saturated, unmistakable colour in a photograph.
BRIGHT = 3000

# Every store here is written with a single channel, because none of these
# questions is about colour separation — the colours in the photographs come
# from the shaders, so that two layers holding identical numbers can still be
# told apart on screen.
def _one_channel() -> list[Channel]:
    return [Channel(name="probe", color="FFFFFF", window=(0, 4095))]


# ---------------------------------------------------------------------------
# Question 1: does a layer underneath give the layer above its transparency back?
# ---------------------------------------------------------------------------
#
# Two images of exactly the same size and voxel size, sitting on exactly the same
# ground. The lower one is imaged everywhere; the upper one is imaged over only
# half of its extent, and the half nobody imaged reads back as nought.
#
# Drawn with a shader that makes nought see-through, the interesting half of the
# picture is the right-hand one. If the layer underneath shows through there,
# transparency between layers works and the whole arrangement in `LAYERS.md` is
# possible. If instead that half comes out blank, the upper layer has painted
# over the lower one with nothing, and the arrangement does not work.
#
# They are deliberately the same size and voxel size so that nothing else can be
# blamed for the result. The only difference between them is which is on top.

TRANSPARENCY_VOXELS = 1024
TRANSPARENCY_TILE = 256


def _flat_tile(height: int, width: int, value: int) -> np.ndarray:
    """One tile of even brightness, shaped the way the writer expects (z, y, x)."""
    return np.full((1, height, width), value, dtype=np.uint16)


def write_the_lower_layer(folder: Path, *, name: str = "under") -> None:
    """A small image imaged from edge to edge, to sit at the bottom of the stack.

    It stands in for the plate layout: written once, covering everything, and
    never changing afterwards. Because it is imaged everywhere, anywhere it fails
    to appear on screen is somewhere a layer above has hidden it — which is
    exactly what the first measurement is looking for.
    """
    canvases = TileCanvases.create(
        folder,
        name=name,
        canvas_shape=(1, TRANSPARENCY_VOXELS, TRANSPARENCY_VOXELS),
        tile_shape=(1, TRANSPARENCY_TILE, TRANSPARENCY_TILE),
        tile_step=(1, TRANSPARENCY_TILE, TRANSPARENCY_TILE),
        voxel_size_um=(1.0, 1.0, 1.0),
        channels=_one_channel(),
        discard_existing_run=True,
    )
    across = TRANSPARENCY_VOXELS // TRANSPARENCY_TILE
    for row in range(across):
        for column in range(across):
            canvases.write(
                _flat_tile(TRANSPARENCY_TILE, TRANSPARENCY_TILE, BRIGHT),
                origin=(0, row * TRANSPARENCY_TILE, column * TRANSPARENCY_TILE),
                tile_index=(0, row, column),
            )
    canvases.close()


def write_the_upper_layer(folder: Path, *, name: str = "over") -> None:
    """The same ground, imaged over only its left half.

    The right half is never written at all, so it reads back as nought — which is
    what any part of a declared canvas that the microscope has not visited reads
    back as. That untouched half is the part of the picture the first measurement
    is about.
    """
    canvases = TileCanvases.create(
        folder,
        name=name,
        canvas_shape=(1, TRANSPARENCY_VOXELS, TRANSPARENCY_VOXELS),
        tile_shape=(1, TRANSPARENCY_TILE, TRANSPARENCY_TILE),
        tile_step=(1, TRANSPARENCY_TILE, TRANSPARENCY_TILE),
        voxel_size_um=(1.0, 1.0, 1.0),
        channels=_one_channel(),
        discard_existing_run=True,
    )
    across = TRANSPARENCY_VOXELS // TRANSPARENCY_TILE
    for row in range(across):
        for column in range(across // 2):
            canvases.write(
                _flat_tile(TRANSPARENCY_TILE, TRANSPARENCY_TILE, BRIGHT),
                origin=(0, row * TRANSPARENCY_TILE, column * TRANSPARENCY_TILE),
                tile_index=(0, row, column),
            )
    canvases.close()


# ---------------------------------------------------------------------------
# Question 2: does a coarse layer land correctly against a fine one?
# ---------------------------------------------------------------------------
#
# The plate layout would be written at something like ten micrometres to a voxel
# while the acquisition is at about a third of one — nearly thirty times finer.
# They are meant to line up because an OME-Zarr image records the *physical* size
# of a voxel and where its corner sits in the world, and the engine places
# layers by those physical facts rather than by counting pixels.
#
# The shape of the check is borrowed from the sandwich measurements, because it
# proved itself there: put a square inside a square. The coarse image holds a
# square 880 micrometres across; the fine image holds a square 560 micrometres
# across, centred on exactly the same point of the world. If the two land where
# they should, the coarse square shows as an even border 160 micrometres wide all
# the way round the fine one. Any error in placement makes that border uneven,
# and *which* side it thickens says which way the error goes.
#
# A border is used rather than simply asking "do the two centres agree" because a
# border can be read straight off a photograph without trusting anything the
# engine says about itself.

# The coarse image: ten micrometres to a voxel, a shade over a centimetre across.
COARSE_UM = 10.0
COARSE_VOXELS = 1024
# The fine image: about a third of a micrometre to a voxel, the size a real
# detailed scan is written at.
FINE_UM = 0.35
FINE_VOXELS = 4096
# Where the fine image's low corner sits in the world, in micrometres. Set so
# that the fine image straddles the coarse one's feature — which also puts the
# writer's ``origin_um`` under test, since a wrong corner would show here as
# plainly as a wrong voxel size.
FINE_ORIGIN_UM = 4280.0

# The feature in the coarse image, in its own voxels. 468 to 556 covers 4680 to
# 5560 micrometres, which is 880 micrometres wide and centred on 5120.
COARSE_FEATURE = (468, 556)
# The feature in the fine image, in its own voxels. 1600 to 3200 covers
# 4280 + 560 = 4840 to 4280 + 1120 = 5400 micrometres: 560 micrometres wide and
# centred on 5120, the same point of the world as the coarse feature.
FINE_FEATURE = (1600, 3200)
# What the border between them should therefore measure, in micrometres. This is
# the number every reading in question 2 is compared against.
EXPECTED_BORDER_UM = 160.0


def write_the_coarse_layer(folder: Path, *, name: str = "coarse",
                           voxel_um: float = COARSE_UM) -> None:
    """A coarse image holding one square feature at a known place in the world.

    Written as a single tile covering the whole canvas, because the point here is
    where the picture lands rather than how it was scanned. Everywhere outside
    the square is left at nought so that it draws as nothing at all and the
    square is the only thing on screen.

    ``voxel_um`` can be changed so that the same feature, at the same place in
    the world and the same size in micrometres, is written at a different
    coarseness. That is what makes it possible to find out whether a small
    disagreement between two layers depends on how coarse one of them is — which
    is the difference between a half-a-voxel convention and a fault.
    """
    # However coarse the voxels are, the canvas covers the same ground and the
    # square is the same size in micrometres, so the two versions differ in
    # nothing except coarseness.
    voxels = int(round(COARSE_VOXELS * COARSE_UM / voxel_um))
    low = int(round(COARSE_FEATURE[0] * COARSE_UM / voxel_um))
    high = int(round(COARSE_FEATURE[1] * COARSE_UM / voxel_um))
    canvases = TileCanvases.create(
        folder,
        name=name,
        canvas_shape=(1, voxels, voxels),
        tile_shape=(1, voxels, voxels),
        tile_step=(1, voxels, voxels),
        voxel_size_um=(voxel_um, voxel_um, voxel_um),
        channels=_one_channel(),
        discard_existing_run=True,
    )
    plane = np.zeros((1, voxels, voxels), dtype=np.uint16)
    plane[0, low:high, low:high] = BRIGHT
    canvases.write(plane, origin=(0, 0, 0), tile_index=(0, 0, 0))
    canvases.close()


def write_the_fine_layer(folder: Path, *, name: str = "fine",
                         corner_wrong_by_um: float = 0.0) -> None:
    """A fine image holding a smaller square centred on the very same point.

    Its low corner is deliberately not at the origin of the world. A run images
    part of a carrier rather than the whole of it, so the corner of a detailed
    scan sits wherever the stage happened to be — and if the engine ignored that,
    the square would land nearly four millimetres away from where it belongs.

    ``corner_wrong_by_um`` writes the corner down wrongly on purpose, by the
    given number of micrometres. Nothing else about the image changes. This is
    what a real version of this fault would look like — a stage position recorded
    slightly wrong, or an origin left out — and it is used to show that the
    border reading really does notice, rather than being a check that has never
    been seen to fail.
    """
    canvases = TileCanvases.create(
        folder,
        name=name,
        canvas_shape=(1, FINE_VOXELS, FINE_VOXELS),
        tile_shape=(1, 400, 400),
        tile_step=(1, 400, 400),
        voxel_size_um=(FINE_UM, FINE_UM, FINE_UM),
        channels=_one_channel(),
        origin_um=(0.0, FINE_ORIGIN_UM, FINE_ORIGIN_UM + corner_wrong_by_um),
        discard_existing_run=True,
    )
    low, high = FINE_FEATURE
    for row in range(low, high, 400):
        for column in range(low, high, 400):
            canvases.write(
                _flat_tile(400, 400, BRIGHT),
                origin=(0, row, column),
                tile_index=(0, row // 400, column // 400),
            )
    canvases.close()


# ---------------------------------------------------------------------------
# Question 3: the whole stack, drawn together
# ---------------------------------------------------------------------------
#
# Three images on the same ground: the carrier and its wells at the bottom, the
# tiles the operator planned above that, and the acquisition itself on top,
# filling in as tiles land. This is the arrangement the whole investigation is
# about, so these three are shaped to look like the real thing rather than to be
# easy to measure.
#
# The carrier and the plan are both written at ten micrometres to a voxel, which
# is plenty for an outline and a rectangle. The acquisition is written at the
# real detailed-scan voxel size, so the stack really does mix a coarse layer with
# a fine one exactly as it would in use.

# The piece of carrier the stack is drawn on: forty by thirty millimetres, which
# is about a third of a plate and comfortably fills a window.
STACK_UM = 10.0
STACK_WIDE = 4000
STACK_TALL = 3000

# The planned tiles: a grid of rectangles inside one well, each 700 micrometres
# across, which is a realistic field of view for a detailed scan.
PLAN_COLUMNS = 4
PLAN_ROWS = 3
PLAN_TILE_UM = 700.0
# Where the corner of the planned grid sits in the world, in micrometres.
PLAN_ORIGIN_UM = (9000.0, 12000.0)  # (y, x)

# The acquisition covering that same grid, at the fine voxel size. Four by three
# tiles of 2000 voxels each, and 2000 voxels at 0.35 micrometres is exactly the
# 700 micrometres a planned tile measures.
ACQ_UM = 0.35
ACQ_TILE_VOXELS = 2000


def _wells(plane: np.ndarray, value: int) -> None:
    """Draw a few round wells into a plane, the way a carrier drawing has them.

    Round rather than square on purpose: a circle drawn into a coarse image is a
    good way to see whether the coarse image is being drawn at the size it claims
    to be, because a circle that has been stretched is obvious at a glance in a
    way that a stretched rectangle is not.
    """
    tall, wide = plane.shape
    down, across = np.ogrid[:tall, :wide]
    for row in range(2):
        for column in range(3):
            centre_y = int(tall * (0.3 + 0.4 * row))
            centre_x = int(wide * (0.2 + 0.3 * column))
            radius = int(min(tall, wide) * 0.16)
            ring = (down - centre_y) ** 2 + (across - centre_x) ** 2
            # An outline rather than a filled disc, so that anything drawn over
            # the well is still visible inside it.
            plane[(ring < radius ** 2) & (ring > (radius - 12) ** 2)] = value


def write_the_carrier(folder: Path, *, name: str = "carrier") -> None:
    """The plate layout: the outline of the carrier and its wells.

    This is the layer that would be written once per carrier type and reused by
    every run on that carrier, so it is the cheapest of the three to keep and the
    one that has to sit at the very bottom of the stack.
    """
    canvases = TileCanvases.create(
        folder,
        name=name,
        canvas_shape=(1, STACK_TALL, STACK_WIDE),
        tile_shape=(1, STACK_TALL, STACK_WIDE),
        tile_step=(1, STACK_TALL, STACK_WIDE),
        voxel_size_um=(STACK_UM, STACK_UM, STACK_UM),
        channels=_one_channel(),
        discard_existing_run=True,
    )
    plane = np.zeros((STACK_TALL, STACK_WIDE), dtype=np.uint16)
    # The outline of the carrier itself, a band around the edge.
    edge = 20
    plane[:edge, :] = BRIGHT
    plane[-edge:, :] = BRIGHT
    plane[:, :edge] = BRIGHT
    plane[:, -edge:] = BRIGHT
    _wells(plane, BRIGHT)
    canvases.write(plane[None, :, :], origin=(0, 0, 0), tile_index=(0, 0, 0))
    canvases.close()


def write_the_plan(folder: Path, *, name: str = "plan") -> None:
    """The tiles the operator chose for this run, written just before it starts.

    Each planned tile is drawn as an outline rather than a filled rectangle, for
    the same reason the wells are: whatever is acquired inside it has to remain
    visible, and an outline is what an operator would recognise as "this is where
    the microscope is going to look".
    """
    canvases = TileCanvases.create(
        folder,
        name=name,
        canvas_shape=(1, STACK_TALL, STACK_WIDE),
        tile_shape=(1, STACK_TALL, STACK_WIDE),
        tile_step=(1, STACK_TALL, STACK_WIDE),
        voxel_size_um=(STACK_UM, STACK_UM, STACK_UM),
        channels=_one_channel(),
        discard_existing_run=True,
    )
    plane = np.zeros((STACK_TALL, STACK_WIDE), dtype=np.uint16)
    side = int(PLAN_TILE_UM / STACK_UM)
    top = int(PLAN_ORIGIN_UM[0] / STACK_UM)
    left = int(PLAN_ORIGIN_UM[1] / STACK_UM)
    thickness = 4
    for row in range(PLAN_ROWS):
        for column in range(PLAN_COLUMNS):
            y0 = top + row * side
            x0 = left + column * side
            plane[y0:y0 + side, x0:x0 + thickness] = BRIGHT
            plane[y0:y0 + side, x0 + side - thickness:x0 + side] = BRIGHT
            plane[y0:y0 + thickness, x0:x0 + side] = BRIGHT
            plane[y0 + side - thickness:y0 + side, x0:x0 + side] = BRIGHT
    canvases.write(plane[None, :, :], origin=(0, 0, 0), tile_index=(0, 0, 0))
    canvases.close()


def open_the_acquisition(folder: Path, *, name: str = "acquired") -> TileCanvases:
    """Declare the acquisition that fills in as tiles land, and leave it open.

    Handed back still open rather than closed, because the point of question 3 is
    to photograph the stack part-acquired and then again fully acquired, which
    means writing more tiles into it between the two photographs. Close it
    yourself when you are finished.
    """
    return TileCanvases.create(
        folder,
        name=name,
        canvas_shape=(
            1,
            PLAN_ROWS * ACQ_TILE_VOXELS,
            PLAN_COLUMNS * ACQ_TILE_VOXELS,
        ),
        tile_shape=(1, ACQ_TILE_VOXELS, ACQ_TILE_VOXELS),
        tile_step=(1, ACQ_TILE_VOXELS, ACQ_TILE_VOXELS),
        voxel_size_um=(ACQ_UM, ACQ_UM, ACQ_UM),
        channels=_one_channel(),
        origin_um=(0.0, PLAN_ORIGIN_UM[0], PLAN_ORIGIN_UM[1]),
        discard_existing_run=True,
    )


def _speckled_tile(size: int, seed: int) -> np.ndarray:
    """A tile of picture with visible structure in it.

    A perfectly even tile would be indistinguishable from a rectangle of flat
    colour, and a measurement that could not tell those apart would not be able
    to say whether it was looking at acquired picture or at the plan drawn
    underneath it. A few broad blobs are enough to make it unmistakably a
    photograph of something.
    """
    down, across = np.ogrid[:size, :size]
    pattern = (
        np.sin(down / (size / 6.0) + seed) * np.cos(across / (size / 5.0) + seed * 0.7)
    )
    values = BRIGHT * 0.45 + BRIGHT * 0.4 * pattern
    return np.clip(values, 1, 65535).astype(np.uint16)[None, :, :]


def acquire_tiles(canvases: TileCanvases, places) -> None:
    """Write picture into the given (row, column) places of the planned grid."""
    for seed, (row, column) in enumerate(places):
        canvases.write(
            _speckled_tile(ACQ_TILE_VOXELS, seed),
            origin=(0, row * ACQ_TILE_VOXELS, column * ACQ_TILE_VOXELS),
            tile_index=(0, row, column),
        )


# ---------------------------------------------------------------------------
# Question 4: what a plate-sized layer actually costs
# ---------------------------------------------------------------------------
#
# A microplate is about 128 by 86 millimetres. At ten micrometres to a voxel that
# is 12800 by 8600 voxels, and the arithmetic that has never been checked says it
# comes to roughly seventeen hundred pieces, a few hundred kilobytes, and a few
# seconds to write.
#
# It is measured four ways rather than one, because two separate things are in
# doubt. Keeping the pyramid of smaller copies or not changes how much is written;
# and a *patterned* background compresses far less well than a flat one, so the
# cheerful answer for flat colour may not survive somebody wanting a grid drawn
# on their plate.

PLATE_WIDE_MM = 128.0
PLATE_TALL_MM = 86.0
PLATE_UM = 10.0
PLATE_WIDE = int(PLATE_WIDE_MM * 1000 / PLATE_UM)   # 12800
PLATE_TALL = int(PLATE_TALL_MM * 1000 / PLATE_UM)   # 8600
# How much of the plate is written at a time. The plate is written in bands
# rather than in one piece simply so that a machine with modest memory can do it;
# a band of 500 rows is about twelve megabytes.
PLATE_BAND = 500


def _plate_band(top: int, height: int, *, patterned: bool) -> np.ndarray:
    """One horizontal band of the plate drawing.

    ``patterned`` decides between the two cases being compared: a plain drawing
    of the carrier and its wells, which is mostly empty and compresses down to
    almost nothing, and the same drawing with a fine grid over the whole of it,
    which does not.
    """
    plane = np.zeros((height, PLATE_WIDE), dtype=np.uint16)
    down = np.arange(top, top + height)[:, None]
    across = np.arange(PLATE_WIDE)[None, :]
    # The outline of the carrier. The left and right edges are in every band;
    # the top and bottom edges only fall in the first and last ones, so which
    # rows of *this* band belong to them is worked out from where the band sits.
    edge = 20
    plane[:, :edge] = BRIGHT
    plane[:, -edge:] = BRIGHT
    rows = np.arange(top, top + height)
    plane[(rows < edge) | (rows >= PLATE_TALL - edge), :] = BRIGHT
    # A grid of wells, the way a 96-well plate has them: twelve across, eight
    # down, on nine-millimetre centres.
    for row in range(8):
        for column in range(12):
            centre_y = (11.0 + 9.0 * row) * 1000 / PLATE_UM
            centre_x = (14.0 + 9.0 * column) * 1000 / PLATE_UM
            radius = 3.2 * 1000 / PLATE_UM
            ring = (down - centre_y) ** 2 + (across - centre_x) ** 2
            plane[(ring < radius ** 2) & (ring > (radius - 8) ** 2)] = BRIGHT
    if patterned:
        # A grid every millimetre, which is a hundred voxels at ten micrometres.
        # Drawn dimmer than the carrier so the two can be told apart on screen.
        grid = ((down % 100) < 2) | ((across % 100) < 2)
        plane[grid & (plane == 0)] = BRIGHT // 3
    return plane


def write_the_plate(folder: Path, *, name: str, patterned: bool,
                    pyramid: bool) -> dict:
    """Write a whole plate-sized layer and time it.

    Returns what it cost: how long it took in seconds, how many bytes it left on
    disk, and how many files. Those three are the answer to question 4, and they
    are counted from the filesystem afterwards rather than estimated.
    """
    started = time.perf_counter()
    canvases = TileCanvases.create(
        folder,
        name=name,
        canvas_shape=(1, PLATE_TALL, PLATE_WIDE),
        tile_shape=(1, PLATE_BAND, PLATE_WIDE),
        tile_step=(1, PLATE_BAND, PLATE_WIDE),
        voxel_size_um=(PLATE_UM, PLATE_UM, PLATE_UM),
        channels=_one_channel(),
        # ``levels=1`` keeps only the full-size copy. It is the honest way to ask
        # what the pyramid costs, because the pyramid is the part that is written
        # over and over as tiles land.
        levels=None if pyramid else 1,
        discard_existing_run=True,
    )
    for index, top in enumerate(range(0, PLATE_TALL, PLATE_BAND)):
        height = min(PLATE_BAND, PLATE_TALL - top)
        canvases.write(
            _plate_band(top, height, patterned=patterned)[None, :, :],
            origin=(0, top, 0),
            tile_index=(0, index, 0),
        )
    canvases.close()
    seconds = time.perf_counter() - started
    store = folder / f"{name}.ome.zarr"
    files = [path for path in store.rglob("*") if path.is_file()]
    return {
        "name": name,
        "patterned": patterned,
        "pyramid": pyramid,
        "seconds": round(seconds, 2),
        "bytes": sum(path.stat().st_size for path in files),
        "files": len(files),
        "voxels": PLATE_TALL * PLATE_WIDE,
    }


# ---------------------------------------------------------------------------
# Question 5: does a pattern survive being shrunk down?
# ---------------------------------------------------------------------------
#
# Every smaller copy in the pyramid halves how much detail is kept, so a pattern
# whose stripes are only a few voxels apart cannot possibly survive many
# halvings. The claim being tested is that a pattern with a *physical* period —
# a grid line every millimetre, which is a hundred voxels at ten micrometres —
# does survive, while one defined in voxels does not.
#
# Both are written into the same size of canvas with the same number of copies,
# so the only difference between them is the period of the pattern.

PATTERN_VOXELS = 8192
PATTERN_UM = 10.0
# How many progressively smaller copies to keep. Asked for outright rather than
# left to the writer's own reckoning, because the whole question here is how far
# down the pyramid each pattern survives — and a pyramid that stops after four
# copies would answer "both of them made it to the bottom" without that meaning
# anything.
PATTERN_LEVELS = 7
# The band the pattern is written in, so that a machine with modest memory can
# write an eight-thousand-voxel canvas without holding all of it at once.
PATTERN_BAND = 1024
# A line every millimetre. At ten micrometres to a voxel that is every hundred
# voxels, and the line is drawn six voxels (sixty micrometres) wide.
PHYSICAL_PERIOD_VOXELS = 100
PHYSICAL_LINE_VOXELS = 6
# A line every four voxels, drawn two voxels wide. This one is defined in voxels
# with no physical meaning at all, which is the case the claim says will fail.
VOXEL_PERIOD_VOXELS = 4
VOXEL_LINE_VOXELS = 2


def write_a_pattern(folder: Path, *, name: str, period: int, line: int) -> None:
    """Write a grid of lines with the given period and thickness, in voxels."""
    canvases = TileCanvases.create(
        folder,
        name=name,
        canvas_shape=(1, PATTERN_VOXELS, PATTERN_VOXELS),
        tile_shape=(1, PATTERN_BAND, PATTERN_VOXELS),
        tile_step=(1, PATTERN_BAND, PATTERN_VOXELS),
        voxel_size_um=(PATTERN_UM, PATTERN_UM, PATTERN_UM),
        channels=_one_channel(),
        levels=PATTERN_LEVELS,
        discard_existing_run=True,
    )
    across = np.arange(PATTERN_VOXELS)[None, :]
    for index, top in enumerate(range(0, PATTERN_VOXELS, PATTERN_BAND)):
        height = min(PATTERN_BAND, PATTERN_VOXELS - top)
        down = np.arange(top, top + height)[:, None]
        grid = ((down % period) < line) | ((across % period) < line)
        plane = np.where(grid, BRIGHT, 0).astype(np.uint16)
        canvases.write(plane[None, :, :], origin=(0, top, 0),
                       tile_index=(0, index, 0))
    canvases.close()


# ---------------------------------------------------------------------------
# Question 6: the ambiguity that is not yet fixed
# ---------------------------------------------------------------------------
#
# Making unimaged room see-through works by asking how bright a voxel is: if
# there is nothing there, let whatever is underneath show through. But somewhere
# that genuinely *was* imaged and came back black looks exactly the same to that
# question, so it disappears too.
#
# These two stores show it plainly. The lower one is a carrier drawing, so there
# is something underneath to show through. The upper one has a single tile
# written into it holding real but very dark picture — mostly nought, with one
# faint blob a couple of counts above it — sitting beside a great deal of room
# nobody has visited. In the picture, the imaged-and-black part of that tile and
# the never-visited room beside it are indistinguishable.
#
# `viz_studio/OPTIONS.md` records the one-line change to the writer that would
# settle this. It is deliberately *not* applied here. The point of these stores
# is to put the problem in front of somebody as a picture so the decision can be
# made on what it actually looks like.

DARK_VOXELS = 2048
DARK_TILE = 512
# Where the one dark tile is written, in tiles across and down.
DARK_TILE_AT = (1, 1)


def write_the_ambiguity(folder: Path, *, under: str = "darkunder",
                        over: str = "darkover") -> None:
    """A carrier underneath, and above it one tile of genuinely dark picture.

    The tile really was acquired. Most of it is nought, because that is what a
    camera looking at nothing produces once its background has been taken off,
    and a faint blob sits in the middle of it a couple of counts above nought so
    that there is something there to see. Everything around the tile was never
    written at all.
    """
    lower = TileCanvases.create(
        folder,
        name=under,
        canvas_shape=(1, DARK_VOXELS, DARK_VOXELS),
        tile_shape=(1, DARK_VOXELS, DARK_VOXELS),
        tile_step=(1, DARK_VOXELS, DARK_VOXELS),
        voxel_size_um=(1.0, 1.0, 1.0),
        channels=_one_channel(),
        discard_existing_run=True,
    )
    plane = np.zeros((DARK_VOXELS, DARK_VOXELS), dtype=np.uint16)
    # A coarse grid, so that wherever it shows through it is obvious that it is
    # the layer underneath being seen rather than the layer above being dark.
    down = np.arange(DARK_VOXELS)[:, None]
    across = np.arange(DARK_VOXELS)[None, :]
    plane[(((down % 128) < 6) | ((across % 128) < 6))] = BRIGHT
    lower.write(plane[None, :, :], origin=(0, 0, 0), tile_index=(0, 0, 0))
    lower.close()

    upper = TileCanvases.create(
        folder,
        name=over,
        canvas_shape=(1, DARK_VOXELS, DARK_VOXELS),
        tile_shape=(1, DARK_TILE, DARK_TILE),
        tile_step=(1, DARK_TILE, DARK_TILE),
        voxel_size_um=(1.0, 1.0, 1.0),
        channels=_one_channel(),
        discard_existing_run=True,
    )
    tile = np.zeros((DARK_TILE, DARK_TILE), dtype=np.uint16)
    down = np.arange(DARK_TILE)[:, None]
    across = np.arange(DARK_TILE)[None, :]
    middle = DARK_TILE // 2
    blob = (down - middle) ** 2 + (across - middle) ** 2 < (DARK_TILE // 5) ** 2
    # Two counts. This is real signal — faint, but a camera really did record it.
    tile[blob] = 2
    row, column = DARK_TILE_AT
    upper.write(
        tile[None, :, :],
        origin=(0, row * DARK_TILE, column * DARK_TILE),
        tile_index=(0, row, column),
    )
    upper.close()

    # A third image marking where the microscope really did look.
    #
    # This is needed because there is no way to reveal the truth from the picture
    # itself — that is the whole problem. A shader asked to draw the upper layer
    # solid draws the *whole declared canvas* solid, including all the room
    # nobody visited, so it shows nothing useful. What actually knows where the
    # microscope went is the record the writer keeps beside the data, and this
    # simply draws that record as an outline so it can be laid over the picture.
    footprint = TileCanvases.create(
        folder,
        name="darkfootprint",
        canvas_shape=(1, DARK_VOXELS, DARK_VOXELS),
        tile_shape=(1, DARK_VOXELS, DARK_VOXELS),
        tile_step=(1, DARK_VOXELS, DARK_VOXELS),
        voxel_size_um=(1.0, 1.0, 1.0),
        channels=_one_channel(),
        discard_existing_run=True,
    )
    mark = np.zeros((DARK_VOXELS, DARK_VOXELS), dtype=np.uint16)
    y0, x0 = row * DARK_TILE, column * DARK_TILE
    thickness = 5
    mark[y0:y0 + DARK_TILE, x0:x0 + thickness] = BRIGHT
    mark[y0:y0 + DARK_TILE, x0 + DARK_TILE - thickness:x0 + DARK_TILE] = BRIGHT
    mark[y0:y0 + thickness, x0:x0 + DARK_TILE] = BRIGHT
    mark[y0 + DARK_TILE - thickness:y0 + DARK_TILE, x0:x0 + DARK_TILE] = BRIGHT
    footprint.write(mark[None, :, :], origin=(0, 0, 0), tile_index=(0, 0, 0))
    footprint.close()


# ---------------------------------------------------------------------------


def write_everything_but_the_plate(folder: Path) -> None:
    """Write every store the browser measurements need.

    The plate-sized ones are left out because they take far longer than the rest
    put together and only question 4 needs them; ``measure.py`` writes those
    itself, timing them as it goes, since the timing is the measurement.
    """
    folder.mkdir(parents=True, exist_ok=True)
    write_the_lower_layer(folder)
    write_the_upper_layer(folder)
    write_the_coarse_layer(folder)
    # The same feature at twice the coarseness, used to find out whether the
    # small offset between a coarse layer and a fine one grows with how coarse
    # the coarse one is.
    write_the_coarse_layer(folder, name="coarser", voxel_um=2 * COARSE_UM)
    write_the_fine_layer(folder)
    # The same fine image with its corner written down a hundred micrometres
    # wrong, so that the border reading can be shown to notice a real error.
    write_the_fine_layer(folder, name="finewrong", corner_wrong_by_um=100.0)
    write_the_carrier(folder)
    write_the_plan(folder)
    write_a_pattern(folder, name="physicalgrid",
                    period=PHYSICAL_PERIOD_VOXELS, line=PHYSICAL_LINE_VOXELS)
    write_a_pattern(folder, name="voxelgrid",
                    period=VOXEL_PERIOD_VOXELS, line=VOXEL_LINE_VOXELS)
    write_the_ambiguity(folder)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    write_everything_but_the_plate(args.folder)
    for path in sorted(args.folder.glob("*.ome.zarr")):
        print(path)
