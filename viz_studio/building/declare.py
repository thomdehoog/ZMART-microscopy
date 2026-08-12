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
from pathlib import Path

from composer import PIECE, Composer
from mosaic import read_the_transfer, the_mosaic_written_down

# The key inside the picture's description under which we record what it was built
# from. Namespaced under one word of ours, the same courtesy OME-Zarr 0.5 pays by
# keeping its own fields under ``ome``.
OURS = "zmart"


def declare_a_built_picture(where: str | Path, transfer: str | Path, *,
                            name: str = "built", piece: int = PIECE) -> Path:
    """Write the description of a picture built from a transfer.

    Args:
        where: the folder to put it in. The viewer is opened on this folder.
        transfer: the container holding one OME-Zarr per tile.
        name: what to call the picture. The operator sees it as the heading in
            the viewer's panel.
        piece: how large a piece of the built picture is, across height and width.

    Returns:
        The picture's own folder, which is what the viewer opens.
    """
    where, transfer = Path(where), Path(transfer).resolve()
    mosaic = read_the_transfer(transfer)
    composer = Composer(mosaic, piece=piece)

    store = where / f"{name}.ome.zarr"
    store.mkdir(parents=True, exist_ok=True)

    described = json.loads(composer.group_json())
    described["attributes"][OURS] = {
        "what": (
            "A picture that holds no pixels. Every piece of it is built when it is "
            "asked for, out of the tiles of the transfer named below, which are "
            "read and never changed."
        ),
        "built_from": transfer.as_posix(),
        "piece": composer.piece,
        "tiles": len(mosaic.tiles),
    }
    (store / "zarr.json").write_text(json.dumps(described, indent=1),
                                     encoding="utf-8")

    for level in range(mosaic.levels):
        inside = store / str(level)
        inside.mkdir(exist_ok=True)
        (inside / "zarr.json").write_text(
            json.dumps(json.loads(composer.array_json(level)), indent=1),
            encoding="utf-8")

    # The tiles' whole geometry, written down so opening never walks the
    # transfer again. Declaring read every tile just above; keeping what was
    # learned is what makes opening immediate at any position count.
    (store / "tiles.json").write_text(
        json.dumps(the_mosaic_written_down(mosaic)), encoding="utf-8")

    return store


def main() -> None:
    import argparse

    parsed = argparse.ArgumentParser(description=__doc__)
    parsed.add_argument("transfer", type=Path)
    parsed.add_argument("where", type=Path)
    parsed.add_argument("--name", default="built")
    parsed.add_argument("--piece", type=int, default=PIECE)
    given = parsed.parse_args()

    store = declare_a_built_picture(given.where, given.transfer,
                                    name=given.name, piece=given.piece)
    print(f"\n  declared {store}")
    print("  it holds no pixels; open the folder above it in the viewer.\n")


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    main()
