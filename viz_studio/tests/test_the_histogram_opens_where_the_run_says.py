"""The picture of a channel's brightness, the moment it is first shown.

Two things have to be right before an operator can use the histogram to set
contrast, and neither is about the numbers being correct -- both are about
where things sit on screen.

**The window has to be visible as a window.** The two blue marks are the
brightness the display ramp is spent on. If they sit hard against the ends of
the picture there is nothing to see beyond them, and no way to tell whether
the specimen is being clipped. So the stretch of brightness drawn is laid out
around the window the run itself asked for: the marks land at 15% and 85%
along the width, exactly, leaving a seventh of the picture beyond each of
them. The operator asked for exactly that (2026-08-22), and settled the awkward
case on 2026-08-23: the framing wins even when it takes the axis below zero
or past the declared range. An axis clamped at zero pinned the low mark to
the left edge for exactly the dim channels Auto is most used on, so a pair
of marks that always sits in the same two places is worth an empty stretch
of track no pixel can occupy.

**The bars have to be scaled to what is drawn.** The tallest bar sets the
height of every other one. Measured over bins the axis does not reach, a
background peak outside the picture flattens everything inside it to a line.

Nothing here presses Auto. A run that states its own window has said what it
wants shown, and the viewer believes it.
"""

from __future__ import annotations

import json
import threading

import numpy as np
import pytest
import zarr
from server import make_server

# Where the window's edges are meant to land along the histogram, and how far
# out they may be before this fails. The tolerance is a whole percent of the
# width -- the marks are placed by arithmetic, not by hand, so anything
# further out is a mistake rather than a rounding.
SITS_AT = (0.15, 0.85)
NEAR_ENOUGH = 0.01


def _a_channel_with_a_window(path, *, start, end, floor=200, ceiling=6000,
                             planes=4):
    """One channel whose run declares the window it wants shown.

    The pixels climb evenly from ``floor`` to ``ceiling`` so that the
    histogram has something in every bin -- a flat block of one value gives a
    single bar and says nothing about where anything sits.
    """
    path.mkdir(parents=True)
    group = zarr.open_group(str(path), mode="w", zarr_format=2)
    climbing = np.linspace(floor, ceiling, 64 * 64, dtype=np.float64)
    data = np.tile(climbing.reshape(1, 1, 64, 64), (1, planes, 1, 1)).astype("uint16")
    group.create_array("0", shape=data.shape, chunks=(1, 1, 64, 64),
                       dtype="uint16")[:] = data
    (path / ".zattrs").write_text(json.dumps({
        "multiscales": [{
            "version": "0.4",
            "axes": [{"name": "c", "type": "channel"},
                     {"name": "z", "type": "space", "unit": "micrometer"},
                     {"name": "y", "type": "space", "unit": "micrometer"},
                     {"name": "x", "type": "space", "unit": "micrometer"}],
            "datasets": [{"path": "0", "coordinateTransformations": [
                {"type": "scale", "scale": [1.0, 2.0, 0.35, 0.35]}]}],
        }],
        "omero": {"channels": [{
            "label": "ch0", "color": "00FF66",
            "window": {"min": 0, "max": 65535, "start": start, "end": end},
        }]},
    }), encoding="utf-8")
    return path


@pytest.fixture
def opened_on(browser, built_dist, tmp_path):
    """Open the viewer on one store and hand back the page it drew."""
    servers = []

    def open_it(name, *, start, end):
        data = tmp_path / name
        data.mkdir()
        _a_channel_with_a_window(data / f"{name}_pos001.ome.zarr", start=start, end=end)
        server = make_server(port=0, data_dir=data, site_dir=built_dist,
                             store=f"{name}_pos001.ome.zarr")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append((server, thread))
        page = browser.new_page(viewport={"width": 1300, "height": 1000})
        page.goto(f"http://127.0.0.1:{server.server_address[1]}",
                  wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartConfig !== undefined", timeout=30_000)
        page.wait_for_selector("[aria-label^='histogram']", timeout=30_000)
        page.wait_for_timeout(1500)
        return page

    yield open_it
    for server, thread in servers:
        server.shutdown()
        thread.join(timeout=5)


def _the_picture(page):
    """Where the marks sit and how tall the bars are, read off the drawing."""
    return page.evaluate("""() => {
      const svg = document.querySelector("[aria-label^='histogram']");
      const across = svg.viewBox.baseVal.width;
      const bars = [...svg.querySelectorAll("rect")];
      const marks = bars.filter((one) => one.getAttribute("fill") === "var(--accent)")
        .map((one) => Number(one.getAttribute("x")) / across).sort((a, b) => a - b);
      const counts = bars.filter((one) => one.getAttribute("fill") === "currentColor")
        .map((one) => Number(one.getAttribute("height")));
      return {marks, tallest: Math.max(...counts, 0), bars: counts.length};
    }""")


def test_the_window_a_run_declared_sits_across_the_middle(opened_on, tmp_path):
    """A window well clear of zero puts its marks at 15% and 85%."""
    page = opened_on("bright", start=2000, end=4000)
    page.screenshot(path=str(tmp_path / "a_window_across_the_middle.png"))
    seen = _the_picture(page)
    assert len(seen["marks"]) == 2, (
        f"the window should be drawn as two marks; saw {seen['marks']}"
    )
    for mark, meant in zip(seen["marks"], SITS_AT):
        assert abs(mark - meant) < NEAR_ENOUGH, (
            f"the window's marks are at {[round(one, 3) for one in seen['marks']]} "
            f"along the histogram, not at {SITS_AT}. An operator cannot see what "
            "is being clipped without room beyond the marks"
        )


def test_the_axis_goes_below_zero_to_keep_the_framing(opened_on, tmp_path):
    """A window that opens at zero still puts its marks at 15% and 85%.

    Fifteen per cent of the width below the window is brightness no pixel
    can have, and for a day the axis was clamped there -- which pinned the
    low mark against the left edge for exactly the dim channels Auto is
    most used on. The operator asked for the exact framing instead
    (2026-08-23): the marks always sit in the same two places, whatever
    the window's numbers, and the empty stretch below zero is the price,
    knowingly paid. This gate used to pin the clamp, and now pins its
    absence just as firmly.
    """
    page = opened_on("fromzero", start=0, end=4000)
    page.screenshot(path=str(tmp_path / "a_window_that_opens_at_zero.png"))
    seen = _the_picture(page)
    assert len(seen["marks"]) == 2, (
        f"the window should be drawn as two marks; saw {seen['marks']}"
    )
    for mark, meant in zip(seen["marks"], SITS_AT):
        assert abs(mark - meant) < NEAR_ENOUGH, (
            f"the window's marks are at {[round(one, 3) for one in seen['marks']]} "
            f"along the histogram, not at {SITS_AT}: the framing must hold even "
            "when it takes the axis below zero"
        )


def test_the_bars_are_scaled_to_the_part_of_the_picture_drawn(opened_on, tmp_path):
    """Something reaches the top of the histogram, whatever the axis shows.

    The bars are drawn as a share of the tallest one. Take that tallest from
    a bin the axis never reaches and every bar inside the picture is squashed
    towards nothing -- which is what an operator reports as "the histogram is
    empty" (2026-08-22).
    """
    page = opened_on("scaled", start=2000, end=4000)
    page.screenshot(path=str(tmp_path / "bars_scaled_to_what_is_drawn.png"))
    seen = _the_picture(page)
    assert seen["bars"] > 4, f"only {seen['bars']} bars were drawn at all"
    assert seen["tallest"] > 18, (
        f"the tallest bar drawn reaches {seen['tallest']} of the 22 the "
        "histogram has room for, so the picture is squashed against its floor"
    )
