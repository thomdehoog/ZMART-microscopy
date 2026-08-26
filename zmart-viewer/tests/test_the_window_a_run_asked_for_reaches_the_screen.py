"""A run's own brightness window has to reach the screen.

A microscopist choosing a brightness range at the instrument expects to see their
acquisition looking that way when they open it. OME-Zarr carries the choice in the
``omero`` block of the store's description, as ``start`` and ``end``.

Two of the four numbers in that block are a trap and are the reason this file
exists. Beside ``start`` and ``end`` sit ``min`` and ``max``, which are the
*camera's whole range* — nought to sixty-five thousand for a sixteen-bit camera. A
real specimen occupies a narrow band inside that, so a picture opened on ``min``
and ``max`` comes out very nearly black and stays that way until somebody thinks
to drag a slider.

**For a pointed-at picture there is no way to recover from getting this wrong.**
The viewer's usual answer, where a run says nothing, is to read the pixels and
work a window out from them. A picture assembled by pointing at positions holds no
pixels of its own — every piece of it is answered by handing over a position's
file — so reading it finds only the empty value, and the window comes out covering
the whole range of the data type. That was measured before this was fixed: the
specimen reached the screen at fourteen out of two hundred and fifty-five, and the
frame-rate table it was measured with reported a perfectly healthy thirty-five
frames a second over a black screen.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from pixels import fraction_lit
from stores import channels

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from zmart_storage.canvas import Channel  # noqa: E402
from zmart_storage.positions import start_a_run  # noqa: E402

TILE = (1, 256, 256)
PIECE = 128

# The band the specimen really occupies, and what the run asks to be shown. Well
# inside the camera's range on purpose, since that gap is the whole subject here.
ASKED_FOR = (400, 3800)
CAMERA_RANGE = (0, 65535)


def _a_run(folder: Path, positions: int = 4) -> Path:
    """A small run whose specimen sits in a narrow band of a wide camera range."""
    across = 2
    with start_a_run(
        folder, name="experiment",
        room=(TILE[0], across * TILE[1], across * TILE[2]),
        tile_shape=TILE, voxel_size_um=(2.0, 0.325, 0.325),
        channels=[Channel("488", window=ASKED_FOR)], piece=PIECE,
    ) as run:
        for index in range(positions):
            rng = np.random.default_rng(index)
            picture = (2500 + rng.normal(0, 300, TILE)).clip(0, 4000).astype("uint16")
            run.write(picture,
                      at=(0, (index // across) * TILE[1], (index % across) * TILE[2]))
        return run.path


def test_the_store_reports_the_window_the_run_asked_for(tmp_path):
    """Read from the description, and from the right two of the four numbers."""
    picture = _a_run(tmp_path / "experiment")
    described = channels(picture)

    assert len(described) == 1
    window = described[0].get("window")
    assert window is not None, (
        "the store says which brightness it should be shown between and the viewer "
        "did not read it, so the picture will open on the camera's whole range"
    )
    assert (window["low"], window["high"]) == ASKED_FOR, (
        f"the window came back as {window}, which is not what the run asked for. "
        "If it is the camera's whole range, min and max are being read where start "
        "and end were meant"
    )
    assert (window["low"], window["high"]) != CAMERA_RANGE


def test_a_picture_that_holds_no_pixels_still_opens_bright(
        browser, built_dist, tmp_path):
    """The end of it: open the picture and look at the screen.

    This is the check that would have caught the fault, and none of the ones above
    it would have. The frame rate was healthy, every request was answered, every
    byte served matched the position it came from — and the screen was black,
    because the brightness window was worked out by reading a picture that
    deliberately holds nothing.
    """
    import threading

    from measure_the_frame_rate_of_a_linked_view import EVERY_SOURCE_RESOLVED
    from server import make_server

    folder = tmp_path / "experiment"
    picture = _a_run(folder)

    server = make_server(port=0, data_dir=folder, site_dir=built_dist,
                         store=picture.name, live=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 900, "height": 700})
    try:
        page.goto(f"http://127.0.0.1:{server.server_address[1]}",
                  wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartViewer !== undefined", timeout=60_000)
        page.wait_for_function("() => window.zmartSourcesWaiting() === 0",
                               timeout=120_000)
        page.wait_for_function(EVERY_SOURCE_RESOLVED, timeout=300_000)
        page.wait_for_timeout(4000)

        lit = fraction_lit(page)
        assert lit > 0.3, (
            f"only {lit:.3f} of the picture reached the screen. The specimen is "
            "there and every piece of it is being served — it is being drawn at a "
            "few per cent of its brightness because the window covers the camera's "
            "whole range instead of the band the run asked for"
        )

        # And the window the engine was actually given, so a future failure says
        # which of the two numbers went wrong rather than only that it looks dark.
        given = page.evaluate("""() => {
          const layers = window.zmartViewer.state.toJSON().layers || [];
          const image = layers.find((one) => one.type === "image");
          return image && image.shaderControls
            && image.shaderControls.normalized
            && image.shaderControls.normalized.range;
        }""")
        assert given == list(ASKED_FOR), (
            f"the engine was given the range {given} rather than {list(ASKED_FOR)}"
        )
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)
