"""The picture must never empty when the viewer is told the data changed.

When a live run commits something new, the picture on screen has to be
refreshed. The way stock Neuroglancer offers to do that is all-or-nothing: it
can only invalidate a *whole* chunk source. Everything the page is holding for
that source is dropped and re-requested at once, so for as long as the refetch
takes there is nothing left to draw. The operator sees the specimen vanish and
come back — a black flash, on every commit.

That flash is the reason this repository carries a patch against its pinned
Neuroglancer (``frontend/scripts/patch_neuroglancer.mjs``), which adds a second,
*named* invalidation that refreshes only the handful of pieces a commit actually
touched. The patch works, and it is what the viewer uses in normal operation.
But a local patch is a maintenance burden forever, and the far better outcome
would be for the flash to be fixed where it comes from. A defect that can be
measured reliably is a defect that can be argued about and fixed; a defect that
only shows up as "it looked like it blinked" is not.

So the subject of this test is the whole-source invalidation itself, called by
hand on every source the page draws from. When this test was first written the
whole-source path was still stock, and this test measured the flash directly:
one whole frame at 0% lit, about 17 milliseconds, invisible to screenshots and
plain to the eye. The repository's patch now routes the whole-source refresh
through the same keep-drawing-until-replaced delivery the named refresh uses,
and this test is the gate that holds that cure in place: if the patch is ever
lost — a Neuroglancer upgrade, a build that skipped the patcher — the flash
comes back, and this test goes red rather than an operator noticing first.

**Watching the screen is the hard part.** A flash of this kind can last one or
two drawn frames, which at sixty frames a second is thirty milliseconds or less.
A test that takes a screenshot every quarter of a second will nearly always look
either side of it and report that nothing happened. So instead of sampling on a
timer, this test asks the browser to measure the picture *once per drawn frame*,
from inside the page. One frame is the honest smallest unit here: a frame that
was never put on screen was never seen by anybody, and a frame that was put on
screen was.

The measurement has three layers, in decreasing order of how much they are
allowed to decide:

1. **Lit pixels per frame** — the primary oracle, and the only one this test
   asserts on. It is the closest thing available to "what the operator saw".
2. **Chunk availability per frame** — how many of the pieces the view needs are
   actually in hand. This is more sensitive than pixels and it explains *why* a
   dip happened, but it is one step removed from the screen, so it is reported
   alongside a failure rather than being the thing that fails.
3. **A recording of the real compositor output** — off by default, switched on
   with an environment variable, for a human who wants to look at the flash
   rather than read numbers about it.

A refresh that never happens would also never flicker, so passing the pixel
check alone would not mean the picture refreshed. The test therefore also
counts the piece requests the page makes after the invalidation, and fails if
there were none: the screen must stay lit *and* the data must really have been
asked for again.

**There are two tests here, because the flash found two roads.** The first
drives the chunk refresh directly, as above. The second drives the road the
operator actually travels — a position of a live run landing while the page
watches — because on 2026-08-23 that road flickered while the first test
passed: the page was not dropping chunks at all, it was throwing away and
rebuilding the *drawing layers themselves* on every landing, and for the
100–300 milliseconds a rebuild took there was nothing to draw. Same black
picture, different machinery — so it needs its own gate, watching the same
way, frame by frame.
"""

from __future__ import annotations

import base64
import json
import os
import statistics
import sys
import threading
import time
from pathlib import Path

_VIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_VIZ / "app" / "picture"))

import measure_a_governed_run_at_scale as harness  # noqa: E402
from declare import declare_a_governed_picture  # noqa: E402
from server import make_server  # noqa: E402

from zmart_live.tests.test_coordinator import some_specimen  # noqa: E402
from zmart_live.tests.test_gateway import a_live_run  # noqa: E402

# --------------------------------------------------------------------------
# The numbers this test depends on, and why each one is what it is.
# --------------------------------------------------------------------------

# How wide the practice survey is, in positions. Six across is thirty-six
# positions, which is large enough that the picture comfortably fills the middle
# of the window and small enough that writing and baking it takes seconds. This
# is meant to be a cheap gate that can run on every change, not a soak test.
SURVEY_ACROSS = 6

# Which part of the drawing surface is measured: the middle half of it, in both
# directions. This is the same convention as ``image_middle`` in ``pixels.py``,
# and it is used here for the same reason — the viewer's own controls (the
# scale bar, the buttons, the sliders) sit in the corners on top of the image,
# and counting them would let a panel with nothing in it look occupied.
MIDDLE_SHARE = 0.5

# A pixel counts as "lit" — as showing specimen rather than empty ground — when
# its brightest colour channel is above this. It is the same floor
# ``fraction_lit`` in ``pixels.py`` uses, kept identical on purpose so that the
# percentages this test prints can be compared directly with the ones the other
# browser tests print. The floor sits well above the near-black of an unimaged
# region and well below any real signal, so nothing hinges on its exact value.
LIT_FLOOR = 40

# The measured region is shrunk to this many pixels each way before it is
# counted. Reading a full-size drawing surface every frame would cost more time
# than a frame has, and the measurement would start disturbing the very timing
# it is trying to observe. Sixty-four by sixty-four is four thousand pixels,
# which is plenty to tell a drawn picture from an empty one and cheap enough
# that the page keeps its normal frame rate while being watched.
SAMPLE_GRID = 64

# A frame counts as "the picture collapsed" when fewer than this share of the
# baseline's lit pixels are still lit. Half is chosen because it is far outside
# anything ordinary drawing does: pieces arriving or leaving at the edge of the
# view move the lit fraction by a few percent, whereas dropping an entire source
# takes it essentially to zero. Anything between roughly a fifth and four fifths
# would separate those two cases equally well, so this threshold is not a
# delicate one.
COLLAPSE_SHARE = 0.5

# How long to let the picture stand still before measuring anything, in
# milliseconds. Everything is already committed and baked before the page opens,
# so this is only waiting out the last of the drawing, not waiting for data.
SETTLE_MS = 2_500

# How many frames of a quiet, unchanging picture to collect before acting. At a
# normal sixty frames a second this is about half a second of "this is what the
# operator was looking at", which is more than enough to take a stable middle
# value from, and short enough not to lengthen the test noticeably.
STEADY_FRAMES_WANTED = 30

# How long to keep watching after the invalidation is fired, in milliseconds.
# Two seconds is comfortably longer than a local server takes to hand back
# everything a modest survey needs, so the recovery is inside the recording and
# a failure can say how long the flash lasted rather than only that it began.
WATCH_AFTER_MS = 2_000

# The baseline picture must be at least this lit before the test is willing to
# believe its own measurement. If the window opened on a mostly empty view then
# there was never much picture to lose, and "it did not go dark" would be a
# statement about nothing. This guard is not the defect being tested, which is
# why failing it raises ``TheMeasurementCouldNotBeMade`` rather than an
# assertion: a broken fixture must never be mistaken for a verdict.
BASELINE_MUST_BE_LIT = 0.30


class TheMeasurementCouldNotBeMade(Exception):
    """The fixture or the page was not in a state where the question makes sense.

    This is raised when something goes wrong *before* the real question is
    asked — the survey did not draw, the page never finished opening, the
    browser would not let the drawing surface be read. It is deliberately not
    an ``AssertionError``, so that a broken fixture reads as a broken fixture
    in the test report rather than as a verdict about the screen.
    """


# --------------------------------------------------------------------------
# The pieces of JavaScript that do the measuring, kept as named strings so the
# Python below reads as a description of the experiment rather than as a wall
# of quoted code.
# --------------------------------------------------------------------------

# Reading pixels back out of a WebGL drawing surface only works if the browser
# was told to keep that surface around after it has been shown. By default it is
# free to throw it away the moment the frame is composited, and a read then
# returns nothing at all. The attribute that asks it to keep the surface is
# chosen when the drawing context is first created, which happens deep inside
# Neuroglancer's start-up, so there is no later moment at which it can be set.
# The only way in is to wrap the function that creates contexts and add the
# attribute to whatever the page asked for — and to do that before any of the
# page's own code has run, which is what ``add_init_script`` is for.
_KEEP_THE_DRAWN_PIXELS_READABLE = """(() => {
  const makeContext = HTMLCanvasElement.prototype.getContext;
  HTMLCanvasElement.prototype.getContext = function (kind, asked) {
    if (kind === 'webgl2' || kind === 'webgl' || kind === 'experimental-webgl') {
      asked = Object.assign({}, asked || {}, { preserveDrawingBuffer: true });
    }
    return makeContext.call(this, kind, asked);
  };
})();"""

# The per-frame recorder. It hangs itself off a `requestAnimationFrame` loop,
# which the browser runs once for every frame it is about to draw, and on each
# pass it writes down three things: the moment, how much of the middle of the
# picture is lit, and how many of the pieces the view wants are actually in hand.
#
# The pixels are read by drawing the middle of the big drawing surface into a
# small plain 2D canvas and reading that back. Shrinking first is what keeps the
# cost per frame low; drawing onto black first is what makes a fully transparent
# surface read as dark, which is what the operator would see against the page.
#
# One honest limitation, worth knowing when reading the numbers. These callbacks
# run just before the browser paints, so what is read is the picture as it stood
# for the frame that has just been shown, not the one about to be. A reading may
# therefore sit one frame later than the frame it describes. That does not blur
# a flash or hide one — a dark frame is still recorded as a dark frame, and its
# length in frames is still right — it only means the moment a flash is reported
# to have begun can be out by a single frame, about sixteen milliseconds.
_WATCH_EVERY_FRAME = """([grid, middleShare, litFloor]) => {
  const drawn = document.querySelector('canvas');
  if (!drawn) return { started: false, why: 'the page has no drawing surface' };
  const small = document.createElement('canvas');
  small.width = grid;
  small.height = grid;
  const flat = small.getContext('2d', { willReadFrequently: true });
  const watch = { frames: [], stop: false, invalidatedAt: null, trouble: null };
  window.zmartFlickerWatch = watch;

  const onEveryFrame = (moment) => {
    if (watch.stop) return;
    let lit = null;
    try {
      const margin = (1 - middleShare) / 2;
      flat.fillStyle = '#000000';
      flat.fillRect(0, 0, grid, grid);
      flat.drawImage(
        drawn,
        drawn.width * margin, drawn.height * margin,
        drawn.width * middleShare, drawn.height * middleShare,
        0, 0, grid, grid);
      const seen = flat.getImageData(0, 0, grid, grid).data;
      let counted = 0;
      for (let at = 0; at < seen.length; at += 4) {
        const brightest = Math.max(seen[at], seen[at + 1], seen[at + 2]);
        if (brightest > litFloor) counted += 1;
      }
      lit = counted / (grid * grid);
    } catch (problem) {
      watch.trouble = String(problem);
    }

    // The same reading the viewer's own progress display uses: how many pieces
    // the current view needs, and how many of them the page is holding. It
    // moves before the pixels do, so it is the best available explanation of
    // why a dip in the picture happened.
    let needed = 0;
    let available = 0;
    let layers = 0;
    const viewer = window.zmartViewer;
    if (viewer) {
      for (const managed of viewer.layerManager.managedLayers) {
        for (const drawing of (managed.layer && managed.layer.renderLayers) || []) {
          const progress = drawing.layerChunkProgressInfo;
          if (!progress) continue;
          layers += 1;
          needed += progress.numVisibleChunksNeeded;
          available += progress.numVisibleChunksAvailable;
        }
      }
    }

    watch.frames.push({
      t: moment, lit, needed, available, layers,
    });
    requestAnimationFrame(onEveryFrame);
  };

  requestAnimationFrame(onEveryFrame);
  return { started: true, why: null };
}"""

# The whole-source invalidation, fired by hand on every source the page is
# drawing from. This is exactly the loop `invalidateTheDirtyPieces` in
# `engine.js` walks to find its sources — every entry in the shared table that
# knows how to invalidate itself and describes a volume — except that here each
# one is asked to refresh *everything* rather than named pieces. It is the same
# call `letGoOfDecodedPieces` makes when a run announces it wrote image into a
# store already open, so what is measured here is what the operator gets then.
_FIRE_THE_WHOLE_SOURCE_INVALIDATION = """() => {
  const watch = window.zmartFlickerWatch;
  const shared = window.zmartViewer.chunkManager
    && window.zmartViewer.chunkManager.rpc
    && window.zmartViewer.chunkManager.rpc.objects;
  if (!shared) return { asked: 0, at: null };
  // Written down before the first call, so that every frame drawn from here on
  // is counted as "after the invalidation" even if the browser manages to draw
  // one in the middle of the loop.
  const at = performance.now();
  if (watch) watch.invalidatedAt = at;
  let asked = 0;
  for (const [, held] of shared) {
    if (!held || typeof held.invalidateCache !== 'function') continue;
    if (!held.spec || !held.spec.upperVoxelBound) continue;
    held.invalidateCache();
    asked += 1;
  }
  return { asked, at };
}"""

_STOP_WATCHING = """() => {
  const watch = window.zmartFlickerWatch;
  if (!watch) return null;
  watch.stop = true;
  return {
    frames: watch.frames,
    invalidatedAt: watch.invalidatedAt,
    trouble: watch.trouble,
  };
}"""


# --------------------------------------------------------------------------
# Reading the recording.
# --------------------------------------------------------------------------

def _read_the_frame_recording(recording: dict) -> dict:
    """Turn a list of per-frame readings into the story of what was seen.

    The recording is every frame the browser drew while it was being watched,
    each one carrying the moment it happened, how much of the middle of the
    picture was lit, and how many pieces were in hand. This works out what the
    steady picture looked like before anything was asked of it, how far it fell
    afterwards, and — the number that matters most — the longest unbroken
    stretch of frames in which it stayed collapsed, in frames and in
    milliseconds.

    Returns a plain dictionary of those findings. It raises nothing; a recording
    too short or too empty to say anything comes back with ``usable`` set to
    false and a sentence saying why, and the caller decides what to do about it.
    """
    frames = [one for one in (recording.get("frames") or [])
              if one.get("lit") is not None]
    fired_at = recording.get("invalidatedAt")

    if fired_at is None:
        return {"usable": False,
                "why": "the invalidation was never recorded, so before and "
                       "after cannot be told apart",
                "frames": len(frames)}

    before = [one for one in frames if one["t"] < fired_at]
    after = [one for one in frames if one["t"] >= fired_at]
    if len(before) < 3 or len(after) < 3:
        return {"usable": False,
                "why": (f"only {len(before)} frames were drawn before the "
                        f"invalidation and {len(after)} after it, which is too "
                        "few to compare"),
                "frames": len(frames)}

    # The middle value rather than the average, because the last frames before
    # the invalidation are the ones most likely to hold a stray reading, and a
    # middle value is not moved by one of those the way an average is.
    baseline = statistics.median(one["lit"] for one in before)
    collapsed_below = baseline * COLLAPSE_SHARE

    deepest_frame = min(after, key=lambda one: one["lit"])

    # The longest unbroken run of collapsed frames. Its length in milliseconds
    # is measured from the first collapsed frame to whichever frame ended it —
    # the first healthy one after it, or the end of the recording. That is the
    # honest span, because a frame stays on screen until the next one replaces
    # it, so a single collapsed frame is still one frame's worth of darkness.
    longest = {"frames": 0, "ms": 0.0, "began_at": None, "deepest": None,
               "recovered": True}
    running: list[dict] = []

    def close_the_run(ended_at: float | None) -> None:
        """Finish a stretch of collapsed frames and keep it if it is the longest.

        ``ended_at`` is the moment of the first healthy frame after the stretch,
        or ``None`` when the recording simply stopped while the picture was
        still collapsed. In that second case the span can only be measured up to
        the last frame that was actually recorded, which understates it — so it
        is flagged, and the failure message says the picture had not come back.
        """
        if not running:
            return
        recovered = ended_at is not None
        last_moment = ended_at if recovered else running[-1]["t"]
        if len(running) > longest["frames"]:
            longest.update({
                "frames": len(running),
                "ms": last_moment - running[0]["t"],
                "began_at": running[0]["t"] - fired_at,
                "deepest": min(one["lit"] for one in running),
                "recovered": recovered,
            })

    for one in after:
        if one["lit"] < collapsed_below:
            running.append(one)
        else:
            close_the_run(one["t"])
            running = []
    close_the_run(None)

    # How long a frame took, measured as the gap between one frame and the
    # next. The last frame has no successor, which is why the two lists being
    # paired here are deliberately of different lengths.
    intervals = [b["t"] - a["t"]
                 for a, b in zip(frames, frames[1:], strict=False)
                 if b["t"] > a["t"]]

    return {
        "usable": True,
        "why": None,
        "baseline": baseline,
        "collapsed_below": collapsed_below,
        "deepest": deepest_frame["lit"],
        "deepest_at_ms": deepest_frame["t"] - fired_at,
        "deepest_needed": deepest_frame["needed"],
        "deepest_available": deepest_frame["available"],
        "collapsed_frames": longest["frames"],
        "collapsed_ms": longest["ms"],
        "collapse_began_at_ms": longest["began_at"],
        "picture_came_back": longest["recovered"],
        "watched_after_ms": after[-1]["t"] - fired_at,
        "frames_before": len(before),
        "frames_after": len(after),
        "typical_frame_ms": (statistics.median(intervals)
                             if intervals else None),
        "chunks_before": (before[-1]["needed"], before[-1]["available"]),
    }


def _describe_what_was_seen(found: dict) -> str:
    """The sentence a person reading a failed run of this test should get.

    The audience for this is somebody looking at continuous-integration output,
    quite possibly a microscopist rather than a programmer, and quite possibly
    without the page in front of them. So it says what happened on screen in
    plain terms first, and the supporting numbers after.
    """
    how_many = found["collapsed_frames"]
    frame_word = "frame" if how_many == 1 else "frames"
    if found["typical_frame_ms"] is None:
        frame_cost = "not enough frames were drawn to say"
    else:
        frame_cost = f"{found['typical_frame_ms']:.1f} ms, typically"
    if found["picture_came_back"]:
        recovery = ("The picture did come back on its own once the pieces had "
                    "been fetched again.")
    else:
        recovery = ("The picture had still not come back "
                    f"{found['watched_after_ms']:.0f} ms later, when the "
                    "watching stopped, so the flash lasted at least as long as "
                    "the figure above and possibly longer.")

    lines = [
        f"the screen dropped from {found['baseline']:.0%} lit to "
        f"{found['deepest']:.0%} lit for {how_many} {frame_word} "
        f"({found['collapsed_ms']:.0f} ms) after a whole-source cache "
        "invalidation — the operator sees this as a black flash.",
        "",
        "What was measured, frame by frame, from inside the page:",
        f"  steady picture before  {found['baseline']:.1%} of the middle lit, "
        f"over {found['frames_before']} frames",
        f"  deepest frame after    {found['deepest']:.1%} lit, "
        f"{found['deepest_at_ms']:.0f} ms after the invalidation",
        f"  stayed collapsed for   {how_many} {frame_word} "
        f"({found['collapsed_ms']:.0f} ms), starting "
        f"{found['collapse_began_at_ms']:.0f} ms after it",
        f"  one frame cost         {frame_cost}",
        f"  pieces in hand         {found['chunks_before'][1]} of "
        f"{found['chunks_before'][0]} needed before, "
        f"{found['deepest_available']} of {found['deepest_needed']} "
        "at the deepest frame",
        "",
        recovery,
        "",
        "The threshold for 'collapsed' is half the steady picture, which is "
        f"{found['collapsed_below']:.1%} lit here. Ordinary drawing moves the "
        "lit fraction by a few percent; dropping a whole source takes it to "
        "nearly nothing, so there is a wide gap between the two.",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# The optional recording of what the compositor really showed.
# --------------------------------------------------------------------------

def _start_recording_the_screen(page, into: Path):
    """Ask the browser to send us every frame it composites, and save them.

    This is corroboration for a human, not evidence the test relies on. The
    numbers above are measured inside the page and could in principle be wrong
    about what reached the glass; these are the actual frames the browser put on
    screen, saved as images beside a timeline, so somebody can look at the flash
    with their own eyes.

    It is off unless ``ZMART_FLICKER_SCREENCAST`` names a folder, because
    capturing every frame is not free and would make an ordinary run of this
    test slower and noisier for no gain.
    """
    into.mkdir(parents=True, exist_ok=True)
    session = page.context.new_cdp_session(page)
    caught: list[dict] = []

    def keep_one_frame(payload: dict) -> None:
        number = len(caught)
        name = f"frame_{number:05d}.jpg"
        (into / name).write_bytes(base64.b64decode(payload["data"]))
        caught.append({
            "file": name,
            "browser_timestamp": payload.get("metadata", {}).get("timestamp"),
            "captured_at": time.perf_counter(),
        })
        try:
            session.send("Page.screencastFrameAck",
                         {"sessionId": payload["sessionId"]})
        except Exception:
            # The page is closing and the acknowledgement has nowhere to go.
            # Losing the tail of a debugging recording is not worth an error.
            pass

    session.on("Page.screencastFrame", keep_one_frame)
    session.send("Page.startScreencast",
                 {"format": "jpeg", "quality": 60, "everyNthFrame": 1})
    return session, caught


def _stop_recording_the_screen(session, caught: list[dict], into: Path,
                               found: dict) -> None:
    """Stop the recording and write the timeline beside the saved frames."""
    try:
        session.send("Page.stopScreencast")
    except Exception:
        pass
    (into / "timeline.json").write_text(
        json.dumps({"findings": found, "frames": caught}, indent=2),
        encoding="utf-8")


# --------------------------------------------------------------------------
# The test itself.
# --------------------------------------------------------------------------

def test_the_screen_never_goes_black_when_the_cache_is_invalidated(
    browser, built_dist, tmp_path
):
    """A complete, settled picture must survive being told its data changed.

    The scenario is deliberately as quiet as it can be made. A modest survey is
    written and every position is committed *before* the picture is declared, so
    by the time the page opens there is nothing still arriving and nothing still
    baking. The picture is then left alone to settle, and only then is the
    whole-source invalidation fired. Anything the measurement sees after that
    moment is caused by the invalidation and by nothing else, which is what
    makes a two-frame dip attributable rather than merely interesting.
    """
    harness.FIXTURES = tmp_path

    # Everything is committed before the picture is declared, so the bake below
    # writes a complete survey and no position lands while the measurement is
    # running. The subject here is invalidation, not acquisition.
    run, order = harness.the_run(SURVEY_ACROSS)
    for position_id in order:
        harness.fast_publish(run, position_id)

    shown = run.folder / "views" / "shown"
    store = declare_a_governed_picture(shown, run.folder, name="live",
                                       bake=True)

    site = Path(os.environ.get("ZMART_STORM_BUILT_DIST", built_dist))
    server = make_server(port=0, data_dir=shown, site_dir=site,
                         store=[store.name], window=harness.BRIGHT, live=True)
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()

    recording_into = (Path(os.environ["ZMART_FLICKER_SCREENCAST"])
                      if os.environ.get("ZMART_FLICKER_SCREENCAST") else None)

    page = browser.new_page(viewport={"width": 1000, "height": 780})
    screencast = None
    caught_frames: list[dict] = []
    try:
        port = server.server_address[1]

        # This has to be in place before any of the page's own code runs,
        # because the drawing surface's attributes are fixed when Neuroglancer
        # first asks for a drawing context and can never be changed afterwards.
        page.add_init_script(_KEEP_THE_DRAWN_PIXELS_READABLE)
        # The viewer asks the server every so often whether the run has moved
        # on. Nothing here ever moves on — the survey was finished before the
        # page opened — so the only thing those checks can contribute during
        # the measurement is background traffic. Setting the interval to a
        # minute puts them well outside the few seconds that are being watched,
        # which keeps the invalidation the only thing that happened.
        page.add_init_script("globalThis.zmartLiveCheckMs = 60_000")

        page.goto(f"http://127.0.0.1:{port}", wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartViewer !== undefined",
                               timeout=60_000)
        page.wait_for_function("() => window.zmartSourcesWaiting() === 0",
                               timeout=90_000)
        # Every piece the view wants is in hand. This is the page's own account
        # of itself, and it is what "the picture is complete" means here.
        page.wait_for_function(
            """() => {
              let needed = 0, available = 0;
              for (const managed of
                   window.zmartViewer.layerManager.managedLayers) {
                for (const drawing of
                     (managed.layer && managed.layer.renderLayers) || []) {
                  const progress = drawing.layerChunkProgressInfo;
                  if (!progress) continue;
                  needed += progress.numVisibleChunksNeeded;
                  available += progress.numVisibleChunksAvailable;
                }
              }
              return available > 0 && available >= needed;
            }""",
            timeout=90_000,
        )
        page.wait_for_timeout(SETTLE_MS)

        if recording_into is not None:
            screencast, caught_frames = _start_recording_the_screen(
                page, recording_into)

        started = page.evaluate(_WATCH_EVERY_FRAME,
                                [SAMPLE_GRID, MIDDLE_SHARE, LIT_FLOOR])
        if not started.get("started"):
            raise TheMeasurementCouldNotBeMade(
                "the per-frame watcher could not be installed: "
                f"{started.get('why')}")

        # Collect a stretch of steady frames first. This is what "before" means,
        # and it is also a check that the page is drawing at all — a page that
        # has stopped producing frames would otherwise look exactly like a page
        # whose picture never went dark.
        gathering_until = time.monotonic() + 10
        while time.monotonic() < gathering_until:
            so_far = page.evaluate(
                "() => window.zmartFlickerWatch.frames.length")
            if so_far >= STEADY_FRAMES_WANTED:
                break
            page.wait_for_timeout(100)
        else:
            raise TheMeasurementCouldNotBeMade(
                "the page did not draw "
                f"{STEADY_FRAMES_WANTED} frames in ten seconds, so there is no "
                "steady picture to compare anything against")

        # From here on, count the piece requests the page makes. A refresh that
        # never asks for anything can never flicker either, so the pixel check
        # alone could be fooled by an invalidation that quietly did nothing.
        # The listener starts just before the invalidation is fired, so every
        # request it sees was caused by it — the picture was settled and the
        # live poll was pushed a minute away before the watching began.
        refetches: list[str] = []
        page.on("request",
                lambda asked: refetches.append(asked.url)
                if "/data/" in asked.url and "/c/" in asked.url else None)

        fired = page.evaluate(_FIRE_THE_WHOLE_SOURCE_INVALIDATION)
        if not fired.get("asked"):
            raise TheMeasurementCouldNotBeMade(
                "no chunk source in the page accepted a whole-source "
                "invalidation, so the thing this test is about never happened")

        page.wait_for_timeout(WATCH_AFTER_MS)
        recording = page.evaluate(_STOP_WATCHING)
        if recording is None:
            raise TheMeasurementCouldNotBeMade(
                "the per-frame watcher disappeared from the page before it "
                "could be read back")
        if recording.get("trouble"):
            raise TheMeasurementCouldNotBeMade(
                "the drawing surface could not be read back: "
                f"{recording['trouble']}. This usually means the browser threw "
                "the drawn pixels away after compositing them, which the "
                "preserveDrawingBuffer override at the top of this file is "
                "meant to prevent")

        found = _read_the_frame_recording(recording)
        if not found["usable"]:
            raise TheMeasurementCouldNotBeMade(
                f"the frame recording cannot be read: {found['why']}")
        if found["baseline"] < BASELINE_MUST_BE_LIT:
            raise TheMeasurementCouldNotBeMade(
                f"the settled picture was only {found['baseline']:.1%} lit, "
                f"below the {BASELINE_MUST_BE_LIT:.0%} this test needs before "
                "it can tell a collapse from an already-empty window. The "
                "survey did not draw, so nothing was measured")

        print("FLICKER WATCH:", json.dumps({
            key: value for key, value in found.items()
            if key not in ("usable", "why")
        }, default=float), flush=True)

        if recording_into is not None:
            _stop_recording_the_screen(screencast, caught_frames,
                                       recording_into, found)
            (recording_into / "frames.json").write_text(
                json.dumps(recording["frames"], indent=2), encoding="utf-8")
            screencast = None
            print("FLICKER RECORDING:", recording_into, flush=True)

        # The two assertions. Everything above is setup and measurement; these
        # are the questions. First: the refresh must really have happened —
        # pieces must have been asked for again after the invalidation, because
        # a refresh that fetches nothing can never flicker and would pass the
        # pixel check while leaving the operator's picture permanently stale.
        assert refetches, (
            "the whole-source invalidation caused no piece requests at all — "
            "the screen stayed lit only because nothing was refreshed, which "
            "trades a visible flash for a silently stale picture"
        )
        # Second: at no drawn frame may the picture have collapsed. This is
        # what the operator experiences as the absence of the black flash.
        assert found["deepest"] >= found["collapsed_below"], (
            _describe_what_was_seen(found))
        print(f"REFRESH CONFIRMED: {len(refetches)} piece requests after the "
              "invalidation", flush=True)
    finally:
        if screencast is not None and recording_into is not None:
            _stop_recording_the_screen(screencast, caught_frames,
                                       recording_into, {})
        page.close()
        server.shutdown()
        serving.join(timeout=5)


# The settled half-picture must be at least this lit before the landing test
# trusts its own measurement. It is lower than BASELINE_MUST_BE_LIT above on
# purpose: this scenario opens with one of the run's two positions committed,
# so only part of the window holds specimen — measured at about 25% of the
# middle in practice. What matters for catching a collapse is the *relative*
# drop to half of whatever the steady picture was, and a quarter-lit picture
# gives that comparison plenty of room.
LANDING_BASELINE_MUST_BE_LIT = 0.10


def test_the_screen_never_goes_black_when_a_position_lands(
    browser, built_dist, tmp_path
):
    """A position landing must add to the picture without ever taking it away.

    This is the road the operator actually drives: a live run is open on
    screen, and the microscope (here: the test) commits another position. The
    news reaches the page, the page refreshes what it draws, and the new
    position appears beside the ones already there.

    The defect this gate holds out is the one found on 2026-08-23. Every
    landing advanced the run's revision, and the refresh answered by making
    the engine resolve the picture's address from scratch — which first throws
    away the loaded drawing layers and only then reads the description again.
    Between those two moments the layer had nothing to draw: the whole picture
    went black for 100–300 ms, at every landing, sixteen times over a sixteen
    position replay. The chunk-refresh gate above stayed green throughout,
    because no chunk was ever dropped — the *layers* were. Since the picture's
    description is written once at declaration and never moves (see
    declare_a_governed_picture), re-reading it bought nothing; the refresh is
    pixels-only now, delivered in place while the stale pixels keep drawing.

    So this test watches, frame by frame, exactly the way the first one does,
    while a real landing happens, and asserts three things: the picture never
    collapses on any drawn frame, the drawing layers are never torn down, and
    the landing genuinely arrived — the revision advanced and pieces were
    fetched. A refresh that never happened would pass the first two for free.
    """
    run = a_live_run(tmp_path)
    run.write_and_publish("posA", some_specimen(1700))

    server = make_server(
        port=0,
        data_dir=run.folder,
        site_dir=Path(os.environ.get("ZMART_STORM_BUILT_DIST", built_dist)),
        store="views/live/live.ome.zarr",
        window=(0, 4095),
        live=True,
    )
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()

    page = browser.new_page(viewport={"width": 1000, "height": 780})
    try:
        port = server.server_address[1]
        page.add_init_script(_KEEP_THE_DRAWN_PIXELS_READABLE)
        # The slow recovery poll is set fast so the landing's news reaches the
        # page promptly even if the immediate announcement is missed — this
        # test is about what the refresh does to the picture, not about which
        # of the two delivery roads carried the news.
        page.add_init_script("globalThis.zmartLiveCheckMs = 500")

        page.goto(f"http://127.0.0.1:{port}", wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartViewer !== undefined",
                               timeout=60_000)
        page.wait_for_function(
            """() => window.zmartConfig?.liveState?.runs?.[0]?.revision >= 1""",
            timeout=60_000)
        # Every piece the view wants is in hand — the first position has
        # fully arrived and drawn before anything else is allowed to happen.
        page.wait_for_function(
            """() => {
              let needed = 0, available = 0;
              for (const managed of
                   window.zmartViewer.layerManager.managedLayers) {
                for (const drawing of
                     (managed.layer && managed.layer.renderLayers) || []) {
                  const progress = drawing.layerChunkProgressInfo;
                  if (!progress) continue;
                  needed += progress.numVisibleChunksNeeded;
                  available += progress.numVisibleChunksAvailable;
                }
              }
              return available > 0 && available >= needed;
            }""",
            timeout=90_000,
        )
        page.wait_for_timeout(SETTLE_MS)

        started = page.evaluate(_WATCH_EVERY_FRAME,
                                [SAMPLE_GRID, MIDDLE_SHARE, LIT_FLOOR])
        if not started.get("started"):
            raise TheMeasurementCouldNotBeMade(
                "the per-frame watcher could not be installed: "
                f"{started.get('why')}")

        gathering_until = time.monotonic() + 10
        while time.monotonic() < gathering_until:
            so_far = page.evaluate(
                "() => window.zmartFlickerWatch.frames.length")
            if so_far >= STEADY_FRAMES_WANTED:
                break
            page.wait_for_timeout(100)
        else:
            raise TheMeasurementCouldNotBeMade(
                "the page did not draw "
                f"{STEADY_FRAMES_WANTED} frames in ten seconds, so there is no "
                "steady picture to compare anything against")

        refetches: list[str] = []
        page.on("request",
                lambda asked: refetches.append(asked.url)
                if "/data/" in asked.url else None)

        # Mark the moment, then land the second position. Every frame drawn
        # from here on is "after the landing" for the reading below.
        page.evaluate(
            "() => { window.zmartFlickerWatch.invalidatedAt ="
            " performance.now(); }")
        run.write_and_publish("posB", some_specimen(3000))

        # Wait until the page has heard the news and drawn itself complete
        # again, then a moment longer, so the whole refresh — including any
        # collapse it might cause — is inside the recording.
        page.wait_for_function(
            """() => window.zmartConfig?.liveState?.runs?.[0]?.revision >= 2""",
            timeout=60_000)
        page.wait_for_timeout(WATCH_AFTER_MS)

        recording = page.evaluate(_STOP_WATCHING)
        if recording is None:
            raise TheMeasurementCouldNotBeMade(
                "the per-frame watcher disappeared from the page before it "
                "could be read back")
        if recording.get("trouble"):
            raise TheMeasurementCouldNotBeMade(
                "the drawing surface could not be read back: "
                f"{recording['trouble']}")

        found = _read_the_frame_recording(recording)
        if not found["usable"]:
            raise TheMeasurementCouldNotBeMade(
                f"the frame recording cannot be read: {found['why']}")
        if found["baseline"] < LANDING_BASELINE_MUST_BE_LIT:
            raise TheMeasurementCouldNotBeMade(
                f"the settled picture was only {found['baseline']:.1%} lit, "
                f"below the {LANDING_BASELINE_MUST_BE_LIT:.0%} this test "
                "needs before it can tell a collapse from an already-empty "
                "window. The first position did not draw, so nothing was "
                "measured")

        print("LANDING WATCH:", json.dumps({
            key: value for key, value in found.items()
            if key not in ("usable", "why")
        }, default=float), flush=True)

        # The landing must genuinely have happened: the revision moved (waited
        # on above), the refresh road fired, and pieces were fetched. Without
        # these, a page that quietly ignored the landing would pass the picture
        # checks for free while showing the operator a stale picture.
        assert page.evaluate(
            "() => window.zmartSourceRefreshing.sources.length") > 0, (
            "the landing advanced the revision but the refresh road never "
            "fired — the picture on screen is silently stale")
        assert refetches, (
            "the landing caused no piece requests at all — the screen stayed "
            "lit only because nothing was refreshed, which trades a visible "
            "flash for a silently stale picture")

        # The picture may never collapse on any drawn frame. This is the
        # assertion that failed — 0% lit for 100–300 ms per landing — before
        # the refresh became pixels-only.
        assert found["deepest"] >= found["collapsed_below"], (
            _describe_what_was_seen(found))

        # And the drawing layers themselves must survive the landing. This is
        # the mechanism behind the collapse, asserted directly so a future
        # rebuild that happens to refill within one frame — too fast for the
        # pixel check to see, but a stutter the operator can still feel — is
        # caught all the same.
        frames = [one for one in (recording.get("frames") or [])
                  if one.get("lit") is not None]
        fired_at = recording["invalidatedAt"]
        drawing_before = statistics.median(
            one["layers"] for one in frames if one["t"] < fired_at)
        fewest_after = min(
            one["layers"] for one in frames if one["t"] >= fired_at)
        assert fewest_after >= drawing_before, (
            f"the page was drawing with {drawing_before:.0f} layers before "
            f"the landing and only {fewest_after} at some frame after it — "
            "the landing tore drawing layers down and rebuilt them, which is "
            "the very mechanism that blacked out the picture on 2026-08-23"
        )
        print(f"LANDING CONFIRMED: {len(refetches)} piece requests, layers "
              f"held at {drawing_before:.0f}", flush=True)
    finally:
        page.close()
        server.shutdown()
        serving.join(timeout=5)
