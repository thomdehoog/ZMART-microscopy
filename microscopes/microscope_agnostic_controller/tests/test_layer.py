"""Tests for the Microscope Agnostic Controller against the mock driver.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import pytest
from microscope_agnostic_controller import get_instruments, set_instrument

# Reference actuators for the mock: motoric on every axis.
MOTORIC = {"x": "motoric", "y": "motoric", "z": "motoric"}


@pytest.fixture
def mic():
    instrument = get_instruments()[0]
    session = set_instrument(instrument, reference_actuators=MOTORIC, reference_objective="10x")
    yield session
    session.disconnect()


class TestInstruments:
    def test_lists_with_options(self):
        inst = next(i for i in get_instruments() if i["connection"]["vendor"] == "mock")
        assert inst["connection"]["microscope"] == "mock-scope"
        assert inst["connection"]["api"] == "mock-api"
        assert "10x" in inst["objectives"]
        assert "motoric" in inst["actuators"]["x"]


class TestSetInstrument:
    def test_context_resolves(self, mic):
        assert mic.context == {"vendor": "mock", "microscope": "mock-scope", "api": "mock-api"}

    def test_connection_reaches_driver(self, mic):
        # the variable connection dict is forwarded untouched to the driver's connect()
        assert mic.get_context()["client"] == "mock-client"

    def test_unknown_vendor_raises(self):
        with pytest.raises(ValueError, match="no driver registered"):
            set_instrument(
                {"connection": {"vendor": "nope", "microscope": "x", "api": "y"}},
                reference_actuators=MOTORIC,
                reference_objective="10x",
            )

    def test_unknown_objective_raises(self):
        inst = get_instruments()[0]
        with pytest.raises(ValueError, match="unknown objective"):
            set_instrument(inst, reference_actuators=MOTORIC, reference_objective="999x")

    def test_unknown_actuator_raises(self):
        inst = get_instruments()[0]
        with pytest.raises(ValueError, match="unknown actuator"):
            set_instrument(
                inst, reference_actuators={"z": "hovercraft"}, reference_objective="10x"
            )


class TestCoordinates:
    def test_set_get_roundtrip_10x_no_offset(self, mic):
        mic.set_xyz(10, 20, 5)
        pos = mic.get_xyz()
        assert (pos["x"]["value"], pos["y"]["value"], pos["z"]["value"]) == (10, 20, 5)
        assert pos["x"]["unit"] == "um"

    def test_objective_offset_applied_by_driver(self):
        inst = get_instruments()[0]
        mic = set_instrument(inst, reference_actuators=MOTORIC, reference_objective="20x")
        mic.set_xyz(0, 0, 0)
        pos = mic.get_xyz()
        assert pos["x"]["value"] == 1.5
        assert pos["y"]["value"] == -0.8
        mic.disconnect()

    def test_actuator_selector_reported_back(self, mic):
        pos = mic.get_xyz(with_actuators={"z": "piezo"})
        assert pos["z"]["actuator"] == "piezo"
        assert pos["x"]["actuator"] == "motoric"  # untouched axes use the reference one

    def test_set_xyz_returns_driver_record(self, mic):
        rec = mic.set_xyz(10, 20, 5)
        assert rec["position"] == {"x": 10, "y": 20, "z": 5}  # 10x: no offset
        assert rec["actuators"]["z"] == "motoric"


class TestAcquire:
    def test_acquire_returns_record(self, mic):
        rec = mic.acquire(acquisition_type="prescan", position_label="A1")
        assert rec["acquisition_type"] == "prescan"
        assert rec["position_label"] == "A1"
        assert rec["settle"] == "backlash-corrected"  # active default
        assert rec["format"] == "ome-tiff"  # active default
        assert rec["filename"] == "A1.tiff"

    def test_acquire_options_override(self, mic):
        rec = mic.acquire(
            acquisition_type="targetscan",
            position_label="B2",
            options={"backlash_correction": False, "format": "ome-zarr"},
        )
        assert rec["settle"] == "direct"
        assert rec["format"] == "ome-zarr"
        assert rec["filename"] == "B2.zarr"

    def test_acquisition_options_discovered(self, mic):
        opts = mic.get_acquisition_options()
        assert opts["backlash_correction"]["active"] is True
        assert "ome-zarr" in opts["format"]["options"]


class TestState:
    def test_state_split_into_mutable_immutable(self, mic):
        state = mic.get_state()
        assert set(state) == {"immutable", "mutable"}
        assert "serial" in state["immutable"]
        assert "laser_power" in state["mutable"]

    def test_capture_and_reapply(self, mic):
        original = mic.get_state()
        mic.set_state({"mutable": {"laser_power": 99.0}})
        assert mic.get_state()["mutable"]["laser_power"] == 99.0
        mic.set_state(original)
        assert mic.get_state()["mutable"]["laser_power"] == original["mutable"]["laser_power"]

    def test_set_state_returns_driver_record(self, mic):
        result = mic.set_state({"mutable": {"laser_power": 7.0}})
        assert result["applied"]["laser_power"] == 7.0

    def test_immutable_mismatch_rejected(self, mic):
        with pytest.raises(ValueError, match="different instrument"):
            mic.set_state({"immutable": {"serial": "OTHER"}, "mutable": {}})


class TestProcedures:
    def test_get_procedures_lists_available(self, mic):
        assert "autofocus" in mic.get_procedures()

    def test_set_procedure_runs(self, mic):
        mic.set_procedure({"name": "autofocus"})  # records last_procedure, no error

    def test_set_procedure_returns_driver_record(self, mic):
        result = mic.set_procedure({"name": "autofocus"})
        assert result["ran"]["name"] == "autofocus"


class TestContext:
    def test_get_context_passthrough(self, mic):
        ctx = mic.get_context()
        assert len(ctx["initial_positions"]) == 3
        assert ctx["initial_positions"][0] == {"x": 0.0, "y": 0.0, "z": 0.0}
        assert ctx["serial"] == "MOCK-0001"


class TestModuleStyle:
    def test_module_delegates_to_active_microscope(self):
        import microscope_agnostic_controller as m

        inst = m.get_instruments()[0]
        m.set_instrument(inst, reference_actuators=MOTORIC, reference_objective="20x")
        m.set_xyz(0, 0, 0)
        assert m.get_xyz()["x"]["value"] == 1.5
        m.disconnect()

    def test_unknown_attribute_raises(self):
        import microscope_agnostic_controller as m

        missing = "definitely_not_a_method"
        with pytest.raises(AttributeError):
            getattr(m, missing)
