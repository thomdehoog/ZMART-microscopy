"""Measure whether the layer stack described in `LAYERS.md` actually works.

Run it with::

    python viz_studio/layer_stack/measure.py --out /somewhere/to/put/the/results

It writes a folder of photographs and a ``results.json`` beside them, and prints
a readable summary as it goes. ``--only "part of a name"`` runs a single
measurement, which is what you want while working on one.

The arrangement being tested has three layers inside the engine's flat view:
the plate layout at the bottom, the tiles the operator chose for this run above
it, and the acquisition itself on top, with room nobody has imaged drawn
see-through so that the two layers below show through it.

All of it rests on one assumption that had never been checked — that a layer
underneath gives the layer above its transparency back. That is measured first,
and if it fails nothing else matters.

Two rules govern every number here, and both were learned the hard way in this
repository.

**Every answer comes from a photograph.** Nothing below asks the engine whether
it is satisfied. An engine can report itself perfectly happy while drawing
nothing at all, and it can report the right position while showing an older
frame. What reaches the screen is the only thing an operator sees, so it is the
only thing measured.

**Every check is broken on purpose and shown to fail.** A check that has never
been seen to fail is not evidence of anything. Where a measurement below asserts
something, it is run again with the thing it depends on deliberately broken, and
the report gives both readings side by side.
"""

from __future__ import annotations

import argparse
import io
import json
import shutil
import sys
import threading
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_VIZ = _HERE.parent
_REPO = _VIZ.parent
# This folder must come first. The sandwich probe next door has a ``make_stores``
# of its own, and whichever folder is searched first is the one that wins — so
# putting this one last in the list below (and therefore first in the search
# order, since each is inserted at the front) is what makes ``import make_stores``
# mean the stores for these measurements rather than those for that one.
for extra in (str(_REPO), str(_VIZ / "tests"), str(_VIZ / "sandwich"), str(_HERE)):
    if extra in sys.path:
        sys.path.remove(extra)
    sys.path.insert(0, extra)

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

import make_stores  # noqa: E402
from probe_server import Ledger, make_probe_server  # noqa: E402

# The browser this machine actually has. The version Playwright would reach for
# by default is not installed here and cannot be downloaded, so it is named
# outright.
CHROMIUM = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

# Software rendering. There is no graphics card on this machine, and without
# these the drawing surface is simply blank — the engine needs WebGL2 and gets
# none. What that costs these particular measurements is very little: they are
# about what colour a pixel comes out, not about how often a frame arrives.
SOFTWARE_GL = ["--use-gl=angle", "--use-angle=swiftshader", "--ignore-gpu-blocklist"]

WINDOW = {"width": 900, "height": 700}

# The colour behind everything, as the page is told to set it and as it should
# then appear in a photograph. Having it written in both places on purpose is
# what lets a measurement say "this pixel is the background" rather than "this
# pixel is dark, which probably means nothing was drawn".
BACKGROUND_HEX = "#3060a0"
BACKGROUND_RGB = (0x30, 0x60, 0xA0)


class Probe:
    """The server, a browser, and one page of the probe, held open together."""

    def __init__(self, data_dir: Path, out: Path):
        self.data_dir = data_dir
        self.out = out
        self.ledger = Ledger()
        self.server = make_probe_server(
            port=0,
            site_dir=_HERE / "page" / "dist",
            data_dir=data_dir,
            ledger=self.ledger,
        )
        self.port = self.server.server_address[1]
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()
        self._playwright = None
        self.browser = None
        self.page = None
        self.console: list[str] = []

    def __enter__(self):
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self.browser = self._playwright.chromium.launch(
            args=SOFTWARE_GL, executable_path=CHROMIUM
        )
        return self

    def __exit__(self, *_):
        if self.browser:
            self.browser.close()
        if self._playwright:
            self._playwright.stop()
        self.server.shutdown()
        self._thread.join(timeout=5)

    def open(self, layers, *, cx: float, cy: float, um_per_pixel: float,
             background: str = BACKGROUND_HEX):
        """Open the probe with the given stack, bottom of the stack first.

        ``layers`` is a list of dictionaries, each naming the store to draw and
        the shader to draw it with. It is handed over as a piece of JSON in the
        address, so one built page serves every arrangement in this file.
        """
        if self.page:
            self.page.close()
        context = self.browser.new_context(viewport=dict(WINDOW), device_scale_factor=1)
        self.page = context.new_page()
        self.console = []
        self.page.on("console", lambda m: self.console.append(f"{m.type}: {m.text}"))
        self.page.on("pageerror", lambda e: self.console.append(f"pageerror: {e}"))
        asked = {
            "layers": json.dumps(layers),
            "bg": background,
            "cx": cx,
            "cy": cy,
            "umpp": um_per_pixel,
        }
        from urllib.parse import urlencode

        self.page.goto(
            f"http://127.0.0.1:{self.port}/?{urlencode(asked)}",
            wait_until="domcontentloaded",
        )
        self.page.wait_for_function(
            "() => window.probe && (window.probe.ready || window.probe.failed)",
            timeout=90_000,
        )
        failed = self.page.evaluate("() => window.probe.failed")
        if failed:
            raise RuntimeError(f"the probe page could not start: {failed}")
        self.view = {"cx": cx, "cy": cy, "umPerPixel": um_per_pixel}
        self.settle()
        return self.page

    def settle(self, tries: int = 80) -> None:
        """Wait until the photograph stops changing.

        Asked of the pixels rather than of the engine. The engine announces that
        it has finished long before the last piece of image has arrived and been
        drawn, so waiting on its own account of itself would photograph a picture
        that was still filling in.
        """
        last = None
        same = 0
        for _ in range(tries):
            now = self.photograph()
            if last is not None and np.array_equal(now, last):
                same += 1
                if same >= 2:
                    return
            else:
                same = 0
            last = now
            time.sleep(0.2)

    def photograph(self):
        """One photograph of the window, as height by width by red-green-blue."""
        shot = self.page.screenshot()
        return np.array(Image.open(io.BytesIO(shot)).convert("RGB"))

    def save(self, picture, name: str) -> str:
        Image.fromarray(picture).save(self.out / f"{name}.png")
        return f"{name}.png"

    def believes(self, expression: str):
        """Ask the page something. Never a verdict — only a handle or a diagnosis."""
        return self.page.evaluate(f"() => {expression}")

    def act(self, expression: str):
        result = self.page.evaluate(f"() => {expression}")
        self.settle()
        return result

    # -- turning micrometres into places in a photograph -------------------

    def where(self, picture, x_um: float, y_um: float) -> tuple[int, int]:
        """Where a point of specimen lands in this photograph, as (row, column).

        Worked out from the view the page was given rather than from anything the
        engine says, so that if the engine draws in the wrong place the reading
        moves and the measurement notices.
        """
        scale = picture.shape[1] / WINDOW["width"]
        column = ((x_um - self.view["cx"]) / self.view["umPerPixel"]
                  + WINDOW["width"] / 2) * scale
        row = ((y_um - self.view["cy"]) / self.view["umPerPixel"]
               + WINDOW["height"] / 2) * scale
        return int(round(row)), int(round(column))

    def patch(self, picture, x_um: float, y_um: float, radius: int = 6) -> dict:
        """The average colour of a small patch of specimen, and how even it is.

        A patch rather than a single pixel because a single pixel can land on the
        soft edge of something and report a colour that is nowhere in the
        picture. The spread is handed back with it so that a patch straddling two
        colours can be recognised as such rather than averaged into a third.
        """
        row, column = self.where(picture, x_um, y_um)
        block = picture[
            max(0, row - radius):row + radius + 1,
            max(0, column - radius):column + radius + 1,
        ]
        if block.size == 0:
            return {"rgb": None, "spread": None, "at": [row, column]}
        return {
            "rgb": [int(round(v)) for v in block.reshape(-1, 3).mean(axis=0)],
            "spread": round(float(block.reshape(-1, 3).std(axis=0).max()), 1),
            "at": [row, column],
        }


# ---------------------------------------------------------------------------
# Reading colours out of a photograph
# ---------------------------------------------------------------------------


def names_the_colour(rgb) -> str:
    """Say plainly which of the things being drawn a colour belongs to.

    The measurements give each layer a saturated colour that nothing else in the
    picture could produce, so this needs no threshold anybody could argue about:
    it simply says which of a handful of known colours is nearest, and refuses to
    answer if none of them is close.
    """
    if rgb is None:
        return "off the picture"
    # Acquired picture is drawn in greys, so a patch whose three colours are
    # nearly equal is picture rather than any of the flat colours below. This is
    # checked first because a mid grey happens to sit fairly near the background
    # blue, and calling acquired picture "the background" would turn the one
    # reading question 3 asks into nonsense.
    spread_of_colour = max(rgb) - min(rgb)
    if spread_of_colour < 25:
        if max(rgb) < 20:
            return "black"
        if min(rgb) > 235:
            return "white"
        return f"acquired picture (grey, {int(sum(rgb) / 3)})"
    known = {
        "the lower layer (green)": (0, 255, 0),
        "the upper layer (red)": (255, 0, 0),
        "the background": BACKGROUND_RGB,
        "black": (0, 0, 0),
        "white": (255, 255, 255),
        "yellow": (255, 255, 0),
        "magenta": (255, 0, 255),
    }
    best, distance = None, None
    for name, want in known.items():
        gap = sum((int(a) - int(b)) ** 2 for a, b in zip(rgb, want)) ** 0.5
        if distance is None or gap < distance:
            best, distance = name, gap
    if distance > 90:
        return f"something else, {tuple(int(v) for v in rgb)}"
    return best


def describe(patch: dict) -> str:
    """One readable line for a patch of photograph, whatever shape it came in.

    Different measurements record a patch under different names — one calls the
    average colour ``rgb`` and another ``colour`` — so this looks for either
    rather than insisting on one. It is only used for the summary printed while
    a run goes by; the numbers themselves are kept in full in ``results.json``.
    """
    rgb = patch.get("rgb", patch.get("colour"))
    extra = ""
    if patch.get("spread") is not None:
        extra = f", varying by {patch['spread']}"
    elif patch.get("how varied") is not None:
        extra = f", varying by {patch['how varied']}"
    return f"{names_the_colour(rgb)} {tuple(rgb or ())}{extra}"


# ---------------------------------------------------------------------------
# Question 1: does a layer underneath give the layer above its transparency back?
# ---------------------------------------------------------------------------
#
# This is the load-bearing one. The engine turns blending off for whichever layer
# it draws first and leaves it on for every layer after that. The reasoning
# everything else rests on is that putting the plate underneath therefore makes
# the acquisition the second or third layer, so its alpha survives and the
# see-through parts really are see-through.
#
# The measurement is two image layers on exactly the same ground. The lower one
# is imaged everywhere and drawn green. The upper one is imaged over its left
# half only and drawn red, with a shader that makes anything never written
# see-through. So the right half of the picture is the whole question: green
# means the lower layer shows through and the arrangement works; anything else
# means it does not.

# The stores for this question are 1024 voxels across at a micrometre each, so
# the specimen is 1024 micrometres square with its middle at (512, 512).
TRANSPARENCY_MIDDLE = 512.0
# Two micrometres to a screen pixel puts the 1024-micrometre square at 512 pixels
# across in a 900 by 700 window, which leaves plenty of background visible around
# it. The background has to stay visible: it is how a measurement tells "nothing
# was drawn here" from "something was drawn here in a dark colour".
TRANSPARENCY_UM_PER_PIXEL = 2.0

# The three places every photograph in this question is read at, in micrometres
# on the specimen.
WHERE_THE_UPPER_LAYER_WAS_WRITTEN = (256.0, 512.0)
WHERE_NOBODY_IMAGED = (768.0, 512.0)
WELL_OUTSIDE_BOTH = (-300.0, 512.0)


def _read_the_three_places(probe: Probe, picture) -> dict:
    return {
        "where the upper layer was written": probe.patch(
            picture, *WHERE_THE_UPPER_LAYER_WAS_WRITTEN),
        "where nobody imaged": probe.patch(picture, *WHERE_NOBODY_IMAGED),
        "well outside both": probe.patch(picture, *WELL_OUTSIDE_BOTH),
    }


def _open_the_two_layers(probe: Probe, *, upper_shader: str = "red",
                         upper_opacity: float = 1.0,
                         lower_opacity: float = 1.0):
    return probe.open(
        [
            {"store": "under", "shader": "green", "opacity": lower_opacity},
            {"store": "over", "shader": upper_shader, "opacity": upper_opacity},
        ],
        cx=TRANSPARENCY_MIDDLE,
        cy=TRANSPARENCY_MIDDLE,
        um_per_pixel=TRANSPARENCY_UM_PER_PIXEL,
    )


def measure_transparency(probe: Probe) -> dict:
    """Does the lower layer show through the upper layer's see-through half?"""
    found = {}

    # -- with a layer underneath ------------------------------------------
    _open_the_two_layers(probe)
    picture = probe.photograph()
    found["with a layer underneath"] = {
        "photograph": probe.save(picture, "1-with-a-layer-underneath"),
        "layers the engine says it drew": probe.believes("window.probe.drawnLayers()"),
        "read": _read_the_three_places(probe, picture),
    }

    # -- with the lower layer taken away ----------------------------------
    #
    # Not hidden but genuinely absent, so that the upper layer is the only thing
    # in the stack and is therefore the one the engine draws first.
    probe.open(
        [{"store": "over", "shader": "red", "opacity": 1.0}],
        cx=TRANSPARENCY_MIDDLE,
        cy=TRANSPARENCY_MIDDLE,
        um_per_pixel=TRANSPARENCY_UM_PER_PIXEL,
    )
    picture = probe.photograph()
    found["with the lower layer taken away"] = {
        "photograph": probe.save(picture, "1-with-the-lower-layer-taken-away"),
        "layers the engine says it drew": probe.believes("window.probe.drawnLayers()"),
        "read": _read_the_three_places(probe, picture),
    }

    # -- the deliberate breakage ------------------------------------------
    #
    # The reading above claims that green appearing on the right-hand side means
    # the lower layer is showing through. That claim is worth nothing unless the
    # same reading can be shown to report something different when the lower
    # layer is genuinely hidden. So the upper layer is drawn with a shader that
    # is opaque everywhere, including over ground nobody imaged. The lower layer
    # is still there, still underneath, still green — and it must now be
    # invisible. If the reading still says green, it is not measuring what it
    # claims to measure.
    _open_the_two_layers(probe, upper_shader="redopaque")
    picture = probe.photograph()
    found["broken on purpose: the upper layer made opaque"] = {
        "photograph": probe.save(picture, "1-broken-upper-layer-opaque"),
        "read": _read_the_three_places(probe, picture),
    }
    return found


def measure_switching_the_lower_layer_off(probe: Probe) -> dict:
    """What happens to the acquisition when the operator hides the plate.

    This follows straight from the question above and would otherwise arrive
    later as a mystery. If the upper layer's transparency depends on there being
    something underneath it, then hiding the plate changes how the acquisition
    itself is drawn — and an operator who simply wanted the plate out of the way
    would have no reason at all to connect the two things.

    Two ways of putting a layer out of sight are tried, because they are not the
    same thing. **Hiding** it takes it out of the list the engine draws, so
    whatever was above it moves down and becomes the first layer. Setting its
    **opacity to nought** leaves it in that list drawing nothing, which — if it
    still holds its place — would let the plate be taken off the screen without
    disturbing the layer above at all.
    """
    found = {}

    _open_the_two_layers(probe)
    picture = probe.photograph()
    found["both layers shown"] = {
        "photograph": probe.save(picture, "1b-both-shown"),
        "layers the engine says it drew": probe.believes("window.probe.drawnLayers()"),
        "read": _read_the_three_places(probe, picture),
    }

    left = probe.act("window.probe.setVisible('under', false)")
    picture = probe.photograph()
    found["the lower layer hidden"] = {
        "photograph": probe.save(picture, "1b-lower-layer-hidden"),
        "layers the engine says it drew": left,
        "read": _read_the_three_places(probe, picture),
    }

    probe.act("window.probe.setVisible('under', true)")
    left = probe.act("window.probe.setOpacity('under', 0.0)")
    picture = probe.photograph()
    found["the lower layer left loaded at nought opacity"] = {
        "photograph": probe.save(picture, "1b-lower-layer-zero-opacity"),
        "layers the engine says it drew": probe.believes("window.probe.drawnLayers()"),
        "read": _read_the_three_places(probe, picture),
    }
    return found


# ---------------------------------------------------------------------------
# Can several layers show different rectangles of one store?
# ---------------------------------------------------------------------------
#
# A promising idea is to stop drawing one layer across a run's whole declared
# canvas and instead give each imaged region a bounded layer of its own, so that
# ground nobody visited has nothing drawn over it and is see-through by
# construction rather than by asking how bright a voxel is.
#
# The danger is that it quietly turns into one *store* per region. That would be
# fatal: this project writes one sparse image per acquisition type, with tiles
# landing straight into their places and no stitching, and the coordinate
# system, the coverage record and the whole layout depend on that. So the
# question is narrow and worth settling on its own: can several layers each show
# a different rectangle of *one* store on disk?
#
# Three things are tried, in order of how much they would buy.

# A translation big enough to put a second copy of the 1024-micrometre square
# clear of the first, so that a photograph can tell "two layers drawn apart" from
# "two layers exactly on top of one another".
CROP_SHIFT_UM = 1400.0


def _identity_with_shift(shift_x_um: float) -> dict:
    """A source transform: the store's own axes, moved sideways.

    An image written by this project declares five axes — the moment, the colour,
    and then depth, height and width — so the matrix is five rows of six numbers:
    five for the axes themselves and a last column that shifts them.
    """
    names = ["t", "c", "z", "y", "x"]
    matrix = []
    for row in range(5):
        line = [1.0 if row == column else 0.0 for column in range(5)]
        line.append(shift_x_um if names[row] == "x" else 0.0)
        matrix.append(line)
    return {
        "matrix": matrix,
        "outputDimensions": {
            "t": [1, "s"],
            "c": [1, ""],
            "z": [1e-6, "m"],
            "y": [1e-6, "m"],
            "x": [1e-6, "m"],
        },
    }


def measure_two_layers_over_one_store(probe: Probe) -> dict:
    """Can one store on disk feed several layers, and can they be cropped?"""
    found = {}
    url = f"http://127.0.0.1:{probe.port}/data/under.ome.zarr/|zarr2:"

    # -- two layers, one store, no transform ------------------------------
    #
    # The first thing to establish is the cheap half of the question: whether the
    # engine will accept two layers pointing at the same store at all. Drawn one
    # green and one red, with the red on top and opaque, the picture says plainly
    # whether both were built.
    probe.open(
        [
            {"store": "under", "shader": "green", "opacity": 1.0, "source": url},
            {"store": "again", "shader": "redopaque", "opacity": 1.0, "source": url},
        ],
        cx=TRANSPARENCY_MIDDLE, cy=TRANSPARENCY_MIDDLE,
        um_per_pixel=TRANSPARENCY_UM_PER_PIXEL,
    )
    picture = probe.photograph()
    found["two layers pointing at one store"] = {
        "photograph": probe.save(picture, "1c-two-layers-one-store"),
        "layers the engine says it drew": probe.believes("window.probe.drawnLayers()"),
        "read": {
            "over the store": probe.patch(picture, 512.0, 512.0),
            "well outside it": probe.patch(picture, -300.0, 512.0),
        },
    }

    # -- two layers, one store, one of them moved sideways ----------------
    #
    # If a layer can be given a transform of its own then the two can at least be
    # *placed* independently, which is the half of the idea that does not need
    # cropping. Photographed side by side so that the reading cannot be confused
    # with one layer drawn twice in the same place.
    probe.open(
        [
            {"store": "under", "shader": "green", "opacity": 1.0,
             "source": {"url": url, "transform": _identity_with_shift(0.0)}},
            {"store": "again", "shader": "red", "opacity": 1.0,
             "source": {"url": url,
                        "transform": _identity_with_shift(CROP_SHIFT_UM)}},
        ],
        cx=TRANSPARENCY_MIDDLE + CROP_SHIFT_UM / 2,
        cy=TRANSPARENCY_MIDDLE,
        um_per_pixel=4.0,
    )
    picture = probe.photograph()
    found["one store, two layers, one moved sideways"] = {
        "photograph": probe.save(picture, "1c-one-store-two-places"),
        "read": {
            "where the unmoved layer is": probe.patch(picture, 512.0, 512.0),
            "where the moved layer should be": probe.patch(
                picture, 512.0 + CROP_SHIFT_UM, 512.0),
            "between the two": probe.patch(
                picture, 512.0 + CROP_SHIFT_UM / 2, 512.0),
        },
    }

    # -- and the thing that would actually be needed ----------------------
    #
    # Placing a layer is not the same as bounding it. What the idea needs is for
    # a layer to show only *part* of the store it points at, so that it covers
    # one imaged region and nothing else. Everything the source specification
    # accepts is tried here, and what each one did is recorded — including the
    # error text, because an error that names what it expected is itself an
    # answer.
    attempts = {}
    for label, source in {
        "a bound written onto the output axes": {
            "url": url,
            "transform": {
                **_identity_with_shift(0.0),
                # There is no key for this. It is written anyway so that the
                # engine can say so itself rather than being taken on trust.
                "outputBounds": {"x": [0, 512], "y": [0, 512]},
            },
        },
        "asking for a subsource that would be a rectangle": {
            "url": url,
            "enableDefaultSubsources": False,
            "subsources": {"0:0:0-512_0-512": True},
        },
    }.items():
        try:
            probe.open(
                [{"store": "under", "shader": "green", "opacity": 1.0,
                  "source": source}],
                cx=TRANSPARENCY_MIDDLE, cy=TRANSPARENCY_MIDDLE,
                um_per_pixel=TRANSPARENCY_UM_PER_PIXEL,
            )
            picture = probe.photograph()
            attempts[label] = {
                "what happened": "accepted",
                "photograph": probe.save(
                    picture, f"1c-{label.replace(' ', '-')[:40]}"),
                "read": {
                    "inside the rectangle asked for": probe.patch(
                        picture, 200.0, 200.0),
                    "outside it, still inside the store": probe.patch(
                        picture, 850.0, 850.0),
                },
            }
        except Exception as why:
            attempts[label] = {
                "what happened": "refused",
                "what the engine said": str(why)[:400],
            }
    found["attempts at showing only part of a store"] = attempts
    return found


# ---------------------------------------------------------------------------
# Question 2: does a coarse layer land correctly against a fine one?
# ---------------------------------------------------------------------------
#
# The plate would be written at ten micrometres to a voxel and the acquisition at
# about a third of one. They are meant to line up because an OME-Zarr image
# records the physical size of a voxel and where its corner sits, and the engine
# places layers by those physical facts rather than by counting pixels. An error
# here would be silent and would put every well in the wrong place.
#
# The reading is a border. The coarse layer holds a square 880 micrometres
# across; the fine layer holds one 560 micrometres across centred on exactly the
# same point of the world. If both land where they should, the coarse square
# shows as an even border 160 micrometres wide all the way round the fine one.

REGISTRATION_MIDDLE = 5120.0
REGISTRATION_UM_PER_PIXEL = 2.5


def _label_of(rgb) -> str:
    """Which of the three things in the picture a pixel belongs to.

    Deliberately blunt. The two layers are drawn in saturated green and red and
    the background is a blue nothing else could produce, so a pixel is whichever
    of those it is nearest — and anything not close to one of them is called an
    edge and left out of the reading, which is what keeps the soft boundary
    between two colours from being counted as either.
    """
    known = {"green": (0, 255, 0), "red": (255, 0, 0), "background": BACKGROUND_RGB}
    for name, want in known.items():
        if sum((int(a) - int(b)) ** 2 for a, b in zip(rgb, want)) ** 0.5 < 60:
            return name
    return "edge"


def _run_of(labels, wanted) -> tuple[int, int] | None:
    """Where a colour starts and stops along a cut, as (first, last)."""
    at = [i for i, label in enumerate(labels) if label == wanted]
    return (at[0], at[-1]) if at else None


def _borders_along(picture, cut_row: int | None, cut_column: int | None,
                   um_per_photo_pixel: float) -> dict:
    """The width of the coarse border on either side of the fine square.

    Read along one straight cut across the picture. Handed back in micrometres,
    which is the only unit in which the answer means anything: an error of two
    photograph pixels is a different matter at one magnification than another.
    """
    line = picture[cut_row, :, :] if cut_row is not None else picture[:, cut_column, :]
    labels = [_label_of(rgb) for rgb in line]
    green = _run_of(labels, "green")
    red = _run_of(labels, "red")
    if not green or not red:
        return {"read": False, "why": "the two squares were not both found"}
    before = (red[0] - green[0]) * um_per_photo_pixel
    after = (green[1] - red[1]) * um_per_photo_pixel
    # The difference between the two squares' middles. This is the honest single
    # number for "how far apart did the two layers land", and it is steadier than
    # either border on its own: the soft edge between two colours moves both
    # sides of a square the same way, so it cancels out of a middle and does not
    # cancel out of a border.
    green_middle = (green[0] + green[1]) / 2
    red_middle = (red[0] + red[1]) / 2
    return {
        "read": True,
        "how far the two middles are apart, um":
            round((red_middle - green_middle) * um_per_photo_pixel, 1),
        "border before the fine square, um": round(before, 1),
        "border after the fine square, um": round(after, 1),
        "how uneven, um": round(abs(before - after), 1),
        "fine square across, um": round((red[1] - red[0]) * um_per_photo_pixel, 1),
        "coarse square across, um": round((green[1] - green[0]) * um_per_photo_pixel, 1),
        "one photograph pixel is, um": round(um_per_photo_pixel, 2),
    }


def _read_registration(probe: Probe, picture) -> dict:
    scale = picture.shape[1] / WINDOW["width"]
    um_per_photo_pixel = REGISTRATION_UM_PER_PIXEL / scale
    middle_row = picture.shape[0] // 2
    middle_column = picture.shape[1] // 2
    return {
        "across the middle": _borders_along(
            picture, middle_row, None, um_per_photo_pixel),
        "down the middle": _borders_along(
            picture, None, middle_column, um_per_photo_pixel),
        "what it should be, um": make_stores.EXPECTED_BORDER_UM,
    }


def measure_coarse_against_fine(probe: Probe) -> dict:
    """Do a ten-micrometre layer and a third-of-a-micrometre layer coincide?"""
    found = {}

    probe.open(
        [
            {"store": "coarse", "shader": "green", "opacity": 1.0},
            {"store": "fine", "shader": "red", "opacity": 1.0},
        ],
        cx=REGISTRATION_MIDDLE, cy=REGISTRATION_MIDDLE,
        um_per_pixel=REGISTRATION_UM_PER_PIXEL,
    )
    picture = probe.photograph()
    found["as the two stores describe themselves"] = {
        "photograph": probe.save(picture, "2-coarse-against-fine"),
        "borders": _read_registration(probe, picture),
    }

    # -- the deliberate breakage ------------------------------------------
    #
    # The border above is claimed to be even because the two layers land where
    # they should. That claim is only worth something if the same reading goes
    # uneven when one of them genuinely does not.
    #
    # So the fine image is written a second time with its corner recorded a
    # hundred micrometres wrong and nothing else changed. That is what this fault
    # would really look like — a stage position written down slightly wrong, or
    # an origin left out — and it is exactly the kind of error that would
    # otherwise be silent, because a picture in the wrong place is still a
    # perfectly good picture.
    probe.open(
        [
            {"store": "coarse", "shader": "green", "opacity": 1.0},
            {"store": "finewrong", "shader": "red", "opacity": 1.0},
        ],
        cx=REGISTRATION_MIDDLE, cy=REGISTRATION_MIDDLE,
        um_per_pixel=REGISTRATION_UM_PER_PIXEL,
    )
    picture = probe.photograph()
    found["broken on purpose: the corner written down 100 um wrong"] = {
        "photograph": probe.save(picture, "2-broken-corner-100um-wrong"),
        "borders": _read_registration(probe, picture),
    }

    # -- where the last few micrometres come from --------------------------
    #
    # The reading above does not come out at exactly nought, and a small
    # disagreement nobody has explained is exactly the kind of thing that turns
    # out later to have been the first sign of something real. So rather than
    # note it and move on, it is put to a test that can refute the explanation.
    #
    # The guess is that it is half a voxel of the *coarse* layer — that is, the
    # two images disagree about whether the number recorded for a corner means
    # the edge of the first voxel or its middle. If that is right, doing the
    # whole thing again with the coarse layer twice as coarse must double the
    # disagreement. If it is instead something about the fine layer, or about the
    # reading itself, the number will not move.
    probe.open(
        [
            {"store": "coarser", "shader": "green", "opacity": 1.0},
            {"store": "fine", "shader": "red", "opacity": 1.0},
        ],
        cx=REGISTRATION_MIDDLE, cy=REGISTRATION_MIDDLE,
        um_per_pixel=REGISTRATION_UM_PER_PIXEL,
    )
    picture = probe.photograph()
    found["the same, with the coarse layer twice as coarse"] = {
        "photograph": probe.save(picture, "2-twice-as-coarse"),
        "coarse voxel, um": 2 * make_stores.COARSE_UM,
        "half a coarse voxel less half a fine one, um":
            round((2 * make_stores.COARSE_UM - make_stores.FINE_UM) / 2, 2),
        "borders": _read_registration(probe, picture),
    }
    return found


# ---------------------------------------------------------------------------
# Question 3: the whole stack, photographed
# ---------------------------------------------------------------------------
#
# The plate at the bottom, the tiles the operator planned above it, and a sparse
# acquisition above that. It should look like this: the plate visible
# everywhere, the tile rectangles visible where they were planned, and picture
# only where picture was taken.

def measure_the_whole_stack(probe: Probe) -> dict:
    """Build the three-layer stack and photograph it filling in."""
    found = {}
    places = [(row, column)
              for row in range(make_stores.PLAN_ROWS)
              for column in range(make_stores.PLAN_COLUMNS)]
    # Written afresh so that the first photograph really is of a run part way
    # through rather than of one that was finished earlier.
    canvases = make_stores.open_the_acquisition(probe.data_dir)
    some = places[:5]
    make_stores.acquire_tiles(canvases, some)

    grid_wide = make_stores.PLAN_COLUMNS * make_stores.PLAN_TILE_UM
    grid_tall = make_stores.PLAN_ROWS * make_stores.PLAN_TILE_UM
    centre_x = make_stores.PLAN_ORIGIN_UM[1] + grid_wide / 2
    centre_y = make_stores.PLAN_ORIGIN_UM[0] + grid_tall / 2

    layers = [
        {"store": "carrier", "shader": "green", "opacity": 1.0},
        {"store": "plan", "shader": "magenta", "opacity": 1.0},
        {"store": "acquired", "shader": "grey", "opacity": 1.0},
    ]

    # The whole carrier, so that the plate layer can be seen for what it is.
    probe.open(layers, cx=20000.0, cy=15000.0, um_per_pixel=45.0)
    picture = probe.photograph()
    found["the whole carrier, part acquired"] = {
        "photograph": probe.save(picture, "3-carrier-wide"),
    }

    # Close in on the planned grid, where all three layers overlap.
    probe.open(layers, cx=centre_x, cy=centre_y, um_per_pixel=4.5)
    picture = probe.photograph()
    found["part acquired"] = {
        "photograph": probe.save(picture, "3-part-acquired"),
        "tiles written": len(some),
        "tiles planned": len(places),
        "read": _read_the_stack(probe, picture, some, places),
    }

    make_stores.acquire_tiles(canvases, places[5:])
    canvases.close()
    # Nothing on disk announces a new tile — the image was declared at full size
    # before any tile existed and its description is identical before and after.
    # So the engine has to be told to let go of what it decoded, or the tiles
    # written just now are never noticed at all.
    probe.act("window.probe.letGo()")
    picture = probe.photograph()
    found["fully acquired"] = {
        "photograph": probe.save(picture, "3-fully-acquired"),
        "tiles written": len(places),
        "read": _read_the_stack(probe, picture, places, places),
    }
    return found


def _read_the_stack(probe: Probe, picture, written, planned) -> dict:
    """What is showing in the middle of each planned tile.

    Read at the middle of a tile rather than at its edge, because the edge is
    where the planned rectangle is drawn and the middle is where acquired picture
    would be. A tile that has been imaged should show picture there; one that has
    not should show whatever is underneath.
    """
    side = make_stores.PLAN_TILE_UM
    reading = {}
    for row, column in planned:
        x = make_stores.PLAN_ORIGIN_UM[1] + (column + 0.5) * side
        y = make_stores.PLAN_ORIGIN_UM[0] + (row + 0.5) * side
        patch = probe.patch(picture, x, y, radius=10)
        reading[f"tile {row},{column}"] = {
            "was imaged": [row, column] in [list(p) for p in written],
            "colour": patch["rgb"],
            "how varied": patch["spread"],
        }
    return reading


# ---------------------------------------------------------------------------
# Question 6: the ambiguity that is not yet fixed
# ---------------------------------------------------------------------------
#
# Making unimaged room see-through works by asking how bright a voxel is, so a
# tile that genuinely was imaged and came back black disappears too. This shows
# it: one tile of real but very dark picture beside room that was never written,
# photographed twice — once as an operator would see it, and once with the same
# layer drawn solid so that where the microscope actually looked can be seen.
#
# `viz_studio/OPTIONS.md` records a one-line change to the writer that would
# settle this. It is deliberately not applied. The point is to put the problem in
# front of somebody as a picture.

DARK_MIDDLE = 1024.0
DARK_UM_PER_PIXEL = 2.6


def measure_the_dark_tile(probe: Probe) -> dict:
    """Show a genuinely dark tile vanishing exactly as unvisited room does."""
    found = {}
    tile = make_stores.DARK_TILE
    row, column = make_stores.DARK_TILE_AT
    # The middle of the one tile that really was imaged, and a place beside it
    # that never was. Both in micrometres, which for this store is one to a voxel.
    imaged_x = (column + 0.5) * tile
    imaged_y = (row + 0.5) * tile
    never_x = (column + 1.5) * tile
    never_y = (row + 0.5) * tile

    def _how_much_plate_shows(picture, x_um, y_um, half=40) -> float:
        """What share of a patch is showing the plate underneath.

        This is the number the whole question turns on. Where the acquisition
        made itself see-through, the plate below shows and this is high. Where
        the acquisition drew something, the plate is covered and this is low. If
        a place the microscope genuinely visited reads the same as a place it
        never visited, the two are indistinguishable on screen — which is the
        fault being demonstrated.
        """
        row, column = probe.where(picture, x_um, y_um)
        block = picture[row - half:row + half, column - half:column + half]
        if block.size == 0:
            return float("nan")
        green = (block[:, :, 1].astype(int) - block[:, :, 0].astype(int) > 60) & (
            block[:, :, 1].astype(int) - block[:, :, 2].astype(int) > 60)
        return round(float(green.mean()), 3)

    for label, layers, name in (
        ("as an operator would see it",
         [{"store": "darkunder", "shader": "green", "opacity": 1.0},
          {"store": "darkover", "shader": "grey", "opacity": 1.0}],
         "6-as-the-operator-sees-it"),
        ("the same, with the writer's own record of where it looked drawn over it",
         [{"store": "darkunder", "shader": "green", "opacity": 1.0},
          {"store": "darkover", "shader": "grey", "opacity": 1.0},
          {"store": "darkfootprint", "shader": "magenta", "opacity": 1.0}],
         "6-with-the-footprint-marked"),
    ):
        probe.open(layers, cx=DARK_MIDDLE, cy=DARK_MIDDLE,
                   um_per_pixel=DARK_UM_PER_PIXEL)
        picture = probe.photograph()
        found[label] = {
            "photograph": probe.save(picture, name),
            "how much of the plate shows through": {
                "in the dark part of the tile that WAS imaged":
                    _how_much_plate_shows(picture, imaged_x - tile * 0.35, imaged_y),
                "in room beside it that was NEVER written":
                    _how_much_plate_shows(picture, never_x, never_y),
            },
            "read": {
                "the faint blob inside the imaged tile": probe.patch(
                    picture, imaged_x, imaged_y, radius=5),
            },
        }
    return found


# ---------------------------------------------------------------------------
# Question 4: what the plate actually costs
# ---------------------------------------------------------------------------
#
# Arithmetic says a 128 by 86 millimetre plate at ten micrometres to a voxel is
# about seventeen hundred pieces, a few hundred kilobytes, and a few seconds to
# write. None of that had been checked. It is measured four ways, because two
# separate things are in doubt: whether keeping the pyramid of smaller copies
# matters, and whether the cheerful answer survives somebody wanting a pattern
# drawn on their plate rather than flat colour.


def measure_what_the_plate_costs(probe: Probe) -> dict:
    """Write a plate-sized layer four ways and count what each one cost."""
    found = {}
    scratch = probe.out / "plate-scratch"
    for patterned in (False, True):
        for pyramid in (True, False):
            name = ("patterned" if patterned else "flat") + (
                "-with-pyramid" if pyramid else "-no-pyramid")
            scratch.mkdir(parents=True, exist_ok=True)
            cost = make_stores.write_the_plate(
                scratch, name=name, patterned=patterned, pyramid=pyramid)
            cost["megabytes"] = round(cost["bytes"] / 1e6, 2)
            cost["bytes per million voxels"] = round(
                cost["bytes"] / (cost["voxels"] / 1e6))
            label = (("a patterned background" if patterned else "flat colour")
                     + (", keeping the smaller copies" if pyramid
                        else ", full size only"))
            found[label] = cost
            print(f"    {label}: {cost['megabytes']} MB, "
                  f"{cost['files']} files, {cost['seconds']} s", flush=True)
            # Removed as soon as it has been counted. Four plate-sized images
            # left lying about would be most of a gigabyte, and the numbers have
            # already been taken.
            shutil.rmtree(scratch / f"{name}.ome.zarr", ignore_errors=True)
    shutil.rmtree(scratch, ignore_errors=True)
    return found


# ---------------------------------------------------------------------------
# Question 5: does a pattern survive being shrunk down?
# ---------------------------------------------------------------------------
#
# Every smaller copy in the pyramid keeps half as much detail, so a pattern whose
# lines are only a few voxels apart cannot survive many halvings. The claim being
# tested is that a pattern with a *physical* period — a line every millimetre,
# which is a hundred voxels at ten micrometres — does survive, while one defined
# in voxels does not.
#
# One thing about how this project's writer makes its smaller copies decides the
# whole answer, and it is worth stating before any number below. It does not
# average. It takes every second voxel and throws the rest away. So a pattern
# does not fade gently into grey as it is shrunk; it either happens to keep
# landing on the voxels that are kept, or it does not — and what comes out can be
# a solid block just as easily as an empty one.


def _read_the_levels(store: Path) -> list[dict]:
    """Open every smaller copy in a store and say what is left of the pattern.

    This looks at what is actually on disk, which is what the engine will draw
    when the operator zooms out. Two numbers are taken from each copy: how much
    of it is bright, and how much it varies. A pattern that has survived varies;
    one that has been lost is even, whether it was lost by everything going dark
    or by everything going bright.
    """
    import zarr

    group = zarr.open_group(str(store), mode="r")
    levels = []
    for name in sorted((key for key in group.array_keys()), key=int):
        array = group[name]
        plane = np.asarray(array[0, 0, 0, :, :])
        levels.append({
            "level": int(name),
            "voxels across": int(plane.shape[1]),
            "share of it bright": round(float((plane > 0).mean()), 3),
            "how much it varies": round(float(plane.std()), 1),
            "plane": plane,
        })
    return levels


def _still_visible(level: dict) -> bool:
    """Whether a pattern can still be made out in this copy.

    A pattern is there if the copy is neither all dark nor all bright. The two
    ways of losing it look completely different on disk and identical to an
    operator — a flat rectangle either way — so both are counted as lost.
    """
    share = level["share of it bright"]
    return 0.02 < share < 0.98


def measure_a_pattern_shrinking(probe: Probe) -> dict:
    """Follow both patterns down the pyramid and say where each one goes."""
    found = {}
    for store, label, period_um in (
        ("physicalgrid", "a line every millimetre (a physical period)",
         make_stores.PHYSICAL_PERIOD_VOXELS * make_stores.PATTERN_UM),
        ("voxelgrid", "a line every four voxels (a period with no physical meaning)",
         make_stores.VOXEL_PERIOD_VOXELS * make_stores.PATTERN_UM),
    ):
        levels = _read_the_levels(probe.data_dir / f"{store}.ome.zarr")
        lost_at = None
        for level in levels:
            if not _still_visible(level) and lost_at is None:
                lost_at = level["level"]
            # A small square out of the middle of each copy, saved so that the
            # numbers can be checked against a picture rather than believed.
            plane = level.pop("plane")
            side = min(200, plane.shape[0])
            middle = plane.shape[0] // 2
            crop = plane[middle:middle + side, middle:middle + side]
            shown = (crop > 0).astype(np.uint8) * 255
            Image.fromarray(shown).resize((400, 400), Image.NEAREST).save(
                probe.out / f"5-{store}-level-{level['level']}.png")
            level["picture of this copy"] = f"5-{store}-level-{level['level']}.png"
            level["one voxel of this copy is, um"] = round(
                make_stores.PATTERN_UM * make_stores.PATTERN_VOXELS
                / level["voxels across"], 1)
        found[label] = {
            "the pattern repeats every, um": period_um,
            "copies kept": len(levels),
            "first copy in which it can no longer be made out": lost_at,
            "copy by copy": levels,
        }
    return found


# ---------------------------------------------------------------------------


MEASUREMENTS = {
    "1. does a layer underneath give the layer above its transparency back":
        measure_transparency,
    "1b. what switching the lower layer off does":
        measure_switching_the_lower_layer_off,
    "1c. can several layers show different rectangles of one store":
        measure_two_layers_over_one_store,
    "2. does a coarse layer land correctly against a fine one":
        measure_coarse_against_fine,
    "3. the whole stack": measure_the_whole_stack,
    "4. what the plate actually costs": measure_what_the_plate_costs,
    "5. does a pattern survive being shrunk down": measure_a_pattern_shrinking,
    "6. the ambiguity that is not yet fixed": measure_the_dark_tile,
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--only", default=None)
    parser.add_argument("--data", type=Path, default=None,
                        help="where to keep the little acquisitions these "
                             "measurements are made against. Written if the "
                             "folder is not there yet, and reused if it is, so "
                             "that working on one measurement does not mean "
                             "writing every store again each time.")
    parser.add_argument("--rewrite-stores", action="store_true",
                        help="write the stores again even if they are there")
    args = parser.parse_args()

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    data = args.data or (out / "stores")
    if args.rewrite_stores and data.exists():
        shutil.rmtree(data)
    if not data.exists():
        print("writing the stores ...", flush=True)
        started = time.perf_counter()
        make_stores.write_everything_but_the_plate(data)
        print(f"  written in {time.perf_counter() - started:.1f} s", flush=True)

    results = {}
    with Probe(data, out) as probe:
        for name, run in MEASUREMENTS.items():
            if args.only and args.only.lower() not in name.lower():
                continue
            print(f"\n=== {name} ===", flush=True)
            started = time.perf_counter()
            results[name] = run(probe)
            print(f"  ({time.perf_counter() - started:.1f} s)", flush=True)
            for heading, block in results[name].items():
                print(f"  {heading}:")
                for place, patch in (block.get("read") or {}).items():
                    print(f"    {place}: {describe(patch)}")

    (out / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nwritten to {out}")


if __name__ == "__main__":
    main()
