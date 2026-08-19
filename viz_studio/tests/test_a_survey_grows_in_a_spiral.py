"""A survey that grows outward in a spiral stays visible at every step.

This is the acquisition pattern a smart microscope actually drives: the run
opens with a block of positions already imaged in the middle of the canvas,
and every later position lands one step further out, ring after ring,
spiralling away from the centre. The operator should *watch* the survey grow
-- each landing appearing on screen while everything already drawn stays
exactly where it was.

Two different things can break, so two different instruments guard them:

1. **The spiral itself** -- the order positions land in. Its properties are
   pinned as plain unit tests: the walk starts at the centre, never returns
   inward, steps through each ring contiguously, and covers every cell of
   the survey exactly once. The manifest's commit order is then checked
   against that same walk, so "the spiral was done properly" is a fact about
   the published record, not about intentions.

2. **The growth on screen** -- a browser gate. The centre block is published
   before the page opens; the remaining rings then land live, and after each
   ring the photographed canvas must show more lit ground than before, in a
   patch that has grown outward around the same centre, while the running
   lit fraction never falls back (nothing already on screen may go dark --
   the no-black promise, held during growth).

The gate runs under the one cache invalidation the viewer keeps:
whole-source, which drops everything and refetches behind the picture on
screen. (A named per-piece ladder was measured beside it and deleted.)

In-container sizes are deliberately modest. On a real GPU the same gate
scales through two environment knobs: ``ZMART_SPIRAL_ACROSS`` (survey side,
default 12) and ``ZMART_SPIRAL_SEED_RINGS`` (how many centre rings are
already imaged when the page opens, default 2) -- raise the seed to open on
an already-large survey and confirm late landings still appear promptly.
"""

from __future__ import annotations

import io
import json
import os
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pytest

_VIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_VIZ / "building"))

import measure_a_governed_run_at_scale as harness  # noqa: E402
from declare import declare_a_governed_picture  # noqa: E402
from server import make_server  # noqa: E402
from test_a_commit_storm_under_zooming import _announce, _dirty_for  # noqa: E402

ACROSS = int(os.environ.get("ZMART_SPIRAL_ACROSS", "12"))
SEED_RINGS = int(os.environ.get("ZMART_SPIRAL_SEED_RINGS", "2"))


# ---------------------------------------------------------------------------
# The spiral, as arithmetic
# ---------------------------------------------------------------------------

def ring_of(row: int, column: int, across: int) -> int:
    """Which ring of the spiral a cell belongs to, centre being ring zero.

    Doubling keeps the arithmetic in whole numbers for even-sided surveys,
    where the centre falls between four cells rather than on one.
    """
    doubled = max(abs(2 * row - (across - 1)), abs(2 * column - (across - 1)))
    # Odd-sided surveys have a true centre cell (doubled = 0, 2, 4, ...);
    # even-sided ones centre between four cells (doubled = 1, 3, 5, ...).
    return doubled // 2 if across % 2 == 1 else (doubled - 1) // 2


def one_ring_walk(ring: int, across: int) -> list[tuple[int, int]]:
    """The cells of one ring, walked contiguously clockwise from its top-left."""
    cells = [(row, column)
             for row in range(across) for column in range(across)
             if ring_of(row, column, across) == ring]
    if not cells:
        return []
    top = min(row for row, _ in cells)
    bottom = max(row for row, _ in cells)
    left = min(column for _, column in cells)
    right = max(column for _, column in cells)
    walk = [(top, column) for column in range(left, right + 1)]
    walk += [(row, right) for row in range(top + 1, bottom + 1)]
    walk += [(bottom, column) for column in range(right - 1, left - 1, -1)]
    walk += [(row, left) for row in range(bottom - 1, top, -1)]
    return walk


def the_spiral(across: int) -> list[tuple[int, int]]:
    """Every cell of the survey, centre block first, then ring after ring."""
    rings = ring_of(0, 0, across) + 1
    ordered: list[tuple[int, int]] = []
    for ring in range(rings):
        ordered.extend(one_ring_walk(ring, across))
    return ordered


class TestTheSpiralItself:
    """The walk's properties, pinned before any browser is involved."""

    @pytest.mark.parametrize("across", [5, 8, 12, 13])
    def test_every_cell_is_visited_exactly_once(self, across):
        walked = the_spiral(across)
        assert len(walked) == across * across
        assert len(set(walked)) == across * across

    @pytest.mark.parametrize("across", [5, 8, 12, 13])
    def test_the_walk_never_returns_inward(self, across):
        rings = [ring_of(row, column, across) for row, column in the_spiral(across)]
        assert rings == sorted(rings), (
            "a later cell of the spiral sits on an inner ring -- the walk "
            "turned back toward the centre"
        )

    @pytest.mark.parametrize("across", [5, 8, 12, 13])
    def test_each_ring_is_walked_contiguously(self, across):
        for ring in range(1, ring_of(0, 0, across) + 1):
            walk = one_ring_walk(ring, across)
            for here, there in zip(walk, walk[1:], strict=False):
                assert max(abs(here[0] - there[0]), abs(here[1] - there[1])) == 1, (
                    f"ring {ring} jumps from {here} to {there} -- not a walk"
                )

    def test_the_instrument_rejects_a_shuffled_order(self):
        """The never-inward check can actually fail, proven here forever."""
        shuffled = list(reversed(the_spiral(8)))
        rings = [ring_of(row, column, 8) for row, column in shuffled]
        assert rings != sorted(rings)


# ---------------------------------------------------------------------------
# Colours and moments ride the same spiral, at the record level
# ---------------------------------------------------------------------------
#
# A run recording two colours over two moments, landed in the same spiral,
# must keep every promise the FILE contract makes about (t, c): a new moment
# only ever adds files, the record and the walk agree moment by moment, and
# the declared picture carries the grown (t, c) axes.

class TestTheSpiralWithColoursAndMoments:

    ACROSS = 4  # rings 0..1: a seeded 2x2 centre and one spiral ring

    def a_two_colour_timelapse(self, folder):
        from zmart_live.coordinator import LivePublisher
        from zmart_live.model import GridCell
        from zmart_live.profiles import plan_the_writing

        profile, _ = plan_the_writing(
            "overview", frame=harness.FRAME, z_planes=1,
            channels=("green", "red"), timepoints=2,
        )
        width = len(str(self.ACROSS - 1))
        cells = {GridCell(row, column): f"p{row:0{width}d}{column:0{width}d}"
                 for row in range(self.ACROSS) for column in range(self.ACROSS)}
        run = LivePublisher(
            folder / "experiment" / "acquisitions" / "spiral",
            profile, run_id="spiral-colours",
            cells=cells, channels=("green", "red"),
        )
        return run, width

    def coloured_frame(self, value: int) -> np.ndarray:
        one = np.full((1, harness.FRAME, harness.FRAME), value, "uint16")
        return np.stack([one, one + 1])  # green, red: distinct on purpose

    def test_a_new_moment_only_adds_files_and_colours_stay_apart(self, tmp_path):
        import zarr

        run, width = self.a_two_colour_timelapse(tmp_path)
        spiral = [f"p{row:0{width}d}{column:0{width}d}"
                  for row, column in the_spiral(self.ACROSS)]
        for number, position_id in enumerate(spiral):
            run.write_and_publish(position_id,
                                  self.coloured_frame(1000 + number * 10),
                                  timepoint=0)

        # Every byte moment zero owns, photographed before moment one lands.
        # The chunk files of a published moment are the immutable science;
        # the contract says a new moment only ever ADDS files.
        def moment_zero_files(store):
            return {path: path.read_bytes()
                    for path in store.rglob("*")
                    if path.is_file() and "/c/0/" in str(path).replace("\\", "/")}

        before = {position_id: moment_zero_files(run.position_store(position_id))
                  for position_id in spiral}
        assert all(before.values()), "moment zero wrote no chunk files at all?"

        for number, position_id in enumerate(spiral):
            run.write_and_publish(position_id,
                                  self.coloured_frame(3000 + number * 10),
                                  timepoint=1)

        for position_id in spiral:
            after = moment_zero_files(run.position_store(position_id))
            assert after == before[position_id], (
                f"publishing moment 1 of {position_id} touched moment 0's "
                "files -- a stored unit spanned time, or a write rewrote "
                "published bytes"
            )

        # Both colours, both moments, read back through plain zarr: each kept
        # exactly the pixels it was given, nobody's copy of anybody else's.
        source = zarr.open_array(str(run.position_store(spiral[0]) / "0"),
                                 mode="r")
        assert source.shape[:3] == (2, 2, 1)
        assert set(np.unique(source[0, 0])) == {1000}
        assert set(np.unique(source[0, 1])) == {1001}
        assert set(np.unique(source[1, 0])) == {3000}
        assert set(np.unique(source[1, 1])) == {3001}

    def test_the_record_and_the_walk_agree_moment_by_moment(self, tmp_path):
        from zmart_live.gateway import _LiveRun

        run, width = self.a_two_colour_timelapse(tmp_path)
        spiral = [f"p{row:0{width}d}{column:0{width}d}"
                  for row, column in the_spiral(self.ACROSS)]
        for moment in (0, 1):
            for position_id in spiral:
                run.write_and_publish(position_id,
                                      self.coloured_frame(1000 + moment),
                                      timepoint=moment)

        committed = [(event.position_id, event.timepoint)
                     for event in run.manifest.events()]
        assert committed == ([(one, 0) for one in spiral]
                             + [(one, 1) for one in spiral]), (
            "the manifest's commit order is not the spiral walk repeated "
            "per moment"
        )
        reader = _LiveRun(run.folder)
        published = reader._published_units()
        for position_id in spiral:
            assert (position_id, 0, 0) in published
            assert (position_id, 1, 0) in published

    def test_a_run_with_colours_and_moments_declares_as_a_grown_picture(
        self, tmp_path
    ):
        """The refusals retired the day the grown serving stood its gates.

        A run recording several colours or moments was refused at this
        door — loudly, never a silent collapse — from the day the
        truncation was caught until the combined-axes oracle and the
        browser gates stood (the plan's own condition). Now it declares as
        a picture grown along (t, c), whose every frame the oracle holds
        to its own stamp. The room comes from the sealed profile, so an
        EMPTY run declares with its full grown description too.
        """
        import json

        run, width = self.a_two_colour_timelapse(tmp_path)
        store = declare_a_governed_picture(run.folder / "views" / "empty",
                                           run.folder, name="live")
        described = json.loads((store / "zarr.json").read_text())
        axes = [axis["name"] for axis in
                described["attributes"]["ome"]["multiscales"][0]["axes"]]
        assert axes == ["t", "c", "z", "y", "x"]
        level = json.loads((store / "0" / "zarr.json").read_text())
        assert level["shape"][:2] == [2, 2], (
            "the grown description must carry the profile's (t, c) room"
        )

        # The bake takes the grown room too, one file per (moment, channel)
        # frame -- this used to be a refusal, retired when the per-(t, c)
        # bake landed (its own gates live in
        # test_a_grown_run_is_baked_per_commit; here we only pin that the
        # door is open and leaves the stamp of a finished bake).
        run.write_and_publish(f"p{0:0{width}d}{0:0{width}d}",
                              self.coloured_frame(1000), timepoint=0)
        baked = declare_a_governed_picture(run.folder / "views" / "baked",
                                           run.folder, name="live", bake=True)
        assert (baked / "baked.json").is_file(), (
            "a grown run's bake must finish and stamp itself like a flat one"
        )


# ---------------------------------------------------------------------------
# The growth on screen, under both invalidations
# ---------------------------------------------------------------------------

def _lit_geometry(page, floor: int = 40) -> dict:
    """One photograph of the canvas, distilled to where the light is.

    ``fraction`` is how much of the canvas is lit at all. ``area`` is the
    size of the box around everything lit, and ``centre_offset`` how far
    that box's middle sits from the canvas middle (as a fraction of the
    canvas diagonal). Growth outward around a fixed centre reads as: the
    fraction climbs, the box grows, the offset stays small.
    """
    from PIL import Image

    box = page.locator("canvas").first.bounding_box()
    shot = page.screenshot(clip=box)
    pixels = np.array(Image.open(io.BytesIO(shot)).convert("RGB"))
    lit = pixels.max(axis=2) > floor
    if not lit.any():
        return {"fraction": 0.0, "area": 0.0, "centre_offset": 1.0}
    rows, columns = np.nonzero(lit)
    height, width = lit.shape
    area = float((rows.max() - rows.min() + 1) * (columns.max() - columns.min() + 1))
    centre = ((rows.min() + rows.max()) / 2, (columns.min() + columns.max()) / 2)
    offset = float(np.hypot(centre[0] - height / 2, centre[1] - width / 2)
                   / np.hypot(height, width))
    return {"fraction": float(lit.mean()),
            "area": area / (height * width),
            "centre_offset": offset}



def test_the_spiral_growth_is_visible(browser, built_dist, tmp_path):
    harness.FIXTURES = tmp_path
    run, order = harness.the_run(ACROSS)
    width = len(str(ACROSS - 1))

    def named_for(cell: tuple[int, int]) -> str:
        return f"p{cell[0]:0{width}d}{cell[1]:0{width}d}"

    spiral = the_spiral(ACROSS)
    seeded = [cell for cell in spiral if ring_of(*cell, ACROSS) < SEED_RINGS]
    landing = [cell for cell in spiral if ring_of(*cell, ACROSS) >= SEED_RINGS]
    assert seeded and landing, "the knobs must leave both a centre and a spiral"
    for cell in seeded:
        harness.fast_publish(run, named_for(cell))

    shown = run.folder / "views" / "shown"
    store = declare_a_governed_picture(shown, run.folder, name="live", bake=True)
    pictured = len(json.loads((store / "zarr.json").read_text(
        encoding="utf-8"))["attributes"]["ome"]["multiscales"][0]["datasets"])
    site = Path(os.environ.get("ZMART_STORM_BUILT_DIST", built_dist))
    server = make_server(port=0, data_dir=shown, site_dir=site,
                         store=[store.name], window=harness.BRIGHT, live=True)
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    page = browser.new_page(viewport={"width": 1000, "height": 780})
    try:
        port = server.server_address[1]
        page.add_init_script("globalThis.zmartLiveCheckMs = 150")
        page.goto(f"http://127.0.0.1:{port}",
                  wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartViewer !== undefined",
                               timeout=60_000)
        page.wait_for_function("() => window.zmartSourcesWaiting() === 0",
                               timeout=90_000)
        page.wait_for_timeout(2_000)

        opening = _lit_geometry(page)
        assert opening["fraction"] > 0.005, (
            "the seeded centre never appeared, so growth would be measured "
            "against a black canvas and mean nothing"
        )
        assert opening["centre_offset"] < 0.25, (
            "the seeded block is not in the middle of the screen -- the "
            "spiral's outward growth could not be read from photographs"
        )

        story = [dict(opening, ring="seeded")]
        high_water = opening["fraction"]
        never_regressed = True
        rings = sorted({ring_of(*cell, ACROSS) for cell in landing})
        for ring in rings:
            # No pacing on purpose: outside a deliberate burst test, the
            # spiral fills in as fast as the writer can land -- which is not
            # far past twenty a second anyway, and exactly the cadence the
            # viewer has to keep up with in real acquisition.
            for cell in [one for one in landing
                         if ring_of(*one, ACROSS) == ring]:
                harness.fast_publish(run, named_for(cell))
                _announce(port, _dirty_for(run, pictured, named_for(cell)))
            # The ring has landed; the page now has to show it. Poll until
            # the photograph has both more light and a larger lit box than
            # the previous ring, or fail loudly with the whole story.
            deadline = time.time() + 30
            grown = None
            while time.time() < deadline:
                seen = _lit_geometry(page)
                if seen["fraction"] < high_water - 0.02:
                    never_regressed = False
                high_water = max(high_water, seen["fraction"])
                if (seen["fraction"] >= story[-1]["fraction"] + 0.005
                        and seen["area"] >= story[-1]["area"]):
                    grown = seen
                    break
                page.wait_for_timeout(300)
            assert grown is not None, (
                f"ring {ring} landed but never became visible; "
                f"story so far: {json.dumps(story)}"
            )
            story.append(dict(grown, ring=ring))

        print("SPIRAL GROWTH:", json.dumps({"story": story}),
              flush=True)
        assert never_regressed, (
            "the lit canvas shrank while the spiral was landing -- ground "
            "already on screen went dark during growth, which is exactly "
            "the flicker the invalidation must not show"
        )
        # Outward growth, measured by what CAN move. The lit box is bounded
        # by the fitted viewport -- the seeded block's box already spans much
        # of it -- so the box only has to grow, while the lit FRACTION is the
        # honest magnitude signal (measured here: ~8% seeded to ~52% full),
        # and the centre staying put is what says the growth was outward
        # around the seed rather than a drift.
        assert story[-1]["fraction"] > story[0]["fraction"] * 3, (
            "the lit ground barely grew -- the spiral filled almost nothing "
            "beyond the seeded block"
        )
        assert story[-1]["area"] > story[0]["area"], (
            "the lit region's box never widened -- nothing landed outside "
            "the seeded block's footprint"
        )
        assert story[-1]["centre_offset"] <= story[0]["centre_offset"] + 0.05, (
            "the lit region drifted off the seeded centre -- growth was not "
            "the outward spiral"
        )

        # The record agrees with the walk: what the manifest committed, in
        # order, IS the seeded block followed by the spiral. The screen
        # showed growth; this shows the growth was the spiral.
        committed = [event.position_id for event in run.manifest.events()]
        assert committed == [named_for(cell) for cell in seeded + landing], (
            "the manifest's commit order is not the spiral walk"
        )
    finally:
        page.close()
        server.shutdown()
        serving.join(timeout=5)
