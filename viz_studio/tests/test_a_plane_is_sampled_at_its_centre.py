"""A one-plane picture is drawn at its centre and gone past its edge; a stack opens where the rule says.

This is the committed form of a fact that only ever lived in a debugging
report: that a flat, one-plane source is drawn when the engine samples the
*centre* of its single voxel, and disappears when it samples the voxel's
boundary. Neuroglancer counts a voxel as running from ``k`` to ``k + 1``, so
the centre of the only plane is at a height of one half — which is exactly
where `neuroglancer-under/viewer.js` puts the height for a flat map
(``theMapStandsOnItsFirstPlane``) and exactly why its depth reading subtracts
a half before speaking in micrometres (``theDepthItCanShow``).

Nothing here is asserted from the source text. A store is written, the engine
is opened on it in a real browser, and the photograph is looked at: a
one-plane picture that is not on screen photographs as black, whatever the
engine reports about itself. The stack half of the check reads the depth
control back and holds it to the middle-plane rule in ``options/planes.js``,
with the half-voxel arithmetic inside: a stack of four planes at 2 µm opens
at plane 2, which is 4 µm from the first plane — not 3 µm, not 5 µm.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "options" / "measure"))
sys.path.insert(0, str(_HERE.parent.parent))

from test_the_options_hold_together import harness_page, measurement_data  # noqa: E402,F401

pytestmark = pytest.mark.usefixtures("harness_page")


def _spread(picture) -> float:
    """How varied the photograph is: near nought for the empty box, large for a picture.

    The box is painted a dark grey, not black, so "brighter than black" would
    call an empty box drawn — it did, once. The spread of the colours cannot be
    fooled that way: one flat colour has none, whatever colour it is.
    """
    return float(np.asarray(picture)[..., :3].astype(float).std())


def test_a_one_plane_source_is_drawn_at_its_centre_and_gone_past_its_edge(harness_page):
    """The flat map's only voxel: sampled inside it there is a picture, past it there is none.

    Two photographs, and the check is that they differ. The first is taken
    where the engine opens, which is the voxel's centre; the second after the
    height has been pushed a whole voxel further, past the only plane there
    is. A test that looked at one photograph alone could be satisfied by an
    empty box — and was, until the box's own colour was taken into account.
    """
    harness_page.option = "neuroglancer-under"
    harness_page.open(store="square", draw="none")
    harness_page.settle(tries=40)
    at_the_centre = _spread(harness_page.photograph())

    # A single plane offers no depth to move through, so no control is offered
    # — and in particular no control that opens at minus half a voxel.
    assert harness_page.believes("window.harness.viewer.theDepthItCanShow?.() ?? null") is None

    # Push the height past the only voxel: 1.5 voxels of a 1 µm voxel.
    harness_page.believes("window.harness.viewer.setPlane(1.5)")
    harness_page.settle(tries=40)
    past_the_edge = _spread(harness_page.photograph())

    assert at_the_centre > 20, f"nothing drawn at the centre: spread {at_the_centre:.1f}"
    assert past_the_edge < 5, f"still drawing past the edge: spread {past_the_edge:.1f}"


@pytest.mark.parametrize("option", ["neuroglancer-under", "viv-under"])
def test_the_plane_asked_for_is_the_plane_read_back(harness_page, measurement_data, option):
    """setPlane and theDepthItCanShow agree, to the micrometre, on both engines.

    Neuroglancer keeps its bounds at voxel edges, so a height asked for as a
    plane's edge and read back as a centre came out half a plane short: asked
    for 4 µm at 2 µm a plane, the reading said 3. The two now count the same
    way, and this holds them to it.
    """
    _a_four_plane_stack(measurement_data)
    harness_page.option = option
    harness_page.open(store="stack", draw="none")
    harness_page.settle(tries=40)
    for asked in (0.0, 2.0, 4.0, 6.0):
        harness_page.believes(f"window.harness.viewer.setPlane({asked})")
        read = harness_page.believes("window.harness.viewer.theDepthItCanShow()")
        assert read["atUm"] == pytest.approx(asked, abs=1e-6), (
            f"{option}: asked for {asked} µm and read back {read['atUm']} µm"
        )


def _a_four_plane_stack(measurement_data):
    """Four planes at 2 µm, written once beside the rig's own stores."""
    _a_four_plane_stack(measurement_data)

    harness_page.option = option
    harness_page.open(store="stack", draw="none")
    harness_page.settle(tries=40)
    for asked in (0.0, 2.0, 4.0, 6.0):
        harness_page.believes(f"window.harness.viewer.setPlane({asked})")
        read = harness_page.believes("window.harness.viewer.theDepthItCanShow()")
        assert read["atUm"] == pytest.approx(asked, abs=1e-6), (
            f"{option}: asked for {asked} µm and read back {read['atUm']} µm"
        )


def _a_four_plane_stack(measurement_data):
    """Four planes at 2 µm, written once beside the rig's own stores."""
    import acquisitions

    from zmart_storage.canvas import Channel

    if (measurement_data / "stack.ome.zarr").exists():
        return
    stack = acquisitions._canvas(
        measurement_data, "stack",
        shape=(4, acquisitions.SQUARE_VOXELS, acquisitions.SQUARE_VOXELS),
        tile=(4, acquisitions.SQUARE_TILE, acquisitions.SQUARE_TILE),
        voxel_um=2.0,
        channels=[Channel(name="probe", color="FFFFFF", window=(0, 4095))],
    )
    tiles = acquisitions.SQUARE_VOXELS // acquisitions.SQUARE_TILE
    for row in range(tiles):
        for column in range(tiles):
            stack.write(
                acquisitions._a_tile(4, acquisitions.SQUARE_TILE, acquisitions.SQUARE_TILE,
                                     row * tiles + column),
                origin=(0, row * acquisitions.SQUARE_TILE, column * acquisitions.SQUARE_TILE),
                tile_index=(0, row, column),
            )


@pytest.mark.parametrize(
    "option",
    [
        pytest.param(
            "neuroglancer-under",
            marks=pytest.mark.xfail(
                strict=True,
                reason=(
                    "neuroglancer-under puts every acquisition on its first plane "
                    "(theMapStandsOnItsFirstPlane) and does not ask options/planes.js. "
                    "That is the debt test_no_option_decides_for_itself_which_plane_to_open_on "
                    "already names; this stays an expected failure until the engine "
                    "opens a stack where the rule says, and then fails loudly so the "
                    "mark is removed."
                ),
            ),
        ),
        "viv-under",
    ],
)
def test_a_stack_opens_on_the_middle_plane_the_rule_names(
    harness_page, measurement_data, option,
):
    """Four planes at 2 µm open at plane 2, which is 4 µm from the first plane.

    The middle-plane rule in ``options/planes.js`` is the legacy anchor the
    design names for a stack with no recorded reference plane. This holds each
    engine to it, and records which engine does not yet keep it.
    """
    import acquisitions

    from zmart_storage.canvas import Channel

    stack = acquisitions._canvas(
        measurement_data, "stack",
        shape=(4, acquisitions.SQUARE_VOXELS, acquisitions.SQUARE_VOXELS),
        tile=(4, acquisitions.SQUARE_TILE, acquisitions.SQUARE_TILE),
        voxel_um=2.0,
        channels=[Channel(name="probe", color="FFFFFF", window=(0, 4095))],
    )
    tiles = acquisitions.SQUARE_VOXELS // acquisitions.SQUARE_TILE
    for row in range(tiles):
        for column in range(tiles):
            stack.write(
                acquisitions._a_tile(4, acquisitions.SQUARE_TILE, acquisitions.SQUARE_TILE,
                                     row * tiles + column),
                origin=(0, row * acquisitions.SQUARE_TILE, column * acquisitions.SQUARE_TILE),
                tile_index=(0, row, column),
            )

    harness_page.option = option
    harness_page.open(store="stack", draw="none")
    harness_page.settle(tries=40)

    depth = harness_page.believes("window.harness.viewer.theDepthItCanShow()")
    assert depth is not None, "a four-plane stack offers a depth control"
    assert depth["lowUm"] == 0
    assert depth["stepUm"] == pytest.approx(2.0)
    assert depth["highUm"] == pytest.approx(6.0)
    # floor(4 / 2) = 2, the middle plane `planes.js` names; plane 2 sits 4 µm
    # from the first. A reading of 3 or 5 would mean the engine's half-voxel
    # had leaked into the number an operator is shown.
    assert depth["atUm"] == pytest.approx(4.0, abs=1e-6)
