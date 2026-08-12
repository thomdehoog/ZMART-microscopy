"""Write down what a built picture is, so the viewer can open it like any other.

A built picture holds no pixels anywhere — every piece of it is made when asked
for. But a viewer asks what an image *is* long before it asks for any of it: the
axes, the size, how large a voxel is, where it sits on the stage, what copies it
keeps. That much has to exist on disk, because it is read as ordinary files.

So this writes a folder that looks exactly like an OME-Zarr image and contains no
image: a description for the picture and one for each of its resolutions, and
nothing else. A few kilobytes. :mod:`served` supplies the pieces when they are
asked for.

This mirrors what :mod:`zmart_storage.linked` writes for a pointed-at view, and
for the same reason — an image nobody can describe is an image nobody can open.
The difference is only where the pieces come from afterwards.

**Where the transfer is recorded.** Under one word of ours inside the picture's own
description, which is where OME-Zarr says a writer may keep whatever else it needs.
That way the built folder is self-contained: it says which transfer it was built
from, so it can be opened again tomorrow without being told.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import zarr
from composer import PIECE, Composer
from mosaic import read_the_transfer, the_mosaic_written_down

# The key inside the picture's description under which we record what it was built
# from. Namespaced under one word of ours, the same courtesy OME-Zarr 0.5 pays by
# keeping its own fields under ``ome``.
OURS = "zmart"


def declare_a_built_picture(where: str | Path, transfer: str | Path, *,
                            name: str = "built", piece: int = PIECE,
                            bake: bool = False, workers: int = 1) -> Path:
    """Write the description of a picture built from a transfer.

    Args:
        where: the folder to put it in. The viewer is opened on this folder.
        transfer: the container holding one OME-Zarr per tile.
        name: what to call the picture. The operator sees it as the heading in
            the viewer's panel.
        piece: how large a piece of the built picture is, across height and width.
        bake: also build the coarse ground now, once, and keep it as real
            files -- the pinned levels from the tiles, and the picture's own
            levels above them, halving y and x until the whole picture fits
            one piece. The cold start then reads files instead of touching
            every tile in front of whoever looks first. A switch, so a baked
            and an unbaked declaration can be compared side by side.
        workers: how many processes build while baking. One builds in place.

    Returns:
        The picture's own folder, which is what the viewer opens.
    """
    where, transfer = Path(where), Path(transfer).resolve()
    mosaic = read_the_transfer(transfer)
    composer = Composer(mosaic, piece=piece, workers=workers)

    store = where / f"{name}.ome.zarr"
    store.mkdir(parents=True, exist_ok=True)

    # Declaring says everything the picture is, so anything baked by an earlier
    # declaration goes first -- otherwise declaring without the bake would
    # leave yesterday's baked ground quietly being served, and the switch
    # would only ever turn on.
    for kept in sorted(store.glob("[0-9]*")):
        if kept.is_dir() and (int(kept.name) >= mosaic.levels
                              or (kept / "c").exists()):
            shutil.rmtree(kept)

    for level in range(mosaic.levels):
        inside = store / str(level)
        inside.mkdir(exist_ok=True)
        (inside / "zarr.json").write_text(
            json.dumps(json.loads(composer.array_json(level)), indent=1),
            encoding="utf-8")

    described = json.loads(composer.group_json())
    baked: list[int] = []
    if bake:
        try:
            baked = _bake_the_coarse_ground(store, composer, described)
        finally:
            composer.close()

    described["attributes"][OURS] = {
        "what": (
            "A picture that holds no pixels beyond its baked coarse ground. "
            "Every other piece of it is built when it is asked for, out of the "
            "tiles of the transfer named below, which are read and never "
            "changed."
        ),
        "built_from": transfer.as_posix(),
        "piece": composer.piece,
        "tiles": len(mosaic.tiles),
        "baked": baked,
    }
    (store / "zarr.json").write_text(json.dumps(described, indent=1),
                                     encoding="utf-8")

    # The tiles' whole geometry, written down so opening never walks the
    # transfer again. Declaring read every tile just above; keeping what was
    # learned is what makes opening immediate at any position count.
    (store / "tiles.json").write_text(
        json.dumps(the_mosaic_written_down(mosaic)), encoding="utf-8")

    return store


def declare_a_governed_picture(where: str | Path, run: str | Path, *,
                               name: str = "live", piece: int = PIECE) -> Path:
    """Write the description of a picture built from a manifest-governed run.

    The counterpart of :func:`declare_a_built_picture` for a live run: the
    description is written once, from the run's **layout** — so the declared
    shape is complete before the first position lands and never moves — and
    every piece is built at request time by :mod:`governed`, which consults
    the manifest per request. Nothing here is ever rewritten as the run grows:
    the frame was never derived from what has arrived.

    No bake, deliberately: baked ground is real files, and a live run's ground
    changes under them. Patching the bake per commit is planned work
    (PLAN_responsiveness.md); until it exists a governed picture is served
    warm from the composer's inherited caches instead.

    The picture serves the run's first channel and first moment. A run that
    records several channels is refused here, loudly, rather than shown with
    its colours silently collapsed; growing the served axes is the named next
    step of the gate work.

    Args:
        where: the folder to put the description in.
        run: the governed run's root — the folder holding ``positions/``,
            ``views/`` and the manifest's bookkeeping.
        name: what to call the picture.
        piece: how large a piece of the built picture is.

    Returns:
        The picture's own folder, which is what the viewer opens.
    """
    from governed import GovernedRun

    where, run = Path(where), Path(run).resolve()
    governed = GovernedRun(run, piece=piece)
    composer = governed.composer()
    channels = composer.mosaic.channels_recorded
    if len(channels) > 1:
        raise ValueError(
            f"the run at {run} records {len(channels)} channels "
            f"({', '.join(channels)}), and this picture can serve exactly one "
            "— declaring it would silently collapse the colours into "
            "whichever came first. Growing the served channel axis is the "
            "gate work's next step; until then, a multi-colour run is shown "
            "by pointing."
        )

    store = where / f"{name}.ome.zarr"
    store.mkdir(parents=True, exist_ok=True)
    for level in range(composer.mosaic.levels):
        inside = store / str(level)
        inside.mkdir(exist_ok=True)
        (inside / "zarr.json").write_text(
            json.dumps(json.loads(composer.array_json(level)), indent=1),
            encoding="utf-8")

    described = json.loads(composer.group_json())
    described["attributes"][OURS] = {
        "what": (
            "A picture of a live, manifest-governed run. It holds no pixels; "
            "every piece is built when asked for, from the positions the "
            "run's manifest has published as of that request, and nothing "
            "else."
        ),
        "governed_from": run.as_posix(),
        "piece": composer.piece,
    }
    (store / "zarr.json").write_text(json.dumps(described, indent=1),
                                     encoding="utf-8")
    return store


def _bake_the_coarse_ground(store: Path, composer: Composer,
                            described: dict) -> list[int]:
    """Build the coarse ground once, into real files, and extend the pyramid.

    Two kinds of level come out of this. The composer's pinned levels are
    built from the tiles -- the one-visit-per-tile floor, paid here instead of
    at every cold open. Above them, the picture's own levels are averaged from
    the level below, two by two in y and x, until one piece holds the whole
    picture: the tiles cannot provide those (a camera frame's coarsest copy is
    already a few dozen pixels), but a survey is looked at from further back
    the larger it grows, so the picture must keep halving where its tiles
    stop. No tile is touched a second time for them.

    The baked levels are ordinary zarr arrays -- same piece size, same
    encoding the composer declares -- so serving them is serving files, immune
    to everything that makes building slow. A piece holding only fill value is
    left unwritten, which is the same absent-means-fill answer the composer
    gives for such ground.
    """
    coarsest = composer.mosaic.levels - 1
    pinned = sorted(composer.pinned_levels)
    datasets = described["attributes"]["ome"]["multiscales"][0]["datasets"]

    for level in pinned:
        deep, down, across = composer.grid(level)
        for plane in range(deep):
            for row in range(down):
                inside = store / str(level) / "c" / str(plane) / str(row)
                for column in range(across):
                    # The very bytes the composer would put on the wire, kept
                    # as the chunk file the engine would ask for -- so a baked
                    # answer and a built one cannot differ. Empty ground stays
                    # unwritten: absent means fill, here as everywhere.
                    body = composer.bytes_for(level, plane, row, column)
                    if body is None:
                        continue
                    inside.mkdir(parents=True, exist_ok=True)
                    (inside / str(column)).write_bytes(body)

    # The picture's own levels, chained upward from what was just baked.
    depth, height, width = composer.mosaic.shape(coarsest)
    whole = np.asarray(zarr.open_array(str(store / str(coarsest)), mode="r"))
    voxel = list(composer.mosaic.voxel_um(coarsest))
    level = coarsest
    while height > composer.piece or width > composer.piece:
        level += 1
        height, width = -(-height // 2), -(-width // 2)
        voxel = [voxel[0], voxel[1] * 2, voxel[2] * 2]
        evened = np.pad(whole, ((0, 0), (0, height * 2 - whole.shape[1]),
                                (0, width * 2 - whole.shape[2])), mode="edge")
        whole = (evened.reshape(depth, height, 2, width, 2)
                 .mean(axis=(2, 4)).round()
                 .astype(composer.mosaic.dtype))
        made = zarr.create_array(
            store=str(store / str(level)), shape=(depth, height, width),
            chunks=(1, composer.piece, composer.piece),
            dtype=composer.mosaic.dtype, zarr_format=3,
            dimension_names=list(composer.mosaic.axes), overwrite=True,
        )
        made[:] = whole
        datasets.append({
            "path": str(level),
            "coordinateTransformations": [
                {"type": "scale", "scale": list(voxel)},
                {"type": "translation",
                 "translation": list(composer.mosaic.corner_um)},
            ],
        })

    return pinned + list(range(coarsest + 1, level + 1))


def main() -> None:
    import argparse

    parsed = argparse.ArgumentParser(description=__doc__)
    parsed.add_argument("transfer", type=Path)
    parsed.add_argument("where", type=Path)
    parsed.add_argument("--name", default="built")
    parsed.add_argument("--piece", type=int, default=PIECE)
    parsed.add_argument("--bake", action="store_true",
                        help="also build the coarse ground now, once, into "
                        "real files, so opening never builds it again. "
                        "Declaring without this removes any earlier bake.")
    parsed.add_argument("--workers", type=int, default=1,
                        help="how many processes build while baking; "
                        "one builds in place")
    given = parsed.parse_args()

    store = declare_a_built_picture(given.where, given.transfer,
                                    name=given.name, piece=given.piece,
                                    bake=given.bake, workers=given.workers)
    print(f"\n  declared {store}")
    print("  it holds no pixels; open the folder above it in the viewer.\n")


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    main()
