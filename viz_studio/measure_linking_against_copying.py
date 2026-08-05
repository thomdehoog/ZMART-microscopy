"""Is a picture that was never written down as good to look at as one that was?

That is the whole question, and everything here exists to answer it with numbers.

Two ways of handing a run to the viewer
---------------------------------------

A run of many tiles has to reach the viewer as **one** image. The drawing engine
builds a layer per image and every layer takes part in every frame, so a thousand
separate positions draw at twenty-four frames in five seconds where one image
manages several hundred. There are two ways to produce that one image, and this
compares them over exactly the same tiles.

**Copying** — what :mod:`zmart_storage.cropped` already does, and the control here.
Every tile is written twice: once whole into the archive, and once again into a
canvas that holds the whole run as a single picture. It works, it is measured, and
it costs a second copy of every voxel.

**Pointing** — what :mod:`zmart_storage.linked` does, and the thing being tested. No
voxel of the full-size picture is copied anywhere. The view is a list saying which
piece of the picture is which piece of which tile, and the viewer's server answers
a request for a piece by handing over the tile's own file, byte for byte. Only the
zoomed-out copies are written, because shrinking makes numbers no file holds.

Pointing plainly saves disk. What is not obvious, and what this measures, is
whether it costs anything to *look* at — the picture arrives through one more step,
and a step on every piece of every frame is exactly the kind of thing that turns out
to matter.

What it reports, per size, for each arrangement
-----------------------------------------------

``first pixel``
    How long from opening the page until there is something of the specimen on
    screen. This is the wait an operator actually feels.
``requests``
    How many pieces of image the browser asked the server for while opening.
``flat frames``
    How many frames the viewer manages in five seconds in the everyday view. Below
    about fifty, panning and moving the contrast handles feel heavy.
``contrast``
    How long one nudge of a brightness slider takes — the number felt most directly,
    because judging a specimen means moving that slider.
``volume``
    The same frame count with the volume drawn instead of a plane, **as a share of
    the flat rate rather than on its own.** A machine without a graphics card draws
    through software, so an absolute figure for a volume says more about the machine
    than about the run. What holds anywhere is how much of its own rate the viewer
    keeps when asked for the harder view.
``on disk``
    What each arrangement costs beside the archive of whole tiles, which both of them
    need and neither of them writes twice.

Running it
----------

    python measure_linking_against_copying.py

That sweeps one, four, a hundred and about five hundred tiles. The two large sizes
— about two thousand and ten thousand tiles — are opt-in, because ten thousand tiles
takes several minutes to write and about two gigabytes of disk while it runs::

    ZMART_THE_WHOLE_SWEEP=1 python measure_linking_against_copying.py

Or choose the sizes yourself::

    python measure_linking_against_copying.py 100,2000

Everything is written under a temporary folder and removed as soon as each size has
been measured, so none of your own data is touched and the disk never holds more
than one size at a time. It needs the viewer page built
(``npm --prefix frontend run build``) and a browser, the same as the tests.

What this run cannot tell you
-----------------------------

The machine this was written on has no graphics card and draws through software, so
every frame rate here is a fact about that machine as much as about the run. What
survives the move to real hardware is the *comparison*: both arrangements were
measured in the same window, on the same tiles, minutes apart. If pointing costs
nothing here it is unlikely to cost much anywhere; if it costs something, the size
of that something will change.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

VIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(VIZ / "backend"))
sys.path.insert(0, str(VIZ.parent))

from measure_the_overlapping_run import _a_tile, look_at_it  # noqa: E402

from zmart_storage.canvas import Channel  # noqa: E402
from zmart_storage.cropped import TilesAndCanvas  # noqa: E402
from zmart_storage.linked import PlacedTile, link_the_tiles  # noqa: E402

# One acquired tile, and how far the stage steps between them. They are the same
# number here: **the tiles butt up against one another**, which is the case pointing
# is built for. A run whose tiles overlap can be pointed at as well, but only if the
# pieces are small enough to divide the trim, and that changes the piece size — which
# would make this a comparison of two things at once. See the note at the end of
# `LINKING_INSTEAD_OF_COPYING.md`.
#
# Deliberately small. What is being measured is how each arrangement behaves as the
# number of tiles grows, and that has nothing to do with how large each tile is.
TILE = (2, 128, 128)
STEP = (2, 128, 128)

# How large one piece of the picture is. A whole tile, which is what makes a piece of
# the view exactly a piece of a tile and so lets it be pointed at rather than copied.
CHUNK = 128

VOXEL_UM = (2.0, 0.35, 0.35)
ORIGIN_UM = (0.0, 250.0, 180.0)

# The brightness window both arrangements declare, so the viewer opens on a sensible
# picture instead of measuring one. That keeps this measurement about the drawing.
WINDOW = (0, 4000)

SIZES_BY_DEFAULT = (1, 4, 100, 500)
SIZES_IF_ASKED = (2000, 10000)
THE_WHOLE_SWEEP = "ZMART_THE_WHOLE_SWEEP"

# How many different tiles to make up and then reuse. Making a fresh one for every
# tile of a ten-thousand-tile run would spend more time inventing pictures than
# measuring anything, and it changes nothing being measured: the pieces of a zarr
# image are compressed one at a time, so two identical tiles cost the same as two
# different ones.
HOW_MANY_DIFFERENT_TILES = 16

# What each arrangement is called in the table.
COPIED = "canvas (copied)"
POINTED = "view (pointed at)"


def _how_the_raster_comes_out(size: int) -> tuple[int, int, int]:
    """A square raster, with colours and moments, coming to about ``size`` tiles.

    The smallest size is a single tile of a single colour at a single moment,
    because that is the degenerate case worth measuring; everything larger records
    two colours at two moments, which is where an arrangement that confused one
    recording of a field with another would show it.
    """
    if size <= 1:
        return 1, 1, 1
    channels = frames = 2
    across = max(1, round((size / (channels * frames)) ** 0.5))
    return across, channels, frames


# -- writing the run both ways -------------------------------------------------


def write_both_arrangements(folder: Path, size: int) -> dict:
    """Write the tiles once, and hand the same tiles to the viewer both ways.

    The archive of whole tiles is written once and shared, which is what makes this
    a fair comparison: the two arrangements differ in what is built *on top of* the
    same tiles and in nothing else.
    """
    across, channels, frames = _how_the_raster_comes_out(size)
    extent = tuple((across - 1) * STEP[axis] + TILE[axis] for axis in (1, 2))
    room = (TILE[0], extent[0], extent[1])

    run = TilesAndCanvas.create(
        folder,
        name="written",
        canvas_shape=room,
        tile_shape=TILE,
        tile_step=STEP,
        tile_grid=(1, across, across),
        voxel_size_um=VOXEL_UM,
        origin_um=ORIGIN_UM,
        channels=[Channel(name, window=WINDOW) for name in ("488", "561")[:channels]],
        frames=frames,
        chunk=CHUNK,
    )

    library = [_a_tile(seed) for seed in range(HOW_MANY_DIFFERENT_TILES)]
    began = time.monotonic()
    tiles = 0
    placed: list[PlacedTile] = []
    for frame in range(frames):
        for channel in range(channels):
            for row in range(across):
                for column in range(across):
                    where = run.write(
                        library[_which_tile(across, row, column, channel, frame)],
                        origin=(0, row * STEP[1], column * STEP[2]),
                        channel=channel,
                        frame=frame,
                        tile_index=(0, row, column),
                    )
                    tiles += 1
                    if frame == 0 and channel == 0:
                        placed.append(PlacedTile(
                            store=where,
                            lands_at=(0, row * STEP[1], column * STEP[2]),
                        ))
    run.close()
    writing = time.monotonic() - began

    began = time.monotonic()
    view = link_the_tiles(folder, name="pointed", tiles=placed, view_shape=room)
    pointing = time.monotonic() - began

    return {
        "tiles": tiles,
        "across": across,
        "channels": channels,
        "frames": frames,
        "positions": len(placed),
        "writing": writing,
        "pointing": pointing,
        "canvas": run.canvas_path,
        "archive": run.tiles_folder,
        "view": view.path,
        "pointers": view.pointers,
    }


def _which_tile(across: int, row: int, column: int, channel: int, frame: int) -> int:
    """Which of the made-up tiles this position, colour and moment was given."""
    return (
        (row * across + column) + channel * 5 + frame * 7
    ) % HOW_MANY_DIFFERENT_TILES


def what_they_weigh(shape: dict) -> dict:
    """How much disk each arrangement takes, in megabytes.

    The archive is counted on its own because both arrangements need it and neither
    writes it twice — it is the acquisition itself. What is being compared is what
    each of them adds on top.
    """
    def megabytes(path: Path) -> float:
        answered = subprocess.run(
            ["du", "-sk", str(path)], capture_output=True, text=True, check=False
        ).stdout.split()
        return (int(answered[0]) if answered else 0) / 1024

    return {
        "canvasMB": megabytes(shape["canvas"]),
        "viewMB": megabytes(shape["view"]),
        "archiveMB": megabytes(shape["archive"]),
    }


# -- one size ------------------------------------------------------------------


def measure(size: int) -> dict:
    """Write one run both ways, open each in the viewer, and clear it away."""
    work = Path(tempfile.mkdtemp(prefix=f"zmart-linking-{size}-"))
    try:
        run = work / "run"
        shape = write_both_arrangements(run, size)
        weighed = what_they_weigh(shape)
        print(
            f"    wrote {shape['tiles']} tiles into {shape['positions']} positions "
            f"in {shape['writing']:.0f} s, pointed at them in {shape['pointing']:.0f} s",
            flush=True,
        )
        # The canvas first and the view second, every time. They are measured minutes
        # apart on the same machine, so anything that drifts over those minutes lands
        # on the view rather than being shared out -- which is the conservative way
        # round, since the view is the thing being argued for.
        copied = look_at_it(run, store="written.ome.zarr")
        pointed = look_at_it(run, store="pointed.ome.zarr")
        return {
            "asked": size, **shape, **weighed,
            "arrangements": {COPIED: copied, POINTED: pointed},
        }
    finally:
        # Cleared away before the next size is written, so the disk never holds two.
        shutil.rmtree(work, ignore_errors=True)


# -- the table -----------------------------------------------------------------


def report(rows: list[dict]) -> None:
    """Print the comparison, and then say in words what it means."""
    print()
    print(
        f"{'tiles':>7} {'arrangement':>18} {'first pixel':>12} {'requests':>9} "
        f"{'flat frames':>12} {'contrast':>10} {'volume':>7} {'on disk':>9}"
    )
    print("-" * 92)
    for row in rows:
        for at, (named, found) in enumerate(row["arrangements"].items()):
            first = "-" if found["firstPixel"] is None else f"{found['firstPixel']:.1f} s"
            share = (
                "-" if not found["flatFrames"]
                else f"{found['volumeFrames'] / found['flatFrames']:.0%}"
            )
            weight = row["canvasMB"] if named == COPIED else row["viewMB"]
            print(
                f"{row['tiles'] if at == 0 else '':>7} {named:>18} {first:>12} "
                f"{found['requests']:>9} {found['flatFrames']:>12} "
                f"{found['contrastMs']:>7} ms {share:>7} {weight:>6.0f} MB"
            )
        print()

    print(
        f"{'tiles':>7} {'archive':>10} {'writing both':>14} {'pointing':>10} "
        f"{'view / canvas':>14}"
    )
    print("-" * 60)
    for row in rows:
        share = "-" if not row["canvasMB"] else f"{row['viewMB'] / row['canvasMB']:.0%}"
        print(
            f"{row['tiles']:>7} {row['archiveMB']:>7.0f} MB "
            f"{row['writing']:>11.0f} s {row['pointing']:>8.0f} s {share:>14}"
        )

    print()
    _say_what_it_means(rows)


def _say_what_it_means(rows: list[dict]) -> None:
    """Read the table out loud, so the answer does not depend on reading it right."""
    def each(what: str, named: str) -> list[float]:
        return [row["arrangements"][named][what] for row in rows]

    drawn = [
        pointed / copied
        for pointed, copied in zip(each("flatFrames", POINTED), each("flatFrames", COPIED), strict=True)
        if copied
    ]
    if drawn:
        worst = min(drawn)
        print(
            f"Pointing draws at between {min(drawn):.0%} and {max(drawn):.0%} of the "
            f"rate the copied canvas draws at.\n"
            + (
                "That is the same rate within the noise of this measurement, so the\n"
                "picture being pointed at rather than written down costs nothing to\n"
                "look at."
                if worst > 0.9 else
                f"At its worst, pointing costs {1 - worst:.0%} of the frame rate. That\n"
                "is a real cost and it should be weighed against the disk it saves."
            )
        )

    opening = [
        pointed / copied
        for pointed, copied in zip(each("firstPixel", POINTED), each("firstPixel", COPIED), strict=True)
        if copied
    ]
    if opening:
        print(
            f"\nThe first of the specimen appears in between {min(opening):.0%} and "
            f"{max(opening):.0%} of the time\nthe canvas takes."
        )

    asked = [
        pointed - copied
        for pointed, copied in zip(each("requests", POINTED), each("requests", COPIED), strict=True)
    ]
    print(
        f"\nThe browser asked for between {min(asked):+d} and {max(asked):+d} more "
        "pieces of picture when\npointing than when copying. The pieces are the same "
        "size in both arrangements,\nso this should be nought or close to it; a large "
        "number here would mean the two\nwere not really being asked the same question."
    )

    disk = [row["viewMB"] / row["canvasMB"] for row in rows if row["canvasMB"]]
    if disk:
        print(
            f"\nOn disk the pointed-at view costs between {min(disk):.0%} and "
            f"{max(disk):.0%} of what the canvas\ncosts, over the same tiles. What is "
            "left is the zoomed-out copies, which cannot\nbe pointed at because "
            "shrinking the picture makes numbers no file holds."
        )

    print(
        "\nThe volume column is a share of the flat rate rather than a number of "
        "frames,\nand deliberately so: this machine draws through software, so an "
        "absolute figure\nfor a volume says more about the machine than about the run."
    )

    heavy = [
        row for row in rows
        if row["arrangements"][POINTED]["flatFrames"] < 50
    ]
    if heavy:
        print(
            f"\nNote that at {heavy[0]['tiles']} tiles the pointed-at view managed only "
            f"{heavy[0]['arrangements'][POINTED]['flatFrames']} frames in five\nseconds. "
            "A run that size is heavy to work with whichever way it is shown."
        )


def main() -> None:
    chosen = [
        part for argument in sys.argv[1:] for part in argument.split(",") if part
    ]
    if chosen:
        sizes = [int(part) for part in chosen]
    elif os.environ.get(THE_WHOLE_SWEEP):
        sizes = [*SIZES_BY_DEFAULT, *SIZES_IF_ASKED]
    else:
        sizes = list(SIZES_BY_DEFAULT)
        print(
            f"Sweeping {', '.join(str(size) for size in sizes)} tiles. The two large "
            f"sizes ({', '.join(str(size) for size in SIZES_IF_ASKED)}) are not part of "
            f"an\nordinary run, because ten thousand tiles takes several minutes to "
            f"write and\nabout two gigabytes of disk. Set {THE_WHOLE_SWEEP}=1 to "
            "include them."
        )

    if not (VIZ / "frontend" / "dist" / "index.html").exists():
        print(
            "The viewer page has not been built, so there is nothing to open. Build "
            "it first:\n\n    npm --prefix frontend run build\n"
        )
        raise SystemExit(1)

    rows = []
    for size in sizes:
        print(f"\n  about {size} tiles ...", flush=True)
        rows.append(measure(size))
    report(rows)


if __name__ == "__main__":
    main()
