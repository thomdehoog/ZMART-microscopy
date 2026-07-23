"""Does a real mesoSPIM acquisition load, as written, with no conversion?

The demo volume is written by this repo, so it cannot prove the viewer reads
what the microscope actually produces. These tests run against a real mesoSPIM
transfer on the share and skip where it is not mounted, which keeps them honest
on the acquisition PC and quiet everywhere else.

Two things a real store does that the demo does not, both load-bearing:

* it is served from a **mapped network drive**, whose resolved form is a UNC
  path — the case that made every request 403 until ``make_server`` resolved
  its directories;
* it carries a **translation** as well as a scale, and has **no channel axis**
  (one store per tile and channel) and **no omero block**, so nothing tells the
  viewer what intensity window to display.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
from server import make_server

_SHARE = Path(
    r"Z:/zmbstaff/10637/Raw_Data/mesoSPIM_transfer_20260626_1700/"
    r"multitile_NF_Mag5x_Ch488_Ch647.ome.zarr"
)
_TILE = "Mag5_Tile0_Ch488_Flt405-488-561-640-Quadrupleblock_Sh1_Rot15.99995.ome.zarr"


@pytest.fixture(scope="module")
def tile() -> Path:
    path = _SHARE / _TILE
    if not (path / ".zattrs").exists():
        pytest.skip(f"real mesoSPIM data not available at {_SHARE}")
    return path


def test_store_is_the_zarr_v2_flavour_the_viewer_asks_for(tile):
    """The source URL uses `|zarr2:`; a v3 store would not load through it."""
    assert json.loads((tile / ".zgroup").read_text())["zarr_format"] == 2
    assert json.loads((tile / "0" / ".zarray").read_text())["zarr_format"] == 2


def test_multiscales_are_ngff_0_4_with_spatial_axes(tile):
    multiscales = json.loads((tile / ".zattrs").read_text())["multiscales"][0]
    assert multiscales["version"] == "0.4"
    assert [a["name"] for a in multiscales["axes"]] == ["z", "y", "x"]
    assert {a["unit"] for a in multiscales["axes"]} == {"micrometer"}
    assert len(multiscales["datasets"]) == 6


def test_levels_carry_a_translation_as_well_as_a_scale(tile):
    """Sample position in stage coordinates — the demo has no equivalent."""
    datasets = json.loads((tile / ".zattrs").read_text())["multiscales"][0]["datasets"]
    for dataset in datasets:
        kinds = [t["type"] for t in dataset["coordinateTransformations"]]
        assert kinds == ["scale", "translation"]
    assert datasets[0]["coordinateTransformations"][0]["scale"] == [10.0, 1.1, 1.1]


def test_chunks_are_blosc_zstd_with_nested_separator(tile):
    array = json.loads((tile / "0" / ".zarray").read_text())
    assert array["dtype"] == "<u2"
    assert array["dimension_separator"] == "/"
    assert array["compressor"]["id"] == "blosc"
    assert array["compressor"]["cname"] == "zstd"


def test_the_viewer_reads_it_from_the_network_share(tile, built_dist, browser):
    """End to end: served off Z:, read by the engine, pixels on the GPU."""
    server = make_server(port=0, data_dir=_SHARE, site_dir=built_dist)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    page = browser.new_page(viewport={"width": 1200, "height": 900})
    try:
        page.goto(base, wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartViewer !== undefined", timeout=30_000)
        page.evaluate(
            """(src) => window.zmartViewer.state.restoreState({
                 layers: [{type: 'image', name: 'meso', source: src,
                           shader: '#uicontrol invlerp normalized(range=[198, 214])\\nvoid main() { emitGrayscale(normalized()); }'}],
                 layout: '4panel',
               })""",
            f"{base}/data/{_TILE}/|zarr2:",
        )

        deadline = time.monotonic() + 180
        report = {"available": 0, "err": None}
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
            if report["err"] or report["available"] > 0:
                break
            time.sleep(1.0)

        assert report["err"] is None, report["err"]
        assert report["names"] == ["z", "y", "x"]
        assert report["scales"] == pytest.approx([1e-5, 1.1e-6, 1.1e-6], rel=1e-6)
        assert report["available"] > 0, "no chunks from the real store reached the GPU"
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)
