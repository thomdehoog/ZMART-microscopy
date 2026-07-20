"""Tests for the cross-vendor controller against the mock driver.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import pytest

from zmart_controller import get_instruments, set_instrument


def _mock_instrument():
    return next(instrument for instrument in get_instruments() if instrument["vendor"] == "mock")


@pytest.fixture
def mic():
    session = set_instrument(_mock_instrument())
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
        assert mic.get_info()["client"] == "mock-client"

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
        assert pos["x"]["actuator"] == "motoric"  # untouched axes use the reference one

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
    def test_state_split_into_changeable_observed(self, mic):
        state = mic.get_state()
        assert list(state) == ["changeable", "observed"]  # changeable first
        assert "laser_power" in state["changeable"]
        assert "serial" in state["observed"]

    def test_capture_and_reapply(self, mic):
        original = mic.get_state()
        mic.set_state({"changeable": {"laser_power": 99.0}})
        assert mic.get_state()["changeable"]["laser_power"] == 99.0
        mic.set_state(original)
        assert mic.get_state()["changeable"]["laser_power"] == original["changeable"]["laser_power"]

    def test_set_state_returns_driver_record(self, mic):
        assert mic.set_state({"changeable": {"laser_power": 7.0}})["applied"]["laser_power"] == 7.0

    def test_observed_is_a_report_never_an_instruction(self, mic):
        # A mismatching observed part does not block applying the changeable
        # part (operator decision: set_state acts on changeable only).
        rec = mic.set_state({"changeable": {"laser_power": 5.0}, "observed": {"serial": "OTHER"}})
        assert rec["applied"]["laser_power"] == 5.0


class TestProcedures:
    def test_get_procedures_lists_available(self, mic):
        assert "autofocus" in mic.get_procedures()

    def test_run_procedure_returns_driver_record(self, mic):
        assert mic.run_procedure({"name": "autofocus"})["ran"]["name"] == "autofocus"


class TestInfo:
    def test_get_info_passthrough(self, mic):
        info = mic.get_info()
        assert len(info["tile_positions"]) == 3
        assert info["tile_positions"][0] == {
            "x": 0.0,
            "y": 0.0,
            "z": 0.0,
            "tile_size": {"x": 100.0, "y": 100.0},
        }


class TestDisconnect:
    def test_session_disconnect_is_idempotent(self, mic):
        assert mic.closed is False
        mic.disconnect()
        assert mic.closed is True
        mic.disconnect()  # second call must be a no-op, not a driver double-close

    def test_ops_after_disconnect_raise(self, mic):
        mic.disconnect()
        with pytest.raises(RuntimeError, match="disconnected"):
            mic.get_xyz()

    def test_actuator_selection_does_not_persist(self, mic):
        """Defaults are fixed (the reference actuator), never sticky —
        a per-call selection applies to that call only."""
        mic.set_xyz(0, 0, 0, with_actuators={"z": "piezo"})
        assert mic.get_xyz()["z"]["actuator"] == "motoric"

    def test_invalid_acquire_option_rejected(self, mic):
        with pytest.raises(ValueError, match="unknown acquisition option"):
            mic.acquire(acquisition_type="prescan", position_label="A1", options={"fromat": "x"})
        with pytest.raises(ValueError, match="invalid value"):
            mic.acquire(acquisition_type="prescan", position_label="A1", options={"format": "png"})


class TestModuleStyle:
    def test_module_delegates_to_active_microscope(self):
        import zmart_controller as m

        m.set_instrument(_mock_instrument())
        m.set_xyz(10, 20, 5)
        assert m.get_xyz()["x"]["value"] == 10
        m.disconnect()

    def test_module_disconnect_clears_active(self):
        import zmart_controller as m

        m.set_instrument(_mock_instrument())
        m.disconnect()
        with pytest.raises(AttributeError, match="no active microscope"):
            m.acquire(acquisition_type="prescan", position_label="A1")
        m.disconnect()  # no active microscope: still a no-op

    def test_swap_survives_failing_teardown(self):
        import zmart_controller as m

        first = m.set_instrument(_mock_instrument())
        first.disconnect = lambda: (_ for _ in ()).throw(RuntimeError("teardown boom"))
        with pytest.raises(RuntimeError, match="teardown boom"):
            m.set_instrument(_mock_instrument())
        # the new session must be tracked despite the old teardown failing
        m.set_xyz(1, 2, 3)
        assert m.get_xyz()["x"]["value"] == 1

    def test_no_active_session_error_is_helpful(self):
        import zmart_controller as m

        with pytest.raises(AttributeError, match="set_instrument"):
            m.acquire(acquisition_type="prescan", position_label="A1")

    def test_unknown_attribute_raises(self):
        import zmart_controller as m

        missing = "definitely_not_a_method"
        with pytest.raises(AttributeError):
            getattr(m, missing)
