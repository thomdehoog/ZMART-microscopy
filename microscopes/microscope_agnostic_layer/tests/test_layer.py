"""Tests for the microscope-agnostic layer against the mock driver."""

from __future__ import annotations

import pytest
from microscope_agnostic_layer import connect


@pytest.fixture
def mic():
    session = connect(vendor="mock")
    yield session
    session.disconnect()


class TestConnect:
    def test_defaults_resolve(self, mic):
        assert mic.context["microscope"] == "mock-scope"
        assert mic.context["api"] == "mock-api"
        assert mic.context["objective"] == "10x"
        assert mic.context["stage_type"] == "motoric"

    def test_capabilities_discovered(self, mic):
        caps = mic.capabilities
        assert caps["objective"]["active"] == "10x"
        assert "ome-zarr" in caps["save_format"]["options"]
        assert caps["stages"]["z"]["options"] == ["motoric", "piezo"]

    def test_unknown_vendor(self):
        with pytest.raises(ValueError, match="unknown vendor"):
            connect(vendor="nope")

    def test_unknown_microscope(self):
        with pytest.raises(ValueError, match="no driver"):
            connect(vendor="mock", microscope="ghost")


class TestCoordinates:
    def test_set_get_roundtrip_10x_no_offset(self, mic):
        mic.set_xyz(10, 20, 5)
        pos = mic.get_xyz()
        assert (pos["x"]["value"], pos["y"]["value"], pos["z"]["value"]) == (10, 20, 5)
        assert pos["x"]["unit"] == "um"

    def test_objective_offset_applied_by_driver(self):
        mic = connect(vendor="mock", objective="20x")
        mic.set_xyz(0, 0, 0)
        pos = mic.get_xyz()
        assert pos["x"]["value"] == 1.5
        assert pos["y"]["value"] == -0.8

    def test_stage_selector_reported_back(self, mic):
        pos = mic.get_xyz(stages={"z": "piezo"})
        assert pos["z"]["stage"] == "piezo"
        assert pos["x"]["stage"] == "motoric"  # untouched axes use the active frame


class TestAcquireSave:
    def test_acquire_backlash_default_on(self, mic):
        assert mic.acquire()["settle"] == "backlash-corrected"

    def test_acquire_backlash_off(self, mic):
        assert mic.acquire(backlash_correction=False)["settle"] == "direct"

    def test_save_defaults_to_active(self, mic):
        mic.acquire()
        out = mic.save()
        assert out["format"] == "ome-tiff"
        assert out["procedure"] == "direct"

    def test_save_override(self, mic):
        mic.acquire()
        out = mic.save(format="ome-zarr", procedure="tiled", name="well_A1")
        assert out["format"] == "ome-zarr"
        assert out["procedure"] == "tiled"
        assert out["name"] == "well_A1"

    def test_save_without_acquire_raises(self, mic):
        with pytest.raises(RuntimeError):
            mic.save()


class TestState:
    def test_state_split_into_mutable_immutable(self, mic):
        state = mic.get_state()
        assert set(state) == {"immutable", "mutable"}
        assert "serial" in state["immutable"]
        assert "laser_power" in state["mutable"]

    def test_capture_and_reactivate(self, mic):
        original = mic.get_state()
        mic.set_state({"mutable": {"laser_power": 99.0}})
        assert mic.get_state()["mutable"]["laser_power"] == 99.0
        mic.set_state(original)  # reactivate the captured state
        assert mic.get_state()["mutable"]["laser_power"] == original["mutable"]["laser_power"]

    def test_immutable_mismatch_rejected(self, mic):
        with pytest.raises(ValueError, match="different instrument"):
            mic.set_state({"immutable": {"serial": "OTHER"}, "mutable": {}})

    def test_immutable_not_settable(self, mic):
        serial = mic.get_state()["immutable"]["serial"]
        mic.set_state({"immutable": {"serial": serial}, "mutable": {"gain": 3.0}})
        assert mic.get_state()["immutable"]["serial"] == serial  # unchanged
        assert mic.get_state()["mutable"]["gain"] == 3.0


class TestFlexibleDicts:
    def test_procedure_roundtrip(self, mic):
        mic.set_procedure({"name": "zstack", "steps": [1, 2, 3]})
        assert mic.get_procedure() == {"name": "zstack", "steps": [1, 2, 3]}

    def test_initial_positions(self, mic):
        positions = mic.get_initial_positions()
        assert isinstance(positions, list)
        assert len(positions) == 3
        assert positions[0] == {"x": 0.0, "y": 0.0, "z": 0.0}
