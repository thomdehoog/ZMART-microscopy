"""The canvas, drawn by a real browser.

The other canvas tests check what Python believes. These check what is
actually on the screen — that the layers draw, that they move as one when the
view is dragged, that a switched-off layer is really gone, and that a window
opens through the stack rather than through one layer. None of that can be
proved from Python: it is the browser that composes the layers.

This is also where the arrangement for a future image engine is put to the
test. Everything is drawn from one shared view, so an engine plugged in
underneath can be handed the same numbers instead of being moved along with
the rest. If a layer ever started keeping its own position, these tests are
where it would show.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import pytest  # noqa: E402

pytest.importorskip("anywidget")
playwright_api = pytest.importorskip("playwright.sync_api")

from _widget_browser import widget_in_a_browser  # noqa: E402
from workflow import react as wreact  # noqa: E402


def _launch(pw):
    try:
        return pw.chromium.launch()
    except Exception as first_error:  # pragma: no cover - environment-specific
        import os
        from pathlib import Path

        chromium = os.environ.get("ZMART_CHROMIUM", "/opt/pw-browsers/chromium")
        if Path(chromium).exists():
            try:
                return pw.chromium.launch(executable_path=chromium)
            except Exception:
                pass
        pytest.skip(f"no Chromium available for Playwright: {first_error}")


def _canvas():
    """A canvas shaped like the real one: a base, a carrier, fields, points."""
    canvas = wreact.canvas(
        [
            {"kind": "engine", "id": "engine", "label": "image engine"},
            {
                "kind": "shapes",
                "id": "carrier",
                "label": "carrier",
                "shapes": [{"bounds": [0, 0, 300, 200], "stroke": "#8888ff"}],
            },
            {
                "kind": "shapes",
                "id": "fields",
                "label": "scan fields",
                "interactive": True,
                "shapes": [
                    {"bounds": [0, 0, 100, 100], "fill": "rgba(255,0,0,0.4)"},
                    {"bounds": [100, 0, 100, 100], "fill": "rgba(0,255,0,0.4)"},
                ],
            },
            {
                "kind": "points",
                "id": "focus",
                "label": "focus points",
                "dimmable": False,
                "interactive": True,
                "points": [{"x": 50.0, "y": 50.0}, {"x": 150.0, "y": 50.0}],
            },
        ]
    )
    canvas.look_at(150.0, 100.0, scale=1.5)
    return canvas


@pytest.fixture()
def drawn():
    """A mounted canvas in a real browser, ready to be looked at and dragged."""
    canvas = _canvas()
    with widget_in_a_browser(canvas) as base, playwright_api.sync_playwright() as pw:
        browser = _launch(pw)
        page = browser.new_page(viewport={"width": 1400, "height": 1100})
        errors: list[str] = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.goto(base, wait_until="domcontentloaded")
        page.wait_for_function("window.__mounted === true", timeout=30_000)
        page.wait_for_timeout(200)
        try:
            yield page, canvas, errors
        finally:
            browser.close()


# The one moving frame every layer sits in.
_FRAME = "#here div[style*='translate(']"


def test_the_canvas_draws_without_complaint(drawn):
    """It mounts, and the browser reports nothing wrong."""
    page, _canvas_obj, errors = drawn
    assert errors == [], f"the canvas threw in the browser: {errors}"
    assert page.locator(_FRAME).count() >= 1
    playwright_api.expect(page.locator("#here")).to_contain_text("layers")


def test_every_layer_sits_in_the_one_moving_frame(drawn):
    """There is a single frame carrying the view; no layer is outside it.

    This is the arrangement that lets an image engine be plugged in later. If
    a layer positioned itself instead of sitting in the shared frame, it could
    drift away from the others, and there would be nothing coherent to hand an
    engine that keeps its own camera.
    """
    page, _canvas_obj, _errors = drawn
    frames = page.evaluate(
        """() => [...document.querySelectorAll("#here div")]
             .filter((d) => (d.style.transform || "").includes("translate("))
             .length"""
    )
    assert frames == 1, f"expected one moving frame, found {frames}"

    # Every drawn layer is a child of it, and each is placed in sample units.
    layer_count = page.evaluate(
        """() => {
             const frame = [...document.querySelectorAll("#here div")]
               .find((d) => (d.style.transform || "").includes("translate("));
             return frame.children.length;
           }"""
    )
    assert layer_count == 4, f"expected four layers in the frame, found {layer_count}"


def test_dragging_moves_every_layer_together(drawn):
    """One drag moves the whole picture, and nothing shifts relative to it.

    The layers keep their own positions on the sample and are carried by the
    frame, so after a drag each is in the same place on the sample as before
    while all of them have moved the same distance on screen.
    """
    page, _canvas_obj, errors = drawn
    box = page.locator(_FRAME).first.bounding_box()
    assert box is not None

    def positions():
        # Only what is drawn ON the sample. The readouts at the bottom of the
        # frame sit in screen space and are meant to stay put while the view
        # moves under them, so they would wrongly look like a layer left behind.
        return page.evaluate(
            """() => {
                 const frame = [...document.querySelectorAll("#here div")]
                   .find((d) => (d.style.transform || "").includes("translate("));
                 const out = {};
                 for (const el of frame.querySelectorAll("[style*='left']")) {
                   const key = el.getAttribute("data-point") ?? el.style.left + ":" + el.style.top;
                   const r = el.getBoundingClientRect();
                   out[key] = [Math.round(r.left), Math.round(r.top)];
                 }
                 return out;
               }"""
        )

    before = positions()
    assert before, "nothing was drawn to move"

    page.mouse.move(box["x"] + 200, box["y"] + 200)
    page.mouse.down()
    page.mouse.move(box["x"] + 260, box["y"] + 240, steps=6)
    page.mouse.up()
    page.wait_for_timeout(120)

    after = positions()
    shared = [k for k in before if k in after]
    assert len(shared) >= 3, "too little on screen to tell whether it moved together"

    shifts = {tuple(a - b for a, b in zip(after[k], before[k], strict=True)) for k in shared}
    assert len(shifts) == 1, f"the layers moved by different amounts: {sorted(shifts)}"
    moved = next(iter(shifts))
    assert moved != (0, 0), "dragging moved nothing at all"
    assert errors == []


def test_zooming_keeps_the_layers_together_too(drawn):
    """Scrolling changes the shared view, not any single layer."""
    page, _canvas_obj, _errors = drawn
    box = page.locator(_FRAME).first.bounding_box()

    def frame_transform():
        return page.evaluate(
            """() => [...document.querySelectorAll("#here div")]
                 .find((d) => (d.style.transform || "").includes("translate(")).style.transform"""
        )

    before = frame_transform()
    page.mouse.move(box["x"] + 200, box["y"] + 200)
    page.mouse.wheel(0, -240)
    page.wait_for_timeout(150)
    after = frame_transform()

    assert after != before, "scrolling did not change the view"
    assert "scale(" in after
    # Still exactly one frame — zooming must not have made a layer position
    # itself separately.
    frames = page.evaluate(
        """() => [...document.querySelectorAll("#here div")]
             .filter((d) => (d.style.transform || "").includes("translate(")).length"""
    )
    assert frames == 1


def test_switching_a_layer_off_takes_it_off_the_screen(drawn):
    """Off means gone, not merely invisible.

    An unseen layer that was still drawn would cost the browser the same work
    and would still swallow clicks meant for whatever is underneath it.
    """
    page, canvas, _errors = drawn

    def layers_drawn():
        return page.evaluate(
            """() => {
                 const frame = [...document.querySelectorAll("#here div")]
                   .find((d) => (d.style.transform || "").includes("translate("));
                 return frame.children.length;
               }"""
        )

    assert layers_drawn() == 4
    hidden = [
        {**layer, "visible": False} if layer["id"] == "fields" else layer
        for layer in canvas.layers
    ]
    page.evaluate("layers => window.__setTrait('layers', layers)", hidden)
    page.wait_for_timeout(120)
    assert layers_drawn() == 3, "a switched-off layer was still drawn"


def test_a_window_cuts_through_the_stack_but_never_the_bottom_layer(drawn):
    """Opening a window has to reach the imagery, or it reveals nothing useful.

    A hole in one layer would show the next layer down. So the window is cut
    through everything above the bottom layer at once — and never through the
    bottom layer, which is the thing it exists to reveal.
    """
    page, canvas, errors = drawn
    canvas.see_through_fields("fields", [0], opacity=0.0)
    page.evaluate("m => window.__setTrait('opacity_map', m)", canvas.opacity_map)
    page.wait_for_timeout(150)

    masked = page.evaluate(
        """() => {
             const frame = [...document.querySelectorAll("#here div")]
               .find((d) => (d.style.transform || "").includes("translate("));
             return [...frame.children].map((c) => Boolean(c.style.mask));
           }"""
    )
    assert masked[0] is False, "the bottom layer was cut, so nothing shows through"
    assert all(masked[1:]), "the window did not reach every layer above the bottom"

    # The mask really is drawn, in sample units, where the field is.
    # The window is drawn where the scan field really is. A mask is measured
    # from the corner of what it masks, so the field's place on the sample is
    # shifted by the canvas's own corner — and the size is untouched.
    window_rect = page.evaluate(
        """() => {
             const r = document.querySelector("mask rect:nth-of-type(2)");
             return r ? [r.getAttribute("x"), r.getAttribute("y"),
                         r.getAttribute("width"), r.getAttribute("height")]
                         .map(Number) : null;
           }"""
    )
    extent = canvas.extent
    field = canvas.layers[2]["shapes"][0]["bounds"]
    assert window_rect == pytest.approx(
        [field[0] - extent[0], field[1] - extent[1], field[2], field[3]]
    ), window_rect
    assert errors == []


def test_a_layer_that_takes_no_clicks_lets_them_through(drawn):
    """Only what a layer draws can be clicked, and only if it takes clicks.

    A layer's own container covers the whole sample. If that took clicks, an
    interactive layer would swallow every click meant for the layers beneath
    it — anywhere it happened to have drawn nothing, which is most of it.
    """
    page, _canvas_obj, _errors = drawn
    containers = page.evaluate(
        """() => {
             const frame = [...document.querySelectorAll("#here div")]
               .find((d) => (d.style.transform || "").includes("translate("));
             return [...frame.children].map((c) => c.style.pointerEvents);
           }"""
    )
    assert containers == ["none", "none", "none", "none"], (
        "a layer's container takes clicks, so it blocks the layers below it"
    )

    # The scan fields are worked with, so what they draw does take clicks;
    # the carrier is only there to be read, so what it draws does not.
    drawn_things = page.evaluate(
        """() => {
             const out = {};
             for (const el of document.querySelectorAll("[data-layer]")) {
               out[el.getAttribute("data-layer")] = el.style.pointerEvents;
             }
             return out;
           }"""
    )
    assert drawn_things["fields"] == "auto"
    assert drawn_things["carrier"] == "none"


def test_the_shared_dial_fades_only_what_follows_it(drawn):
    """Turning the dial down must not fade what the operator is placing."""
    page, canvas, _errors = drawn

    def solidity():
        return page.evaluate(
            """() => {
                 const frame = [...document.querySelectorAll("#here div")]
                   .find((d) => (d.style.transform || "").includes("translate("));
                 return [...frame.children].map((c) => Number(c.style.opacity || 1));
               }"""
        )

    assert solidity() == [1, 1, 1, 1]
    page.evaluate("() => window.__setTrait('dim', 0.25)")
    page.wait_for_timeout(120)

    faded = solidity()
    ids = [layer["id"] for layer in canvas.layers]
    by_id = dict(zip(ids, faded, strict=True))
    assert by_id["carrier"] == pytest.approx(0.25), "the carrier ignored the dial"
    assert by_id["fields"] == pytest.approx(0.25), "the scan fields ignored the dial"
    assert by_id["engine"] == pytest.approx(1.0), "the imagery was faded by its own dial"
    assert by_id["focus"] == pytest.approx(1.0), (
        "focus points faded, so dimming to see the sample would hide what you are placing"
    )


def test_opening_a_window_really_shows_the_imagery(tmp_path):
    """The proof that matters: the pixels change, and only where they should.

    Everything else about the window can look right while nothing happens on
    screen — the style can be set, the mask can be in the page, and the layer
    can still be drawn exactly as before. So this looks at the picture itself.
    A window is opened over one field and not its neighbour, and the colours
    are read back from both.
    """
    import numpy as np
    from PIL import Image
    from workflow.react._support import jpeg_data_url

    # A plainly red picture, so "the sample showed through" is unmistakable
    # against the blue cover over it.
    red = np.zeros((8, 8, 3), dtype=np.float32)
    red[..., 0] = 1.0
    imagery = jpeg_data_url(red)
    canvas = wreact.canvas(
        [
            {
                "kind": "images",
                "id": "imagery",
                "label": "imagery",
                "images": [
                    {"x0": 0, "y0": 0, "w": 100, "h": 100, "src": imagery},
                    {"x0": 100, "y0": 0, "w": 100, "h": 100, "src": imagery},
                ],
            },
            {
                "kind": "shapes",
                "id": "cover",
                "label": "cover",
                "shapes": [{"bounds": [0, 0, 200, 100], "fill": "rgb(0,0,255)"}],
            },
        ]
    )
    canvas.look_at(100.0, 50.0, scale=2.0)

    with widget_in_a_browser(canvas) as base, playwright_api.sync_playwright() as pw:
        browser = _launch(pw)
        page = browser.new_page(viewport={"width": 1200, "height": 900})
        page.goto(base, wait_until="domcontentloaded")
        page.wait_for_function("window.__mounted === true", timeout=30_000)
        page.wait_for_timeout(300)

        # Where each field actually is on screen. Taking fractions of the
        # moving frame would be wrong: that frame spans the whole piece of
        # sample the canvas covers, most of which is outside the visible part.
        centres = page.evaluate(
            """() => [...document.querySelectorAll("#here img")].map((im) => {
                 const r = im.getBoundingClientRect();
                 return [Math.round(r.left + r.width / 2), Math.round(r.top + r.height / 2)];
               })"""
        )
        assert len(centres) == 2, f"expected two fields on screen, found {len(centres)}"
        (left_at, right_at) = sorted(centres)

        def colours():
            shot = tmp_path / "canvas.png"
            page.screenshot(path=str(shot))
            with Image.open(shot) as picture:
                pixels = picture.convert("RGB")
                return pixels.getpixel(tuple(left_at)), pixels.getpixel(tuple(right_at))

        covered_left, covered_right = colours()
        assert covered_left[2] > covered_left[0], "the cover should be blue over both fields"
        assert covered_right[2] > covered_right[0]

        # Open a window over the left-hand field only.
        canvas.see_through([{"shape": "rect", "bounds": [0, 0, 100, 100], "opacity": 0.0}])
        page.evaluate("m => window.__setTrait('opacity_map', m)", canvas.opacity_map)
        page.wait_for_timeout(300)
        opened_left, opened_right = colours()

        assert opened_left != covered_left, (
            "the window changed nothing on screen — the imagery never showed through"
        )
        assert opened_left[0] > opened_left[2], (
            f"the sample should show through the window, got {opened_left}"
        )
        assert opened_right == covered_right, (
            f"the window reached a field it was not opened over, got {opened_right}"
        )
        browser.close()


@pytest.fixture()
def workable():
    """A canvas the operator can work on: scan fields and focus points."""
    canvas = wreact.canvas(
        [
            {
                "kind": "shapes",
                "id": "fields",
                "label": "scan fields",
                "interactive": True,
                "shapes": [
                    {"bounds": [0, 0, 100, 100], "stroke": "#38bdf8"},
                    {"bounds": [120, 0, 100, 100], "stroke": "#38bdf8"},
                ],
            },
            {
                "kind": "points",
                "id": "focus",
                "label": "focus points",
                "dimmable": False,
                "interactive": True,
                "points": [{"x": 60.0, "y": 170.0}],
            },
        ]
    )
    with widget_in_a_browser(canvas) as base, playwright_api.sync_playwright() as pw:
        browser = _launch(pw)
        page = browser.new_page(viewport={"width": 1500, "height": 1200})
        errors: list[str] = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.goto(base, wait_until="domcontentloaded")
        page.wait_for_function("window.__mounted === true", timeout=30_000)
        page.wait_for_timeout(200)
        try:
            yield page, canvas, errors
        finally:
            browser.close()


def _sent(page):
    return page.evaluate("() => window.__sent")


def _centre(page, selector):
    box = page.locator(selector).first.bounding_box()
    assert box is not None, f"{selector} is not on screen"
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def test_the_pointer_does_one_thing_at_a_time(workable):
    """Which tool is chosen decides what a click means, so none is guessed at."""
    page, canvas, _errors = workable
    page.get_by_title("drag to move the view").click()
    assert _sent(page)[-1] == {"type": "tool", "value": "pan"}

    page.get_by_title("click to add a focus point, click one to take it away").click()
    assert _sent(page)[-1] == {"type": "tool", "value": "focus"}


def test_clicking_a_scan_field_picks_it_out(workable):
    """Choosing a field is how a panel on the right knows what to talk about."""
    page, canvas, errors = workable
    page.evaluate("() => window.__setTrait('tool', 'move')")
    page.wait_for_timeout(80)

    x, y = _centre(page, "[data-shape='1']")
    page.mouse.click(x, y)
    page.wait_for_timeout(120)

    assert _sent(page)[-1] == {"type": "pick", "layer": "fields", "index": 1}
    canvas.pick("fields", 1)
    page.evaluate("s => window.__setTrait('selection', s)", canvas.selection)
    page.wait_for_timeout(120)
    outline = page.evaluate(
        "() => document.querySelector(\"[data-shape='1']\").style.border"
    )
    assert "#ffffff" in outline.replace("rgb(255, 255, 255)", "#ffffff"), outline
    assert errors == []


def test_dragging_a_scan_field_moves_it_and_a_click_does_not(workable):
    """A hand never holds quite still, so a click must not nudge the field.

    Anything shorter than a few pixels is a click; further than that is a
    move, reported as the distance across the sample rather than across the
    screen, because that is what it means on the microscope.
    """
    page, canvas, errors = workable
    page.evaluate("() => window.__setTrait('tool', 'move')")
    page.wait_for_timeout(80)

    # A click with the tiniest wobble must still read as a click.
    x, y = _centre(page, "[data-shape='0']")
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 2, y + 1, steps=2)
    page.mouse.up()
    page.wait_for_timeout(120)
    assert _sent(page)[-1]["type"] == "pick", "a small wobble moved the field"

    # A real drag moves it, by a distance measured on the sample.
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 60, y + 30, steps=8)
    page.mouse.up()
    page.wait_for_timeout(150)
    moved = _sent(page)[-1]
    assert moved["type"] == "move" and moved["layer"] == "fields" and moved["index"] == 0
    scale = page.evaluate(
        """() => {
             const frame = [...document.querySelectorAll("#here div")]
               .find((d) => (d.style.transform || "").includes("translate("));
             return Number(frame.style.transform.match(/scale\\(([-0-9.]+)\\)/)[1]);
           }"""
    )
    assert moved["dx"] == pytest.approx(60 / scale, abs=1.0), moved
    assert moved["dy"] == pytest.approx(30 / scale, abs=1.0), moved

    canvas.move_item("fields", 0, moved["dx"], moved["dy"])
    assert canvas.layers[0]["shapes"][0]["bounds"][0] == pytest.approx(60 / scale, abs=1.0)
    assert errors == []


def test_placing_and_taking_away_a_focus_point(workable):
    """Click bare sample to add one; click one to take it away again.

    The same two gestures the focus map has always used, so an operator who
    knows one knows the other.
    """
    page, canvas, errors = workable
    page.evaluate("() => window.__setTrait('tool', 'focus')")
    page.wait_for_timeout(80)

    # Somewhere on the picture with nothing drawn on it — found rather than
    # guessed, so the click really lands on bare sample.
    empty = page.evaluate(
        """() => {
             const frame = [...document.querySelectorAll("#here div")]
               .find((d) => (d.style.transform || "").includes("translate("));
             const view = frame.parentElement.getBoundingClientRect();
             for (let y = view.top + 12; y < view.bottom - 12; y += 9) {
               for (let x = view.left + 12; x < view.right - 12; x += 9) {
                 const el = document.elementFromPoint(x, y);
                 if (el && !el.closest("[data-shape], [data-point]")) return [x, y];
               }
             }
             return null;
           }"""
    )
    assert empty, "the whole picture is covered — nowhere to place a point"
    page.mouse.click(empty[0], empty[1])
    page.wait_for_timeout(120)
    placed = _sent(page)[-1]
    assert placed["type"] == "place", placed
    before = len(canvas.layers[1]["points"])
    canvas.place_point("focus", placed["x"], placed["y"])
    assert len(canvas.layers[1]["points"]) == before + 1

    # Clicking an existing point takes it away.
    x, y = _centre(page, "[data-point='0']")
    page.mouse.click(x, y)
    page.wait_for_timeout(120)
    assert _sent(page)[-1] == {"type": "remove", "layer": "focus", "index": 0}
    canvas.remove_point("focus", 0)
    assert len(canvas.layers[1]["points"]) == before
    assert errors == []


def test_moving_the_view_never_disturbs_what_is_on_it(workable):
    """With the view tool chosen, dragging pans and touches nothing else."""
    page, canvas, errors = workable
    page.evaluate("() => window.__setTrait('tool', 'pan')")
    page.wait_for_timeout(80)

    x, y = _centre(page, "[data-shape='0']")
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 50, y + 20, steps=6)
    page.mouse.up()
    page.wait_for_timeout(150)

    kinds = [m["type"] for m in _sent(page)]
    assert "move" not in kinds and "pick" not in kinds, (
        f"panning disturbed the scan fields: {kinds}"
    )
    assert errors == []
