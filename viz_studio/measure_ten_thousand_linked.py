"""Ten thousand positions shown as one picture by pointers alone: does it hold?

This is the measurement the linked view exists for. Everything about linking has
been proven at tens of tiles — the pointers resolve, the picture matches a written
canvas voxel for voxel, building is quick. None of that says what happens at the
size this project is actually aiming for, and a thing that holds at fifty tiles
and fails at ten thousand would be worse than useless, because it would look like
an answer.

Four questions, each answered with a number rather than an argument:

Does a tile still cost the same to add when it is the ten-thousandth?
    The view is grown the way a real run grows it — one position at a time,
    through :class:`zmart_storage.linked.GrowingLinkedView` — and every add is
    timed. The first hundred and the last hundred should cost the same; if adding
    grows with the run, an acquisition pays it thousands of times over.

Does the server's memory stay in proportion to the tiles?
    An earlier arrangement spread the map into one entry per *piece* and would
    have reached tens of gigabytes here. The reader now keeps one note per tile
    per row of pieces it crosses, and this measures what that really holds at ten
    thousand tiles, in megabytes, using Python's own accounting.

Is looking a piece up still quick?
    Every request for a piece of the picture goes through the lookup, so it has
    to stay well under a millisecond. Measured over tens of thousands of asks:
    pieces a tile supplies, pieces on ground nobody imaged, and pieces of a
    zoomed-out copy.

Is the answer still right?
    A sample of pieces across the picture and its zoomed-out copies is followed
    through the pointers to the tile file each names, and the voxels decoded and
    compared against what was written there. Speed that serves the wrong tile is
    not speed.

The run is deliberately awkward: tiles sit on a grid but about one in thirteen
was never imaged, so the picture has holes — the shape smart microscopy
produces, and the case the row-by-row lookup has to earn its keep on. The tiles
are small so that ten thousand of them fit comfortably in a temporary folder;
what is being measured — counts of tiles, rows and pieces — does not care how
many voxels a tile holds, only how many tiles there are.

Run it with::

    python measure_ten_thousand_linked.py           # 100 x 100 = 10,000 positions
    python measure_ten_thousand_linked.py 32        # smaller, if time is short

It writes about 150 MB under a temporary folder and removes it afterwards. It
needs no browser and no graphics card: what a browser would add — how request
counts feel on screen — is measured by ``measure_the_chunk_size.py``, and the
answer there depends on the piece size alone, which linking no longer changes.
"""

from __future__ import annotations

import json
import shutil
import statistics
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

import numpy as np
import zarr

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import linking  # noqa: E402  (the viewer's own reader, answering for the view)

from zmart_storage.canvas import Channel, _declare_one  # noqa: E402
from zmart_storage.linked import PlacedTile, start_a_growing_view  # noqa: E402

# One position: a single plane, 64 voxels across, in pieces of 32, keeping its
# own half-size copy so the view can point at every zoom and write nothing.
TILE = (1, 64, 64)
PIECE = 32
LEVELS = 2
VOXEL_UM = (2.0, 0.35, 0.35)

# About one position in thirteen is never imaged, scattered across the grid, so
# the picture has holes the way a smart-microscopy run does.
def _imaged(down: int, across: int) -> bool:
    return (down * 31 + across * 7) % 13 != 0


def _write_one_position(folder: Path, number: int, down: int, across: int) -> Path:
    """One position whose every voxel holds its own tile number.

    A constant per tile is enough to prove a pointer resolved to the right
    tile, and it keeps the check readable: the value found is the tile that
    should be there, or the picture is wrong.
    """
    store = folder / f"pos{number:05d}.ome.zarr"
    arrays = _declare_one(
        store, canvas_shape=TILE, frames=1, channels=1, dtype="uint16",
        chunk=PIECE, levels=LEVELS, voxel_size_um=VOXEL_UM,
        origin_um=(0.0, down * TILE[1] * VOXEL_UM[1],
                   across * TILE[2] * VOXEL_UM[2]),
        channel_blocks=[Channel("488", window=(0, 65535)).described(65535)],
    )
    value = np.uint16(number)
    arrays[0][0, 0] = np.full(TILE, value, dtype="uint16")
    for level in range(1, LEVELS):
        factor = 2 ** level
        small = (TILE[0], max(1, TILE[1] // factor), max(1, TILE[2] // factor))
        arrays[level][0, 0] = np.full(small, value, dtype="uint16")
    return store


def main() -> None:
    grid = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    work = Path(tempfile.mkdtemp(prefix="linked10k-"))
    try:
        _measure(work, grid)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _measure(work: Path, grid: int) -> None:
    positions = work / "positions"
    positions.mkdir()
    room = (TILE[0], grid * TILE[1], grid * TILE[2])
    # Which tile number was written at each imaged grid place, for checking a
    # followed pointer against what should be there.
    numbered: dict[tuple[int, int], int] = {}
    for down in range(grid):
        for across in range(grid):
            if _imaged(down, across):
                numbered[(down, across)] = len(numbered)

    # -- growing the view, one position at a time, timing every add ------------
    print(f"growing a view over up to {grid * grid} positions "
          f"({room[1]} x {room[2]} voxels, pieces of {PIECE}) ...")
    adds_ms: list[float] = []
    writes_ms: list[float] = []
    number = 0
    first_store: Path | None = None
    view = None
    begun = time.perf_counter()
    for down in range(grid):
        for across in range(grid):
            if not _imaged(down, across):
                continue
            started = time.perf_counter()
            store = _write_one_position(positions, number, down, across)
            writes_ms.append((time.perf_counter() - started) * 1000)
            lands = (0, down * TILE[1], across * TILE[2])
            if view is None:
                first_store = store
                view = start_a_growing_view(
                    work, like=PlacedTile(store=store, lands_at=lands),
                    view_shape=room, name="survey", levels=LEVELS,
                    origin_um=(0.0, 0.0, 0.0))
            started = time.perf_counter()
            view.add(PlacedTile(store=store, lands_at=lands))
            adds_ms.append((time.perf_counter() - started) * 1000)
            number += 1
    assert view is not None and first_store is not None
    started = time.perf_counter()
    built = view.finish()
    finishing = time.perf_counter() - started
    growing = time.perf_counter() - begun

    listed = linking.the_map_inside(built.path)
    assert listed is not None
    map_bytes = len(json.dumps(listed))
    hundred = max(1, min(100, len(adds_ms) // 2))
    nothing = (" (nothing written at any zoom)"
               if built.pointed_levels == built.levels else "")
    print(f"  positions imaged      {number}")
    print(f"  pointed levels        {built.pointed_levels} of "
          f"{built.levels}{nothing}")
    print(f"  whole run             {growing:8.1f} s   (writing the positions "
          f"included, {statistics.median(writes_ms):.1f} ms median each)")
    print(f"  one add, median       {statistics.median(adds_ms):8.2f} ms")
    print(f"  first hundred adds    {statistics.mean(adds_ms[:hundred]):8.2f} ms")
    print(f"  last hundred adds     {statistics.mean(adds_ms[-hundred:]):8.2f} ms")
    print(f"  folding the list      {finishing * 1000:8.0f} ms")
    print(f"  the map weighs        {map_bytes / 1024:8.0f} kB "
          f"({map_bytes // max(1, number)} bytes a position)")

    # -- what answering for it costs the server -------------------------------
    print("opening the view the way the server does ...")
    tracemalloc.start()
    started = time.perf_counter()
    first_down, first_across = next(iter(numbered))
    held = linking.the_bytes_behind(
        built.path,
        f"0/0/0/0/{first_down * (TILE[1] // PIECE)}"
        f"/{first_across * (TILE[2] // PIECE)}")
    cold = (time.perf_counter() - started) * 1000
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert held is not None, "a piece of the first imaged tile should be a pointer"
    print(f"  first ask (parses and indexes the whole map) {cold:6.1f} ms")
    print(f"  memory while doing so                        {peak / 1e6:6.1f} MB")

    rows = room[1] // PIECE
    columns = room[2] // PIECE
    rng = np.random.default_rng(7)
    asks = []
    for _ in range(20_000):
        level = int(rng.integers(0, LEVELS))
        factor = 2 ** level
        down = int(rng.integers(0, max(1, rows // factor)))
        across = int(rng.integers(0, max(1, columns // factor)))
        asks.append((f"{level}/0/0/0/{down}/{across}", level, down, across))
    started = time.perf_counter()
    answered = [linking.the_bytes_behind(built.path, ask) for ask, *_ in asks]
    each_us = (time.perf_counter() - started) / len(asks) * 1e6
    supplied = sum(1 for one in answered if one is not None)
    print(f"  one lookup, averaged over {len(asks)}          "
          f"{each_us:6.1f} us")
    print(f"  answered with a file  {supplied}, "
          f"with 'nothing here' {len(asks) - supplied}")

    # -- is the answer right? -------------------------------------------------
    print("following a sample of pointers to the voxels behind them ...")
    pieces_per_tile = TILE[1] // PIECE  # per axis, at full size
    checked = wrong = holes_right = 0
    for ask, level, down, across in asks[:2000]:
        factor = 2 ** level
        tile_down = down * factor // pieces_per_tile
        tile_across = across * factor // pieces_per_tile
        found = linking.the_bytes_behind(built.path, ask)
        if not _imaged(tile_down, tile_across):
            assert found is None, (
                f"{ask} is ground nobody imaged and should have no pointer")
            holes_right += 1
            continue
        assert found is not None, f"{ask} should be supplied by a tile"
        named = found.path.split("/")
        tile = zarr.open_group(str(work / named[0] / named[1]), mode="r")
        piece = np.asarray(tile[named[2]])[0, 0]
        if not np.all(piece == numbered[(tile_down, tile_across)]):
            wrong += 1
        checked += 1
    print(f"  pieces followed and decoded  {checked}, wrong {wrong}")
    print(f"  holes answered 'nothing here' {holes_right}")
    assert wrong == 0, "a pointer resolved to the wrong tile"

    # -- what this means for a browser ----------------------------------------
    screen, written_piece = 2048, 256
    print("what a browser would ask for, from the arithmetic this settles:")
    print(f"  a {screen} px screenful is (screen / piece)^2 pieces whatever the "
          "tile count —")
    print(f"  {(screen // written_piece) ** 2} pieces of "
          f"{written_piece} (what the project writes), "
          f"{(screen // PIECE) ** 2} of the {PIECE} used here to keep "
          "ten thousand tiles small")
    print(f"  the same specimen as {number} separate sources, measured "
          f"before: about {round(number * 5.2)} requests to open")


if __name__ == "__main__":
    main()
