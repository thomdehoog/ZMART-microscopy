"""Two layers, one on top of the other: do they stay lined up?

This is the check described in :mod:`margins`, run against the two arrangements
this project is choosing between. It is written as a test rather than only as a
measurement because the question comes back every time either layer changes, and
because a check nobody can run again is not a check.

What each part is for:

- **The control must come out at zero.** Both layers drawn inside one canvas
  cannot come apart, so if the check finds them apart the check is measuring its
  own noise and nothing else here means anything.
- **The arrangement being proposed must match the control.** The image in a
  canvas of its own underneath, with the layer on top repainted from the frame
  the engine has just drawn.
- **The arrangement that ought to fail must fail.** The same thing with the layer
  on top repainted the instant the mouse moves. If that passes too, the check
  cannot tell the two apart and is worth nothing.
- **And a turned view must be caught**, because that is the fault
  `CONTROLS.md` says is silent.

These open a real browser and read the pixels it drew. On a machine that cannot
draw they skip, with a reason, in the same way as the rest of this suite.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_VIZ = Path(__file__).resolve().parent.parent
_SANDWICH = _VIZ / "sandwich"
for extra in (str(_SANDWICH), str(_VIZ.parent)):
    if extra not in sys.path:
        sys.path.insert(0, extra)


def _harness():
    try:
        import measure  # noqa: F401
    except ImportError as why:  # pragma: no cover - depends on the machine
        pytest.skip(f"the sandwich harness cannot be imported: {why}")
    return measure


@pytest.fixture(scope="module")
def probe(tmp_path_factory):
    """The probe page, its server, and a browser, opened once for these tests."""
    measure = _harness()
    if not (_SANDWICH / "page" / "dist" / "index.html").exists():
        pytest.skip(
            "the probe page has not been built — run "
            "`npm --prefix viz_studio/sandwich/page install && "
            "npm --prefix viz_studio/sandwich/page run build`"
        )
    out = tmp_path_factory.mktemp("margins")
    data = out / "data"
    data.mkdir()
    measure.write_the_square(data).close()
    measure.write_the_sparse_canvas(data).close()
    opened = measure.Probe(data, out)
    try:
        with opened:
            yield opened
    except Exception as why:  # pragma: no cover - depends on the machine
        pytest.skip(f"no usable browser for the margin check: {why}")


def _worst_unevenness(probe, *, arrangement, follow):
    """Pan, zoom and throw the view about, and return the worst reading."""
    measure = _harness()
    probe.open(arrangement=arrangement, follow=follow, store="square", voxels=1024)
    worst = 0.0
    for gesture in (measure.pan_steadily, measure.throw_it_about, measure.zoom_in_and_out):
        found = measure.measure_a_gesture(probe, gesture, f"{arrangement}-{follow}")
        assert found["samples"] > 5, (
            f"only {found['samples']} usable photographs out of "
            f"{found['photographs']} — the check did not see enough to say anything"
        )
        worst = max(worst, found["unevenness"])
    return worst


# How uneven the four sides may be and still count as lined up, in the
# photograph's own pixels. One pixel is the floor of the measurement itself: the
# hole falls on fractional pixel positions and its soft edge is read as one place
# or the next. The control comes out at nought and the proposed arrangement at
# one, so two leaves room for the machine to be having a bad day without leaving
# room for a real disagreement, which starts at ten and goes to eighty.
LINED_UP = 2.0


def test_one_canvas_holding_both_layers_cannot_come_apart(probe):
    """The control. If this is not zero, nothing else in this file means anything."""
    worst = _worst_unevenness(probe, arrangement="one-canvas", follow="presented")
    assert worst <= LINED_UP, (
        f"the two layers came {worst} pixels apart inside a single canvas, where "
        "they are drawn in one pass from one view and cannot. That is the check "
        "measuring its own noise, so no other reading here can be trusted."
    )


def test_the_image_underneath_stays_put_when_the_sheet_follows_the_engine(probe):
    """The arrangement being proposed: repaint from the frame the engine just drew."""
    worst = _worst_unevenness(probe, arrangement="sandwich", follow="presented")
    assert worst <= LINED_UP, (
        f"the picture slid {worst} pixels out from under the drawing over it. "
        "The whole point of repainting from the engine's last finished frame is "
        "that both layers are equally behind, which is the same as being lined up."
    )


def test_the_check_notices_a_sheet_that_follows_the_mouse_instead(probe):
    """And the arrangement that ought to fail must fail.

    A check that passes whatever it is shown is worse than no check. This one
    repaints the layer on top the moment the mouse moves, without waiting for the
    engine, which is exactly the mistake the arrangement above exists to avoid.
    """
    worst = _worst_unevenness(probe, arrangement="sandwich", follow="pointer")
    assert worst > LINED_UP * 2, (
        "repainting the layer on top the instant the mouse moves left the two "
        f"layers only {worst} pixels apart, which is as good as waiting for the "
        "engine. Either the machine is too slow to tell them apart or the check "
        "has stopped being able to see a disagreement at all."
    )


def test_the_check_notices_a_turned_view(probe):
    """A turned flat view stops lining up with the drawing over it, silently.

    `CONTROLS.md` removes every way an operator could turn the flat view, and a
    removal is only worth having if something would notice it coming back. So the
    view is turned here deliberately, past any gesture, and the check must see it.

    Note which reading catches it. A square turned by a couple of degrees is
    almost exactly as wide across its middle as it was, so a single cut through
    the centre says nothing is wrong. It is the *slant* — the same side measured
    along three cuts that disagree with each other — that gives it away.
    """
    from margins import margins_at_every_cut

    probe.open(arrangement="sandwich", follow="presented", store="square", voxels=1024)
    probe.believes("window.probe.reset()")
    probe.settle(tries=20)
    _, straight = margins_at_every_cut(probe.photograph())
    assert straight is not None and straight <= LINED_UP, (
        f"the edges were already slanted by {straight} pixels before anything was "
        "turned, so this test could not tell a turn from its own starting point"
    )

    probe.believes("window.probe.rotateOnPurpose(2)")
    probe.settle(tries=15)
    _, turned = margins_at_every_cut(probe.photograph())
    assert turned is not None and turned > LINED_UP, (
        f"the view was turned two degrees and the edges slanted by only {turned} "
        "pixels, so a rotation creeping back into the flat view would go unnoticed"
    )
