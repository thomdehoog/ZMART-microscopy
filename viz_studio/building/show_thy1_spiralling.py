"""One real block of specimen, laid out in a spiral, appearing while you watch.

This is a demonstration rather than a measurement, and it exists to answer a
question somebody asked at the microscope: can we see what a growing survey
looks like using *real* image data, without waiting for a microscope and
without copying tens of gigabytes around?

The answer is yes, and the trick is the one ``measure_a_transfer_repeated.py``
already uses. A position on disk is a small ``zarr.json`` saying where that
position sits, and beside it a folder of pixels for each zoom level. Only the
first of those is per-position; the pixels can be shared. So every block in
this spiral gets its own tiny description with its own place on the stage, and
its zoom-level folders are **junctions** — Windows' way of making one folder
appear in a second place — back to a single real tile of the Thy1 acquisition.
A spiral of fifty blocks therefore costs about seventy kilobytes, while looking
to anything that reads it like fifty full blocks of specimen.

Because the junctions carry every zoom level and every plane the microscope
wrote, this is real data in the full sense: you can zoom in until you see
individual cells, and switch between the flat view and the three-dimensional
one, exactly as you could on the original acquisition.

It will of course look like the same piece of brain over and over, because it
is. The point is not the specimen; it is watching a survey grow, and seeing
what real blocks — which are large, and slow to decode, quite unlike the
synthetic tiles the scaling tests use — feel like while it happens.

Run it in three steps, because the viewer has to be looking at the folder
before the blocks start arriving::

    python show_thy1_spiralling.py --prepare --out D:/zmart-thy1-spiral
    python ../run_demo.py --data D:/zmart-thy1-spiral --port 8848
    python show_thy1_spiralling.py --drip --out D:/zmart-thy1-spiral

``--prepare`` makes the folder and puts the middle block in it, so the viewer
has something to open. ``--drip`` adds the rest, one per second, telling the
viewer each time. The viewer also watches the folder by itself, so the telling
is a courtesy rather than a requirement.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

# The acquisition to borrow a block from, and which of its six tiles to use.
# Any one tile is a complete little volume with its own pyramid, which is
# exactly what a "position" is here.
THY1 = Path(r"D:\OMEzarr data\Thy1-25x-3x2-1ch-OMEZARR\Thy1_Mag25x_Ch561.ome.zarr")
TILE = "Mag25_Tile0_Ch561_Flt405-488-561-640-Quadrupleblock_Sh0_Rot359.028.ome.zarr"


def _junction(link: Path, target: Path) -> None:
    """Make one folder appear in a second place, without copying it.

    A junction is Windows' own way of doing this, and it is used here rather
    than a symbolic link because Windows grants junctions to an ordinary user
    while symbolic links need a privilege this machine does not have.
    """
    done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                          capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError(f"could not link {link} -> {target}: "
                           f"{done.stdout} {done.stderr}")


def _the_tile_we_borrow() -> tuple[Path, dict, list[str], tuple[float, float]]:
    """Read the real tile once: its description, its levels, and its size.

    Returns the tile's folder, the description we will copy for each block, the
    names of its zoom-level folders, and how far apart two blocks must sit —
    in real distance — for them to touch exactly rather than overlap or leave a
    gap between them.
    """
    tile = THY1 / TILE
    described = json.loads((tile / "zarr.json").read_text(encoding="utf-8"))
    multiscales = described["attributes"]["ome"]["multiscales"][0]
    levels = [dataset["path"] for dataset in multiscales["datasets"]]

    finest = json.loads((tile / levels[0] / "zarr.json").read_text(encoding="utf-8"))
    _, height, width = finest["shape"]
    scale = next(one["scale"] for one in multiscales["datasets"][0]
                 ["coordinateTransformations"] if one["type"] == "scale")
    # How wide and how tall the block is in micrometres: the number of pixels
    # multiplied by what one pixel measures.
    return tile, described, levels, (height * scale[1], width * scale[2])


def _spiral(across: int) -> list[tuple[int, int]]:
    """The cells of an ``across`` by ``across`` grid, from the middle outwards.

    A microscope drives its stage from somewhere and works outwards; laying the
    blocks down in that order makes the growth read as a journey rather than as
    a scatter, and every new block touches one that is already there.
    """
    middle = (across - 1) // 2
    cells = [(middle, middle)]
    row, column, step = middle, middle, 1
    while len(cells) < across * across:
        for _ in range(step):
            column += 1
            if 0 <= row < across and 0 <= column < across:
                cells.append((row, column))
        for _ in range(step):
            row += 1
            if 0 <= row < across and 0 <= column < across:
                cells.append((row, column))
        step += 1
        for _ in range(step):
            column -= 1
            if 0 <= row < across and 0 <= column < across:
                cells.append((row, column))
        for _ in range(step):
            row -= 1
            if 0 <= row < across and 0 <= column < across:
                cells.append((row, column))
        step += 1
    return cells[:across * across]


def _place_a_block(out: Path, number: int, row: int, column: int,
                   described: dict, levels: list[str], tile: Path,
                   apart: tuple[float, float]) -> Path:
    """Write one block: its own description, and junctions to the shared pixels."""
    store = out / f"Spiral{number:03d}_r{row}c{column}.ome.zarr"
    store.mkdir(parents=True)

    # The description is the real tile's, with the block slid into its place on
    # the grid. Every zoom level carries the same slide, because they are all
    # descriptions of the same piece of specimen at different coarsenesses.
    moved = json.loads(json.dumps(described))
    tall, wide = apart
    for dataset in moved["attributes"]["ome"]["multiscales"][0]["datasets"]:
        for transformation in dataset["coordinateTransformations"]:
            if transformation["type"] == "translation":
                depth, down, across_ = transformation["translation"]
                transformation["translation"] = [depth,
                                                 down + row * tall,
                                                 across_ + column * wide]
    (store / "zarr.json").write_text(json.dumps(moved, indent=2), encoding="utf-8")

    for level in levels:
        _junction(store / level, tile / level)
    return store


def _tell_the_viewer(port: int) -> int:
    """Say that something new has arrived. Nought heard is not an error."""
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/announce",
            data=json.dumps({}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=5) as answer:
            return json.load(answer).get("told", 0)
    except (urllib.error.URLError, OSError, ValueError):
        return 0


def _put_it_on_screen(port: int, store: Path) -> str:
    """Ask the viewer to read the spiral's FOLDER again, now one more block is in it.

    Announcing is not enough for a block that was not there when the viewer
    started: an announcement means "look again at what you already have", and
    the viewer was never told about this one. This is the route a run uses to
    put something new on screen, and it is deliberately open so that what is
    shown is decided by the experiment rather than by whoever is watching.

    The **folder** is named here rather than the block, and that is the whole
    difference between a picture and a heap. A folder is one acquisition, and
    the stores inside it are pieces of one specimen laid out in one shared set
    of coordinates, so each block appears in its own place. Naming a block on
    its own makes it an acquisition in its own right, with a coordinate frame
    of its own -- and forty-nine of those land on top of one another, which is
    exactly what was seen the first time this was tried.
    """
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/stores/open",
            data=json.dumps({"path": str(store)}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=20) as answer:
            given = json.load(answer)
            if "error" in given:
                return f"refused: {given['error'][:60]}"
            return "opened"
    except urllib.error.HTTPError as refused:
        return f"HTTP {refused.code}"
    except (urllib.error.URLError, OSError, ValueError) as wrong:
        return f"could not ask: {wrong}"


def main() -> int:
    parsing = argparse.ArgumentParser(description=__doc__)
    parsing.add_argument("--out", required=True,
                         help="the folder the viewer will be opened on")
    parsing.add_argument("--across", type=int, default=7,
                         help="blocks across and down; 7 gives forty-nine")
    parsing.add_argument("--every", type=float, default=1.0,
                         help="seconds between blocks appearing")
    parsing.add_argument("--port", type=int, default=8848,
                         help="the port the viewer answers on")
    parsing.add_argument("--prepare", action="store_true",
                         help="make the folder and place the middle block")
    parsing.add_argument("--drip", action="store_true",
                         help="add the remaining blocks, one at a time")
    asked = parsing.parse_args()

    out = Path(asked.out)
    tile, described, levels, apart = _the_tile_we_borrow()
    cells = _spiral(asked.across)

    if asked.prepare:
        if out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True)
        row, column = cells[0]
        _place_a_block(out, 0, row, column, described, levels, tile, apart)
        print(f"{out} is ready with its middle block "
              f"({tile.name} shared, nothing copied).")
        print(f"Open it with:  python ../run_demo.py --data {out} "
              f"--port {asked.port}")
        print(f"Then add the rest with:  python show_thy1_spiralling.py "
              f"--drip --out {out}")
        return 0

    if asked.drip:
        began = time.time()
        for number, (row, column) in enumerate(cells[1:], start=1):
            _place_a_block(out, number, row, column, described, levels,
                           tile, apart)
            said = _put_it_on_screen(asked.port, out)
            _tell_the_viewer(asked.port)
            print(f"  block {number + 1}/{len(cells)} at row {row} column "
                  f"{column}  ({said})", flush=True)
            time.sleep(asked.every)
        size = sum(one.stat().st_size for one in out.rglob("*") if one.is_file()
                   and not one.is_symlink())
        print(f"\n{len(cells)} blocks in {time.time() - began:.0f} s. "
              f"The folder's own files come to {size / 1024:.0f} KB; the "
              f"specimen behind them is untouched.")
        return 0

    parsing.error("say --prepare or --drip")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
