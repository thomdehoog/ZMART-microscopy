"""The ZMART controller contract, end to end over the offline fake ZEN API."""

import pytest
from mock_zen_api import FakeGRPCError, build_fake_client
from zenapi import zen_zmart_adapter as adapter


@pytest.fixture
def scope_box(monkeypatch):
    """Swap the gateway connection for the fake; the box hands the scope to the test."""
    box = {}

    def _fake_open(connection):
        client, scope = build_fake_client()
        box["scope"] = scope
        scope.image_output_folder = connection["_zen_folder"]
        return client

    monkeypatch.setattr(adapter, "_open_client", _fake_open)
    return box


@pytest.fixture
def connection(tmp_path):
    return {
        "vendor": "zeiss",
        "microscope": "test-scope",
        "api": "zen-api",
        "config": "unused.ini",
        "output_root": str(tmp_path / "out"),
        "machine_root": str(tmp_path / "programdata"),
        "_zen_folder": str(tmp_path / "zen_images"),
    }


@pytest.fixture
def handle(scope_box, connection):
    h = adapter.connect(connection)
    try:
        yield h
    finally:
        adapter.disconnect(h)


def test_ops_table_is_complete():
    from zmart_controller.registry import OPS

    assert set(OPS) <= set(adapter.OPS)


def test_connect_copies_default_limits_and_reads_identity(handle, connection, tmp_path):
    limits_file = tmp_path / "programdata" / "zeiss" / "test-scope" / "stage_limits.json"
    assert limits_file.exists()
    assert handle.limits_are_defaults is True
    assert handle.limits["x"]["max"] == 60000.0
    assert handle.immutable["app"] == "ZEN"
    assert [o["index"] for o in handle.immutable["objectives"]] == [1, 2, 3]


def test_origin_shifts_frame_and_persists(scope_box, connection):
    h = adapter.connect(connection)
    scope_box["scope"].x_m, scope_box["scope"].y_m, scope_box["scope"].z_m = 1e-3, -2e-3, 5e-5
    assert adapter.get_xyz(h)["x"]["value"] == pytest.approx(1000.0)
    rec = adapter.set_origin(h)
    assert rec["origin"] == pytest.approx({"x": 1000.0, "y": -2000.0, "z": 50.0})
    assert adapter.get_xyz(h)["x"]["value"] == 0.0
    adapter.disconnect(h)

    h2 = adapter.connect(connection)  # a new session restores the persisted origin
    assert h2.origin == pytest.approx(rec["origin"])
    adapter.disconnect(h2)


def test_set_xyz_maps_through_origin_and_confirms(handle, scope_box):
    scope = scope_box["scope"]
    scope.x_m, scope.y_m, scope.z_m = 1e-3, 1e-3, 1e-4
    adapter.set_origin(handle)
    rec = adapter.set_xyz(handle, 10, 20, -50)
    assert scope.x_m == pytest.approx(1010e-6)
    assert scope.y_m == pytest.approx(1020e-6)
    assert scope.z_m == pytest.approx(50e-6)
    assert rec["confirmed"] == pytest.approx({"x": 10.0, "y": 20.0, "z": -50.0})
    assert rec["actuators"] == {"x": "motoric", "y": "motoric", "z": "motoric"}


def test_set_xyz_outside_limits_is_a_runtime_error(handle, scope_box):
    with pytest.raises(RuntimeError, match="set_xyz refused"):
        adapter.set_xyz(handle, 0, 0, 99999)
    assert scope_box["scope"].calls == []  # refused before ZEN was asked


def test_set_xyz_rpc_failure_is_a_runtime_error(handle, scope_box):
    scope_box["scope"].errors["stage_move"] = FakeGRPCError(
        "FAILED_PRECONDITION", "not in API mode"
    )
    with pytest.raises(RuntimeError, match="FAILED_PRECONDITION"):
        adapter.set_xyz(handle, 1, 1, 1)


def test_state_round_trip(handle, scope_box):
    state = adapter.get_state(handle)
    assert state["changeable"] == {"objective_position": 1, "experiment": None}
    assert state["observed"]["available_experiments"] == ["ZMART_Snap", "ZMART_ZStack"]
    assert state["observed"]["busy"] is False
    applied = adapter.set_state(
        handle, {"changeable": {"objective_position": 3, "experiment": "ZMART_Snap"}}
    )
    assert applied == {"applied": {"objective_position": 3, "experiment": "ZMART_Snap"}}
    assert scope_box["scope"].objective_index == 3
    assert adapter.get_state(handle)["changeable"]["experiment"] == "ZMART_Snap"


def test_acquire_needs_an_experiment(handle):
    with pytest.raises(ValueError, match="needs a loaded ZEN experiment"):
        adapter.acquire(handle, acquisition_type="snap", position_label="a")


def test_acquire_snap_copies_czi_into_data_folder(handle, scope_box, tmp_path):
    adapter.set_state(handle, {"changeable": {"experiment": "ZMART_Snap"}})
    rec = adapter.acquire(
        handle, acquisition_type="overview", position_label="tile 3/a", options={"timeout_s": 2}
    )
    dst = tmp_path / "out" / "data" / "overview_tile_3_a.czi"
    assert rec["image_files"] == [str(dst)] and dst.exists()
    assert rec["copied"] is True and rec["mode"] == "snap"
    assert rec["zen_image_path"] == str(tmp_path / "zen_images" / "overview_tile_3_a.czi")
    assert scope_box["scope"].calls[-1] == ("run_snap", "exp::ZMART_Snap", "overview_tile_3_a")


def test_acquire_stack_runs_the_whole_experiment(handle, scope_box):
    rec = adapter.acquire(
        handle,
        acquisition_type="z-stack",
        position_label="p1",
        options={"experiment": "ZMART_ZStack"},
    )
    assert rec["mode"] == "experiment" and rec["experiment"] == "ZMART_ZStack"
    assert scope_box["scope"].calls[-1][0] == "run_experiment"


def test_acquire_leaves_czi_on_zen_when_folder_unreachable(handle, scope_box, tmp_path):
    scope_box["scope"].image_output_folder = str(tmp_path / "not_mounted_share")
    scope_box["scope"]._write_czi = lambda name: None  # ZEN wrote it where we cannot see
    adapter.set_state(handle, {"changeable": {"experiment": "ZMART_Snap"}})
    rec = adapter.acquire(
        handle, acquisition_type="snap", position_label="x", options={"timeout_s": 0.05}
    )
    assert rec["copied"] is False
    assert rec["image_files"] == [rec["zen_image_path"]]


def test_procedures(handle, scope_box):
    procs = adapter.get_procedures(handle)
    assert {"software_autofocus", "find_surface", "live", "stop"} <= set(procs)
    with pytest.raises(ValueError, match="needs a loaded ZEN experiment"):
        adapter.run_procedure(handle, {"name": "software_autofocus"})
    adapter.set_state(handle, {"changeable": {"experiment": "ZMART_Snap"}})
    af = adapter.run_procedure(handle, {"name": "software_autofocus", "timeout_s": 5})
    assert af["focus_um"] == pytest.approx(135.0) and af["frame_z_um"] == pytest.approx(135.0)
    fs = adapter.run_procedure(handle, {"name": "find_surface"})
    assert fs["focus_um"] == pytest.approx(120.0)
    assert adapter.run_procedure(handle, {"name": "live"})["ran"] == "live"
    assert adapter.run_procedure(handle, {"name": "stop"})["experiment_id"] == "exp::ZMART_Snap"
    with pytest.raises(ValueError, match="unknown procedure"):
        adapter.run_procedure(handle, {"name": "teleport"})


def test_ops_refuse_after_disconnect(scope_box, connection):
    h = adapter.connect(connection)
    adapter.disconnect(h)
    with pytest.raises(RuntimeError, match="disconnected"):
        adapter.get_xyz(h)


def test_registered_with_controller():
    from zmart_controller import registry

    adapter.register()
    assert any(c["vendor"] == "zeiss" for c in registry.get_instruments())
