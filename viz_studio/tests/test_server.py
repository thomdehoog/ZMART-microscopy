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

import numpy as np
import pytest
import zarr
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
    config = json.loads(body)
    layers = config["layers"]
    assert len(layers) == 1
    assert layers[0]["source"] == "/data/demo.zarr/|zarr2:"
    assert layers[0]["window"]["high"] > layers[0]["window"]["low"]
    # Both windows travel up front so the 2-D/3-D toggle needs no round trip.
    assert layers[0]["volumeWindow"]["high"] > layers[0]["volumeWindow"]["low"]
    # This fixture has metadata but no readable array, so the server is honest:
    # display can fall back, while a histogram is not invented.
    assert layers[0]["histogram"] is None
    assert config["chrome"] is False, "the engine's own furniture stays hidden"


def test_config_reports_the_store_it_was_given(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("x", encoding="utf-8")
    config = config_from(
        data_dir=tmp_path, site_dir=site, store="acquisition.zarr", window=(5.0, 50.0)
    )
    assert config["layers"][0]["source"] == "/data/acquisition.zarr/|zarr2:"
    assert config["layers"][0]["window"] == {"low": 5.0, "high": 50.0}


def test_config_includes_a_histogram_for_a_readable_store(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("x", encoding="utf-8")
    data = np.arange(4 * 8 * 8, dtype=np.uint16).reshape(4, 8, 8)
    store = tmp_path / "sample.zarr"
    group = zarr.open_group(str(store), mode="w", zarr_format=2)
    group.create_array("0", data=data, chunks=data.shape)
    (store / ".zattrs").write_text(
        json.dumps({"multiscales": [{"datasets": [{"path": "0"}]}]}),
        encoding="utf-8",
    )
    config = config_from(data_dir=tmp_path, site_dir=site, store="sample.zarr")
    histogram = config["layers"][0]["histogram"]
    assert len(histogram["counts"]) == 64
    assert sum(histogram["counts"]) == data.size


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


def _goto_box(unit: str = "m") -> dict:
    """A box the viewer would send: two corners, each axis with its own unit."""
    scale = {"m": 1e-6, "um": 1.0}[unit]
    corner = lambda x, y, z: {  # noqa: E731 -- a table, clearer inline
        "x": {"value": x * scale, "unit": unit},
        "y": {"value": y * scale, "unit": unit},
        "z": {"value": z * scale, "unit": unit},
    }
    return {"id": "target-1", "pointA": corner(10, 40, 4), "pointB": corner(30, 60, 6)}


class _FakeSession:
    """A stand-in microscope, so the endpoint can be tested with no hardware."""

    def __init__(self, refuse=None):
        self.refuse = refuse
        self.moves = []

    def get_xyz(self, with_actuators=None):
        return {"x": 0.0, "y": 0.0, "z": 0.0}

    def set_xyz(self, x, y, z, with_actuators=None):
        if self.refuse is not None:
            raise self.refuse
        self.moves.append((x, y, z))
        return {"ok": True}


@pytest.fixture
def serving_with_microscope(tmp_path):
    """A server with a pretend microscope attached and moves switched on."""
    site = tmp_path / "site"
    data = tmp_path / "data"
    site.mkdir()
    data.mkdir()
    (site / "index.html").write_text("<!doctype html>", encoding="utf-8")

    def build(session, *, allow_stage_moves=True):
        server = make_server(
            port=0,
            data_dir=data,
            site_dir=site,
            session=session,
            allow_stage_moves=allow_stage_moves,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        build.cleanup.append((server, thread))
        return server.server_address[1]

    build.cleanup = []
    try:
        yield build
    finally:
        for server, thread in build.cleanup:
            server.shutdown()
            thread.join(timeout=5)


def test_goto_reports_the_target_without_a_microscope(serving):
    """The demo answers where it *would* go, and moves nothing."""
    status, _, body = request(
        serving, "/api/goto", method="POST", body=json.dumps(_goto_box()).encode()
    )
    assert status == 200
    answer = json.loads(body)
    assert answer["moved"] is False
    assert answer["target"] == pytest.approx({"x": 20.0, "y": 50.0, "z": 5.0})
    assert "no microscope" in answer["action"]


def test_goto_moves_the_stage_to_the_centre_of_the_box(serving_with_microscope):
    session = _FakeSession()
    port = serving_with_microscope(session)
    status, _, body = request(
        port, "/api/goto", method="POST", body=json.dumps(_goto_box()).encode()
    )
    assert status == 200
    assert json.loads(body)["moved"] is True
    assert session.moves == [pytest.approx((20.0, 50.0, 5.0))]


def test_goto_does_not_move_when_moves_are_switched_off(serving_with_microscope):
    """Attaching a microscope is not on its own permission to drive it."""
    session = _FakeSession()
    port = serving_with_microscope(session, allow_stage_moves=False)
    status, _, body = request(
        port, "/api/goto", method="POST", body=json.dumps(_goto_box()).encode()
    )
    assert status == 200
    assert json.loads(body)["moved"] is False
    assert session.moves == []


def test_a_refused_move_answers_conflict_with_the_reason(serving_with_microscope):
    """A driver's travel-limit refusal must reach the operator intact."""
    session = _FakeSession(refuse=RuntimeError("target outside the z travel limit"))
    port = serving_with_microscope(session)
    status, _, body = request(
        port, "/api/goto", method="POST", body=json.dumps(_goto_box()).encode()
    )
    assert status == 409
    answer = json.loads(body)
    assert "outside the z travel limit" in answer["error"]
    assert answer["moved"] is False


def test_a_box_in_an_unknown_unit_is_rejected(serving_with_microscope):
    session = _FakeSession()
    port = serving_with_microscope(session)
    payload = {
        "pointA": {"x": {"value": 1.0, "unit": "furlong"}},
        "pointB": {"x": {"value": 2.0, "unit": "furlong"}},
    }
    status, _, body = request(port, "/api/goto", method="POST", body=json.dumps(payload).encode())
    assert status == 400
    assert "unsupported coordinate unit" in json.loads(body)["error"]
    assert session.moves == []


def test_the_same_box_in_micrometres_lands_in_the_same_place(serving_with_microscope):
    """A store written in µm and one in metres must drive to the same point."""
    session = _FakeSession()
    port = serving_with_microscope(session)
    for unit in ("m", "um"):
        request(port, "/api/goto", method="POST", body=json.dumps(_goto_box(unit)).encode())
    assert session.moves[0] == pytest.approx(session.moves[1])


def test_malformed_goto_body_is_rejected(serving):
    status, _, _ = request(serving, "/api/goto", method="POST", body=b"{not json")
    assert status == 400


def test_annotations_start_empty_and_round_trip_as_a_sidecar(serving):
    status, _, body = request(serving, "/api/annotations")
    assert status == 200
    assert json.loads(body) == {"version": 1, "annotations": []}
    document = {
        "version": 1,
        "annotations": [
            {"id": "p1", "type": "point", "point": [1, 2, 3], "description": "cell"},
            {
                "id": "b1",
                "type": "axis_aligned_bounding_box",
                "pointA": [1, 2, 3],
                "pointB": [4, 5, 6],
                "description": "",
            },
        ],
    }
    status, _, body = request(
        serving, "/api/annotations", method="POST", body=json.dumps(document).encode()
    )
    assert status == 200
    assert json.loads(body) == {
        **document,
        "annotations": [
            {**document["annotations"][0], "point": [1.0, 2.0, 3.0]},
            {
                **document["annotations"][1],
                "pointA": [1.0, 2.0, 3.0],
                "pointB": [4.0, 5.0, 6.0],
            },
        ],
    }
    assert json.loads(request(serving, "/api/annotations")[2]) == json.loads(body)


@pytest.mark.parametrize(
    "document",
    [
        {},
        {"version": 1, "annotations": "not a list"},
        {"version": 1, "annotations": [{"id": "x", "type": "line"}]},
        {
            "version": 1,
            "annotations": [{"id": "x", "type": "point", "point": [float("inf")]}],
        },
    ],
)
def test_invalid_annotation_documents_are_rejected(serving, document):
    status, _, _ = request(
        serving,
        "/api/annotations",
        method="POST",
        body=json.dumps(document).encode(),
    )
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
