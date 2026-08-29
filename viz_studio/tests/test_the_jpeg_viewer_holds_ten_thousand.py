"""The scan drawn from small JPEGs, at the size it has to survive.

A scan of ten thousand fields is the whole reason this engine exists, and it is
also the size at which the obvious way of doing things stops working. So these
tests are mostly about restraint: what the viewer *refuses* to do when there is
too much of it.

They drive a real browser and read what it drew, because every one of the
mistakes these guard against passed a test that only counted things. A picture
that fetched exactly the right number of fields and came out blank is still a
blank picture.
"""

from __future__ import annotations

import http.server
import json
import shutil
import socketserver
import threading
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("tifffile")
pytest.importorskip("PIL")

_VIZ = Path(__file__).resolve().parents[1]

#: How large a picture the browser gets. Fixed, because how many fields fit on
#: screen is what decides how many are fetched, and a test whose numbers move
#: with the window is no test at all.
A_WINDOW = {"width": 1000, "height": 700}


def _serve(folder: Path):
    """Hand out a folder over HTTP, the way the pictures reach a browser."""

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(folder), **kwargs)

        def log_message(self, *args):
            pass

    socketserver.TCPServer.allow_reuse_address = True
    server = socketserver.TCPServer(("127.0.0.1", 0), Quiet)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


THE_PAGE = """<!doctype html><meta charset="utf-8">
<style>html,body{margin:0;background:#05070d}#box{position:absolute;inset:0}</style>
<div id="box"></div>
<script type="module">
window.__fault = null;
window.__asked = [];
try {
  const { openViewer } = await import("./options/jpeg-under/viewer.js");
  window.__viewer = await openViewer(document.getElementById("box"), {
    acquisitions: [{ url: "./scan", name: "overview" }],
    background: "#05070d",
  });
  window.__ready = true;
} catch (e) { window.__fault = String((e && e.stack) || e); }
</script>
"""


@pytest.fixture(scope="module")
def a_served_scan(tmp_path_factory):
    """A real scan made by the helper, served the way a browser would get it.

    Small on purpose — nine fields, really exported and really converted, so
    that the two halves of this are shown to fit together. The tests that need
    ten thousand build the note for those themselves, because writing ten
    thousand TIFFs to prove a drawing rule would take minutes and prove nothing
    extra.
    """
    from viz_studio.backend.jpeg_tiles import make_small_pictures
    from viz_studio.backend.mock_scan import export_a_mock_scan

    root = tmp_path_factory.mktemp("jpeg-viewer")
    exported = root / "exported"
    places = export_a_mock_scan(exported, across=3, down=3, pixels=64, um_per_pixel=1.0)
    note = make_small_pictures(exported, places, root / "scan")

    shutil.copytree(_VIZ / "options", root / "options",
                    ignore=shutil.ignore_patterns("measure", "harness", "*.md"))
    (root / "index.html").write_text(THE_PAGE, encoding="utf-8")

    server, url = _serve(root)
    try:
        yield root, url, note
    finally:
        server.shutdown()


def _write_a_note_of(root: Path, how_many: int, note: dict) -> None:
    """Say there are this many fields, laid out in a square.

    Every field gets its own file, even though all the files hold the same
    picture. That matters more than it looks: what these tests measure is how
    many pictures the viewer *asks for*, and if the fields shared one address
    the browser would answer the second request from its own store and the
    measurement would come out zero however badly the viewer behaved. Separate
    names, one picture — cheap on disk, and honest about the asking.
    """
    import os

    one = note["tiles"][0]
    pictures = root / "scan"
    source = pictures / one["src"]
    side = int(how_many ** 0.5) + 1
    tiles = []
    for index in range(how_many):
        row, column = divmod(index, side)
        name = f"F{index:05d}.jpg"
        here = pictures / name
        if not here.exists():
            # Copied, not hard-linked: NTFS caps a file at 1023 links, and a
            # ten-thousand-field fixture could never be built on Windows. The
            # copies are four kilobytes each.
            shutil.copy(source, here)
        tiles.append(dict(one, label=f"F{index:05d}", src=name,
                          x0=column * one["w"], y0=row * one["h"]))
    (pictures / "tiles.json").write_text(
        json.dumps(dict(note, tiles=tiles)), encoding="utf-8"
    )


def _open(browser, url: str):
    page = browser.new_page(viewport=A_WINDOW)
    asked = []
    page.on("request", lambda r: asked.append(r.url) if r.url.endswith(".jpg") else None)
    page.goto(f"{url}/index.html")
    page.wait_for_function("window.__ready === true || window.__fault", timeout=60_000)
    fault = page.evaluate("window.__fault")
    assert not fault, fault
    return page, asked


def _what_was_drawn(page):
    """The scan's own surface, as an array of greys, with nothing else in it.

    Waits for the browser to finish a drawing before reading. The viewer asks
    the browser for a frame rather than drawing on the spot — that is what
    keeps a burst of changes from redrawing the scan a dozen times — so reading
    the canvas the instant the viewer opens can catch it before that frame has
    happened, and see an empty surface that was never shown to anybody.
    """
    page.evaluate("""() => new Promise((done) => {
      requestAnimationFrame(() => requestAnimationFrame(done));
    })""")
    shot = page.evaluate("""() => {
      const canvases = document.querySelectorAll('canvas');
      return canvases[1].toDataURL('image/png');
    }""")
    import base64
    import io

    from PIL import Image

    raw = base64.b64decode(shot.split(",", 1)[1])
    with Image.open(io.BytesIO(raw)) as picture:
        return np.asarray(picture.convert("L"), dtype=np.float32)


def test_ten_thousand_fields_are_asked_for_once_each(browser, a_served_scan):
    """The size this exists to survive, and the restraint that lets it.

    Zoomed out to the whole of ten thousand fields, each is decoded at the
    few pixels it is drawn — a kilobyte apiece, so all of them fit in the
    byte budget together. The restraint that matters is that nothing is
    thrown away and immediately asked for again: a cache smaller than one
    drawn scan once refetched its own evictions forever, and the operator
    watched a grey band crawl through a finished overview.
    """
    root, url, note = a_served_scan
    _write_a_note_of(root, 10_000, note)

    page, asked = _open(browser, url)
    page.wait_for_timeout(4000)
    assert len(asked) == len(set(asked)), (
        f"{len(asked) - len(set(asked))} pictures were fetched more than once; "
        "evicted work is being asked for again"
    )
    page.close()


def test_the_whole_scan_is_there_in_the_very_first_frame(browser, a_served_scan):
    """A picture that is still loading looks exactly like one that is broken.

    So nothing is ever waited for. Every field on screen is painted the one
    colour its note gives for it before any picture is asked for, which means
    the scan is complete and readable from the first frame and only gets
    sharper. This is the check that a frame-counting test cannot make: it looks
    at the pixels.
    """
    root, url, note = a_served_scan
    _write_a_note_of(root, 2_500, note)

    page, _ = _open(browser, url)
    drawn = _what_was_drawn(page)
    covered = float((drawn > 8).mean())
    assert covered > 0.5, (
        f"only {covered:.0%} of the scan's surface has anything on it in the first "
        "frame; a scan that fills in from blank reads as a fault"
    )
    page.close()


def test_the_scan_looks_the_same_everywhere_at_any_zoom(browser, a_served_scan):
    """No part of the scan may be sharp because it happened to be in the middle.

    Only so many pictures can be kept decoded at once. An earlier version gave
    them to the fields nearest the middle of the view until it ran out of room,
    which drew a disc of sharpness in the centre of the scan — a memory limit
    showing through onto the screen, which is not something an operator should
    ever be shown.

    So every field is decoded at the size it is drawn: far out, tiny and
    cheap for all alike; close in, full pictures for the few on screen. The
    halves checked here are that the close view gives every visible field
    its picture, and that nothing is thrown away and asked for again on the
    way.
    """
    root, url, note = a_served_scan
    _write_a_note_of(root, 2_500, note)
    a_field_is = note["tiles"][0]["w"]

    page, asked = _open(browser, url)
    kept = page.evaluate("() => window.__viewer.howManyPicturesAreKept()")
    switches_at = ((A_WINDOW["width"] * A_WINDOW["height"]) / (kept * 2 / 3)) ** 0.5

    # Far out, every field is fetched small, and none twice.
    # The middle of the scan, so the screen is full of fields and the count
    # below is a fair one.
    middle = page.evaluate("() => window.__viewer.getView().centre")
    page.evaluate("([centre, zoom]) => window.__viewer.setView({centre, zoom})",
                  [middle, a_field_is / (switches_at * 0.7)])
    # The opening view fetched at its own size before this phase began; the
    # ledger starts when the phase does, as it does below.
    del asked[:]
    page.wait_for_timeout(2500)
    assert len(asked) == len(set(asked)), (
        "a far-zoom picture was fetched more than once"
    )

    # Closer in, a field is drawn large, so it is decoded again at the larger
    # size — the far-zoom fetches above are a different question, and the
    # ledger starts afresh here.
    del asked[:]
    # Every field on screen gets a picture, and nothing is fetched twice.
    page.evaluate("([centre, zoom]) => window.__viewer.setView({centre, zoom})",
                  [middle, a_field_is / (switches_at * 1.3)])
    page.wait_for_timeout(5000)

    on_screen = page.evaluate(
        """(fieldUm) => {
          const where = window.__viewer.whereThingsAreDrawn();
          const side = fieldUm / where.zoom;
          return Math.round((where.width / side) * (where.height / side));
        }""",
        a_field_is,
    )
    assert len(set(asked)) >= on_screen * 0.9, (
        f"about {on_screen} fields are on screen but only {len(set(asked))} got a "
        "picture, so part of the scan is sharp and part of it is not"
    )
    assert len(asked) == len(set(asked)), (
        "a picture was fetched more than once, which means pictures are being "
        "thrown away and immediately asked for again"
    )
    assert len(set(asked)) <= kept, (
        f"{len(set(asked))} full pictures were asked for but only {kept} fit the budget"
    )
    page.close()


def test_fields_that_land_later_appear_without_the_view_moving(browser, a_served_scan):
    """A scan is looked at while it is still being taken.

    Nothing on disk announces itself, so the page says when it thinks something
    new has been written and the viewer reads the note again. What matters as
    much as the new fields appearing is that the view does not jump: an
    operator lining up a target should not be moved off it because the
    microscope finished another row.
    """
    root, url, note = a_served_scan
    _write_a_note_of(root, 400, note)

    page, _ = _open(browser, url)
    before = page.evaluate("() => window.__viewer.getView()")
    was_drawn = float(( _what_was_drawn(page) > 8).mean())

    _write_a_note_of(root, 1_600, note)
    page.evaluate("() => window.__viewer.tilesMayHaveLanded()")
    page.wait_for_timeout(1500)

    after = page.evaluate("() => window.__viewer.getView()")
    assert after["zoom"] == pytest.approx(before["zoom"])
    assert after["centre"]["x"] == pytest.approx(before["centre"]["x"])
    assert after["centre"]["y"] == pytest.approx(before["centre"]["y"])

    now_drawn = float((_what_was_drawn(page) > 8).mean())
    assert now_drawn > was_drawn + 0.05, (
        "the fields that landed did not appear; the note was re-read but nothing was drawn"
    )
    page.close()


def test_a_drawing_handed_to_the_bottom_slot_really_is_beneath_the_picture(browser, a_served_scan):
    """``drawsUnder`` is a promise, and this is the one that checks it.

    It matters because it is what makes swapping this engine for neuroglancer
    later a change of engine and nothing else: both put the scan at the bottom
    and take the operator's drawing above and below it. An engine that claimed
    to draw underneath and did not would put every carrier outline and every
    focus point in the wrong order the day it was swapped in.
    """
    root, url, note = a_served_scan
    _write_a_note_of(root, 9, note)

    page, _ = _open(browser, url)
    assert page.evaluate("() => window.__viewer.drawsUnder") is True

    # A block of white below the picture, and a block of white above it, in the
    # same place. If the bottom one is really underneath, the picture hides it.
    page.evaluate("""() => {
      const paint = (frame) => {
        frame.context.fillStyle = 'white';
        frame.context.fillRect(0, 0, frame.width, frame.height);
      };
      window.__viewer.drawUnder(paint);
    }""")
    page.wait_for_timeout(1200)
    underneath = _what_was_drawn(page)
    assert underneath.mean() < 200, (
        "the scan's own surface came out white, so the drawing meant for underneath "
        "landed on top of the picture"
    )
    page.close()


def test_dragging_the_picture_moves_it_by_exactly_what_the_hand_moved(browser, a_served_scan):
    """The gesture code is shared, so the viewer has to speak its language.

    Every engine here is panned and zoomed by one piece of code in
    `viz_studio/options/gestures.js`, which reads the view back through
    ``getView`` and hands a new one to ``setView``. That only works if a view
    means the same thing on both sides of the conversation, and this viewer
    once got it wrong: it kept a centre as a plain pair while everything else
    used a pair of named numbers, so its own numbers agreed with each other
    perfectly and dragging produced nothing at all.

    That is the shape of fault this checks for, and it is worth a test of its
    own because it is invisible from inside. Everything a test can *ask* the
    viewer answers correctly; only the dragging is broken.

    A drag of so many screen pixels should move the specimen by exactly that
    many pixels' worth, because what an operator expects when they take hold of
    a picture is that the point under their finger stays under their finger.
    """
    root, url, note = a_served_scan
    _write_a_note_of(root, 100, note)

    page, _ = _open(browser, url)
    before = page.evaluate("() => window.__viewer.getView()")

    box = page.locator("#box").bounding_box()
    middle = (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.move(*middle)
    page.mouse.down()
    page.mouse.move(middle[0] - 120, middle[1] - 80, steps=6)
    page.mouse.up()
    page.wait_for_timeout(300)

    after = page.evaluate("() => window.__viewer.getView()")
    assert after["zoom"] == pytest.approx(before["zoom"]), "a drag must not change the zoom"
    assert after["centre"]["x"] == pytest.approx(before["centre"]["x"] + 120 * before["zoom"], rel=0.02)
    assert after["centre"]["y"] == pytest.approx(before["centre"]["y"] + 80 * before["zoom"], rel=0.02)


def test_the_drawings_are_handed_the_frame_every_other_engine_hands_them(browser, a_served_scan):
    """One piece of drawing code has to work over every engine.

    The application draws the carrier, the positions and everything else once,
    and each engine calls that same drawing. So the thing an engine hands it is
    settled in `viz_studio/options/contract.md` and is not this engine's to
    choose: one object holding the view, the size of the box, a drawing context
    and a way of turning micrometres into screen pixels.

    Checked here rather than left to the day somebody swaps engines, because a
    drawing handed the wrong shape does not complain — it draws nothing, or
    draws in the corner, and looks like an engine that is broken.
    """
    root, url, note = a_served_scan
    _write_a_note_of(root, 9, note)

    page, _ = _open(browser, url)
    seen = page.evaluate("""() => new Promise((done) => {
      window.__viewer.drawOver((frame) => {
        const spot = frame.project(1000, 500);
        const back = frame.unproject(spot.x, spot.y);
        done({
          keys: Object.keys(frame).sort(),
          hasContext: typeof frame.context?.fillRect === "function",
          centreIsNamed: typeof frame.centre?.x === "number",
          projectIsNamed: typeof spot?.x === "number",
          roundTripX: back.x,
          roundTripY: back.y,
        });
      });
    })""")

    assert seen["hasContext"], "no drawing context was handed over"
    assert seen["centreIsNamed"], "the view's centre is not a pair of named numbers"
    assert seen["projectIsNamed"], "project did not answer with a pair of named numbers"
    for wanted in ("centre", "zoom", "width", "height", "density", "project", "unproject"):
        assert wanted in seen["keys"], f"the frame has no {wanted}"
    # Micrometres out and back again should land where they started.
    assert seen["roundTripX"] == pytest.approx(1000)
    assert seen["roundTripY"] == pytest.approx(500)


def test_a_picture_the_scan_had_not_written_yet_arrives_later(browser, a_served_scan):
    """A fetch can race the scan: the note names a field whose picture is
    still being encoded. Remembering that failure forever left a finished
    overview with grey holes nothing would fill; the signal that something
    landed forgets it, and the field is asked for again."""
    root, url, note = a_served_scan
    _write_a_note_of(root, 9, note)
    pictures = root / "scan"
    late = pictures / "F00004.jpg"
    held_back = late.read_bytes()
    late.unlink()

    page, asked = _open(browser, url)
    page.evaluate("([centre, zoom]) => window.__viewer.setView({centre, zoom})",
                  [{"x": note["tiles"][0]["w"] * 1.5, "y": note["tiles"][0]["h"] * 1.5},
                   note["tiles"][0]["w"] / 200])
    page.wait_for_timeout(1500)
    first = asked.count(f"{url}/scan/F00004.jpg")
    assert first >= 1, "the missing picture was never even asked for"

    late.write_bytes(held_back)
    page.evaluate("() => window.__viewer.tilesMayHaveLanded()")
    page.wait_for_timeout(1500)
    assert asked.count(f"{url}/scan/F00004.jpg") > first, (
        "the picture landed and was never asked for again"
    )
    page.close()
