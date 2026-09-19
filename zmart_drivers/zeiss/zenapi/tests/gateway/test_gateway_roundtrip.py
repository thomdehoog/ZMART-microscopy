"""The driver over the real zen_api wheel and a real TLS connection to the fake gateway.

Only the microscope is fake: request and response messages are the generated
ZEISS classes, the transport is grpclib over TLS, and the token check is the
gateway's. The round-trip checks are shared with the hardware suite.
"""

import pytest
import zenapi as drv
from roundtrip_checks import (
    check_experiment_run,
    check_motion,
    check_objective_switch,
    check_reads,
    check_started_experiment_can_be_monitored,
)
from zenapi.simulator.fake_gateway import CONTROLLING_DENIED


def test_connect_records_runtime(client):
    assert client.runtime["zen_api_version"]
    assert client.runtime["services"]["stage"].endswith("StageServiceStub")
    assert "unavailable" not in client.runtime["services"]["experiment"]


def test_reads(client):
    reads = check_reads(client)
    assert reads["objectives"][0]["name"].startswith("Plan-Apochromat")


def test_motion(client, gateway):
    check_motion(client)
    focus_targets = [c[1] for c in gateway.zen.calls if c[0] == "focus.move_to"]
    assert focus_targets[0] == pytest.approx(10e-6)


def test_objective_switch(client):
    check_objective_switch(client)


def test_snap_and_experiment(client, gateway):
    snap = check_experiment_run(client, "ZMART_Snap", output_name="snap_01", mode="snap")
    assert snap["acquisition"].command_result["status"]["images_count"] == 1
    stack = check_experiment_run(client, "ZMART_ZStack", output_name="stack_01", mode="experiment")
    assert stack["acquisition"].command_result["status"]["images_count"] == 5
    assert stack["czi"].read_bytes().startswith(b"ZISRAWFILE")


def test_started_experiment_is_monitored(client, gateway):
    gateway.zen.frame_time_s = 0.02
    updates = check_started_experiment_can_be_monitored(
        client, "ZMART_Tiles", output_name="tiles_01"
    )
    assert updates[-1]["images_acquired_index"] == 4


def test_monitor_after_the_experiment_finished_raises(client):
    """ZEN documents that subscribing after the end throws; the fake does the same."""
    from grpclib import GRPCError

    exp = drv.load_experiment(client, "ZMART_Snap")
    drv.run_snap(client, exp, output_name="done")
    with pytest.raises(GRPCError):
        list(drv.monitor(client, exp))


def test_focus_procedures(client):
    exp = drv.load_experiment(client, "ZMART_Snap")
    assert drv.find_autofocus(client, exp, timeout_s=5)["z_um"] == pytest.approx(135.0)
    assert drv.find_surface(client)["z_um"] == pytest.approx(120.0)
    assert drv.store_focus(client)["success"]
    drv.move_z(client, 500)
    assert drv.recall_focus(client)["z_um"] == pytest.approx(120.0)


def test_out_of_range_move_is_a_permanent_failure(client, gateway):
    r = drv.move_xy(client, 90000, 0)
    assert r["success"] is False
    assert "OUT_OF_RANGE" in r["message"]
    assert r["timing"]["attempts"] == 1  # permanent: not retried
    assert gateway.zen.x_m == 0.0


def test_unknown_experiment_is_not_found(client):
    from grpclib import GRPCError

    with pytest.raises(GRPCError, match="does not exist"):
        drv.load_experiment(client, "nope")


def test_save_copies_the_czi(client, tmp_path):
    from zenapi.acquisition.naming import Naming, run_hash

    exp = drv.load_experiment(client, "ZMART_2CH")
    acq = drv.acquire(client, exp, mode="snap", output_name="two_channels")
    naming = Naming(acquisition_type="snap", hash6=run_hash(), position_label="p1")
    saved = drv.save(client, acq, tmp_path / "run", naming, stable_poll_s=0.05)
    assert saved.czi_path.exists()
    assert saved.czi_path.parent == tmp_path / "run" / "snap" / "data"


def test_wrong_token_is_refused(gateway):
    cfg = gateway.config()
    with pytest.raises(ConnectionError, match="control token"):
        drv.connect(**{**cfg, "control_token": "not-the-token"})


def test_missing_token_is_refused(gateway):
    cfg = gateway.config()
    with pytest.raises(ConnectionError):
        drv.connect(**{**cfg, "control_token": " "})


def test_supervised_mode_allows_reads_but_refuses_moves(client, gateway):
    gateway.zen.supervised = True
    assert drv.get_xy(client)["x_um"] == 0.0  # monitoring: still allowed
    r = drv.move_xy(client, 10, 10)
    assert r["success"] is False
    assert CONTROLLING_DENIED in r["message"]
    assert "PERMISSION_DENIED" in r["message"]


def test_config_ini_round_trip(config_ini, gateway):
    from zenapi.connection import zen_runtime

    cfg = zen_runtime.load_config(config_ini)
    assert cfg["port"] == gateway.port
    assert cfg["control_token"] == gateway.control_token
    assert cfg["cert_file"] == str(gateway.cert_file)


def test_second_start_of_the_same_experiment_is_a_fresh_run(client, gateway):
    """The fake must not answer a new start with the previous run's final status."""
    gateway.zen.frame_time_s = 0.02
    exp = drv.load_experiment(client, "ZMART_ZStack")
    drv.start_experiment(client, exp, output_name="run_a")
    updates_a = list(drv.monitor(client, exp))
    drv.start_experiment(client, exp, output_name="run_b")
    status = drv.get_status(client, exp)
    assert status["is_experiment_running"] is True
    updates_b = list(drv.monitor(client, exp))
    assert updates_a[-1]["is_experiment_running"] is False
    assert updates_b[0]["is_experiment_running"] is True
    assert updates_b[-1]["is_experiment_running"] is False


def test_starting_a_running_experiment_is_refused(client, gateway):
    from grpclib import GRPCError

    gateway.zen.frame_time_s = 0.05
    exp = drv.load_experiment(client, "ZMART_Tiles")
    drv.start_experiment(client, exp, output_name="busy")
    with pytest.raises(GRPCError, match="already running"):
        drv.start_experiment(client, exp, output_name="again")
    drv.stop(client, exp)


def test_gateway_can_be_stopped_and_started_again(tmp_path):
    from zenapi.simulator import FakeGateway

    gw = FakeGateway(tmp_path / "again")
    gw.start()
    gw.stop()
    gw.port = 0
    gw.start()
    try:
        assert gw.port  # a new free port was picked and is open
        c = drv.connect(**gw.config())
        assert drv.ping(c)
        drv.close(c)
    finally:
        gw.stop()
