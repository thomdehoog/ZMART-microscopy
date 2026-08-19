"""A grown (t, c) live run's baked ground stays true, commit by commit.

The flat per-commit bake has its own file of gates; this is the grown room's
retirement of the last bake refusal. A timelapse or multi-channel run bakes
one file per (moment, channel) piece, exactly as a grown transfer does since
the per-frame bake landed -- and every commit patches the touched frames
before anyone can be answered from them. The oracle is the flat file's:
byte-equality with a from-scratch bake of the same manifest state, because
the from-scratch bake is trivially true.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

VIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(VIZ / "building"))
sys.path.insert(0, str(VIZ.parent))

from declare import declare_a_governed_picture  # noqa: E402
from governed import GovernedRun  # noqa: E402
from test_a_governed_picture_is_baked_per_commit import (  # noqa: E402
    a_fresh_bake_of,
    every_baked_file,
)
from test_the_composer_obeys_the_manifest import FRAME, PIECE  # noqa: E402

from zmart_live.coordinator import LivePublisher  # noqa: E402
from zmart_live.model import GridCell  # noqa: E402
from zmart_live.profiles import plan_the_writing  # noqa: E402


def _a_grown_run(folder: Path) -> LivePublisher:
    """Two positions, two channels, room for two moments."""
    profile, _ = plan_the_writing("overview", frame=FRAME, z_planes=1,
                                  timepoints=2, channels=("a", "b"))
    return LivePublisher(folder, profile, run_id="grown-bake-run",
                         cells={GridCell(0, 0): "posA",
                                GridCell(0, 1): "posB"})


def _a_frame(value: int) -> np.ndarray:
    """One publication: both channels, told apart by a fixed offset."""
    stack = np.empty((2, 1, FRAME, FRAME), "uint16")
    stack[0] = value
    stack[1] = value + 4000
    return stack


def test_a_grown_declare_bakes_every_frame(tmp_path):
    """The last bake refusal retires: a grown run bakes, frame by frame.

    Every baked file must hold exactly the bytes composing that (moment,
    channel) gives, and a moment one position has not reached stays absent
    for that position's ground -- fill, not another moment's specimen.
    """
    run = _a_grown_run(tmp_path)
    run.write_and_publish("posA", _a_frame(500), timepoint=0)
    run.write_and_publish("posB", _a_frame(1300), timepoint=0)
    run.write_and_publish("posA", _a_frame(2100), timepoint=1)

    store = declare_a_governed_picture(run.folder / "views" / "shown",
                                       run.folder, name="shown", piece=PIECE,
                                       bake=True)
    governed = GovernedRun(run.folder, piece=PIECE, store=store)
    try:
        composer = governed.composer()
        composer.stop_warming()
        moments, channels = composer.mosaic.frame_room
        assert (moments, channels) == (2, 2)
        checked = 0
        for level_dir in sorted(store.glob("[0-9]*")):
            level = int(level_dir.name)
            if not (level_dir / "c").is_dir():
                continue
            if level >= composer.mosaic.levels:
                continue  # the extended levels are the rehalve gate's below
            deep, down, across = composer.grid(level)
            for moment in range(moments):
                for channel in range(channels):
                    for plane in range(deep):
                        for row in range(down):
                            for column in range(across):
                                body = composer.bytes_for(
                                    level, plane, row, column,
                                    moment=moment, channel=channel)
                                baked = store.joinpath(
                                    str(level), "c", str(moment),
                                    str(channel), str(plane), str(row),
                                    str(column))
                                if body is None:
                                    assert not baked.exists(), (
                                        f"{baked} exists over absent ground"
                                    )
                                    continue
                                checked += 1
                                assert baked.is_file(), (
                                    f"frame ({moment}, {channel}) of level "
                                    f"{level} was not baked at {baked}"
                                )
                                assert baked.read_bytes() == body
        assert checked, "the gate never compared a single baked frame"
    finally:
        governed.close()


def _the_composed_footprint_of(composer, store: Path, name: str) -> int:
    """How many baked pieces one position's ground touches, at the levels
    the bake composes from tiles (the extended levels above are re-halved,
    not composed). The same footprint rule the patcher itself applies, so
    the gates below can say "no more work than the change" in its units.
    """
    import json

    baked = json.loads((store / "zarr.json").read_text(encoding="utf-8"))[
        "attributes"]["zmart"]["baked"]
    tile = next(one for one in composer.mosaic.tiles
                if one.name.split(".")[0] == name)
    pieces = 0
    for level in baked:
        if level >= composer.mosaic.levels:
            continue
        at = composer.mosaic.lands_at(tile, level)
        held = tile.copies[level].shape
        rows = (at[1] + held[1] - 1) // PIECE - at[1] // PIECE + 1
        columns = (at[2] + held[2] - 1) // PIECE - at[2] // PIECE + 1
        pieces += rows * columns
    return pieces


def test_a_moment_landing_composes_only_the_frames_it_touched(tmp_path):
    """A landing at one moment must not recompose the whole timelapse.

    The stage-0 instruments projected ~165-190 seconds of frozen picture
    for a synchronous whole-room patch at a 500-moment retake
    (MEASURED_stage0_c_and_t_instruments.md), and the c-and-t plan made a
    per-moment bound the build gate. The commit names the moment it
    touched, so the patch composes that moment's frames of the footprint
    -- every channel, since a publication writes all channels -- and
    nothing else. The room here is only two moments and two channels, but
    the arithmetic discriminates: the footprint once per touched frame
    (x2 channels) against once per every frame (x4).
    """
    run = _a_grown_run(tmp_path)
    run.write_and_publish("posA", _a_frame(500), timepoint=0)
    run.write_and_publish("posB", _a_frame(1300), timepoint=0)
    store = declare_a_governed_picture(run.folder / "views" / "shown",
                                       run.folder, name="shown", piece=PIECE,
                                       bake=True)
    governed = GovernedRun(run.folder, piece=PIECE, store=store)
    try:
        governed.composer().stop_warming()
        run.write_and_publish("posB", _a_frame(3000), timepoint=1)
        composer = governed.composer()
        composer.stop_warming()
        counted = governed.accounting["last_bake_pieces_composed"]
        footprint = _the_composed_footprint_of(composer, store, "posB")
        channels = composer.mosaic.frame_room[1]
        assert counted <= footprint * channels, (
            f"one moment landed, but the patch composed {counted} pieces "
            f"against a one-moment bound of {footprint * channels} -- it is "
            "recomposing frames the commit never touched, which is the "
            "whole-room freeze the stage-0 instruments measured"
        )
    finally:
        governed.close()


def test_a_recovering_scan_patches_only_the_landed_moments(tmp_path):
    """A stale stamp names its missed events, and they name their moments.

    A landing that arrives while no viewer is open is caught up on the
    next open by the stamp scan. The scan reads which events the stamp
    never absorbed, and each event says which moment it committed -- so
    the catch-up carries the same per-moment bound as the live patch, and
    the files still end byte-identical to a from-scratch bake.
    """
    run = _a_grown_run(tmp_path)
    run.write_and_publish("posA", _a_frame(500), timepoint=0)
    run.write_and_publish("posB", _a_frame(1300), timepoint=0)
    store = declare_a_governed_picture(run.folder / "views" / "shown",
                                       run.folder, name="shown", piece=PIECE,
                                       bake=True)
    run.write_and_publish("posB", _a_frame(3000), timepoint=1)

    governed = GovernedRun(run.folder, piece=PIECE, store=store)
    try:
        composer = governed.composer()
        composer.stop_warming()
        counted = governed.accounting["last_bake_pieces_composed"]
        footprint = _the_composed_footprint_of(composer, store, "posB")
        channels = composer.mosaic.frame_room[1]
        assert counted <= footprint * channels, (
            f"the catch-up scan composed {counted} pieces against a "
            f"one-moment bound of {footprint * channels}"
        )
        patched = every_baked_file(store)
        reference = a_fresh_bake_of(run.folder, tmp_path / "reference")
        assert patched == reference
    finally:
        governed.close()


def test_a_retake_replaces_every_moment_of_its_position(tmp_path):
    """A retaken position's OTHER moments cannot survive as stale files.

    A retake moves the whole position to a new generation -- a new folder
    carrying every moment it already held, with the retaken moment's
    pixels replaced. Every baked frame of that position now composes from
    the new store, so the patch must treat a generation change as touching
    every moment the position ever wrote, not just the retaken one.
    """
    run = _a_grown_run(tmp_path)
    run.write_and_publish("posA", _a_frame(500), timepoint=0)
    run.write_and_publish("posA", _a_frame(900), timepoint=1)
    run.write_and_publish("posB", _a_frame(1300), timepoint=0)
    store = declare_a_governed_picture(run.folder / "views" / "shown",
                                       run.folder, name="shown", piece=PIECE,
                                       bake=True)
    governed = GovernedRun(run.folder, piece=PIECE, store=store)
    try:
        governed.composer().stop_warming()
        run.replace_a_position("posA", _a_frame(2600), timepoint=0)
        governed.composer().stop_warming()
        patched = every_baked_file(store)
        reference = a_fresh_bake_of(run.folder, tmp_path / "reference")
        assert patched == reference, (
            "after a retake the baked files differ from a from-scratch "
            "bake of the same state: "
            + ", ".join(sorted(set(patched) ^ set(reference))[:6] or
                        [one for one in sorted(patched)
                         if patched[one] != reference.get(one)][:6])
        )
    finally:
        governed.close()


def test_a_moment_landing_patches_the_grown_bake(tmp_path):
    """A commit at a new moment makes the touched frames true again.

    The oracle is byte-equality of EVERY baked file with a from-scratch
    bake of the same manifest state -- moments, channels, extended levels
    and all.
    """
    run = _a_grown_run(tmp_path)
    run.write_and_publish("posA", _a_frame(500), timepoint=0)
    run.write_and_publish("posB", _a_frame(1300), timepoint=0)

    store = declare_a_governed_picture(run.folder / "views" / "shown",
                                       run.folder, name="shown", piece=PIECE,
                                       bake=True)
    governed = GovernedRun(run.folder, piece=PIECE, store=store)
    try:
        governed.composer().stop_warming()
        run.write_and_publish("posB", _a_frame(3000), timepoint=1)
        governed.composer().stop_warming()  # the derive patches before answering
        patched = every_baked_file(store)
        reference = a_fresh_bake_of(run.folder, tmp_path / "reference")
        assert patched == reference, (
            "the patched grown bake differs from a from-scratch bake of the "
            "same state: "
            + ", ".join(sorted(set(patched) ^ set(reference))[:6] or
                        [one for one in sorted(patched)
                         if patched[one] != reference.get(one)][:6])
        )
    finally:
        governed.close()
