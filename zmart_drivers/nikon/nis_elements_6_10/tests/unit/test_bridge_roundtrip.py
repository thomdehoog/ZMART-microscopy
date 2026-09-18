"""Client <-> real bridge server <-> fake NIS: every operation, and the refusals."""

import pytest
from nis_elements_6_10.commands import commands as cmd
from nis_elements_6_10.commands.commands import LimitError
from nis_elements_6_10.connection.client import NisClient, NisConnectionError
from nis_elements_6_10.readers import readers


def test_ping_reports_versions(client):
    info = readers.get_bridge_info(client)
    assert info["nis"].startswith("6.10") and info["protocol"] == 1


def test_position_and_limits(client):
    assert readers.get_position(client) == {"x": 39904.7, "y": -13433.1, "z": 500.0}
    limits = readers.get_limits(client)
    assert limits["x"] == {"min": -57000.0, "max": 57000.0} and limits["z"]["max"] == 10000.0


def test_move_xyz_reports_new_position(client, fake_api):
    assert cmd.move_xyz(client, 100, -200, 1500) == {"x": 100.0, "y": -200.0, "z": 1500.0}
    assert fake_api.calls == ["move_xyz(100.0,-200.0,1500.0)"]


def test_move_outside_nis_limits_is_refused_before_reaching_nis(client, fake_api):
    with pytest.raises(LimitError, match="z = 20000.0 um is outside"):
        cmd.move_xyz(client, 0, 0, 20000)
    assert fake_api.calls == []


def test_objectives_listed_and_selectable(client, fake_api):
    objectives = readers.get_objectives(client)
    assert objectives["current"] == 4
    # the empty slot 6 is dropped from the list
    assert [o["position"] for o in objectives["objectives"]] == [1, 2, 3, 4, 5]
    assert cmd.set_objective(client, 2) == 2 and fake_api.nosepiece == 2


def test_bad_objective_position_is_a_value_error(client):
    with pytest.raises(ValueError, match="position"):
        client.request("set_objective", position="two")


def test_nis_refusal_arrives_as_runtime_error(client):
    with pytest.raises(RuntimeError, match="DR_BADPARAMETER"):
        cmd.set_objective(client, 9)


def test_optical_configuration_must_exist(client, fake_api):
    assert cmd.select_optical_configuration(client, "FITC") == "FITC"
    assert fake_api.selected_configuration == "FITC"
    with pytest.raises(ValueError, match="unknown optical configuration"):
        cmd.select_optical_configuration(client, "Nope")


def test_capture_then_save_writes_file_and_closes_document(client, fake_api, tmp_path):
    info = cmd.capture(client)
    assert info["width"] == 2048 and fake_api.open_documents == 1
    target = tmp_path / "data" / "snap.tif"
    saved = cmd.save_image(client, str(target), format="tif")
    assert target.exists() and saved["bytes"] > 0
    assert fake_api.saved[0][1] == 18  # ImageSaveAs "all layers, TIFF"
    assert fake_api.open_documents == 0


def test_save_nd2_uses_nikon_type(client, fake_api, tmp_path):
    cmd.capture(client)
    cmd.save_image(client, str(tmp_path / "snap.nd2"), format="nd2", close=False)
    assert fake_api.saved[0][1] == 14 and fake_api.open_documents == 1


def test_unknown_op_is_refused(client):
    with pytest.raises(ValueError, match="unknown op"):
        client.request("run_macro", text="StgMoveXY(0,0,0);")


def test_connect_without_bridge_gives_plain_hint():
    with pytest.raises(NisConnectionError, match="start_bridge.mac"):
        NisClient("127.0.0.1", 1, timeout=0.5).connect()


def test_two_clients_are_served_in_turn(bridge):
    a = NisClient("127.0.0.1", bridge.server_address[1])
    b = NisClient("127.0.0.1", bridge.server_address[1])
    a.connect()
    b.connect()
    try:
        assert a.request("get_position") == b.request("get_position")
    finally:
        a.close()
        b.close()


def test_without_a_pump_requests_time_out_with_a_hint(fake_api):
    """Inside NIS the macro loop pumps; if it is not running, the client learns why."""
    from nis_elements_6_10.bridge import nis_bridge

    server = nis_bridge.serve(fake_api, "127.0.0.1", 0)  # no pump thread
    server.job_timeout = 0.2
    c = NisClient("127.0.0.1", server.server_address[1], timeout=5.0)
    try:
        with pytest.raises(RuntimeError, match="start_bridge.mac"):
            c.connect()  # connect() pings, and the ping has nobody to run it
    finally:
        c.close()
        server.shutdown()
        server.server_close()


def test_shutdown_op_marks_stop_requested(client, bridge):
    assert client.request("shutdown") == {"stopping": True}
    assert bridge.stop_requested
