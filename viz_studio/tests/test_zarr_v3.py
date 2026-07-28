"""Zarr v3 and OME-Zarr 0.5, including sharded stores.

The engine has been able to read these all along — it registers ``zarr:``,
``zarr2:`` and ``zarr3:`` providers, implements the ``sharding_indexed`` codec,
and accepts OME multiscale versions 0.4 and 0.5. What stopped a version 3 store
opening was our own wiring: every source address was written ``|zarr2:``.

Sharding matters here for a reason that has nothing to do with speed of reading.
A run of forty thousand positions at six pyramid levels is millions of small
files, which a managed Windows filesystem handles badly. Sharding packs them into
few large ones, and the engine still fetches a single chunk out of a shard with an
HTTP range request rather than pulling the whole thing — so the filesystem relief
costs nothing at the viewer.

The scheme is chosen per store from what is on disk rather than by asking the
engine to detect it. ``zarr:`` would auto-detect, but it does so by probing for
*both* layouts on every source, doubling the small metadata requests that a large
folder is already dominated by.
"""

from __future__ import annotations

import json
import threading
import urllib.request

import numpy as np
import pytest
import zarr
from library import Library
from server import make_server
from stores import axis_names, declared_channels, is_store, voxel_size, zarr_scheme


def _v3_store(path, *, channels=("488", "561"), shards=None):
    """An OME-Zarr 0.5 store: zarr v3, metadata under ``ome`` in ``zarr.json``."""
    shape = (1, len(channels), 4, 64, 64)
    chunks = (1, 1, 2, 32, 32)
    group = zarr.open_group(str(path), mode="w", zarr_format=3)
    array = group.create_array(
        "0", shape=shape, chunks=chunks, shards=shards, dtype="uint16"
    )
    array[:] = np.full(shape, 1200, dtype=np.uint16)
    group.attrs.update(
        {
            "ome": {
                "version": "0.5",
                "multiscales": [
                    {
                        "axes": [
                            {"name": "t", "type": "time", "unit": "second"},
                            {"name": "c", "type": "channel"},
                            {"name": "z", "type": "space", "unit": "micrometer"},
                            {"name": "y", "type": "space", "unit": "micrometer"},
                            {"name": "x", "type": "space", "unit": "micrometer"},
                        ],
                        "datasets": [
                            {
                                "path": "0",
                                "coordinateTransformations": [
                                    {"type": "scale", "scale": [1.0, 1.0, 2.0, 0.5, 0.5]}
                                ],
                            }
                        ],
                    }
                ],
                "omero": {"channels": [{"label": name} for name in channels]},
            }
        }
    )
    return path


def _v2_store(path):
    """The layout everything else in this suite writes, for the contrast."""
    path.mkdir(parents=True)
    group = zarr.open_group(str(path), mode="w", zarr_format=2)
    group.create_array("0", shape=(4, 32, 32), chunks=(1, 32, 32), dtype="uint16")[:] = 900
    (path / ".zattrs").write_text(
        json.dumps(
            {
                "multiscales": [
                    {
                        "version": "0.4",
                        "axes": [{"name": a, "unit": "micrometer"} for a in ("z", "y", "x")],
                        "datasets": [
                            {
                                "path": "0",
                                "coordinateTransformations": [
                                    {"type": "scale", "scale": [2.0, 0.5, 0.5]}
                                ],
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


class TestChoosingTheScheme:
    def test_a_version_2_store_is_addressed_as_zarr2(self, tmp_path):
        assert zarr_scheme(_v2_store(tmp_path / "old.ome.zarr")) == "zarr2"

    def test_a_version_3_store_is_addressed_as_zarr3(self, tmp_path):
        assert zarr_scheme(_v3_store(tmp_path / "new.ome.zarr")) == "zarr3"

    def test_a_sharded_store_is_addressed_the_same_way(self, tmp_path):
        """Sharding is a codec, not a format version — it must not change the scheme."""
        store = _v3_store(tmp_path / "sharded.ome.zarr", shards=(1, 1, 4, 64, 64))
        assert zarr_scheme(store) == "zarr3"

    def test_something_unreadable_falls_back_rather_than_raising(self, tmp_path):
        empty = tmp_path / "nothing"
        empty.mkdir()
        assert zarr_scheme(empty) == "zarr2"


class TestReadingVersion3Metadata:
    """OME 0.5 puts multiscales under ``ome`` inside ``zarr.json``, not in ``.zattrs``."""

    def test_it_is_recognised_as_a_store_at_all(self, tmp_path):
        assert is_store(_v3_store(tmp_path / "new.ome.zarr"))

    def test_its_axes_are_read(self, tmp_path):
        store = _v3_store(tmp_path / "new.ome.zarr")
        assert axis_names(store) == ["t", "c", "z", "y", "x"]

    def test_its_voxel_size_is_read(self, tmp_path):
        """Spatial axes only — the t and c entries say nothing about magnification."""
        store = _v3_store(tmp_path / "new.ome.zarr")
        assert voxel_size(store) == (2.0, 0.5, 0.5)

    def test_its_channels_are_read_from_the_ome_block(self, tmp_path):
        """0.5 moved ``omero`` under ``ome``; reading the old place finds nothing."""
        store = _v3_store(tmp_path / "new.ome.zarr", channels=("488", "561", "640"))
        assert declared_channels(store) == ["488", "561", "640"]

    def test_a_sharded_store_reads_the_same(self, tmp_path):
        store = _v3_store(tmp_path / "sharded.ome.zarr", shards=(1, 1, 4, 64, 64))
        assert axis_names(store) == ["t", "c", "z", "y", "x"]
        assert declared_channels(store) == ["488", "561"]


class TestServingVersion3:
    def _config_over_http(self, folder, name):
        server = make_server(port=0, data_dir=folder, store=[name], live=False)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{server.server_address[1]}/api/config"
            ) as answer:
                return json.loads(answer.read())
        finally:
            server.shutdown()
            thread.join(timeout=5)

    def test_the_config_addresses_it_as_zarr3(self, tmp_path):
        folder = tmp_path / "run"
        folder.mkdir()
        _v3_store(folder / "overview_pos001.ome.zarr", shards=(1, 1, 4, 64, 64))
        config = self._config_over_http(folder, "overview_pos001.ome.zarr")
        sources = [source for layer in config["layers"] for source in layer.get("sources", [])]
        assert sources, "a version 3 store produced no layers at all"
        assert all(source.endswith("|zarr3:") for source in sources), sources

    def test_a_version_2_store_is_still_addressed_as_zarr2(self, tmp_path):
        """The positive control: the change must not relabel what already worked."""
        folder = tmp_path / "run"
        folder.mkdir()
        _v2_store(folder / "overview_pos001.ome.zarr")
        config = self._config_over_http(folder, "overview_pos001.ome.zarr")
        sources = [source for layer in config["layers"] for source in layer.get("sources", [])]
        assert sources and all(source.endswith("|zarr2:") for source in sources), sources

    def test_a_version_3_store_opens_as_a_dataset(self, tmp_path):
        folder = tmp_path / "run"
        folder.mkdir()
        _v3_store(folder / "overview_pos001.ome.zarr")
        library = Library()
        number = library.open(folder)
        assert library.dataset(number).stores == ["overview_pos001.ome.zarr"]


class TestTheServerContractShardingNeeds:
    """Byte ranges and HEAD, which nothing asked of this server until sharding did.

    These live beside the sharding tests because that is the only thing that uses
    them, and because the end-to-end test above cannot say *why* it failed when
    one of them breaks — it simply waits for pixels that never come.
    """

    def _serving(self, tmp_path):
        folder = tmp_path / "run"
        folder.mkdir()
        store = _v2_store(folder / "overview_pos001.ome.zarr")
        server = make_server(port=0, data_dir=folder, store=[store.name], live=False)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        chunk = f"http://127.0.0.1:{server.server_address[1]}/data/0/{store.name}/0/0.0.0"
        return server, thread, chunk

    def _ask(self, url, *, headers=None, method="GET"):
        request = urllib.request.Request(url, headers=headers or {}, method=method)
        try:
            with urllib.request.urlopen(request) as answer:
                return answer.status, dict(answer.headers), answer.read()
        except urllib.error.HTTPError as refused:
            return refused.code, dict(refused.headers), refused.read()

    def test_a_range_gets_exactly_those_bytes_and_says_so(self, tmp_path):
        server, thread, chunk = self._serving(tmp_path)
        try:
            _, _, whole = self._ask(chunk)
            status, headers, body = self._ask(chunk, headers={"Range": "bytes=4-11"})
            assert status == 206
            assert body == whole[4:12]
            assert headers["Content-Range"] == f"bytes 4-11/{len(whole)}"
            assert headers["Content-Length"] == "8"
        finally:
            server.shutdown()
            thread.join(timeout=5)

    def test_a_suffix_range_reads_from_the_end(self, tmp_path):
        """How the index at the end of a shard is fetched."""
        server, thread, chunk = self._serving(tmp_path)
        try:
            _, _, whole = self._ask(chunk)
            status, _, body = self._ask(chunk, headers={"Range": "bytes=-6"})
            assert status == 206
            assert body == whole[-6:]
        finally:
            server.shutdown()
            thread.join(timeout=5)

    def test_head_gives_the_size_without_the_body(self, tmp_path):
        """The body is not merely wasteful here — it desynchronises the connection."""
        server, thread, chunk = self._serving(tmp_path)
        try:
            _, _, whole = self._ask(chunk)
            status, headers, body = self._ask(chunk, method="HEAD")
            assert status == 200
            assert body == b""
            assert headers["Content-Length"] == str(len(whole))
            assert headers["Accept-Ranges"] == "bytes"
        finally:
            server.shutdown()
            thread.join(timeout=5)

    def test_a_range_past_the_end_is_refused_rather_than_wrapped(self, tmp_path):
        server, thread, chunk = self._serving(tmp_path)
        try:
            status, headers, _ = self._ask(chunk, headers={"Range": "bytes=999999-"})
            assert status == 416
            assert headers["Content-Range"].startswith("bytes */")
        finally:
            server.shutdown()
            thread.join(timeout=5)

    def test_no_range_still_gets_the_whole_thing(self, tmp_path):
        """The positive control: the ordinary request must be untouched."""
        server, thread, chunk = self._serving(tmp_path)
        try:
            status, headers, body = self._ask(chunk)
            assert status == 200
            assert "Content-Range" not in headers
            assert len(body) == int(headers["Content-Length"])
        finally:
            server.shutdown()
            thread.join(timeout=5)


def test_a_sharded_version_3_store_reaches_the_renderer(tmp_path, built_dist, browser):
    """The whole point, end to end: sharded v3 data actually draws.

    Nothing else in the suite would catch a wrong scheme being emitted, because
    every other fixture is version 2 and ``|zarr2:`` is right for those.
    """
    folder = tmp_path / "run"
    folder.mkdir()
    _v3_store(folder / "overview_pos001.ome.zarr", shards=(1, 1, 4, 64, 64))
    server = make_server(port=0, data_dir=folder, store=["overview_pos001.ome.zarr"], live=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 900, "height": 700})
    try:
        page.goto(f"http://127.0.0.1:{server.server_address[1]}", wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartViewer !== undefined", timeout=60_000)
        page.wait_for_function(
            """() => {
                 const v = window.zmartViewer;
                 let needed = 0, available = 0;
                 for (const m of v.layerManager.managedLayers)
                   for (const rl of (m.layer && m.layer.renderLayers) || []) {
                     const p = rl.layerChunkProgressInfo;
                     if (p) { needed += p.numVisibleChunksNeeded; available += p.numVisibleChunksAvailable; }
                   }
                 return available > 0 && available >= needed;
               }""",
            timeout=120_000,
        )
        errors = page.evaluate(
            """() => {
                 const out = [];
                 for (const m of window.zmartViewer.layerManager.managedLayers)
                   for (const ds of (m.layer && m.layer.dataSources) || [])
                     if (ds.loadState && ds.loadState.error) out.push(String(ds.loadState.error));
                 return out;
               }"""
        )
        assert errors == []
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)
