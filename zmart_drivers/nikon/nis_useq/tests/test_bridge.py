"""Client <-> real bridge server <-> fake NIS: each operation, and each refusal."""

from pathlib import Path

import pytest
import tifffile
from nis_useq import bridge, install_macros
from nis_useq.client import NisClient, NisConnectionError
from nis_useq.protocol import decode_reply


def test_ping_reports_versions(client):
    assert client.info["nis"].startswith("6.10") and client.info["protocol"] == 1


def test_move_only_the_given_axes(client, fake):
    assert client.request("move", z=800) == {"x": 1000.0, "y": -500.0, "z": 800.0}
    client.request("move", x=10)  # y is kept, z untouched
    client.request("move", x=1, y=2, z=3)
    assert fake.calls == ["move_z(800)", "move_xy(10,-500)", "move_xyz(1,2,3)"]


def test_move_needs_an_axis(client):
    with pytest.raises(ValueError, match="at least one"):
        client.request("move")


def test_unknown_op_and_bad_json_are_value_errors(client, server):
    with pytest.raises(ValueError, match="unknown op 'fly'"):
        client.request("fly")
    with pytest.raises(ValueError, match="not valid JSON"):
        decode_reply(server.handle_line("{nope"))


def test_optical_configuration_must_exist(client, fake):
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


def test_exposure_must_be_positive(client, fake):
    client.request("set_exposure", exposure_ms=20)
    with pytest.raises(ValueError, match="positive"):
        client.request("set_exposure", exposure_ms=0)
    assert fake.calls == ["exposure(20)"]


def test_snap_saves_a_tiff_and_closes_the_image(client, fake, tmp_path):
    path = tmp_path / "snap.tif"
    info = client.request("snap", path=str(path))
    assert info["width"] == 64 and info["pixel_size_um"] is None
    assert tifffile.imread(path).max() == 1 and fake.open_images == 0


def test_snap_reports_the_calibration(client, fake, tmp_path):
    fake.calibrated = True
    assert client.request("snap", path=str(tmp_path / "a.tif"))["pixel_size_um"] == 0.108


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


def test_request_times_out_when_the_macro_loop_is_not_running(fake):
    srv = bridge.serve(fake, "127.0.0.1", 0)  # nobody pumps
    srv.job_timeout_s = 0.2
    try:
        with pytest.raises(RuntimeError, match="start_bridge.mac"):
            NisClient("127.0.0.1", srv.server_address[1], timeout=5.0)
    finally:
        srv.shutdown()
        srv.server_close()


def test_no_bridge_gives_a_plain_hint(unused_port=1):
    with pytest.raises(NisConnectionError, match="start_bridge.mac"):
        NisClient("127.0.0.1", unused_port, timeout=1.0)


def test_macros_carry_the_path_and_port(tmp_path):
    start, stop = install_macros.render(Path(r"C:\code\nis_useq"), r"C:\code\b.stop", 5000)
    assert r"p = r'C:\\code\\nis_useq'" in start and "b.start(port=5000)" in start
    assert 'ExistFile("C:\\\\code\\\\b.stop")' in start and r"C:\\code\\b.stop" in stop
    # NIS silently refuses macros with comments or string variables
    assert not any(line.startswith(("//", "char ")) for line in start.splitlines())

    start_path, _ = install_macros.install(tmp_path, port=6000)
    assert b"\r\n" in start_path.read_bytes() and "nis_useq.bridge as b" in start_path.read_text()


def test_macro_lifecycle_start_reload_stop(monkeypatch):
    """What start_bridge.mac does: start, pump, reload the module, stop."""
    import importlib
    import os

    from fake_nis import FakeNisApi

    monkeypatch.setattr(bridge, "NisApi", FakeNisApi)
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
        assert importlib.import_module("nis_useq.bridge").stop() == "bridge stopped"
    assert not os.path.exists(bridge.STOP_FILE)


def test_bridge_needs_only_the_standard_library():
    """NIS-Elements' Python has numpy and nothing else; the bridge must not need even that."""
    import subprocess
    import sys

    code = (
        "import sys\n"
        "for name in ('numpy', 'useq', 'tifffile', 'pymmcore_plus'): sys.modules[name] = None\n"
        "import nis_useq.bridge, nis_useq.install_macros\n"
    )
    project = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=project, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
