"""Does the scale bar tell the truth about how large the specimen is?

The little white bar in the top-right corner of the viewer, with a number above
it, is the one thing on screen that turns a picture into a measurement. An
operator looks at a cell, compares it with the bar, and writes "roughly 20 µm
across" into a notebook and then into a paper. Nothing else in the viewer is
used that way.

That makes a wrong bar much worse than an ugly one. If the bar reads "50 µm"
while the field of view is really five hundred micrometres wide, the operator is
handed a wrong number carrying the full authority of the instrument, and there is
nothing on screen — no warning, no oddity, no blank panel — that would ever give
it away. ``ScaleBar.jsx`` says as much in its own words: a bar that does not
follow the zoom "would quietly state the wrong size". Until these tests were
written, nothing anywhere in this suite looked at the bar at all.

One fault turned up while these were being written, and it has since been fixed.
In the **3-D view** the bar used to state the scale of the flat view instead of
the volume's — over-stating the demo specimen by about three quarters, by an
amount that changed with the height of the window, and not moving at all when the
volume was magnified. The two views count their zoom differently, and the bar read
the flat view's in both. It was pinned by a test that was expected to fail, that
test began passing the moment the fix landed, and the marker came off; the test is
now the last one in this file. `FAULTS.md`, section I, has the measurement.

Everything before it is about the single-plane view.

So the tests here are all forms of one question: **does the bar agree with the
data and with itself?** They check that

1. the number written above the bar is the length the bar is actually drawn — the
   drawn width in screen pixels, multiplied by how much of the specimen one
   screen pixel covers, comes back to the number on the label;
2. the bar follows the zoom, so that zooming in a hundredfold divides the stated
   length by a hundred instead of leaving a stale number on screen;
3. the bar follows the voxel size the data declares, so that a store recorded at
   0.35 µm per pixel and one recorded at 3.5 µm per pixel do not get the same
   bar; and
4. the number is one a person would write down — a round length in a sensible
   unit, "37 µm" rather than "0.037 mm".

How the arithmetic is checked without simply repeating it
--------------------------------------------------------

A test that recomputed the bar the same way the viewer does would agree with the
viewer no matter how wrong both were. So these tests reach for two things the
viewer's scale-bar code never touches.

The first is the store itself: the voxel size is read straight out of the
OME-Zarr metadata on disk, which is where the truth about the specimen lives.

The second is the drawing engine's magnification, which it calls the *zoom
factor* and which counts how many voxels of the finest resolution level fit into
one screen pixel. One screen pixel therefore covers ``zoom × voxel size`` of the
specimen. That relation is the engine's own definition, used elsewhere in this
suite already (``test_render_acceptance.py`` sets the zoom to ``1/3.5e-7`` and
calls it "one metre per screen pixel"), and it does not depend on any of the
scale bar's own reasoning.

What is deliberately not checked here
-------------------------------------

The bar is drawn as an ordinary web element whose width is given in CSS pixels,
while the engine draws the image itself onto a canvas measured in the screen's
real pixels. On a display where those two are not the same — a HiDPI or "retina"
laptop screen, where one CSS pixel is two or three real ones — the bar could in
principle be scaled differently from the image beside it. The headless browser
these tests run in reports one CSS pixel per real pixel, so nothing here can see
that, and it is worth someone checking by eye on a retina screen.

The drawing engine's own "relative display scale" — a control that lets one axis
be stretched against another — is exercised in
``test_the_picture_can_be_stretched.py`` rather than here. This file used to say
that an operator could not reach that situation because the viewer never put the
control on screen, and that if it were ever exposed the bar would need thinking
about again. The layer panel now offers a stretch per axis, so it is exposed and
it has been thought about: where the axes *on screen* are stretched unevenly
there is no single length that one screen pixel covers, and this viewer draws a
single bar for the first spatial axis it finds. The answer taken was not a
cleverer bar but a warning that no single one can be true — including the part
that is easy to miss, that whether a depth stretch matters depends on whether the
volume is on screen.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path

import numpy as np
import pytest
import zarr
from server import make_server

# The element the viewer labels its scale bar with, and the plain rectangle
# inside it that is the bar. The label sits above the rectangle, so the two are
# read separately: the words from the wrapper, the width from the rectangle.
BAR = "[aria-label='scale bar']"
BAR_RECTANGLE = f"{BAR} > div"

# How long each SI prefix is, in metres. The bar picks its own prefix so that the
# number stays readable, so the test has to be able to read whichever one it
# chose. Anything outside this list is a unit no microscope has any business
# printing, and a test that met one should say so rather than quietly cope.
METRES_IN = {
    "pm": 1e-12,
    "nm": 1e-9,
    "µm": 1e-6,  # MICRO SIGN, which is what the drawing engine emits
    "μm": 1e-6,  # GREEK SMALL LETTER MU, which looks identical and also occurs
    "mm": 1e-3,
    "m": 1.0,
    "km": 1e3,
}

# The lengths the bar is allowed to read, as multiples of a power of ten. These
# are the same seven values ``ScaleBar.jsx`` lists, and they are the reason a
# microscope's scale bar says "2 µm" and never "1.87 µm".
ROUND_LENGTHS = (1.0, 1.5, 2.0, 3.0, 5.0, 7.5, 10.0)

# How much of the specimen the bar aims to span, in screen pixels. It will not be
# exactly this, because the length is rounded to one of the values above first,
# but a bar that has drifted far from it has stopped being a scale bar.
AIMED_AT_PIXELS = 120

# Long-form axis unit names, as OME-Zarr spells them, in metres. Only the ones a
# volume of a specimen would use are here; anything else is left to fail loudly.
METRES_IN_LONG = {"nanometer": 1e-9, "micrometer": 1e-6, "millimeter": 1e-3, "meter": 1.0}


# --------------------------------------------------------------------------
# Reading the bar, and working out independently what it ought to say
# --------------------------------------------------------------------------


def finest_voxel_metres(store: Path) -> float:
    """The smallest voxel edge the store on disk declares, in metres.

    This is the number the whole scale bar rests on. A voxel is one
    three-dimensional pixel of the acquisition, and an OME-Zarr store records how
    large one is in the ``coordinateTransformations`` of its finest resolution
    level — for the demo volume, 2 µm between planes and 0.35 µm within a plane.

    The *smallest* of those edges is what matters, because that is what the
    drawing engine measures its magnification against: its zoom factor counts how
    many of the finest voxels fit into one screen pixel, and "finest" means the
    shortest edge of the ones being displayed.

    Returns the length in metres. Raises if the store does not describe its own
    voxel size, which is a store no scale bar could be honest about anyway.
    """
    described = json.loads((store / ".zattrs").read_text(encoding="utf-8"))
    multiscale = described["multiscales"][0]
    finest = multiscale["datasets"][0]["coordinateTransformations"][0]["scale"]
    spatial = [
        length * METRES_IN_LONG[axis["unit"]]
        for axis, length in zip(multiscale["axes"], finest)
        if axis.get("type") == "space"
    ]
    assert spatial, f"{store} does not say how large a voxel is"
    return min(spatial)


def metres_per_screen_pixel(page, voxel_metres: float) -> float:
    """How much of the specimen one screen pixel covers, right now.

    Worked out from the drawing engine's magnification and the voxel size read
    off the disk, without asking the scale bar anything. That independence is the
    point: this is the yardstick the bar is measured against.
    """
    zoom = page.evaluate("() => window.zmartViewer.navigationState.zoomFactor.value")
    assert isinstance(zoom, (int, float)) and zoom > 0, f"the viewer's zoom reads {zoom!r}"
    return zoom * voxel_metres


def read_bar(page) -> dict:
    """What the bar currently says, and how wide it is currently drawn.

    Comes back as the label's number and unit, that length converted to metres,
    and the width of the drawn rectangle in screen pixels. Raises if there is no
    bar on screen, or if its label is not a number and a length unit — both of
    which are failures worth hearing about rather than skipping past.
    """
    wrapper = page.locator(BAR)
    assert wrapper.count() == 1, (
        f"expected exactly one scale bar on screen, found {wrapper.count()}"
    )
    label = wrapper.inner_text().strip()
    # A plain decimal number and a unit, and nothing else. Anything the pattern
    # turns down is already a failure rather than an inconvenience for the test:
    # a label in scientific notation ("5e-8 mm") is not something an operator can
    # read off a figure, which is the whole reason the bar rounds its length.
    parsed = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*([A-Za-zµμ]+)", label)
    assert parsed, (
        f"the scale bar reads {label!r}, which is not a plain number and a unit "
        "that someone could write on a figure"
    )
    number, unit = float(parsed.group(1)), parsed.group(2)
    assert unit in METRES_IN, (
        f"the scale bar is labelled {label!r}, and {unit!r} is not a length a "
        "microscope should be printing"
    )
    rectangle = page.locator(BAR_RECTANGLE).bounding_box()
    assert rectangle is not None, "the scale bar has a label but nothing drawn under it"
    return {
        "label": label,
        "number": number,
        "unit": unit,
        "metres": number * METRES_IN[unit],
        "pixels": rectangle["width"],
    }


def set_zoom(page, zoom: float) -> None:
    """Change the magnification and wait for the bar to answer.

    The wait is on the label's own text changing, which is exactly the property
    the bar's docstring worries about: a bar that ignores the zoom would sit
    there unchanged and this would time out rather than quietly compare a stale
    reading. Only ever called with a change large enough that the label must
    move.
    """
    before = read_bar(page)["label"]
    page.evaluate(
        "(value) => { window.zmartViewer.navigationState.zoomFactor.value = value; }", zoom
    )
    page.wait_for_function(
        """(before) => {
          const bar = document.querySelector("[aria-label='scale bar']");
          return bar !== null && bar.innerText.trim() !== before;
        }""",
        arg=before,
        timeout=15_000,
    )


def assert_the_label_matches_the_drawing(bar: dict, per_pixel: float, where: str) -> None:
    """The bar's two halves — its words and its width — have to agree.

    The number of pixels the bar spans, times how much of the specimen one pixel
    covers, is the length the bar really represents. That has to be the length
    written above it. This is the check that catches a wrong number, and it does
    not care *how* the bar went wrong: a stale label, a mis-scaled width and a
    unit slipped by a factor of a thousand all fail it the same way.

    The tolerance is one screen pixel's worth, because the bar's width is rounded
    to a whole number of pixels and cannot be more faithful than that. On a bar a
    hundred-odd pixels long that is under one percent, far finer than anything an
    operator could read off the screen by eye.
    """
    drawn = bar["pixels"] * per_pixel
    slack = per_pixel  # one pixel of rounding
    assert abs(drawn - bar["metres"]) <= slack, (
        f"{where}: the bar is labelled {bar['label']} but the {bar['pixels']:.0f} "
        f"pixels it spans are really "
        f"{drawn / METRES_IN[bar['unit']]:.4g} {bar['unit']} of specimen"
    )


# --------------------------------------------------------------------------
# A store whose voxel size we choose ourselves
# --------------------------------------------------------------------------


def write_volume(path: Path, voxel_um: tuple[float, float, float]) -> Path:
    """Write a small OME-Zarr volume that declares the voxel size it is given.

    The demo volume the other tests share knows one voxel size, and one is not
    enough to tell whether the bar reads the data or merely remembers a number.
    So this writes a throwaway volume of a chosen scale. It is deliberately tiny
    — a couple of small planes — because nothing here depends on what is in the
    image, only on what the store says its voxels measure.

    ``voxel_um`` is the (z, y, x) size of one voxel in micrometres. Returns the
    path that was written.
    """
    path.mkdir(parents=True, exist_ok=True)
    group = zarr.open_group(str(path), mode="w", zarr_format=2)
    array = group.create_array("0", shape=(1, 2, 256, 256), chunks=(1, 1, 256, 256), dtype="uint16")
    # A gradient rather than a flat block, so that if anyone ever looks at a
    # screenshot of this they can see an image rather than a solid colour.
    plane = np.add.outer(np.arange(256), np.arange(256)).astype("uint16") * 40
    array[0, 0] = plane
    array[0, 1] = plane
    (path / ".zattrs").write_text(
        json.dumps(
            {
                "multiscales": [
                    {
                        "version": "0.4",
                        "axes": [
                            {"name": "c", "type": "channel"},
                            {"name": "z", "type": "space", "unit": "micrometer"},
                            {"name": "y", "type": "space", "unit": "micrometer"},
                            {"name": "x", "type": "space", "unit": "micrometer"},
                        ],
                        "datasets": [
                            {
                                "path": "0",
                                "coordinateTransformations": [
                                    {"type": "scale", "scale": [1.0, *voxel_um]}
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
                            "window": {"min": 0, "max": 65535, "start": 0, "end": 8000},
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def bar_for_voxel_size(browser, built_dist, tmp_path):
    """Open the viewer on a volume of a chosen voxel size and read its scale bar.

    Hands back a function taking the (z, y, x) voxel size in micrometres and a
    magnification to set, and returning the bar's reading together with the
    yardstick it should be judged against. Each volume gets its own short-lived
    server and page, and the page is closed before the next one opens: two viewers
    drawing at once on a small machine is a way to fail on tiredness rather than
    on anything true.
    """
    running: list = []

    def measure(voxel_um: tuple[float, float, float], zoom: float) -> dict:
        folder = tmp_path / f"voxels-{voxel_um[2]}"
        store = write_volume(folder / "overview_pos001.ome.zarr", voxel_um)
        server = make_server(
            port=0,
            data_dir=folder,
            site_dir=built_dist,
            store=store.name,
            live=False,
            allow_open=False,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        running.append((server, thread))
        page = browser.new_page(viewport={"width": 1200, "height": 900})
        try:
            page.goto(f"http://127.0.0.1:{server.server_address[1]}", wait_until="domcontentloaded")
            page.wait_for_function("() => window.zmartViewer !== undefined", timeout=30_000)
            page.wait_for_selector(BAR, timeout=30_000)
            # Both volumes are looked at from the same distance, so that any
            # difference in their bars can only have come from the data.
            page.evaluate(
                "(value) => { window.zmartViewer.navigationState.zoomFactor.value = value; }",
                zoom,
            )
            page.wait_for_timeout(700)
            declared = finest_voxel_metres(store)
            return {
                "bar": read_bar(page),
                "per_pixel": metres_per_screen_pixel(page, declared),
                "voxel_metres": declared,
            }
        finally:
            page.close()
            server.shutdown()
            thread.join(timeout=5)

    try:
        yield measure
    finally:
        for server, thread in running:
            server.shutdown()
            thread.join(timeout=5)


@pytest.fixture
def demo_voxel_metres(demo_store: Path) -> float:
    """The demo volume's finest voxel edge, read from its own metadata on disk."""
    return finest_voxel_metres(demo_store / "demo.zarr")


# --------------------------------------------------------------------------
# The number on the bar is the length the bar is drawn
# --------------------------------------------------------------------------


class TestTheLabelAndTheDrawingAgree:
    """The bar's words and the bar's width must describe the same length.

    An operator reads a measurement off this by holding the bar up against a cell
    and multiplying. That only works if the drawn rectangle really is as long as
    the label claims, so this is the most important thing in the file.
    """

    def test_the_bar_is_on_screen_at_all(self, viewer_page):
        """A bar that is missing is its own kind of failure, and easy to overlook.

        Everything below reads the bar, so all of it would fail if the bar were
        gone — but it would fail with a confusing message about a locator. This
        says the plain thing first: the viewer opens with a scale bar showing.
        """
        bar = read_bar(viewer_page)
        assert bar["pixels"] > 10, f"the bar is drawn only {bar['pixels']} pixels wide"

    def test_the_stated_length_is_the_length_that_is_drawn(
        self, viewer_page, demo_voxel_metres
    ):
        """The whole point of the file, on the volume the viewer opens with.

        The demo volume records 0.35 µm to a pixel within a plane, and the viewer
        opens looking at it one voxel to a screen pixel — so a bar spanning about
        a hundred and forty pixels is covering about fifty micrometres of
        specimen, and the label had better say so.
        """
        bar = read_bar(viewer_page)
        per_pixel = metres_per_screen_pixel(viewer_page, demo_voxel_metres)
        assert_the_label_matches_the_drawing(bar, per_pixel, "as the viewer opens")

    def test_the_bar_is_drawn_near_the_length_it_aims_for(
        self, viewer_page, demo_voxel_metres
    ):
        """The bar is meant to be about a hundred and twenty pixels long.

        It will never be exactly that, because the length is rounded to a round
        number first, but rounding can only move it by so much: the round lengths
        are never more than one and a half times apart, so the bar cannot end up
        half or double the size it aimed for. A bar far outside that range has
        stopped being about the zoom at all, and would also be either invisible or
        running off the edge of the picture.
        """
        bar = read_bar(viewer_page)
        assert AIMED_AT_PIXELS / 2 < bar["pixels"] < AIMED_AT_PIXELS * 2, (
            f"the bar aims for about {AIMED_AT_PIXELS} pixels and was drawn "
            f"{bar['pixels']:.0f}"
        )


# --------------------------------------------------------------------------
# It follows the zoom
# --------------------------------------------------------------------------


class TestItFollowsTheZoom:
    """A bar frozen at its opening value is the fault its own docstring warns of.

    This is not a far-fetched way to break the viewer. The bar computes itself
    once when the page opens and then again whenever the drawing engine says the
    view has moved; drop that second half — by listening to the wrong signal, or
    by remembering a value it should have recomputed — and the viewer still looks
    perfectly finished. It just states the size the specimen *was* at the moment
    the page opened, for the rest of the session.
    """

    def test_zooming_in_a_thousandfold_divides_the_stated_length_by_a_thousand(
        self, viewer_page, demo_voxel_metres
    ):
        """A thousand times closer means a thousandth as much specimen across the bar.

        A factor of a thousand is chosen because it is exactly one step of the SI
        prefixes — micrometres to nanometres. So the expected answer is not merely
        "smaller", or "roughly a thousand times smaller": it is the *same* round
        number with the next unit down, drawn the same number of pixels wide.
        Fifty micrometres becomes fifty nanometres, and there is no slack in that
        for a nearly-right bar to hide in.
        """
        before = read_bar(viewer_page)
        zoom = viewer_page.evaluate(
            "() => window.zmartViewer.navigationState.zoomFactor.value"
        )
        set_zoom(viewer_page, zoom / 1000)
        after = read_bar(viewer_page)

        assert after["metres"] == pytest.approx(before["metres"] / 1000, rel=0.01), (
            f"zoomed in a thousandfold, the bar went from {before['label']} to "
            f"{after['label']}, which is not a thousand times shorter"
        )
        assert after["number"] == pytest.approx(before["number"], rel=0.01), (
            f"{before['label']} should have become the same number in the next unit "
            f"down, and instead reads {after['label']}"
        )
        assert after["pixels"] == pytest.approx(before["pixels"], abs=1.5)
        assert_the_label_matches_the_drawing(
            after, metres_per_screen_pixel(viewer_page, demo_voxel_metres),
            "after zooming in a thousandfold",
        )

    def test_zooming_out_a_thousandfold_lengthens_it_by_the_same_factor(
        self, viewer_page, demo_voxel_metres
    ):
        """And the other direction, which is not the same journey back.

        Zooming out is how an operator finds their way around a mosaic, and it is
        where a bar with the factor the wrong way up would be most obviously wrong
        and least often looked at. Fifty micrometres becomes fifty millimetres.
        """
        before = read_bar(viewer_page)
        zoom = viewer_page.evaluate(
            "() => window.zmartViewer.navigationState.zoomFactor.value"
        )
        set_zoom(viewer_page, zoom * 1000)
        after = read_bar(viewer_page)

        assert after["metres"] == pytest.approx(before["metres"] * 1000, rel=0.01), (
            f"zoomed out a thousandfold, the bar went from {before['label']} to "
            f"{after['label']}"
        )
        assert after["number"] == pytest.approx(before["number"], rel=0.01), (
            f"{before['label']} should have become the same number in the next unit "
            f"up, and instead reads {after['label']}"
        )
        assert_the_label_matches_the_drawing(
            after, metres_per_screen_pixel(viewer_page, demo_voxel_metres),
            "after zooming out a thousandfold",
        )

    def test_the_label_agrees_with_the_drawing_at_every_magnification(
        self, viewer_page, demo_voxel_metres
    ):
        """Walked across nine decades of zoom, checking the bar at each stop.

        A microscopist really does travel this far in one session: from a whole
        mosaic several millimetres across down to a single organelle. The bar has
        to be honest at every stop, not only at the one the page happened to open
        at, and awkward magnifications — the ones that fall between two round
        lengths — are where an off-by-a-factor mistake shows up.
        """
        opening = viewer_page.evaluate(
            "() => window.zmartViewer.navigationState.zoomFactor.value"
        )
        for factor in (1e-3, 1e-2, 0.1, 0.3, 3, 30, 300, 3000, 1e4):
            set_zoom(viewer_page, opening * factor)
            bar = read_bar(viewer_page)
            per_pixel = metres_per_screen_pixel(viewer_page, demo_voxel_metres)
            assert_the_label_matches_the_drawing(
                bar, per_pixel, f"at {factor:g} times the opening magnification"
            )
            assert AIMED_AT_PIXELS / 2 < bar["pixels"] < AIMED_AT_PIXELS * 2, (
                f"at {factor:g} times the opening magnification the bar was drawn "
                f"{bar['pixels']:.0f} pixels wide"
            )


# --------------------------------------------------------------------------
# It follows the voxel size the data declares
# --------------------------------------------------------------------------


class TestItReadsTheVoxelSizeFromTheData:
    """How large a voxel is comes from the acquisition, and the bar must use it.

    This is the check that no amount of zooming can make. A bar that had the zoom
    perfectly right but the voxel size wrong — hard-coded, or read from the wrong
    axis — would move correctly as the operator zoomed and still be wrong by a
    constant factor everywhere, which is exactly the kind of error that survives
    a careful look.
    """

    def test_a_tenfold_coarser_voxel_gets_a_tenfold_longer_bar(self, bar_for_voxel_size):
        """Two volumes, ten times apart in scale, looked at from the same distance.

        One declares 0.35 µm voxels — a typical high-magnification objective — and
        the other 3.5 µm, which is what a low-magnification overview of a cleared
        specimen looks like. At the same magnification the second shows ten times
        as much specimen across the same screen, so its bar must state ten times
        the length. Since ten is a power of ten and the bar's round lengths are a
        value times a power of ten, the bar should read the same number with the
        next unit up and be drawn the same width.
        """
        fine = bar_for_voxel_size((2.0, 0.35, 0.35), zoom=1.0)
        coarse = bar_for_voxel_size((20.0, 3.5, 3.5), zoom=1.0)

        assert coarse["voxel_metres"] == pytest.approx(fine["voxel_metres"] * 10), (
            "the two stores were not written ten times apart after all"
        )
        assert coarse["bar"]["metres"] == pytest.approx(
            fine["bar"]["metres"] * 10, rel=0.01
        ), (
            "a store with ten times coarser voxels was given a bar reading "
            f"{coarse['bar']['label']} where the fine one reads "
            f"{fine['bar']['label']} — the bar is not reading the voxel size"
        )
        assert coarse["bar"]["pixels"] == pytest.approx(fine["bar"]["pixels"], abs=1.5)

    def test_each_of_them_is_honest_about_its_own_specimen(self, bar_for_voxel_size):
        """And both bars separately agree with the store they were drawn for.

        The comparison above would still pass if both bars were wrong by the same
        factor, so each is also measured against its own store's declared voxel
        size. Between them, the two tests pin the bar to the data rather than only
        to itself.
        """
        for voxel_um in ((2.0, 0.35, 0.35), (20.0, 3.5, 3.5)):
            measured = bar_for_voxel_size(voxel_um, zoom=1.0)
            assert_the_label_matches_the_drawing(
                measured["bar"],
                measured["per_pixel"],
                f"on a store declaring {voxel_um[2]} µm voxels",
            )


# --------------------------------------------------------------------------
# The number is one a person would write down
# --------------------------------------------------------------------------


class TestTheNumberIsOneAPersonWouldWrite:
    """A scale bar is only useful if the number on it is one you can reason with.

    This is the intent ``ScaleBar.jsx`` states at the top of the file, and it is a
    real convenience rather than a decoration: "50 µm" can be halved and doubled
    in your head against a cell on screen, and "0.0472 mm" cannot. The tests here
    pin that intent so that a change which starts printing awkward numbers is
    caught, rather than quietly making the viewer harder to measure with.
    """

    def test_the_length_is_always_one_of_the_round_numbers(
        self, viewer_page, demo_voxel_metres
    ):
        """Across nine decades of zoom, the number is a round one every time.

        The bar is allowed 1, 1.5, 2, 3, 5, 7.5 or 10 times a power of ten. With
        the unit chosen to suit, that leaves a small set of labels — 1 through
        750 — and the number on screen must be one of them however awkward the
        magnification.
        """
        allowed = {
            round(significand * step, 6)
            for significand in ROUND_LENGTHS
            for step in (1, 10, 100)
        }
        opening = viewer_page.evaluate(
            "() => window.zmartViewer.navigationState.zoomFactor.value"
        )
        seen = []
        for factor in (1e-3, 0.007, 0.1, 0.42, 3, 17, 300, 2600, 1e4):
            set_zoom(viewer_page, opening * factor)
            bar = read_bar(viewer_page)
            seen.append(bar["label"])
            assert round(bar["number"], 6) in allowed, (
                f"the bar read {bar['label']}, and {bar['number']} is not a round "
                "length anyone would write on a figure"
            )
        # And the walk really did visit several different lengths, so that this is
        # a test of many labels rather than of one label nine times over.
        assert len(set(seen)) >= 5, f"the zoom walk barely moved the bar: {seen}"

    def test_the_unit_changes_rather_than_the_number_becoming_a_fraction(
        self, viewer_page
    ):
        """Zooming in walks millimetres down to micrometres down to nanometres.

        The alternative — keeping one unit and letting the number shrink — is what
        gives you "0.037 mm" on a figure, which is both harder to read and easy to
        misplace a decimal point in. So the number is kept between 1 and 1000 and
        the unit does the moving, which is what every microscope's own scale bar
        does.
        """
        opening = viewer_page.evaluate(
            "() => window.zmartViewer.navigationState.zoomFactor.value"
        )
        units = set()
        for factor in (1e-3, 0.1, 3, 300, 1e4):
            set_zoom(viewer_page, opening * factor)
            bar = read_bar(viewer_page)
            units.add(bar["unit"])
            assert 1.0 <= bar["number"] < 1000.0, (
                f"the bar read {bar['label']} — the number should stay between 1 "
                "and 1000 and let the unit move instead"
            )
        assert len(units) >= 3, (
            "across four decades of zoom the bar never changed its unit, so it is "
            f"not walking down the scale as it was meant to: {sorted(units)}"
        )


# --------------------------------------------------------------------------
# The volume view, where the bar means something different
# --------------------------------------------------------------------------


def test_the_bar_is_honest_in_the_volume_view_too(viewer_page, demo_voxel_metres):
    """The bar must mean the same thing when the operator turns the volume on.

    Judging a cleared specimen is done in the volume view as much as in a single
    plane, and the bar sits in the same corner saying the same sort of thing, so
    an operator has every reason to read a measurement off it there. That makes a
    wrong number in this view no less serious than a wrong number in the flat one.

    The magnification is worked out here the way the drawing engine works it out
    for a volume panel: the volume view keeps its own zoom, and that zoom counts
    across the whole height of the panel rather than one screen pixel — so one
    pixel covers the zoom divided by the panel's height, times the size of a
    voxel.
    """
    viewer_page.click("text=3D")
    viewer_page.wait_for_timeout(5000)

    panel = viewer_page.locator(".neuroglancer-panel").bounding_box()
    volume_zoom = viewer_page.evaluate(
        "() => window.zmartViewer.perspectiveNavigationState.zoomFactor.value"
    )
    per_pixel = volume_zoom / panel["height"] * demo_voxel_metres
    assert_the_label_matches_the_drawing(
        read_bar(viewer_page), per_pixel, "in the volume view"
    )

    # And it has to follow the volume's own zoom, for the same reason the flat
    # view's bar has to follow that view's zoom: a bar that stays put while the
    # specimen grows on screen is quietly stating the wrong size.
    before = read_bar(viewer_page)["label"]
    viewer_page.evaluate(
        "() => { window.zmartViewer.perspectiveNavigationState.zoomFactor.value /= 20; }"
    )
    viewer_page.wait_for_timeout(3000)
    assert read_bar(viewer_page)["label"] != before, (
        f"the volume was magnified twentyfold and the bar still reads {before}"
    )
