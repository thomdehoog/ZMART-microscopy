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
import os
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from multiprocessing import get_context
from pathlib import Path

import numpy as np
import zarr
from composer import PIECE, Composer
from mosaic import read_the_transfer, the_mosaic_written_down

# The key inside the picture's description under which we record what it was built
# from. Namespaced under one word of ours, the same courtesy OME-Zarr 0.5 pays by
# keeping its own fields under ``ome``.
OURS = "zmart"

# How many worker processes a governed bake fans out over. Processes rather
# than threads, after measurement: every zarr read and piece encode funnels
# through zarr's one per-process event loop, so threads queued there and a
# four-thread bake was measured SLOWER than the serial loop (16 s to 27 s at
# 1,024 positions). Separate processes each bring their own interpreter and
# their own loop. One means the plain serial loop.
_BAKE_PROCESSES = min(4, os.cpu_count() or 1)

# The governed run a bake worker process serves, built once when the worker
# starts -- the same shape composer.py gives its transfer workers. Module
# level, because a process pool initializer has nowhere else to put it.
_BAKING: tuple | None = None


def _start_baking(run: Path, piece: int) -> None:
    """Give this bake worker its own reading of the governed run.

    The worker opens the run exactly the way a server would — through
    :class:`governed.GovernedRun`, so the full fail-closed gate rides along:
    committed ground whose chunks are missing is refused, never invented,
    in the worker just as in the parent. Its background warmer is stopped
    at once; a bake worker builds exactly the pieces it is told to.
    """
    global _BAKING
    here = Path(__file__).resolve().parent
    for one in (here, here.parent, here.parent.parent):
        if str(one) not in sys.path:
            sys.path.insert(0, str(one))
    from governed import GovernedRun

    governed = GovernedRun(run, piece=piece)
    composer = governed.composer()
    composer.stop_warming()
    _BAKING = (governed, composer)


def _bake_one_stripe(store: Path, level: int, rows: tuple[int, ...]) -> int:
    """One worker's share of a bake: whole rows of one level, written as files.

    Returns how many pieces it wrote. A commit that lands while workers are
    baking may leave some pieces holding slightly newer ground than the
    stamp the parent captured before the bake began — the benign direction:
    the stamp claims only the older prefix, so the first derive re-patches
    those commits' footprints and the files converge (the same catch-up
    that review finding D2 pinned for the serial bake).
    """
    assert _BAKING is not None, "a bake worker must be started before use"
    _, composer = _BAKING
    deep = composer.grid(level)[0]
    across = composer.grid(level)[2]
    written = 0
    for row in rows:
        for plane in range(deep):
            inside = store / str(level) / "c" / str(plane) / str(row)
            for column in range(across):
                body = composer.bytes_for(level, plane, row, column)
                if body is None:
                    continue
                inside.mkdir(parents=True, exist_ok=True)
                (inside / str(column)).write_bytes(body)
                written += 1
    return written


def declare_a_built_picture(where: str | Path, transfer: str | Path, *,
                            name: str = "built", piece: int = PIECE,
                            bake: bool = False, workers: int = 1,
                            told=None) -> Path:
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
        told: called as ``told(done, total)`` while baking, so whoever asked
            for the bake can draw a progress bar. The units are rows of
            pieces; only their ratio means anything.

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
        if mosaic.frame_room != (1, 1):
            raise ValueError(
                f"the picture at {transfer} keeps room for "
                f"{mosaic.frame_room[0]} moment(s) and {mosaic.frame_room[1]} "
                "channel(s), and the bake writes one file per flat piece — "
                "baking it would freeze one frame and serve it for every "
                "other. The per-(t, c) bake is ordered work; until it lands, "
                "declare a grown picture without the bake."
            )
        try:
            baked = _bake_the_coarse_ground(store, composer, described,
                                            told=told)
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
                               name: str = "live", piece: int = PIECE,
                               bake: bool = False) -> Path:
    """Write the description of a picture built from a manifest-governed run.

    The counterpart of :func:`declare_a_built_picture` for a live run: the
    description is written once, from the run's **layout** — so the declared
    shape is complete before the first position lands and never moves — and
    every piece is built at request time by :mod:`governed`, which consults
    the manifest per request. Nothing here is ever rewritten as the run grows:
    the frame was never derived from what has arrived.

    ``bake`` is the live counterpart of the transfer's switch, and the live
    run keeps BOTH modes deliberately. Baked ground is real files and a live
    run's ground changes under them, so a baked governed picture is only
    honest because :class:`governed.GovernedRun` patches the touched pieces
    inside every derive, before the fresh snapshot answers anyone — per
    commit, never rebuilt. What is baked here is the ground as of THIS
    moment (for a young run: nothing, since fill is expressed by absence);
    every later commit keeps it true. Declaring again without ``bake``
    removes the baked ground, exactly as it does for a transfer.

    A run that records several channels or several moments is declared as a
    picture GROWN along (t, c): five axes, one frame per chunk, every frame
    served from the record (see the combined-axes oracle in
    ``test_every_plane_serves_its_own_stamp``). The loud refusals that once
    stood here — no silent colour collapse, no first-moment-as-the-run —
    retired the day that oracle and the browser gate both stood; what they
    guarded is now guarded by the serving itself.

    Args:
        where: the folder to put the description in.
        run: the governed run's root — the folder holding ``data/`` (the
            collection of position images) and ``views/`` (the live view's
            store and its metadata).
        name: what to call the picture.
        piece: how large a piece of the built picture is.

    Returns:
        The picture's own folder, which is what the viewer opens.
    """
    from governed import GovernedRun

    where, run = Path(where), Path(run).resolve()
    governed = GovernedRun(run, piece=piece)
    try:
        composer = governed.composer()
        # The identity of the manifest prefix this snapshot folded, captured
        # NOW: the bake below writes this snapshot's ground and may take
        # minutes at scale, and a stamp read from the manifest afterwards
        # claimed every commit that landed in the window as absorbed --
        # never baked, never patched (review finding D2).
        folded = governed._run._folded
        tail = governed._run._last_folded_revision
        revision = governed._run._geometry()[0].revision
        if bake and composer.mosaic.frame_room != (1, 1):
            raise ValueError(
                f"the run at {run} keeps room for "
                f"{composer.mosaic.frame_room[0]} moment(s) and "
                f"{composer.mosaic.frame_room[1]} channel(s), and the bake "
                "writes one file per flat piece — baking it would freeze one "
                "frame and serve it for every other. The per-(t, c) bake is "
                "ordered work; until it lands, declare a grown run without "
                "the bake."
            )

        store = where / f"{name}.ome.zarr"
        store.mkdir(parents=True, exist_ok=True)
        for kept in sorted(store.glob("[0-9]*")):
            # An earlier declaration's baked ground goes first, or declaring
            # without the bake would leave yesterday's files quietly being
            # served -- the transfer's rule, for the same reason.
            if kept.is_dir() and (int(kept.name) >= composer.mosaic.levels
                                  or (kept / "c").exists()):
                shutil.rmtree(kept)
        for level in range(composer.mosaic.levels):
            inside = store / str(level)
            inside.mkdir(exist_ok=True)
            (inside / "zarr.json").write_text(
                json.dumps(json.loads(composer.array_json(level)), indent=1),
                encoding="utf-8")

        described = json.loads(composer.group_json())
        baked: list[int] = []
        if bake:
            from governed import _holding_the_bake_lock

            with _holding_the_bake_lock(store):
                baked = _bake_the_coarse_ground(store, composer, described,
                                                governed_run=run)
        described["attributes"][OURS] = {
            "what": (
                "A picture of a live, manifest-governed run. It holds no "
                "pixels beyond its baked coarse ground, kept true per "
                "commit; every other piece is built when asked for, from "
                "the positions the run's manifest has published as of that "
                "request, and nothing else."
            ),
            "governed_from": run.as_posix(),
            "piece": composer.piece,
            "baked": baked,
        }
        (store / "zarr.json").write_text(json.dumps(described, indent=1),
                                         encoding="utf-8")
        if bake:
            governed.stamp_the_bake(store, events=folded, tail=tail,
                                    layout=revision)
        return store
    finally:
        governed.close()


def _bake_the_coarse_ground(store: Path, composer: Composer,
                            described: dict, *,
                            governed_run: Path | None = None,
                            told=None) -> list[int]:
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

    built_by_workers = False
    if governed_run is not None and _BAKE_PROCESSES > 1:
        # A governed bake fans its rows out over worker processes, each with
        # its own reading of the run (see _start_baking). Started by spawn
        # rather than fork, deliberately: the parent's zarr has a live event
        # loop and held locks, which a forked child would inherit mid-state,
        # and spawn is also what the microscope's Windows machine does -- so
        # the one behaviour is the tested behaviour. The parent's own warmer
        # is stopped first; four processes building the picture do not need
        # a fifth building it again in the background.
        composer.stop_warming()
        try:
            working = ProcessPoolExecutor(
                max_workers=_BAKE_PROCESSES, mp_context=get_context("spawn"),
                initializer=_start_baking,
                initargs=(governed_run, composer.piece),
            )
            try:
                stripes = []
                for level in pinned:
                    down = composer.grid(level)[1]
                    for worker in range(min(_BAKE_PROCESSES, down)):
                        rows = tuple(range(worker, down, _BAKE_PROCESSES))
                        if rows:
                            stripes.append(working.submit(
                                _bake_one_stripe, store, level, rows))
                # Consumed in order; a stripe that cannot be built stops the
                # bake, exactly as the serial loop's first failure would.
                for stripe in stripes:
                    stripe.result()
            finally:
                working.shutdown(wait=True, cancel_futures=True)
            built_by_workers = True
        except BrokenProcessPool:
            # The workers died before doing anything -- almost always
            # because the calling script starts work at import time, and a
            # spawned worker re-imports the calling script. The bake matters
            # more than the speed-up, so it is redone serially, whole; a
            # piece written twice is written identically. The fix on the
            # caller's side is one line: put the script's work under
            # ``if __name__ == "__main__":``.
            print("The bake's worker processes could not start (usually: "
                  "the calling script runs its work at import time, and a "
                  "worker re-imports it -- guard the script with "
                  "'if __name__ == \"__main__\":'). Baking serially "
                  "instead, which is slower and otherwise identical.")
    if not built_by_workers:
        # One unit of progress per row of pieces, counted up front so the
        # ratio is honest from the first report.
        total = sum(composer.grid(level)[0] * composer.grid(level)[1]
                    for level in pinned)
        done = 0
        for level in pinned:
            deep, down, across = composer.grid(level)
            for plane in range(deep):
                for row in range(down):
                    done += 1
                    if told is not None:
                        told(done, total)
                    inside = store / str(level) / "c" / str(plane) / str(row)
                    for column in range(across):
                        # The very bytes the composer would put on the wire,
                        # kept as the chunk file the engine would ask for --
                        # so a baked answer and a built one cannot differ.
                        # Empty ground stays unwritten: absent means fill,
                        # here as everywhere.
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
