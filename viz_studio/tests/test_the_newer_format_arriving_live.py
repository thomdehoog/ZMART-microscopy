"""A run written in the newer format, watched while it is being written.

This is the gap the fault register named and could not close. Every test of a run
arriving as it happens used OME-Zarr 0.4, and the only test of 0.5 opened a folder
that had finished being written. The two never met — so the format this project is
aiming at was never once exercised on the path the microscope actually uses.

That mattered more than a missing tick. Three of the faults found by hand were
version 3 reading faults that the live path would have walked straight into: the
frame count could not read 0.5 at all on three of the four ways version 3 names its
pieces, the axis-unit repair silently stopped working, and the channel count fell
back to trusting the description. Every one of those shows up only when something
is *changing*, which is exactly what the finished-folder test cannot see.

They could not meet before because the writer only produced 0.4. It now produces
either, so this file writes a run as 0.5, tile by tile, with the viewer open and
watching — the ordinary live path, on the newer format.

Each test here carries its own positive control. Asserting that a 0.5 run works is
worth nothing if the store on disk quietly turned out to be a 0.4 one, so the shape
of what was written is checked as well: version 3 keeps its description inside
``zarr.json`` and files the pieces of image under a folder called ``c``, neither of
which a 0.4 store has.
"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pixels import image_middle
from server import make_server

from zmart_storage.canvas import Channel, TileCanvases

# A canvas a quarter of which one tile fills, so a tile landing is plainly visible
# in a photograph rather than being a few pixels somebody has to squint at.
CANVAS = (4, 1024, 1024)
TILE = (4, 256, 256)
CHUNK, LEVELS = 128, 2

ANNOUNCE = """async () => {
  const response = await fetch('/api/announce', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({reason: 'a tile was written', wrote_image_in_place: true}),
  });
  return (await response.json()).told;
}"""


def a_run(
    folder: Path,
    name: str = "overview",
    *,
    frames: int = 1,
    voxel_size_um: tuple[float, float, float] = (2.0, 0.35, 0.35),
) -> TileCanvases:
    """One acquisition type's image, declared empty, in the newer format.

    ``voxel_size_um`` is what makes two stores a different *kind* of scan rather
    than two positions of the same one. That is read from inside each store rather
    than from its name, because an overview and a close-up target scan were taken
    at different magnifications and nobody can rename that away.
    """
    return TileCanvases.create(
        folder,
        name=name,
        canvas_shape=CANVAS,
        tile_shape=TILE,
        tile_step=TILE,
        voxel_size_um=voxel_size_um,
        channels=[Channel("488", window=(0, 4000))],
        frames=frames,
        chunk=CHUNK,
        levels=LEVELS,
        ome_zarr_version="0.5",
    )


def a_tile() -> np.ndarray:
    """A tile with structure in it, so it cannot be mistaken for a flat fill."""
    z, y, x = TILE
    ramp = np.linspace(600, 3800, x, dtype=np.float32)
    plane = np.tile(ramp, (y, 1))
    plane[::16, :] = 3900
    return np.broadcast_to(plane, (z, y, x)).astype("uint16")


def how_much_is_drawn(page) -> float:
    """The share of the middle of the picture showing specimen rather than nothing."""
    pixels = image_middle(page)
    return float((pixels.max(axis=2) > 40).mean())


READY = """() => {
  const v = window.zmartViewer;
  if (!v) return false;
  let needed = 0, available = 0;
  for (const managed of v.layerManager.managedLayers) {
    for (const rl of (managed.layer && managed.layer.renderLayers) || []) {
      const p = rl.layerChunkProgressInfo;
      if (p) { needed += p.numVisibleChunksNeeded; available += p.numVisibleChunksAvailable; }
    }
  }
  return available > 0 && available >= needed;
}"""


def open_the_viewer(browser, built_dist, folder: Path, store: str | None = None):
    """A viewer open on the run, with its first draw finished.

    Naming a store opens exactly that one. Leaving it out opens the *folder*, which
    is what an operator does and what lets an acquisition written later be found —
    a viewer pinned to one named store has been told what to show and does not go
    looking for more.
    """
    if store is None:
        server = make_server(port=0, data_dir=folder, site_dir=built_dist, loads=[{}])
    else:
        server = make_server(
            port=0, data_dir=folder, site_dir=built_dist, store=store, live=True
        )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1000, "height": 800})
    page.goto(f"http://127.0.0.1:{server.server_address[1]}", wait_until="domcontentloaded")
    page.wait_for_function("() => window.zmartViewer !== undefined", timeout=30_000)
    page.wait_for_function(READY, timeout=60_000)
    page.wait_for_timeout(1500)
    return server, thread, page


# --------------------------------------------------------------------------
# The positive control: what was written really is the newer format


def test_the_writer_really_produces_version_three_on_disk(tmp_path):
    """Without this, every test below could be passing against a 0.4 store."""
    run = tmp_path / "run"
    a_run(run).close()
    store = run / "overview.ome.zarr"

    assert (store / "zarr.json").exists(), "no zarr.json, so this is not version 3"
    assert not (store / ".zattrs").exists(), "a .zattrs file means this is version 2"

    described = json.loads((store / "zarr.json").read_text())
    assert described["zarr_format"] == 3
    # 0.5 gathers the OME description under an `ome` key inside the store's own
    # attributes, rather than leaving it at the top of a file of its own.
    ome = described["attributes"]["ome"]
    assert ome["version"] == "0.5"
    assert [axis["name"] for axis in ome["multiscales"][0]["axes"]] == ["t", "c", "z", "y", "x"]
    # And the pieces of image are filed under `c`, which is version 3's own naming
    # and the layout the frame counting has to understand.
    assert (store / "0" / "c").exists() or not any(
        entry.name not in {"zarr.json"} for entry in (store / "0").iterdir()
    ), "version 3 should file its pieces under a folder called c"


def test_the_two_formats_describe_the_same_run(tmp_path):
    """A run is the same run whichever way it is written down.

    Everything an operator sees comes through these five answers, so if they agree
    then choosing a format is genuinely a matter of what else can read the folder.
    """
    from stores import axis_names, channels, voxel_size, written_timepoints, zarr_scheme

    seen = {}
    for version in ("0.4", "0.5"):
        run = tmp_path / f"run{version}"
        canvas = TileCanvases.create(
            run, name="overview", canvas_shape=CANVAS, tile_shape=TILE, tile_step=TILE,
            voxel_size_um=(2.0, 0.35, 0.35),
            channels=[Channel("488"), Channel("561")],
            frames=4, chunk=CHUNK, levels=LEVELS, ome_zarr_version=version,
        )
        canvas.write(a_tile(), origin=(0, 0, 0), channel=0, frame=0)
        canvas.write(a_tile(), origin=(0, 0, TILE[2]), channel=1, frame=1)
        canvas.close()
        store = run / "overview.ome.zarr"
        seen[version] = {
            "axes": axis_names(store),
            "channels": [c["name"] for c in channels(store)],
            "voxel": voxel_size(store),
            "frames": written_timepoints(store),
        }
        # The one thing that must differ, so this is not comparing a store with itself.
        assert zarr_scheme(store) == ("zarr3" if version == "0.5" else "zarr2")

    assert seen["0.4"] == seen["0.5"], (
        f"the two formats describe the run differently: {seen}"
    )


# --------------------------------------------------------------------------
# The live path, on the newer format


def test_a_tile_written_into_a_newer_format_run_appears(browser, built_dist, tmp_path):
    """The ordinary live path — a tile landing inside an open store — on 0.5."""
    run = tmp_path / "run"
    canvas = a_run(run)
    server, thread, page = open_the_viewer(browser, built_dist, run, "overview.ome.zarr")
    try:
        empty = how_much_is_drawn(page)

        canvas.write(a_tile(), origin=(0, TILE[1], TILE[2]), tile_index=(0, 1, 1))
        assert page.evaluate(ANNOUNCE) >= 1, "the page was not listening"
        page.wait_for_timeout(2500)

        after = how_much_is_drawn(page)
        assert after > empty + 0.02, (
            f"a tile written into a 0.5 store did not appear: {empty:.3f} -> {after:.3f}"
        )
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def test_a_newer_format_timelapse_lengthens_as_it_is_written(
    browser, built_dist, tmp_path
):
    """The time slider must follow a 0.5 run as its moments land.

    This is the combination that had never been tested and where the reading faults
    were found: counting how far a run reaches means reading the folder the pieces
    are filed in, and version 3 names that folder differently. A run that declares
    ten moments and has imaged three must offer three.
    """
    run = tmp_path / "run"
    canvas = a_run(run, frames=10)
    canvas.write(a_tile(), origin=(0, 0, 0), frame=0, tile_index=(0, 0, 0))

    server, thread, page = open_the_viewer(browser, built_dist, run, "overview.ome.zarr")
    try:
        frames_now = "() => (window.zmartConfig.layers[0] || {}).frames"
        assert page.evaluate(frames_now) == 1, (
            "a run that has imaged one moment of ten should offer one, not the "
            f"ten it declared — got {page.evaluate(frames_now)}"
        )

        for frame in (1, 2):
            canvas.write(a_tile(), origin=(0, 0, 0), frame=frame, tile_index=(0, 0, 0))
        assert page.evaluate(ANNOUNCE) >= 1
        page.wait_for_function(f"{frames_now} === 3", timeout=30_000)

        assert page.evaluate(frames_now) == 3, (
            "the run reached three moments and the viewer did not follow it"
        )
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def test_a_newer_format_position_arriving_mid_run_joins_the_picture(
    browser, built_dist, tmp_path
):
    """Another position of the same scan is one more piece of the same specimen.

    It must join the row it belongs to rather than become a row of its own — the
    positions of a tiled overview are pieces of one picture, and the engine places
    each by the stage position recorded inside it.
    """
    run = tmp_path / "run"
    first = a_run(run, "overview")
    first.write(a_tile(), origin=(0, 0, 0), tile_index=(0, 0, 0))

    # Opened as a folder rather than as one named store, because that is what an
    # operator does and it is the only way an acquisition written later is found.
    server, thread, page = open_the_viewer(browser, built_dist, run)
    try:
        rows = "() => window.zmartConfig.layers.length"
        pieces = "() => window.zmartConfig.layers[0].sources.length"
        assert page.evaluate(rows) == 1
        assert page.evaluate(pieces) == 1

        # Same magnification, so this is the same kind of scan in another place.
        second = a_run(run, "overview_pos2")
        second.write(a_tile(), origin=(0, TILE[1], TILE[2]), tile_index=(0, 1, 1))
        second.close()
        assert page.evaluate(ANNOUNCE) >= 1
        page.wait_for_function(f"{pieces} === 2", timeout=30_000)

        assert page.evaluate(rows) == 1, (
            "another position of the same scan became a row of its own"
        )
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def test_a_newer_format_second_kind_of_scan_gets_its_own_row(
    browser, built_dist, tmp_path
):
    """A target scan arriving mid-run must not be swallowed into the overview.

    This is the fault that used to leave a target scan with no heading, no eye and
    no way to tell it was there, checked here on the newer format. What makes the
    two a different kind of scan is the magnification recorded inside each store,
    not the name — so the second is written with a much larger voxel.
    """
    run = tmp_path / "run"
    first = a_run(run, "overview")
    first.write(a_tile(), origin=(0, 0, 0), tile_index=(0, 0, 0))

    server, thread, page = open_the_viewer(browser, built_dist, run)
    try:
        rows = "() => window.zmartConfig.layers.length"
        assert page.evaluate(rows) == 1

        second = a_run(run, "targetscan", voxel_size_um=(5.0, 2.0, 2.0))
        second.write(a_tile(), origin=(0, TILE[1], TILE[2]), tile_index=(0, 1, 1))
        second.close()
        assert page.evaluate(ANNOUNCE) >= 1
        page.wait_for_function(f"{rows} === 2", timeout=30_000)

        names = page.evaluate("() => window.zmartConfig.layers.map((l) => l.group)")
        assert any("targetscan" in str(name) for name in names), (
            f"the target scan has no heading of its own: {names}"
        )
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)
