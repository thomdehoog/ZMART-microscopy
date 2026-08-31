"""Manifest publication drives the production server's bounded refresh state."""

from __future__ import annotations

import http.client
import json
import threading

import live_config
from announcements import Announcements, ManifestWatcher
from library import Library
from live_config import LIVE_PICTURE, LiveRegistry, live_rows
from server import make_server

from zmart_live.live_state import LiveStateTracker
from zmart_live.tests.test_coordinator import some_specimen
from zmart_live.tests.test_gateway import a_live_run, prepare_without_publishing


def _request(port: int, path: str, *, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    try:
        connection.request("GET", path, headers=headers or {})
        response = connection.getresponse()
        body = response.read()
        return response.status, dict(response.getheaders()), body
    finally:
        connection.close()


def _post(port: int, path: str, payload: dict):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    try:
        body = json.dumps(payload)
        connection.request(
            "POST",
            path,
            body=body,
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


def _server_for(tmp_path, run):
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("viewer", encoding="utf-8")
    server = make_server(
        port=0,
        data_dir=run.folder,
        site_dir=site,
        store="views/overview.ome.zarr",
        window=(0, 4095),
        live=True,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_manifest_watcher_ignores_files_deduplicates_and_tolerates_a_jump(tmp_path):
    run = a_live_run(tmp_path)
    tracker = LiveStateTracker(run.folder)
    announcements = Announcements()
    heard = announcements.listen()
    watcher = ManifestWatcher((tracker,), announcements)

    prepare_without_publishing(run, "posA", 700)
    assert watcher.check_once() == 0
    assert heard.empty()

    run.publish("posA")
    run.write_and_publish("posB", some_specimen(900))
    assert watcher.check_once() == 1
    assert tracker.revision == 2
    assert heard.get_nowait() is not None
    assert heard.empty()

    assert watcher.check_once() == 0
    assert heard.empty()

    marker = run.manifest.truth
    sound = marker.read_text(encoding="utf-8")
    marker.write_text("damaged", encoding="utf-8")
    assert watcher.check_once() == 0
    assert tracker.revision == 2
    assert tracker.freshness == "degraded"
    assert heard.empty()
    marker.write_text(sound, encoding="utf-8")


def test_manifest_watcher_still_nudges_if_an_api_request_observed_first(tmp_path):
    run = a_live_run(tmp_path)
    tracker = LiveStateTracker(run.folder)
    announcements = Announcements()
    heard = announcements.listen()
    watcher = ManifestWatcher((tracker,), announcements)

    run.write_and_publish("posA", some_specimen(700))
    assert tracker.observe() is True, "the API request should win the race"
    assert watcher.check_once() == 1
    assert heard.get_nowait() is not None
    assert watcher.check_once() == 0


def test_live_state_and_config_advance_only_after_commit_with_stable_urls(tmp_path):
    run = a_live_run(tmp_path)
    server, thread = _server_for(tmp_path, run)
    port = server.server_address[1]
    try:
        status, headers, body = _request(port, "/api/live-state")
        assert status == 200
        initial = json.loads(body)
        assert initial["runs"][0]["revision"] == 0
        etag = headers["ETag"]

        prepare_without_publishing(run, "posA", 1700)
        status, _, body = _request(
            port,
            "/api/live-state",
            headers={"If-None-Match": etag},
        )
        assert status == 304 and body == b""
        status, _, body = _request(port, "/api/config")
        assert status == 200
        assert json.loads(body)["layers"] == []

        run.publish("posA")
        status, headers, body = _request(
            port,
            "/api/live-state",
            headers={"If-None-Match": etag},
        )
        assert status == 200
        published = json.loads(body)
        live_run = published["runs"][0]
        assert live_run["revision"] == 1
        assert len(live_run["sources"]) == 1
        assert [source["url"] for source in live_run["sources"]] == [LIVE_PICTURE]
        assert {source["revision"] for source in live_run["sources"]} == {1}
        assert {
            tuple((item["start"], item["stop"]) for item in source["committed_time_ranges"])
            for source in live_run["sources"]
        } == {((0, 1),)}

        status, _, body = _request(port, "/api/config")
        assert status == 200
        config = json.loads(body)
        assert len(config["layers"]) == 1
        assert sum(len(row["sources"]) for row in config["layers"]) == 1
        assert [row["sources"] for row in config["layers"]] == [
            [f"/data/0/{LIVE_PICTURE}/|zarr3:"]
        ]
        assert {revision for row in config["layers"] for revision in row["sourceRevisions"]} == {1}
        assert all("?" not in url for row in config["layers"] for url in row["sources"])
        assert all(row["committedTimeRanges"] == [{"start": 0, "stop": 1}]
                   for row in config["layers"])

        current_etag = headers["ETag"]
        status, _, body = _request(
            port,
            "/api/live-state",
            headers={"If-None-Match": current_etag},
        )
        assert status == 304 and body == b""
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_declared_time_room_does_not_reach_config_until_its_event_commits(tmp_path):
    run = a_live_run(tmp_path, timepoints=2)
    run.write_and_publish("posA", some_specimen(700))
    server, thread = _server_for(tmp_path, run)
    port = server.server_address[1]
    try:
        _, _, body = _request(port, "/api/config")
        assert {tuple((r["start"], r["stop"]) for r in row["committedTimeRanges"])
                for row in json.loads(body)["layers"]} == {((0, 1),)}

        prepare_without_publishing(run, "posA", 2400, moment=1)
        _, _, body = _request(port, "/api/config")
        assert {tuple((r["start"], r["stop"]) for r in row["committedTimeRanges"])
                for row in json.loads(body)["layers"]} == {((0, 1),)}

        run.publish("posA", timepoint=1)
        _, _, body = _request(port, "/api/config")
        config = json.loads(body)
        assert {tuple((r["start"], r["stop"]) for r in row["committedTimeRanges"])
                for row in config["layers"]} == {((0, 2),)}
        assert {revision for row in config["layers"] for revision in row["sourceRevisions"]} == {2}
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_gapped_commits_have_ranges_but_no_misleading_frame_high_water(tmp_path):
    run = a_live_run(tmp_path, timepoints=3)
    run.write_and_publish("posA", some_specimen(700))
    prepare_without_publishing(run, "posA", 2400, moment=2)
    run.publish("posA", timepoint=2)
    server, thread = _server_for(tmp_path, run)
    port = server.server_address[1]
    try:
        _, _, body = _request(port, "/api/config")
        rows = json.loads(body)["layers"]
        assert rows
        assert all(
            row["committedTimeRanges"]
            == [{"start": 0, "stop": 1}, {"start": 2, "stop": 3}]
            for row in rows
        )
        assert all(row["frames"] == 0 for row in rows)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_damaged_marker_serves_last_good_state_as_degraded_until_restored(tmp_path):
    run = a_live_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))
    server, thread = _server_for(tmp_path, run)
    port = server.server_address[1]
    try:
        _, headers, body = _request(port, "/api/live-state")
        sound = json.loads(body)
        assert sound["runs"][0]["revision"] == 1
        old_etag = headers["ETag"]

        marker = run.manifest.truth
        original = marker.read_text(encoding="utf-8")
        marker.write_text("damaged", encoding="utf-8")
        status, headers, body = _request(
            port,
            "/api/live-state",
            headers={"If-None-Match": old_etag},
        )
        assert status == 200
        degraded = json.loads(body)["runs"][0]
        assert degraded["revision"] == 1
        assert degraded["freshness"] == "degraded"
        assert headers["ETag"] != old_etag

        marker.write_text(original, encoding="utf-8")
        _, _, body = _request(port, "/api/live-state")
        restored = json.loads(body)["runs"][0]
        assert restored["revision"] == 1
        assert restored["freshness"] == "current"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_live_registry_follows_the_production_open_and_close_routes(tmp_path):
    first = a_live_run(tmp_path / "first")
    second = a_live_run(tmp_path / "second")
    first.write_and_publish("posA", some_specimen(700))
    second.write_and_publish("posA", some_specimen(1900))
    server, thread = _server_for(tmp_path, first)
    port = server.server_address[1]
    try:
        status, config = _post(
            port,
            "/api/stores/open",
            {"path": str(second.folder / "views" / "overview.ome.zarr")},
        )
        assert status == 200
        assert [run["dataset"] for run in config["liveState"]["runs"]] == [0, 1]
        assert {
            source_id.split("/", 1)[0]
            for row in config["layers"]
            for source_id in row["sourceIds"]
        } == {"0", "1"}

        second_group = next(
            row["group"]
            for row in config["layers"]
            if row["sourceIds"][0].startswith("1/")
        )
        status, closed = _post(
            port,
            "/api/stores/close",
            {"group": second_group},
        )
        assert status == 200
        assert [run["dataset"] for run in closed["liveState"]["runs"]] == [0]
        assert all(
            source_id.startswith("0/")
            for row in closed["layers"]
            for source_id in row["sourceIds"]
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_binding_a_live_run_declares_the_baked_picture_exactly_once(tmp_path, monkeypatch):
    run = a_live_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))
    declared = []
    really = live_config.declare_a_governed_picture

    def counting(*args, **kwargs):
        declared.append(args)
        return really(*args, **kwargs)

    monkeypatch.setattr(live_config, "declare_a_governed_picture", counting)
    library = Library()
    library.open(run.folder, names=["views/overview.ome.zarr"], watch=False)
    registry = LiveRegistry(library)

    bindings, governed = registry.refresh()
    assert len(bindings) == 1 and governed == {0}
    assert len(declared) == 1
    store = run.folder / "views" / "picture.ome.zarr"
    assert (store / "zarr.json").is_file()
    assert (store / "baked.json").is_file()

    bindings, _ = registry.refresh()
    assert len(bindings) == 1
    assert len(declared) == 1, "a second refresh must not re-declare"

    restarted = LiveRegistry(library)
    bindings, _ = restarted.refresh()
    assert len(bindings) == 1
    assert len(declared) == 1, "a fresh registry must recognise the store on disk"

    rows = live_rows(bindings[0])
    assert [row["sources"] for row in rows] == [[f"/data/0/{LIVE_PICTURE}/|zarr3:"]]


def test_the_served_picture_answers_behind_the_manifest_gate(tmp_path):
    run = a_live_run(tmp_path)
    server, thread = _server_for(tmp_path, run)
    port = server.server_address[1]
    piece = f"/data/0/{LIVE_PICTURE}/0/c/0/0/0"
    try:
        status, _, body = _request(port, f"/data/0/{LIVE_PICTURE}/zarr.json")
        assert status == 200 and b"governed_from" in body

        prepare_without_publishing(run, "posA", 1700)
        status, _, body = _request(port, piece)
        assert status == 404 and body == b"", "written but unpublished stays absent"

        run.publish("posA")
        status, _, body = _request(port, piece)
        assert status == 200 and len(body) > 0
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_a_run_whose_picture_cannot_be_declared_is_withheld_not_linked(tmp_path, monkeypatch):
    run = a_live_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))

    def refusing(*args, **kwargs):
        raise ValueError("the bake refused")

    monkeypatch.setattr(live_config, "declare_a_governed_picture", refusing)
    library = Library()
    library.open(run.folder, names=["views/overview.ome.zarr"], watch=False)
    registry = LiveRegistry(library)

    bindings, governed = registry.refresh()
    assert bindings == ()
    assert governed == {0}, "the run still governs its dataset while refused"
    assert any("the bake refused" in why for why in registry.errors.values())


def test_initially_damaged_manifest_never_falls_back_to_folder_inference(tmp_path):
    run = a_live_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))
    run.manifest.truth.write_text("damaged", encoding="utf-8")
    server, thread = _server_for(tmp_path, run)
    port = server.server_address[1]
    try:
        status, _, body = _request(port, "/api/config")
        assert status == 200
        config = json.loads(body)
        assert config["layers"] == []
        assert "liveState" not in config

        status, _, body = _request(port, "/api/live-state")
        assert status == 200
        assert json.loads(body)["runs"] == []
    finally:
        server.shutdown()
        thread.join(timeout=5)
