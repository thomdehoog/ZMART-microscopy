"""Place a run's positions by editing their descriptions, and nothing else.

A position records where it was acquired, and the viewer draws it there. Writing a
*correction* beside that -- a translation in micrometres -- moves the tile without
touching a voxel, to any precision, and can be revised afterwards by editing a few
bytes of JSON. That is what a stitcher's measured offset wants to be, and it is
free of the grid of pieces that a pointed picture imposes: 51.2 voxels is an
ordinary offset here and cannot be expressed there at all.

**The stage position lives in the multiscale-level ``coordinateTransformations``,
and removing or replacing it strips every tile of where it belongs.** They then
collapse towards the origin and pile on top of one another, which draws as a
patchwork of blocks and reads convincingly as a rendering fault. It cost four wrong
diagnoses -- the transform slot, fractional voxels, overlapping tiles, and
progressive loading -- before the working and broken stores were compared field by
field and the deleted block was obvious. The correction belongs in the *dataset*
transforms, which compose with the stage position rather than replacing it.

Used as::

    python place_positions_by_transform.py <ladder>/n100 <where to write> [overlap]

``overlap`` is how much of a tile the neighbour should cover, in voxels of the
finest level, and defaults to a tenth of a tile. Negative spreads them apart.
Pixels are copied byte for byte and never altered.
"""

from __future__ import annotations

import json
import math
import shutil
import sys
from pathlib import Path

VOXEL_UM = 0.325
TILE = 512
NOMINAL_UM = TILE * VOXEL_UM       # 166.4: one tile across
DEFAULT_OVERLAP_VOXELS = TILE / 10  # 51.2 -- a tenth, and not a whole voxel


def place(store: Path, row: int, column: int, overlap_um: float) -> None:
    """Record a correction on this store, leaving its stage position alone.

    The offset is written into every resolution level. A translation is applied
    after the scale and is therefore already physical, so the same number is right
    for each of them.
    """
    described = store / "zarr.json"
    held = json.loads(described.read_text(encoding="utf-8"))
    multiscale = held["attributes"]["ome"]["multiscales"][0]
    names = [axis["name"] for axis in multiscale["axes"]]
    offset = {"y": -row * overlap_um, "x": -column * overlap_um}

    # multiscale["coordinateTransformations"] is where the position records the
    # stage position it was taken at. It is deliberately not touched. See the note
    # at the top of this file for what happens when it is.
    for dataset in multiscale["datasets"]:
        kept = [t for t in dataset["coordinateTransformations"]
                if t.get("type") != "translation"]
        kept.append({
            "type": "translation",
            "translation": [float(offset.get(name, 0.0)) for name in names],
        })
        dataset["coordinateTransformations"] = kept

    described.write_text(json.dumps(held, indent=1), encoding="utf-8")


def main() -> int:
    rung = Path(sys.argv[1])
    into = Path(sys.argv[2])
    overlap_voxels = float(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_OVERLAP_VOXELS
    overlap_um = overlap_voxels * VOXEL_UM

    positions = rung / "experiment.ome.zarr" / "positions"
    if not positions.exists():
        print(f"no positions at {positions}")
        return 1

    found = sorted(p for p in positions.iterdir() if p.name.endswith(".ome.zarr"))
    across = int(math.ceil(math.sqrt(len(found))))

    if into.exists():
        shutil.rmtree(into)
    into.mkdir(parents=True)

    for index, source in enumerate(found):
        target = into / f"overview_pos{index:05d}.ome.zarr"
        shutil.copytree(source, target)
        place(target, index // across, index % across, overlap_um)

    print(f"{len(found)} stores, {across} across, each corrected by "
          f"{overlap_um:.2f} um ({overlap_voxels:g} voxels) per step")
    print(f"written to {into}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
