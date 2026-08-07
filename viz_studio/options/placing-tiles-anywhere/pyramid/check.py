"""Check every size of the composed picture, and measure what each size costs.

Two questions are answered here, and neither needs anybody to look at a picture.

**Is it right?** Every piece the server would serve, at all four sizes, is
composed, the bytes are written out as an ordinary zarr store, that store is
opened again with plain zarr — so the encoding is checked as well as the
arithmetic — and every voxel is compared with a canvas built independently in
numpy and averaged down the same way. The same comparison is then made again over
HTTP, through the real server, so the routing and the headers are checked too.

**What does it cost?** A piece of the eighth-size picture covers sixty-four times
the ground of a full-size piece, so it has to be read out of far more of the
positions' files. Whether the work grows in step with that is measured rather than
argued about: each piece is timed, and the files it had to be read out of are
counted twice over — once by working it out from the geometry, and once by
watching every read the zarr library actually makes.
"""

from __future__ import annotations

import shutil
import statistics
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import zarr
from zarr.storage import LocalStore

sys.path.insert(0, str(Path(__file__).resolve().parent))

import geometry as g
from compose import Composer
from compose_server import serve, STORE

HERE = Path(__file__).resolve().parent
POSITIONS = HERE / "run" / "pyramid.ome.zarr" / "positions"
READ_BACK = HERE / "read-back.zarr"

# How many times each piece is composed when it is being timed. Composing is a few
# milliseconds, so one reading of one piece is mostly noise; the middle of several
# is a number worth quoting.
REPEATS = 7


# ---------------------------------------------------------------------------
# Watching every read the zarr library makes
# ---------------------------------------------------------------------------

READS: list[str] = []


class Counting(LocalStore):
    """A folder of files that keeps a note of every file it is asked for.

    This is how the count of "files read per piece" is checked rather than
    trusted. The arithmetic in ``Composer.source_chunks_read`` works the number out
    from the geometry; this watches what really happened. If the two ever disagree
    the arithmetic is wrong, and the cost table would be quietly describing
    something other than the work being done.
    """

    async def get(self, key, prototype, byte_range=None):
        READS.append(key)
        return await super().get(key, prototype, byte_range)

    async def get_partial_values(self, prototype, key_ranges):
        for key, _ in key_ranges:
            READS.append(key)
        return await super().get_partial_values(prototype, key_ranges)


def a_watched_composer() -> Composer:
    """The same composer, but reading through folders that count what they hand out."""
    composer = Composer(POSITIONS, g.PLACES)
    folders = sorted(POSITIONS.glob("*.ome.zarr"))
    composer.arrays = [
        zarr.open_array(Counting(str(one / "0"), read_only=True), mode="r")
        for one in folders
    ]
    return composer


# ---------------------------------------------------------------------------
# Is it right?
# ---------------------------------------------------------------------------


def compose_everything(composer: Composer) -> dict[int, dict[tuple[int, int], bytes]]:
    """Every piece of every size, composed once."""
    made = {}
    for level in range(g.LEVELS):
        down, across = composer.grid(level)
        made[level] = {(cy, cx): composer.bytes_for(level, cy, cx)
                       for cy in range(down) for cx in range(across)}
    return made


def read_back(composer: Composer, made: dict, folder: Path) -> dict[int, np.ndarray]:
    """Write the pieces out as a plain zarr store and open it again as one.

    Opening it with plain zarr, which knows nothing of this experiment, is the
    point: if the bytes were encoded even slightly wrongly, this is where it shows,
    rather than three steps later as a black window in a browser.
    """
    if folder.exists():
        shutil.rmtree(folder)
    pictures = {}
    for level in range(g.LEVELS):
        (folder / str(level)).mkdir(parents=True)
        (folder / str(level) / "zarr.json").write_bytes(composer.array_json(level))
        for (cy, cx), raw in made[level].items():
            where = folder / str(level) / "c" / "0" / "0" / "0" / str(cy)
            where.mkdir(parents=True, exist_ok=True)
            (where / str(cx)).write_bytes(raw)
        pictures[level] = zarr.open_array(str(folder / str(level)), mode="r")[0, 0, 0]
    return pictures


def compare(pictures: dict[int, np.ndarray], what: str) -> int:
    """Compare each size against the independently built canvas, voxel by voxel."""
    worst_total = 0
    print(f"\n{what}")
    print(f"{'level':>5}  {'size':>12}  {'voxels checked':>15}  {'voxels wrong':>13}")
    for level in range(g.LEVELS):
        meant = g.truth(level)
        got = pictures[level]
        wrong = int((got != meant).sum())
        worst_total += wrong
        print(f"{level:>5}  {f'{meant.shape[0]} x {meant.shape[1]}':>12}  "
              f"{meant.size:>15,}  {wrong:>13,}")
        if wrong:
            # A disagreement is a finding, so it is described rather than hidden
            # behind a failure: how far off, and whereabouts.
            difference = got.astype(int) - meant.astype(int)
            rows, columns = np.nonzero(difference)
            print(f"        largest disagreement: {np.abs(difference).max()} "
                  f"grey levels; rows {rows.min()}–{rows.max()}, "
                  f"columns {columns.min()}–{columns.max()}")
    return worst_total


# ---------------------------------------------------------------------------
# What does it cost?
# ---------------------------------------------------------------------------


def cost(composer: Composer, watched: Composer) -> None:
    """Time every piece at every size, and count the files each one is read from."""
    # Everything composed once first, so that no size is charged for warming up
    # the machine's own file cache while the others are not.
    compose_everything(composer)

    # What one bare read of one of the positions' files costs, on its own. It is
    # the unit everything below is built out of, so having it makes the table
    # readable: if a piece that reads twenty files takes twenty times this, the
    # cost is simply the reading and there is nothing else to look for.
    one_read = []
    for _ in range(50):
        started = time.perf_counter()
        composer.arrays[0][0, 0, 0, 0:g.CHUNK, 0:g.CHUNK]
        one_read.append((time.perf_counter() - started) * 1000)
    print(f"\nreading one of the positions' own 128-voxel files, on its own: "
          f"{statistics.median(one_read):.2f} ms")

    print("\nwhat one piece costs, by size")
    print(f"{'level':>5}  {'pieces':>7}  {'ground a piece covers':>21}  "
          f"{'median ms':>9}  {'worst ms':>8}  {'files read':>10}  "
          f"{'watched':>8}  {'ms per file':>11}  {'files, whole picture':>20}  "
          f"{'whole picture ms':>16}")
    for level in range(g.LEVELS):
        down, across = composer.grid(level)
        reach = g.CHUNK * 2 ** level
        per_piece = []
        files = []
        watched_files = []
        for cy in range(down):
            for cx in range(across):
                readings = []
                for _ in range(REPEATS):
                    started = time.perf_counter()
                    composer.bytes_for(level, cy, cx)
                    readings.append((time.perf_counter() - started) * 1000)
                per_piece.append(statistics.median(readings))
                files.append(composer.source_chunks_read(level, cy, cx))
                READS.clear()
                watched.compose(level, cy, cx)
                watched_files.append(len([one for one in READS
                                          if not one.endswith("zarr.json")]))
        print(f"{level:>5}  {down * across:>7}  {f'{reach} x {reach}':>21}  "
              f"{statistics.median(per_piece):>9.2f}  {max(per_piece):>8.2f}  "
              f"{f'{statistics.median(files):.0f} / {max(files)}':>10}  "
              f"{f'{statistics.median(watched_files):.0f}':>8}  "
              f"{sum(per_piece) / sum(files):>11.2f}  {sum(files):>20}  "
              f"{sum(per_piece):>16.1f}")

    print("\n  'files read' is the median and the worst count of the positions' own "
          "128-voxel\n  files one piece has to be read out of; 'watched' is the same "
          "median counted by\n  watching every read zarr made, as a check on the "
          "arithmetic.")

    # And what the two halves of the work cost separately, so the shape of the
    # growth can be read rather than guessed at.
    print("\nwhere the time goes, for the slowest piece of each size")
    print(f"{'level':>5}  {'reading and laying out ms':>25}  "
          f"{'averaging ms':>12}  {'encoding ms':>11}")
    for level in range(g.LEVELS):
        down, across = composer.grid(level)
        worst = max(((cy, cx) for cy in range(down) for cx in range(across)),
                    key=lambda place: composer.source_chunks_read(level, *place))
        factor = 2 ** level
        laying, averaging, encoding = [], [], []
        for _ in range(REPEATS):
            started = time.perf_counter()
            y0, y1, x0, x1 = composer.ground(level, *worst)
            ground = np.zeros((g.CHUNK * factor, g.CHUNK * factor), "uint16")
            for number in composer.touching(level, *worst):
                ty, tx = composer.places[number]
                ay, by = max(y0, ty), min(y1, ty + g.TILE)
                ax, bx = max(x0, tx), min(x1, tx + g.TILE)
                ground[ay - y0:by - y0, ax - x0:bx - x0] = composer.arrays[number][
                    0, 0, 0, ay - ty:by - ty, ax - tx:bx - tx]
            middle = time.perf_counter()
            piece = g.shrink(ground, factor)
            shrunk = time.perf_counter()
            composer.encode(level, piece)
            done = time.perf_counter()
            laying.append((middle - started) * 1000)
            averaging.append((shrunk - middle) * 1000)
            encoding.append((done - shrunk) * 1000)
        print(f"{level:>5}  {statistics.median(laying):>25.2f}  "
              f"{statistics.median(averaging):>12.2f}  "
              f"{statistics.median(encoding):>11.2f}")


# ---------------------------------------------------------------------------
# The same thing again, over the wire
# ---------------------------------------------------------------------------


def over_http(composer: Composer) -> dict[int, np.ndarray]:
    """Fetch every piece of every size from the real server and reassemble them."""
    server, address, _ = serve(POSITIONS, g.PLACES)
    folder = HERE / "over-http.zarr"
    if folder.exists():
        shutil.rmtree(folder)
    pictures = {}
    try:
        for level in range(g.LEVELS):
            (folder / str(level)).mkdir(parents=True)
            described = urllib.request.urlopen(
                f"{address}/{STORE}/{level}/zarr.json", timeout=10).read()
            (folder / str(level) / "zarr.json").write_bytes(described)
            down, across = composer.grid(level)
            for cy in range(down):
                for cx in range(across):
                    raw = urllib.request.urlopen(
                        f"{address}/{STORE}/{level}/c/0/0/0/{cy}/{cx}",
                        timeout=10).read()
                    where = folder / str(level) / "c" / "0" / "0" / "0" / str(cy)
                    where.mkdir(parents=True, exist_ok=True)
                    (where / str(cx)).write_bytes(raw)
            pictures[level] = zarr.open_array(
                str(folder / str(level)), mode="r")[0, 0, 0]
    finally:
        server.shutdown()
    shutil.rmtree(folder)
    return pictures


def what_pointing_would_have_given() -> None:
    """The comparison that says whether composing the smaller copies was necessary.

    The way this project builds a zoomed-out picture today is by *pointing*: the
    writer gives every position its own smaller copies, made by keeping every
    second voxel, and the picture's half-size level is described as being those
    copies, laid at half the position's own offset. It costs nothing to build,
    which is exactly why it is worth knowing what it gets wrong.

    Half of 179 is 89.5, and there is no such voxel, so the copy has to be laid at
    89 or at 90. Either way it is a quarter of a micrometre out — and because each
    position's copy kept its own every-second voxel, two overlapping positions
    sampled the specimen on grids that are out of step with each other as well.
    This lays them the most favourable way, rounding to the nearest voxel, and
    compares the result with what the half-size picture should be.
    """
    folders = sorted(POSITIONS.glob("*.ome.zarr"))
    smaller = [zarr.open_array(str(one / "1"), mode="r") for one in folders]
    deepest = max(len(list(one.glob("[0-9]*"))) for one in folders)

    height, width = g.level_shape(1)
    pointed = np.zeros((height, width), "uint16")
    for number, (y, x) in enumerate(g.PLACES):
        piece = smaller[number][0, 0, 0]
        at_y, at_x = round(y / 2), round(x / 2)
        pointed[at_y:at_y + piece.shape[0], at_x:at_x + piece.shape[1]] = piece

    meant = g.truth(1)
    difference = pointed.astype(int) - meant.astype(int)
    wrong = int((difference != 0).sum())
    print("\nwhat pointing at the positions' own smaller copies would have given")
    print(f"   smaller copies each position actually has : "
          f"{deepest - 1} (the picture needs {g.LEVELS - 1})")
    print(f"   voxels checked, at half size              : {meant.size:,}")
    print(f"   voxels wrong                              : {wrong:,} "
          f"({100 * wrong / meant.size:.0f}%)")
    if wrong:
        print(f"   largest disagreement                      : "
              f"{np.abs(difference).max()} grey levels out of 65535")
        print(f"   typical disagreement where it disagrees   : "
              f"{np.abs(difference)[difference != 0].mean():.0f} grey levels")


def main() -> None:
    composer = Composer(POSITIONS, g.PLACES)
    watched = a_watched_composer()

    print(f"tile {g.TILE}, piece {g.CHUNK}, step {g.STEP}, overlap {g.OVERLAP} voxels")
    print(f"positions                          : {len(g.PLACES)}")
    print(f"canvas                             : {g.CANVAS_Y} x {g.CANVAS_X}")
    print(f"sizes offered                      : {g.LEVELS}")
    for level in range(g.LEVELS):
        down, across = composer.grid(level)
        straddling = sum(1 for cy in range(down) for cx in range(across)
                         if len(composer.touching(level, cy, cx)) > 1)
        alone = sum(1 for cy in range(down) for cx in range(across)
                    if len(composer.touching(level, cy, cx)) == 1)
        empty = sum(1 for cy in range(down) for cx in range(across)
                    if not composer.touching(level, cy, cx))
        print(f"   level {level}: {down * across:>2} pieces, "
              f"{straddling} straddle more than one position, "
              f"{alone} rest on one, {empty} touch none")

    made = compose_everything(composer)
    wrong = compare(read_back(composer, made, READ_BACK),
                    "composed, encoded, written out and opened again with plain zarr")
    shutil.rmtree(READ_BACK)

    wrong += compare(over_http(composer),
                     "the same, fetched from the running server over HTTP")

    what_pointing_would_have_given()
    cost(composer, watched)

    if wrong:
        raise SystemExit(
            "\nthe composed picture is not the picture we meant to make — see the "
            "disagreements above")


if __name__ == "__main__":
    main()
