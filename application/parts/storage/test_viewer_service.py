"""The Smart Viewer sources that reach the operator canvas."""

from __future__ import annotations

import json
import threading
import time
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
        "source_versions": {},
        "source_order": {},
        "canvas": {"x_um": [0, 160], "y_um": [0, 160]},
        "pending": set(),
        "wake": threading.Event(),
    }


def test_the_installed_smart_viewer_is_the_separate_supported_package():
    found = service.viewer_provenance()

    assert found["version"] == "0.2.1"
    assert not Path(found["path"]).is_relative_to(service._MICROSCOPY_ROOT)


def test_an_in_repository_viewer_copy_is_refused():
    copied = service._MICROSCOPY_ROOT / "viz_studio" / "backend" / "zmart_viewer.py"

    with pytest.raises(RuntimeError, match="separate ZMART-viewer checkout"):
        service._validate_viewer_provenance("0.2.1", copied)


@pytest.mark.parametrize("installed_version", ["0.1.0", "0.2.0", "0.2.2"])
def test_an_unproved_viewer_release_is_refused(tmp_path, installed_version):
    with pytest.raises(RuntimeError, match=r"Smart Viewer 0\.2\.1 is required"):
        service._validate_viewer_provenance(
            installed_version, tmp_path / "zmart_viewer" / "__init__.py"
        )


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
            urllib.request.urlopen(request, timeout=service.VIEWER_REQUEST_TIMEOUT_S)
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


def test_publication_reads_config_and_status_only_reads_the_snapshot(monkeypatch):
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
    monkeypatch.setattr(service, "_ask", lambda *_: {})
    try:
        service._publish_once(service._viewer["wake"], {})
        state = service.status()
        service.status()
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
    monkeypatch.setattr(service, "_ask", lambda *_: {})
    try:
        service._publish_once(service._viewer["wake"], {})
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
    for i in range(2):
        (tmp_path / f"overview_P{i:06}.ome.zarr").mkdir()

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
    monkeypatch.setattr(service, "_read", lambda *_: {})
    try:
        service.a_position_landed(
            "overview", tmp_path, store=tmp_path / "overview_P000000.ome.zarr"
        )
        _flush()
        service.a_position_landed(
            "overview", tmp_path, store=tmp_path / "overview_P000001.ome.zarr"
        )
        _flush()
    finally:
        service._viewer.clear()
        service._viewer.update(before)

    assert [route for route, _ in calls] == ["/api/stores/open", "/api/announce"]
    assert calls[0][1]["composition"]["regions"] == "complete"
    assert len(calls[1][1]["publications"][0]["source_revisions"]) == 2
    assert not any(route == "/api/stores/close" for route, _ in calls)


def test_background_config_read_has_a_bounded_timeout(monkeypatch):
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
    assert seen == [("http://127.0.0.1:8848/api/config", service.VIEWER_REQUEST_TIMEOUT_S)]
    assert 0 < service.VIEWER_REQUEST_TIMEOUT_S <= 30


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
        {
            "group": "target",
            "name": "channel 0",
            "sources": ["/data/1/target_P000002.ome.zarr/|zarr3:"],
        },
    )
    try:
        sources = service._the_sources_in(config, 8848)
        acquisitions = service._the_acquisitions_in(config, 8848)
    finally:
        service._viewer.clear()
        service._viewer.update(before)
    assert [one["url"].rsplit("/", 2)[-2] for one in sources["target"]] == [
        "target_P000000.ome.zarr",
        "target_P000001.ome.zarr",
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
    monkeypatch.setattr(
        service, "_ask", lambda port, route, payload: calls.append((route, payload)) or {}
    )
    monkeypatch.setattr(service, "_read", lambda *_: {})
    service._viewer["opened"].add(str(tmp_path))
    try:
        service.stores_were_retired("target", tmp_path)
        _flush()
    finally:
        service._viewer.clear()
        service._viewer.update(before)
    assert [route for route, _ in calls] == ["/api/announce"]
    assert calls[0][1]["publications"][0]["source_revisions"] == {}
    assert calls[0][1]["publications"][0]["composition"]["order"] == []


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


def test_only_rewritten_stores_advance_their_published_revision(monkeypatch, tmp_path):
    monkeypatch.setattr(service, "_viewer", _empty_service(port=8848))
    first = tmp_path / "overview_P000000.ome.zarr"
    second = tmp_path / "overview_P000001.ome.zarr"
    first.mkdir()
    second.mkdir()
    config = _config(
        {
            "group": "overview",
            "sources": [f"/data/0/{store.name}/|zarr3:" for store in (first, second)],
        }
    )
    calls = []

    def ask(port, route, payload):
        calls.append((route, payload))
        return config if route == "/api/stores/open" else {}

    monkeypatch.setattr(service, "_ask", ask)
    monkeypatch.setattr(service, "_read", lambda *_: config)
    service.a_position_landed("overview", tmp_path, store=first)
    _flush()
    service.a_position_landed("overview", tmp_path, store=second)
    _flush()
    rows = service.status()["acquisitions"][0]["channels"]
    assert rows[0]["sourceRevisions"] == [1, 1]
    service.a_position_landed("overview", tmp_path, store=first)
    _flush()
    rows = service.status()["acquisitions"][0]["channels"]
    assert rows[0]["sourceRevisions"] == [2, 1]
    publications = [payload["publications"][0] for route, payload in calls if route == "/api/announce"]
    assert [list(p["source_revisions"].values()) for p in publications] == [[1, 1], [2, 1]]
    assert publications[-1]["composition"]["order"] == [second.name, first.name]


def test_source_revisions_match_url_encoded_names(monkeypatch):
    state = _empty_service(port=8848)
    state["source_versions"][("overview", "a position.ome.zarr")] = 3
    monkeypatch.setattr(service, "_viewer", state)
    rows = service._the_acquisitions_in(
        _config(
            {
                "group": "overview",
                "sources": ["/data/0/a%20position.ome.zarr/|zarr3:"],
            }
        ),
        8848,
    )
    assert rows[0]["channels"][0]["sourceRevisions"] == [3]


def _flush():
    pending = set(service._viewer["pending"])
    service._viewer["pending"].clear()
    return service._publish_once(service._viewer["wake"], pending)


def test_stalled_viewer_does_not_block_capture_or_status_and_coalesces_100_writes(
    monkeypatch, tmp_path
):
    state = _empty_service(port=8848)
    monkeypatch.setattr(service, "_viewer", state)
    entered, release, captured, published = (threading.Event() for _ in range(4))
    calls = []
    for i in range(100):
        (tmp_path / f"P{i}.zarr").mkdir()

    def read(*_):
        entered.set()
        assert release.wait(5)
        return _config(
            {"group": "overview", "sources": [f"/data/0/P{i}.zarr/|zarr3:" for i in range(100)]}
        )

    def ask(port, route, payload):
        calls.append((route, payload))
        return {}

    monkeypatch.setattr(service, "_ask", ask)
    monkeypatch.setattr(service, "_read", read)
    monkeypatch.setattr(service, "_still_on_disk", lambda _: True)
    publish = service._publish_once

    def publish_and_signal(*args):
        result = publish(*args)
        published.set()
        return result

    monkeypatch.setattr(service, "_publish_once", publish_and_signal)
    worker = threading.Thread(target=service._publish_changes, args=(state["wake"],))
    worker.start()
    service.a_position_landed("overview", tmp_path, store="P0.zarr")
    assert entered.wait(2)

    def capture():
        for i in range(1, 100):
            service.a_position_landed("overview", tmp_path, store=f"P{i}.zarr")
            assert service.status()["acquisitions"] == []
        captured.set()

    producer = threading.Thread(target=capture)
    producer.start()
    try:
        assert captured.wait(2), "capture or status waited for the blocked viewer"
        assert not release.is_set()
        assert state["pending"] == {str(tmp_path)}
        assert len(state["source_versions"]) == 100
        release.set()
        assert published.wait(2)
    finally:
        release.set()
        producer.join(2)
        wake = state["wake"]
        with service._the_turn:
            state["wake"] = None
        wake.set()
        worker.join(2)
    assert not worker.is_alive()
    assert len(service.status()["acquisitions"][0]["channels"][0]["sources"]) == 100
    assert sum(route == "/api/stores/open" for route, _ in calls) == 1
    assert sum(route == "/api/announce" for route, _ in calls) <= 2


def test_failed_publication_is_retained_and_retried_without_another_capture(monkeypatch, tmp_path):
    state = _empty_service(port=8848)
    monkeypatch.setattr(service, "_viewer", state)
    monkeypatch.setattr(service, "_ask", lambda *_: {})
    recovered = threading.Event()
    reads = []

    def read(*_):
        reads.append(1)
        if len(reads) == 1:
            raise TimeoutError("busy")
        recovered.set()
        return {}

    monkeypatch.setattr(service, "_read", read)
    service.a_position_landed("overview", tmp_path, store="P0.zarr")
    worker = threading.Thread(target=service._publish_changes, args=(state["wake"],))
    worker.start()
    try:
        assert recovered.wait(4), "a failed snapshot must retry even when acquisition stops"
    finally:
        wake = state["wake"]
        with service._the_turn:
            state["wake"] = None
        wake.set()
        worker.join(2)
    assert len(reads) == 2


def test_late_snapshot_cannot_replace_a_new_session(monkeypatch):
    state = _empty_service(port=8848)
    monkeypatch.setattr(service, "_viewer", state)
    monkeypatch.setattr(service, "_ask", lambda *_: {})

    def reconnect(*_):
        state.update(_empty_service(port=8849))
        return _config({"group": "old", "sources": ["/data/0/P0.zarr/|zarr3:"]})

    monkeypatch.setattr(service, "_read", reconnect)
    service._publish_once(state["wake"], {})
    assert service.status()["url"] == "http://127.0.0.1:8849"
    assert service.status()["acquisitions"] == []


def test_retirement_during_the_first_folder_open_is_not_lost(monkeypatch, tmp_path):
    state = _empty_service(port=8848)
    monkeypatch.setattr(service, "_viewer", state)
    (tmp_path / "P0.zarr").mkdir()

    def ask(port, route, payload):
        if route == "/api/stores/open":
            service.stores_were_retired("overview", tmp_path)
        return {}

    monkeypatch.setattr(service, "_ask", ask)
    monkeypatch.setattr(service, "_read", lambda *_: {})
    service.a_position_landed("overview", tmp_path, store="P0.zarr")
    assert _flush()
    assert state["pending"] == {str(tmp_path)}


@pytest.mark.parametrize("bake", [False, True])
def test_real_viewer_publishes_100_positions_without_holding_up_notifications(
    monkeypatch, tmp_path, bake
):
    from zmart_storage.canvas import _declare_one

    monkeypatch.setattr(service, "_viewer", _empty_service())
    folder = tmp_path / "overview"
    folder.mkdir()
    notify_ms, status_ms = [], []
    service.start(tmp_path, bake=bake, canvas={"x_um": [0, 160], "y_um": [0, 160]})
    assert service.status()["running"], service.status()
    server = service._viewer["server"]
    try:
        for i in range(100):
            store = folder / f"P{i:03d}.ome.zarr"
            staging = tmp_path / "writing" / store.name
            arrays = _declare_one(
                staging,
                canvas_shape=(1, 16, 16),
                frames=1,
                channels=1,
                dtype="uint16",
                chunk=16,
                levels=2,
                voxel_size_um=(1, 1, 1),
                origin_um=(0, (i // 10) * 16, (i % 10) * 16),
                channel_blocks=[
                    {
                        "label": "signal",
                        "color": "FFFFFF",
                        "window": {"start": 0, "end": 255, "min": 0, "max": 65535},
                    }
                ],
                ome_zarr_version="0.5",
            )
            arrays[0][:] = i + 1
            arrays[1][:] = i + 1
            from application.parts.storage.zarr_positions import _describe_mean_pyramid
            description_path = staging / "zarr.json"
            description = json.loads(description_path.read_text())
            _describe_mean_pyramid(description)
            description_path.write_text(json.dumps(description))
            # Match the acquisition writer: only complete stores enter the watched folder.
            staging.rename(store)
            before = time.perf_counter()
            service.a_position_landed("overview", folder, store=store)
            notify_ms.append((time.perf_counter() - before) * 1000)
            before = time.perf_counter()
            service.status()
            status_ms.append((time.perf_counter() - before) * 1000)
        last_write = time.perf_counter()
        while time.perf_counter() - last_write < 15:
            state = service.status()
            publication = folder / ".zmart-viewer/overview.ome.zarr/publication.json"
            completed = json.loads(publication.read_text())["versions"] if publication.exists() else {}
            if len(completed) == 100 and state["acquisitions"]:
                break
            time.sleep(0.02)
        assert state["error"] is None, state["error"]
        assert len(state["sources"].get("overview", [])) == 1
        assert len(completed) == 100
        assert not (folder / ".zmart-viewer/overview.ome.zarr/0/c").exists()
        if not bake:
            assert not list((folder / ".zmart-viewer/overview.ome.zarr").glob("*/c"))
        print(
            {
                "positions": 100,
                "bake": bake,
                "notification_max_ms": max(notify_ms),
                "status_max_ms": max(status_ms),
                "final_publication_lag_ms": (time.perf_counter() - last_write) * 1000,
            }
        )
    finally:
        service.stop()
        server.server_close()
