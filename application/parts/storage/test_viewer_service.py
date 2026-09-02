"""The Smart Viewer sources that reach the operator canvas."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

import application.parts.storage.viewer_service as service


def _config(*layers: dict) -> dict:
    return {"layers": [{"kind": "image", **layer} for layer in layers]}


def _empty_service(*, port: int | None = None) -> dict:
    return {
        "server": None,
        "thread": None,
        "port": port,
        "error": None,
        "sources": {},
        "acquisitions": [],
        "opened": set(),
    }


def test_the_installed_smart_viewer_is_the_separate_supported_package():
    found = service.viewer_provenance()

    assert found["version"] == "0.2.0"
    assert not Path(found["path"]).is_relative_to(service._MICROSCOPY_ROOT)


def test_an_in_repository_viewer_copy_is_refused():
    copied = service._MICROSCOPY_ROOT / "viz_studio" / "backend" / "zmart_viewer.py"

    with pytest.raises(RuntimeError, match="separate ZMART-viewer checkout"):
        service._validate_viewer_provenance("0.2.0", copied)


def test_an_unproved_viewer_release_is_refused(tmp_path):
    with pytest.raises(RuntimeError, match="Smart Viewer 0.2.0 is required"):
        service._validate_viewer_provenance("0.1.0", tmp_path / "zmart_viewer" / "__init__.py")


def test_the_external_viewer_owns_the_measurement_route(tmp_path):
    viewer_server = service._smart_viewer_server()
    server = viewer_server.make_server(
        port=0,
        data_dir=str(tmp_path),
        live=True,
        allow_open=True,
        panel_side="left",
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/measure",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with pytest.raises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(request, timeout=service.VIEWER_POLL_TIMEOUT_S)
        assert raised.value.code == 400
        assert json.load(raised.value) == {"error": "which picture to measure is needed"}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_every_field_in_one_viewer_dataset_is_kept():
    answered = service._the_sources_in(
        _config(
            {
                "group": "overview",
                "sources": [
                    f"/data/0/overview_P{number:06d}.ome.zarr/|zarr3:" for number in range(4)
                ],
            }
        ),
        port=8848,
    )

    assert len(answered["overview"]) == 4
    assert all(
        one["url"].startswith("http://127.0.0.1:8848/data/0/") for one in answered["overview"]
    )


def test_only_the_newest_dataset_generation_is_kept():
    answered = service._the_sources_in(
        _config(
            {
                "group": "overview",
                "sources": [
                    "/data/0/overview_P000000.ome.zarr/|zarr3:",
                    "/data/0/overview_P000001.ome.zarr/|zarr3:",
                    "/data/2/overview_P000000.ome.zarr/|zarr3:",
                    "/data/2/overview_P000001.ome.zarr/|zarr3:",
                    "/data/2/overview_P000002.ome.zarr/|zarr3:",
                ],
            }
        ),
        port=8848,
    )

    assert len(answered["overview"]) == 3
    assert all("/data/2/" in one["url"] for one in answered["overview"])


def test_smart_viewer_channel_rows_keep_all_their_spatial_sources():
    sources = [f"/data/7/overview_P{number:06d}.ome.zarr/|zarr3:" for number in range(9)]
    answered = service._the_acquisitions_in(
        _config(
            *[
                {
                    "group": "overview",
                    "name": f"channel {channel}",
                    "channelIndex": channel,
                    "color": [0, channel / 2, 1],
                    "window": {"low": 192, "high": 2575},
                    "histogram": {"counts": [1, 2, 3], "low": 0, "high": 4095},
                    "sources": sources,
                }
                for channel in range(3)
            ]
        ),
        port=8848,
    )

    assert len(answered) == 1
    assert answered[0]["name"] == "overview"
    assert len(answered[0]["channels"]) == 3
    assert [channel["name"] for channel in answered[0]["channels"]] == [
        "channel 0",
        "channel 1",
        "channel 2",
    ]
    assert all(len(channel["sources"]) == 9 for channel in answered[0]["channels"])
    assert all(
        source.startswith("http://127.0.0.1:8848/data/7/")
        for channel in answered[0]["channels"]
        for source in channel["sources"]
    )


def test_scene_discards_an_old_generation_without_flattening_the_new_one():
    answered = service._the_acquisitions_in(
        _config(
            {
                "group": "overview",
                "name": "channel 0",
                "channelIndex": 0,
                "sources": [
                    "/data/3/old-a.ome.zarr/|zarr3:",
                    "/data/3/old-b.ome.zarr/|zarr3:",
                    "/data/17/current-a.ome.zarr/|zarr3:",
                    "/data/17/current-b.ome.zarr/|zarr3:",
                    "/data/17/current-c.ome.zarr/|zarr3:",
                ],
            }
        ),
        port=8848,
    )

    assert len(answered[0]["channels"][0]["sources"]) == 3
    assert all("/data/17/" in source for source in answered[0]["channels"][0]["sources"])


def test_viewer_decorations_do_not_make_an_extra_acquisition():
    answered = service._the_sources_in(
        _config(
            {
                "group": "session-abc · overview.zmartview.zarr (2)",
                "sources": ["/data/2/overview.ome.zarr/|zarr3:"],
            },
            {
                "group": "focussing",
                "sources": ["/data/3/focussing.ome.zarr/|zarr3:"],
            },
        ),
        port=8848,
    )

    assert sorted(answered) == ["focussing", "overview"]


def test_status_reads_the_live_viewer_config_afresh(monkeypatch):
    before = dict(service._viewer)
    service._viewer.clear()
    service._viewer.update(_empty_service(port=8848))
    asked: list[tuple[int, str]] = []

    def read(port: int, route: str) -> dict:
        asked.append((port, route))
        return _config(
            {
                "group": "overview",
                "sources": [
                    f"/data/0/overview_P{number:06d}.ome.zarr/|zarr3:" for number in range(4)
                ],
            }
        )

    monkeypatch.setattr(service, "_read", read)
    try:
        state = service.status()
    finally:
        service._viewer.clear()
        service._viewer.update(before)

    assert asked == [(8848, "/api/config")]
    assert len(state["sources"]["overview"]) == 4
    assert len(state["acquisitions"]) == 1
    assert len(state["acquisitions"][0]["channels"]) == 1
    assert len(state["acquisitions"][0]["channels"][0]["sources"]) == 4


def test_status_keeps_the_last_picture_when_a_refresh_stumbles(monkeypatch):
    before = dict(service._viewer)
    service._viewer.clear()
    service._viewer.update(_empty_service(port=8848))
    service._viewer["sources"] = {
        "overview": [{"url": "http://127.0.0.1:8848/data/0/overview.ome.zarr/", "name": "overview"}]
    }

    def unavailable(port: int, route: str) -> dict:
        raise TimeoutError(f"{port}{route} did not answer")

    monkeypatch.setattr(service, "_read", unavailable)
    try:
        state = service.status()
    finally:
        service._viewer.clear()
        service._viewer.update(before)

    assert len(state["sources"]["overview"]) == 1
    assert "current picture could not be read" in state["error"]


def test_a_growing_folder_is_opened_once_and_then_only_announced(monkeypatch, tmp_path):
    before = dict(service._viewer)
    service._viewer.clear()
    service._viewer.update(_empty_service(port=8848))
    calls: list[tuple[str, dict]] = []

    def ask(port: int, route: str, payload: dict) -> dict:
        assert port == 8848
        calls.append((route, payload))
        if route == "/api/stores/open":
            return _config(
                {
                    "group": "overview",
                    "sources": ["/data/0/overview_P000000.ome.zarr/|zarr3:"],
                }
            )
        return {}

    monkeypatch.setattr(service, "_ask", ask)
    try:
        service.a_position_landed("overview", tmp_path)
        service.a_position_landed("overview", tmp_path)
    finally:
        service._viewer.clear()
        service._viewer.update(before)

    assert calls == [
        ("/api/stores/open", {"path": str(tmp_path)}),
        ("/api/announce", {"wrote_image_in_place": True}),
        ("/api/announce", {"wrote_image_in_place": True}),
    ]
    assert not any(route == "/api/stores/close" for route, _ in calls)


def test_live_config_read_finishes_before_the_next_operator_poll(monkeypatch):
    seen: list[tuple[str, float]] = []

    class Answer:
        def __enter__(self):
            return self

        def __exit__(self, *ignored):
            return None

        def read(self):
            return json.dumps({"layers": []}).encode()

    def urlopen(url: str, timeout: float):
        seen.append((url, timeout))
        return Answer()

    monkeypatch.setattr(service.urllib.request, "urlopen", urlopen)

    assert service._read(8848, "/api/config") == {"layers": []}
    assert seen == [("http://127.0.0.1:8848/api/config", service.VIEWER_POLL_TIMEOUT_S)]
    assert service.VIEWER_POLL_TIMEOUT_S < 1.5


def test_a_store_gone_from_disk_is_left_out_of_what_the_page_is_handed(tmp_path):
    """A shorter rerun removes stores; the viewer still lists them.

    The viewer is never asked to close the acquisition (a folder it has closed
    is a different picture to it when opened again), so the service leaves
    any source whose store is gone out of both answers it gives the page."""
    before = dict(service._viewer)
    service._viewer.clear()
    service._viewer.update(_empty_service(port=8848))
    folder = tmp_path / "positions" / "target"
    (folder / "target_P000000.ome.zarr").mkdir(parents=True)
    (folder / "target_P000001.ome.zarr").mkdir()
    service._viewer["opened"].add(str(folder))
    config = _config(
        {
            "group": "target",
            "name": "channel 0",
            "sources": [
                "/data/1/target_P000000.ome.zarr/|zarr3:",
                "/data/1/target_P000001.ome.zarr/|zarr3:",
                "/data/1/target_P000002.ome.zarr/|zarr3:",
            ],
        },
        {"group": "target", "name": "channel 0", "sources": ["/data/1/target_P000002.ome.zarr/|zarr3:"]},
    )
    try:
        sources = service._the_sources_in(config, 8848)
        acquisitions = service._the_acquisitions_in(config, 8848)
    finally:
        service._viewer.clear()
        service._viewer.update(before)
    assert [one["url"].rsplit("/", 2)[-2] for one in sources["target"]] == [
        "target_P000000.ome.zarr", "target_P000001.ome.zarr",
    ]
    assert [len(channel["sources"]) for channel in acquisitions[0]["channels"]] == [2], (
        "the row the viewer split off for the missing store is dropped, not added as a channel"
    )


def test_addresses_outside_the_opened_folders_are_left_alone():
    before = dict(service._viewer)
    service._viewer.clear()
    service._viewer.update(_empty_service(port=8848))
    try:
        assert service._still_on_disk("/data/0/demo.zarr/|zarr2:")
        assert service._still_on_disk("http://elsewhere/picture.zarr")
    finally:
        service._viewer.clear()
        service._viewer.update(before)


def test_retired_stores_are_announced_plainly(monkeypatch, tmp_path):
    before = dict(service._viewer)
    service._viewer.clear()
    service._viewer.update(_empty_service(port=8848))
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(service, "_ask", lambda port, route, payload: calls.append((route, payload)) or {})
    try:
        service.stores_were_retired("target", tmp_path)
    finally:
        service._viewer.clear()
        service._viewer.update(before)
    assert calls == [("/api/announce", {})]


def test_retiring_stores_without_a_viewer_is_nothing(tmp_path):
    before = dict(service._viewer)
    service._viewer.clear()
    service._viewer.update(_empty_service(port=None))
    try:
        service.stores_were_retired("target", tmp_path)
        assert service._viewer["error"] is None
    finally:
        service._viewer.clear()
        service._viewer.update(before)
