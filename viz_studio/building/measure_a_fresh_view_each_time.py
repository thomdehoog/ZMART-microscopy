"""Replacing a hundred-position view with a fresh one, over and over, from outside.

What this is asking
-------------------

A smart run changes while somebody is looking at it: positions arrive, the
picture grows, and the ground already on screen has to be replaced by ground
that includes what just landed. Neuroglancer has no public way to say "what you
remember about this picture is out of date" — the engine treats a data source as
immutable and offers no invalidate-this-chunk to call.

The workaround is to stop asking it to change its mind: **never mutate a loaded
picture, hand it a new one instead.** Every generation of the run is declared as
a fresh built picture at a fresh address, and switching generations means
closing the picture that is open and opening the next. The engine can have no
memory of an address it has never seen, so nothing needs invalidating and
nothing stale can survive — at the price of paying for a load on every
generation.

Whether that price is affordable is the only open question, and it is what this
measures: **how long does replacing the open view with the next one take, and
does it stay that way after dozens of them?**

How the swap is made, and why not any other way
-----------------------------------------------

Everything goes through the server's own front door, exactly as a workflow
would during an experiment (``make_server`` names this route on purpose):

1. ``POST /api/stores/open`` with the next generation's folder,
2. ``POST /api/stores/close`` with the heading of the one on screen,
3. ``POST /api/announce``, which is how an open page learns to ask again.

The page then does everything itself — refetches what is open, takes the old
layer down, builds the new one — through the one code path it always uses. An
earlier version of this harness swapped layers *underneath* the page instead,
through the engine's own layer list, and the page fought it: its next sync pass
put back what the harness had removed, several times a second, and both the
picture and the panel flickered without end. The page owns the layer list;
anything measuring it has to go through the page.

Why each generation has its own colour
--------------------------------------

Each generation's picture is named for a different channel (``Ch405``,
``Ch488``, ``Ch561``, ``Ch647``), so the panel itself draws each one in a
different colour, using the same convention it applies to any acquisition. The
colour on screen therefore says *which generation's layer is being drawn*, and
the screen — photographed and classified, never trusted by eye — is the
instrument. The pixel bytes differ between generations too (each is written in
its own brightness band), and every generation sits at an address the browser
has never fetched, so the piece requests counted per swap are necessarily
fresh: a swap that shows the new colour with no requests would mean the
measurement is broken, not that the browser was clever.

What comes back
---------------

For every swap:

``gone``
    from the first POST until the outgoing generation is no longer what is on
    screen.

``shown``
    from the same moment until the incoming generation's colour is on screen.
    This is the number an operator would feel, and it honestly includes
    everything a live swap would cost: the announcement reaching the page, the
    page catching up, the layer being rebuilt, the visible pieces being
    fetched and drawn.

``blank``
    the gap between the two: how long the screen showed neither. If it is
    nought, double-buffering generations would solve a problem that does not
    exist; if it is not, that is exactly the number double-buffering — opening
    the new generation *before* closing the old — would remove.

``requests``
    how many the swap cost. A swap fetches what is in view, not the whole
    picture, which is the reason this can be affordable at all.

``heap``
    the browser's own memory, reported first and last. Dozens of discarded
    generations is exactly where an engine that never lets go would show it.

Run it with::

    python measure_a_fresh_view_each_time.py --headed --dwell 1
    python measure_a_fresh_view_each_time.py --positions 100 --swaps 24

``--headed`` opens a visible window, and on Windows that is the only way the
browser reaches the graphics card. Do not type into the window; it is the
measurement. ``--dwell`` holds each generation on screen so a person can watch
the colours change; it sits outside every timing.
"""

from __future__ import annotations

import argparse
import io
import json
import shutil
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

_BUILDING = Path(__file__).resolve().parent
_VIZ = _BUILDING.parent
sys.path.insert(0, str(_BUILDING))
sys.path.insert(0, str(_VIZ))
sys.path.insert(0, str(_VIZ / "backend"))
sys.path.insert(0, str(_VIZ / "tests"))

import measure_the_frame_rate_of_a_linked_view as watching  # noqa: E402
from declare import declare_a_built_picture  # noqa: E402
from measure_scaling import write_a_transfer  # noqa: E402
from server import make_server  # noqa: E402

# The generations. Each is named for a channel the panel already knows how to
# colour (see ``_CHANNEL_COLORS`` in backend/stores.py — the panel colours by
# the wavelength in a store's name), and each writes its pixels in a brightness
# band of its own, so the bytes differ between generations as well as the
# colour. The colours here are the panel's own values, kept in step by the test
# below rather than by discipline.
SETS = (
    ("blue", "405", (0.30, 0.45, 1.00), (24000, 32000)),
    ("green", "488", (0.00, 1.00, 0.40), (32000, 40000)),
    ("amber", "561", (1.00, 0.75, 0.10), (40000, 48000)),
    ("magenta", "647", (1.00, 0.20, 1.00), (48000, 56000)),
)

# How much of the middle of the picture to classify, in pixels.
#
# Small on purpose: the classification runs on every frame the page paints, and
# a patch this size keeps it to a few milliseconds.
PATCH = 160

# A pixel dimmer than this (out of 255, on its brightest channel) is showing
# background, not specimen. Well below the dimmest band above once the panel's
# measured window has been applied, and well above black.
FLOOR = 25

# Where the camera is, read before and after a swap. Not put back: the page owns
# the camera exactly as it owns the layers, and if replacing a generation moves
# it, that is a finding to report rather than a nuisance to hide.
WHERE_THE_CAMERA_IS = """() => {
  const nav = window.zmartViewer.navigationState;
  return {at: Array.from(nav.position.value), zoom: nav.zoomFactor.value};
}"""


def which_generation_is_this(image_bytes: bytes, middle: dict) -> str:
    """Which generation this frame of the page is showing, or ``blank``.

    Classified by hue rather than by exact colour: every lit pixel is scaled to
    its own brightness before being matched, because the panel's shader carries
    the specimen's brightness *in* the colour — a dim blue pixel and a bright
    blue pixel are the same generation. Pixels below the floor are background;
    a patch that is mostly background is ``blank``, which during a swap is a
    reading, not a failure.
    """
    import numpy as np
    from PIL import Image

    whole = np.asarray(Image.open(io.BytesIO(image_bytes)).convert("RGB"),
                       dtype=np.float64)
    pixels = whole[middle["top"]:middle["top"] + middle["side"],
                   middle["left"]:middle["left"] + middle["side"]]
    brightness = pixels.max(axis=2)
    lit = brightness > FLOOR
    if lit.mean() < 0.5:
        return "blank"
    hue = pixels[lit] / brightness[lit][:, None]
    named = [(name, np.array(colour) / max(colour))
             for name, _, colour, _ in SETS]
    apart = np.stack([np.abs(hue - wanted).sum(axis=1) for _, wanted in named])
    counts = np.bincount(apart.argmin(axis=0), minlength=len(named))
    return named[int(counts.argmax())][0]


class WatchingTheScreen:
    """The page's own frames, streamed as it paints them, never asked for.

    An earlier version of this harness photographed the page in a loop with
    ``page.screenshot``, and in a headed browser every capture forces the
    compositor's hand -- the operator watched the window flash white and black
    for the whole run. That is the instrument disturbing the experiment. The
    screencast is the stream the browser's own developer tools watch a page
    through: the page pushes a frame whenever it repaints, each stamped with
    the moment it was painted, and nothing about drawing changes because
    someone is listening.

    Frames arrive only when something repaints. That is a feature: the frame
    in which the new generation's colour first appears *is* the moment it was
    shown, read from the frame's own timestamp rather than from a poll's
    schedule.
    """

    def __init__(self, page, middle: dict):
        self._middle = middle
        self._frames: list[tuple[float, bytes]] = []
        self._latest: str | None = None
        self._session = page.context.new_cdp_session(page)
        self._session.on("Page.screencastFrame", self._one_frame)
        self._session.send("Page.startScreencast", {
            "format": "png", "everyNthFrame": 1,
        })

    def _one_frame(self, told) -> None:
        import base64
        self._frames.append((float(told["metadata"]["timestamp"]),
                             base64.b64decode(told["data"])))
        self._session.send("Page.screencastFrameAck",
                           {"sessionId": told["sessionId"]})

    def seen_since(self, moment: float) -> list[tuple[float, str]]:
        """Every (when, generation) painted since ``moment``, classified.

        Consumes what it classifies, and remembers the last answer so that a
        stretch with no repaints -- an idle page is a silent one -- still has
        a current reading in :attr:`showing`.
        """
        taken, self._frames = self._frames, []
        readings = []
        for when, image in taken:
            if when < moment:
                continue
            self._latest = which_generation_is_this(image, self._middle)
            readings.append((when, self._latest))
        return readings

    @property
    def showing(self) -> str | None:
        """The last classified reading, or ``None`` before any frame came."""
        return self._latest


def write_the_generations(work: Path, positions: int) -> list[Path]:
    """Write one folder per generation, each a two-channel dataset.

    Same geometry deliberately: the generations differ in their values, their
    colour and their address, and in nothing else — so a swap moves nothing on
    screen and what is measured is the swap, not a re-framing.

    Two channels rather than one, and the second is a dark single tile that
    never reaches the screen. The panel colours channels only when there is
    more than one — a lone channel is greyscale on principle (``channel_color``
    says why) — so the companion is what earns the main store its colour. Real
    generations will be multi-channel anyway; the fixture just declines to
    pretend otherwise. The companion's wavelength is one the palette does not
    know, so it could only ever draw grey, and its pixels are near enough to
    nothing that it does not draw at all.
    """
    generations = []
    for number, (name, wavelength, _, band) in enumerate(SETS):
        transfer = work / f"transfer-{name}"
        write_a_transfer(transfer, positions, values=band)
        dark = work / f"dark-{name}"
        write_a_transfer(dark, 1, values=(1, 2))
        folder = work / "views" / f"gen{number:02d}"
        folder.mkdir(parents=True, exist_ok=True)
        declare_a_built_picture(folder, transfer, name=f"gen{number:02d}_Ch{wavelength}")
        declare_a_built_picture(folder, dark, name=f"gen{number:02d}_Ch999")
        generations.append(folder)
        print(f"  {name:<8} {positions} positions written and declared "
              f"under {folder.name}", flush=True)
    return generations


def ask(port: int, route: str, body: dict | None = None) -> dict:
    """One question to the server's own API, the way a workflow would ask it."""
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{route}",
        data=None if body is None else json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="GET" if body is None else "POST",
    )
    with urllib.request.urlopen(request, timeout=30) as answer:
        return json.loads(answer.read().decode("utf-8"))


def groups_in(config: dict) -> set[str]:
    """The headings the panel is showing, which is what closing goes by."""
    return {layer.get("group") or "" for layer in config.get("layers", [])}


def swap_to(page, watching_the_screen: WatchingTheScreen, port: int,
            generation: Path, expect: str, was_showing: str,
            asked: dict, patience: float = 60.0) -> dict:
    """Replace the open generation with this one, and time what is seen.

    The three POSTs are the whole intervention; everything after them is the
    page's own doing. What the operator sees is then read from the frames the
    page painted -- their own timestamps, not a poll's schedule -- because the
    engine reporting a source resolved and the operator seeing the picture are
    different moments, and only the second one is the question.
    """
    where = page.evaluate(WHERE_THE_CAMERA_IS)
    before_requests = asked["requests"]
    showing = groups_in(ask(port, "/api/config"))
    began = time.time()
    opened = ask(port, "/api/stores/open", {"path": str(generation)})
    opened_ms = (time.time() - began) * 1000.0
    closing = time.time()
    for heading in showing & groups_in(opened):
        ask(port, "/api/stores/close", {"group": heading})
    closed_ms = (time.time() - closing) * 1000.0
    ask(port, "/api/announce", {"reason": f"generation swap to {generation.name}"})

    gone = shown = None
    while shown is None and time.time() - began < patience:
        # Waiting through the page is what lets its frames be delivered; the
        # wait itself asks the page for nothing.
        page.wait_for_timeout(30)
        for when, seeing in watching_the_screen.seen_since(began):
            now = (when - began) * 1000.0
            if gone is None and seeing != was_showing:
                gone = now
            if seeing == expect:
                shown = now
                break
    moved = page.evaluate(WHERE_THE_CAMERA_IS)
    return {
        # What the server itself spent inside the two POSTs. If most of
        # ``shown`` sits inside ``opened``, the swap is slow before the page
        # has heard anything, and the page is not the place to look.
        "opened_ms": opened_ms,
        "closed_ms": closed_ms,
        "gone_ms": gone,
        "shown_ms": shown,
        "blank_ms": None if (gone is None or shown is None) else shown - gone,
        "requests": asked["requests"] - before_requests,
        "drifted": abs(moved["zoom"] - where["zoom"]) > 1e-6,
    }


def a_page_on(browser, dist: Path, opening: Path):
    """The viewer, open on the first generation and settled.

    Returns the page, the server, its thread, and a counter of every request
    the page has made — read at each end of a swap, which is what turns it into
    the cost of that swap.
    """
    server = make_server(port=0, data_dir=opening, site_dir=dist,
                         loads=[{"path": str(opening), "name": opening.name}])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 900, "height": 700})
    asked = {"requests": 0}
    page.on("request", lambda _: asked.update(requests=asked["requests"] + 1))
    page.goto(f"http://127.0.0.1:{server.server_address[1]}",
              wait_until="domcontentloaded")
    page.wait_for_function("() => window.zmartViewer !== undefined", timeout=60_000)
    page.wait_for_function("() => window.zmartSourcesWaiting() === 0", timeout=300_000)
    page.wait_for_function(watching.EVERY_SOURCE_RESOLVED, timeout=600_000)
    page.wait_for_timeout(2000)
    return page, server, thread, asked


def main() -> int:
    parsing = argparse.ArgumentParser(description=__doc__)
    parsing.add_argument("--positions", type=int, default=100,
                         help="how many positions each generation holds")
    parsing.add_argument("--swaps", type=int, default=12,
                         help="how many times to replace the view with the next one")
    parsing.add_argument("--headed", action="store_true",
                         help="open a visible window, which on Windows is the only "
                              "way the browser reaches the graphics card")
    parsing.add_argument("--dwell", type=float, default=0.0,
                         help="seconds to hold each generation on screen before "
                              "the next swap, so a person can watch; outside "
                              "every timing")
    asked_for = parsing.parse_args()

    dist = _VIZ / "frontend" / "dist"
    if not (dist / "index.html").is_file():
        raise SystemExit(
            "the viewer page has not been built; build it once with\n"
            "  npm --prefix viz_studio/frontend run build"
        )

    work = Path(tempfile.mkdtemp(prefix="fresh-view-"))
    started, browser = watching.a_browser(asked_for.headed)
    watching.say_what_is_drawing(browser)
    print(f"\nWriting {len(SETS)} generations of {asked_for.positions} positions...")
    generations = write_the_generations(work, asked_for.positions)

    page = server = thread = None
    try:
        page, server, thread, asked = a_page_on(browser, dist, generations[0])
        port = server.server_address[1]
        canvas = page.locator("canvas").first.bounding_box()
        watcher = WatchingTheScreen(page, {
            "left": int(canvas["x"] + canvas["width"] / 2 - PATCH / 2),
            "top": int(canvas["y"] + canvas["height"] / 2 - PATCH / 2),
            "side": PATCH,
        })
        waited = time.time()
        while watcher.showing is None and time.time() - waited < 15:
            page.wait_for_timeout(100)
            watcher.seen_since(0.0)
        first_seen = watcher.showing
        if first_seen != SETS[0][0]:
            raise SystemExit(
                f"the opening generation reads as {first_seen!r} where "
                f"{SETS[0][0]!r} was expected, so the colours cannot be "
                "trusted and nothing was measured. The panel colours by the "
                "wavelength in a store's name; check the names and "
                "_CHANNEL_COLORS still agree."
            )
        heap_first = page.evaluate(
            "() => performance.memory?.usedJSHeapSize || 0")

        print(f"\n  {'swap':>4} {'generation':>10} {'open':>8} {'close':>8} "
              f"{'gone':>8} {'shown':>8} {'blank':>8} {'requests':>9}")
        print("  " + "-" * 72)
        showing = SETS[0][0]
        rows = []
        for number in range(asked_for.swaps):
            which = (number + 1) % len(SETS)
            name = SETS[which][0]
            row = swap_to(page, watcher, port, generations[which], name,
                          showing, asked)
            row["generation"] = name
            rows.append(row)
            if row["shown_ms"] is not None:
                showing = name
            def say(key, row=row):
                return (f"{row[key]:>6.0f}ms" if row[key] is not None
                        else "     --")
            print(f"  {number + 1:>4} {name:>10} {say('opened_ms')} "
                  f"{say('closed_ms')} {say('gone_ms')} "
                  f"{say('shown_ms')} {say('blank_ms')} {row['requests']:>9}"
                  + ("  <- never appeared" if row["shown_ms"] is None else "")
                  + ("  <- camera moved" if row["drifted"] else ""),
                  flush=True)
            if asked_for.dwell:
                page.wait_for_timeout(int(asked_for.dwell * 1000))
        heap_last = page.evaluate(
            "() => performance.memory?.usedJSHeapSize || 0")

        arrived = [one for one in rows if one["shown_ms"] is not None]
        print()
        if not arrived:
            print("  No swap ever put the new generation on screen. The swap "
                  "route is broken\n  somewhere between the API and the panel — "
                  "that is a finding about the\n  viewer, not about the "
                  "workaround. Nothing here says what a swap costs.")
        else:
            middles = sorted(one["shown_ms"] for one in arrived)
            blanks = sorted(one["blank_ms"] for one in arrived
                            if one["blank_ms"] is not None)
            print(f"  {len(arrived)} of {len(rows)} swaps put the new "
                  "generation on screen.")
            print(f"  shown: middling {middles[len(middles) // 2]:.0f} ms, "
                  f"quickest {middles[0]:.0f}, slowest {middles[-1]:.0f}")
            if blanks:
                print(f"  blank: middling {blanks[len(blanks) // 2]:.0f} ms — "
                      "what opening the new generation before closing the old "
                      "would remove")
            first_few = [one["shown_ms"] for one in arrived[:3]]
            last_few = [one["shown_ms"] for one in arrived[-3:]]
            drift = ((sum(last_few) / len(last_few))
                     / max(1e-9, sum(first_few) / len(first_few)))
            print(f"  the last swaps against the first: {drift:.2f}x — a "
                  "number well above 1.0\n  means discarded generations are "
                  "not being let go of")
        if heap_first and heap_last:
            print(f"  heap: {heap_first / 1e6:.0f} MB at the start, "
                  f"{heap_last / 1e6:.0f} MB after {len(rows)} swaps")
    except KeyboardInterrupt:
        print("\nStopped. Everything above is measured.")
    finally:
        if page is not None:
            page.close()
        if server is not None:
            server.shutdown()
        if thread is not None:
            thread.join(timeout=5)
        browser.close()
        started.stop()
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
