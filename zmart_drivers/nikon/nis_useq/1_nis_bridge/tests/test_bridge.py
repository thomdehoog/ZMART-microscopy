"""Client <-> real bridge server <-> fake NIS: each operation, and each refusal."""

import importlib
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest
import tifffile
from nis_bridge import bridge, install_macros
from nis_bridge.client import NisClient, NisConnectionError
from nis_bridge.fake import FakeNisApi
from nis_bridge.protocol import decode_reply, encode_request


def test_ping_reports_versions(client):
    assert client.info["nis"].startswith("6.10") and client.info["protocol"] == 2


def test_move_only_the_given_axes(client, fake):
    assert client.request("move", z=800) == {"x": 1000.0, "y": -500.0, "z": 800.0}
    client.request("move", x=10)  # y is kept
    client.request("move", y=20)  # x is kept
    client.request("move", x=1, y=2, z=3)
    assert fake.calls == ["move_z(800)", "move_xy(10,-500)", "move_xy(10,20)", "move_xyz(1,2,3)"]


def test_move_needs_an_axis(client):
    with pytest.raises(ValueError, match="at least one"):
        client.request("move")


def test_unknown_op_and_bad_json_are_value_errors(client, server):
    with pytest.raises(ValueError, match="unknown op 'fly'"):
        client.request("fly")
    with pytest.raises(ValueError, match="not valid JSON"):
        decode_reply(server.handle_line("{nope"))


def test_optical_configuration_must_exist(client):
    assert client.request("select_optical_configuration", name="FITC") == {"selected": "FITC"}
    with pytest.raises(ValueError, match="unknown optical configuration"):
        client.request("select_optical_configuration", name="GFP")


def test_objectives_skip_empty_slots(client):
    assert client.request("get_objectives") == {
        "current": 1,
        "objectives": {"1": "Plan Apo 10x", "2": "Apo 20x WI", "4": "Plan Apo 60x WI"},
    }


def test_set_objective_checks_and_reports_nis_refusal(client):
    assert client.request("set_objective", position=2) == {"current": 2}
    with pytest.raises(ValueError, match="nosepiece position"):
        client.request("set_objective", position="two")
    with pytest.raises(RuntimeError, match="DR_BADPARAMETER"):
        client.request("set_objective", position=9)


def test_exposure_reports_what_nis_applied(client, fake):
    assert client.request("set_exposure", exposure_ms=20.4) == {"exposure_ms": 20}
    with pytest.raises(ValueError, match="positive"):
        client.request("set_exposure", exposure_ms=0)
    assert fake.calls == ["exposure(20.4)"]


def test_snap_saves_a_tiff_and_closes_the_image(client, fake, tmp_path):
    path = tmp_path / "snap.tif"
    assert client.request("snap", path=str(path)) == {"path": str(path), "pixel_size_um": None}
    assert tifffile.imread(path).max() == 1 and fake.open_images == 0


def test_snap_reports_the_calibration(client, fake, tmp_path):
    fake.calibrated = True
    assert client.request("snap", path=str(tmp_path / "a.tif"))["pixel_size_um"] == 0.108


def test_snap_closes_the_image_even_when_saving_fails(client, fake, tmp_path, monkeypatch):
    monkeypatch.setattr(fake, "save_tiff", lambda path: None)  # NIS writes nothing
    with pytest.raises(RuntimeError, match="no file appeared"):
        client.request("snap", path=str(tmp_path / "a.tif"))
    assert fake.open_images == 0


def test_pfs_on_and_off(client, fake):
    assert client.request("set_pfs", on=True)["meaning"] == "on, focused"
    assert client.request("set_pfs", on=False)["on"] is False
    with pytest.raises(ValueError, match="true or false"):
        client.request("set_pfs", on="yes")
    fake.has_pfs = False
    with pytest.raises(RuntimeError, match="no Perfect Focus System"):
        client.request("set_pfs", on=True)


def test_autofocus_failure_is_a_runtime_error(client, fake):
    assert client.request("autofocus", range_um=20)["z"] == 503.0
    fake.autofocus_result = 0
    with pytest.raises(RuntimeError, match="focus not found"):
        client.request("autofocus")


def test_shutdown_asks_the_loop_to_stop(client, server):
    client.request("shutdown")
    assert server.stop_requested


def test_requests_from_several_threads_all_get_their_own_reply(client):
    results = []
    threads = [
        threading.Thread(target=lambda: results.append(client.request("get_position")))
        for _ in range(5)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(results) == 5


# -- when the NIS macro loop is not running -------------------------------------------


@pytest.fixture
def unpumped(fake):
    """A bridge whose macro loop is not running: requests queue up but nothing runs them."""
    srv = bridge.serve(fake, "127.0.0.1", 0)
    yield srv
    srv.shutdown()
    srv.server_close()


def test_a_request_that_never_started_says_why(unpumped):
    reply = unpumped.handle_line(encode_request(1, "get_position", {}, 0.2))
    with pytest.raises(RuntimeError, match="did not start within 0.2 s.*start_bridge.mac"):
        decode_reply(reply)


def test_a_request_the_client_gave_up_on_never_runs_later(unpumped, fake):
    move = encode_request(1, "move", {"z": 700}, 0.2)
    assert "did not start" in unpumped.handle_line(move)
    unpumped.pump()  # the macro loop comes back
    assert fake.calls == [] and fake.position["z"] == 500.0


def test_the_client_hears_why_when_the_loop_is_not_running(unpumped):
    with pytest.raises(RuntimeError, match="'ping' did not start within 0.3 s.*start_bridge.mac"):
        NisClient("127.0.0.1", unpumped.server_address[1], timeout=0.3)


def test_client_reports_a_bridge_that_never_answers(unpumped, monkeypatch):
    monkeypatch.setattr("nis_bridge.client.REPLY_MARGIN_S", 0.0)
    monkeypatch.setattr(unpumped, "handle_line", lambda line: time.sleep(5) or "")
    with pytest.raises(NisConnectionError, match="did not answer 'ping' within 0.3 s"):
        NisClient("127.0.0.1", unpumped.server_address[1], timeout=0.3)


def test_client_refuses_an_old_bridge(port, monkeypatch):
    monkeypatch.setattr(bridge, "PROTOCOL_VERSION", 1)
    with pytest.raises(NisConnectionError, match="speaks protocol 1.*Restart start_bridge.mac"):
        NisClient("127.0.0.1", port, timeout=5.0)


def test_no_bridge_gives_a_plain_hint():
    with pytest.raises(NisConnectionError, match="start_bridge.mac"):
        NisClient("127.0.0.1", 1, timeout=1.0)


# -- the macro and the NIS side --------------------------------------------------------


def test_macro_carries_the_path_and_port(tmp_path):
    text = install_macros.render(Path(r"C:\code\nis_bridge"), r"C:\code\b.stop", 5000)
    assert r"p = r'C:\\code\\nis_bridge'" in text and "b.start(port=5000)" in text
    assert 'ExistFile("C:\\\\code\\\\b.stop")' in text
    # NIS silently refuses macros with comments or string variables
    assert not any(line.startswith(("//", "char ")) for line in text.splitlines())

    path = install_macros.install(tmp_path, port=6000)
    text = path.read_text()
    assert b"\r\n" in path.read_bytes() and "nis_bridge.bridge as b" in text
    assert "importlib.reload(p)" in text  # the protocol too, or a changed version stays cached


def test_macro_lifecycle_start_reload_stop(monkeypatch, tmp_path):
    """What start_bridge.mac does: start, pump, reload the module, stop."""
    monkeypatch.setattr(bridge, "NisApi", FakeNisApi)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))  # where the bridge log goes
    try:
        assert "listening" in bridge.start(port=0)
        bridge.pump(0)
        assert "already running" in bridge.start(port=0)
        server = bridge._running["server"]
        reloaded = importlib.reload(bridge)  # the macro reloads to pick up code changes
        assert reloaded._running["server"] is server
        server.request_stop()  # what a client's "shutdown" request does
        reloaded.pump(0)
        assert os.path.exists(reloaded.STOP_FILE)  # this ends the macro loop
    finally:
        assert importlib.import_module("nis_bridge.bridge").stop() == "bridge stopped"
    assert not os.path.exists(bridge.STOP_FILE)
    assert (tmp_path / "nis-bridge.log").exists() and not bridge.log.handlers


def test_bridge_needs_only_the_standard_library():
    """NIS-Elements' Python has numpy and nothing else; the bridge must not need even that."""
    code = (
        "import sys\n"
        "for name in ('numpy', 'useq', 'tifffile', 'pymmcore_plus'): sys.modules[name] = None\n"
        "import nis_bridge.bridge, nis_bridge.install_macros\n"
    )
    project = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=project, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_the_start_macro_needs_an_editable_install(monkeypatch, tmp_path):
    monkeypatch.setattr(install_macros, "PROJECT_DIR", tmp_path)  # as in site-packages
    with pytest.raises(SystemExit, match="pip install -e"):
        install_macros.install(tmp_path)
    assert not (tmp_path / "start_bridge.mac").exists()


def test_the_fake_refuses_a_move_beyond_the_stage_limits(client, fake):
    with pytest.raises(RuntimeError, match="outside the stage limits"):
        client.request("move", z=20000)
    assert fake.position["z"] == 500.0
