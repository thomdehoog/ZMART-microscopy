"""A deep picture's room is declared whole, before any position lands.

The frame a browser navigates must be complete from the first moment and
never move: a declared shape that grew with arrivals would re-anchor every
voxel coordinate mid-experiment, and the operator would watch the world
slide. So the declared description is the layout's and the profile's fact
alone — every plane of every planned position, arrived or not — and a
landing changes pixels, never geometry.

The gate is byte-level on purpose: declare the picture on an empty deep
run, photograph every description it wrote, land a position, declare
again, and demand the descriptions come back byte-identical. Anything
weaker (comparing parsed shapes) would let a re-declare quietly reorder
or reword the descriptions the browser has already cached.

The generous-ceiling half of the depth plan's rule — declared room BEYOND
what will be imaged, with un-imaged room free per landing — needs the
per-axis ceiling to exist in the profile first; its cost-parity rung
(declared ≫ imaged priced identical to declared = imaged) is ordered with
that construction and joins this file the day the ceiling ships.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_VIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_VIZ / "app" / "picture"))

from declare import declare_a_governed_picture  # noqa: E402

from zmart_live.model import GridCell  # noqa: E402
from zmart_live.profiles import plan_the_writing  # noqa: E402

DEPTH = 13  # ragged, per the depth test plan's fixture rule
FRAME = 384


def the_descriptions_of(store: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(store)): path.read_bytes()
        for path in sorted(store.rglob("zarr.json"))
    }


def test_declare_land_redeclare_leaves_every_description_byte_identical(tmp_path):
    from zmart_live.coordinator import LivePublisher

    profile, _ = plan_the_writing("overview", frame=FRAME, z_planes=DEPTH)
    run = LivePublisher(
        tmp_path / "experiment" / "acquisitions" / "deep",
        profile, run_id="deep-room",
        cells={GridCell(0, 0): "p00", GridCell(0, 1): "p01"},
    )

    # Declared on the EMPTY run: the room exists before any pixels do.
    store = declare_a_governed_picture(run.folder / "views" / "shown",
                                       run.folder, name="live", bake=False)
    before = the_descriptions_of(store)
    assert before, "the declaration wrote no descriptions at all"

    stack = np.full((DEPTH, FRAME, FRAME), 1200, "uint16")
    run.write_and_publish("p00", stack)

    again = declare_a_governed_picture(run.folder / "views" / "shown",
                                       run.folder, name="live", bake=False)
    assert again == store
    after = the_descriptions_of(store)
    assert after == before, (
        "re-declaring after a landing changed these descriptions: "
        + ", ".join(sorted(name for name in set(before) | set(after)
                           if before.get(name) != after.get(name)))
        + " -- the declared room moved under a browser that already read it"
    )
