"""The brightness window has to change what is on screen, not just what the panel says.

Choosing a brightness window — "anything dimmer than this is black, anything
brighter is white" — is the first thing a microscopist does with a new
acquisition. It is how a specimen is found at all: the camera records sixteen-bit
numbers, a real acquisition occupies a narrow band of them, and the window is what
stretches that band across the greys the screen can show.

So the window has to reach the picture. It is entirely possible for it not to, and
for everything else to look healthy while it does not: the server can measure a
sensible window, the panel can display it, the drawing engine can hold it and
report it back correctly, every piece of image can be fetched — and the screen can
still show a flat, featureless shape with all the shading missing. That happened
here, and it is worth writing down what it looked like, because the symptom is
easy to mistake for something else.

The viewer's flat-picture shader used to hand the brightness to the *transparency*
of each point rather than to its colour, in the belief that the drawing engine
multiplies colour by transparency before it draws. It does for a picture with
another picture underneath it. It does not for the bottom-most one: there the
engine switches blending off altogether, writes the colour straight to the screen,
and consults the transparency only as a yes-or-no test for "is this background?".
The whole brightness range therefore collapsed to a single flat colour. Measured
on a specimen that ramps smoothly from 600 to 3900 counts, a sensible window of
500–4000 and an absurd one of 0–60000 produced *pixel-identical* pictures: two
colours in the whole view, pure white inside the specimen and pure black outside.

That is what the first tests here guard. The first is the direct check: two servers
over the very same data, told to use very different windows, must not draw the same
picture. The second is the reason it matters — the narrow window has to show the
gradient that is genuinely in the data, rather than a solid block. The third repeats
that on a specimen written to make the point unmissable: a plain ramp, whose every
column should come out a different grey.

They look at a photograph of the drawing surface rather than asking the engine what
it holds. That distinction is the whole point: the engine held the right numbers
throughout the fault.

Two further things belong here, because they are the two ways the correction could
have made matters worse rather than better.

**Ground nobody has imaged has to stay transparent.** The fault above arrived as a
fix for a real problem, and that problem must not come back. Most of a row is
usually empty — a canvas is declared to the size of the stage and filled in as the
run goes — so a row drawn opaque everywhere hides every row beneath it, and an
experiment with an overview and a target scan shows only whichever happens to be on
top. Both rows load, both hold their data, and one of them is invisible. So the
brightness belongs in the colour and the transparency has one job only: saying
whether this spot was imaged at all.

**And the window has to be measurable in the first place.** A separate fault meant
it was not, on the very format this project is aiming at. The measurement read a
store's description from a ``.zattrs`` file, which is where OME-Zarr 0.4 keeps it;
OME-Zarr 0.5 keeps it elsewhere, so a 0.5 store came back as unreadable. Nothing
failed and nothing was reported — the store simply opened over the whole range a
sixteen-bit camera can produce, with no histogram for the panel to draw and nothing
for the Auto button to restore.
"""

from __future__ import annotations

import json
import threading

import numpy as np
import pytest
import zarr
from contrast import measure
from demo_data import write_demo_zarr
from pixels import colour_spread, image_middle
from server import make_server

# Two brightness windows that could not be more different, and what each should do
# to this particular specimen.
#
# The demo volume's cells sit between a background of about 800 counts and a peak
# of about 20800, so the first window is roughly the right one: it spreads the whole
# specimen across the available greys and the cells come out shaded.
#
# The second is very nearly the whole range a sixteen-bit camera can record. That is
# not an arbitrary bad choice — it is essentially the window the viewer falls back to
# when it cannot measure a store, and showing real data over it is the failure the
# brightness measurement exists to prevent: the specimen occupies the bottom third of
# it and the picture comes out dim and flat. So both windows compared here are ones a
# microscopist could really meet.
#
# Two practical limits on what may be written here, both worth knowing before
# changing these numbers. The drawing engine reads them in the units of the stored
# data and refuses anything outside nought to 65535 for sixteen-bit data, so a wider
# range would be quietly ignored and this test would be measuring nothing. And the
# engine leaves a setting out of its own account of itself when that setting still
# holds its default, which for sixteen-bit data is exactly nought to 65535 — so the
# top of the wide window is pulled a little short of it, and the check below that the
# window really arrived has something to read.
_SENSIBLE_WINDOW = (800.0, 21000.0)
_FAR_TOO_WIDE_WINDOW = (0.0, 60000.0)


@pytest.fixture(scope="module")
def one_channel_store(tmp_path_factory):
    """A folder holding one single-channel acquisition, written once for both tests.

    Single-channel on purpose, and it is the whole point of the fixture rather than
    a way of keeping it small. The fault this file is about only ever showed itself
    on the *bottom-most* picture on screen, so an acquisition that produces exactly
    one row in the panel is the case that exposes it. A three-channel volume hides
    it: the two rows above the bottom one were drawn correctly all along, and their
    shading was enough to make the view look plausible.
    """
    folder = tmp_path_factory.mktemp("contrast_reaches")
    write_demo_zarr(folder / "overview_pos001.zarr", single_channel=True)
    return folder


def _drawn_with(browser, folder, site_dir, window):
    """Open the viewer over ``folder`` with ``window`` forced, and photograph it.

    Returns the middle of the drawing surface as height by width by red-green-blue.
    The window is handed to the server rather than typed into the panel so that the
    picture is measured on a page that has never been touched — which is also how
    ``--range`` reaches the viewer in real use.
    """
    server = make_server(
        port=0,
        data_dir=folder,
        site_dir=site_dir,
        store=["overview_pos001.zarr"],
        live=False,
        window=window,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 900, "height": 700})
    try:
        page.goto(f"http://127.0.0.1:{server.server_address[1]}", wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartViewer !== undefined", timeout=60_000)
        # Wait until the engine says it has every piece of image the view needs.
        # Photographing before that would measure how far the loading had got
        # rather than how the data is being shown.
        page.wait_for_function(
            """() => {
                 const v = window.zmartViewer;
                 let needed = 0, available = 0;
                 for (const m of v.layerManager.managedLayers)
                   for (const rl of (m.layer && m.layer.renderLayers) || []) {
                     const p = rl.layerChunkProgressInfo;
                     if (p) {
                       needed += p.numVisibleChunksNeeded;
                       available += p.numVisibleChunksAvailable;
                     }
                   }
                 return available > 0 && available >= needed;
               }""",
            timeout=120_000,
        )
        # A short settle after the last piece lands, because the engine draws on its
        # own schedule and the frame on screen may still be one behind.
        page.wait_for_timeout(2500)
        window_in_engine = page.evaluate(
            """() => {
                 for (const layer of window.zmartViewer.state.toJSON().layers) {
                   const range = layer.shaderControls?.normalized?.range;
                   if (range) return range;
                 }
                 return null;
               }"""
        )
        return image_middle(page), window_in_engine
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def test_two_very_different_windows_draw_two_different_pictures(
    browser, built_dist, one_channel_store
):
    """The same data, two windows, and the pictures must genuinely differ.

    This is the assertion the fault could not pass. Before it was fixed both
    pictures were identical to the pixel, so comparing them is enough on its own —
    no threshold to calibrate and nothing to tune.

    The engine's own account of the window is checked first, and only so that a
    failure below can be read properly. If the two windows had never reached the
    engine, the pictures would rightly be identical and the fault would be
    somewhere else entirely — in the server, or in the panel — so it is worth
    ruling that out in the same breath rather than leaving the reader to wonder.
    """
    import numpy as np

    sensible, sensible_range = _drawn_with(
        browser, one_channel_store, built_dist, _SENSIBLE_WINDOW
    )
    far_too_wide, wide_range = _drawn_with(
        browser, one_channel_store, built_dist, _FAR_TOO_WIDE_WINDOW
    )

    assert sensible_range == list(_SENSIBLE_WINDOW), sensible_range
    assert wide_range == list(_FAR_TOO_WIDE_WINDOW), wide_range

    assert not np.array_equal(sensible, far_too_wide), (
        "two completely different brightness windows drew the very same picture, "
        "so the window is reaching the engine and the panel but not the drawing. "
        f"Both came out as {colour_spread(sensible)}"
    )
    # And not merely different by a pixel here and there. Stretching the window
    # across the whole sixteen-bit range leaves the specimen in the bottom third of
    # it, so the picture has to come out substantially darker, and the average
    # brightness is the plainest thing to compare.
    assert sensible.mean() > far_too_wide.mean() * 1.5, (
        "widening the brightness window to nearly the whole range of the camera "
        "barely "
        f"changed how bright the picture is (average {sensible.mean():.1f} with a "
        f"sensible window, {far_too_wide.mean():.1f} with the widest one), so the "
        "window is not really deciding how the data is shown"
    )


def test_the_shading_in_the_data_survives_to_the_screen(
    browser, built_dist, one_channel_store
):
    """A specimen with soft, graded edges has to be drawn with soft, graded edges.

    The demo volume's cells are smooth balls of brightness, so a faithful drawing
    of them has many shades of grey in it. During the fault this came out as two
    colours only — pure white where there was any signal at all and pure black
    everywhere else — a flat cut-out shape rather than a picture of cells.

    Counting how many different colours appear is a blunt measurement, and
    deliberately so: it cannot tell you the picture is *correct*, only that the
    shading was not thrown away. Twenty is far above the two the fault produced and
    far below the two hundred or so a healthy single-channel picture gives, so
    nothing here is delicately balanced.
    """
    picture, _ = _drawn_with(browser, one_channel_store, built_dist, _SENSIBLE_WINDOW)
    spread = colour_spread(picture)
    assert spread["distinct"] > 20, (
        "the specimen was drawn as a flat shape with no shading in it, so the "
        f"brightness of each point never reached the screen: {spread}"
    )


# --- a specimen written to make the point unmissable -------------------------
#
# The tests above use the demo volume, which is the right thing for them to use: it
# is what the viewer opens with and what an operator sees first. What follows writes
# its own specimen instead, and it is worth saying why rather than leaving it looking
# like duplication.
#
# A plain ramp — brightness climbing steadily across the frame, with a bright line
# every eighth row — has a known answer. Every column of it should come out a
# different grey, so a faithful drawing has hundreds of distinct brightnesses in it
# and a drawing that has thrown the brightness away has two. There is no judgement
# involved in reading that, whereas with a picture of cells somebody has to decide how
# much shading counts as "enough". It also lets a channel be filled in over one half
# of the frame and left untouched over the other, which is what the tests about two
# rows need and what no natural specimen provides.

# How wide the written specimen is, in voxels, and how large one voxel is in
# micrometres. Together these decide how much of the view the specimen fills, and that
# is worth caring about: every measurement here is taken from the middle of the view,
# so a specimen arriving as a few pixels in the centre of an empty field would leave
# those measurements reading mostly background. At 256 voxels of half a micrometre the
# specimen is 128 micrometres across and covers a good share of the middle of the
# view.
_WIDE = 256
_VOXEL = 0.5

# The brightness window these written stores are shown over, and the range of values
# the specimen is written with.
#
# The floor sits *below* the dimmest imaged value on purpose. Anything at or under the
# floor comes out fully transparent, because that is how a spot nobody has imaged is
# told apart from a dark one — so a test about brightness should not have part of its
# specimen disappearing for that reason. Imaged data therefore starts at 600 and the
# floor is 500, which leaves "transparent" meaning "never imaged" and nothing else.
_FITTED_WINDOW = (500.0, 4000.0)
_DIMMEST = 600
_BRIGHTEST = 3900


def _ramp(wide: int):
    """A square plane: brightness climbing down it, with a bright line every eighth column.

    The structure is load-bearing rather than decoration. An image filled with one value
    everywhere is a single flat colour on screen, and a single flat colour is also
    exactly what an empty panel is — so with an even fill no measurement could tell a
    drawn picture from an undrawn one, and none could tell one brightness window from
    another either.

    The gradient runs **down** the plane rather than across it, and that is deliberate.
    Two of the tests below divide the picture into a left half and a right half and
    compare them, so the specimen must not itself be brighter on one side than the
    other — otherwise the comparison would be measuring the ramp rather than the
    drawing. With the gradient running downwards, any two columns of the plane hold the
    same range of brightnesses.
    """
    down = np.linspace(_DIMMEST, _BRIGHTEST - 100, wide, dtype=np.float32)
    plane = np.tile(down[:, None], (1, wide))
    plane[:, ::8] = _BRIGHTEST
    return plane


def _write_store(path, planes, *, labels=None, zarr_format=2):
    """A small OME-Zarr, written from one two-dimensional plane per channel.

    Each plane is repeated through the depth, so whichever z the viewer happens to
    open at shows the same thing and no test has to drive the z slider.

    ``labels`` decides the shape of the store, and the two shapes exercise different
    parts of the viewer:

    * left out, which needs exactly one plane, writes a plain ``z, y, x`` image with
      no channel axis and nothing describing a channel. That is the store with **no
      colour of its own** — one image, drawn in plain white — and it is the case the
      brightness fault lived in, because a single uncoloured row is the bottom-most
      picture on screen and there is nothing above it to hide the fault.
    * given, writes ``t, c, z, y, x`` with one channel per name. Each becomes a row of
      its own in the panel, which is what the tests about two rows over the same
      ground need. Each is given white as its colour, so both shapes draw the same way
      and a difference between these tests can never be a difference of colour.

    ``zarr_format`` chooses which generation of the format writes the store: 2 for the
    OME-Zarr 0.4 layout nearly every instrument produces today, 3 for the OME-Zarr 0.5
    layout this project is aiming at. The two keep the image's description in quite
    different places, which is the whole point of the last two tests in this file.

    Note what is deliberately *not* written: a brightness window. OME-Zarr lets a store
    declare one, and the viewer rightly honours a declared window over anything it
    measures — so a store declaring one would let the measurement tests below pass
    without any measurement having happened.
    """
    depth = 4
    if labels is None:
        (plane,) = planes
        data = np.broadcast_to(plane, (depth, *plane.shape)).astype(np.uint16)
        axes = ("z", "y", "x")
        scale = [2.0, _VOXEL, _VOXEL]
        chunks = (1, 64, 64)
    else:
        data = np.stack(
            [np.broadcast_to(plane, (depth, *plane.shape)) for plane in planes]
        ).astype(np.uint16)[None]
        axes = ("t", "c", "z", "y", "x")
        scale = [1.0, 1.0, 2.0, _VOXEL, _VOXEL]
        chunks = (1, 1, 1, 64, 64)

    kinds = {"t": "time", "c": "channel", "z": "space", "y": "space", "x": "space"}
    units = {"t": "second", "z": "micrometer", "y": "micrometer", "x": "micrometer"}
    multiscale = {
        "axes": [
            {"name": axis, "type": kinds[axis]}
            | ({"unit": units[axis]} if axis in units else {})
            for axis in axes
        ],
        "datasets": [
            {"path": "0", "coordinateTransformations": [{"type": "scale", "scale": scale}]}
        ],
    }
    described = {"multiscales": [multiscale]}
    if labels is not None:
        # A channel has to be given a colour here as well as a name. The drawing engine
        # parses this block itself and refuses a channel that names no colour, and it
        # reports that as a complaint about the channel list rather than about the
        # colour, which is easily an hour lost. White is chosen so that these rows look
        # exactly like a store that describes no channels at all.
        described["omero"] = {
            "channels": [{"label": label, "color": "FFFFFF"} for label in labels]
        }

    group = zarr.open_group(str(path), mode="w", zarr_format=zarr_format)
    group.create_array("0", shape=data.shape, chunks=chunks, dtype="uint16")[:] = data
    if zarr_format == 3:
        # Version 3 keeps a store's own attributes inside ``zarr.json``, and OME-Zarr
        # 0.5 gathers the image description under an ``ome`` key inside those, saying
        # which version of the format it is once for the whole block. That nesting is
        # what the brightness measurement used to be unable to find.
        group.attrs.update({"ome": {"version": "0.5", **described}})
    else:
        # OME-Zarr 0.4 says which version it is inside each multiscale entry instead.
        # Putting it in the wrong place is not forgiven: the drawing engine reports that
        # the store has no multiscale metadata at all, which is a confusing thing to be
        # told about a store that plainly has some.
        multiscale["version"] = "0.4"
        (path / ".zattrs").write_text(json.dumps(described), encoding="utf-8")
    return path


def _viewer_on(browser, site_dir, folder, name, window):
    """Open the viewer on one written store and wait until it has drawn it.

    Comes back as ``(page, stop)``; call ``stop()`` when finished, which closes the page
    and shuts the server down. This is the same preparation ``_drawn_with`` above does,
    except that the page is handed back still open, because the tests below need to
    change what is showing and photograph it again.
    """
    server = make_server(
        port=0,
        data_dir=folder,
        site_dir=site_dir,
        store=[name],
        live=False,
        window=window,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1200, "height": 900})

    def stop():
        page.close()
        server.shutdown()
        thread.join(timeout=5)

    try:
        page.goto(
            f"http://127.0.0.1:{server.server_address[1]}", wait_until="domcontentloaded"
        )
        page.wait_for_function("() => window.zmartViewer !== undefined", timeout=60_000)
        page.wait_for_function(
            """() => {
                 let needed = 0, available = 0;
                 for (const m of window.zmartViewer.layerManager.managedLayers)
                   for (const rl of (m.layer && m.layer.renderLayers) || []) {
                     const p = rl.layerChunkProgressInfo;
                     if (p) {
                       needed += p.numVisibleChunksNeeded;
                       available += p.numVisibleChunksAvailable;
                     }
                   }
                 return available > 0 && available >= needed;
               }""",
            timeout=120_000,
        )
        # The engine having every piece it wants is not quite the same as the picture
        # having been drawn with them; the two are a frame or two apart. This is the one
        # place where a short pause is the right tool.
        page.wait_for_timeout(2500)
    except Exception:
        stop()
        raise
    return page, stop


def _grey(page):
    """The middle of the picture as one brightness per pixel, from 0 to 255.

    These rows are drawn without a colour of their own, so red, green and blue all
    carry the same number and taking the largest of the three loses nothing. It makes
    what follows much easier to read: one brightness per pixel is exactly what a
    microscopist is looking at when they turn the contrast handles.
    """
    return image_middle(page).max(axis=2)


# What counts as "there is specimen here" rather than "this is ground nobody imaged".
# The floor sits well above the black of an unimaged region and well below the dimmest
# part of the ramp that the window brings up, so nothing here is sensitive to exactly
# where it is put.
_LIT = 40


def _describe(grey) -> dict:
    """A few plain numbers about a patch of picture, for asserting on and for failures.

    ``mean`` is the average brightness over the whole patch, and it is the number to
    compare when two patches should be showing the same thing. ``lit`` is what share of
    the patch is showing specimen at all rather than unimaged ground. ``brightness`` is
    the average of the lit part alone, which is useful to read in a failure message but
    a poor thing to compare, for a reason worth knowing: if a picture is drawn too dimly
    its faintest parts fall below the "lit" floor and drop out of the average
    altogether, so the average of what survives barely moves. ``distinct`` is how many
    different brightnesses appear, which is how shading is told apart from a flat
    silhouette, and ``saturated`` is what share sits at the very top of the scale, which
    is what a window making no difference produces.
    """
    lit = grey > _LIT
    return {
        "mean": round(float(grey.mean()), 1),
        "lit": round(float(lit.mean()), 3),
        "brightness": round(float(grey[lit].mean()), 1) if lit.any() else 0.0,
        "distinct": int(np.unique(grey).size),
        "saturated": round(float((grey > 250).mean()), 3),
    }


def test_a_narrow_window_on_ramped_data_shows_a_gradient(browser, built_dist, tmp_path):
    """A window that fits the specimen has to show its shading, not a silhouette.

    This is the fault the tests above are about, seen from the clearest possible angle,
    and it needs only one picture rather than two. The specimen ramps steadily across
    the frame, so drawn over a window that fits it, the picture has to be a spread of
    many brightnesses.

    Under the fault it was exactly two — pure black and pure white — because the colour
    written out was white everywhere the row covered and background everywhere else.
    That is worth spelling out, because a two-value picture is not obviously wrong to
    look at: it has edges, it has shape, and the specimen is recognisable. What it has
    lost is every gradation *inside* the specimen, which on real data is where the
    biology is.

    The store here has no channel axis and describes no channels, so it arrives as one
    row with no colour of its own. That is the case the fault lived in: a single
    uncoloured row is the bottom-most picture on screen, and the bottom-most picture is
    the one whose transparency the engine discards.
    """
    folder = tmp_path / "run"
    folder.mkdir()
    _write_store(folder / "overview_pos001.ome.zarr", [_ramp(_WIDE)])

    page, stop = _viewer_on(
        browser, built_dist, folder, "overview_pos001.ome.zarr", _FITTED_WINDOW
    )
    try:
        found = _describe(_grey(page))
    finally:
        stop()
    print(f"\n  a ramp over a window that fits it: {found}")

    assert found["lit"] > 0.1, f"nothing was drawn at all: {found}"
    # A ramp two hundred and fifty-six voxels wide, shown over a window that fits it,
    # offers something close to two hundred distinct brightnesses, and that is what is
    # measured here. Sixteen is a long way below it and a long way above the two a flat
    # silhouette gives, so this fails on the fault without being sensitive to how the
    # picture happens to be scaled onto the screen.
    assert found["distinct"] > 16, (
        "the picture holds almost no distinct brightnesses, so the specimen is being "
        f"drawn as a flat silhouette rather than with its shading: {found}"
    )
    # The same thing said a second way, because the count above could in principle be
    # satisfied by a picture that is nearly all saturated with a few soft edges on it.
    assert found["saturated"] < 0.5, (
        f"most of the picture sits at the very top of the scale: {found}"
    )


@pytest.fixture
def two_complementary_rows(browser, built_dist, tmp_path):
    """One acquisition whose two channels each fill in one half of the frame.

    This fixture is the shape both tests below need, and the shape is doing real work,
    so it is worth explaining.

    The two channels hold **the same specimen in different places**: an identical ramp,
    one in the left half of the frame and one in the right, with nothing at all in the
    other half. Two things follow, and they are exactly the two things being tested.

    Because each channel is empty where the other has specimen, whichever row the
    engine happens to draw on top has to let the other show through — so "both halves
    of the picture are lit" is a statement about transparency that does not depend on
    which row is on top.

    And because the two halves hold the *same* ramp, the two halves of the picture must
    come out equally bright. Any difference between them is something the drawing did,
    not something in the data — which is what makes the second test below possible.
    """
    folder = tmp_path / "run"
    folder.mkdir()
    half = _ramp(_WIDE // 2)
    blank = np.zeros_like(half)
    _write_store(
        folder / "overview_pos001.ome.zarr",
        [np.hstack([half, blank]), np.hstack([blank, half])],
        labels=["left-half", "right-half"],
    )
    page, stop = _viewer_on(
        browser, built_dist, folder, "overview_pos001.ome.zarr", _FITTED_WINDOW
    )
    try:
        yield page
    finally:
        stop()


def _halves(page) -> dict:
    """The left and right halves of the middle of the picture, described separately.

    A margin is left out around the seam. The two halves meet at one voxel boundary in
    the data, but on screen that boundary is smoothed by the engine's own sampling, so
    a few columns either side of it belong cleanly to neither half. Measuring away from
    the seam keeps these tests about what they are named for rather than about how an
    edge is filtered.
    """
    grey = _grey(page)
    middle = grey.shape[1] // 2
    margin = max(grey.shape[1] // 10, 1)
    return {
        "left": _describe(grey[:, : middle - margin]),
        "right": _describe(grey[:, middle + margin :]),
    }


def test_ground_nobody_imaged_stays_transparent(two_complementary_rows):
    """Two rows over the same ground, and neither may black the other out.

    This is the property the fault above arrived as a fix for, and it has to survive the
    correction — which is why it is tested here rather than left implied. Most of a row
    is usually empty, so a row drawn opaque everywhere hides every row beneath it, and
    an experiment with an overview and a target scan then shows only whichever happens
    to be on top. Both rows load, both hold their data, and one of them is invisible.

    Both halves lit is the only way to pass, and the control that follows is what stops
    this from being an assertion that cannot fail: each row is hidden in turn, and one
    half of the picture has to go dark while the other survives. That is how we know the
    two halves really were coming from two different rows rather than from one row
    covering the whole frame.

    Which row owns which half of the *screen* is deliberately not assumed. The engine
    places an image from what the store says about its position, and whether that leaves
    the first half of the data on the left or on the right of the view is its business
    rather than this test's. What matters, and what is checked, is that the two rows own
    opposite halves — so hiding either one leaves the other's half untouched.
    """
    page = two_complementary_rows
    both = _halves(page)
    print(f"\n  both rows shown: {both}")
    for side in ("left", "right"):
        assert both[side]["lit"] > 0.05, (
            f"the {side} half of the view has nothing in it with both rows shown, so a "
            f"row holding nothing is covering the row that holds something: {both}"
        )

    owned = {}
    for hidden in ("left-half", "right-half"):
        page.get_by_label(f"toggle {hidden}").first.click()
        page.wait_for_timeout(2000)
        without = _halves(page)
        print(f"  {hidden} hidden: {without}")
        went_dark = [
            side
            for side in ("left", "right")
            if without[side]["lit"] < both[side]["lit"] / 4
        ]
        survived = [
            side
            for side in ("left", "right")
            if without[side]["lit"] > both[side]["lit"] * 0.8
        ]
        assert len(went_dark) == 1 and len(survived) == 1, (
            f"hiding the {hidden} row should have emptied exactly one half of the "
            f"picture and left the other alone: {both} became {without}"
        )
        owned[hidden] = went_dark[0]
        page.get_by_label(f"toggle {hidden}").first.click()
        page.wait_for_timeout(2000)

    assert owned["left-half"] != owned["right-half"], (
        "both rows turned out to own the same half of the picture, so the halves being "
        f"lit was never evidence of anything: {owned}"
    )


def test_a_row_on_top_is_drawn_as_brightly_as_the_row_beneath_it(two_complementary_rows):
    """The row on top must not be dimmed by having its brightness applied twice.

    This guards a mistake that is very easy to make and very hard to see, so it is worth
    setting out in full.

    Brightness has to go into the *colour* — that is the whole of the fix these tests are
    about — and coverage has to go into the transparency. The tempting short cut is to
    write the brightness into both, since the bottom-most row ignores transparency
    anyway and it looks harmless. It is not harmless. Every row above the bottom one
    *is* blended, using ordinary "straight" transparency rather than the
    already-multiplied kind, which means the engine multiplies the colour by the
    transparency as it draws. A row that has already dimmed its colour by the brightness
    and then declares that same brightness as its transparency is therefore dimmed by it
    twice: a half-bright point comes out at a quarter.

    Two things make that failure nasty. It is invisible on a single row, because the
    bottom-most row is not blended at all. And where it does show, it looks like a
    slightly dimmer acquisition rather than like a fault — a target scan that seems to
    have been taken with less exposure than the overview it sits on.

    The two halves of this picture hold the same ramp, so they must be drawn equally
    brightly. One of them is the row on top. Measured, applying the brightness twice
    takes thirty per cent off that half — so the tolerance below is generous and the
    failure is still unmissable.

    The comparison is on the average over the whole half of the picture, not on the
    average of the part that is lit. That is deliberate. Dimming the specimen pushes its
    faintest parts below the floor at which anything counts as lit, so they leave the
    average rather than lowering it, and the average of what remains hardly moves: it
    read 144 against 158 while the picture had lost a quarter of its lit area. Averaging
    the whole half counts what was lost.
    """
    both = _halves(two_complementary_rows)
    print(f"\n  the two halves: {both}")

    left, right = both["left"]["mean"], both["right"]["mean"]
    assert left > 0 and right > 0, f"one half of the picture is empty: {both}"
    # Fifteen per cent either way covers the engine's own sampling and the fact that the
    # two halves are not photographed at identical positions on screen. The mistake this
    # guards against costs several times that.
    assert 0.85 < left / right < 1.18, (
        "the two halves of the picture hold the same specimen but are not drawn "
        "equally brightly, which is what happens when the row on top has its "
        f"brightness applied twice — once in its colour and again as its "
        f"transparency: {both}"
    )
    # And the same again by area, because the two go together: a half drawn too dimly
    # loses its faintest parts entirely, and that shows up here rather than in the
    # average above.
    lit_left, lit_right = both["left"]["lit"], both["right"]["lit"]
    assert 0.85 < lit_left / lit_right < 1.18, (
        "the two halves of the picture hold the same specimen but do not show the same "
        f"amount of it, so one of them is being drawn too dimly to see: {both}"
    )


# --- measuring a window at all, on the format this project is aiming at ------


def test_an_ome_zarr_zero_point_five_store_measures_its_own_window(tmp_path):
    """A store in the format we are aiming at must not open on a guess.

    Everything above is about a window reaching the picture. This is about there being a
    window to reach it with. OME-Zarr 0.5 keeps an image's description in a different
    place from 0.4, and while the brightness measurement looked only in the older place,
    a 0.5 store came back as unreadable. Nothing failed and nothing was reported: the
    store simply opened over the whole range a sixteen-bit camera can produce — which on
    a real acquisition draws black — with no histogram for the panel to draw and nothing
    for the Auto button to restore.

    So this asks for the measurement without stating a window, and checks that what
    comes back describes *this specimen* rather than the kind of number it happens to be
    stored as.
    """
    store = _write_store(
        tmp_path / "overview_pos001.ome.zarr", [_ramp(64)], zarr_format=3
    )

    found = measure(store)
    print(f"\n  measured from an OME-Zarr 0.5 store: {found['window']}")

    assert found["window"] != (0.0, 65535.0), (
        "an OME-Zarr 0.5 store fell back to the whole range of its data type, which is "
        "what this viewer does when it cannot read a store's pixels at all"
    )
    low, high = found["window"]
    # The specimen runs from 600 to 3900 counts, and the window is a percentile of it
    # rather than its extremes, so it should land just inside those bounds. Checking
    # that it sits inside the specimen's own range is what says the measurement really
    # read this store's pixels rather than guessing well.
    assert _DIMMEST - 100 <= low < high <= _BRIGHTEST + 100, found["window"]

    histogram = found["histogram"]
    assert histogram is not None, (
        "an OME-Zarr 0.5 store got no histogram, so the panel has nothing to draw and "
        "the Auto button has nothing to restore"
    )
    assert sum(histogram["counts"]) > 0
    assert histogram["high"] > histogram["low"]
    assert histogram["autoWindow"]["high"] > histogram["autoWindow"]["low"]

    # The volume window too. That one is always measured from pixels, whatever a store
    # declares, so it was lost just as completely.
    assert found["volumeWindow"] != (0.0, 65535.0), found["volumeWindow"]


def test_the_older_format_still_measures_the_same_specimen(tmp_path):
    """The positive control for the test above: 0.4 always worked and must keep working.

    Without this, the repair could have moved the problem rather than solved it —
    teaching the measurement to read the newer layout while quietly losing the older
    one, which is the layout every instrument in the building writes today. The same
    specimen written both ways has to measure the same, down to the histogram.
    """
    written_the_old_way = measure(
        _write_store(tmp_path / "old_pos001.ome.zarr", [_ramp(64)])
    )
    written_the_new_way = measure(
        _write_store(tmp_path / "new_pos001.ome.zarr", [_ramp(64)], zarr_format=3)
    )
    assert written_the_old_way["window"] == written_the_new_way["window"]
    assert written_the_old_way["volumeWindow"] == written_the_new_way["volumeWindow"]
    assert written_the_old_way["histogram"] == written_the_new_way["histogram"]
