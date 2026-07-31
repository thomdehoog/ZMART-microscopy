"""Does the viewer keep up once a lot of the specimen is open?

This guards the finding that `NEXT_STEPS.md` calls decisive, and which nothing in
the suite could see. With a thousand positions open the viewer managed 24 frames in
five seconds where a hundred positions managed 302, and a single step of a contrast
slider cost 191 milliseconds against 16. Three drawing layers are made per position
and every one of them takes part in every frame, so the cost is paid on every draw
for as long as the acquisition is open.

That is a different fault from the loading ones beside it, and worse. Loading
slowly is visible and finite — the operator waits and it finishes. A viewer that
has finished loading and then moves at five frames a second is *permanently* like
that, and it is what an operator has to work in for the rest of the session.

**It is not fixed, and these tests say so honestly.** The fix recorded in
`NEXT_STEPS.md` is that the engine has to be holding fewer positions, which is an
architectural change rather than a small one. So there are two tests here. One
holds the line where it is today, so that a further slide is noticed. The other
states the behaviour actually wanted and is marked as expected to fail, so that the
day somebody fixes it the suite says so and the marker comes off.

**Everything here is a comparison, never a number.** A machine without a graphics
card draws slowly whatever the data, so an absolute rate would mean nothing and
would need re-tuning for every machine. What is measured instead is how much of its
*own* rate the viewer keeps when ten times as many positions are open. That holds
anywhere, and if the whole machine slows down both halves slow together and the
ratio does not move.

**What it measures, stated plainly.** It moves through the specimen the way an
operator does and counts the frames the browser manages. It does not separate "the
engine is drawing more layers" from "there is more picture in view" — both are real
costs of having more positions open, and both are felt the same way by whoever is
using it. The cause, when it was last chased, was the drawing layers.
"""

from __future__ import annotations

import threading

import pytest
from server import make_server
from test_many_positions_arrive import HELD, write_folder

# How many positions to compare. Ten times as many is the same shape of comparison
# as the hundred-against-a-thousand that found the fault, and these two open in
# seconds rather than in the eight minutes a two-thousand mosaic took.
FEW = 20
MANY = 200

# How long to count frames for. Long enough to average over a slow patch, short
# enough that the test stays a test.
SAMPLE_SECONDS = 3.0

# The line the viewer must not fall below today.
#
# Measured on this repository's sandbox over three runs: it kept 40%, 35% and 38%
# of its rate — a spread of three points, which is a steady enough measurement to
# set a line against. A quarter sits well beneath that, so an ordinarily busy
# machine will not trip it, and well above the eight per cent (24 frames against
# 302) that the fault was first found at. So this catches a further slide without
# crying wolf.
MUST_KEEP_TODAY = 0.25

# What the viewer should manage, and does not. A viewer that pays no cost per
# position on every frame keeps essentially all of its rate; four fifths allows for
# there genuinely being more picture in view. This is the target, not the state.
THE_RATE_WE_WANT = 0.8

# Started once and only once: calling it twice would leave two loops running and
# both counting, which reads as the page having doubled its rate.
COUNT_FRAMES = """() => {
  if (window.__counting) return;
  window.__counting = true;
  window.__drawn = 0;
  const tick = () => { window.__drawn += 1; requestAnimationFrame(tick); };
  requestAnimationFrame(tick);
}"""

# Keep the view moving while the frames are counted. A page with nothing to redraw
# is not being asked the question this test exists to ask: the cost being looked
# for is paid per frame, so there have to be frames. Moving through the specimen is
# what an operator does constantly, and it is the surest way to ask for one.
KEEP_MOVING = """() => {
  if (window.__nudging) return;
  window.__nudging = true;
  let forward = true;
  window.__nudge = setInterval(() => {
    const nav = window.zmartViewer.navigationState;
    const at = Float32Array.from(nav.position.value);
    at[at.length - 1] += forward ? 0.5 : -0.5;
    forward = !forward;
    nav.position.value = at;
  }, 16);
}"""


def frames_drawn_with(browser, built_dist, folder, count: int) -> int:
    """Open ``count`` positions, let them settle, then count frames while moving."""
    server = make_server(
        port=0,
        data_dir=folder,
        site_dir=built_dist,
        store=sorted(p.name for p in folder.glob("*.ome.zarr"))[:count],
        live=False,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 900, "height": 700})
    try:
        page.goto(
            f"http://127.0.0.1:{server.server_address[1]}", wait_until="domcontentloaded"
        )
        page.wait_for_function("() => window.zmartViewer !== undefined", timeout=60_000)
        # Every position handed over, and nothing left queued. Counting frames while
        # stores are still arriving would measure the loading, which is a different
        # question and is measured in test_many_positions_arrive.py.
        page.wait_for_function(f"{HELD} === {count}", timeout=180_000)
        page.wait_for_function("() => window.zmartSourcesWaiting() === 0", timeout=120_000)
        page.wait_for_timeout(3000)

        page.evaluate(KEEP_MOVING)
        page.evaluate(COUNT_FRAMES)
        page.evaluate("() => { window.__drawn = 0; }")
        page.wait_for_timeout(int(SAMPLE_SECONDS * 1000))
        drawn = page.evaluate("() => window.__drawn")
        page.evaluate("() => clearInterval(window.__nudge)")
        return drawn
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


@pytest.fixture(scope="module")
def how_much_it_keeps(browser, built_dist, tmp_path_factory) -> float:
    """The share of its own drawing rate the viewer keeps at ten times the positions.

    Measured once for the whole file. Both tests below ask the same question of the
    same measurement — one about where the viewer is, one about where it should be —
    and measuring twice would double the slowest part of this file for no gain.
    """
    folder = tmp_path_factory.mktemp("drawing_cost")
    write_folder(folder, MANY)

    few = frames_drawn_with(browser, built_dist, folder, FEW)
    many = frames_drawn_with(browser, built_dist, folder, MANY)
    assert few > 0, (
        "no frames were counted even with a handful of positions open, so this "
        "measurement is not working and says nothing at all about the viewer"
    )
    kept = many / few
    print(
        f"\n  {FEW} positions: {few} frames in {SAMPLE_SECONDS:.0f}s"
        f"\n  {MANY} positions: {many} frames in {SAMPLE_SECONDS:.0f}s"
        f"\n  kept {kept:.0%} of its rate"
    )
    return kept


def test_the_drawing_rate_has_not_slid_further(how_much_it_keeps):
    """Hold the line where the viewer is today, so a further slide is noticed.

    Read the failure message before believing it on a machine doing other work: the
    two halves are measured minutes apart, so a sandbox that became busy in between
    can move the ratio on its own. Run it again on a quiet machine before treating
    one failure as a regression.
    """
    assert how_much_it_keeps >= MUST_KEEP_TODAY, (
        f"with {MANY} positions open the viewer kept only {how_much_it_keeps:.0%} "
        f"of the rate it manages with {FEW}, where it kept about a third when this "
        "line was drawn. Something has made the per-position cost worse.\n\n"
        "This is the cost paid on every frame for as long as the acquisition is "
        "open, so it is what an operator has to work in rather than something they "
        "wait out."
    )


@pytest.mark.xfail(
    reason=(
        "the viewer pays a cost per position on every frame, so opening more of the "
        "specimen slows everything down permanently rather than only while loading. "
        "Measured on this sandbox: twenty positions manage about 125 frames in three "
        "seconds and two hundred manage about 50, so a tenfold increase in positions "
        "costs roughly two thirds of the rate. It was first found far worse still, at "
        "24 frames in five seconds against 302. NEXT_STEPS.md records the cause as "
        "three drawing layers being made per position, every one of which takes part "
        "in every frame, and the fix as the engine having to hold fewer positions — "
        "which is an architectural change rather than a small one. When it is done, "
        "this test will start passing and the marker must come off."
    ),
    strict=True,
)
def test_the_drawing_rate_should_barely_depend_on_how_many_positions_are_open(
    how_much_it_keeps,
):
    """What the viewer should manage, stated so the day it does is noticed."""
    assert how_much_it_keeps >= THE_RATE_WE_WANT
