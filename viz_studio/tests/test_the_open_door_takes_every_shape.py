"""Every shape of data the open door promises to take, opened through it.

The viewer's reading of these shapes is held in place elsewhere, in detail:
``test_zarr_v3.py`` for version 3 and OME-Zarr 0.5, ``test_a_plate_lays_itself_out.py``
for a high-content-screening plate, and ``test_a_transfer_is_built_into_one_picture.py``
and ``test_a_drifted_run_is_placed_truthfully.py`` for tiles that land at
awkward places. Those go far deeper than this file does and none of it is
repeated here.

What this file holds is the operator's own path to each of them: **point the
load window at it, press Open once, and see the specimen.** That is a
different claim from "the reader can read it", and it is the one that broke.
For a day the first door refused anything that was not a single image, so a
folder of positions -- the ordinary shape of a run -- could be read perfectly
well by every module underneath and still had nowhere to go in the interface.

The fixtures are deliberately tiny and written out in full rather than
borrowed, so that this file can be read as a description of what the viewer
accepts. Each is a few kilobytes and takes a moment to write.

The last two are the ones worth the most attention. A real stage does not
put tiles on a tidy grid and a real run does not image every part of the
ground it declares, so the viewer has to place tiles wherever their own
descriptions say -- to a fraction of a micrometre, at whatever size each
one happens to be -- and to leave the ground between them **empty**. Empty
rather than filled in: an invented pixel in a picture a biologist is about
to draw a conclusion from is the worst thing this viewer could do.
"""

from __future__ import annotations

import json
import threading

import numpy as np
import pytest
import zarr
from driving import open_through_the_window, replay_through_the_window
from pixels import fraction_lit, image_middle
from server import make_server
from test_a_plate_lays_itself_out import a_small_plate

# One micrometre per voxel across the specimen, two through it. Round numbers
# so that a tile's size in voxels and its place in micrometres can be reasoned
# about in the same breath while reading the odd run below.
VOXEL = (1.0, 1.0, 2.0, 1.0, 1.0)

# What a channel is shown over. Stated rather than measured, for the reason
# test_zarr_v3.py records: the contrast measurement reads the version 2 layout
# only, so a 0.5 store gets no histogram and falls back to the whole range of
# the number type, which shows an evenly-filled specimen as uniformly
# saturated -- indistinguishable from a blank panel. Stating it keeps these
# gates measuring what they are named for.
WINDOW = {"min": 0, "max": 65535, "start": 200, "end": 3000}

CHANNELS = (("Ch488", "00FF66"), ("Ch647", "FF00AA"))


def _specimen(height: int, width: int, seed: int) -> np.ndarray:
    """A small pattern with real variation in it, so a picture reads as one.

    Flat values would be no use here: a panel filled evenly with one colour
    cannot be told from a panel showing nothing, which is the very confusion
    these gates exist to avoid.

    The pattern is kept well ABOVE the bottom of the brightness window on
    purpose -- its dimmest value is 1200 against a window starting at 200 --
    so that every imaged voxel reaches the screen plainly lit. That is what
    lets the gate below read a dark pixel as ground nobody imaged rather
    than as a dark part of the specimen.
    """
    y, x = np.mgrid[0:height, 0:width]
    rings = np.sin((np.hypot(y - height / 2, x - width / 2) + seed) / 4.0)
    return (rings * 0.5 + 0.5) * 1800 + 1200


def _write_04(folder, name, *, at=(0.0, 0.0), size=(64, 64), seed=0):
    """One OME-Zarr 0.4 image: zarr version 2, description in ``.zattrs``.

    ``at`` is where the top-left of the image sits on the stage, in
    micrometres, and ``size`` is how many voxels across and down it holds.
    Neither has to be round, and the odd run below relies on that.
    """
    path = folder / name
    path.mkdir(parents=True)
    height, width = size
    data = np.zeros((1, len(CHANNELS), 3, height, width), "uint16")
    for channel in range(len(CHANNELS)):
        for plane in range(3):
            data[0, channel, plane] = _specimen(height, width, seed + channel * 7)
    zarr.open_group(str(path), mode="w", zarr_format=2).create_array(
        "0", shape=data.shape, chunks=(1, 1, 1, height, width), dtype="uint16")[:] = data
    (path / ".zattrs").write_text(json.dumps({
        "multiscales": [{
            "version": "0.4",
            "axes": [{"name": "t", "type": "time", "unit": "second"},
                     {"name": "c", "type": "channel"},
                     {"name": "z", "type": "space", "unit": "micrometer"},
                     {"name": "y", "type": "space", "unit": "micrometer"},
                     {"name": "x", "type": "space", "unit": "micrometer"}],
            "datasets": [{"path": "0", "coordinateTransformations": [
                {"type": "scale", "scale": list(VOXEL)},
                {"type": "translation",
                 "translation": [0.0, 0.0, 0.0, at[0], at[1]]}]}],
        }],
        "omero": {"channels": [{"label": label, "color": colour, "window": WINDOW}
                               for label, colour in CHANNELS]},
    }), encoding="utf-8")
    return path


def _write_05(folder, name, *, at=(0.0, 0.0), size=(64, 64), seed=3):
    """The same image as OME-Zarr 0.5: zarr version 3, description nested twice.

    Version 3 keeps a store's own attributes under ``attributes`` in
    ``zarr.json``, and 0.5 gathers ``multiscales`` and ``omero`` under an
    ``ome`` key inside that -- so what 0.4 writes at the top of a file lives
    two levels down here. A reader that knows only one of the two places
    stops working the moment an instrument is updated.
    """
    path = folder / name
    path.mkdir(parents=True)
    height, width = size
    shape = (1, len(CHANNELS), 3, height, width)
    group = zarr.open_group(str(path), mode="w", zarr_format=3)
    array = group.create_array(
        "0", shape=shape, chunks=(1, 1, 1, height, width), dtype="uint16")
    data = np.zeros(shape, "uint16")
    for channel in range(len(CHANNELS)):
        for plane in range(3):
            data[0, channel, plane] = _specimen(height, width, seed + channel * 7)
    array[:] = data
    group.attrs.update({"ome": {
        "version": "0.5",
        "multiscales": [{
            "axes": [{"name": "t", "type": "time", "unit": "second"},
                     {"name": "c", "type": "channel"},
                     {"name": "z", "type": "space", "unit": "micrometer"},
                     {"name": "y", "type": "space", "unit": "micrometer"},
                     {"name": "x", "type": "space", "unit": "micrometer"}],
            "datasets": [{"path": "0", "coordinateTransformations": [
                {"type": "scale", "scale": list(VOXEL)},
                {"type": "translation",
                 "translation": [0.0, 0.0, 0.0, at[0], at[1]]}]}],
        }],
        "omero": {"channels": [{"label": label, "color": colour, "window": WINDOW}
                               for label, colour in CHANNELS]},
    }})
    return path


# The odd run: three tiles of three different sizes, at places no grid would
# put them, with ground between them that nobody imaged.
#
# Written out as numbers rather than computed, because the point of this
# fixture is that the numbers are awkward and a reader should be able to see
# that they are. In micrometres, and with one micrometre to the voxel, the
# tiles cover:
#
#     A   y    0.0 ..  48.0     x    0.0 ..  48.0
#     B   y    9.7 ..  49.7     x   92.3 .. 148.3
#     C   y   95.1 .. 151.1     x   18.9 ..  58.9
#
# The rectangle they declare between them is 151.1 by 148.3 -- 22,408 square
# micrometres -- of which 6,784 were ever imaged. Just over 30% of the ground,
# with the middle of it empty. If the viewer ever invents a pixel, this is the
# fixture that shows it.
#
# The rectangle is deliberately near enough SQUARE, and that is not cosmetic.
# A long thin run fitted to the window sits in a letterbox, and the black
# above and below it would be counted as unimaged ground by anything looking
# at the canvas -- so the gate would pass on a viewer that filled every gap.
# Measured: with the tiles laid edge to edge instead, the same gate went on
# passing until the shape was squared up.
ODD_TILES = (
    ("odd_tileA.ome.zarr", (0.0, 0.0), (48, 48), 0),
    ("odd_tileB.ome.zarr", (9.7, 92.3), (40, 56), 5),
    ("odd_tileC.ome.zarr", (95.1, 18.9), (56, 40), 11),
)


def _write_odd_run(folder):
    """A run whose tiles are neither the same size nor on any grid."""
    for name, at, size, seed in ODD_TILES:
        _write_04(folder, name, at=at, size=size, seed=seed)
    return folder


@pytest.fixture
def shapes(tmp_path):
    """One folder holding every shape, each in an acquisition folder of its own."""
    root = tmp_path / "shapes"
    _write_04(root / "plain04", "plain04_pos001.ome.zarr")
    _write_05(root / "plain05", "plain05_pos001.ome.zarr")
    (root / "plate").mkdir(parents=True)
    a_small_plate(root / "plate")
    _write_odd_run(root / "odd")
    # Two positions sharing a quarter of their ground, which is how a real
    # stage is asked to move: tiles are overlapped on purpose so a stitcher
    # can measure the true offset afterwards.
    _write_04(root / "overlapping", "overlapping_pos001.ome.zarr",
              at=(0.0, 0.0), size=(64, 64), seed=0)
    _write_04(root / "overlapping", "overlapping_pos002.ome.zarr",
              at=(16.0, 48.0), size=(64, 64), seed=9)
    return root


@pytest.fixture
def page_on(browser, built_dist, shapes):
    """A viewer started on the 0.4 image, from which the rest are opened."""
    server = make_server(
        port=0,
        data_dir=shapes / "plain04",
        site_dir=built_dist,
        store="plain04_pos001.ome.zarr",
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1300, "height": 1000})
    try:
        page.goto(f"http://127.0.0.1:{server.server_address[1]}",
                  wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartConfig !== undefined", timeout=30_000)
        yield page, shapes
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def _wait_until_drawn(page, heading: str) -> None:
    """Wait until every piece the named acquisition needs has arrived."""
    page.wait_for_function(
        """(heading) => {
          const v = window.zmartViewer;
          const mine = v.layerManager.managedLayers.filter(
            (m) => m.name.startsWith(heading));
          if (!mine.length) return false;
          let needed = 0, available = 0;
          for (const m of mine) {
            for (const rl of (m.layer && m.layer.renderLayers) || []) {
              const p = rl.layerChunkProgressInfo;
              if (p) { needed += p.numVisibleChunksNeeded;
                       available += p.numVisibleChunksAvailable; }
            }
          }
          return available > 0 && available >= needed;
        }""",
        arg=heading, timeout=60_000)
    page.wait_for_timeout(1500)


def _open(page, browse_to, row: str) -> str:
    """Open one shape through the window's first door and name what arrived.

    ``browse_to`` is the folder the window is pointed at and ``row`` is what
    is selected inside it -- which is either an image or, for a run of
    several positions, the acquisition folder holding them.
    """
    before = set(page.evaluate("() => window.zmartConfig.groups"))
    open_through_the_window(page, row, folder=browse_to)
    page.wait_for_function(
        "(before) => window.zmartConfig.groups.some((g) => !before.includes(g))",
        arg=sorted(before), timeout=30_000)
    arrived = [one for one in page.evaluate("() => window.zmartConfig.groups")
               if one not in before]
    assert arrived, "opening added no acquisition to the panel"
    _wait_until_drawn(page, arrived[0])
    return arrived[0]


def test_an_ome_zarr_04_image_opens_and_draws(page_on):
    """The commonest shape there is, and the one the viewer starts on."""
    page, _ = page_on
    _wait_until_drawn(page, "plain04")
    assert fraction_lit(page) > 0.2, "the 0.4 image drew nothing worth seeing"


def test_an_ome_zarr_05_image_opens_and_draws(page_on):
    """Version 3 on disk, 0.5 metadata nested twice over. Same door, same press."""
    page, root = page_on
    heading = _open(page, root / "plain05", "plain05_pos001.ome.zarr")
    assert heading.startswith("plain05")
    assert fraction_lit(page) > 0.05, "the 0.5 image opened but drew nothing"


def test_a_plate_opens_and_draws(page_on):
    """A screening plate: no stage translations at all, wells on a grid.

    Where a field belongs follows from the plate's own row and column
    indices rather than from anything written inside the field, so a plate
    is laid out by the door rather than by the tiles -- and the operator
    still only presses Open.
    """
    page, root = page_on
    heading = _open(page, root / "plate", "plate.ome.zarr")
    assert fraction_lit(page) > 0.05, f"{heading} opened but drew nothing"


def test_an_odd_run_opens_as_one_composed_picture(page_on):
    """Three tiles, three sizes, no grid: composed into one picture.

    The sizes differ on purpose. A viewer that quietly assumed one shape for
    every position would draw the first tile and then either stretch or crop
    the others, and both of those look plausible enough on screen to be
    believed.

    What arrives is ONE source per channel rather than one per position, and
    that is the point rather than an implementation detail leaking through.
    A folder handed to the engine as a source per position draws far more
    slowly, and -- less obviously -- loses its colours: adding is a property
    of a layer, so a row fed by several positions cannot be added to the rows
    beneath it and an operator sees only the topmost channel of a run they
    imaged in four. Composing settles both, and the positions still paste
    over one another with the last opened on top rather than blending.
    """
    page, root = page_on
    heading = _open(page, root, "odd")
    rows = page.evaluate(
        "(h) => window.zmartConfig.layers"
        ".filter((l) => (l.group || '') === h)"
        ".map((l) => ({name: l.name,"
        "              sources: (l.sources || [l.source]).length}))", arg=heading)
    assert rows, f"{heading} arrived with no channels"
    assert all(row["sources"] == 1 for row in rows), (
        f"a composed run is one picture, so each channel is fed by one "
        f"source; got {rows}")
    # And it is still the run's own channels, wearing the names the
    # microscope gave them. Composing that renamed them to "channel 1" and
    # "channel 2" -- and dropped the colours and windows with them -- is the
    # fault this half of the gate exists for.
    assert [row["name"] for row in rows] == [label for label, _ in CHANNELS], (
        f"the composed picture must keep the run's own channel names, "
        f"got {[row['name'] for row in rows]}")
    assert fraction_lit(page) > 0.02, "the odd run opened but drew nothing"


def test_a_composed_run_mixes_its_channels(page_on):
    """Every channel of a composed run reaches the screen, not just the top one.

    Hiding one channel of a picture whose channels MIX takes some light off
    the screen and leaves the rest. Hiding one channel of a picture whose
    channels COVER each other either changes nothing at all -- it was
    underneath -- or reveals a whole second picture that was hidden. So the
    reading after hiding is compared with the reading before, and it has to
    move a little without moving a lot.
    """
    page, root = page_on
    _open(page, root, "odd")
    before = fraction_lit(page)
    page.get_by_label(f"toggle {CHANNELS[-1][0]}").last.click()
    page.wait_for_timeout(2000)
    after = fraction_lit(page)
    assert before > 0.02, "nothing was on screen to begin with"
    assert after < before * 1.4, (
        f"hiding the top channel took the picture from {before:.3f} to "
        f"{after:.3f} lit -- it was covering the others rather than mixing "
        "with them")


def test_nothing_is_drawn_where_nothing_was_imaged(page_on):
    """The ground between the tiles stays empty, and that is the whole point.

    Only 39% of the rectangle these three tiles declare between them was ever
    imaged. So a picture of the whole run has to come out substantially dark:
    a canvas that filled up would mean the viewer had invented specimen, which
    is the one mistake here that could change what somebody concludes from
    their data.

    This looks at the screen. The byte-level counterpart -- that no padded or
    unimaged piece is ever *served* as picture -- is held by
    ``test_a_drifted_run_is_placed_truthfully.py``; the two together say the
    emptiness survives all the way from the disk to the eye.

    Both numbers below were chosen by falsifying this gate rather than by
    taste. Laying the same three tiles edge to edge so they cover all of
    their own ground -- which is what a viewer that filled the gaps would
    draw -- moves the reading from 0.305 lit and a dimmest pixel of 0, to
    1.000 lit and a dimmest pixel of 91. The thresholds sit in the gap
    between those two, and the gate has been watched to fail.
    """
    page, root = page_on
    _open(page, root, "odd")
    # Frame the whole run, so what is measured is the declared rectangle
    # rather than wherever the view happened to be sitting.
    page.get_by_role("button", name="Overview", exact=True).click()
    page.wait_for_timeout(2500)

    lit = fraction_lit(page)
    assert lit > 0.01, "nothing at all is on screen; this measures the wrong thing"
    assert lit < 0.75, (
        f"{lit:.3f} of the picture is lit, but only about a third of this run's "
        "ground was imaged -- pixels are being shown where none were recorded")

    # And the emptiness is really emptiness rather than a dim wash over
    # everything: the darkest part of the picture has to be near black.
    darkest = int(np.asarray(image_middle(page)).max(axis=2).min())
    assert darkest < 30, (
        f"the dimmest pixel on screen is {darkest}, so unimaged ground is being "
        "painted rather than left alone")


def test_tiles_that_overlap_load_and_do_not_blend(page_on):
    """Overlapping positions open, and the shared ground is not brightened.

    Overlap is the ordinary case on a real stage -- tiles are given an
    overlap on purpose so a stitcher can measure the true offset afterwards
    -- so a viewer that only coped with tiles laid edge to edge would be no
    use. These two share a quarter of their ground.

    What the shared strip must NOT be is brighter. Where two positions meet,
    one wins and is drawn on top; they are never added. A viewer that added
    them would draw a bright seam along every join, and on a specimen that
    seam reads as signal.
    """
    page, root = page_on
    heading = _open(page, root, "overlapping")
    rows = page.evaluate(
        "(h) => window.zmartConfig.layers"
        ".filter((l) => (l.group || '') === h)"
        ".map((l) => (l.sources || [l.source]).length)", arg=heading)
    assert rows and all(count == 1 for count in rows), (
        f"overlapping positions should compose to one picture, got {rows}")
    page.get_by_role("button", name="Overview", exact=True).click()
    page.wait_for_timeout(2000)
    brightest = int(np.asarray(image_middle(page)).max())
    assert fraction_lit(page) > 0.05, "the overlapping run drew nothing"
    # The specimen's own top is 3000 against a window ending at 3000, so a
    # single position already reaches full brightness. Adding two of them
    # could not go higher on screen -- what it WOULD do is turn the dim parts
    # of the pattern bright inside the shared strip, which the ring pattern
    # makes visible as a lost dark ring. So the check is that the picture
    # still holds properly dark ground inside the specimen.
    darkest_inside = int(np.asarray(image_middle(page)).max(axis=2).min())
    assert brightest > 100, f"the specimen is not being drawn, brightest {brightest}"
    assert darkest_inside < 30, (
        f"the dimmest pixel is {darkest_inside}: the overlap looks blended "
        "rather than covered")


def _photograph_a_scene(browser, built_dist, root, scene_folder):
    """Open one already-declared picture and bring back what reached the screen."""
    server = make_server(port=0, data_dir=scene_folder.parent,
                         site_dir=built_dist, store=scene_folder.name)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1300, "height": 1000})
    try:
        page.goto(f"http://127.0.0.1:{server.server_address[1]}",
                  wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartConfig !== undefined",
                               timeout=30_000)
        heading = page.evaluate("() => window.zmartConfig.groups")[0]
        _wait_until_drawn(page, heading)
        page.get_by_role("button", name="Overview", exact=True).click()
        page.wait_for_timeout(2000)
        return np.asarray(image_middle(page)).astype(float)
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def test_a_bake_changes_how_fast_the_picture_arrives_and_nothing_else(
        browser, built_dist, shapes, tmp_path):
    """The same run, declared without a bake and with one, has to look the same.

    A bake computes the coarse ground now and keeps it as real files instead
    of making each piece when the browser asks. That is a promise about
    *speed* and about nothing else: the pixels a baked picture serves are the
    pixels an unbaked one would have made, so the two must be the same
    picture on screen.

    They are photographed and compared rather than reasoned about, because
    the ways a bake could quietly differ -- a level built from the wrong
    copy, a piece written with the fill value where a tile reaches, an
    off-by-one in the pyramid -- all produce a picture that looks entirely
    plausible on its own and only shows up beside the other one.

    The awkward run is the one used, deliberately. A bake over tiles laid on
    a tidy grid is the easy case; these three sit at fractional offsets, at
    three different sizes, with unimaged ground between them.
    """
    from declare import declare_a_built_picture

    plain = declare_a_built_picture(tmp_path / "unbaked", shapes / "odd",
                                    name="odd", bake=False)
    baked = declare_a_built_picture(tmp_path / "baked", shapes / "odd",
                                    name="odd", bake=True)
    without = _photograph_a_scene(browser, built_dist, shapes, plain)
    with_it = _photograph_a_scene(browser, built_dist, shapes, baked)

    assert without.shape == with_it.shape, (
        f"the two pictures are different sizes: {without.shape} against "
        f"{with_it.shape}")
    assert float(without.max()) > 40, (
        "the unbaked picture drew nothing, so there is nothing to compare")
    assert float(with_it.max()) > 40, "the baked picture drew nothing"
    apart = float(np.abs(without - with_it).mean())
    assert apart < 2.0, (
        f"baked and unbaked differ by {apart:.2f} levels per pixel on "
        "average -- a bake must change how fast the picture arrives and "
        "nothing about what it shows")
