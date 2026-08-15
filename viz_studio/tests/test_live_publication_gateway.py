"""The application server, not a test-only server, enforces live publication."""

from __future__ import annotations

import http.client
import threading

from server import make_server

from zmart_live.coordinator import LivePublisher
from zmart_live.gateway import answer_from_a_live_run
from zmart_live.model import GridCell
from zmart_live.profiles import plan_the_writing
from zmart_live.tests.test_coordinator import FRAME, some_specimen


def ask(
    port: int, path: str, *, headers: dict[str, str] | None = None
) -> tuple[int, bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    try:
        connection.request("GET", path, headers=headers or {})
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def test_the_real_backend_withholds_then_routes_the_same_virtual_chunk(tmp_path):
    profile, _ = plan_the_writing("overview", frame=FRAME, z_planes=1)
    run = LivePublisher(
        tmp_path / "run",
        profile,
        run_id="real-backend-gate",
        cells={GridCell(0, 0): "posA"},
    )
    run.write_a_position("posA", some_specimen(2300))
    run.write_the_link_map(frozenset({("posA", 0)}))
    run.write_the_view()
    run.write_the_layout()

    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("viewer", encoding="utf-8")
    store = "views/live/live.ome.zarr"
    server = make_server(
        port=0,
        data_dir=run.folder,
        site_dir=site,
        store=store,
        window=(0, 4095),
        live=True,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        requested = f"/data/0/{store}/0/c/0/0/0/0/0"
        status, body = ask(server.server_address[1], requested)
        assert status == 404 and body == b""

        run.publish("posA")
        status, body = ask(server.server_address[1], requested)
        assert status == 200
        routed = answer_from_a_live_run(run.view_level() / "c/0/0/0/0/0")
        assert routed is not None and routed.serving is not None
        with routed.serving.path.open("rb") as source:
            source.seek(routed.serving.offset)
            expected = source.read(routed.serving.length)
        assert body == expected

        partial_status, partial = ask(
            server.server_address[1], requested, headers={"Range": "bytes=3-17"}
        )
        assert partial_status == 206
        assert partial == expected[3:18]
    finally:
        server.shutdown()
        thread.join(timeout=5)
