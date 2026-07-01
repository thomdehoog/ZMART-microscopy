"""Tests for the cross-vendor controller against the mock driver.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import pytest
from zmart import get_instruments, set_instrument


@pytest.fixture
def mic():
    session = set_instrument(get_instruments()[0])
    yield session
    session.disconnect()


class TestInstruments:
    def test_lists_connection_dicts(self):
        inst = next(i for i in get_instruments() if i["vendor"] == "mock")
        assert inst["microscope"] == "mock-scope"
        assert inst["api"] == "mock-api"
        assert inst["client"] == "mock-client"


class TestSetInstrument:
    def test_context_resolves(self, mic):
        assert mic.context == {"vendor": "mock", "microscope": "mock-scope", "api": "mock-api"}

    def test_connection_reaches_driver(self, mic):
        # the variable connection dict is forwarded untouched to the driver's connect()
        assert mic.get_context()["client"] == "mock-client"

    def test_unknown_instrument_raises(self):
        with pytest.raises(ValueError, match="no driver registered"):
            set_instrument({"vendor": "nope", "microscope": "x", "api": "y"})


class TestFrame:
    def test_set_get_roundtrip(self, mic):
        rec = mic.set_xyz(10, 20, 5)
        assert rec["position"] == {"x": 10, "y": 20, "z": 5}
        assert rec["actuators"]["z"] == "motoric"
        pos = mic.get_xyz()
        assert (pos["x"]["value"], pos["y"]["value"], pos["z"]["value"]) == (10, 20, 5)
        assert pos["x"]["unit"] == "um"

    def test_set_origin_zeros_here(self, mic):
        mic.set_xyz(10, 20, 5)
        mic.set_origin()  # current position becomes (0, 0, 0)
        pos = mic.get_xyz()
        assert (pos["x"]["value"], pos["y"]["value"], pos["z"]["value"]) == (0, 0, 0)

    def test_get_actuators_lists_options(self, mic):
        assert mic.get_actuators()["z"] == ["motoric", "galvo", "piezo"]

    def test_actuator_selector_reported_back(self, mic):
        pos = mic.get_xyz(with_actuators={"z": "piezo"})
        assert pos["z"]["actuator"] == "piezo"
        assert pos["x"]["actuator"] == "motoric"  # untouched axes use the active one

    def test_unknown_actuator_raises(self, mic):
        with pytest.raises(ValueError, match="unknown actuator"):
            mic.set_xyz(0, 0, 0, with_actuators={"z": "hovercraft"})


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
        assert mic.set_state({"mutable": {"laser_power": 7.0}})["applied"]["laser_power"] == 7.0

    def test_immutable_mismatch_rejected(self, mic):
        with pytest.raises(ValueError, match="different instrument"):
            mic.set_state({"immutable": {"serial": "OTHER"}, "mutable": {}})


class TestProcedures:
    def test_get_procedures_lists_available(self, mic):
        assert "autofocus" in mic.get_procedures()

    def test_set_procedure_returns_driver_record(self, mic):
        assert mic.set_procedure({"name": "autofocus"})["ran"]["name"] == "autofocus"


class TestContext:
    def test_get_context_passthrough(self, mic):
        ctx = mic.get_context()
        assert len(ctx["initial_positions"]) == 3
        assert ctx["initial_positions"][0] == {"x": 0.0, "y": 0.0, "z": 0.0}


class TestModuleStyle:
    def test_module_delegates_to_active_microscope(self):
        import zmart as m

        m.set_instrument(m.get_instruments()[0])
        m.set_xyz(10, 20, 5)
        assert m.get_xyz()["x"]["value"] == 10
        m.disconnect()

    def test_unknown_attribute_raises(self):
        import zmart as m

        missing = "definitely_not_a_method"
        with pytest.raises(AttributeError):
            getattr(m, missing)
