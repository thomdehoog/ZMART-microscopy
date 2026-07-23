"""The HTTP contract the viewer depends on.

The viewer fetches hundreds of small chunk files from one origin, so the pieces
that matter are: a missing chunk answers 404 (zarr treats that as "background
here", and turning it into an error would break sparse volumes), a path may not
climb out of the data directory, and the JSON endpoints answer the shapes the
frontend expects.
"""

from __future__ import annotations

import http.client
import json
import threading

import pytest
from server import make_server


@pytest.fixture
def serving(tmp_path):
    """A server over throwaway site/data directories, on a free port."""
    site = tmp_path / "site"
    data = tmp_path / "data"
    (site / "assets").mkdir(parents=True)
    data.mkdir()
    (site / "index.html").write_text("<!doctype html><title>page</title>", encoding="utf-8")
    (data / "demo.zarr").mkdir()
    (data / "demo.zarr" / ".zattrs").write_text('{"multiscales": []}', encoding="utf-8")
    (data / "demo.zarr" / "chunk").write_bytes(b"\x01\x02\x03\x04")
    (tmp_path / "outside.txt").write_text("secret", encoding="utf-8")

    server = make_server(port=0, data_dir=data, site_dir=site)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        thread.join(timeout=5)


def request(port: int, path: str, method: str = "GET", body: bytes | None = None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        headers = {"Content-Length": str(len(body))} if body is not None else {}
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        conn.close()


def test_root_serves_the_built_page(serving):
    status, _, body = request(serving, "/")
    assert status == 200
    assert b"<title>page</title>" in body


def test_chunk_is_served_byte_exact_with_a_length(serving):
    status, headers, body = request(serving, "/data/demo.zarr/chunk")
    assert status == 200
    assert body == b"\x01\x02\x03\x04"
    assert headers["Content-Length"] == "4"
    assert headers["Content-Type"] == "application/octet-stream"


def test_missing_chunk_is_a_plain_404(serving):
    """Sparse volumes rely on this: absent chunk means background, not error."""
    status, _, _ = request(serving, "/data/demo.zarr/0/9.9.9.9")
    assert status == 404


def test_path_traversal_out_of_the_data_directory_is_refused(serving):
    status, _, _ = request(serving, "/data/../outside.txt")
    assert status == 403


def test_health_endpoint(serving):
    status, _, body = request(serving, "/api/health")
    assert status == 200
    assert json.loads(body) == {"ok": True}


def config_from(**kwargs) -> dict:
    """The /api/config a server built with ``kwargs`` answers."""
    server = make_server(port=0, **kwargs)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        _, _, body = request(server.server_address[1], "/api/config")
    finally:
        server.shutdown()
        thread.join(timeout=5)
    return json.loads(body)


def test_config_tells_the_page_what_to_open(serving):
    """The page fetches this instead of hardcoding a store, so --data works."""
    status, _, body = request(serving, "/api/config")
    assert status == 200
    layers = json.loads(body)["layers"]
    assert len(layers) == 1
    assert layers[0]["source"] == "/data/demo.zarr/|zarr2:"
    assert layers[0]["window"]["high"] > layers[0]["window"]["low"]


def test_config_reports_the_store_it_was_given(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("x", encoding="utf-8")
    config = config_from(
        data_dir=tmp_path, site_dir=site, store="acquisition.zarr", window=(5.0, 50.0)
    )
    assert config["layers"][0]["source"] == "/data/acquisition.zarr/|zarr2:"
    assert config["layers"][0]["window"] == {"low": 5.0, "high": 50.0}


def test_several_stores_become_several_layers(tmp_path):
    """A tiled acquisition is many stores; they must arrive as many layers."""
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("x", encoding="utf-8")
    names = [
        "Mag5_Tile0_Ch488_FltEmpty_Sh1_Rot0.ome.zarr",
        "Mag5_Tile0_Ch647_FltEmpty_Sh1_Rot0.ome.zarr",
        "Mag5_Tile1_Ch488_FltEmpty_Sh1_Rot0.ome.zarr",
    ]
    config = config_from(
        data_dir=tmp_path, site_dir=site, store=names, window=(0.0, 100.0)
    )
    layers = config["layers"]
    assert [layer["name"] for layer in layers] == ["Tile0_Ch488", "Tile0_Ch647", "Tile1_Ch488"]
    assert [layer["source"] for layer in layers] == [f"/data/{n}/|zarr2:" for n in names]


def test_channels_are_coloured_only_when_overlaid(tmp_path):
    """One channel alone stays greyscale; 488 and 647 together go green/magenta."""
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("x", encoding="utf-8")
    alone = config_from(
        data_dir=tmp_path, site_dir=site, store="Tile0_Ch488.ome.zarr", window=(0.0, 1.0)
    )
    assert alone["layers"][0]["color"] is None

    together = config_from(
        data_dir=tmp_path,
        site_dir=site,
        store=["Tile0_Ch488.ome.zarr", "Tile0_Ch647.ome.zarr"],
        window=(0.0, 1.0),
    )
    green, magenta = (layer["color"] for layer in together["layers"])
    assert green == [0.0, 1.0, 0.4]
    assert magenta == [1.0, 0.2, 1.0]


def test_goto_echoes_the_box_it_was_given(serving):
    payload = {"min": [1, 2, 3], "max": [4, 5, 6]}
    status, _, body = request(
        serving, "/api/goto", method="POST", body=json.dumps(payload).encode()
    )
    assert status == 200
    answer = json.loads(body)
    assert answer["received"] == payload
    assert "goto" in answer["action"]


def test_malformed_goto_body_is_rejected(serving):
    status, _, _ = request(serving, "/api/goto", method="POST", body=b"{not json")
    assert status == 400


def test_unknown_api_routes_are_404(serving):
    assert request(serving, "/api/nope")[0] == 404
    assert request(serving, "/api/nope", method="POST", body=b"{}")[0] == 404


def test_post_outside_the_api_is_404(serving):
    assert request(serving, "/index.html", method="POST", body=b"{}")[0] == 404


def test_serves_data_from_an_unresolved_directory(tmp_path):
    """The guard must compare like with like, or real stores 403.

    ``make_server`` is handed whatever path the caller has: a mapped network
    drive (``Z:\\...`` resolving to a UNC path), a symlink, or simply a path
    with a ``..`` in it. The traversal check resolves the *request* target, so
    unless the configured directory is resolved too, nothing under it is ever
    served — which is how a real acquisition folder fails while the demo works.
    """
    data = tmp_path / "data"
    data.mkdir()
    (data / "chunk").write_bytes(b"\xaa\xbb")
    unresolved = tmp_path / "data" / ".." / "data"

    server = make_server(port=0, data_dir=unresolved, site_dir=tmp_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, _, body = request(server.server_address[1], "/data/chunk")
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert status == 200
    assert body == b"\xaa\xbb"


def test_server_binds_localhost_only(tmp_path):
    """The command endpoint must not be reachable from the network."""
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("x", encoding="utf-8")
    server = make_server(port=0, data_dir=tmp_path, site_dir=site)
    try:
        assert server.server_address[0] == "127.0.0.1"
    finally:
        server.server_close()
