"""Does a run written by `zmart_storage` actually appear in the viewer, as it goes?

Everything in the storage decision rests on this working, so it is checked against
the real writer and against the picture on screen — not against what the engine
says about itself.

That distinction matters more than it sounds. A piece of canvas nobody has written
is decoded, held and counted as "available" exactly like a written one, so the
engine's own count of loaded pieces does not move when a tile lands. A test
watching that number would report everything fine while the screen stayed empty.
So these tests photograph the picture and measure how far it is from being one
flat colour.

Three things are checked, and the arrangement is only usable if all three hold:

1. **The canvases start empty and look empty.** Without this the rest would pass on
   a store that was never blank.
2. **Each tile appears as it is written**, one after another, into canvases the
   viewer has been holding open all along.
3. **Several canvases update independently** — one per acquisition type, which is
   the shape a run actually has.

There is one thing a run must do for any of this to work, and it is not obvious.
Nothing on disk changes when a tile lands inside a store that is already open:
same store, same name, same declared shape. The engine has already decoded the
emptiness that was there before, remembers it with no time limit, and will never
ask the disk again. So the run has to say that it wrote in place. That is what
`wrote_image_in_place` is for, and a test below fails without it.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pixels import colour_spread, image_middle
from server import make_server

from zmart_storage.canvas import Channel, TileCanvases

# A canvas a quarter of which one tile fills, so a landing is plainly visible in a
# photograph rather than being a few pixels somebody has to squint at.
CANVAS = (4, 1024, 1024)
TILE = (4, 256, 256)
CHUNK, LEVELS = 128, 2

# What a run says once it has written a tile into a canvas the viewer already holds.
# The flag is the whole point: it says the image landed somewhere already looked at,
# which is the one thing re-reading the store's description cannot reveal.
ANNOUNCE_IN_PLACE = """async () => {
  const response = await fetch('/api/announce', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({reason: 'a tile was written', wrote_image_in_place: true}),
  });
  return (await response.json()).told;
}"""


def _a_canvas(folder: Path, name: str) -> TileCanvases:
    """One acquisition type's image, declared empty at the start of a run."""
    return TileCanvases.create(
        folder,
        name=name,
        canvas_shape=CANVAS,
        tile_shape=TILE,
        tile_step=TILE,  # butted up, which is the rule
        voxel_size_um=(2.0, 0.35, 0.35),
        channels=[Channel("488", window=(0, 4000))],
        chunk=CHUNK,
        levels=LEVELS,
    )


def _a_tile() -> np.ndarray:
    """A tile with structure in it, so it cannot be mistaken for a flat fill."""
    z, y, x = TILE
    ramp = np.linspace(600, 3800, x, dtype=np.float32)
    plane = np.tile(ramp, (y, 1))
    plane[::16, :] = 3900
    return np.broadcast_to(plane, (z, y, x)).astype("uint16")


def _how_much_is_drawn(page) -> float:
    """The share of the middle of the picture showing specimen rather than nothing.

    Deliberately *not* the usual "how far is this from being one flat colour"
    measure. That one answers "is the panel blank", which is a different question
    and gives the wrong answer here: a canvas filled edge to edge with an even
    tile is one flat colour just as much as an empty panel is, so it would score
    a full screen of specimen and a blank screen exactly alike.

    Counting how much is brighter than the background separates them, and it
    rises steadily as tiles land, which is what these tests need to watch.

    Also deliberately not a count of pieces the engine says it holds: a piece of
    canvas nobody has written is decoded and counted exactly like a written one,
    so that number does not move when a tile lands.
    """
    pixels = image_middle(page)
    return float((pixels.max(axis=2) > 40).mean())


def _open_the_viewer(browser, built_dist, folder: Path, store: str):
    server = make_server(port=0, data_dir=folder, site_dir=built_dist,
                         store=store, live=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1000, "height": 800})
    page.goto(f"http://127.0.0.1:{server.server_address[1]}",
              wait_until="domcontentloaded")
    page.wait_for_function("() => window.zmartViewer !== undefined", timeout=60_000)
    page.wait_for_timeout(3000)
    return server, thread, page


def test_a_canvas_written_by_the_writer_starts_empty_and_fills_in(
    browser, built_dist, tmp_path
):
    """A run's tiles appear one after another, into a canvas held open throughout.

    This is the whole arrangement in one test: the writer declares an empty canvas,
    the viewer opens on it, and then tiles land while somebody is watching.
    """
    run = tmp_path / "run"
    canvas = _a_canvas(run, "overview")
    server, thread, page = _open_the_viewer(browser, built_dist, run,
                                            "overview.ome.zarr")
    try:
        # The control. Without it, everything below would pass on a canvas that was
        # never blank in the first place.
        assert colour_spread(image_middle(page))["distinct"] <= 2, (
            "the canvas was meant to start empty, so the picture should be flat"
        )

        drawn = [_how_much_is_drawn(page)]
        landings = []
        places = [(1, 1), (1, 2), (2, 1), (2, 2)]
        for number, (row, col) in enumerate(places, start=1):
            began = time.perf_counter()
            canvas.write(_a_tile(), origin=(0, row * TILE[1], col * TILE[2]),
                         tile_index=(0, row, col))
            told = page.evaluate(ANNOUNCE_IN_PLACE)
            assert told >= 1, f"the page was not listening when tile {number} landed"
            page.wait_for_timeout(2500)
            landings.append(time.perf_counter() - began)
            drawn.append(_how_much_is_drawn(page))

        # Not assert_something_was_drawn here: it asks whether the panel is a flat
        # colour, and a canvas covered by an even tile is flat too. What says the
        # specimen arrived is that more of the middle is lit than before.
        assert drawn[-1] > drawn[0] + 0.05, (
            f"the picture barely changed as four tiles landed: {drawn}"
        )
        # Each landing should add to the picture rather than the first one doing all
        # the work -- that is what says the viewer keeps noticing rather than
        # settling into what it decoded early on.
        assert drawn[2] > drawn[1], (
            f"the second tile did not add anything: {drawn}"
        )
        print(f"\n  how much is drawn, tile by tile: "
              f"{', '.join(f'{d:.2f}' for d in drawn)}")
        print(f"  seconds per landing: "
              f"{', '.join(f'{s:.1f}' for s in landings)}")
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def test_several_canvases_update_on_the_fly_independently(
    browser, built_dist, tmp_path
):
    """One image per acquisition type, all open at once, each growing on its own.

    This is the shape a run actually has -- an overview and a target scan, say --
    and it is the arrangement the whole storage decision assumes. A tile landing in
    one must appear without disturbing the other.
    """
    run = tmp_path / "run"
    overview = _a_canvas(run, "overview")
    targetscan = _a_canvas(run, "targetscan")
    server, thread, page = _open_the_viewer(browser, built_dist, run,
                                            "overview.ome.zarr")
    try:
        assert colour_spread(image_middle(page))["distinct"] <= 2, (
            "both canvases were meant to start empty"
        )
        # Both images should be open, since the viewer was pointed at the folder.
        sources = page.evaluate(
            """() => window.zmartViewer.layerManager.managedLayers
                 .filter((m) => m.layer && m.layer.type === 'image')
                 .reduce((n, m) => n + m.layer.dataSources.length, 0)"""
        )
        assert sources >= 2, (
            f"expected an image open for each acquisition type, found {sources}"
        )

        empty = _how_much_is_drawn(page)

        overview.write(_a_tile(), origin=(0, TILE[1], TILE[2]), tile_index=(0, 1, 1))
        assert page.evaluate(ANNOUNCE_IN_PLACE) >= 1
        page.wait_for_timeout(2500)
        after_overview = _how_much_is_drawn(page)
        assert after_overview > empty + 0.02, (
            f"the overview's tile did not appear: {empty:.3f} -> {after_overview:.3f}"
        )

        targetscan.write(_a_tile(), origin=(0, 2 * TILE[1], 2 * TILE[2]),
                         tile_index=(0, 2, 2))
        assert page.evaluate(ANNOUNCE_IN_PLACE) >= 1
        page.wait_for_timeout(2500)
        after_target = _how_much_is_drawn(page)
        assert after_target > after_overview, (
            "the target scan's tile did not appear alongside the overview's: "
            f"{after_overview:.3f} -> {after_target:.3f}"
        )
        print(f"\n  empty {empty:.3f} -> overview {after_overview:.3f} "
              f"-> plus targetscan {after_target:.3f}")
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def test_without_saying_it_wrote_in_place_the_tile_stays_invisible(
    browser, built_dist, tmp_path
):
    """The trap this arrangement has to be built around, pinned so it stays known.

    Nothing on disk changes when a tile lands inside an open canvas, so the engine
    has no reason to look again — it decoded the emptiness earlier and remembers it
    for as long as the page is open. An ordinary announcement is not enough.

    If this test ever starts failing, that is good news and means the engine grew a
    way of noticing on its own. It should be read, not simply deleted.
    """
    run = tmp_path / "run"
    canvas = _a_canvas(run, "overview")
    server, thread, page = _open_the_viewer(browser, built_dist, run,
                                            "overview.ome.zarr")
    try:
        before = _how_much_is_drawn(page)
        canvas.write(_a_tile(), origin=(0, TILE[1], TILE[2]), tile_index=(0, 1, 1))
        page.evaluate(
            """async () => {
              await fetch('/api/announce', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({reason: 'a tile was written'}),
              });
            }"""
        )
        page.wait_for_timeout(2500)
        assert _how_much_is_drawn(page) == pytest.approx(before, abs=0.01), (
            "the tile appeared without the run saying it wrote in place -- welcome, "
            "but it means this test no longer describes the engine"
        )
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


# -- more than one colour, and more than one moment ---------------------------

MOVE_IN_TIME = """(frame) => {
  const nav = window.zmartViewer.navigationState.position;
  const space = nav.coordinateSpace.value;
  const at = space.names.indexOf('t');
  if (at < 0) return null;
  const where = Array.from(nav.value);
  where[at] = frame + 0.5;
  nav.value = Float32Array.from(where);
  return space.names;
}"""


def test_each_channel_is_its_own_row_and_fills_in_on_its_own(
    browser, built_dist, tmp_path
):
    """Two colours in one canvas, each drawn separately and each updating live.

    A canvas holds its channels inside one array rather than in separate folders,
    so what tells them apart is the ``omero`` block the writer puts in the store's
    description. If that were wrong the viewer would show one channel and silently
    hide the other, which has happened here before on real data.
    """
    run = tmp_path / "run"
    canvas = TileCanvases.create(
        run, name="overview", canvas_shape=CANVAS,
        tile_shape=TILE, tile_step=TILE,
        voxel_size_um=(2.0, 0.35, 0.35),
        channels=[Channel("488", window=(0, 4000)),
                  Channel("561", window=(0, 4000))],
        chunk=CHUNK, levels=LEVELS,
    )
    server, thread, page = _open_the_viewer(browser, built_dist, run,
                                            "overview.ome.zarr")
    try:
        rows = page.evaluate(
            """() => window.zmartViewer.layerManager.managedLayers
                 .filter((m) => m.layer && m.layer.type === 'image')
                 .map((m) => m.name)"""
        )
        assert len(rows) == 2, (
            f"expected a row for each colour the canvas declares, got {rows}"
        )
        assert any("488" in name for name in rows) and any("561" in name for name in rows), (
            f"the rows are not named after the channels in the description: {rows}"
        )

        drawn = [_how_much_is_drawn(page)]
        for channel, (row, col) in enumerate([(1, 1), (2, 2)]):
            canvas.write(_a_tile(), origin=(0, row * TILE[1], col * TILE[2]),
                         channel=channel, tile_index=(0, row, col))
            assert page.evaluate(ANNOUNCE_IN_PLACE) >= 1
            page.wait_for_timeout(2500)
            drawn.append(_how_much_is_drawn(page))

        assert drawn[1] > drawn[0] + 0.02, (
            f"the first channel's tile did not appear: {drawn}"
        )
        assert drawn[2] > drawn[1] + 0.02, (
            f"the second channel's tile did not appear: {drawn}"
        )
        print(f"\n  two channels, drawn: {', '.join(f'{d:.2f}' for d in drawn)}")
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def test_a_timepoint_written_later_can_be_reached_and_is_seen(
    browser, built_dist, tmp_path
):
    """A canvas that keeps several moments, filled in one after another.

    The hazard this is really about: the engine remembers that a frame was empty
    when it looked too early, with no time limit, and will not look again. So a
    frame written after the viewer opened is exactly the case that can be on disk
    and yet refuse to appear. Moving to it and finding it there is the check.
    """
    run = tmp_path / "run"
    canvas = TileCanvases.create(
        run, name="overview", canvas_shape=CANVAS,
        tile_shape=TILE, tile_step=TILE,
        voxel_size_um=(2.0, 0.35, 0.35),
        channels=[Channel("488", window=(0, 4000))],
        frames=3, chunk=CHUNK, levels=LEVELS,
    )
    server, thread, page = _open_the_viewer(browser, built_dist, run,
                                            "overview.ome.zarr")
    try:
        names = page.evaluate(
            "() => window.zmartViewer.navigationState.coordinateSpace.value.names"
        )
        assert "t" in names, (
            f"a canvas declaring several moments should have a time axis: {names}"
        )

        # Look at the last moment before anything has been written to it, which is
        # what makes this a real test: the engine now believes that frame is empty.
        page.evaluate(MOVE_IN_TIME, 2)
        page.wait_for_timeout(2000)
        assert _how_much_is_drawn(page) == 0.0, "nothing has been written yet"

        # Now fill that moment in, and go back to it.
        canvas.write(_a_tile(), origin=(0, TILE[1], TILE[2]), frame=2,
                     tile_index=(0, 1, 1))
        assert page.evaluate(ANNOUNCE_IN_PLACE) >= 1
        page.wait_for_timeout(3000)
        page.evaluate(MOVE_IN_TIME, 2)
        page.wait_for_timeout(2500)
        late = _how_much_is_drawn(page)
        assert late > 0.02, (
            "a moment written after the viewer had already looked at it stayed "
            f"empty on screen: {late:.3f}"
        )

        # And an earlier moment, written afterwards, is still its own picture --
        # frames must not bleed into one another.
        page.evaluate(MOVE_IN_TIME, 0)
        page.wait_for_timeout(2500)
        assert _how_much_is_drawn(page) == pytest.approx(0.0, abs=0.02), (
            "a moment nothing was written to is showing another moment's image"
        )
        print(f"\n  a late frame reached and drawn: {late:.2f}")
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


@pytest.mark.xfail(
    reason="the viewer still gathers every image in a folder into one row, as "
           "though they were positions of a single acquisition. Both are drawn "
           "now that unimaged ground is transparent, but they share one row's "
           "contrast, colour and visibility -- so an overview and a target scan "
           "cannot be adjusted apart. Grouping in stores.py assumes a folder of "
           "positions and has to learn that one image can be an acquisition type.",
    strict=True,
)
def test_each_acquisition_type_gets_a_row_of_its_own(browser, built_dist, tmp_path):
    """An overview and a target scan are different things and want separate controls.

    Being visible is not the same as being separable. This is what the panel has to
    show before "one image per acquisition type" is really true on screen.
    """
    run = tmp_path / "run"
    _a_canvas(run, "overview")
    _a_canvas(run, "targetscan")
    server, thread, page = _open_the_viewer(browser, built_dist, run,
                                            "overview.ome.zarr")
    try:
        rows = page.evaluate(
            """() => window.zmartViewer.layerManager.managedLayers
                 .filter((m) => m.layer && m.layer.type === 'image')
                 .map((m) => m.name)"""
        )
        assert len(rows) == 2, (
            f"expected a row for the overview and one for the target scan, got {rows}"
        )
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)
