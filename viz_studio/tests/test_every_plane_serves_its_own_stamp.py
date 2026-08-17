"""Every served plane shows its own plane's specimen — the z identity oracle.

Depth's quietest failure is not a crash but a substitution: a piece served
from the plane above, a slab built off by one, a coarse level that dropped
the last ragged plane. A screenshot census cannot see it (both sides of an
F5 lie identically), so identity gets its own record-level gate: every
plane of the fixture is stamped with its own index, and the served
composer is asked for every piece of every plane at every level and
compared against that stamp. Wrong-plane, off-by-one and dropped-tail all
decode to visibly wrong numbers in milliseconds.

Two rules of the depth test plan are load-bearing here:

- **The depth is ragged on purpose** (13 planes): even-only depths let a
  last-plane-blank off-by-one pass every comparison.
- **Both chunk packings are exercised**: one plane per compressed block
  (what the governed writer ships today) and several planes per block
  (Thy1's shape, and a per-profile option tomorrow, 13 planes in 8-plane
  blocks so the final block is partial). Chunk geometry is the data's
  fact; a viewer correct on one packing only is correct by coincidence.

This oracle is the z third of the combined-axes identity gate ordered by
both plans (value = 1000·t + 100·c + z); the t and c thirds join it the
day the served picture grows those axes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import zarr

_VIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_VIZ / "building"))

from zmart_live.model import GridCell  # noqa: E402
from zmart_live.profiles import plan_the_writing  # noqa: E402

from check import decode  # noqa: E402
from governed import GovernedRun  # noqa: E402

DEPTH = 13     # ragged on purpose
STAMP = 1000   # plane k carries the value STAMP + k, everywhere, exactly
FRAME = 384


def a_stamped_stack() -> np.ndarray:
    planes = np.empty((DEPTH, FRAME, FRAME), dtype="uint16")
    for plane in range(DEPTH):
        planes[plane] = STAMP + plane
    return planes


def every_plane_matches(composer, *, depth: int) -> None:
    """Ask for every piece of every plane at every level; compare to the stamp.

    Constant planes survive the pyramid exactly — the mean of a constant is
    itself — so the expectation needs no resampling arithmetic: whatever
    the level, plane k holds STAMP + k and nothing else.
    """
    piece = composer.piece
    for level in range(composer.mosaic.levels):
        deep, height, width = composer.mosaic.shape(level)
        assert deep == depth, (
            f"level {level} keeps {deep} planes where the data records "
            f"{depth} -- a pyramid quietly changed the depth"
        )
        for plane in range(depth):
            for row in range(-(-height // piece)):
                for column in range(-(-width // piece)):
                    body = composer.bytes_for(level, plane, row, column)
                    decoded = decode(body, piece, str(composer.mosaic.dtype),
                                     composer.mosaic.axes)
                    valid = decoded[:height - row * piece, :width - column * piece]
                    assert set(np.unique(valid)) == {STAMP + plane}, (
                        f"level {level} plane {plane} piece ({row}, {column}) "
                        f"serves {sorted(np.unique(valid))[:4]} where the "
                        f"stamp says {STAMP + plane} -- another plane's "
                        "specimen is on screen"
                    )


def test_the_governed_door_serves_the_stamp_one_plane_per_block(tmp_path):
    """The writer's own packing: inner chunks one plane deep, z never halved."""
    from zmart_live.coordinator import LivePublisher

    profile, _ = plan_the_writing("overview", frame=FRAME, z_planes=DEPTH)
    run = LivePublisher(
        tmp_path / "experiment" / "acquisitions" / "deep",
        profile, run_id="stamped-deep",
        cells={GridCell(0, 0): "p00"},
    )
    run.write_and_publish("p00", a_stamped_stack())

    opened = GovernedRun(run.folder)
    try:
        every_plane_matches(opened.composer(), depth=DEPTH)
    finally:
        opened.close()


def test_the_built_door_serves_the_stamp_several_planes_per_block(tmp_path):
    """Thy1's packing: 8-plane blocks over 13 planes, the final block partial."""
    from declare import declare_a_built_picture

    import served

    side = 256
    store = tmp_path / "stores" / "stamped.ome.zarr"
    datasets = []
    for level in range(2):
        shrink = 2 ** level
        planes = np.empty((DEPTH, side // shrink, side // shrink), "uint16")
        for plane in range(DEPTH):
            planes[plane] = STAMP + plane
        made = zarr.create_array(
            store=str(store / str(level)), shape=planes.shape,
            chunks=(8, side // shrink, side // shrink), dtype="uint16",
            fill_value=0, overwrite=True)
        made[:] = planes
        datasets.append({
            "path": str(level),
            "coordinateTransformations": [
                {"type": "scale", "scale": [1.0, float(shrink), float(shrink)]},
                {"type": "translation", "translation": [0.0, 0.0, 0.0]},
            ],
        })
    (store / "zarr.json").write_text(json.dumps({
        "zarr_format": 3, "node_type": "group",
        "attributes": {"ome": {"version": "0.5", "multiscales": [{
            "axes": [
                {"name": "z", "type": "space", "unit": "micrometer"},
                {"name": "y", "type": "space", "unit": "micrometer"},
                {"name": "x", "type": "space", "unit": "micrometer"},
            ],
            "datasets": datasets,
        }]}},
    }, indent=2))

    declared = declare_a_built_picture(tmp_path / "shown", tmp_path / "stores",
                                       name="stamped")
    composer = served._composer_for(declared)
    assert composer is not None, "the declared picture would not open"
    try:
        every_plane_matches(composer, depth=DEPTH)
    finally:
        # The built door starts a background warm pass over the coarse
        # levels; left running, it races pytest's deletion of this fixture
        # and dies noisily at interpreter exit. Stop it and wait it out.
        composer.close()
        if composer._warmer is not None:
            composer._warmer.join(timeout=10)
