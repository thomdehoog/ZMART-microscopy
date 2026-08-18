"""Every operator door, fed exactly what nobody should ever feed it.

The load window's doors answer folder paths, names and paces that come from
an operator's hands, and one day from other people's scripts. Each gate here
abuses one door the way a slip, a typo, or a hostile caller would, and pins
the answer we can stand behind: a plain refusal in the reply, never a hang,
never a crash, and never a file written anywhere the operator did not point.

Server-level on purpose -- no browser -- so the whole battery runs in
seconds and can grow a case per incident forever.
"""

import sys
import threading
import time
from pathlib import Path

import pytest

VIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(VIZ / "building"))
sys.path.insert(0, str(VIZ / "backend"))
sys.path.insert(0, str(VIZ.parent))

from server import make_server  # noqa: E402
from test_a_dataset_is_relived_as_a_live_run import (  # noqa: E402
    _a_grid_scan,
    _post,
)
from test_open_and_close import _store  # noqa: E402


@pytest.fixture
def door(built_dist, tmp_path):
    """A served viewer and the folder beside it, for abusing."""
    first = tmp_path / "overview"
    first.mkdir()
    _store(first / "overview_pos001.ome.zarr", channels=1)
    server = make_server(port=0, data_dir=first, site_dir=built_dist,
                         store="overview_pos001.ome.zarr")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", tmp_path
    finally:
        server.shutdown()
        thread.join(timeout=5)


class TestTheConstructDoor:
    def test_a_name_cannot_walk_out_of_the_scene_folder(self, door):
        """A name with path steps in it must not place files anywhere.

        ``name`` becomes the scene's folder name; fed ``../escaped`` it
        would land the scene BESIDE the folder the operator chose, and a
        hostile caller could aim it anywhere the server can write. Refused
        at the door, with nothing written.
        """
        address, folder = door
        scan = _a_grid_scan(folder / "scan")
        for name in ("../escaped", "a/b", "..", "a\\b"):
            status, answer = _post(address, "/api/stores/construct",
                                   {"path": str(scan),
                                    "viewer_folder": str(scan / "scenes"),
                                    "bake": False, "name": name})
            assert status == 400, (name, status, answer)
            assert "name" in answer["error"], answer
        assert not (folder / "escaped.ome.zarr").exists()
        assert not (folder / "scan" / "escaped.ome.zarr").exists()

    def test_a_file_where_a_folder_should_be_answers_plainly(self, door):
        address, folder = door
        pretender = folder / "not-a-folder.txt"
        pretender.write_text("hello", encoding="utf-8")
        status, answer = _post(address, "/api/stores/construct",
                               {"path": str(pretender),
                                "viewer_folder": str(folder / "scenes"),
                                "bake": False})
        assert status == 404 and "folder" in answer["error"]

    def test_an_empty_dataset_reports_its_reason_through_the_status(self, door):
        """The build thread's failure must surface, not strand the poller."""
        address, folder = door
        empty = folder / "empty"
        empty.mkdir()
        status, _ = _post(address, "/api/stores/construct",
                          {"path": str(empty),
                           "viewer_folder": str(empty / "scenes"),
                           "bake": False})
        assert status == 200
        for _ in range(100):
            _, told = _post(address, "/api/stores/construct-status", {})
            if told.get("state") != "running":
                break
            time.sleep(0.1)
        assert told.get("state") == "error"
        assert "no OME-Zarr" in told.get("error", "")


class TestTheReplayDoorAbused:
    def test_a_hostile_pace_cannot_kill_the_replay(self, door):
        """A negative or absurd 'every' is clamped, not crashed on."""
        address, folder = door
        scan = _a_grid_scan(folder / "paced")
        status, answer = _post(address, "/api/stores/replay",
                               {"path": str(scan), "every": -5})
        assert status == 200, answer
        for _ in range(100):
            _, told = _post(address, "/api/stores/replay-status", {})
            if told.get("state") != "running":
                break
            time.sleep(0.2)
        assert told.get("state") == "done", told

    def test_replaying_a_scene_folder_is_refused_with_its_reason(self, door):
        """A scenes folder holds a built picture, not raw positions."""
        address, folder = door
        scan = _a_grid_scan(folder / "raw")
        status, _ = _post(address, "/api/stores/construct",
                          {"path": str(scan),
                           "viewer_folder": str(scan / "scenes"),
                           "bake": False, "name": "linked"})
        assert status == 200
        for _ in range(100):
            _, told = _post(address, "/api/stores/construct-status", {})
            if told.get("state") != "running":
                break
            time.sleep(0.1)
        assert told.get("state") == "done"
        status, answer = _post(address, "/api/stores/replay",
                               {"path": str(scan / "scenes")})
        assert status == 400, answer
        assert answer.get("error"), "the refusal must carry its reason"

    def test_a_second_replay_of_the_same_dataset_gets_its_own_folder(self, door):
        address, folder = door
        scan = _a_grid_scan(folder / "again")
        for expected in ("replay-1", "replay-2"):
            status, _ = _post(address, "/api/stores/replay",
                              {"path": str(scan), "every": 0})
            assert status == 200
            for _ in range(150):
                _, told = _post(address, "/api/stores/replay-status", {})
                if told.get("state") != "running":
                    break
                time.sleep(0.2)
            assert told.get("state") == "done"
            assert (scan / "replays" / expected / "data").exists()
            _post(address, "/api/stores/close", {"group": f"{scan.name} replay"})


class TestTheOpenDoor:
    def test_a_broken_description_is_refused_not_crashed_on(self, door):
        """A truncated zarr.json is what a copy interrupted halfway leaves."""
        address, folder = door
        broken = folder / "broken" / "hurt.ome.zarr"
        broken.mkdir(parents=True)
        (broken / "zarr.json").write_text('{"attributes": {"ome":',
                                          encoding="utf-8")
        status, answer = _post(address, "/api/stores/open",
                               {"path": str(broken)})
        assert status in (400, 404), (status, answer)
        assert answer.get("error"), "the refusal must say something"

    def test_a_half_written_scene_is_refused_plainly(self, door):
        """A scene folder without its description is a build that died."""
        address, folder = door
        half = folder / "half" / "scene.ome.zarr"
        (half / "0").mkdir(parents=True)
        status, answer = _post(address, "/api/stores/open",
                               {"path": str(half)})
        assert status in (400, 404), (status, answer)
        assert answer.get("error")

    def test_listing_a_missing_folder_answers_inside_the_reply(self, door):
        address, _ = door
        status, answer = _post(address, "/api/stores/list",
                               {"path": "/nowhere/at/all"})
        assert status in (200, 400, 404)
        if status != 200:
            assert answer.get("error")


class TestTheDoorsTogether:
    def test_a_build_and_a_replay_can_run_at_once(self, door):
        """The two jobs are separate machines and must not trip each other."""
        address, folder = door
        building = _a_grid_scan(folder / "building")
        replaying = _a_grid_scan(folder / "replaying")
        status, _ = _post(address, "/api/stores/replay",
                          {"path": str(replaying), "every": 0.3})
        assert status == 200
        status, _ = _post(address, "/api/stores/construct",
                          {"path": str(building),
                           "viewer_folder": str(building / "scenes"),
                           "bake": True, "name": "baked"})
        assert status == 200
        outcomes = {}
        for route, key in (("/api/stores/construct-status", "build"),
                           ("/api/stores/replay-status", "replay")):
            for _ in range(200):
                _, told = _post(address, route, {})
                if told.get("state") != "running":
                    break
                time.sleep(0.2)
            outcomes[key] = told.get("state")
        assert outcomes == {"build": "done", "replay": "done"}, outcomes
