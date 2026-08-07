"""What does a real acquisition actually leave on disk, and can it be pointed at?

Why this exists
---------------

The viewer can show a folder of tiles as one picture in two quite different ways,
and which of them is possible depends entirely on how the tiles were written.

The cheap way is to **hand over a tile's own file untouched**. That works only when
a piece of the picture the viewer asks for happens to be exactly a piece of one
tile, byte for byte — which needs the tiles' grid of pieces to line up with the
picture's, and needs every tile stored the same way as every other. When it works it
costs nothing at all: no pixels are read, decoded or copied.

The general way is to **assemble the piece** out of whichever tiles overlap it,
which always works and costs real effort on every request.

For a run this project writes itself, the cheap way can be arranged. For a transfer
from another microscope — a mesoSPIM, say — nobody arranged anything, and the only
honest way to find out how often the cheap way is available is to look.

This script looks. Point it at a folder of ``.ome.zarr`` stores and it reports what
they are, how they are stored, where they sit, and — the number that matters — what
fraction of the picture could be served by handing a file over rather than by
assembling it.

Running it
----------

::

    python viz_studio/measure_what_a_transfer_looks_like.py /path/to/transfer

Nothing is written and nothing is changed. It only reads descriptions, not pixels,
so it is quick even on a very large run.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path


def _described(store: Path) -> tuple[dict, str] | None:
    """What a store says about itself, and which generation of OME-Zarr wrote it."""
    newer = store / "zarr.json"
    if newer.is_file():
        held = json.loads(newer.read_text(encoding="utf-8"))
        attributes = held.get("attributes") or {}
        return (attributes.get("ome") or attributes), "0.5"
    older = store / ".zattrs"
    if older.is_file():
        return json.loads(older.read_text(encoding="utf-8")), "0.4"
    return None


def _array_description(level: Path) -> dict | None:
    for name in ("zarr.json", ".zarray"):
        held = level / name
        if held.is_file():
            return json.loads(held.read_text(encoding="utf-8"))
    return None


def _chunk_of(described: dict) -> tuple[int, ...]:
    if described.get("zarr_format") == 2:
        return tuple(int(n) for n in described["chunks"])
    grid = (described.get("chunk_grid") or {}).get("configuration") or {}
    return tuple(int(n) for n in grid["chunk_shape"])


def _is_sharded(described: dict) -> bool:
    """Whether pieces are packed into larger files rather than being files.

    A shard holds many pieces inside one file. That is often a good idea — it keeps
    the number of files down — but it means a piece is no longer something that can
    be handed over on its own, so it rules the cheap way out.
    """
    for codec in described.get("codecs") or []:
        if "sharding" in str(codec.get("name", "")).lower():
            return True
    return False


def _where_and_how_large(attributes: dict) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Where this store's full-size picture sits, and how large one of its voxels is.

    Only the **first** copy of the picture is asked, because that is the full-size
    one and the only one a piece can be handed over from. An image also carries its
    smaller copies here, each with a coarser voxel and its own position; reading all
    of them together would add up positions that were never meant to be added and
    report a voxel several times too large.

    A position may be written twice over: once for the image as a whole and once
    beside the copy. Both are collected, because a reader is meant to compose them.
    """
    multiscale = (attributes.get("multiscales") or [{}])[0]
    at = [0.0] * 5
    size = [1.0] * 5

    def apply(transforms) -> None:
        for transform in transforms or []:
            if transform.get("type") == "translation":
                moved = [float(n) for n in transform["translation"]]
                for axis in range(len(moved)):
                    at[-len(moved) + axis] += moved[axis]
            if transform.get("type") == "scale":
                scaled = [float(n) for n in transform["scale"]]
                for axis in range(len(scaled)):
                    size[-len(scaled) + axis] = scaled[axis]

    apply(multiscale.get("coordinateTransformations"))
    datasets = multiscale.get("datasets") or []
    if datasets:
        apply(datasets[0].get("coordinateTransformations"))
    return tuple(at[-3:]), tuple(size[-3:])


def _first_level(store: Path, attributes: dict) -> Path | None:
    multiscale = (attributes.get("multiscales") or [{}])[0]
    datasets = multiscale.get("datasets") or []
    if not datasets:
        return None
    return store / str(datasets[0]["path"])


def look_at(folder: Path) -> int:
    stores = sorted(
        child for child in folder.iterdir()
        if child.is_dir() and child.name.endswith(".zarr")
    )
    if not stores and _described(folder) is not None:
        stores = [folder]
    if not stores:
        print(f"No .ome.zarr stores found in {folder}.")
        return 1

    print(f"Looking at {len(stores)} stores in {folder}\n")

    ways_stored: Counter = Counter()
    chunks: Counter = Counter()
    sharded = 0
    placements: list[tuple[str, tuple[float, ...], tuple[float, ...], tuple[int, ...]]] = []
    unreadable: list[str] = []

    for store in stores:
        read = _described(store)
        if read is None:
            unreadable.append(store.name)
            continue
        attributes, version = read
        level = _first_level(store, attributes)
        described = _array_description(level) if level is not None else None
        if described is None:
            unreadable.append(store.name)
            continue

        chunk = _chunk_of(described)
        chunks[chunk[-2:]] += 1
        if _is_sharded(described):
            sharded += 1
        ways_stored[json.dumps({
            "ome": version,
            "dtype": str(described.get("dtype") or described.get("data_type")),
            "chunk": list(chunk),
            "compressor": json.dumps(
                described.get("compressor") or described.get("codecs"), sort_keys=True
            ),
            "fill": described.get("fill_value"),
        }, sort_keys=True)] += 1

        at, voxel = _where_and_how_large(attributes)
        shape = tuple(int(n) for n in described["shape"])
        placements.append((store.name, at, voxel, shape))

    # -- how they are stored ---------------------------------------------------
    print("How they are stored")
    print("-" * 70)
    if unreadable:
        print(f"  {len(unreadable)} store(s) could not be read: "
              f"{', '.join(unreadable[:3])}{' ...' if len(unreadable) > 3 else ''}")
    print(f"  pieces across y and x: "
          f"{', '.join(f'{c} in {n} stores' for c, n in chunks.most_common())}")
    print(f"  sharded (pieces packed into larger files): {sharded} of {len(stores)}")
    if len(ways_stored) == 1:
        print("  every store is written the same way, so they could be one picture")
    else:
        print(f"  *** {len(ways_stored)} DIFFERENT ways of storing a picture here.")
        print("      Handing bytes over untouched needs one description true of all of")
        print("      them, so a run mixing these cannot be pointed at as it stands.")

    # -- where they sit --------------------------------------------------------
    if not placements:
        return 1
    print("\nWhere they sit, and whether their pieces line up")
    print("-" * 70)
    voxel = placements[0][2]
    corner = tuple(min(one[1][axis] for one in placements) for axis in range(3))
    piece = chunks.most_common(1)[0][0]

    aligned = 0
    phases: Counter = Counter()
    for name, at, its_voxel, shape in placements:
        if its_voxel != voxel:
            continue
        # Where this tile begins, counted in voxels from the run's own corner.
        begins = tuple(
            int(round((at[axis] - corner[axis]) / its_voxel[axis]))
            if its_voxel[axis] else 0
            for axis in range(3)
        )
        phase = (begins[1] % piece[0], begins[2] % piece[1])
        phases[phase] += 1
        if phase == (0, 0):
            aligned += 1

    print(f"  a piece is {piece[0]} x {piece[1]} voxels (y by x)")
    print(f"  tiles beginning exactly on a piece boundary: {aligned} of "
          f"{len(placements)}")
    if aligned != len(placements):
        worst = max(
            max(p[0], p[1]) for p in phases
        )
        print(f"  the rest begin up to {worst} voxels past one, so no file of theirs")
        print("  holds the bytes a piece of the picture is asking for")

    # -- the number that decides the architecture ------------------------------
    print("\nWhat this means for the viewer")
    print("-" * 70)
    share = aligned / len(placements) if placements else 0.0
    print(f"  about {share:.0%} of these tiles could be served by handing over a file")
    print(f"  untouched; the other {1 - share:.0%} would have to be assembled from")
    print("  whichever pieces overlap them.")
    if sharded:
        print("  Sharding rules out handing files over for those stores whatever their")
        print("  placement, because a piece is not a file there.")
    if share < 0.99:
        print("\n  So a viewer that has to open this transfer needs the assembling")
        print("  path. Pointing at files can only ever be an optimisation on top of")
        print("  it, taken when a piece happens to line up.")
    else:
        print("\n  So this transfer could be pointed at wholesale, with no pixels")
        print("  copied and no assembling path needed.")
    return 0


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        print("Give one argument: the folder holding the .ome.zarr stores.")
        return 2
    folder = Path(sys.argv[1]).expanduser()
    if not folder.is_dir():
        print(f"{folder} is not a folder.")
        return 2
    return look_at(folder)


if __name__ == "__main__":
    raise SystemExit(main())
