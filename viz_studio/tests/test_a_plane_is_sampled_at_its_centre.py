"""A one-plane picture is drawn, and a stack opens on the plane the rule names.

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


def _drawn_share(picture) -> float:
    pixels = np.asarray(picture)
    if pixels.ndim == 3:
        pixels = pixels[..., :3].max(axis=-1)
    return float((pixels > 16).mean())


def test_a_one_plane_source_is_drawn_not_sampled_off_its_edge(harness_page):
    """The flat map's only voxel is sampled at its centre: the picture is there."""
    harness_page.option = "neuroglancer-under"
    harness_page.open(store="square", draw="none")
    harness_page.settle(tries=40)

    share = _drawn_share(harness_page.photograph())
    assert share > 0.05, (
        f"only {share:.1%} of the box is drawn: a one-plane source sampled at its "
        "voxel boundary rather than its centre photographs as black"
    )
    # A single plane offers no depth to move through, so no control is offered
    # — and in particular no control that opens at minus half a voxel.
    assert harness_page.believes("window.harness.viewer.theDepthItCanShow?.() ?? null") is None


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
