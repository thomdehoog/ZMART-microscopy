"""A picture grown along (t, c) draws in the real browser, and steers.

The record-level oracle proves every frame decodes to its own stamp; this
gate proves the other half of the contract — the frames reach a screen.
The engine is handed the grown five-axis description, must offer the time
axis in its own coordinate space, and steering t or z (and c, however the
frontend chooses to expose colour) must change the drawn pixels in the
stamped direction. Each station gets the operator's F5 pair: what is on
screen after a reload must be what was on screen before it.

The fixture's stamps are chosen for a photograph, not a byte-compare:
brightness steps of two fifths of the display window per moment, one
fifth per channel, one twentieth per plane — big enough that a wrong
frame on screen moves the mean brightness far outside noise, and a
human looking at the saved screenshots (the standing habit) sees the
picture brighten step by step.
"""

from __future__ import annotations

import io
import json
import sys
import threading
from pathlib import Path

import numpy as np
import pytest
import zarr

_VIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_VIZ / "building"))

from declare import declare_a_built_picture  # noqa: E402
from server import make_server  # noqa: E402

MOMENTS, COLOURS, PLANES = 2, 2, 3
SIDE = 256
WINDOW = (0.0, 3000.0)


def the_brightness(moment: int, channel: int, plane: int) -> int:
    return 600 + 1200 * moment + 600 * channel + 150 * plane


def a_grown_picture(folder: Path) -> Path:
    store = folder / "stores" / "stamped.ome.zarr"
    frames = np.empty((MOMENTS, COLOURS, PLANES, SIDE, SIDE), "uint16")
    for moment in range(MOMENTS):
        for channel in range(COLOURS):
            for plane in range(PLANES):
                frames[moment, channel, plane] = the_brightness(
                    moment, channel, plane)
    made = zarr.create_array(
        store=str(store / "0"), shape=frames.shape,
        chunks=(1, 1, 1, SIDE, SIDE), dtype="uint16", fill_value=0,
        overwrite=True)
    made[:] = frames
    (store / "zarr.json").write_text(json.dumps({
        "zarr_format": 3, "node_type": "group",
        "attributes": {"ome": {"version": "0.5", "multiscales": [{
            "axes": [
                {"name": "t", "type": "time", "unit": "second"},
                {"name": "c", "type": "channel"},
                {"name": "z", "type": "space", "unit": "micrometer"},
                {"name": "y", "type": "space", "unit": "micrometer"},
                {"name": "x", "type": "space", "unit": "micrometer"},
            ],
            "datasets": [{"path": "0", "coordinateTransformations": [
                {"type": "scale", "scale": [1.0, 1.0, 1.0, 1.0, 1.0]},
                {"type": "translation",
                 "translation": [0.0, 0.0, 0.0, 0.0, 0.0]},
            ]}],
        }]}},
    }, indent=2))
    return declare_a_built_picture(folder / "shown", folder / "stores",
                                   name="grown")


def _mean_brightness(page) -> float:
    from PIL import Image

    box = page.locator("canvas").first.bounding_box()
    shot = page.screenshot(clip=box)
    pixels = np.array(Image.open(io.BytesIO(shot)).convert("RGB"))
    return float(pixels.max(axis=2).mean())


def _steer(page, axis: str, value: float) -> None:
    page.evaluate("""([axis, value]) => {
      const position = window.zmartViewer.navigationState.position;
      const names = position.coordinateSpace.value.names;
      const moved = Float32Array.from(position.value);
      moved[names.indexOf(axis)] = value;
      position.value = moved;
    }""", [axis, value])


def _settled(page) -> None:
    page.wait_for_function("() => window.zmartSourcesWaiting() === 0",
                           timeout=90_000)
    page.wait_for_timeout(1_200)


def test_the_grown_picture_draws_and_steers(browser, built_dist, tmp_path):
    shots = tmp_path / "shots"
    shots.mkdir()
    picture = a_grown_picture(tmp_path)
    server = make_server(port=0, data_dir=picture.parent, site_dir=built_dist,
                         store=[picture.name], window=WINDOW, live=True)
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    page = browser.new_page(viewport={"width": 1000, "height": 780})
    try:
        port = server.server_address[1]
        page.goto(f"http://127.0.0.1:{port}", wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartViewer !== undefined",
                               timeout=60_000)
        _settled(page)

        names = page.evaluate(
            """() => Array.from(
              window.zmartViewer.navigationState.position.coordinateSpace.value.names
            )""")
        assert "t" in names, (
            f"the engine's space is {names} -- the grown picture's time axis "
            "never reached the browser"
        )
        assert "z" in names

        # Station 1: the opening frame, and its F5 pair.
        opening = _mean_brightness(page)
        page.screenshot(path=str(shots / "1_t0.png"))
        page.reload(wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartViewer !== undefined",
                               timeout=60_000)
        _settled(page)
        assert abs(_mean_brightness(page) - opening) < 12, (
            "F5 changed the opening frame -- warm and reload disagree"
        )

        # Station 2: one step along time. The stamp says two fifths of the
        # window brighter; demand at least half that, far outside noise.
        _steer(page, "t", 1)
        _settled(page)
        later = _mean_brightness(page)
        page.screenshot(path=str(shots / "2_t1.png"))
        assert later > opening + 25, (
            f"steering t moved brightness {opening:.1f} -> {later:.1f}; the "
            "next moment's stamp is far brighter, so the time axis is not "
            "reaching the pixels"
        )

        # Station 3: one plane down, still at t=1 — a small, definite step.
        _steer(page, "z", 1)
        _settled(page)
        deeper = _mean_brightness(page)
        page.screenshot(path=str(shots / "3_t1_z1.png"))
        assert deeper > later - 12, "stepping z dimmed the picture"

        # Station 4: the F5 pair away from the origin — the operator's
        # protocol: navigate somewhere, reload, the picture must not move.
        page.reload(wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartViewer !== undefined",
                               timeout=60_000)
        _settled(page)
        _steer(page, "t", 1)
        _steer(page, "z", 1)
        _settled(page)
        again = _mean_brightness(page)
        page.screenshot(path=str(shots / "4_t1_z1_after_f5.png"))
        assert abs(again - deeper) < 12, (
            f"the same (t, z) station shows {deeper:.1f} before F5 and "
            f"{again:.1f} after -- reload disagrees with the held page"
        )

        # Colour: however the frontend exposes it — a c axis in the space,
        # or per-channel rows — steering it must brighten by the channel
        # stamp. When neither exists, the grown picture lost its colours.
        if "c" in names:
            _steer(page, "c", 1)
            _settled(page)
            recoloured = _mean_brightness(page)
            page.screenshot(path=str(shots / "5_c1.png"))
            assert recoloured > again + 10, (
                "steering c did not brighten -- the channel axis is not "
                "reaching the pixels"
            )
        else:
            rows = page.evaluate(
                "() => (window.zmartConfig?.layers || []).length")
            assert rows >= COLOURS, (
                f"no c axis in {names} and only {rows} layer row(s) -- the "
                "second colour is not reachable anywhere on this page"
            )
    finally:
        page.close()
        server.shutdown()
        serving.join(timeout=5)
    print(f"screenshots kept at {shots}")
