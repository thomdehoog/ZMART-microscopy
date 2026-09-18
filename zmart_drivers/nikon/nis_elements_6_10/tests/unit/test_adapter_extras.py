"""The controller contract for the extras: piezo actuator, state, procedures, stacks."""

import pytest
from nis_elements_6_10 import nis_zmart_adapter as adapter


@pytest.fixture
def handle(connection):
    h = adapter.connect(connection)
    try:
        yield h
    finally:
        adapter.disconnect(h)


def test_piezo_is_a_second_z_actuator(handle, fake_api):
    assert adapter.get_actuators(handle) == {
        "x": ["motoric"],
        "y": ["motoric"],
        "z": ["motoric", "piezo"],
    }
    adapter.set_origin(handle)  # piezo origin = 50.0
    rec = adapter.set_xyz(handle, 10, 0, 7, with_actuators={"z": "piezo"})
    assert rec["actuators"]["z"] == "piezo"
    # the piezo took the z target; the focus drive was left alone
    assert fake_api.piezo_z == pytest.approx(57.0) and fake_api.position["z"] == 500.0
    assert rec["confirmed"]["z"] == pytest.approx(7.0)
    assert adapter.get_xyz(handle, with_actuators={"z": "piezo"})["z"]["value"] == pytest.approx(
        7.0
    )
    assert adapter.get_xyz(handle)["z"]["value"] == 0.0  # default stays the focus drive


def test_no_piezo_means_no_piezo_actuator(connection, fake_api):
    fake_api.has_piezo = False
    h = adapter.connect(connection)
    assert adapter.get_actuators(h)["z"] == ["motoric"]
    with pytest.raises(ValueError, match="unknown actuator"):
        adapter.get_xyz(h, with_actuators={"z": "piezo"})
    adapter.disconnect(h)


def test_state_covers_exposure_and_pfs(handle, fake_api):
    state = adapter.get_state(handle)
    assert state["changeable"] == {"objective_position": 4, "exposure_ms": 100.0, "pfs": False}
    assert state["observed"]["pfs"]["present"] is True
    applied = adapter.set_state(handle, {"changeable": {"exposure_ms": 30, "pfs": True}})
    assert applied == {"applied": {"exposure_ms": 30.0, "pfs": True}}
    assert fake_api.pfs_on is True


def test_procedures(handle, fake_api):
    names = set(adapter.get_procedures(handle))
    assert names == {"autofocus", "live", "freeze", "pfs_on", "pfs_off"}
    adapter.set_origin(handle)
    result = adapter.run_procedure(handle, {"name": "autofocus", "range_um": 20})
    assert result["frame_z_um"] == pytest.approx(3.0)
    assert result["focus_um"] == pytest.approx(503.0)
    assert adapter.run_procedure(handle, {"name": "pfs_off"})["pfs"]["on"] is False
    adapter.run_procedure(handle, {"name": "live"})
    assert fake_api.is_live
    with pytest.raises(ValueError, match="unknown procedure"):
        adapter.run_procedure(handle, {"name": "make_coffee"})


def test_acquire_stack_saves_nd2(handle, fake_api, tmp_path):
    adapter.set_origin(handle)
    rec = adapter.acquire(
        handle,
        acquisition_type="z_stack",
        position_label="p1",
        options={"z_start": -10, "z_end": 10, "z_step": 2, "format": "nd2", "exposure_ms": 12},
    )
    assert rec["planes"] == 11 and fake_api.z_series == (510.0, 490.0, 2.0, 11)
    assert rec["image_files"] == [str(tmp_path / "out" / "data" / "z_stack_p1.nd2")]
    assert fake_api.exposure_ms == 12.0


def test_acquire_stack_needs_a_range(handle):
    with pytest.raises(ValueError, match="z_start"):
        adapter.acquire(handle, acquisition_type="stack", position_label="p1")
