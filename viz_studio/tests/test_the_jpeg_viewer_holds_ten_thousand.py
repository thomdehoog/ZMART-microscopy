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
            os.link(source, here)
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


def test_ten_thousand_fields_open_without_asking_for_a_single_picture(browser, a_served_scan):
    """The size this exists to survive, and the restraint that lets it.

    Zoomed out to the whole of ten thousand fields, each one is a handful of
    pixels wide. Fetching and decoding ten thousand pictures to paint that is
    work thrown away twice over — it is slow, and what it draws is
    indistinguishable from the one colour each field already carries. So none
    of them is fetched, and the scan appears at once.
    """
    root, url, note = a_served_scan
    _write_a_note_of(root, 10_000, note)

    page, asked = _open(browser, url)
    page.wait_for_timeout(1500)
    assert asked == [], (
        f"{len(asked)} pictures were fetched to draw fields a few pixels wide; "
        "at this zoom the colour each field already carries says the same thing"
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


def test_no_more_pictures_are_asked_for_than_can_be_kept(browser, a_served_scan):
    """Asking for more than can be held means asking for the same ones for ever.

    Decoded pictures cost far more memory than the JPEGs they came from, so
    only so many are kept. If a frame asks for more than that, every frame
    throws away pictures the next frame immediately asks for again: the scan
    flickers, the network never settles, and it gets worse the further out you
    zoom. So the fields nearest the middle of the view get their real picture
    and the rest keep their summary colour.

    The view here is set deliberately, not fitted, because this only goes wrong
    in one band: fields large enough on screen to deserve a real picture, and
    far more of them at once than can be kept. Twenty pixels a field puts well
    over a thousand of them on screen, which is comfortably inside it.
    """
    root, url, note = a_served_scan
    _write_a_note_of(root, 2_500, note)

    page, asked = _open(browser, url)
    a_field_is = note["tiles"][0]["w"]
    page.evaluate(
        """(zoom) => {
          const v = window.__viewer.getView();
          window.__viewer.setView({ centre: v.centre, zoom });
        }""",
        a_field_is / 20.0,
    )
    page.wait_for_timeout(4000)

    on_screen = page.evaluate(
        """(fieldUm) => {
          const where = window.__viewer.whereThingsAreDrawn();
          const sideInPixels = fieldUm / where.zoom;
          return Math.round((where.width / sideInPixels) * (where.height / sideInPixels));
        }""",
        a_field_is,
    )
    assert on_screen > 400, (
        f"only about {on_screen} fields are on screen, which is fewer than can be "
        "kept decoded — this test is not in the band where the mistake shows"
    )

    assert len(asked) == len(set(asked)), (
        "a picture was fetched more than once, which is the thrash this guards against"
    )
    assert len(asked) <= 400, (
        f"{len(asked)} pictures were asked for, more than the {400} that can be kept "
        "decoded — every frame would throw away pictures the next frame asks for again"
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
    assert after["centre"] == pytest.approx(before["centre"])

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
      const paint = (ctx, where) => {
        ctx.fillStyle = 'white';
        ctx.fillRect(0, 0, where.width, where.height);
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
