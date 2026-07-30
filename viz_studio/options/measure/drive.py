"""Opening a page, moving the view, and photographing what reached the screen.

Two rules are built into this file rather than left to the person writing a
measurement, because both have been broken before and both cost a great deal.

**Every number comes from a photograph of the screen.** Nothing here asks an
engine where it thinks it is. An engine can report itself perfectly satisfied
while drawing nothing at all, and it can equally report the right position while
presenting an older frame. What reaches the screen is the only thing an operator
sees, so it is the only thing measured. The handful of things this file *does*
ask the page are the means to make something happen — move the view, let go of
what has been decoded, count a gesture that was refused — never the answer to
the question being asked.

**A gesture is recorded rather than sampled.** Asking for a photograph makes the
browser produce a fresh frame and wait for it, which gives two stacked surfaces a
chance to catch up with each other — exactly the disagreement being looked for. A
live recording only reports frames the browser was going to composite anyway, so
what it contains is what an operator would have seen.
"""

from __future__ import annotations

import base64
import io
import json
import os
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlencode

_HERE = Path(__file__).resolve().parent
_VIZ = _HERE.parents[1]
for extra in (str(_HERE), str(_VIZ / "tests"), str(_VIZ.parent)):
    if extra not in sys.path:
        sys.path.insert(0, extra)

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from data_server import Ledger, make_measurement_server  # noqa: E402

# Software rendering. There is no graphics card in the containers this is
# developed in, and without these the drawing surface is simply blank — the
# engine needs WebGL2 and gets none. What it costs the measurements is written
# out in RESULTS.md: frames arrive far less often than they would on real
# hardware, so the numbers describe a slow machine. It cannot invent disagreement
# between two layers *within a single photograph*, which is the thing the
# registration measurement actually reads.
SOFTWARE_GL = ["--use-gl=angle", "--use-angle=swiftshader", "--ignore-gpu-blocklist"]

WINDOW = {"width": 900, "height": 700}

# How wide the band of background is cut, in browser pixels. Must match
# MARGIN_CSS_PX in `harness/src/drawings.js`.
MARGIN_CSS_PX = 40

# Where the built harness page is.
HARNESS_DIST = _HERE.parent / "harness" / "dist"


def find_a_chromium() -> str | None:
    """The Chromium this machine actually has.

    Playwright will only offer the one exact build it was packaged against and
    refuses to launch anything else, so on a machine with a perfectly good
    Chromium of a slightly different build every measurement would fail and every
    picture test would skip. The viewer's own test suite already solves this, so
    this borrows its search rather than keeping a second copy of the answer —
    including the ``ZMART_CHROMIUM`` setting, which overrides it.

    Do not run ``playwright install`` to work around a failure here. The search
    below finds what is already on the machine, and a fault where a third of the
    suite skipped in silence was fixed by making it look.
    """
    from conftest import find_a_chromium as look

    found = look()
    return str(found) if found else None


class Harness:
    """The server, a browser, and one page of the harness, held open together."""

    def __init__(
        self,
        data_dir: Path,
        out: Path,
        *,
        option: str = "neuroglancer-under",
        site_dir: Path | None = None,
    ):
        # Which option is being measured. Held here so that every measurement
        # below can be written without naming one — that is the whole point of
        # the suite, and it is what lets the next two options be measured by
        # running the same file with a different word.
        self.option = option
        self.data_dir = Path(data_dir)
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.ledger = Ledger()
        self.server = make_measurement_server(
            port=0,
            site_dir=site_dir or HARNESS_DIST,
            data_dir=self.data_dir,
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
        chromium = find_a_chromium()
        try:
            self.browser = self._playwright.chromium.launch(args=SOFTWARE_GL)
        except Exception:
            if not chromium:
                raise
            self.browser = self._playwright.chromium.launch(
                args=SOFTWARE_GL, executable_path=chromium
            )
        return self

    def __exit__(self, *_):
        if self.browser:
            self.browser.close()
        if self._playwright:
            self._playwright.stop()
        self.server.shutdown()
        self._thread.join(timeout=5)

    # -- opening a page ----------------------------------------------------

    @property
    def address(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def open(self, *, density: float = 1.0, **params):
        """Open the harness on one option, and wait until there is a picture.

        ``density`` is how many real pixels the screen packs into one browser
        pixel. It is worth being able to set to something that is not a whole
        number: two drawing surfaces have to agree about how large a screen pixel
        is in *real* pixels, and a disagreement about that is invisible at a
        density of exactly one, which is the classic version of that fault.
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
        # The address the data is served from is passed in rather than left for
        # the page to work out, because the option underneath is forbidden to
        # work it out. See the note about addresses in `neuroglancer-under`.
        asked = dict(params)
        asked.setdefault("option", self.option)
        asked.setdefault("data", f"{self.address}/data")
        # Properly encoded rather than joined together by hand. A colour is
        # written "#0000ff", and a bare "#" in an address begins the fragment —
        # so a hand-built query silently loses that setting and every one after
        # it. That cost an hour: the page opened, drew, and quietly used its
        # default colours, which looked like the engine ignoring what it was
        # told.
        query = urlencode(asked)
        self.page.goto(f"{self.address}/?{query}", wait_until="domcontentloaded")
        self.page.wait_for_function(
            "() => window.harness && (window.harness.ready || window.harness.failed)",
            timeout=90_000,
        )
        failed = self.believes("window.harness.failed")
        if failed:
            raise RuntimeError(f"the harness page could not start: {failed}")
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
        browser's own. Neither is wrong, but a measurement that assumed one and
        got the other would report a disagreement of fifty per cent where there
        was none.
        """
        wide = self.believes("window.harness.size()")["width"]
        return MARGIN_CSS_PX * (picture.shape[1] / wide)

    def save(self, name: str) -> str:
        self.page.screenshot(path=str(self.out / f"{name}.png"))
        return f"{name}.png"

    def save_frame(self, picture, name: str) -> str:
        Image.fromarray(picture).save(self.out / f"{name}.png")
        return f"{name}.png"

    def believes(self, expression: str):
        return self.page.evaluate(f"() => {expression}")

    # -- the delay standing in for a network share -------------------------

    def _ask(self, path: str, body: dict | None = None) -> dict:
        # Asked over plain HTTP rather than through the page, so that reading the
        # note never costs the page a moment of its own attention — which would
        # be measuring the measurement.
        import urllib.request

        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            f"{self.address}{path}", data=data,
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
    """A live recording of what actually reached the screen, frame by frame."""

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
# The gestures, as a hand would make them
# ---------------------------------------------------------------------------
#
# Only the two the controls allow. They are written as three shapes of movement
# because each exposes a different way for two layers to come apart, and telling
# those apart is most of the diagnosis.


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
    operator's drawing does with a notch and what the engine does with it
    accumulates, and coming back to the beginning is what makes an accumulated
    error visible rather than merely present.
    """
    page.mouse.move(WINDOW["width"] / 2, WINDOW["height"] / 2)
    for _ in range(notches):
        page.mouse.wheel(0, -120)
    for _ in range(notches):
        page.mouse.wheel(0, 120)


def throw_it_about(page, sweeps: int = 6, span: int = 8, step: int = 12) -> None:
    """Back and forth with sharp reversals — the worst case for a follower.

    A follower that is simply behind looks fine at a steady speed, because being
    behind by a constant amount looks like being in the right place a moment ago.
    It gives itself away at the turn, when it is still going the old way while
    the hand has already started coming back.
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


def require_a_browser() -> None:
    """Stop with a plain explanation if this machine cannot draw.

    Called at the start of a run rather than left to fail somewhere in the
    middle, because a measurement that cannot open a browser has nothing to say
    and should say so at once.
    """
    if os.environ.get("ZMART_REQUIRE_BROWSER") and not HARNESS_DIST.exists():
        raise SystemExit(
            "the harness page has not been built, so there is nothing to open. "
            "Build it with:\n\n"
            "    npm --prefix viz_studio/options/harness run build\n"
        )
