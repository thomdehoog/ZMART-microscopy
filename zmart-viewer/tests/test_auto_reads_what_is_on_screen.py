"""Auto sets the window from the pixels an operator is actually looking at.

Pressing Auto used to measure a sample of the WHOLE picture, however far in
the operator had zoomed. On a plate that is the wrong question twice over: a
well is a hundredth of the picture, so a window set from the whole thing has
almost nothing to do with what is on screen, and most of a survey is ground
nobody imaged, so the black of it drags the black point down to nought and
leaves the specimen flat and dim.

So the measurement follows the view, and the ground that was never imaged is
left out of the vote. It stays the same 1st and 99th percentile of what
remains -- percentiles rather than the extremes, because one hot pixel would
otherwise set the top of the ramp and crush everything real beneath it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest
import zarr

VIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(VIZ / "app" / "server"))

from contrast import measure_here  # noqa: E402

# A picture in four quarters: dim tissue at the top left, bright tissue at the
# bottom right, and nothing imaged in the other two.
DIM, BRIGHT = 300, 6000


@pytest.fixture
def a_picture(tmp_path):
    store = tmp_path / "quarters_pos001.ome.zarr"
    store.mkdir()
    values = np.zeros((1, 64, 64), dtype=np.uint16)
    rng = np.random.default_rng(5)
    values[0, :32, :32] = rng.integers(DIM - 40, DIM + 40, (32, 32))
    values[0, 32:, 32:] = rng.integers(BRIGHT - 400, BRIGHT + 400, (32, 32))
    group = zarr.open_group(str(store), mode="w", zarr_format=2)
    group.create_array("0", shape=values.shape, chunks=(1, 64, 64),
                       dtype="uint16")[:] = values
    (store / ".zattrs").write_text(json.dumps({
        "multiscales": [{
            "version": "0.4",
            "axes": [{"name": "c", "type": "channel"},
                     {"name": "y", "type": "space", "unit": "micrometer"},
                     {"name": "x", "type": "space", "unit": "micrometer"}],
            "datasets": [{"path": "0", "coordinateTransformations": [
                {"type": "scale", "scale": [1.0, 0.35, 0.35]}]}],
        }],
    }), encoding="utf-8")
    return store


def test_the_window_follows_the_part_being_looked_at(a_picture):
    """Looking at the bright quarter gives a bright window, and the dim a dim one."""
    dim = measure_here(a_picture, channel=0, box=((0.0, 0.0), (0.5, 0.5)))
    bright = measure_here(a_picture, channel=0, box=((0.5, 0.5), (1.0, 1.0)))

    assert DIM - 60 < dim["window"][0] < DIM + 60, (
        f"the dim quarter was windowed at {dim['window']}, nowhere near its "
        f"own {DIM}"
    )
    assert BRIGHT - 600 < bright["window"][1] < BRIGHT + 600, (
        f"the bright quarter was windowed at {bright['window']}, nowhere near "
        f"its own {BRIGHT}"
    )
    assert bright["window"][0] > dim["window"][1], (
        "the two quarters were given overlapping windows, so the measurement "
        "is not following the view at all"
    )


def test_the_ground_nobody_imaged_gets_no_vote(a_picture):
    """Black that was never imaged must not drag the black point to nought.

    The whole picture is three-quarters unimaged here. Counted in, the 1st
    percentile is nought and the specimen is left sitting in the top of the
    ramp, flat and dim -- which is exactly what an operator sees today on a
    survey with gaps in it.
    """
    whole = measure_here(a_picture, channel=0, box=((0.0, 0.0), (1.0, 1.0)))
    assert whole["window"][0] > 100, (
        f"the black point landed at {whole['window'][0]}, so the unimaged "
        "ground was counted as though it were specimen"
    )


def test_a_view_with_nothing_in_it_says_so(a_picture):
    """A region holding no imaged pixels has no window to give.

    Panned onto empty ground, an operator pressing Auto must not be handed a
    window measured from nothing -- there is no answer, and inventing one
    would move their picture for no reason.
    """
    empty = measure_here(a_picture, channel=0, box=((0.0, 0.6), (0.4, 1.0)))
    assert empty is None, f"a window was invented from empty ground: {empty}"


def test_a_box_outside_the_picture_is_not_an_error(a_picture):
    """Panned off the edge, the ask is answered rather than raising.

    The view can sit anywhere, including entirely off the picture, and a
    button that throws when pressed at the wrong moment is worse than one
    that says it has nothing to offer.
    """
    assert measure_here(a_picture, channel=0, box=((2.0, 2.0), (3.0, 3.0))) is None
    # Half on, half off: what is on the picture still answers.
    edge = measure_here(a_picture, channel=0, box=((0.25, 0.25), (1.5, 1.5)))
    assert edge is not None and edge["window"][1] > DIM


# -- and the same thing through the panel, as an operator presses it ----------

import threading  # noqa: E402

from server import make_server  # noqa: E402


def test_auto_windows_the_well_being_looked_at(browser, built_dist, tmp_path):
    """Zoomed into the bright quarter, Auto sets a window for THAT quarter.

    The measurement an operator gets must describe what is in front of them.
    Pressed while looking at one bright corner of a mostly-dark picture, Auto
    used to answer with the whole picture's window -- which on a plate means
    the answer has almost nothing to do with the well on screen.
    """
    folder = tmp_path / "quarters"
    folder.mkdir()
    store = folder / "quarters_pos001.ome.zarr"
    store.mkdir()
    values = np.zeros((1, 64, 64), dtype=np.uint16)
    rng = np.random.default_rng(11)
    values[0, :32, :32] = rng.integers(DIM - 40, DIM + 40, (32, 32))
    values[0, 32:, 32:] = rng.integers(BRIGHT - 400, BRIGHT + 400, (32, 32))
    group = zarr.open_group(str(store), mode="w", zarr_format=2)
    group.create_array("0", shape=values.shape, chunks=(1, 64, 64),
                       dtype="uint16")[:] = values
    (store / ".zattrs").write_text(json.dumps({
        "multiscales": [{
            "version": "0.4",
            "axes": [{"name": "c", "type": "channel"},
                     {"name": "y", "type": "space", "unit": "micrometer"},
                     {"name": "x", "type": "space", "unit": "micrometer"}],
            "datasets": [{"path": "0", "coordinateTransformations": [
                {"type": "scale", "scale": [1.0, 0.35, 0.35]}]}],
        }],
    }), encoding="utf-8")

    server = make_server(port=0, data_dir=folder, site_dir=built_dist,
                         store="quarters_pos001.ome.zarr")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1000, "height": 800})
    try:
        page.goto(f"http://127.0.0.1:{server.server_address[1]}",
                  wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartConfig !== undefined",
                               timeout=30_000)
        page.wait_for_function(
            "() => window.zmartSourcesWaiting && window.zmartSourcesWaiting() === 0",
            timeout=60_000)
        page.wait_for_timeout(1_500)

        # Sit on the bright quarter: the middle of the bottom-right of the
        # picture, zoomed so little else is in view.
        page.evaluate("""() => {
          const v = window.zmartViewer;
          const space = v.coordinateSpace.value;
          const p = v.navigationState.position;
          const moved = Float32Array.from(p.value);
          const names = Array.from(space.names);
          for (const axis of ['y', 'x']) {
            const at = names.indexOf(axis);
            if (at < 0) continue;
            const low = space.bounds.lowerBounds[at];
            const high = space.bounds.upperBounds[at];
            moved[at] = low + (high - low) * 0.75;
          }
          p.value = moved;
          v.navigationState.zoomFactor.value /= 3;
        }""")
        page.wait_for_timeout(2_000)

        name = page.evaluate("() => window.zmartConfig.layers[0].name")
        page.locator(f"[aria-label='toggle {name}']").locator("xpath=../..").click()
        page.wait_for_timeout(300)
        page.locator(f"[aria-label='auto contrast {name}']").click()
        page.wait_for_timeout(1_500)

        window_ = page.evaluate("() => window.zmartLayerState[0].window")
        assert window_["high"] > BRIGHT * 0.7, (
            f"Auto answered {window_} while the bright quarter filled the "
            "screen, so it is still measuring the whole picture"
        )
        assert window_["low"] > 100, (
            f"Auto put the black point at {window_['low']}, so the unimaged "
            "ground is still being counted"
        )
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


# -- and it must read a copy of the picture that can still answer -----------

def _write_pyramid(store, levels, *, scale=0.325):
    """A store of pre-computed levels, coarsest last, as a run writes them."""
    group = zarr.open_group(str(store), mode="w", zarr_format=2)
    datasets = []
    for at, plane in enumerate(levels):
        group.create_array(str(at), shape=plane.shape, chunks=(1, 64, 64),
                           dtype="uint16")[:] = plane
        step = 2 ** at
        datasets.append({"path": str(at), "coordinateTransformations": [
            {"type": "scale", "scale": [1.0, scale * step, scale * step]}]})
    (store / ".zattrs").write_text(json.dumps({
        "multiscales": [{
            "version": "0.4",
            "axes": [{"name": "c", "type": "channel"},
                     {"name": "y", "type": "space", "unit": "micrometer"},
                     {"name": "x", "type": "space", "unit": "micrometer"}],
            "datasets": datasets,
        }],
    }), encoding="utf-8")


def _coarser(plane, by):
    """Block means, the way a pyramid is built."""
    _, height, width = plane.shape
    folded = plane.reshape(1, height // by, by, width // by, by)
    return folded.mean(axis=(2, 4)).astype(np.uint16)


def test_auto_reads_a_copy_that_can_still_answer(tmp_path):
    """Zoomed in far, the measurement must not come from a thumbnail.

    It used to read the coarsest copy of the picture that held any pixels,
    on the grounds that a button pressed by hand should read as little as
    possible. That is fine while the whole picture is on screen and wrong
    the moment an operator zooms: on a real plate the coarsest copy is
    241x414 for the entire tray, so a box around one nucleus covered ONE
    pixel of it. The 1st and 99th percentile of one number are the same
    number, the window came back with almost no width, and the picture went
    to two colours -- everything either black or saturated (seen on the
    HA-1a plate, 2026-08-20).

    So the copy is chosen by what the box covers on it: the coarsest one
    that still holds enough of the picture to be worth a percentile.
    """
    store = tmp_path / "speckle_pos001.ome.zarr"
    store.mkdir()
    rng = np.random.default_rng(4)
    fine = np.full((1, 512, 512), 20, dtype=np.uint16)
    rows, cols = np.mgrid[0:512, 0:512]
    inside = (rows - 256) ** 2 + (cols - 256) ** 2 < 150 ** 2
    # Speckle, as fluorescence is: the detail lives between 150 and 300 and
    # averages away to a flat ~225 the moment the picture is halved.
    fine[0][inside] = rng.integers(150, 300, inside.sum())
    _write_pyramid(store, [fine, _coarser(fine, 2), _coarser(fine, 4),
                           _coarser(fine, 8), _coarser(fine, 16)])

    middle = ((0.4375, 0.4375), (0.5625, 0.5625))
    found = measure_here(store, channel=0, box=middle)
    assert found is not None
    low, high = found["window"]

    patch = fine[0, 224:288, 224:288].astype(float)
    want_low, want_high = np.percentile(patch, [1.0, 99.0])
    spread = want_high - want_low
    assert high - low > 0.6 * spread, (
        f"Auto answered {low:.0f}-{high:.0f} for a patch that runs "
        f"{want_low:.0f}-{want_high:.0f}: it is reading a copy too coarse to "
        "hold the detail on screen"
    )
    assert abs(low - want_low) < 0.2 * spread and abs(high - want_high) < 0.2 * spread, (
        f"Auto answered {low:.0f}-{high:.0f}, the pixels on screen run "
        f"{want_low:.0f}-{want_high:.0f}"
    )


def test_the_whole_picture_is_still_measured_from_a_small_copy(tmp_path):
    """And the cheap read stays cheap when the whole picture is in view.

    Choosing by what the box covers must not turn every press at the
    overview into a read of the full-resolution picture: at that zoom the
    coarsest copy holds the whole thing and is exactly the right sample.
    """
    store = tmp_path / "speckle_pos001.ome.zarr"
    store.mkdir()
    rng = np.random.default_rng(5)
    fine = rng.integers(40, 900, (1, 512, 512)).astype(np.uint16)
    _write_pyramid(store, [fine, _coarser(fine, 2), _coarser(fine, 4),
                           _coarser(fine, 8), _coarser(fine, 16)])

    read = []
    original = zarr.open_group

    def watched(*args, **kwargs):
        group = original(*args, **kwargs)

        class Watching:
            def __getitem__(self, name):
                read.append(name)
                return group[name]

        return Watching()

    zarr.open_group = watched
    try:
        found = measure_here(store, channel=0, box=((0.0, 0.0), (1.0, 1.0)))
    finally:
        zarr.open_group = original
    assert found is not None
    assert read and read[0] in {"3", "4"}, (
        f"the whole picture was measured from level {read}, not from one of "
        "the small copies kept for exactly this"
    )
