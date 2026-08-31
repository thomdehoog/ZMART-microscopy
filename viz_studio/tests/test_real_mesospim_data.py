"""Does a real mesoSPIM acquisition load, as written, with no conversion?

The demo volume is written by this repo, so it cannot prove the viewer reads what
a microscope actually produces. These tests run against a real mesoSPIM transfer
and skip, with a clear reason, where there is not one to hand.

Two things a real store does that the demo does not, both load-bearing:

* it is often served from a **mapped network drive**, whose resolved form is a
  UNC path — the case that made every request 403 until ``make_server`` resolved
  its directories;
* it carries a **translation** as well as a scale, and has **no channel axis**
  (one store per tile and channel) and **no omero block**, so nothing in the file
  tells the viewer what intensity window to display.

**Pointing these at your data.** Set ``ZMART_MESOSPIM_STORE`` to a mesoSPIM
transfer folder — the one holding the per-tile ``.ome.zarr`` stores::

    ZMART_MESOSPIM_STORE=/mnt/share/mesoSPIM_transfer_.../multitile.ome.zarr \\
        python run_tests.py -k mesospim

They previously named one folder on one acquisition PC, including the timestamp
of a single transfer, which meant they skipped everywhere and always would —
including on the machine they were written for, as soon as the next transfer
happened. Anything the tests need to know about the data they now read from the
data, so any mesoSPIM transfer will do.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest
from contrast import display_window
from pixels import assert_something_was_drawn
from server import make_server

_STORE_ENV = "ZMART_MESOSPIM_STORE"

# Where the acquisition PC keeps its transfers. Tried when nothing else is set,
# so that machine needs no configuration; everywhere else this simply does not
# exist and the tests say why they skipped.
_DEFAULT_SHARE = Path(r"Z:/zmbstaff/10637/Raw_Data")


def _a_transfer() -> Path | None:
    """A mesoSPIM transfer folder to test against, or None if there is none.

    Prefers whatever ``ZMART_MESOSPIM_STORE`` names. Failing that, looks for the
    most recent transfer on the acquisition PC's share — most recent because
    transfers are named with their date, and the newest is the one most likely to
    match what the microscope writes today.
    """
    named = os.environ.get(_STORE_ENV)
    if named:
        path = Path(named)
        return path if path.is_dir() else None
    if not _DEFAULT_SHARE.is_dir():
        return None
    transfers = sorted(_DEFAULT_SHARE.glob("mesoSPIM_transfer_*/*.ome.zarr"))
    return transfers[-1] if transfers else None


def _holds_an_image(candidate: Path) -> bool:
    """Whether a folder is an image store, rather than a group that contains them.

    A transfer folder is itself a zarr group — it has a ``.zgroup`` and an empty
    ``.zattrs`` — so the presence of those files says nothing about whether there
    is an image here. What distinguishes an image is the ``multiscales``
    description of its pyramid, which is also exactly what the reader needs.
    """
    try:
        attrs = json.loads((candidate / ".zattrs").read_text())
    except (OSError, ValueError):
        return False
    return bool(attrs.get("multiscales"))


def _a_tile(transfer: Path) -> Path | None:
    """One tile store from inside a transfer.

    A mesoSPIM transfer holds one store per tile and channel. Any of them
    exercises the same reading path, so we take the first that looks complete
    rather than naming one — a named tile is how these tests became unreachable
    in the first place.
    """
    if _holds_an_image(transfer):
        return transfer  # pointed straight at a single store
    for candidate in sorted(transfer.glob("*.ome.zarr")):
        if _holds_an_image(candidate):
            return candidate
    return None


@pytest.fixture(scope="module")
def transfer() -> Path:
    found = _a_transfer()
    if found is None:
        pytest.skip(
            f"no mesoSPIM transfer to test against — set {_STORE_ENV} to one "
            "(see this file's docstring)"
        )
    return found


@pytest.fixture(scope="module")
def tile(transfer: Path) -> Path:
    found = _a_tile(transfer)
    if found is None:
        pytest.skip(f"no readable .ome.zarr tile inside {transfer}")
    return found


def test_store_is_the_zarr_v2_flavour_the_viewer_asks_for(tile):
    """The source URL uses `|zarr2:`; a v3 store would not load through it."""
    assert json.loads((tile / ".zgroup").read_text())["zarr_format"] == 2
    level = json.loads((tile / ".zattrs").read_text())["multiscales"][0]["datasets"][0]
    assert json.loads((tile / level["path"] / ".zarray").read_text())["zarr_format"] == 2


def test_multiscales_are_ngff_0_4_with_spatial_axes(tile):
    multiscales = json.loads((tile / ".zattrs").read_text())["multiscales"][0]
    assert multiscales["version"] == "0.4"
    # No channel axis: a mesoSPIM writes one store per tile and channel, which is
    # the arrangement the viewer has to merge back into rows itself.
    assert [a["name"] for a in multiscales["axes"]] == ["z", "y", "x"]
    assert {a["unit"] for a in multiscales["axes"]} == {"micrometer"}
    # A pyramid, not a single level — without one, moving around a large tile
    # would haul full-resolution data for a zoomed-out view.
    assert len(multiscales["datasets"]) > 1


def test_levels_carry_a_translation_as_well_as_a_scale(tile):
    """Sample position in stage coordinates — the demo has no equivalent.

    This is what places tiles beside one another. The numbers differ per
    acquisition, so what is checked is that both transformations are present on
    every level and that the scale grows down the pyramid, which is what a
    correctly written pyramid does.
    """
    datasets = json.loads((tile / ".zattrs").read_text())["multiscales"][0]["datasets"]
    scales = []
    for dataset in datasets:
        kinds = [t["type"] for t in dataset["coordinateTransformations"]]
        assert kinds == ["scale", "translation"], dataset["path"]
        scales.append(dataset["coordinateTransformations"][0]["scale"])
    for finer, coarser in zip(scales, scales[1:], strict=False):
        assert coarser[-1] > finer[-1], f"pyramid does not get coarser: {scales}"


def test_chunks_are_the_compressed_sixteen_bit_form_the_reader_expects(tile):
    level = json.loads((tile / ".zattrs").read_text())["multiscales"][0]["datasets"][0]
    array = json.loads((tile / level["path"] / ".zarray").read_text())
    assert array["dtype"] == "<u2"  # unsigned 16-bit, what the detector gives
    # Each chunk in its own nested folder rather than one flat directory of
    # millions of files, which is what keeps a large store openable.
    assert array["dimension_separator"] == "/"
    assert array["compressor"]["id"] == "blosc"


def test_the_viewer_reads_it_from_where_it_was_written(tile, transfer, built_dist, browser):
    """End to end: served off the share, read by the engine, drawn on screen.

    The last part matters as much as the rest. An earlier version of this checked
    only that pieces of image reached the graphics card, and that can be true
    while the panel shows nothing at all — which is exactly what happened on the
    demo volume for weeks. So this looks at the picture too.
    """
    # Real mesoSPIM stores carry no omero block, so nothing in the file says what
    # intensity window to display, and without one a 16-bit image renders black.
    # Measuring it is what the viewer itself does when it opens a store.
    low, high = display_window(tile)

    served_from = tile.parent if tile != transfer else transfer.parent
    server = make_server(port=0, data_dir=served_from, site_dir=built_dist)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    page = browser.new_page(viewport={"width": 1200, "height": 900})
    try:
        page.goto(base, wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartViewer !== undefined", timeout=30_000)
        page.evaluate(
            """([src, low, high]) => window.zmartViewer.state.restoreState({
                 layers: [{type: 'image', name: 'meso', source: src,
                           shader: '#uicontrol invlerp normalized(range=[' + low + ', ' + high + '])\\n'
                                 + 'void main() { emitGrayscale(normalized()); }'}],
                 layout: 'yz',
               })""",
            [f"{base}/data/0/{tile.name}/|zarr2:", low, high],
        )

        deadline = time.monotonic() + 180
        report = {"available": 0, "err": None, "names": [], "scales": []}
        while time.monotonic() < deadline:
            report = page.evaluate(
                """() => {
                  const v = window.zmartViewer;
                  let needed = 0, available = 0, err = null;
                  for (const m of v.layerManager.managedLayers) {
                    const ds = m.layer && m.layer.dataSources && m.layer.dataSources[0];
                    if (ds && ds.loadState && ds.loadState.error) err = String(ds.loadState.error);
                    for (const rl of (m.layer && m.layer.renderLayers) || []) {
                      const p = rl.layerChunkProgressInfo;
                      if (p) { needed += p.numVisibleChunksNeeded; available += p.numVisibleChunksAvailable; }
                    }
                  }
                  const d = v.coordinateSpace.value;
                  return {needed, available, err, scales: d ? Array.from(d.scales) : [], names: d ? d.names : []};
                }"""
            )
            if report["err"] or (report["available"] > 0 and report["available"] >= report["needed"]):
                break
            time.sleep(1.0)

        assert report["err"] is None, report["err"]
        assert report["names"] == ["z", "y", "x"]
        # Micrometres in the file, metres in the engine: every scale should land
        # somewhere sensible for a light-sheet voxel rather than being off by the
        # thousand that a missed unit conversion would give.
        assert all(1e-8 < scale < 1e-3 for scale in report["scales"]), report["scales"]
        assert report["available"] > 0, "no chunks from the real store reached the GPU"
        page.wait_for_timeout(2000)
        assert_something_was_drawn(page, "the real mesoSPIM tile")
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)
