"""Does the picture face the same way the specimen does?

Every other test that looks at pixels asks whether *something* was drawn, or
whether two tiles landed the right distance apart. None of them asks the
simplest question an operator would ask without thinking: **is what I am looking
at a picture of the specimen, or a mirror image of it?**

That question went unasked for months, and the answer was "a mirror image". The
flat view ran the specimen's width axis towards the *left* of the screen, so the
picture was flipped end for end. Nothing errors when that happens. On a round
embryo, on a symmetrical multi-well plate, on anything that looks much the same
either way round, there is nothing at all to notice. But an operator who picks
out a well on the left of the screen and sends the stage to it sends it to the
well on the other side of the plate, and every measurement they take off the
picture is taken off something that is not their specimen.

So this file measures which way round the picture is, from the picture itself.

**The specimen used is deliberately lopsided.** A small acquisition is written
whose brightness climbs steadily along its own width axis — dim where the width
coordinate is smallest, bright where it is largest. Which end of that ramp is dim
and which is bright is settled by the order the numbers sit in the file, and no
reading of any coordinate, transform or axis order can change it. So when the
picture is photographed, the side the bright end is drawn on says, with nothing
else involved, which way the specimen's width axis runs on screen. It is written
twice over, once as a still and once as a short recording with a time axis in
front of everything, because the viewer picks the axes it draws by their unit and
a recording gives it a different list to pick from.

Two things are then checked, and they are genuinely different questions:

1. **The specimen's width runs to the right.** The picture must get brighter
   towards the right of the screen. This is the mirror itself, and it is the only
   one of the two that can find it.
2. **The picture follows the hand.** Dragging by a known number of pixels moves
   the picture by the same number of pixels in the same direction.

The second is worth saying more about, because it is the check most people would
reach for first and **it cannot find this fault.** The engine pans using the same
axis mapping it draws with, so the picture follows the hand pixel for pixel
whichever way round it has been drawn: measured here at a slope of +1.00 both
before the mirror was put right and after. It is kept because a view that slides
against the hand is unusable, and because having it here means the mirror can
never be quietly "fixed" by reversing the pan gesture instead — that would make
dragging feel normal while leaving the picture just as reflected as it was.

Both readings come out of screenshots. Nothing here asks the engine where it
thinks anything is: that is the very thing under test, and a viewer that had the
axes the wrong way round would describe its own mistake to us perfectly
consistently. The engine is asked one question only — whether it has finished
fetching what the first view needs — which decides *when* it is fair to take the
photograph and makes no claim about what is in it.
"""

from __future__ import annotations

import io
import json
import threading
from pathlib import Path

import numpy as np
import pytest
from measure_the_frame_rate_of_a_linked_view import (  # noqa: E402
    EVERY_SOURCE_RESOLVED,
)
from server import make_server

# The little acquisition this file draws. It is one plane of one channel, a few
# hundred voxels across, at half a micrometre to a voxel — big enough to fill a
# good part of the panel and small enough to write in a moment.
SIDE = 256
VOXEL_UM = (2.0, 0.5, 0.5)

# The intensity window the store declares, and the two ends of the ramp. The
# format lets a store say how it would like to be displayed and the viewer
# honours that, so these come out at predictable shades: the dim end lands about
# a third of the way up the grey scale and the bright end saturates to white.
# A wide, empty gap between them is what makes "which end is this?" a safe
# question to ask of a screenshot.
WINDOW = (0, 4000)
DIM = 1300
BRIGHT = 3900

# The level below which a pixel counts as unimaged ground rather than specimen.
# The same floor the rest of the suite uses — well above the near-black of an
# empty region and well below any real signal — so nothing here depends on
# exactly where it sits.
GROUND = 40


def write_a_lopsided_acquisition(store: Path, *, moments: int = 0) -> Path:
    """Write one small OME-Zarr store that gets brighter along its width axis.

    The plane is filled with a ramp running along the axis the store declares
    last, which is the one called ``x``: the first voxel of every row is dim and
    the last is bright. That asymmetry is the whole point of the store, because
    it is the one fact about the picture that survives every coordinate
    transform — it is simply the order the numbers were written in.

    ``moments`` writes the same picture as a short recording instead of a single
    still, with a time axis declared in front of everything else. That case is
    here because the axes drawn on screen are picked out of the declared list by
    their unit, so an image with a time axis has a different list to pick from —
    and getting that wrong once already cost this viewer a black screen on every
    timelapse. A recording must face the same way a still does.

    The files are written by hand rather than through the zarr library, in the
    same style as ``test_tiles_are_placed_correctly.py``: a handful of short
    files are quicker and much more direct to read than persuading a library to
    emit exactly this description.

    Returns the path to the store it wrote.
    """
    level = store / "0"
    level.mkdir(parents=True, exist_ok=True)
    (store / ".zgroup").write_text('{"zarr_format": 2}', encoding="utf-8")
    # A still is one channel of one plane; a recording is the same thing at
    # several moments, with time in front. Everything after the time axis is
    # identical, which is the point of the comparison.
    shape = ([moments] if moments else []) + [1, 1, SIDE, SIDE]
    chunks = ([1] if moments else []) + [1, 1, SIDE, SIDE]
    (level / ".zarray").write_text(
        json.dumps(
            {
                "zarr_format": 2,
                "shape": shape,
                "chunks": chunks,
                "dtype": "<u2",
                "compressor": None,
                "fill_value": 0,
                "order": "C",
                "filters": None,
                "dimension_separator": ".",
            }
        ),
        encoding="utf-8",
    )
    across = np.linspace(DIM, BRIGHT, SIDE)
    plane = np.tile(across, (SIDE, 1)).astype("<u2")
    for moment in range(moments or 1):
        piece = ([str(moment)] if moments else []) + ["0", "0", "0", "0"]
        (level / ".".join(piece)).write_bytes(plane.tobytes())
    # The axes the store declares, and one number per axis for how big a step
    # along it is. Time and channel have no size worth speaking of, so they get a
    # one; the three that measure distance get the voxel size in micrometres.
    axes = [{"name": "c", "type": "channel"}] + [
        {"name": name, "type": "space", "unit": "micrometer"}
        for name in ("z", "y", "x")
    ]
    step = [1.0, *VOXEL_UM]
    if moments:
        axes.insert(0, {"name": "t", "type": "time", "unit": "second"})
        step.insert(0, 1.0)
    (store / ".zattrs").write_text(
        json.dumps(
            {
                "multiscales": [
                    {
                        "version": "0.4",
                        "axes": axes,
                        "datasets": [
                            {
                                "path": "0",
                                "coordinateTransformations": [
                                    {"type": "scale", "scale": step},
                                    {
                                        "type": "translation",
                                        "translation": [0.0] * len(axes),
                                    },
                                ],
                            }
                        ],
                    }
                ],
                "omero": {
                    "channels": [
                        {
                            "label": "ch0",
                            "color": "FFFFFF",
                            "window": {
                                "min": 0,
                                "max": 65535,
                                "start": WINDOW[0],
                                "end": WINDOW[1],
                            },
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    return store


# The engine's own account of how far it has got with the view in front of it.
# This is the one question asked of the engine anywhere in this file, and it is
# one the engine can answer honestly because it makes no claim about what is in
# the picture. A viewer that has not drawn yet looks exactly like a viewer that
# drew nothing, so photographing too early would give an answer that is wrong in
# the most convincing possible way.
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


@pytest.fixture(scope="module", params=["a still", "a recording"])
def lopsided_page(request, browser, built_dist, tmp_path_factory):
    """A viewer open on the lopsided acquisition, finished drawing it.

    Everything here is run twice: once on a single still, and once on the same
    picture declared as a short recording with a time axis in front of it. The
    two are worth keeping apart because the viewer picks the axes it draws out of
    the declared list by their unit, so a recording hands it a different list —
    and a fault in that picking once left every timelapse black while the data on
    disk was perfectly good. A recording has to face the same way a still does.

    Module-scoped because opening the page is by far the slowest part of this
    file and every test wants the same starting picture. The drag test puts the
    view back where it found it when it is done, so no test can hand another a
    view that has been moved.
    """
    moments = 3 if request.param == "a recording" else 0
    folder = tmp_path_factory.mktemp("lopsided")
    write_a_lopsided_acquisition(
        folder / "overview_pos00000.ome.zarr", moments=moments
    )
    server = make_server(
        port=0,
        data_dir=folder,
        site_dir=built_dist,
        store=["overview_pos00000.ome.zarr"],
        live=False,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1200, "height": 900})
    page.goto(
        f"http://127.0.0.1:{server.server_address[1]}", wait_until="domcontentloaded"
    )
    page.wait_for_function("() => window.zmartViewer !== undefined", timeout=60_000)
    page.wait_for_function("() => window.zmartSourcesWaiting() === 0", timeout=90_000)
    # A mirroring check run before the picture has arrived is a check of nothing.
    page.wait_for_function(EVERY_SOURCE_RESOLVED, timeout=300_000)
    page.wait_for_function(_FIRST_DRAW_IS_DONE, timeout=90_000)
    # Holding the pieces is a step ahead of having painted with them, and the
    # painting happens on the engine's own schedule rather than ours. A short
    # settle covers that gap.
    page.wait_for_timeout(2000)
    # Step back from the opening fit. The viewer opens on the whole picture
    # sized to the window, which for a one-tile acquisition means the specimen
    # runs to the edges of the photographed field and beyond -- and a centre of
    # mass measured on a specimen the crop is clipping under-reports every
    # movement. Three times further out leaves the whole specimen comfortably
    # inside the field, which is the condition every reading below relies on.
    # This sets the view rather than asking about the picture, the same kind of
    # act as the dragging the tests below do.
    page.evaluate("window.zmartViewer.navigationState.zoomFactor.value *= 3")
    page.wait_for_timeout(700)
    try:
        yield page
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


# How much of the drawing surface to photograph, as fractions of its width and
# height. The viewer draws its own controls on top of the image — the 2D/3D
# buttons top left, the scale bar top right, the depth slider down the right-hand
# edge — and every one of them is bright enough to be mistaken for specimen.
# Trimming those edges away leaves a field holding nothing but what the engine
# drew. The trim is symmetrical left and right on purpose: this file is about
# which side of the picture things are on, and an uneven crop would put a bias
# into exactly the measurement being made.
_KEEP = {"left": 0.10, "right": 0.86, "top": 0.15, "bottom": 0.85}


def the_drawing(page) -> np.ndarray:
    """The picture the engine drew, as a height by width array of brightness.

    One number per pixel rather than three, because the specimen is drawn in
    shades of grey and the brightest of the three colour channels summarises it
    faithfully. Working with one number keeps the measurements below easy to
    read.
    """
    from PIL import Image

    canvas = page.locator("canvas").first.bounding_box()
    shot = page.screenshot(
        clip={
            "x": canvas["x"] + canvas["width"] * _KEEP["left"],
            "y": canvas["y"] + canvas["height"] * _KEEP["top"],
            "width": canvas["width"] * (_KEEP["right"] - _KEEP["left"]),
            "height": canvas["height"] * (_KEEP["bottom"] - _KEEP["top"]),
        }
    )
    return np.array(Image.open(io.BytesIO(shot)).convert("RGB")).max(axis=2)


def brightness_along_the_picture(picture: np.ndarray) -> np.ndarray:
    """The average brightness of each column that has specimen in it.

    Columns holding nothing but unimaged ground are left out rather than counted
    as dark, because they would drag the average down at whichever side of the
    picture the specimen happens not to reach, and that is a fact about where the
    view is centred rather than about which way round the specimen is.
    """
    lit = picture > GROUND
    counts = lit.sum(axis=0)
    totals = np.where(lit, picture, 0).sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(counts > 0, totals / np.maximum(counts, 1), np.nan)


def which_way_the_ramp_runs(picture: np.ndarray) -> dict:
    """How fast the picture brightens from left to right, and by how much overall.

    The slope is a straight line fitted through the brightness of each column
    against how far along the picture that column is, in units of grey levels per
    hundred pixels. Positive means the picture gets brighter towards the right,
    which is where the specimen's width axis should run. Negative means the
    picture is a mirror image of the specimen.

    The difference between the two halves is reported alongside it. It says the
    same thing far more bluntly, and having both means a failure message can show
    that the answer does not rest on the fit.
    """
    profile = brightness_along_the_picture(picture)
    columns = np.arange(len(profile), dtype=float)
    usable = ~np.isnan(profile)
    if usable.sum() < 20:
        return {"found": False, "lit_columns": int(usable.sum())}
    slope = float(np.polyfit(columns[usable], profile[usable], 1)[0])
    middle = len(profile) / 2
    left = profile[usable & (columns < middle)]
    right = profile[usable & (columns >= middle)]
    return {
        "found": True,
        "lit_columns": int(usable.sum()),
        "grey_levels_per_100_px": round(slope * 100, 2),
        "left_half_averages": round(float(left.mean()), 1),
        "right_half_averages": round(float(right.mean()), 1),
        "right_minus_left": round(float(right.mean() - left.mean()), 1),
    }


def where_the_specimen_sits(picture: np.ndarray) -> float:
    """Which column the specimen is centred on, on average.

    Adding up the positions of every pixel with something in it and dividing by
    how many there were gives one number for "whereabouts across the picture is
    the specimen". Following that one number as the view is dragged is what turns
    "the picture moved" into a measurement.
    """
    lit = picture > GROUND
    assert lit.any(), "asked where the specimen is when nothing was drawn"
    columns = np.arange(picture.shape[1], dtype=float)
    return float((lit.sum(axis=0) * columns).sum() / lit.sum())


def drag_across(page, by: float) -> None:
    """Drag the picture sideways by ``by`` screen pixels, and let it settle.

    The drag is made in small steps rather than one jump because that is what a
    hand does, and because a single large step can be treated as a click that
    happened to move. It starts from the middle of the panel so that the whole
    specimen stays comfortably inside the photographed field throughout.
    """
    panel = page.locator(".neuroglancer-panel").first.bounding_box()
    x = panel["x"] + panel["width"] / 2
    y = panel["y"] + panel["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    for step in range(1, 11):
        page.mouse.move(x + by * step / 10, y)
    page.mouse.up()
    page.wait_for_timeout(700)


def test_the_specimen_is_not_drawn_as_its_own_mirror_image(lopsided_page):
    """The specimen's width axis runs to the right of the screen, not to the left.

    The acquisition on screen was written dim at its first voxel along width and
    bright at its last. So if the picture brightens towards the right, width runs
    rightwards and the picture is the right way round; if it brightens towards the
    left, the operator is looking at a mirror image of their specimen.

    This is a real fault the viewer had, and the reason it survived so long is
    that there is nothing to see. The picture is bright, detailed and completely
    convincing either way round. Only a specimen that is deliberately lopsided —
    like this one — can tell you which of the two you are looking at.
    """
    picture = the_drawing(lopsided_page)
    reading = which_way_the_ramp_runs(picture)
    assert reading["found"], (
        "the specimen was not drawn, so there is no ramp to read a direction "
        f"from: {reading}"
    )
    print(f"\n  the ramp across the picture: {reading}")
    assert reading["grey_levels_per_100_px"] > 0, (
        "the picture gets *darker* towards the right, so the specimen is drawn "
        "mirrored left to right. The acquisition on screen was written dim at its "
        "first voxel along width and bright at its last, so the bright end must "
        "appear on the right. An operator reading this picture would pick out the "
        "well on the wrong side of their plate, and every position they took off "
        f"it would be reflected: {reading}"
    )
    assert reading["right_minus_left"] > 5, (
        "the two halves of the picture are about equally bright, so the ramp "
        "cannot say which way round the specimen is drawn and this test is not "
        f"measuring anything: {reading}"
    )


@pytest.mark.parametrize("by", [-120, 120])
def test_the_picture_moves_the_way_the_hand_moves(lopsided_page, by):
    """Drag the picture one way and it goes that way, by the same amount.

    This is the half of facing the right way that an operator feels rather than
    sees. Dragging is how anybody moves around a picture, and a viewer in which
    the image slides the opposite way to the hand is unusable long before anybody
    works out why.

    Be clear about what it does *not* do, because it is the check most people
    would reach for first when they hear "the view is mirrored". **It cannot find
    the mirror.** The engine pans using the same axis mapping it draws with, so
    the picture follows the hand pixel for pixel whichever way round it has been
    drawn — measured at a slope of +1.00 both before the mirror was put right and
    after. Only the test above can say which way round the picture is.

    What it is here for is the pair of them together. Reversing the pan gesture
    would make a mirrored viewer feel perfectly normal to drag while leaving the
    picture just as reflected as it was, so it is a change somebody could
    plausibly make in good faith, and this is what would notice.

    The view is put back where it started afterwards, so this leaves the picture
    as it found it for whatever runs next.
    """
    before = where_the_specimen_sits(the_drawing(lopsided_page))
    drag_across(lopsided_page, by)
    after = where_the_specimen_sits(the_drawing(lopsided_page))
    drag_across(lopsided_page, -by)
    moved = after - before
    slope = moved / by
    print(f"\n  dragged {by:+.0f} px, the specimen moved {moved:+.1f} px, slope {slope:+.2f}")
    assert slope > 0, (
        f"the picture was dragged {by:+.0f} pixels across the screen and the "
        f"specimen moved {moved:+.1f} pixels — the other way. Dragging must carry "
        "the picture with the hand, the way a photograph moves when you push it "
        f"across a desk. The slope of the two is {slope:+.2f}, and it has to be "
        "positive."
    )
    assert 0.7 < slope < 1.3, (
        f"the picture was dragged {by:+.0f} pixels and moved {moved:+.1f}, a slope "
        f"of {slope:+.2f}. It should move with the hand pixel for pixel; anything "
        "much away from one means the drag and the drawing disagree about how far "
        "a pixel is."
    )
