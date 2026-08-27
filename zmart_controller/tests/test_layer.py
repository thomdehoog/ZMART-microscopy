"""Tests for the cross-vendor controller against the mock driver.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from zmart_controller import get_instruments, set_instrument


def _mock_instrument():
    return next(instrument for instrument in get_instruments() if instrument["vendor"] == "mock")


@pytest.fixture
def mic(tmp_path):
    """A connected mock scope writing into this test's own folder.

    Without an output root the driver falls back to a relative ``mock-output``,
    which lands wherever pytest was started -- in practice, in the repository.
    """
    instrument = _mock_instrument()
    instrument["output_root"] = str(tmp_path)
    session = set_instrument(instrument)
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

    def test_acquire_says_where_it_wrote(self, mic):
        """The same two keys the real driver answers with.

        `images` is the simple list and `planes` the manifest that tells a
        channel from a z. A client following a record must not have to know
        which driver it is talking to, and only the capture knows where its
        files went -- the output root cannot be composed into a filename,
        because the driver owns naming.
        """
        rec = mic.acquire(acquisition_type="overview", position_label="K00_P000001")
        assert rec["images"] == [plane["path"] for plane in rec["planes"]]
        assert len(rec["planes"]) == 1
        plane = rec["planes"][0]
        assert (plane["t"], plane["z"], plane["c"]) == (0, 0, 0)
        # The canonical name, flat and complete: what the capture was, which
        # capture it was, where on the sample, and which plane of it.
        name = Path(plane["path"]).name
        assert name.startswith(f"overview_{rec['acquisition_hash']}_K00_P000001_")
        assert name.endswith("_T000000_C00_Z00000.ome.tiff")

    def test_acquire_writes_the_file_it_names(self, mic):
        """It writes, because the real driver writes.

        A record naming files that are not there is a record a client can
        follow on the microscope and not on the bench, which is the whole
        class of fault the reference driver exists to keep out.
        """
        rec = mic.acquire(acquisition_type="overview", position_label="K00_P000002")
        written = Path(rec["images"][0])
        assert written.is_file()
        assert written.stat().st_size > 0

    def test_acquire_writes_into_the_acquisition_s_data_folder(self, mic):
        """Where a driver puts what it captured, so a run can grow around it.

        ``<output root>/<acquisition type>/data`` -- the images in a folder of
        their own, leaving room beside it for what comes later: a stitched
        view, an analysis, the vendor's own copy. A driver that wrote the
        images loose in the acquisition folder would make every one of those a
        naming problem.
        """
        rec = mic.acquire(acquisition_type="overview", position_label="K00_P000003")
        written = Path(rec["images"][0])
        assert written.parent.name == "data"
        assert written.parent.parent.name == "overview"

    def test_acquire_prints_the_state_it_captured_under(self, mic):
        """One state file per acquisition, in ``data/metadata``.

        Every driver embeds the state in the images it writes, where reading
        it costs opening a picture. Printed beside them it can simply be read.
        The name is the image's without the channel and the z-slice, which one
        state spans.
        """
        rec = mic.acquire(acquisition_type="overview", position_label="K00_P000004")
        metadata = Path(rec["images"][0]).parent / "metadata" / "ZMART_state"
        printed = metadata / (
            f"overview_{rec['acquisition_hash']}_K00_P000004_T000000_ZMART_state.json"
        )
        assert json.loads(printed.read_text(encoding="utf-8")) == mic.get_state()

    def test_acquire_options_override(self, mic):
        rec = mic.acquire(
            acquisition_type="targetscan",
            position_label="B2",
            options={"backlash_correction": False, "format": "ome-zarr"},
        )
        assert rec["settle"] == "direct"
        assert rec["format"] == "ome-zarr"

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
    def test_connection_status_answers_over_time(self, mic):
        import time

        from zmart_drivers.mock import mock_driver

        # Just opened: the first check answers at once, the rest are pending.
        mic._handle.connected_at = time.monotonic()
        status = mic.get_info()["connection_status"]
        assert list(status) == ["driver", "client", "serial", "stage", "output root"]
        assert status["driver"] == "mock · mock-scope · mock-api"
        assert status["output root"] == mock_driver.PENDING
        # Long enough after: every check has its answer, none pending.
        mic._handle.connected_at = time.monotonic() - 10.0
        status = mic.get_info()["connection_status"]
        assert mock_driver.PENDING not in status.values()
        assert status["client"] == "mock-client"
        assert status["stage"].startswith("x 0.0 · y 0.0 · z 0.0")

    def test_canvas_is_the_travel_and_the_position_is_get_xyz(self, mic):
        mic.set_xyz(1000.0, 2000.0, 30.0)
        canvas = mic.get_info()["canvas"]
        assert canvas == {"x_um": [0.0, 120_000.0], "y_um": [0.0, 80_000.0], "z_um": [0.0, 10_000.0]}
        assert mic.get_xyz()["x"]["value"] == 1000.0
        assert mic.get_xyz()["y"]["value"] == 2000.0

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
