"""Every place that shrinks an extent to a coarser level must round UP.

A stack 13 planes deep, halved, is 7 planes — the seventh coarse plane is
half-filled but holds real specimen, and flooring to 6 would cut the last
plane off the world. The same is true across and down the picture. Today
the rule is invisible: profiles choose frames that divide exactly and no
level shrinks z at all, so floor and ceiling agree everywhere by luck.
The depth chapter ends that luck (levels that halve z are a per-profile
fact, and 291-plane stacks are not powers of two), and both depth reviews
found the call sites already disagreeing — floor in the writer and the
gateway, ceiling in the viewer's world frame — a seam that would surface
as a missing last plane the day a z divisor ships.

This gate drives one odd depth through the real call sites with a real
z-halving profile (legal today as a non-linkable level) and holds them to
the same ceiling answer. It was red when written — the writer's two sites
floored — and it pins the rule before any divisor changes, exactly as the
depth test plan orders (stage 1).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_VIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_VIZ / "app" / "picture"))

from zmart_live.coordinator import LivePublisher  # noqa: E402
from zmart_live.model import AcquisitionProfile, GridCell, LevelGeometry  # noqa: E402

DEPTH = 13  # odd on purpose: the ceiling-versus-floor seam, and 13 // 2 != -(-13 // 2)


@pytest.fixture()
def a_deep_run_whose_levels_halve_z(tmp_path):
    """One position, 13 planes, and a level that halves every spatial axis.

    The z-halving level is non-linkable, which is what makes it legal
    today: linkable levels demand exact division, and this gate exists
    precisely for the extents that do not divide exactly.
    """
    from dataclasses import replace

    from zmart_live.identity import name_for_a_profile

    profile = AcquisitionProfile(
        profile_id="deep-halving",
        acquisition_type="overview",
        axes=("t", "c", "z", "y", "x"),
        frame_shape={"z": DEPTH, "y": 128, "x": 128},
        dtype="uint16",
        voxel_size={"z": 2.0, "y": 0.5, "x": 0.5},
        topology="grid",
        overlap_pixels={"y": 16, "x": 16},
        levels=(
            LevelGeometry(level=0, downsampling={"z": 1, "y": 1, "x": 1},
                          inner_chunk={"z": 1, "y": 128, "x": 128}),
            LevelGeometry(level=1, downsampling={"z": 2, "y": 2, "x": 2},
                          inner_chunk={"z": 1, "y": 64, "x": 64}),
        ),
        channels=("gfp",),
    )
    profile = replace(
        profile, profile_id=name_for_a_profile(profile, readable_prefix="deep")
    )
    return LivePublisher(
        tmp_path / "experiment" / "acquisitions" / "deep",
        profile, run_id="deep-halving-run",
        cells={GridCell(0, 0): "p00"},
    )


def test_the_writer_and_the_world_frame_agree_on_the_ceiling(
    a_deep_run_whose_levels_halve_z,
):
    from governed import TheWorldFrame

    run = a_deep_run_whose_levels_halve_z
    ceiling = (-(-DEPTH // 2), 64, 64)  # (7, 64, 64)

    # The writer's two extent computations: where one tile's pixels sit in
    # the overview, and how large the whole overview is.
    pointed = run._where_one_tile_is_pointed_at("p00", 1)
    assert tuple(pointed.size) == ceiling, (
        f"the writer sizes a tile at level 1 as {tuple(pointed.size)} -- "
        "flooring the odd depth cuts the last plane off the copy"
    )
    assert run._how_big_the_overview_is(1) == ceiling, (
        "the writer sizes the whole overview by flooring the odd depth"
    )

    # The viewer's world frame over the very same layout and profile. The
    # run folder names WHICH run the remembered geometry belongs to (the
    # cache-poisoning fix of 2026-08-19); the geometry itself still comes
    # from the layout and profile alone.
    frame = TheWorldFrame([], run.layout, run.profile, run=run.folder)
    assert frame.shape(1) == ceiling, (
        "the world frame disagrees with the ceiling rule"
    )


def test_the_rule_has_exactly_one_definition():
    """The ceiling lives in one named function, imported at every site.

    The one-definition discipline both depth reviews demanded: if a call
    site computes its own rounding instead of importing the rule, the
    day someone changes one of them the picture's levels disagree about
    how deep the world is. Identity (`is`), not equality: the same
    function object, not a lookalike.
    """
    import governed

    from zmart_live import coordinator, gateway, model

    assert coordinator.rounded_up is model.rounded_up
    assert gateway.rounded_up is model.rounded_up
    assert governed.rounded_up is model.rounded_up
