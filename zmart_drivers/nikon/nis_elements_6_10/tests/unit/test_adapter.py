"""The ZMART controller contract, end to end through the fake bridge."""

import pytest
from nis_elements_6_10 import nis_zmart_adapter as adapter


@pytest.fixture
def handle(connection):
    h = adapter.connect(connection)
    try:
        yield h
    finally:
        adapter.disconnect(h)


def test_ops_table_is_complete():
    from zmart_controller.registry import OPS

    assert set(OPS) <= set(adapter.OPS)


def test_connect_reads_limits_and_identity(handle):
    assert handle.limits["x"]["max"] == 57000.0
    assert handle.immutable["version"].startswith("6.10")
    assert handle.immutable["devices"]["xy"] is True


def test_origin_shifts_frame_and_persists(connection, fake_api):
    h = adapter.connect(connection)
    assert adapter.get_xyz(h)["x"]["value"] == pytest.approx(39904.7)
    rec = adapter.set_origin(h)
    assert rec["origin"] == {"x": 39904.7, "y": -13433.1, "z": 500.0}
    assert adapter.get_xyz(h)["x"]["value"] == 0.0
    adapter.disconnect(h)

    h2 = adapter.connect(connection)  # a new session restores the persisted origin
    assert h2.origin == rec["origin"]
    adapter.disconnect(h2)


def test_set_xyz_maps_through_origin_and_confirms(handle, fake_api):
    adapter.set_origin(handle)
    rec = adapter.set_xyz(handle, 10, 20, -100)
    assert fake_api.position == pytest.approx({"x": 39914.7, "y": -13413.1, "z": 400.0})
    assert rec["confirmed"] == pytest.approx({"x": 10.0, "y": 20.0, "z": -100.0})


def test_set_xyz_outside_limits_is_a_runtime_error(handle, fake_api):
    with pytest.raises(RuntimeError, match="set_xyz refused"):
        adapter.set_xyz(handle, 0, 0, 99999)
    assert fake_api.calls == []


def test_state_round_trip(handle, fake_api):
    state = adapter.get_state(handle)
    assert state["changeable"] == {"objective_position": 4, "exposure_ms": 100.0, "pfs": False}
    assert "DAPI" in state["observed"]["optical_configurations"]
    applied = adapter.set_state(
        handle, {"changeable": {"objective_position": 1, "optical_configuration": "DAPI"}}
    )
    assert applied == {"applied": {"optical_configuration": "DAPI", "objective_position": 1}}
    assert fake_api.nosepiece == 1 and fake_api.selected_configuration == "DAPI"


def test_acquire_saves_into_data_folder(handle, fake_api, tmp_path):
    rec = adapter.acquire(
        handle,
        acquisition_type="overview",
        position_label="tile 3/a",
        options={"optical_configuration": "FITC"},
    )
    path = tmp_path / "out" / "data" / "overview_tile_3_a.tif"
    assert rec["image_files"] == [str(path)] and path.exists()
    assert rec["planes"] == 1 and fake_api.selected_configuration == "FITC"
    assert fake_api.open_documents == 0


def test_acquire_bad_format_is_a_value_error(handle):
    with pytest.raises(ValueError, match="unknown format"):
        adapter.acquire(handle, acquisition_type="a", position_label="b", options={"format": "png"})


def test_ops_refuse_after_disconnect(connection):
    h = adapter.connect(connection)
    adapter.disconnect(h)
    with pytest.raises(RuntimeError, match="disconnected"):
        adapter.get_xyz(h)


def test_registered_with_controller():
    from zmart_controller import registry

    adapter.register()
    assert any(c["vendor"] == "nikon" for c in registry.get_instruments())
