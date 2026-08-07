"""Does the cropped canvas of an overlapping run actually appear on screen?

:mod:`zmart_storage.cropped` writes an overlapping acquisition twice: every tile
whole, in a small image of its own, and every tile trimmed where it meets its
neighbours into one canvas. The whole reason for the second artefact is the viewer — one image draws
quickly where thousands of separate positions do not — so the arrangement is only
worth anything if that one image really draws.

These tests photograph the picture rather than asking the engine about itself,
for the reason ``pixels.py`` sets out at length: a piece of canvas nobody has
written is fetched, decoded and counted as "available" exactly like a written one,
so the engine's own numbers cannot tell a drawn specimen from an empty panel.

Three things are checked, and they are separate questions.

1. **The viewer opens one image, not thousands.** The folder of whole tiles sits
   beside the canvas, and if the viewer picked it up the run would cost exactly
   what the canvas was built to save.
2. **The canvas draws flat**, which is the everyday view.
3. **The canvas draws in the volume.** Nothing in this suite looked at the volume
   at all before — ``HANDOVER_3D.md`` says so plainly — so this is a first
   photograph of it rather than a defence of a known-good state. What it can
   honestly say is whether a specimen appears when the volume is asked for; it
   deliberately does not test rotation, which that same document records as
   measuring no change at all and unrelated to anything here.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import numpy as np
from pixels import assert_something_was_drawn, image_middle
from server import make_server

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from zmart_storage.canvas import Channel
from zmart_storage.cropped import TilesAndCanvas

# An overlapping acquisition small enough to write and open in a few seconds, and
# large enough that the specimen fills a good part of the window.
#
# Eight planes deep rather than two, because a volume draws every plane at once and
# a shallow stack gives a ray almost nothing to accumulate. The tiles overlap by a
# quarter across the specimen and not at all in depth, and a trimmed tile comes to
# 96 voxels, which is exactly one piece of the canvas — the rule
# ``zmart_storage.cropped`` refuses a run for breaking.
TILE = (8, 128, 128)
STEP = (8, 96, 96)
CHUNK = 96
GRID = 4

VOXEL_UM = (2.0, 0.35, 0.35)

# The brightness window the canvas declares, and the range the tiles are drawn in.
# Declaring one means the viewer opens on a sensible picture instead of measuring
# one from the pixels, which keeps these tests about the drawing rather than about
# the brightness measurement.
WINDOW = (0, 4000)


def _a_tile(row: int, column: int) -> np.ndarray:
    """One tile of something that looks like a specimen: dim background, bright blobs.

    The shape of this matters more than it looks, and getting it wrong cost a while
    to work out, so it is worth writing down.

    A volume is shown over a window starting near the **top** of the distribution of
    values — the 99th percentile, in ``backend/contrast.py`` — because a ray passes
    through hundreds of voxels and background that merely looks dim on a single
    plane accumulates into solid fog. That is quite right, and it means a fixture
    made of flat blocks of one value is useless here: if a tenth of the voxels all
    hold the very brightest number, the 99th percentile *is* that number, the window
    collapses to nothing, and the volume opens completely empty. The picture on disk
    would be perfect and the test would be measuring the fixture.

    So this is a smooth thing instead: a dim, slightly uneven background with a
    handful of rounded bright objects in it, different in every tile and different
    from plane to plane. That is also a fair likeness of what a microscope produces,
    which is the other reason to prefer it.
    """
    depth, height, width = TILE
    rng = np.random.default_rng(row * 97 + column)
    z, y, x = np.indices((depth, height, width), dtype=np.float32)

    # A gentle background with a slope across it, so a photograph of the flat view
    # is recognisably a picture and not an even wash.
    picture = 500 + 180 * (y / height) + rng.normal(0, 25, size=(depth, height, width))

    # A handful of rounded objects, placed differently in every tile and leaning
    # through the stack rather than sitting in one plane, so that a ray cast through
    # the volume passes along them and has something to accumulate.
    #
    # They are laid over one another with a maximum rather than added up. Adding
    # would pile two objects into a value above everything else and then flatten
    # against the ceiling, which puts a plateau back at the top of the distribution
    # and empties the volume all over again.
    for _ in range(8):
        at_y = rng.uniform(12, height - 12)
        at_x = rng.uniform(12, width - 12)
        lean_y, lean_x = rng.uniform(-3, 3), rng.uniform(-3, 3)
        spread = rng.uniform(7, 16)
        brightness = rng.uniform(1600, 3500)
        along = (
            (y - (at_y + lean_y * z)) ** 2 + (x - (at_x + lean_x * z)) ** 2
        ) / (2 * spread ** 2)
        picture = np.maximum(picture, brightness * np.exp(-along))
    return picture.astype("uint16")


def _an_overlapping_run(folder: Path) -> TilesAndCanvas:
    """Write a small overlapping raster, both artefacts, and hand it back."""
    run = TilesAndCanvas.create(
        folder,
        name="overview",
        canvas_shape=(
            TILE[0],
            (GRID - 1) * STEP[1] + TILE[1],
            (GRID - 1) * STEP[2] + TILE[2],
        ),
        tile_shape=TILE,
        tile_step=STEP,
        # The raster's own shape, which is what lets the tiles around the outside
        # keep their outer edges instead of losing a border off the whole run.
        tile_grid=(1, GRID, GRID),
        voxel_size_um=VOXEL_UM,
        channels=[Channel("488", window=WINDOW)],
        chunk=CHUNK,
    )
    for row in range(GRID):
        for column in range(GRID):
            run.write(
                _a_tile(row, column),
                origin=(0, row * STEP[1], column * STEP[2]),
                tile_index=(0, row, column),
            )
    run.close()
    return run


# The engine's own account of how far it has got with the view in front of it.
# Trusted for *when* to look and for nothing else, exactly as in
# ``test_canvas_written_live.py``: it says the first draw is finished without making
# any claim about what is in the picture, which leaves the photograph to say that.
_FIRST_DRAW_IS_DONE = """() => {
  let layers = 0, needed = 0, available = 0;
  for (const m of window.zmartViewer.layerManager.managedLayers)
    for (const rl of (m.layer?.renderLayers) || []) {
      layers += 1;
      const p = rl.layerChunkProgressInfo;
      if (p) { needed += p.numVisibleChunksNeeded; available += p.numVisibleChunksAvailable; }
    }
  return layers > 0 && available > 0 && available >= needed;
}"""

# How many separate images the drawing engine was handed. One is the whole point:
# the cost that made this arrangement necessary is paid per image, on every frame.
_HOW_MANY_IMAGES = """() => window.zmartViewer.layerManager.managedLayers
     .filter((m) => m.layer && m.layer.type === 'image')
     .reduce((n, m) => n + m.layer.dataSources.length, 0)"""

# What the engine says about the volume: whether it is really ray-casting, and
# which shader it loaded. Asked alongside the photograph rather than instead of it —
# a shader can be loaded and draw nothing at all.
_VOLUME_STATE = """() => {
  const layer = window.zmartViewer.layerManager.managedLayers[0].layer;
  return {
    mode: window.zmartMode,
    volumeMode: layer.volumeRenderingMode.value,
    shader: layer.fragmentMain.value,
    layout: JSON.stringify(window.zmartViewer.layout.toJSON()),
  };
}"""


def _how_much_is_drawn(page) -> float:
    """The share of the middle of the picture showing specimen rather than nothing.

    Deliberately not the usual "how far is this from one flat colour" measure. A
    canvas covered edge to edge by an even tile is one flat colour just as much as
    an empty panel is, so that measure would score a full screen of specimen and a
    blank screen alike. Counting how much is brighter than the background separates
    them.
    """
    pixels = image_middle(page)
    return float((pixels.max(axis=2) > 40).mean())


def _open_the_viewer(browser, built_dist, folder: Path):
    """A viewer open on the run's canvas, which has finished its first draw."""
    server = make_server(
        port=0, data_dir=folder, site_dir=built_dist,
        store="overview.ome.zarr", live=False,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1000, "height": 800})
    page.goto(f"http://127.0.0.1:{server.server_address[1]}",
              wait_until="domcontentloaded")
    page.wait_for_function("() => window.zmartViewer !== undefined", timeout=60_000)
    page.wait_for_function(_FIRST_DRAW_IS_DONE, timeout=90_000)
    # Having the pieces is a step ahead of having painted with them, and the
    # painting happens on the engine's own schedule rather than ours. The waiting
    # above has already covered the part that takes an unpredictable length of time,
    # so a short settle is enough.
    page.wait_for_timeout(1500)
    return server, thread, page


def test_the_viewer_opens_the_canvas_and_not_the_archive(browser, built_dist, tmp_path):
    """One image reaches the engine, however many tiles the run gathered.

    The folder of whole tiles sits in the run's folder beside the canvas. If the
    viewer treated those as images too, a run of ten thousand tiles would hand the
    engine ten thousand images — which is exactly the cost the canvas exists to
    remove, so the arrangement would have bought nothing at all.
    """
    run = tmp_path / "run"
    _an_overlapping_run(run)
    server, thread, page = _open_the_viewer(browser, built_dist, run)
    try:
        images = page.evaluate(_HOW_MANY_IMAGES)
        assert images == 1, (
            f"the engine was handed {images} images for a run of {GRID * GRID} "
            "overlapping tiles, and it should have been handed the one canvas"
        )
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def test_the_cropped_canvas_draws_flat(browser, built_dist, tmp_path):
    """The everyday view: the trimmed tiles are on screen as one picture."""
    run = tmp_path / "run"
    _an_overlapping_run(run)
    server, thread, page = _open_the_viewer(browser, built_dist, run)
    try:
        spread = assert_something_was_drawn(page, "the cropped canvas")
        lit = _how_much_is_drawn(page)
        assert lit > 0.2, (
            "the cropped canvas of a fully imaged raster barely lit the middle of "
            f"the window: {lit:.3f}. The picture is on disk, so this is the viewer "
            "not drawing it."
        )
        print(f"\n  flat: {lit:.0%} of the middle lit, colour spread {spread}")
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def _in_the_volume(browser, built_dist, folder: Path) -> tuple[float, float]:
    """Open the run, look at it flat, switch to the volume, and look again.

    Returns how much of the middle of the window was lit in each view.
    """
    server, thread, page = _open_the_viewer(browser, built_dist, folder)
    try:
        flat = _how_much_is_drawn(page)
        page.click("text=3D")
        # A volume is far more work than a plane, and on a machine with no graphics
        # card the first frames of one take a while. This waits on the clock rather
        # than on the engine because the engine reports itself content well before
        # the ray-casting has actually painted anything.
        page.wait_for_timeout(6000)

        state = page.evaluate(_VOLUME_STATE)
        assert state["mode"] == "volume", (
            f"the viewer did not switch to the volume: {state['mode']}"
        )
        assert state["volumeMode"] == 1, (
            "the engine is not ray-casting, so whatever is on screen is still a "
            "single plane"
        )
        assert "emitRGBA" in state["shader"], (
            "a volume shader has to emit alpha, or a ray accumulates nothing"
        )
        return flat, _how_much_is_drawn(page)
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def test_the_cropped_canvas_draws_in_the_volume(browser, built_dist, tmp_path):
    """The same canvas, ray-cast rather than sliced.

    Two things have to be true and they fail in different ways. The engine has to
    genuinely enter volume rendering — a misspelled property leaves you looking at
    a single plane and wondering — and a specimen has to appear once it has. The
    second is asked of the pixels, because a shader that emits no alpha loads
    perfectly happily and accumulates nothing.

    **The same canvas with nothing written into it is looked at as well**, and that
    control is doing most of the work here. A volume shows far less of the window
    than a plane does, by design: the brightness window for a volume starts near the
    top of the distribution, so that background does not accumulate into fog along
    every ray. Only a few per cent of the window is expected to light up, which is
    too little to assert against on its own — an empty view would be within reach of
    a generous threshold. Measuring an empty canvas the same way says what "nothing
    at all" really looks like, and the imaged run has to be plainly above it.

    What this deliberately does not test is rotation. ``HANDOVER_3D.md`` records a
    plain drag in a volume as measuring no change at all, and that is a fault in how
    the engine's own bindings are attached rather than anything to do with how a run
    is written — so testing it here would only add a failure that says nothing about
    this arrangement.
    """
    imaged = tmp_path / "run"
    _an_overlapping_run(imaged)
    flat, volume = _in_the_volume(browser, built_dist, imaged)

    # The same canvas, declared exactly the same way and never written to.
    empty = tmp_path / "empty"
    TilesAndCanvas.create(
        empty,
        name="overview",
        canvas_shape=(
            TILE[0],
            (GRID - 1) * STEP[1] + TILE[1],
            (GRID - 1) * STEP[2] + TILE[2],
        ),
        tile_shape=TILE,
        tile_step=STEP,
        tile_grid=(1, GRID, GRID),
        voxel_size_um=VOXEL_UM,
        channels=[Channel("488", window=WINDOW)],
        chunk=CHUNK,
    ).close()
    _, nothing = _in_the_volume(browser, built_dist, empty)

    print(f"\n  flat: {flat:.1%} of the middle lit"
          f"\n  volume: {volume:.1%}"
          f"\n  volume of an empty canvas: {nothing:.1%}")

    assert nothing < 0.005, (
        f"a canvas nothing was written to lit {nothing:.1%} of the volume, so this "
        "measurement cannot tell a drawn specimen from an empty one"
    )
    assert volume > 0.01, (
        f"the volume view of the cropped canvas is empty: {volume:.1%} of the middle "
        f"lit, against {flat:.1%} flat. The same data draws flat, so this is the "
        "volume rather than the run."
    )
    assert volume > nothing + 0.01, (
        f"the volume of an imaged canvas ({volume:.1%}) is no fuller than the volume "
        f"of an empty one ({nothing:.1%}), so nothing of the specimen reached the "
        "ray-casting"
    )
