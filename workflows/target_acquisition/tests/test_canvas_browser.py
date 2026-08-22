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
             return [...frame.children].map((c) =>
               Boolean(c.style.mask || c.style.webkitMask));
           }"""
    )
    assert masked[0] is False, "the bottom layer was cut, so nothing shows through"
    assert all(masked[1:]), "the window did not reach every layer above the bottom"

    # The mask really is drawn, in sample units, where the field is.
    window_rect = page.evaluate(
        """() => {
             const r = document.querySelector("mask rect:nth-of-type(2)");
             return r ? [r.getAttribute("x"), r.getAttribute("y"),
                         r.getAttribute("width"), r.getAttribute("height")] : null;
           }"""
    )
    assert window_rect == ["0", "0", "100", "100"], window_rect
    assert errors == []


def test_a_layer_that_takes_no_clicks_lets_them_through(drawn):
    """A layer drawn to be read must not swallow clicks meant for one below."""
    page, _canvas_obj, _errors = drawn
    events = page.evaluate(
        """() => {
             const frame = [...document.querySelectorAll("#here div")]
               .find((d) => (d.style.transform || "").includes("translate("));
             return [...frame.children].map((c) => c.style.pointerEvents);
           }"""
    )
    # engine and carrier are for looking at; fields and focus are worked with.
    assert events == ["none", "none", "auto", "auto"]


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
