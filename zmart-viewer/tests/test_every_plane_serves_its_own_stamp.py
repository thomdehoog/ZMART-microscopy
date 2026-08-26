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
both plans (value = 1000·t + 100·c + z); the classes below are the t and
c thirds, landed with the five-axis piece address: every (t, c, z) frame
of a grown picture is asked for through the real doors and compared to
its own stamp, so a collapse, swap, or off-by-one on ANY axis — or any
combination — decodes to visibly wrong numbers in a default-suite test.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import zarr

_VIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_VIZ / "app" / "picture"))

from check_the_built_picture import decode  # noqa: E402
from governed import GovernedRun  # noqa: E402

from zmart_live.model import GridCell  # noqa: E402
from zmart_live.profiles import plan_the_writing  # noqa: E402

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
    import served
    from declare import declare_a_built_picture

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


# ---------------------------------------------------------------------------
# The combined-axes oracle: value = 1000·t + 100·c + z, both doors
# ---------------------------------------------------------------------------

MOMENTS = 2
COLOURS = 2
PLANES = 5  # odd on purpose, and small: the z-13 gates above own raggedness


def the_stamp(moment: int, channel: int, plane: int) -> int:
    # The +7 keeps frame (0, 0, 0) from stamping to zero: an all-zero frame
    # compresses to no chunk files at all, which the writer's own inspection
    # rightly refuses to publish as imaged ground.
    return 1000 * moment + 100 * channel + plane + 7


def a_combined_stack(moment: int, frame: int) -> np.ndarray:
    """One moment's landing: every (c, z) frame stamped with its identity."""
    stack = np.empty((COLOURS, PLANES, frame, frame), dtype="uint16")
    for channel in range(COLOURS):
        for plane in range(PLANES):
            stack[channel, plane] = the_stamp(moment, channel, plane)
    return stack


def test_the_built_door_serves_every_frame_through_the_real_address(tmp_path):
    """A five-axis stranger store, served frame by frame through the door.

    The request goes through ``the_bytes_behind`` with the grown seven-part
    address — the same parser and the same path a browser's chunk request
    takes — so a shift anywhere between the address and the pixels decodes
    to another frame's stamp and fails loudly.
    """
    import served
    from declare import declare_a_built_picture

    side = 128
    store = tmp_path / "stores" / "combined.ome.zarr"
    frames = np.empty((MOMENTS, COLOURS, PLANES, side, side), "uint16")
    for moment in range(MOMENTS):
        for channel in range(COLOURS):
            for plane in range(PLANES):
                frames[moment, channel, plane] = the_stamp(moment, channel, plane)
    made = zarr.create_array(
        store=str(store / "0"), shape=frames.shape,
        chunks=(1, 1, 1, side, side), dtype="uint16", fill_value=0,
        overwrite=True)
    made[:] = frames
    (store / "zarr.json").write_text(json.dumps({
        "zarr_format": 3, "node_type": "group",
        "attributes": {"ome": {"version": "0.5", "multiscales": [{
            "axes": [
                {"name": "t", "type": "time", "unit": "second"},
                {"name": "c", "type": "channel"},
                {"name": "z", "type": "space", "unit": "micrometer"},
                {"name": "y", "type": "space", "unit": "micrometer"},
                {"name": "x", "type": "space", "unit": "micrometer"},
            ],
            "datasets": [{"path": "0", "coordinateTransformations": [
                {"type": "scale", "scale": [1.0, 1.0, 1.0, 1.0, 1.0]},
                {"type": "translation",
                 "translation": [0.0, 0.0, 0.0, 0.0, 0.0]},
            ]}],
        }]}},
    }, indent=2))

    declared = declare_a_built_picture(tmp_path / "shown", tmp_path / "stores",
                                       name="combined")
    described = json.loads((declared / "zarr.json").read_text())
    axes = [axis["name"] for axis in
            described["attributes"]["ome"]["multiscales"][0]["axes"]]
    assert axes == ["t", "c", "z", "y", "x"], (
        "a picture whose tiles keep (t, c) room must declare five axes"
    )

    composer = served._composer_for(declared)
    assert composer is not None
    try:
        piece = composer.piece
        for moment in range(MOMENTS):
            for channel in range(COLOURS):
                for plane in range(PLANES):
                    body = served.the_bytes_behind(
                        declared, f"0/c/{moment}/{channel}/{plane}/0/0")
                    decoded = decode(body, piece,
                                     str(composer.mosaic.dtype),
                                     composer.mosaic.axes)
                    valid = decoded[:side, :side]
                    assert set(np.unique(valid)) == {
                        the_stamp(moment, channel, plane)}, (
                        f"frame (t={moment}, c={channel}, z={plane}) serves "
                        f"{sorted(np.unique(valid))[:3]} where its stamp is "
                        f"{the_stamp(moment, channel, plane)}"
                    )
        # One frame past every room answers absent, never a neighbour's.
        assert served.the_bytes_behind(
            declared, f"0/c/{MOMENTS}/0/0/0/0") is None
        assert served.the_bytes_behind(
            declared, f"0/c/0/{COLOURS}/0/0/0") is None
    finally:
        composer.close()
        if composer._warmer is not None:
            composer._warmer.join(timeout=10)


def test_the_governed_door_serves_the_record_not_the_files(tmp_path):
    """The oracle through the governed door — and its fail-closed edges.

    Beyond frame identity, the governed door owes two answers the built
    door does not: a moment nobody published serves as absent even when
    its pixels are already on disk (files mean nothing; the record means
    everything), and a moment published later starts serving the moment
    it is published.
    """
    from governed import GovernedRun

    from zmart_live.coordinator import LivePublisher

    frame = 384
    profile, _ = plan_the_writing(
        "overview", frame=frame, z_planes=PLANES,
        timepoints=3, channels=("green", "red"),
    )
    run = LivePublisher(
        tmp_path / "experiment" / "acquisitions" / "combined",
        profile, run_id="combined-oracle",
        cells={GridCell(0, 0): "p00"},
    )
    for moment in range(MOMENTS):
        run.write_and_publish("p00", a_combined_stack(moment, frame),
                              timepoint=moment)
    # Moment 2's pixels land on disk WITHOUT being published — every step
    # of a publication except the commit, the gateway tests' recipe. This
    # is the one state the record exists to keep off the screen.
    run.write_a_position("p00", a_combined_stack(2, frame), timepoint=2)
    run.write_the_link_map(frozenset(run._committed_units()) | {("p00", 2)})
    run.write_the_view()
    run.write_the_layout()

    opened = GovernedRun(run.folder)
    try:
        composer = opened.composer()
        piece = composer.piece
        deep, height, width = composer.mosaic.shape(0)
        assert composer.mosaic.frame_room == (3, COLOURS)
        for moment in range(MOMENTS):
            for channel in range(COLOURS):
                for plane in range(PLANES):
                    body = composer.bytes_for(0, plane, 0, 0,
                                              moment, channel)
                    decoded = decode(body, piece,
                                     str(composer.mosaic.dtype),
                                     composer.mosaic.axes)
                    valid = decoded[:height, :width]
                    assert set(np.unique(valid)) == {
                        the_stamp(moment, channel, plane)}, (
                        f"frame (t={moment}, c={channel}, z={plane}) serves "
                        "another frame's stamp through the governed door"
                    )
        for channel in range(COLOURS):
            for plane in range(PLANES):
                assert composer.bytes_for(0, plane, 0, 0, 2, channel) is None, (
                    "moment 2 is written but unpublished, and its pixels "
                    "reached the screen -- the record was bypassed"
                )

        run.publish("p00", timepoint=2)
        fresh = opened.composer()
        body = fresh.bytes_for(0, 0, 0, 0, 2, 1)
        decoded = decode(body, piece, str(fresh.mosaic.dtype),
                         fresh.mosaic.axes)
        assert set(np.unique(decoded[:height, :width])) == {the_stamp(2, 1, 0)}
    finally:
        opened.close()


def test_every_door_parses_the_one_address():
    """The one-definition rule for the piece address, checked by identity."""
    import importlib.util

    import served
    from composer import the_piece_address

    # Both server modules are called ``server``; load the building one by
    # its path so the check cannot silently land on the backend's.
    spec = importlib.util.spec_from_file_location(
        "the_building_server", _VIZ / "app" / "picture" / "server.py")
    building_server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(building_server)

    assert served.the_piece_address is the_piece_address
    assert building_server.the_piece_address is the_piece_address
    # And the parser itself: a flat address is frame (0, 0); a grown one
    # carries all six numbers; anything else is not a piece.
    assert the_piece_address("3/c/1/2/4") == (3, 0, 0, 1, 2, 4)
    assert the_piece_address("3/c/2/1/1/2/4") == (3, 2, 1, 1, 2, 4)
    assert the_piece_address("3/c/1/2") is None
    assert the_piece_address("3/c//1/2/4") is None
