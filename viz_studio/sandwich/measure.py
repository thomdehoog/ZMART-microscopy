"""Measure whether the sandwich holds registration, and what it costs when slow.

Run it with::

    python viz_studio/sandwich/measure.py --out /somewhere/to/put/the/results

It writes a folder of photographs and a ``results.json`` beside them, and prints
a readable summary as it goes. Everything in the report this produced was taken
from these numbers; nothing was reasoned about without being measured.

The question it settles is whether the acquired image can be drawn by a second
engine in a canvas of its own *underneath* the operator's drawing, with holes cut
in the drawing where the image should show — rather than as a layer inside the
same canvas. Two drawing surfaces cannot be handed to the screen in the same
instant, so the doubt is that the image slides out from under the outlines
whenever the view moves. The whole of what follows is aimed at that.

Two things about how it measures are worth knowing before reading any number
out of it.

**Every number comes from a photograph of the screen.** Nothing here asks the
engine where it thinks it is. That is a rule this project learned the hard way:
an engine can report itself perfectly satisfied while drawing nothing at all, and
it can equally report the right position while presenting an older frame. What
reaches the screen is the only thing an operator sees, so it is the only thing
measured.

**The same measurement is run on the arrangement that cannot fail.** Drawing both
layers in one canvas makes registration exact by construction, so that
arrangement must come out at zero. If it does not, the harness is measuring its
own noise and every other number here is worthless. That control is run first.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import sys
import threading
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_VIZ = _HERE.parent
_REPO = _VIZ.parent
for extra in (str(_HERE), str(_VIZ / "tests"), str(_REPO)):
    if extra not in sys.path:
        sys.path.insert(0, extra)

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from margins import (  # noqa: E402
    margins_around_the_hole,
    margins_at_every_cut,
    only_the_whole_ones,
    where_the_drawing_sits,
    worst_drift,
)
from make_stores import write_the_sparse_canvas, write_the_square  # noqa: E402
from probe_server import Ledger, make_probe_server  # noqa: E402

# The browser this machine actually has. The version Playwright would reach for
# by default is not installed here and may not be downloaded, so it is named
# outright. If this path is wrong on your machine, correct it here rather than
# running `playwright install`.
CHROMIUM = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

# Software rendering. There is no graphics card on this machine, and without
# these the drawing surface is simply blank — the engine needs WebGL2 and gets
# none. What this costs the measurements is written out in the report: frames
# arrive far less often than they would on real hardware, so the numbers below
# describe a slow machine rather than a fast one. It does not invent
# disagreement between two layers within a single photograph, which is the thing
# actually being measured.
SOFTWARE_GL = ["--use-gl=angle", "--use-angle=swiftshader", "--ignore-gpu-blocklist"]

WINDOW = {"width": 900, "height": 700}
# How wide the band of background is cut, in browser pixels. Must match
# MARGIN_CSS_PX in `page/src/margin_probe.js`.
MARGIN_CSS_PX = 40


# ---------------------------------------------------------------------------
# Driving the page
# ---------------------------------------------------------------------------


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

    # -- opening a page ---------------------------------------------------

    def open(self, *, density: float = 1.0, **params):
        """Open the probe with the arrangement asked for, and wait for a picture.

        ``density`` is how many real pixels the screen packs into one browser
        pixel. It is worth being able to set to something that is not a whole
        number: two canvases have to agree about how large a screen pixel is in
        *real* pixels, and a disagreement about that is invisible at a density
        of exactly one, which is the classic version of this fault.
        """
        if self.page:
            self.page.close()
        context = self.browser.new_context(
            viewport=dict(WINDOW), device_scale_factor=density
        )
        self.page = context.new_page()
        self.console = []
        self.page.on("console", lambda m: self.console.append(f"{m.type}: {m.text}"))
        self.page.on("pageerror", lambda e: self.console.append(f"pageerror: {e}"))
        asked = "&".join(f"{key}={value}" for key, value in params.items())
        self.page.goto(f"http://127.0.0.1:{self.port}/?{asked}", wait_until="domcontentloaded")
        self.page.wait_for_function(
            "() => window.probe && (window.probe.ready || window.probe.failed)",
            timeout=60_000,
        )
        failed = self.page.evaluate("() => window.probe.failed")
        if failed:
            raise RuntimeError(f"the probe page could not start: {failed}")
        # Wait until the picture is actually there. Asked of the pixels rather
        # than of the engine, for the reason given at the top of this file.
        self.settle()
        return self.page

    def settle(self, tries: int = 60) -> None:
        """Wait until the photograph stops changing."""
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

    def nominal(self, picture) -> float:
        """How wide the band should be, in this photograph's own pixels.

        Worked out from the photograph rather than assumed, because the two ways
        of taking one do not agree. A still photograph comes back at the screen's
        real pixel count; a frame from the live recording comes back at the
        browser's own pixel count. Neither is wrong, but a measurement that
        assumed one and got the other would report a disagreement of fifty per
        cent where there was none.
        """
        css_wide = self.believes("window.probe.size()")["width"]
        return MARGIN_CSS_PX * (picture.shape[1] / css_wide)

    def save(self, name: str) -> Path:
        path = self.out / f"{name}.png"
        self.page.screenshot(path=str(path))
        return path

    def save_frame(self, picture, name: str) -> Path:
        path = self.out / f"{name}.png"
        Image.fromarray(picture).save(path)
        return path

    def believes(self, expression: str):
        return self.page.evaluate(f"() => {expression}")

    # -- the delay standing in for a network share -------------------------

    # Asked over plain HTTP rather than through the page, so that the delay can
    # be changed and the note read whether or not a page happens to be open —
    # and so that reading the note never costs the page a moment of its own
    # attention, which would be measuring the measurement.
    def _ask(self, path: str, body: dict | None = None) -> dict:
        import urllib.request

        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=10) as answer:
            return json.loads(answer.read())

    def set_delay(self, milliseconds: float) -> None:
        self._ask("/api/delay", {"ms": milliseconds})

    def clear_ledger(self) -> None:
        self._ask("/api/ledger/clear", {})

    def read_ledger(self) -> dict:
        return self._ask("/api/ledger")

    def coverage(self, image: str) -> dict:
        return self._ask(f"/api/coverage?image={image}")


class Recording:
    """A live recording of what actually reached the screen, frame by frame.

    Taken with the browser's own screen recording rather than by asking for a
    photograph over and over, and the difference matters. Asking for a
    photograph makes the browser produce a fresh frame and wait for it, which
    would give both layers a chance to catch up with each other — exactly the
    disagreement being looked for. A recording only reports frames the browser
    was going to composite anyway, so what it contains is what an operator would
    have seen.
    """

    def __init__(self, page):
        self.page = page
        self.frames: list[tuple[float, str]] = []
        self._cdp = None

    def __enter__(self):
        self._cdp = self.page.context.new_cdp_session(self.page)
        self._cdp.on("Page.screencastFrame", self._got)
        self._cdp.send(
            "Page.startScreencast",
            {
                "format": "png",
                "everyNthFrame": 1,
                "maxWidth": WINDOW["width"] * 2,
                "maxHeight": WINDOW["height"] * 2,
            },
        )
        return self

    def _got(self, params):
        self.frames.append((time.perf_counter(), params["data"]))
        try:
            self._cdp.send(
                "Page.screencastFrameAck", {"sessionId": params["sessionId"]}
            )
        except Exception:
            # The recording was stopped between the frame arriving and this
            # acknowledgement. Nothing is lost; the frame is already kept.
            pass

    def __exit__(self, *_):
        try:
            self._cdp.send("Page.stopScreencast")
        except Exception:
            pass

    def pictures(self):
        for when, data in self.frames:
            yield when, np.array(
                Image.open(io.BytesIO(base64.b64decode(data))).convert("RGB")
            )


# ---------------------------------------------------------------------------
# The gestures
# ---------------------------------------------------------------------------
#
# Only the two the controls allow: dragging pans, and the plain wheel zooms.
# They are written as three shapes of movement because each exposes a different
# way for two layers to come apart, and telling them apart is most of the
# diagnosis.


def pan_steadily(page, steps: int = 40, step: int = 5) -> None:
    """A plain, even drag. A follower that lags shows one side thick, one thin."""
    page.mouse.move(WINDOW["width"] / 2, WINDOW["height"] / 2)
    page.mouse.down()
    for i in range(steps):
        page.mouse.move(WINDOW["width"] / 2 + (i + 1) * step, WINDOW["height"] / 2)
    page.mouse.up()


def zoom_in_and_out(page, notches: int = 4) -> None:
    """A few notches in and the same number back out, ending where it started.

    Ending where it started is deliberate: any small mismatch between what the
    sheet does with a notch and what the engine does with it accumulates, and
    coming back to the beginning is what makes an accumulated error visible
    rather than merely present.
    """
    page.mouse.move(WINDOW["width"] / 2, WINDOW["height"] / 2)
    for _ in range(notches):
        page.mouse.wheel(0, -120)
    for _ in range(notches):
        page.mouse.wheel(0, 120)


def throw_it_about(page, sweeps: int = 6, span: int = 8, step: int = 12) -> None:
    """Back and forth with sharp reversals — the worst case for a follower.

    A follower that is simply behind looks fine at a steady speed, because being
    behind by a constant amount looks like being in the right place a moment
    ago. It is at the turn that it gives itself away: it is still going the old
    way when the hand has already started coming back.
    """
    page.mouse.move(WINDOW["width"] / 2, WINDOW["height"] / 2)
    page.mouse.down()
    where = WINDOW["width"] / 2
    direction = 1
    for _ in range(sweeps):
        for _ in range(span):
            where += direction * step
            page.mouse.move(where, WINDOW["height"] / 2)
        direction = -direction
    page.mouse.up()


GESTURES = {
    "panning": pan_steadily,
    "zooming": zoom_in_and_out,
    "thrown about": throw_it_about,
}


# ---------------------------------------------------------------------------
# The margin measurement itself
# ---------------------------------------------------------------------------


def measure_a_gesture(probe: Probe, gesture, name: str) -> dict:
    """Make one gesture and read the margins out of every frame it produced."""
    probe.believes("window.probe.reset()")
    probe.settle(tries=20)
    readings = []
    with Recording(probe.page) as recording:
        gesture(probe.page)
        time.sleep(0.4)
    worst_picture, worst_seen = None, -1.0
    nominal = None
    worst_slant = 0.0
    for _, picture in recording.pictures():
        if nominal is None:
            nominal = probe.nominal(picture)
        along, slant = margins_at_every_cut(picture)
        readings.extend(along)
        if slant is not None:
            worst_slant = max(worst_slant, slant)
        for reading in along:
            if reading.found and reading.unevenness > worst_seen:
                worst_seen, worst_picture = reading.unevenness, picture
    summary = worst_drift(readings, nominal or MARGIN_CSS_PX)
    summary["band was cut at, in these pixels"] = round(nominal or 0.0, 1)
    summary["worst slant"] = round(worst_slant, 1)
    summary["frames"] = len(recording.frames)
    if worst_picture is not None:
        summary["photograph"] = probe.save_frame(worst_picture, name).name
    return summary


def measure_the_margins(probe: Probe, *, arrangement: str, follow: str,
                        density: float = 1.0, label: str) -> dict:
    """Every gesture, on one arrangement."""
    probe.open(
        arrangement=arrangement, follow=follow, store="square", voxels=1024,
        density=density,
    )
    still = probe.photograph()
    at_rest = margins_around_the_hole(still)
    found = {
        "arrangement": arrangement,
        "follow": follow,
        "density": density,
        "band was cut at, in a still photograph's pixels": round(
            probe.nominal(still), 1),
        "at_rest": at_rest.sides if at_rest.found else {"why": at_rest.why},
        "at_rest_unevenness": at_rest.unevenness,
        "at_rest_photograph": probe.save(f"{label}-at-rest").name,
    }
    for gesture_name, gesture in GESTURES.items():
        found[gesture_name] = measure_a_gesture(
            probe, gesture, f"{label}-{gesture_name.replace(' ', '-')}-worst"
        )
    return found


# ---------------------------------------------------------------------------
# What a stall does to the interface
# ---------------------------------------------------------------------------


def measure_a_stall(probe: Probe, *, follow: str, delay_ms: float, label: str) -> dict:
    """Slow the server down, then drag, and watch what the interface does.

    The stall is made by delaying the *server*, not by blocking the page's own
    thread. That is the honest way round: a real delay is a fetch that has not
    come back, and how an engine behaves while waiting for data is precisely
    what is in question. Blocking the page instead would guarantee a freeze and
    prove nothing.
    """
    # Measured on the sparse canvas rather than the little square, because the
    # stall has to be a real one. The square is small enough to be fetched in a
    # handful of requests, so delaying each of them barely shows; the sparse
    # canvas costs a couple of hundred requests for a single redraw, which is
    # the shape a run actually has and the shape a slow share actually hurts.
    limits = probe.coverage("sparse").get("bounds") or {}
    probe.open(
        arrangement="sandwich", follow=follow, store="sparse", voxels=8192,
        x0=limits["x"][0], x1=limits["x"][1],
        y0=limits["y"][0], y1=limits["y"][1],
    )
    probe.set_delay(delay_ms)
    probe.believes("window.probe.reset()")
    time.sleep(0.3)
    # Make the engine go back to the disk for everything on screen, so the delay
    # is actually met rather than answered out of what it already holds.
    probe.believes("window.probe.letGo()")
    readings = []
    slivers = []
    with Recording(probe.page) as recording:
        started = time.perf_counter()
        pan_steadily(probe.page, steps=40, step=5)
        finished = time.perf_counter()
        time.sleep(0.6)
    changed_at = []
    last = None
    nominal = None
    moved_from = moved_to = None
    worst_picture, worst_sliver = None, -1.0
    for when, picture in recording.pictures():
        if nominal is None:
            nominal = probe.nominal(picture)
        reading = margins_around_the_hole(picture)
        readings.append(reading)
        if reading.found:
            # How far the picture itself travelled during the gesture, read off
            # the screen. This is the plain answer to "did the drag still follow
            # the mouse": the mouse moved a known distance, and either the
            # picture went with it or it did not.
            if moved_from is None:
                moved_from = reading.across.image_starts
            moved_to = reading.across.image_starts
        # The sliver is only meaningful where the whole picture is on screen.
        # Where it is still filling in, the nearest bright pixel to the
        # operator's rectangle is the edge of what has arrived rather than the
        # edge of the imaged ground, and the "sliver" is then a measure of how
        # much data is missing.
        whole = only_the_whole_ones([reading], nominal or MARGIN_CSS_PX)
        drawing = where_the_drawing_sits(picture) if whole else {"found": False}
        if drawing["found"]:
            slivers.append(drawing["sliver"])
            if drawing["sliver"] > worst_sliver:
                worst_sliver, worst_picture = drawing["sliver"], picture
        if last is None or not np.array_equal(picture, last):
            changed_at.append(when)
        last = picture
    whole = only_the_whole_ones(readings, nominal or MARGIN_CSS_PX)
    # The longest the picture stood still while the mouse was moving. This is
    # what an operator would call a freeze.
    gaps = [b - a for a, b in zip(changed_at, changed_at[1:])]
    found = {
        "follow": follow,
        "delay_ms": delay_ms,
        "gesture_seconds": round(finished - started, 2),
        "frames": len(recording.frames),
        "frames_that_changed": len(changed_at),
        "longest_freeze_seconds": round(max(gaps), 3) if gaps else None,
        # The mouse was dragged two hundred browser pixels. This says how far the
        # picture went with it while it was on screen at all, read off the screen
        # rather than out of the page.
        #
        # It comes to less than two hundred, and that is expected rather than a
        # fault: the engine is told to let go of everything it has decoded just
        # before the drag begins, so for the first part of it there is no picture
        # to find. What matters is that the figure is the same at every delay —
        # the picture keeps up with the hand just as well on a slow share as on a
        # local disk.
        "the mouse moved (browser pixels)": 200,
        "the picture moved while it was on screen (photograph pixels)":
            round(moved_to - moved_from, 1) if moved_from is not None else None,
        "photographs where the picture was still filling in":
            f"{len(readings) - len(whole)} of {len(readings)}",
        "registration, on the frames where the picture was whole":
            worst_drift(whole, nominal or MARGIN_CSS_PX),
        "requests": probe.read_ledger(),
    }
    if slivers:
        found["worst_sliver_px"] = round(max(slivers), 1)
        found["typical_sliver_px"] = round(float(np.median(slivers)), 1)
        found["sliver_photograph"] = probe.save_frame(worst_picture, f"{label}-sliver").name
    probe.set_delay(0)
    return found


# ---------------------------------------------------------------------------
# How long a redraw takes, on a local disk and on something like a share
# ---------------------------------------------------------------------------


def measure_a_redraw(probe: Probe, *, delay_ms: float) -> dict:
    """Drop everything decoded, ask for it again, and time the whole round.

    The timing is taken from the server's own note of every request rather than
    from anything the engine says about itself, and the wall clock is measured
    from the moment the engine is told to let go to the moment the server stops
    being asked for anything.
    """
    probe.set_delay(delay_ms)
    probe.clear_ledger()
    started = time.perf_counter()
    probe.believes("window.probe.letGo()")
    quiet_since = None
    seen = -1
    while time.perf_counter() - started < 60:
        now = probe.read_ledger()
        if now["requests"] != seen:
            seen = now["requests"]
            quiet_since = time.perf_counter()
        elif quiet_since and time.perf_counter() - quiet_since > 0.6 and seen > 0:
            break
        time.sleep(0.05)
    elapsed = time.perf_counter() - started - 0.6
    found = probe.read_ledger()
    found["wall_seconds"] = round(max(elapsed, 0.0), 3)
    # The arithmetic everybody does in their head, so it can be compared with
    # what actually happened: so many requests, so many at a time, so many
    # rounds, one delay per round.
    if found["requests"] and found["at_once"]:
        # The arithmetic anybody would do in their head, kept beside what
        # actually happened: so many requests, so many the browser will hold at
        # once, therefore so many rounds, and one delay per round.
        found["rounds_by_arithmetic"] = round(found["requests"] / found["at_once"], 1)
        found["predicted_seconds"] = round(
            (found["requests"] / found["at_once"]) * (delay_ms / 1000.0), 3
        )
    probe.set_delay(0)
    return found


def measure_latency(probe: Probe, *, bounded: bool, delays) -> dict:
    """Time a redraw of the sparse canvas at each delay, bounded or not."""
    where = probe.coverage("sparse")
    limits = where.get("bounds") or {}
    params = dict(
        arrangement="sandwich", follow="presented", store="sparse", voxels=8192,
    )
    if bounded and limits:
        # The record of where the run actually imaged, used to bound what is
        # drawn. This is the arrangement that would ship: the hole in the sheet
        # is the only place the image shows, so there is nothing to be gained by
        # having the engine draw anywhere else — and everywhere else is where it
        # spends its requests asking about ground nobody has been to.
        params.update(
            bounded=1,
            x0=limits["x"][0], x1=limits["x"][1],
            y0=limits["y"][0], y1=limits["y"][1],
        )
    probe.open(**params)
    found = {"bounded": bounded, "coverage": where.get("recorded"), "at": {}}
    for delay in delays:
        found["at"][str(delay)] = measure_a_redraw(probe, delay_ms=delay)
    return found


# ---------------------------------------------------------------------------
# Everything else
# ---------------------------------------------------------------------------


def measure_while_writing(probe: Probe, data_dir: Path) -> dict:
    """Run the margin measurement with a run actively writing to the same disk.

    A finished store flatters the arrangement. During a real run the acquisition
    machine is writing tiles hard while the viewer reads from the same disk, and
    that contention is a source of stalls with nothing to do with networks.
    """
    from make_stores import SQUARE_TILE, _a_tile

    keep_writing = threading.Event()
    keep_writing.set()
    written = {"tiles": 0}
    canvases = write_the_square(data_dir, name="busy")

    def write_hard():
        seed = 0
        while keep_writing.is_set():
            row = (seed // 4) % 4
            column = seed % 4
            canvases.write(
                _a_tile(1, SQUARE_TILE, SQUARE_TILE, seed),
                origin=(0, row * SQUARE_TILE, column * SQUARE_TILE),
                tile_index=(0, row, column),
            )
            written["tiles"] += 1
            seed += 1

    writer = threading.Thread(target=write_hard, daemon=True)
    writer.start()
    try:
        found = measure_the_margins(
            probe, arrangement="sandwich", follow="presented",
            label="while-writing",
        )
    finally:
        keep_writing.clear()
        writer.join(timeout=10)
        canvases.close()
    found["tiles_written_meanwhile"] = written["tiles"]
    return found


def measure_new_data_arriving(probe: Probe, data_dir: Path) -> dict:
    """Write tiles into ground the engine has already looked at, and photograph it.

    This is the viewer's whole purpose, and it is the one place where an engine
    that remembers what it has decoded gets it wrong on purpose: it has already
    decided a piece is absent, and there is no time limit on that decision, so a
    tile written into that piece is never noticed. Not "slow to appear" — no
    request at all, ever.
    """
    from make_stores import SPARSE_TILE, SPARSE_VOXELS, _a_tile

    # A canvas with only a corner imaged, so there is room the engine will
    # certainly have looked at and found empty.
    from zmart_storage import Channel, TileCanvases

    canvases = TileCanvases.create(
        data_dir, name="growing",
        canvas_shape=(1, SPARSE_VOXELS // 4, SPARSE_VOXELS // 4),
        tile_shape=(1, SPARSE_TILE, SPARSE_TILE),
        tile_step=(1, SPARSE_TILE, SPARSE_TILE),
        voxel_size_um=(1.0, 1.0, 1.0),
        channels=[Channel(name="probe", color="FFFFFF", window=(0, 4095))],
        discard_existing_run=True,
    )
    for row in range(2):
        for column in range(2):
            canvases.write(
                _a_tile(1, SPARSE_TILE, SPARSE_TILE, row * 2 + column),
                origin=(0, row * SPARSE_TILE, column * SPARSE_TILE),
                tile_index=(0, row, column),
            )
    span = SPARSE_VOXELS // 4
    probe.open(
        arrangement="sandwich", follow="presented", store="growing",
        voxels=span, x0=0, y0=0, x1=span, y1=span,
    )
    lit_at_first = _how_much_is_lit(probe.photograph())
    before = probe.save("new-data-before").name

    # Now write into room the engine has already looked at and found empty.
    for row in range(2, 4):
        for column in range(4):
            canvases.write(
                _a_tile(1, SPARSE_TILE, SPARSE_TILE, row * 4 + column),
                origin=(0, row * SPARSE_TILE, column * SPARSE_TILE),
                tile_index=(0, row, column),
            )
    time.sleep(2.0)
    probe.settle(tries=15)
    lit_without_being_told = _how_much_is_lit(probe.photograph())
    without = probe.save("new-data-without-telling-it").name

    # And now tell it to let go of what it decoded, which is what the viewer's
    # own live path does.
    asked = probe.believes("window.probe.letGo()")
    time.sleep(2.0)
    probe.settle(tries=20)
    lit_after_letting_go = _how_much_is_lit(probe.photograph())
    after = probe.save("new-data-after-letting-go").name
    canvases.close()
    return {
        "lit_at_first": round(lit_at_first, 4),
        "lit_without_being_told": round(lit_without_being_told, 4),
        "lit_after_letting_go": round(lit_after_letting_go, 4),
        "sources_asked_to_let_go": asked,
        "photographs": [before, without, after],
    }


def _how_much_is_lit(picture) -> float:
    """What share of the window is showing acquired picture rather than nothing."""
    bright = (picture[:, :, 0] > 150) & (picture[:, :, 1] > 150) & (picture[:, :, 2] > 150)
    return float(bright.mean())


def measure_the_removed_gestures(probe: Probe) -> dict:
    """Show that the two allowed gestures move the view and nothing else does.

    An unbound gesture and a gesture nobody tried look exactly alike on screen,
    so each one is made in earnest and the picture is compared with the one
    before it. Rotation matters most: a rotated flat view stops lining up with
    the drawing over it and nothing at all reports that it has.
    """
    probe.open(arrangement="sandwich", follow="presented", store="square", voxels=1024)
    probe.believes("window.probe.reset()")
    probe.settle(tries=20)
    middle = (WINDOW["width"] / 2, WINDOW["height"] / 2)

    found = {"allowed": {}, "removed": {}}

    # First, that the two allowed gestures really do move the view — read off
    # the picture, not off the numbers we set.
    before = margins_around_the_hole(probe.photograph())
    where_before = before.across.image_starts
    pan_steadily(probe.page, steps=10, step=12)
    probe.settle(tries=15)
    after = margins_around_the_hole(probe.photograph())
    found["allowed"]["drag pans"] = {
        "image edge moved by": round(after.across.image_starts - where_before, 1),
        "margins stayed even": after.unevenness,
        "photograph": probe.save("gestures-after-pan").name,
    }
    probe.believes("window.probe.reset()")
    probe.settle(tries=15)
    before = margins_around_the_hole(probe.photograph())
    width_before = before.across.image_ends - before.across.image_starts
    probe.page.mouse.move(*middle)
    for _ in range(5):
        probe.page.mouse.wheel(0, -120)
    probe.settle(tries=15)
    after = margins_around_the_hole(probe.photograph())
    found["allowed"]["wheel zooms"] = {
        "image grew from": round(width_before, 1),
        "to": round(after.across.image_ends - after.across.image_starts, 1),
        "margins stayed even": after.unevenness,
        "photograph": probe.save("gestures-after-zoom").name,
    }

    # And now the ones that used to navigate. Each is tried in earnest and the
    # picture compared with the one before it; the view must not have moved at
    # all.
    probe.believes("window.probe.reset()")
    probe.settle(tries=20)
    rest = probe.photograph()

    def try_this(name, do_it):
        do_it()
        probe.settle(tries=8)
        now = probe.photograph()
        same = bool(np.array_equal(now, rest))
        difference = float(np.abs(now.astype(int) - rest.astype(int)).mean())
        found["removed"][name] = {
            "view unchanged": same,
            "mean difference in the photograph": round(difference, 4),
        }
        if not same:
            probe.save_frame(now, f"gestures-{name.replace(' ', '-')}-moved")

    def shift_drag():
        probe.page.keyboard.down("Shift")
        probe.page.mouse.move(*middle)
        probe.page.mouse.down()
        for i in range(10):
            probe.page.mouse.move(middle[0] + i * 12, middle[1] + i * 6)
        probe.page.mouse.up()
        probe.page.keyboard.up("Shift")

    def right_button():
        probe.page.mouse.click(middle[0] + 150, middle[1] + 100, button="right")

    def ctrl_wheel():
        probe.page.keyboard.down("Control")
        probe.page.mouse.move(*middle)
        for _ in range(5):
            probe.page.mouse.wheel(0, -120)
        probe.page.keyboard.up("Control")

    try_this("shift and drag (used to rotate)", shift_drag)
    try_this("the r key (used to rotate)", lambda: probe.page.keyboard.press("r"))
    try_this("the e key (used to rotate)", lambda: probe.page.keyboard.press("e"))
    try_this(
        "shift and the arrow keys (used to tilt)",
        lambda: [probe.page.keyboard.press(f"Shift+Arrow{d}")
                 for d in ("Left", "Right", "Up", "Down")],
    )
    try_this("ctrl and the wheel (used to zoom)", ctrl_wheel)
    try_this("the right button (used to recentre)", right_button)
    try_this(
        "the arrow keys (used to step sideways)",
        lambda: [probe.page.keyboard.press(f"Arrow{d}") for d in ("Left", "Up")],
    )
    found["what the page counted"] = probe.believes(
        "({refused: window.probe.gestures.refused, "
        "accepted: window.probe.gestures.accepted})"
    )
    return found


def measure_that_the_checks_can_fail(probe: Probe) -> dict:
    """Break the two things on purpose, and show that the checks notice.

    A check that has never been seen to fail is not evidence of anything. Both
    of the ones this session leans on are broken here deliberately:

    - the hole is moved a few pixels away from where it belongs, which is
      exactly what a lagging follower does, and the margins must report it;
    - the flat view is turned, which is the fault `CONTROLS.md` says is silent,
      and the margins must report that too.
    """
    probe.open(arrangement="sandwich", follow="presented", store="square", voxels=1024)
    probe.believes("window.probe.reset()")
    probe.settle(tries=20)
    found = {}

    still = probe.photograph()
    lined_up, slant = margins_at_every_cut(still)
    middle = lined_up[len(lined_up) // 2]
    found["lined up"] = {
        "margins along the middle cut": middle.sides,
        "unevenness along the middle cut": middle.unevenness,
        "slant across the three cuts": round(slant, 1) if slant else slant,
    }
    for pixels in (2, 8):
        probe.believes(f"window.probe.nudgeTheHole({pixels})")
        probe.settle(tries=10)
        broken = margins_around_the_hole(probe.photograph())
        found[f"hole moved {pixels} browser pixels"] = {
            "margins": broken.sides if broken.found else {"why": broken.why},
            "unevenness": broken.unevenness,
            "photograph": probe.save(f"can-fail-nudged-{pixels}").name,
        }
    # And the check that catches a turned view, which a single cut through the
    # middle of a square cannot see at all. See CUTS in `margins.py`.
    probe.believes("window.probe.nudgeTheHole(0)")
    probe.settle(tries=10)

    for degrees in (2, 15):
        probe.believes("window.probe.reset()")
        probe.settle(tries=10)
        probe.believes(f"window.probe.rotateOnPurpose({degrees})")
        probe.settle(tries=15)
        picture = probe.photograph()
        along, slant = margins_at_every_cut(picture)
        middle = along[len(along) // 2]
        found[f"view turned {degrees} degrees"] = {
            "margins along the middle cut":
                middle.sides if middle.found else {"why": middle.why},
            "unevenness along the middle cut": middle.unevenness,
            "slant across the three cuts": round(slant, 1) if slant else slant,
            "photograph": probe.save(f"can-fail-turned-{degrees}").name,
        }
    return found


def measure_pixel_density_and_resize(probe: Probe) -> dict:
    """Open at a density that is not a whole number, and resize half way through.

    Two canvases have to agree about how large a screen pixel is in *real*
    pixels rather than browser pixels. At a density of exactly one they agree by
    accident, which is why this has to be measured at something else.
    """
    density = 1.5
    found = measure_the_margins(
        probe, arrangement="sandwich", follow="presented",
        density=density, label="density-1.5",
    )
    found["canvas_sizes"] = probe.believes("window.probe.canvasSizes()")
    found["density_the_page_sees"] = probe.believes("window.probe.density()")
    # And now change the size of the window while it is open.
    probe.page.set_viewport_size({"width": 1100, "height": 620})
    time.sleep(0.5)
    probe.settle(tries=20)
    still = probe.photograph()
    after = margins_around_the_hole(still)
    found["after_resize"] = {
        "band was cut at, in these pixels": round(probe.nominal(still), 1),
        "margins": after.sides if after.found else {"why": after.why},
        "unevenness": after.unevenness,
        "canvas_sizes": probe.believes("window.probe.canvasSizes()"),
        "photograph": probe.save("density-1.5-after-resize").name,
    }
    return found


def measure_which_way_the_specimen_faces(probe: Probe) -> dict:
    """Does the picture move the way the hand moves?

    This one is here because it very nearly wrecked every other measurement in
    this file, and because it is invisible to every other kind of check.

    The engine draws three chosen axes: one across the window, one down it, one
    into the screen. Which is which follows from the *order* the axes are handed
    over in together with which of the engine's named layouts is asked for — and
    those two interact. Get them wrong and the specimen is drawn mirrored
    left-to-right. Nothing errors. On a round specimen, on a plate, on anything
    roughly symmetrical, it looks exactly like a good picture. It is the same
    family of fault as a rotated view, which `CONTROLS.md` already warns about,
    and it is quieter.

    What it does to the sandwich is not subtle: the sheet moves one way and the
    image moves the other, so a drag of a hundred pixels puts them two hundred
    pixels apart. The first run of these measurements read that as a
    catastrophic lag and it was nothing of the sort.

    So it is measured directly. Drag, and for every frame the engine draws,
    compare where the view says the edge of the acquisition is with where it
    really is on the engine's own drawing surface. The slope between the two is
    +1 when they move together and −1 when they move opposite ways.
    """
    found = {}
    for convention in ("as the viewer does it", "width running to the right"):
        probe.open(
            arrangement="sandwich", follow="presented", store="square",
            voxels=1024, axes=convention.replace(" ", "%20"),
        )
        probe.believes("window.probe.reset()")
        probe.settle(tries=20)
        probe.believes("window.probe.watchFrames(true)")
        pan_steadily(probe.page, steps=30, step=6)
        time.sleep(0.4)
        log = probe.believes("window.probe.frameLog()")
        probe.believes("window.probe.watchFrames(false)")
        usable = [row for row in log if row["drawn"] is not None]
        answer = {"frames": len(log), "frames_with_an_edge_on_the_surface": len(usable)}
        if len(usable) > 2:
            asked = np.array([row["asked"] for row in usable])
            drawn = np.array([row["drawn"] for row in usable])
            said = np.array([row["said"] for row in usable])
            spread = asked.max() - asked.min()
            answer.update({
                "moved the sheet by": round(float(spread), 1),
                "moved the picture by": round(float(drawn.max() - drawn.min()), 1),
                "which way": round(
                    float(np.polyfit(asked, drawn, 1)[0]), 3
                ) if spread > 1 else None,
                # And, separately, whether what the engine says it is showing
                # agrees with what is on its surface. This is the answer to
                # "does the engine expose the frame it has presented".
                "worst gap between what it says and what it drew":
                    round(float(np.max(np.abs(said - drawn))), 1),
                "worst gap between what it was asked and what it says":
                    round(float(np.max(np.abs(asked - said))), 2),
            })
        answer["photograph"] = probe.save(
            f"facing-{convention.replace(' ', '-')}"
        ).name
        found[convention] = answer
    return found


def measure_the_static_offset(probe: Probe) -> dict:
    """Is the picture where the writer's own coordinates say it is?

    Separate from drift, and easy to confuse with it. A constant offset between
    where the application thinks a voxel is and where the engine draws it does
    not change as the view moves, so it does not show up as the margins becoming
    uneven while a gesture is made — but it is there all the same, and it grows
    on screen as the operator zooms in. Measured by reading the margins at
    several magnifications while nothing is moving: an offset fixed in voxels
    shows as a difference between opposite sides that doubles when the
    magnification doubles.
    """
    probe.open(arrangement="sandwich", follow="presented", store="square", voxels=1024)
    found = {"at_each_magnification": []}
    for scale in (8.0, 6.0, 4.0, 3.0, 2.0):
        probe.believes(f"window.probe.setView({{scale: {scale}}})")
        probe.settle(tries=15)
        reading = margins_around_the_hole(probe.photograph())
        if not reading.found:
            found["at_each_magnification"].append(
                {"voxels_per_pixel": scale, "why": reading.why}
            )
            continue
        found["at_each_magnification"].append({
            "voxels_per_pixel": scale,
            "sides": reading.sides,
            "left minus right": round(reading.left - reading.right, 1),
            "top minus bottom": round(reading.top - reading.bottom, 1),
            "in voxels, across": round((reading.left - reading.right) / 2 * scale, 3),
        })
    return found


# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True,
                        help="where to write the photographs and results.json")
    parser.add_argument("--only", default=None,
                        help="run one measurement by name, for working on it")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    data = args.out / "data"
    data.mkdir(exist_ok=True)

    print("writing the two little acquisitions ...")
    square = write_the_square(data)
    sparse = write_the_sparse_canvas(data)
    square.close()
    sparse.close()

    results: dict = {"window": WINDOW, "margin_css_px": MARGIN_CSS_PX}
    with Probe(data, args.out) as probe:
        def run(name, work):
            if args.only and args.only != name:
                return
            print(f"\n=== {name} ===")
            started = time.perf_counter()
            results[name] = work()
            print(json.dumps(results[name], indent=1)[:4000])
            print(f"({round(time.perf_counter() - started, 1)} s)")

        # The control first. Everything else depends on it coming out at zero.
        run("the control: both layers in one canvas", lambda: measure_the_margins(
            probe, arrangement="one-canvas", follow="presented", label="control"))
        run("the sandwich, sheet following the pointer", lambda: measure_the_margins(
            probe, arrangement="sandwich", follow="pointer", label="pointer"))
        run("the sandwich, sheet following the engine's last frame",
            lambda: measure_the_margins(
                probe, arrangement="sandwich", follow="presented", label="presented"))
        run("which way the specimen faces",
            lambda: measure_which_way_the_specimen_faces(probe))
        run("a constant offset, if there is one",
            lambda: measure_the_static_offset(probe))
        run("latency, unbounded",
            lambda: measure_latency(probe, bounded=False, delays=(0, 2, 20)))
        run("latency, bounded to the imaged tiles",
            lambda: measure_latency(probe, bounded=True, delays=(0, 2, 20)))
        run("a stall, with the sheet locked to the engine", lambda: {
            str(delay): measure_a_stall(
                probe, follow="presented", delay_ms=delay, label=f"stall-locked-{delay}")
            for delay in (0, 20, 200)})
        run("a stall, with the compromise", lambda: {
            str(delay): measure_a_stall(
                probe, follow="compromise", delay_ms=delay,
                label=f"stall-compromise-{delay}")
            for delay in (0, 20, 200)})
        run("with a run writing to the same disk",
            lambda: measure_while_writing(probe, data))
        run("does it notice new data arriving",
            lambda: measure_new_data_arriving(probe, data))
        run("a screen that is not one real pixel to a browser pixel",
            lambda: measure_pixel_density_and_resize(probe))
        run("only the two gestures move the view",
            lambda: measure_the_removed_gestures(probe))
        run("and the checks can fail",
            lambda: measure_that_the_checks_can_fail(probe))

    (args.out / "results.json").write_text(json.dumps(results, indent=1))
    print(f"\nwritten to {args.out / 'results.json'}")


if __name__ == "__main__":
    main()
