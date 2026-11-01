"""The operator page's bridge, held to the driver contract it speaks to.

Every fault these cover was invisible from the page: the window drew a focus
map, the rows filled with numbers, and every number was a zero. What the page
cannot see is which key a driver puts its answer under, so that is what is
asserted here — against stubs shaped like the ZMART drivers, answering every
command in the controller's two-part ``{"success", "content"}`` shape, and
against the mock microscope plugged in through the controller.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest
from zmart_controller import ZmartController, register_driver

from .. import mock_microscope
from ..analysis import detection, focus_score, warm
from ..microscope.instrument import Instrument
from ..storage import output, viewer_service
from ..storage.output import prepare_experiment, run_hash
from . import (
    connecting,
    discovery,
    focus,
    ledgers,
    pictures,
    plots,
    protocols,
    readings,
    scan,
    stage,
    state,
    targets,
)


class _Enveloped:
    """A stub driver session, answering the way the controller does: in two parts.

    The stubs below return their content, which keeps them short to read;
    this wraps each answer as ``{"success": True, "output": ...}``, the shape
    every ZMART driver gives through the controller.
    """

    def __init__(self, inner):
        self._inner = inner
        self.context = dict(getattr(inner, "context", {}) or {})

    def __getattr__(self, name):
        found = getattr(self._inner, name)
        if name == "disconnect" or not callable(found):
            return found

        def answered(*args, **kwargs):
            return {"success": True, "output": found(*args, **kwargs)}

        return answered


def _kept(acquisition_type: str, *, position_label: str) -> dict:
    """A stub capture as the bridge keeps it: saved in the run's folder for its
    acquisition type, and filed under that type."""
    record = _plugged(_Driver()).acquire(position_label=position_label, acquisition_type=acquisition_type)
    record["acquisition_type"] = acquisition_type
    return record


#: The hash of the run every stub session captures into.
RUN_HASH = "aaaaaa"


def _plugged(stub) -> Instrument:
    """A stub, as the bridge holds a session: behind :class:`Instrument`, in a run of its own."""
    session = Instrument(_Enveloped(stub))
    session.run = Path(tempfile.mkdtemp(prefix="zmart-run-")) / f"a-run_{RUN_HASH}"
    return session


def _needs_the_analysis_environment(name: str) -> None:
    """Skip a test that runs a ZMART-analysis step in its own conda environment,
    when this machine has not created that environment."""
    if not (Path(sys.prefix).parent / name).is_dir():
        pytest.skip(f"the analysis environment {name} is not set up on this machine")


def _a_mock_session(instrument) -> Instrument:
    """The mock microscope through the controller, as the bridge connects it: given the run."""
    session = Instrument(ZmartController(mock_microscope, instrument))
    session.run = state.run
    return session


class _Driver:
    """A stage that stays where it is put, and an autofocus that answers.

    Shaped after the two drivers in this repo: ``set_xyz`` returns a move
    record carrying the commanded position, and the autofocus reports its
    height under ``frame_z_um`` — the sharp height in frame terms, which is
    the one in the page's own coordinates.
    """

    def __init__(self, *, height_key: str | None = "frame_z_um"):
        self.at = {"x": 0.0, "y": 0.0, "z": 0.0}
        self.drove_to: list[tuple] = []
        self.ran: list[dict] = []
        self.captured: list[tuple[str, str]] = []
        self.applied: list[dict] = []
        self.height_key = height_key
        self.staging = Path(tempfile.mkdtemp(prefix="zmart-driver-"))

    def get_xyz(self, **_kw) -> dict:
        return {axis: {"position": v} for axis, v in self.at.items()}

    def set_state(self, state: dict) -> dict:
        self.applied.append(dict(state))
        return {"applied": dict(state)}

    def set_xyz(self, x, y, z, **_kw) -> dict:
        self.drove_to.append((x, y, z))
        self.at = {"x": float(x), "y": float(y), "z": float(z)}
        return self.get_xyz()  # read back, the same answer as get_xyz

    def get_acquisition_settings(self) -> dict:
        """How a capture is triggered, and nothing else, as the controller's contract asks."""
        return {"trigger": {"options": ["full"], "default": "full", "active": "full"}}

    def acquire(self, *, position_label, acquisition_settings, acquisition_type, output_folder) -> dict:
        """A focussing capture: a stack around wherever the stage is standing.

        Saved in ``output_folder``, or a folder of its own when it is None,
        each file named by the acquisition type and the label as the
        controller's contract asks; the type and the label are recorded as
        they came.
        """
        self.captured.append((acquisition_type, position_label))
        where = Path(output_folder) if output_folder is not None else self.staging
        planes = []
        for index in range(5):
            path = where / f"{acquisition_type}_{position_label}_Z{index:05d}.tiff"
            path.write_bytes(b"a plane")
            planes.append({
                "t": 0, "c": 0, "z": index, "path": str(path),
                "x_um": self.at["x"], "y_um": self.at["y"], "z_um": self.at["z"],
            })
        return {
            "position_label": position_label,
            "acquisition_type": acquisition_type,
            "files": [plane["path"] for plane in planes],
            "planes": planes,
            "found_at": self.at["z"] if self.height_key else None,
        }

    def run_procedure(self, procedure: dict) -> dict:
        """Refuses an unnamed procedure, exactly as the Leica adapter does."""
        self.ran.append(dict(procedure))
        name = procedure.get("name")
        if name != "autofocus":
            raise ValueError(f"unknown procedure {name!r}")
        answer = {"ran": dict(procedure)}
        if self.height_key:
            # the sharp height is wherever this stage stands, as the mock
            # driver's is: deterministic, and enough to tell a real height
            # from a default
            answer[self.height_key] = self.at["z"]
        return answer


@pytest.fixture()
def driver(monkeypatch):
    stub = _Driver()
    monkeypatch.setattr(state, "session", _plugged(stub))
    return stub


# --- driving the stage -------------------------------------------------------


def test_a_drive_answers_with_the_position_the_move_reported(driver):
    """No second read: set_xyz is confirmed and says where it went."""
    went = stage.drive_to({"x": 61_000, "y": 42_000, "z": -380})
    assert driver.drove_to[-1] == (61_000.0, 42_000.0, -380.0)
    assert {axis: reading["position"] for axis, reading in went.items()} == {
        "x": 61_000.0,
        "y": 42_000.0,
        "z": -380.0,
    }


def test_an_axis_not_asked_about_is_left_where_it_stands(driver):
    """Driving across the plate is not a request to move the objective."""
    stage.drive_to({"x": 20_000, "y": 30_000, "z": -390})
    stage.drive_to({"x": 25_000})
    assert driver.drove_to[-1] == (25_000.0, 30_000.0, -390.0)


def test_the_stage_is_read_when_the_instrument_is_free(driver, monkeypatch):
    """A free instrument is asked, and what it says is remembered."""
    monkeypatch.setattr(state, "last_xyz", None)
    stage.drive_to({"x": 1_000, "y": 2_000, "z": -3})
    where = stage.where_the_stage_is()
    assert "busy" not in where
    assert {axis: where[axis]["position"] for axis in ("x", "y", "z")} == {
        "x": 1_000.0,
        "y": 2_000.0,
        "z": -3.0,
    }
    assert state.last_xyz is where


def test_a_busy_instrument_answers_the_last_position_marked_busy(driver, monkeypatch):
    """The page's clock never queues behind a site being captured."""
    monkeypatch.setattr(state, "last_xyz", None)
    stage.the_stage_was_sent_to(5_000, 6_000, -7)
    with state.the_instruments_turn:
        where = stage.where_the_stage_is()
    assert where["busy"] is True
    assert {axis: where[axis]["position"] for axis in ("x", "y", "z")} == {
        "x": 5_000.0,
        "y": 6_000.0,
        "z": -7.0,
    }


def test_a_busy_instrument_with_nothing_remembered_refuses(driver, monkeypatch):
    monkeypatch.setattr(state, "last_xyz", None)
    with state.the_instruments_turn, pytest.raises(RuntimeError, match="busy"):
        stage.where_the_stage_is()


def test_a_driver_that_names_no_position_is_asked_where_it_ended_up(monkeypatch):
    """Some may confirm the move and say nothing about where."""

    class Quiet(_Driver):
        def set_xyz(self, x, y, z, **_kw):
            self.at = {"x": float(x), "y": float(y), "z": float(z)}
            return {"ok": True}

    monkeypatch.setattr(state, "session", _plugged(Quiet()))
    went = stage.drive_to({"x": 7, "y": 8, "z": 9})
    assert {axis: reading["position"] for axis, reading in went.items()} == {
        "x": 7.0,
        "y": 8.0,
        "z": 9.0,
    }


# --- the focus map -----------------------------------------------------------


def _measured(asked):
    """Measure a focus map the way the page drives it: begin, then per point
    drive, capture and score, then end. Hands back the bridge's ledger."""
    points = asked.get("points", [])
    # The page applies the focussing recording once, before it begins.
    if asked.get("state"):
        readings.apply_state(asked["state"])
    begun = focus.begin_focus({"of": len(points)})
    for index, point in enumerate(points):
        start = point.get("startZ")
        at = stage.drive_to({
            "x": point["x"], "y": point["y"],
            **({"z": start} if isinstance(start, (int, float)) else {}),
        })
        record = readings.capture({"acquisition_type": "focussing", "position_label": begun["labels"][index]})["output"]
        focus.score_focus({"record": record, "centre": at["z"]["position"], "point": point})
    focus.end_focus({})
    assert ledgers.focus["error"] is None, ledgers.focus["error"]
    return dict(ledgers.focus)


def test_a_scan_cannot_start_while_the_page_is_measuring_a_map(driver):
    """The stage is the map's until the page ends it."""
    focus.begin_focus({"of": 1})
    try:
        with pytest.raises(RuntimeError, match="focus map"):
            scan.start_scan({"positions": [{"x": 0, "y": 0}]})
    finally:
        focus.end_focus({})


def test_the_ledger_answers_what_the_page_had_scored(driver):
    """A page that reopens reads the map from the bridge, in the order asked."""
    got = _measured({"points": [{"x": 1, "y": 2}, {"x": 3, "y": 4}]})
    assert [(p["x"], p["y"]) for p in got["points"]] == [(1, 2), (3, 4)]
    assert got["done"] == 2 and got["running"] is False
    assert "startZ" not in got["points"][0]


def test_a_focus_map_runs_no_vendor_procedure(driver):
    """The page asks the instrument for pixels and nothing else.

    It called the instrument's own autofocus and kept the height that came
    back, which could not be argued with: no curve to show, so the operator's
    choice of sharpness metric reached nothing and the rule rejecting a peak
    too narrow to be tissue was never applied. Focusing is an image-analysis
    routine that happens to run before the picture rather than after it.
    """
    _measured({"points": [{"x": 1, "y": 2}, {"x": 3, "y": 4}]})
    assert driver.ran == []
    assert [kind for kind, _ in driver.captured] == ["focussing"] * 2


def test_a_measured_point_carries_the_curve_it_was_chosen_from(driver):
    """A height alone cannot be argued with; the plot is how it shows its work."""
    got = _measured({"points": [{"x": 1, "y": 2}]})
    assert got["points"][0]["traces"] == {"brenner": {}}


@pytest.fixture(autouse=True)
def _nothing_scanned_yet(monkeypatch):
    """What one test's scan captured is not the next test's overview."""
    monkeypatch.setattr(state, "records", {})


@pytest.fixture(autouse=True)
def _a_run_to_write_into(tmp_path, monkeypatch):
    """A run folder, as connecting would have made.

    These tests set the session directly instead of connecting, so they get
    the other half of a session too: everything a run captures goes under its
    own folder, and without one there is nothing to write into.
    """
    run = tmp_path / "target-acquisition_000001"
    run.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(state, "run", run)
    return run


@pytest.fixture(autouse=True)
def _score_without_an_engine(monkeypatch):
    """The bridge's scorer, without spawning an analysis environment for it.

    What these tests are about is the translation either side of the focus
    loop -- where the stage is driven, what comes back, and what is reported
    when nothing could be chosen. Scoring real pixels is tested where the
    scoring lives.
    """
    monkeypatch.setattr(
        focus,
        "score_a_stack",
        lambda: (lambda record: {"z_um": record["found_at"], "traces": {"brenner": {}}}),
    )


def test_the_height_the_driver_found_is_the_height_reported(driver):
    """It was read from keys no driver uses, so every point came back 0.0."""
    got = _measured({"points": [{"x": 1, "y": 2, "startZ": -350.0}]})
    point = got["points"][0]
    assert point["zAuto"] == -350.0
    assert point["z"] == -350.0
    assert point["lost"] is False


def test_a_search_begins_where_the_page_asked_it_to(driver):
    """`startZ` is the page saying "begin from what the map predicts here"."""
    _measured({"points": [{"x": 1, "y": 2, "startZ": -412.5}]})
    assert driver.drove_to[-1] == (1.0, 2.0, -412.5)


def test_a_search_with_no_start_asked_for_keeps_the_height_it_has(driver):
    """It used to be driven to frame zero, which threw the map's answer away."""
    stage.drive_to({"x": 0, "y": 0, "z": -300.0})
    _measured({"points": [{"x": 5, "y": 6}]})
    assert driver.drove_to[-1] == (5.0, 6.0, -300.0)


def test_a_point_nothing_could_be_chosen_from_reports_no_height(monkeypatch):
    """None, not zero.

    The page fits a surface through what it is given, so one invented zero
    drags the whole map towards a place nobody measured.
    """
    monkeypatch.setattr(state, "session", _plugged(_Driver(height_key=None)))
    got = _measured({"points": [{"x": 1, "y": 2}]})
    point = got["points"][0]
    assert point["zAuto"] is None
    assert point["z"] is None
    assert point["lost"] is True


# --- how big a frame is ------------------------------------------------------


class _Optics(_Driver):
    """A driver that reports its optics, and says what it is asked to say."""

    def __init__(self, observed):
        super().__init__()
        self.observed = observed

    def get_state(self) -> dict:
        return {"changeable": {}, "observed": self.observed}


def _frame(observed, monkeypatch):
    monkeypatch.setattr(state, "session", _plugged(_Optics(observed)))
    return readings.reading("acquisition")["frameUm"]


def test_the_image_size_and_the_pixel_size_make_the_frame(monkeypatch):
    """The controller's own keys for the current settings: how many pixels, and how
    large each is -- and they change with the settings, which is the whole point.
    Only x is read; a plan is laid in square frames."""
    assert _frame(
        {"pixel_size_um": [0.33, 0.33], "image_size_px": [2048, 2048]}, monkeypatch) == 676
    assert _frame(
        {"pixel_size_um": [0.33, 0.33], "image_size_px": [512, 512]}, monkeypatch) == 169


def test_an_instrument_that_says_no_image_size_is_refused_rather_than_guessed(monkeypatch):
    """A frame nobody reported is not drawn: 512 px was a stand-in for a size
    nobody reported, and a plan laid on it had gaps or overlaps."""
    with pytest.raises(RuntimeError, match="how many pixels"):
        _frame({"pixel_size_um": [1.0, 1.0]}, monkeypatch)


# --- what the instrument offers ----------------------------------------------


def test_the_acquisition_menu_is_handed_over_untouched(monkeypatch):
    """The driver's own menu, in the driver's own words.

    ``options`` is what may be chosen and ``active`` what is chosen now, and
    which settings exist at all is the driver's business — the page shows what
    it is given and hands the same shape back at capture time, so anything
    reworded here would have to be worded back before `acquire` could read it.
    """
    menu = {
        "job": {"options": ["Overview", "HiRes"], "active": "Overview"},
        "format": {"options": ["ome-tiff", "ome-zarr"], "active": "ome-tiff"},
        "backlash_rounds": {"options": "int >= 0", "active": 0},
    }

    class Offering(_Driver):
        def get_acquisition_settings(self):
            return menu

    monkeypatch.setattr(state, "session", _plugged(Offering()))
    assert readings.acquisition_settings() == menu


def test_a_setting_is_applied_as_the_changeable_half_of_state(monkeypatch):
    """`set_state` takes a whole state; the page sends only what it changed.

    The driver acts on `changeable` and treats `observed` as a report, so the
    page has no business sending one — it names the settings it is changing
    and the bridge puts them where the contract says they go.
    """
    sent = {}

    class Settable(_Driver):
        def set_state(self, state):
            sent.update(state)
            return {"applied": dict(state.get("changeable", {}))}

    monkeypatch.setattr(state, "session", _plugged(Settable()))
    answered = readings.apply_state({"job": "HiRes"})
    assert sent == {"changeable": {"job": "HiRes"}}
    assert answered == {"applied": {"job": "HiRes"}}


# --- capturing ---------------------------------------------------------------


class _Capturing(_Driver):
    """A driver that records what it was asked to capture, and writes it.

    It writes because a real driver does: a client may move a record's files
    into the run's folder, and a fake that named files it had not written
    would let that break unnoticed.
    """

    def __init__(self):
        super().__init__()
        self.asked = []
        self.staging = Path(tempfile.mkdtemp(prefix="zmart-capture-"))

    def acquire(self, *, position_label, acquisition_settings, acquisition_type, output_folder):
        self.asked.append((position_label, acquisition_settings, acquisition_type, output_folder))
        path = Path(output_folder or self.staging) / f"{acquisition_type}_{position_label}.tiff"
        path.write_bytes(b"a plane")
        return {
            "position_label": position_label,
            "acquisition_type": acquisition_type,
            "files": [str(path)],
            "planes": [{"t": 0, "z": 0, "c": 0, "path": str(path),
                        "x_um": 0.0, "y_um": 0.0, "z_um": 0.0}],
        }


def test_a_capture_answers_as_the_controller_does(monkeypatch):
    """The record is the half nothing else can reconstruct.

    Where a run will land is in `get_info`; what one capture wrote is only
    known to the capture — a driver names its own files, and one acquisition
    can be many planes. The controller's answer is passed on whole, envelope
    and all, so the page reads what a Python script would.
    """
    driver = _Capturing()
    session = _plugged(driver)
    monkeypatch.setattr(state, "session", session)
    answer = readings.capture({
        "acquisition_type": "overview",
        "position_label": "K00_M000001_G000000_P000007_V00",
    })
    path = str(session.run / "overview" / "overview_K00_M000001_G000000_P000007_V00.tiff")
    assert answer == {"success": True, "output": {
        "position_label": "K00_M000001_G000000_P000007_V00",
        "acquisition_type": "overview",
        "files": [path],
        "planes": [{"t": 0, "z": 0, "c": 0, "path": path,
                    "x_um": 0.0, "y_um": 0.0, "z_um": 0.0}],
    }}


def test_a_capture_the_microscope_declined_is_answered_not_raised(monkeypatch):
    """A script sees ``success`` false and the driver's reason; so does the page."""
    declined = {"success": False, "output": {"reason": "the image never arrived", "files": [],
                                              "planes": []}}

    class _Declining:
        context = {"driver": "declining"}

        def get_acquisition_settings(self):
            return {"success": True, "output": {}}

        def acquire(self, **_asked):
            return declined

    monkeypatch.setattr(state, "session", Instrument(_Declining()))
    assert readings.capture({"acquisition_type": "overview", "position_label": "A1"}) == declined


def test_the_settings_a_capture_is_given_reach_the_driver(monkeypatch):
    """Straight from the menu the page read, straight back to the driver.

    Omitted ones the driver fills from its own actives, which is why nothing
    here invents a default.
    """
    driver = _Capturing()
    session = _plugged(driver)
    monkeypatch.setattr(state, "session", session)
    readings.capture({
        "acquisition_type": "targets",
        "position_label": "K00_M000002_G000001_P000003_V00",
        "acquisition_settings": {"trigger": "full"},
    })
    assert driver.asked[-1] == (
        "K00_M000002_G000001_P000003_V00", {"trigger": "full"},
        "targets", str(session.run / "targets"),
    )


# --- the scan ----------------------------------------------------------------


def _scanned(driver, positions, monkeypatch, **asked):
    """Run a scan to completion on this driver and hand back what it kept."""
    monkeypatch.setattr(state, "session", _plugged(driver))
    kind = asked.get("acquisition_type", "overview")
    state.records[kind] = []
    ledgers.scan.update(running=True, done=0, of=len(positions), error=None, acquisition_type=kind)
    scan.scan_worker(positions, **asked)
    assert ledgers.scan["error"] is None, ledgers.scan["error"]
    return scan.the_scan()


def test_a_scan_labels_every_position_the_canonical_way(monkeypatch):
    """`pos_00000` named nothing.

    A label says where on the sample a capture was taken: carrier,
    compartment, group, position, view. A running index cannot be traced back
    to a well, so a file named by one is a file nobody can place.
    """
    driver = _Capturing()
    scanned = _scanned(driver, [{"x": 0, "y": 0}, {"x": 10, "y": 0}], monkeypatch)
    assert [(label, kind) for label, _, kind, _ in driver.asked] == [
        ("K00_M000000_G000000_P000000_V00", "overview"),
        ("K00_M000000_G000000_P000001_V00", "overview"),
    ]
    assert scanned["done"] == 2


def test_the_scan_answers_only_the_records_since_the_ones_a_page_holds(monkeypatch):
    """A poll three times a second must not carry every record every time.

    The page keeps the records it was given; asked since that many, the
    bridge sends the rest. Asked plainly, it still sends everything.
    """
    driver = _Capturing()
    scanned = _scanned(driver, [{"x": 0, "y": 0}, {"x": 10, "y": 0}, {"x": 20, "y": 0}], monkeypatch)
    assert len(scanned["records"]) == 3
    later = scan.the_scan(since=2)
    assert later["done"] == 3
    assert [r["position_label"] for r in later["records"]] == [scanned["records"][2]["position_label"]]
    assert scan.the_scan(since=3)["records"] == []
    assert len(scan.the_scan(since=0)["records"]) == 3


def test_a_position_says_where_on_the_plate_it_is(monkeypatch):
    """The page knows which well and which tileset; the label carries it."""
    driver = _Capturing()
    _scanned(driver, [{"x": 0, "y": 0, "compartment": 3, "group": 2}], monkeypatch)
    assert driver.asked[-1][0] == "K00_M000003_G000002_P000000_V00"


def test_a_scan_keeps_the_record_of_every_capture(monkeypatch):
    """Kept, because nothing else can reconstruct it.

    They were thrown away: `acquire` was called and its answer dropped, so a
    run could be caused and never accounted for.
    """
    driver = _Capturing()
    scanned = _scanned(driver, [{"x": 0, "y": 0}, {"x": 10, "y": 0}], monkeypatch)
    assert len(scanned["records"]) == 2
    assert [r["position_label"] for r in scanned["records"]] == [
        "K00_M000000_G000000_P000000_V00",
        "K00_M000000_G000000_P000001_V00",
    ]
    assert all(r["files"] for r in scanned["records"])


# --- the target run, the page's own loop ------------------------------------


def _targets_taken(positions, *, append=False, focus=None):
    """Acquire the targets the way the page drives it: begin, then per tile
    drive, capture and land (with a focussing stack scored first when
    *focus* says so), then end. Hands back the bridge's ledger."""
    begun = targets.begin_target_run({"positions": positions, "append": append})
    for index, position in enumerate(positions):
        at = stage.drive_to({"x": position["x"], "y": position["y"],
                               **({"z": position["z"]} if "z" in position else {})})
        found = None
        if focus:
            stack = readings.capture({
                "acquisition_type": "target-focussing", "position_label": begun["labels"][index],
            })["output"]
            found = targets.score_target_focus({"record": stack, "centre": at["z"]["position"],
                                                "x": position["x"], "y": position["y"]})
            if found["z"] is not None:
                at = stage.drive_to({"x": position["x"], "y": position["y"], "z": found["z"]})
        record = readings.capture({"acquisition_type": "targets", "position_label": begun["labels"][index]})["output"]
        targets.target_landed({
            "record": record,
            "position": {"x": position["x"], "y": position["y"], "z": at["z"]["position"]},
            "focus": found and {"z_peak_um": found["z"], "found": found["z"] is not None},
        })
    targets.end_target_run({})
    assert ledgers.acquired["error"] is None, ledgers.acquired["error"]
    return dict(ledgers.acquired)


def test_the_targets_are_taken_one_by_one_as_the_page_drives_them(driver, monkeypatch):
    """No procedure in the bridge: the page drives, captures and lands each
    tile, and the bridge keeps the record the way the scan kept it -- where
    it was asked for, when it was taken, its OME-Zarr position -- and a
    ledger a reopened page can read, since the number it holds."""
    kept = []
    monkeypatch.setattr(output, "move_record_images", lambda record, where: None)
    monkeypatch.setattr(pictures, "keep_position_as_zarr", lambda record, kind: kept.append((record["position_label"], kind)))
    got = _targets_taken([
        {"x": 10, "y": 20, "z": 5, "position_index": 0},
        {"x": 30, "y": 40, "z": 6, "position_index": 1},
    ])
    labels = [record["position_label"] for record in state.records["targets"]]
    assert labels == ["K00_M000000_G000000_P000000_V00", "K00_M000000_G000000_P000001_V00"]
    assert kept == [(labels[0], "targets"), (labels[1], "targets")]
    assert driver.captured == [("targets", labels[0]), ("targets", labels[1])]
    assert driver.drove_to == [(10.0, 20.0, 5.0), (30.0, 40.0, 6.0)]
    first = state.records["targets"][0]
    assert first["requested_position_um"] == {"x": 10.0, "y": 20.0, "z": 5.0}
    assert first["taken"] > 0 and first["focus"] is None
    assert got["done"] == got["of"] == 2 and got["running"] is False
    later = targets.the_target_run(since=1)
    assert [record["position_label"] for record in later["records"]] == [labels[1]]
    assert targets.the_target_run(since=2)["records"] == []


def test_rerunning_one_target_keeps_the_other_pairs(driver, monkeypatch):
    """A selected target is reacquired without throwing the others away."""
    monkeypatch.setattr(output, "move_record_images", lambda record, where: None)
    monkeypatch.setattr(pictures, "keep_position_as_zarr", lambda record, kind: None)
    _targets_taken([
        {"x": 10, "y": 20, "position_index": 0}, {"x": 30, "y": 40, "position_index": 1},
    ])
    first = list(state.records["targets"])
    got = _targets_taken([{"x": 31, "y": 41, "position_index": 1}], append=True)
    assert [record["position_label"] for record in state.records["targets"]] == [
        "K00_M000000_G000000_P000000_V00", "K00_M000000_G000000_P000001_V00",
    ]
    assert state.records["targets"][0] is first[0]
    assert state.records["targets"][1]["requested_position_um"]["x"] == 31.0
    assert len(got["records"]) == 1


def test_a_target_is_focussed_first_when_the_page_asks(driver, monkeypatch):
    """With focussing on, the page takes a stack with the target focussing
    job, the bridge scores it under its own acquisition, and the target is
    captured at the peak; the record says which height and why."""
    monkeypatch.setattr(output, "move_record_images", lambda record, where: None)
    kept = []
    monkeypatch.setattr(pictures, "keep_position_as_zarr", lambda record, kind: kept.append(kind))
    driver.at["z"] = 12.0
    _targets_taken([{"x": 10, "y": 20, "z": 12, "position_index": 0}], focus=True)
    assert driver.captured == [
        ("target-focussing", "K00_M000000_G000000_P000000_V00"),
        ("targets", "K00_M000000_G000000_P000000_V00"),
    ]
    assert "target-focussing" in kept and kept[-1] == "targets"
    record = state.records["targets"][0]
    assert record["focus"]["found"] is True
    assert record["focus"]["z_peak_um"] == record["requested_position_um"]["z"]


def test_a_scan_cannot_start_while_targets_are_being_taken(driver):
    """The stage is the target run's until the page ends it, and the other
    way round."""
    targets.begin_target_run({"positions": [{"x": 0, "y": 0}]})
    try:
        with pytest.raises(RuntimeError, match="target"):
            scan.start_scan({"positions": [{"x": 0, "y": 0}]})
        with pytest.raises(RuntimeError, match="run"):
            focus.begin_focus({"of": 1})
    finally:
        targets.end_target_run({})
    ledgers.scan["running"] = True
    try:
        with pytest.raises(RuntimeError, match="run"):
            targets.begin_target_run({"positions": [{"x": 0, "y": 0}]})
    finally:
        ledgers.scan["running"] = False


def test_a_scan_captures_under_the_kind_of_scan_it_is(monkeypatch):
    """The kind of scan is the interface's own: the acquisition type the
    driver is given, and filed on the record from what was asked, not from
    the answer."""
    driver = _Capturing()
    scanned = _scanned(driver, [{"x": 0, "y": 0}], monkeypatch, acquisition_type="targets")
    assert driver.asked[-1][:3] == ("K00_M000000_G000000_P000000_V00", None, "targets")
    assert scanned["records"][-1]["acquisition_type"] == "targets"



# --- the scan, against a real driver -----------------------------------------


def test_a_scan_really_captures_at_every_position(mock_instrument, monkeypatch, tmp_path):
    """The whole route, with nothing stood in for.

    Every other scan test here drives a fake, which proves the bridge asks
    correctly and not that anything is captured. This one connects the mock
    driver through the controller -- the same path a Leica takes -- and looks
    on disk afterwards. What it asserts is what an operator would check: the
    files are there, one per position, named for where they were taken.
    """
    session = _a_mock_session({**mock_instrument, "output_root": str(tmp_path)})
    monkeypatch.setattr(state, "session", session)
    try:
        positions = [
            {"x": 0.0, "y": 0.0, "z": 5_000.0, "compartment": 1, "group": 1},
            {"x": 900.0, "y": 0.0, "z": 5_000.0, "compartment": 1, "group": 1},
            {"x": 0.0, "y": 700.0, "z": 5_000.0, "compartment": 2, "group": 2},
        ]
        ledgers.scan.update(
        running=True, done=0, of=len(positions), error=None, acquisition_type="overview"
    )
        state.records["overview"] = []
        scan.scan_worker(positions)
        assert ledgers.scan["error"] is None, ledgers.scan["error"]
    finally:
        session.disconnect()

    assert ledgers.scan["done"] == 3
    records = state.records["overview"]
    assert [record["position_label"] for record in records] == [
        "K00_M000001_G000001_P000000_V00",
        "K00_M000001_G000001_P000001_V00",
        "K00_M000002_G000002_P000002_V00",
    ]
    # Every capture wrote what it says it wrote, where a driver writes it.
    written = sorted((state.run / "overview" / "data").glob("*.ome.tiff"))
    assert len(written) == 3 * 3  # three positions, one file per channel
    for record in records:
        for path in (plane["path"] for plane in record["planes"]):
            assert Path(path).is_file()
            assert Path(path).parent == state.run / "overview" / "data"
    # And the state it was captured under is printed beside them, once each.
    printed = sorted(
        (state.run / "overview" / "data" / "metadata" / "ZMART_state").iterdir()
    )
    assert len(printed) == 3


def test_a_scan_stops_and_says_so_when_a_capture_fails(mock_instrument, monkeypatch, tmp_path):
    """A run that could not finish must not read as a shorter one that did.

    The driver is the real one and so is the first capture; the second is made
    to fail, because an instrument that refuses mid-run is the case worth
    covering and nothing in a mock will refuse on its own.
    """
    session = _a_mock_session({**mock_instrument, "output_root": str(tmp_path)})

    class _FailsOnTheSecond:
        """The session, with the second capture refusing."""

        def __init__(self, real):
            self._real = real
            self._made = 0

        def __getattr__(self, name):
            return getattr(self._real, name)

        def acquire(self, **asked):
            self._made += 1
            if self._made == 2:
                raise RuntimeError("the shutter did not open")
            return self._real.acquire(**asked)

    monkeypatch.setattr(state, "session", _FailsOnTheSecond(session))
    try:
        positions = [{"x": 0.0, "y": 0.0}, {"x": 900.0, "y": 0.0}, {"x": 1_800.0, "y": 0.0}]
        ledgers.scan.update(running=True, done=0, of=3, error=None, acquisition_type="overview")
        scan.scan_worker(positions)
    finally:
        session.disconnect()

    assert ledgers.scan["error"] == "the shutter did not open"
    assert ledgers.scan["done"] == 1  # the one that finished, not the one that failed
    assert ledgers.scan["running"] is False
    assert len(state.records["overview"]) == 1


# --- what the canvas is given to draw ----------------------------------------


def test_the_viewer_makes_a_picture_of_every_field_that_was_imaged(mock_instrument, monkeypatch, tmp_path):
    """OME-TIFFs are not something a browser can draw, so the viewer copies them.

    Made when something asks to look, not while the run is going: a scan
    nobody watches makes no pictures. The note says where each field belongs in
    micrometres, which is everything the viewer needs and deliberately all it
    gets -- one that had to open a TIFF to find out where to put something
    would be back to reading large files.
    """
    session = _a_mock_session({**mock_instrument, "output_root": str(tmp_path)})
    monkeypatch.setattr(state, "session", session)
    try:
        positions = [
            {"x": 0.0, "y": 0.0, "z": 5_000.0},
            {"x": 900.0, "y": 0.0, "z": 5_000.0},
        ]
        ledgers.scan.update(running=True, done=0, of=2, error=None, acquisition_type="overview")
        scan.scan_worker(positions)
        assert ledgers.scan["error"] is None, ledgers.scan["error"]

        view = pictures.view_of("overview")
        # Nothing is made while the run goes: the run only acquires.
        assert not view.exists()

        assert pictures.the_view_of("overview") is not None
        note = json.loads((view / "tiles.json").read_text(encoding="utf-8"))
    finally:
        session.disconnect()

    assert [tile["label"] for tile in note["tiles"]] == [
        "K00_M000000_G000000_P000000_V00",
        "K00_M000000_G000000_P000001_V00",
    ]
    assert all((view / tile["src"]).is_file() for tile in note["tiles"])
    # Placed where the run said it sent the stage, not where a file guessed.
    here, there = note["tiles"]
    assert here["x0"] + here["w"] / 2 == pytest.approx(0.0)
    assert there["x0"] + there["w"] / 2 == pytest.approx(900.0)
    # And the acquisition itself is untouched, kept under this run.
    assert list((state.run / "overview" / "data").glob("*.ome.tiff"))
    assert not list(view.glob("*.tiff"))


def test_nothing_is_drawn_for_a_scan_that_has_imaged_nothing(mock_instrument, monkeypatch, tmp_path):
    """A place the run has not reached has no picture, which is not an error."""
    session = _a_mock_session({**mock_instrument, "output_root": str(tmp_path)})
    monkeypatch.setattr(state, "session", session)
    try:
        ledgers.scan.update(running=False, done=0, of=0, error=None, acquisition_type="overview")
        assert pictures.the_view_of("overview") is None
    finally:
        session.disconnect()


# --- the page itself ---------------------------------------------------------


# --- discovering targets -----------------------------------------------------


class _Serial:
    """A finder that answers without pixels, one field after the other: the
    shape the bridge is handed, with the analysis engine left out."""

    def __init__(self, one):
        self.one = one
        self.widths: list[int] = []

    def __call__(self, record, field, settings):
        return self.one(record, field, settings)

    def each(self, records, settings, *, at_once, until=None):
        self.widths.append(at_once)
        for field, record in records.items():
            if until and until():
                return
            try:
                yield field, self.one(record, field, settings)
            except Exception as why:  # noqa: BLE001 -- the outcome, as the real finder files it
                yield field, why


def _an_overview_of_two_fields(monkeypatch):
    """A scanned overview to detect on, and a finder that answers without pixels."""
    records = [
        _kept("overview", position_label=f"P{i}")
        for i in range(2)
    ]
    monkeypatch.setattr(state, "records", {"overview": records})
    monkeypatch.setattr(
        discovery,
        "find_targets",
        lambda: _Serial(lambda record, field, settings: {"cells": [{
            "id": f"{record['position_label']}_obj1", "field": field,
            "x": 100.0 * field, "y": 2.0, "area": 50.0, "intensity": 3.0, "r": 4.0,
            "diameter_asked": settings.get("diameter"),
            "features": {"area": 21.0, "eccentricity": 0.5 + field}
            if field else {"area": 21.0, "solidity": 0.9},
        }], "device": "pretend-gpu"}),
    )
    return records


def _discovered(asked):
    """Start discovery and wait for it, handing back what the page would poll."""
    import time

    discovery.discover_targets(asked)
    for _ in range(200):
        if not ledgers.targets["running"]:
            break
        time.sleep(0.01)
    assert ledgers.targets["error"] is None, ledgers.targets["error"]
    return dict(ledgers.targets)


def test_targets_are_found_field_by_field_over_the_overview(monkeypatch):
    """Every field the scan captured, in the order it captured them."""
    _an_overview_of_two_fields(monkeypatch)
    got = _discovered({"settings": {"diameter": 20.0, "cellprob": 0.0}})
    assert got["done"] == got["of"] == 2
    assert [field["field"] for field in got["fields"]] == [0, 1]
    assert got["fields"][1]["cells"][0]["id"] == "P1_obj1"
    assert got["fields"][1]["cells"][0]["diameter_asked"] == 20.0
    # Which device segmented the field travels with it: a run that fell
    # back to the CPU took ten times longer without a word on the page.
    assert [field["device"] for field in got["fields"]] == ["pretend-gpu", "pretend-gpu"]


def test_one_field_can_be_tried_on_its_own(monkeypatch):
    """Settings are tried on one field before the whole overview is run."""
    _an_overview_of_two_fields(monkeypatch)
    got = _discovered({"fields": [1], "settings": {}})
    assert [field["field"] for field in got["fields"]] == [1]
    assert got["of"] == 1


def test_object_detection_ends_with_its_last_field(monkeypatch):
    """Nothing runs over the whole population after the fields: every
    feature is measured inside a field's own pipeline, so discovery is
    complete the moment the last field lands, however many there are."""
    records = _an_overview_of_two_fields(monkeypatch)
    got = _discovered({"settings": {}})
    assert got["phase"] == "complete"
    assert got["done"] == got["of"] == 2
    assert "embedding_error" not in got
    for cell in (cell for field in got["fields"] for cell in field["cells"]):
        assert not any(name.startswith("umap") for name in (cell.get("features") or {}))
    for record in records:
        kept = next((state.run / "overview" / "analysis").glob(
            f"*_{record['position_label']}_T000000_targets.json"
        ))
        assert "umap" not in kept.read_text(encoding="utf-8")


def test_the_whole_population_is_one_table_on_disk(monkeypatch):
    """Gating needs every object's features in one table, and a script
    needs it without the window: one row an object across every field,
    one column a feature, the union of what any field measured."""
    import csv

    _an_overview_of_two_fields(monkeypatch)
    _discovered({"settings": {}})
    table = state.the_run() / "overview" / "analysis" / (
        f"overview_{run_hash(state.run)}_objects.csv"
    )
    rows = list(csv.DictReader(table.open(encoding="utf-8", newline="")))
    assert [row["id"] for row in rows] == ["P0_obj1", "P1_obj1"]
    assert [row["field"] for row in rows] == ["0", "1"]
    assert [row["position_label"] for row in rows] == ["P0", "P1"]
    assert [row["x_um"] for row in rows] == ["0.0", "100.0"]
    assert list(rows[0])[:6] == ["field", "position_label", "id", "x_um", "y_um", "area"]
    assert rows[0]["eccentricity"] == "" and rows[1]["eccentricity"] == "1.5"
    assert rows[0]["solidity"] == "0.9" and rows[1]["solidity"] == ""


def test_one_field_tried_on_its_own_leaves_the_population_table_alone(monkeypatch):
    """A settings test on one field is not the population; the table of
    the last whole run stays."""
    _an_overview_of_two_fields(monkeypatch)
    _discovered({"settings": {}})
    table = state.the_run() / "overview" / "analysis" / (
        f"overview_{run_hash(state.run)}_objects.csv"
    )
    before = table.read_text(encoding="utf-8")
    _discovered({"fields": [1], "settings": {}})
    assert table.read_text(encoding="utf-8") == before


def test_fast_fields_are_found_several_at_once_and_kept_in_the_samples_order(monkeypatch):
    """The fast way hands every field to the analysis at once, takes them in
    whatever order they land, and says so while they are in flight; what the
    page reads at the end is in the order the sample was scanned."""
    _an_overview_of_two_fields(monkeypatch)
    plain = discovery.find_targets
    seen = {}

    class _Wide(_Serial):
        def each(self, records, settings, *, at_once, until=None):
            self.widths.append(at_once)
            seen["doing"] = ledgers.targets["doing"]
            for field in sorted(records, reverse=True):
                yield field, self.one(records[field], field, settings)

    finder = _Wide(plain().one)
    monkeypatch.setattr(discovery, "find_targets", lambda: finder)
    got = _discovered({"settings": {"method": "fast"}})
    assert finder.widths == [detection.width_of({"method": "fast"})]
    assert finder.widths[0] >= 2
    assert "positions at once" in seen["doing"]
    # The list stays in landing order, so a page's cursor into it holds;
    # the table on disk is in the sample's order.
    assert [field["field"] for field in got["fields"]] == [1, 0]
    assert got["done"] == 2 and got["objects"] == 2
    assert got["phase"] == "complete"
    table = next((state.run / "overview" / "analysis").glob("overview_*_objects.csv"))
    assert [line.split(",")[0] for line in table.read_text(encoding="utf-8").splitlines()[1:]] == ["0", "1"]


def test_discovery_answers_only_the_fields_since_the_ones_a_page_holds(monkeypatch):
    """A poll that carried every field found so far grew with the run: at
    three hundred fields it was 900 MB, took 26 s, and the page asked for
    it three times a second. Asked ``since`` the number it holds, the page
    gets only the fields that landed after; nothing else in the answer
    changes."""
    _an_overview_of_two_fields(monkeypatch)
    _discovered({"settings": {}})
    whole = discovery.the_targets()
    assert [field["field"] for field in whole["fields"]] == [0, 1]
    later = discovery.the_targets(since=1)
    assert [field["field"] for field in later["fields"]] == [1]
    assert later["done"] == 2 and later["phase"] == "complete"
    assert discovery.the_targets(since=2)["fields"] == []
    assert len(discovery.the_targets(since=0)["fields"]) == 2


def test_the_robust_way_finds_one_field_at_a_time(monkeypatch):
    """Every Cellpose worker holds a model on the card; one at a time."""
    _an_overview_of_two_fields(monkeypatch)
    finder = discovery.find_targets()
    monkeypatch.setattr(discovery, "find_targets", lambda: finder)
    _discovered({"settings": {"method": "robust"}})
    assert finder.widths == [1]


def test_what_was_found_is_kept_beside_the_overview(monkeypatch):
    """The targets live with the pixels they were found in, not only on screen."""
    _an_overview_of_two_fields(monkeypatch)
    _discovered({"settings": {}})
    kept = sorted((state.run / "overview" / "analysis").glob("*_targets.json"))
    assert [path.name for path in kept] == [
        "overview_P0_T000000_targets.json",
        "overview_P1_T000000_targets.json",
    ]
    assert json.loads(kept[1].read_text(encoding="utf-8"))[0]["id"] == "P1_obj1"


def test_nothing_to_discover_on_before_an_overview(monkeypatch):
    monkeypatch.setattr(state, "records", {})
    with pytest.raises(RuntimeError, match="overview"):
        discovery.discover_targets({"settings": {}})


def test_the_operators_hand_stops_discovery_between_fields(monkeypatch):
    """Interrupt ends the run after the field in hand; what was found stands."""
    _an_overview_of_two_fields(monkeypatch)
    unbraked = discovery.find_targets

    def finder():
        find = unbraked()

        def find_and_press(record, field, settings):
            cells = find(record, field, settings)
            discovery.stop_targets()
            return cells

        return _Serial(find_and_press)

    monkeypatch.setattr(discovery, "find_targets", finder)
    got = _discovered({"settings": {}})
    assert got["stopped"] is True
    assert got["done"] == 1
    assert [field["field"] for field in got["fields"]] == [0]


def test_a_field_that_fails_does_not_take_the_run_down(monkeypatch):
    """One bad field is reported and stepped over; the rest are still found.

    A run of many fields died whole when one field's analysis threw, and
    nothing short of running everything again could recover it. The run now
    files the failure beside the fields that worked, the way the focus map
    files a lost point."""
    _an_overview_of_two_fields(monkeypatch)
    good = discovery.find_targets

    def finder():
        find = good()

        def find_or_die(record, field, settings):
            if field == 0:
                raise RuntimeError("the pipeline choked on this field")
            return find(record, field, settings)

        return _Serial(find_or_die)

    monkeypatch.setattr(discovery, "find_targets", finder)
    got = _discovered({"settings": {}})
    assert [field["field"] for field in got["fields"]] == [1]
    assert got["done"] == 2
    assert got["error"] is None
    assert len(got["failed"]) == 1
    assert got["failed"][0]["field"] == 0
    assert "choked" in got["failed"][0]["why"]


def test_a_worker_put_down_by_the_hand_is_a_stop_not_a_failure(monkeypatch):
    """Interrupt may kill the analysis mid-field; the run says stopped, not error.

    The brake is allowed to reach work in flight because a killed analysis
    field loses nothing -- its pixels are on disk and detection re-runs from
    its own checkpoint -- unlike a capture, which is why the scan's brake
    waits and this one does not have to.
    """
    _an_overview_of_two_fields(monkeypatch)

    def finder():
        def find_and_die(record, field, settings):
            discovery.stop_targets()
            raise RuntimeError("worker crashed: put down by the operator")

        return _Serial(find_and_die)

    monkeypatch.setattr(discovery, "find_targets", finder)
    discovery.discover_targets({"settings": {}})
    for _ in range(200):
        if not ledgers.targets["running"]:
            break
        time.sleep(0.01)
    assert ledgers.targets["stopped"] is True
    assert ledgers.targets["error"] is None


def test_a_position_without_a_height_is_scanned_where_the_objective_stands(monkeypatch):
    """z = 0 is a coordinate, not an omission.

    The default drove every field of every scan to an absolute height of
    zero while the panel above reported a measured focus map. A position
    that names no height means "image where the objective stands", read
    once, not a drive to the frame's z-zero.
    """
    driver = _Driver()
    driver.at = {"x": 0.0, "y": 0.0, "z": -37.5}
    scanned = _scanned(driver, [{"x": 1.0, "y": 2.0}, {"x": 3.0, "y": 4.0, "z": 5.0}], monkeypatch)
    assert scanned["done"] == 2
    assert driver.drove_to[0] == (1.0, 2.0, -37.5)
    assert driver.drove_to[1] == (3.0, 4.0, 5.0)


def test_a_start_height_is_an_instruction_not_an_answer(driver):
    """`startZ` said where to begin this search; echoing it back would have
    the next run silently begin where this one did."""
    got = _measured({"points": [{"x": 1, "y": 2, "startZ": -350.0}]})
    assert "startZ" not in got["points"][0]


def test_a_reading_reads_no_drivers_own_keys(monkeypatch):
    """Only the controller's keys make the reading; the rest is the driver's own.

    A driver reports its pixel size as None when its settings cannot be read:
    that is refused in a sentence, never guessed. Whatever else it reports
    (an objective, a serial number) stands in the detail as it said it, and the
    summary is the instrument and its frame."""
    monkeypatch.setattr(state, "session", _plugged(_Optics({
        "objective": {"name": "20x"}, "image_size_px": [512, 512], "pixel_size_um": None,
    })))
    with pytest.raises(RuntimeError, match="did not report its pixel size"):
        readings.reading("acquisition")

    monkeypatch.setattr(state, "session", _plugged(_Optics({
        "objective": {"name": "20x"}, "image_size_px": [512, 512], "pixel_size_um": [0.5, 0.5],
    })))
    said = readings.reading("acquisition")
    assert said["summary"].endswith("256 × 256 µm")
    assert ["objective · name", "20x"] in said["detail"]


def test_a_fresh_connect_forgets_the_last_sessions_runs(monkeypatch, tmp_path):
    """The bridge outlives the page. A new session opened over old records
    rebuilt the previous scan's pictures into the fresh run's view, so a
    just-connected canvas showed a scan nobody had taken."""
    monkeypatch.setattr(state, "output_root", str(tmp_path))
    state.records["overview"] = [{"stale": True}]
    ledgers.scan.update(running=False, done=5, of=5, error=None, acquisition_type="overview")
    ledgers.focus.update(running=False, done=3, of=3, error=None, points=[{"x": 1}])
    try:
        connecting.connect({"instrument": mock_microscope.NAME})
        assert state.records == {}
        assert scan.the_scan()["done"] == 0 and scan.the_scan()["records"] == []
        assert ledgers.focus["points"] == []
    finally:
        connecting.disconnect()


def test_the_viewer_is_laid_out_over_the_canvas_get_xyz_reports(monkeypatch, tmp_path):
    """The viewer's area is where the driver says pictures can show, axis by axis.

    It comes from get_xyz's ``canvas`` -- the same answer a script would read
    through the controller -- so nothing above the controller needs to know
    which driver is underneath.
    """
    started = {}
    monkeypatch.setattr(
        viewer_service, "start", lambda run, **kw: started.update(kw, run=run)
    )
    monkeypatch.setattr(state, "output_root", str(tmp_path))
    try:
        connecting.connect({"instrument": mock_microscope.NAME})
        reading = state.session.get_xyz()
    finally:
        connecting.disconnect()
    assert started["canvas"] == {
        f"{axis}_um": reading[axis]["canvas"] for axis in ("x", "y", "z")
    }


def test_a_driver_that_gives_no_canvas_is_said_so_plainly():
    """A driver that does not say where its pictures can show cannot have its area laid out.

    The controller's validate_driver already refuses such a driver; the
    bridge says the same thing in words the operator can act on, rather
    than drawing an area somebody guessed.
    """
    reading = {
        "x": {"position": 0.0, "unit": "micrometer", "actuator_readings": {"motoric": 0.0}, "canvas": [-1.0, 11.0]},
        "y": {"position": 0.0, "unit": "micrometer", "actuator_readings": {"motoric": 0.0}},
        "z": {"position": 0.0, "unit": "micrometer", "actuator_readings": {"motoric": 0.0}, "canvas": [-1.0, 11.0]},
    }
    with pytest.raises(RuntimeError, match=r"does not say where its pictures can show along y"):
        connecting.the_viewers_area(reading)


def test_the_recorded_settings_reach_the_instrument_before_a_focus_map(driver):
    """The page records a focussing configuration and nothing applied it: the
    stacks were captured with whatever job the instrument had selected. And
    when something finally did, it applied the bare half the page stores —
    a shape the driver reads ``changeable`` off and finds nothing in. The
    driver's own contract is asserted here, wrapper and all."""
    _measured({"points": [{"x": 1, "y": 2}], "state": {"job": "ZStack"}})
    assert driver.applied == [{"changeable": {"job": "ZStack"}}]
    assert driver.captured, "and the capture still happened"


def test_the_recorded_settings_reach_the_instrument_before_a_scan(monkeypatch):
    driver = _Driver()
    scanned = _scanned(driver, [{"x": 1.0, "y": 2.0, "z": 0.0}], monkeypatch,
                       recorded={"job": "Overview"})
    assert driver.applied == [{"changeable": {"job": "Overview"}}]
    assert scanned["done"] == 1


def test_the_view_is_built_once_per_scan_state(monkeypatch, tmp_path):
    """Every file request rebuilt the whole view, and two rebuilding at once
    interleaved their writes into a corrupt note that 400d every request
    after. One builder at a time, and only when the scan has grown."""
    import sys
    import types

    built = []
    stub = types.ModuleType("target_acquisition.storage.jpeg_tiles")
    stub.make_what_is_missing = lambda into, fields: built.append(len(fields)) or Path(into)
    monkeypatch.setitem(sys.modules, "target_acquisition.storage.jpeg_tiles", stub)
    record = _kept("overview", position_label="P0")
    monkeypatch.setattr(state, "records", {"overview": [record]})
    monkeypatch.setattr(state, "view_built", {})

    (state.run / "overview" / "view").mkdir(parents=True)
    (state.run / "overview" / "view" / "tiles.json").write_text("{}", encoding="utf-8")
    pictures.the_view_of("overview")
    pictures.the_view_of("overview")
    assert built == [1], "the second request found nothing new to build"

    state.records["overview"].append(
        _kept("overview", position_label="P1"))
    pictures.the_view_of("overview")
    assert built == [1, 2], "a grown scan is built again"


def test_a_field_that_lands_during_a_build_is_not_signed_off_as_built(monkeypatch):
    """The 8932-field scan ended one stride short, for good: the builder took
    a live reference to the records, built the fields it saw, and then signed
    itself done with the list's length -- measured after the scan had grown
    under it. The 46 fields that landed during the last build were never
    encoded, and no later request would ever build them. What was built is
    all that may be signed for."""
    import sys
    import types

    built = []
    stub = types.ModuleType("target_acquisition.storage.jpeg_tiles")

    def build(into, fields):
        built.append(len(fields))
        if len(built) == 1:
            state.records["overview"].append(
                _kept("overview", position_label="P1"))
        return Path(into)

    stub.make_what_is_missing = build
    monkeypatch.setitem(sys.modules, "target_acquisition.storage.jpeg_tiles", stub)
    record = _kept("overview", position_label="P0")
    monkeypatch.setattr(state, "records", {"overview": [record]})
    monkeypatch.setattr(state, "view_built", {})
    (state.run / "overview" / "view").mkdir(parents=True)
    (state.run / "overview" / "view" / "tiles.json").write_text("{}", encoding="utf-8")

    pictures.the_view_of("overview")
    pictures.the_view_of("overview")
    assert built == [1, 2], "the field that landed mid-build was signed off unbuilt"


def test_a_measured_point_names_the_slices_of_the_stack_it_kept(monkeypatch):
    """What the preview shows is the stack the point really captured.

    The worker asks the viewer for small copies of the stack's planes as the
    point lands, and the point carries their names and heights to the page;
    where they are fetched from stays `viewOf`'s answer. A stack that cannot
    be copied costs the preview, never the run -- which is also why the
    copier is stubbed here the way the view builder is."""
    import sys
    import types

    handed = []
    stub = types.ModuleType("target_acquisition.storage.jpeg_tiles")
    stub.make_slice_copies = lambda into, planes: (
        handed.append(planes) or [{"z_um": 1.0, "name": "s_Z00000.jpg"}])
    monkeypatch.setitem(sys.modules, "target_acquisition.storage.jpeg_tiles", stub)
    monkeypatch.setattr(state, "session", _plugged(_Driver()))

    point = _measured({"points": [{"x": 1.0, "y": 2.0}]})["points"][0]
    assert point["slices"] == [{"z_um": 1.0, "name": "s_Z00000.jpg"}]
    assert handed and len(handed[0]) > 0, "the record's planes reached the copier"
    assert all("path" in plane and "z_um" in plane for plane in handed[0])


def test_a_scan_started_again_removes_the_stores_it_will_not_rewrite(monkeypatch):
    """A rerun accounts for exactly what it captured.

    The position stores and the display copies of the last run stayed on
    disk, so a shorter rerun showed fields it never captured, and the viewer
    kept listing every store it had once seen. A store the new plan writes
    again stays, and is replaced in place as it lands; a store beyond the new
    plan is stale: it is removed, and the viewer service is told so that
    the page finds out at once."""
    told = []
    monkeypatch.setattr(
        viewer_service, "stores_were_retired",
        lambda kind, folder: told.append((kind, Path(folder))),
    )
    positions = state.run / "positions" / "overview"
    kept = positions / "overview_K00_M000000_G000000_P000000_V00.ome.zarr"
    stale = positions / "overview_K00_M000000_G000000_P000002_V00.ome.zarr"
    for store in (kept, stale):
        store.mkdir(parents=True)
        (store / "zarr.json").write_text("{}", encoding="utf-8")
    aggregate = positions / ".zmart-viewer" / "overview.ome.zarr"
    aggregate.mkdir(parents=True)
    (aggregate / "publication.json").write_text("published", encoding="utf-8")
    note = positions / "notes.txt"
    note.write_text("keep", encoding="utf-8")
    half_written = state.run / "positions" / ".writing" / "x"
    half_written.mkdir(parents=True)
    copies = pictures.view_of("overview")
    copies.mkdir(parents=True)
    (copies / "tiles.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(state, "view_built", {"overview": 3})

    pictures.replace_the_acquisition("overview", keeping={kept.name})

    assert told == [("overview", positions)]
    assert kept.is_dir(), "a store the new plan writes again stays for in-place replacement"
    assert not stale.exists()
    assert (aggregate / "publication.json").read_text(encoding="utf-8") == "published"
    assert note.read_text(encoding="utf-8") == "keep"
    assert not half_written.parent.exists()
    assert not copies.exists()
    assert "overview" not in state.view_built


def test_a_scan_that_only_grows_keeps_the_viewer_open(monkeypatch):
    """Declaring the same positions again, plus more, is growth, not a rerun
    that shrinks: nothing is stale, so nothing is removed or announced and
    the picture is not reopened."""
    told = []
    monkeypatch.setattr(
        viewer_service, "stores_were_retired",
        lambda kind, folder: told.append(kind),
    )
    positions = state.run / "positions" / "overview"
    kept = positions / "overview_K00_M000000_G000000_P000000_V00.ome.zarr"
    kept.mkdir(parents=True)
    (positions / ".zmart-viewer").mkdir()
    pictures.replace_the_acquisition("overview", keeping={kept.name, "overview_next.ome.zarr"})
    assert told == []
    assert kept.is_dir()


@pytest.mark.parametrize("bake", [False, True])
def test_shorter_rerun_preserves_the_live_aggregate_and_republishes_coverage(monkeypatch, bake):
    from zmart_viewer import STORE, PublishedAcquisition

    from ..storage.images import declare_image
    from ..storage.zarr_positions import _describe_mean_pyramid

    positions = state.run / "positions" / "overview"
    names = ["overview_kept.ome.zarr", "overview_retired.ome.zarr"]
    for index, name in enumerate(names):
        store = positions / name
        arrays = declare_image(
            store, canvas_shape=(1, 32, 32), frames=1, channels=1,
            dtype="uint16", chunk=16, levels=2, voxel_size_um=(1, 1, 1),
            channel_blocks=[{"label": "signal", "color": "FFFFFF"}],
            first_voxel_um=(0, 0.5, index * 64 + 0.5), ome_zarr_version="0.5",
        )
        for array in arrays:
            array[:] = (index + 1) * 100
        description_path = store / "zarr.json"
        description = json.loads(description_path.read_text(encoding="utf-8"))
        _describe_mean_pyramid(description)
        description_path.write_text(json.dumps(description), encoding="utf-8")
    canvas = {"x_um": [0, 128], "y_um": [0, 64]}
    view = PublishedAcquisition(positions, piece=16)

    def publish(held):
        view.publish(positions, dict.fromkeys(held, 1), canvas, bake=bake, composition={
            "regions": "complete", "order": held,
            "pyramid_reduction": "mean-xy2-crop-f32-rint-int",
        })

    try:
        publish(names)
        derived = {path: path.read_bytes() for path in (positions / ".zmart-viewer").rglob("*") if path.is_file()}
        original = {path: path.read_bytes() for path in (positions / names[0]).rglob("*") if path.is_file()}
        told = []
        monkeypatch.setattr(viewer_service, "stores_were_retired", lambda *args: told.append(args))
        pictures.replace_the_acquisition("overview", keeping={names[0]})
        assert told == [("overview", positions)]
        assert all(path.read_bytes() == content for path, content in derived.items())
        publish(names[:1])
        composer = view.outputs[STORE].composer()
        for level in range(composer.mosaic.levels):
            assert composer.values_for(level, 0, 0, 0)[0, 0] == 100
            assert composer.coverage_for(level, 0, 0, 0)[0, 0] == 1
            column, pixel = divmod(64 // 2**level, 16)
            values = composer.values_for(level, 0, 0, column)
            assert values is None or values[0, pixel] == 0
            assert composer.coverage_for(level, 0, 0, column)[0, pixel] == 0
        assert all(path.read_bytes() == content for path, content in original.items())
    finally:
        view.close()


def test_starting_a_scan_names_the_stores_it_keeps_by_the_new_plan(driver, monkeypatch):
    # The scan's thread is never started here, so its "running" is put back after.
    monkeypatch.setitem(ledgers.scan, "running", False)
    asked = []
    monkeypatch.setattr(pictures, "replace_the_acquisition", lambda kind, keeping: asked.append((kind, keeping)))
    monkeypatch.setattr(threading, "Thread", lambda **kw: type("T", (), {"start": lambda self: None})())
    scan.start_scan({"positions": [{"x": 0, "y": 0}, {"x": 1, "y": 0}], "acquisition_type": "overview"})
    assert asked == [("overview", {
        "overview_K00_M000000_G000000_P000000_V00.ome.zarr",
        "overview_K00_M000000_G000000_P000001_V00.ome.zarr",
    })]



def test_a_copy_is_drawn_with_the_display_the_page_asks_with(mock_instrument, monkeypatch, tmp_path):
    """The preview and the gallery must show what the canvas shows.

    Asked with the picture's own windows and colours, the bridge draws the
    field that way, on request; hidden channels add nothing, so a display
    that hides every channel is a black picture -- the one answer that can
    be known without knowing the mock's pixels.
    """
    import io
    import urllib.parse

    from PIL import Image

    session = _a_mock_session({**mock_instrument, "output_root": str(tmp_path)})
    monkeypatch.setattr(state, "session", session)
    try:
        ledgers.scan.update(running=True, done=0, of=1, error=None, acquisition_type="overview")
        scan.scan_worker([{"x": 0.0, "y": 0.0, "z": 5_000.0}])
        assert ledgers.scan["error"] is None, ledgers.scan["error"]
        label = state.records["overview"][0]["position_label"]

        def ask(display):
            query = "" if display is None else "display=" + urllib.parse.quote(json.dumps(display))
            answer = pictures.a_picture({}, query, f"overview/{label}.jpg")
            assert answer.content_type == "image/jpeg"
            return Image.open(io.BytesIO(answer.body)).convert("RGB")

        plain = ask(None)
        dark = ask([{"c": c, "visible": False, "window": [0, 4000], "color": "#ffffff"} for c in range(3)])
        lit = ask([{"c": 0, "visible": True, "window": [0, 1], "color": "#ff0000"}])
    finally:
        session.disconnect()

    assert max(dark.getextrema()[band][1] for band in range(3)) <= 3, "every channel hidden is a black copy"
    # Channel 0 windowed to nothing is fully red wherever it has any signal at all.
    red, green, blue = lit.getextrema()
    assert red[1] >= 250 and green[1] <= 3 and blue[1] <= 3
    # A displayed copy is the whole frame -- the operator judges a diameter
    # against it -- where the plain copy is the small one the scan view wears.
    assert dark.size == lit.size
    assert lit.size[0] >= plain.size[0]



def test_a_targets_scan_publishes_separate_originals_and_raises_by_order(mock_instrument, monkeypatch, tmp_path):
    """The viewer owns composition; the bridge only publishes originals and order."""
    session = _a_mock_session({**mock_instrument, "output_root": str(tmp_path)})
    monkeypatch.setattr(state, "session", session)
    monkeypatch.setattr(state, "run", prepare_experiment(str(tmp_path), protocols.EXPERIMENT))
    try:
        positions = [{"x": 1000.0, "y": 1000.0, "z": 0.0}, {"x": 1060.0, "y": 1000.0, "z": 0.0}]
        scan.start_scan({"positions": positions, "acquisition_type": "targets"})
        for _ in range(200):
            if not ledgers.scan["running"]:
                break
            time.sleep(0.1)
        assert ledgers.scan["error"] is None, ledgers.scan["error"]
        assert ledgers.scan["done"] == 2
        assert not [r.get("zarr_error") for r in ledgers.scan["records"] if r.get("zarr_error")]
        watched = sorted(p.name for p in (state.the_run() / "positions" / "targets").iterdir())
        assert len(watched) == 2 and all(name.startswith("targets_") for name in watched)
        originals = {p: p.read_bytes() for p in (state.the_run() / "positions" / "targets").rglob("*") if p.is_file()}
        raised = []
        monkeypatch.setattr(viewer_service, "raise_position", lambda *args: raised.append(args))
        label = state.records["targets"][0]["position_label"]
        assert targets.raise_target({"position_label": label}) == {"raised": label}
        assert raised == [("targets", state.the_run() / "positions" / "targets",
                           Path(state.records["targets"][0]["zarr"]))]
        assert all(p.read_bytes() == data for p, data in originals.items())
        with pytest.raises(ValueError):
            targets.raise_target({"position_label": "nobody"})
    finally:
        session.disconnect()


def test_targets_are_really_focussed_and_taken_on_the_mock(mock_instrument, monkeypatch, tmp_path):
    """The target run with focussing on, with nothing stood in for: the
    mock driver through the controller, the focussing stack filed under its
    own acquisition and scored, the target taken at the peak."""
    _needs_the_analysis_environment("ZMART--focus--main")
    session = _a_mock_session({**mock_instrument, "output_root": str(tmp_path)})
    monkeypatch.setattr(state, "session", session)
    # A short run folder: under pytest's own, named after this test, the
    # store's chunk files ran past Windows' 260 characters and the
    # conversion failed on the path alone.
    monkeypatch.setattr(state, "run", Path(tempfile.mkdtemp(prefix="zmt-")) / "run")
    state.run.mkdir()
    # What connect does: the session saves into this run, and the analysis writes into it.
    session.run = state.run
    monkeypatch.setattr(warm, "run_folder", None)
    monkeypatch.setattr(warm, "_analysis", None)
    warm.open(state.run)
    # The real scorer, through the warm analysis: this test is about the
    # whole route, and the fake one reads a height the mock does not write.
    monkeypatch.setattr(focus, "score_a_stack", lambda: focus_score.through(warm.the_analysis()))
    kept = []
    real_keep = pictures.keep_position_as_zarr
    monkeypatch.setattr(pictures, "keep_position_as_zarr", lambda record, kind: (real_keep(record, kind), kept.append((kind, record))))
    try:
        # The map first, as a run has it: the coarse job finds the tissue
        # from wherever the objective stands, and the target is driven to
        # that height before its fine stack -- a short one in fine steps,
        # which only reaches the tissue from near it.
        coarse = _measured({"points": [{"x": 0.0, "y": 0.0}], "state": {"job": "Focussing"}})["points"][0]
        assert coarse["z"] is not None, "the coarse job found no tissue"
        readings.apply_state({"job": "Target focussing"})
        got = _targets_taken(
            [{"x": 0.0, "y": 0.0, "z": coarse["z"], "compartment": 1, "group": 1}], focus=True,
        )
    finally:
        session.disconnect()
    assert got["done"] == 1
    record = state.records["targets"][0]
    stack = next(one for kind, one in kept if kind == "target-focussing")
    assert stack.get("zarr_error") is None, stack["zarr_error"]
    assert len(stack["planes"]) > 1, "the Focussing job takes a stack"
    assert record["focus"]["found"] is True
    assert (state.run / "target-focussing" / "data").is_dir()
    assert list((state.run / "positions" / "target-focussing").glob("*.ome.zarr"))
    assert list((state.run / "positions" / "targets").glob("*.ome.zarr"))


# --- the multidimensional plots ---------------------------------------------


def _plotted(asked):
    """Start a plot and wait for it, handing back what the page would poll."""
    import time

    plots.compute_plot(asked)
    for _ in range(600):
        if not ledgers.plots["running"]:
            break
        time.sleep(0.05)
    return dict(ledgers.plots)


def test_a_plot_needs_the_population_table(monkeypatch):
    """Nothing to plot before the whole overview has been detected."""
    _an_overview_of_two_fields(monkeypatch)
    with pytest.raises(RuntimeError, match="whole overview"):
        plots.compute_plot({"kind": "pca"})


def test_the_components_are_computed_apart_and_handed_back_as_columns(monkeypatch):
    """The page names the kind and the ids; the bridge runs the plot in a
    process of its own over the population table and answers the two
    columns an object, by id."""
    _an_overview_of_two_fields(monkeypatch)
    _discovered({"settings": {}})
    asked = {}

    def pretend(kind, table, ids):
        asked.update(kind=kind, table=table, ids=ids)
        out = table.with_name(table.name.replace("_objects.csv", "_pca.csv"))
        out.write_text("id,pca_1,pca_2\nP0_obj1,1.5,-2.0\nP1_obj1,0.5,3.0\n", encoding="utf-8")
        return {"written": {"pca": str(out)}, "objects": 2, "features": ["area"]}

    monkeypatch.setattr(plots, "plot_through_the_analysis", pretend)
    got = _plotted({"kind": "pca", "ids": ["P1_obj1", "P0_obj1"]})
    assert got["error"] is None and got["kinds"] == ["pca"] and got["running"] is False
    assert got["objects"] == 2
    assert asked["kind"] == "pca" and asked["ids"] == ["P1_obj1", "P0_obj1"]
    assert asked["table"].name == f"overview_{run_hash(state.run)}_objects.csv"
    columns = plots.plot_columns("pca")
    assert columns == {"columns": ["pca_1", "pca_2"], "ids": ["P0_obj1", "P1_obj1"],
                       "values": [[1.5, 0.5], [-2.0, 3.0]]}


def test_a_plot_is_refused_while_one_runs_or_detection_runs(monkeypatch):
    _an_overview_of_two_fields(monkeypatch)
    _discovered({"settings": {}})
    ledgers.plots["running"] = True
    try:
        with pytest.raises(RuntimeError, match="already"):
            plots.compute_plot({"kind": "pca"})
    finally:
        ledgers.plots["running"] = False
    ledgers.targets["running"] = True
    try:
        with pytest.raises(RuntimeError, match="detect"):
            plots.compute_plot({"kind": "pca"})
    finally:
        ledgers.targets["running"] = False


def test_a_stopped_plot_says_so_and_a_failed_one_says_why(monkeypatch):
    _an_overview_of_two_fields(monkeypatch)
    _discovered({"settings": {}})

    put_down = []
    monkeypatch.setattr(warm, "close", lambda: put_down.append(True))

    def until_stopped(kind, table, ids):
        # The hand's Interrupt puts the analysis worker down, and the job
        # in it dies of that: the death is the stop, not a failure.
        plots.stop_plot()
        raise RuntimeError("the worker went away")

    monkeypatch.setattr(plots, "plot_through_the_analysis", until_stopped)
    got = _plotted({"kind": "umap"})
    assert got["stopped"] is True and got["error"] is None and put_down == [True]

    def failing(kind, table, ids):
        raise RuntimeError("only 2 objects; a plot needs at least 10")

    monkeypatch.setattr(plots, "plot_through_the_analysis", failing)
    got = _plotted({"kind": "umap"})
    assert got["error"] == "only 2 objects; a plot needs at least 10"


def test_the_components_are_really_computed_over_a_detected_population(monkeypatch, tmp_path):
    """The whole route through the analysis, on the table discovery wrote:
    twelve objects, the components landing by id."""
    _needs_the_analysis_environment("ZMART--object_analysis--umap")
    monkeypatch.setattr(warm, "run_folder", None)
    monkeypatch.setattr(warm, "_analysis", None)
    warm.open(tmp_path)
    records = [
        _kept("overview", position_label=f"P{i}") for i in range(12)
    ]
    monkeypatch.setattr(state, "records", {"overview": records})
    monkeypatch.setattr(
        discovery, "find_targets",
        lambda: _Serial(lambda record, field, settings: {"cells": [{
            "id": f"{record['position_label']}_obj1", "field": field, "x": 1.0 * field, "y": 0.0,
            "area": 10.0 + field, "intensity": 3.0, "r": 4.0,
            "features": {"area": 10.0 + field, "eccentricity": (field % 3) / 3, "solidity": 1 - field / 20},
        }], "device": "cpu"}),
    )
    _discovered({"settings": {}})
    got = _plotted({"kind": "pca"})
    assert got["error"] is None, got["error"]
    columns = plots.plot_columns("pca")
    assert columns["columns"] == ["pca_1", "pca_2"]
    assert sorted(columns["ids"]) == sorted(f"P{i}_obj1" for i in range(12))


# ---- the protocol: the run's settings, written beside its pictures

def test_a_finished_run_writes_its_protocol_where_the_next_session_lists_it(monkeypatch):
    with tempfile.TemporaryDirectory() as root:
        run = Path(root) / "target-acquisition_a1b2c3"
        run.mkdir()
        monkeypatch.setattr(state, "run", run)
        monkeypatch.setattr(protocols, "PROTOCOL_LIBRARY", Path(root) / "protocols")
        written = protocols.save_protocol({"protocol": {"version": 1, "carrier": {"rows": 2}}})
        assert Path(written["written"]) == run / "protocol.json"
        assert json.loads((run / "protocol.json").read_text(encoding="utf-8")) == {
            "version": 1, "carrier": {"rows": 2}}

        older = Path(root) / "target-acquisition_000000"
        older.mkdir()
        (older / "protocol.json").write_text('{"version": 1, "carrier": {"rows": 1}}', encoding="utf-8")
        # an earlier run, written earlier
        import os
        stamp = time.time() - 3600
        os.utime(older / "protocol.json", (stamp, stamp))
        broken = Path(root) / "target-acquisition_ffffff"
        broken.mkdir()
        (broken / "protocol.json").write_text("{not json", encoding="utf-8")

        listed = protocols.protocols()["protocols"]
        assert [one["id"] for one in listed] == ["target-acquisition_a1b2c3", "target-acquisition_000000"]
        assert listed[1]["protocol"] == {"version": 1, "carrier": {"rows": 1}}


def test_a_saved_protocol_lives_in_the_library_and_is_listed_with_the_runs(monkeypatch):
    with tempfile.TemporaryDirectory() as root:
        monkeypatch.setattr(protocols, "PROTOCOL_LIBRARY", Path(root) / "protocols")
        monkeypatch.setattr(state, "run", None)
        monkeypatch.setattr(state, "output_root", None)
        written = protocols.save_protocol_to_library({"protocol": {"version": 1}, "name": "kidney / 20x"})
        assert Path(written["written"]).name == "kidney _ 20x.json"
        listed = protocols.protocols()["protocols"]
        assert [one["id"] for one in listed] == ["kidney _ 20x"]
        assert listed[0]["saved"] is True
        unnamed = protocols.save_protocol_to_library({"protocol": {"version": 1}})
        assert Path(unnamed["written"]).suffix == ".json"
        assert len(protocols.protocols()["protocols"]) == 2


def test_without_a_session_there_is_no_protocol_to_list_or_write(monkeypatch, tmp_path):
    monkeypatch.setattr(state, "run", None)
    monkeypatch.setattr(state, "output_root", None)
    monkeypatch.setattr(protocols, "PROTOCOL_LIBRARY", tmp_path / "protocols")
    assert protocols.protocols() == {"protocols": []}
    with pytest.raises(RuntimeError, match="no session"):
        protocols.save_protocol({"protocol": {}})


def test_before_a_session_the_list_comes_from_the_interfaces_own_folder(monkeypatch):
    """Before connecting, the runs are listed from where the interface puts them, never from a driver's entry."""
    with tempfile.TemporaryDirectory() as root:
        run = Path(root) / "target-acquisition_a1b2c3"
        run.mkdir()
        (run / "protocol.json").write_text('{"version": 1}', encoding="utf-8")
        monkeypatch.setattr(state, "run", None)
        monkeypatch.setattr(protocols, "PROTOCOL_LIBRARY", Path(root) / "library")
        monkeypatch.setattr(state, "output_root", root)
        listed = protocols.protocols()["protocols"]
        assert [one["id"] for one in listed] == ["target-acquisition_a1b2c3"]
        assert listed[0]["protocol"] == {"version": 1}
        # Without a folder of its own, only the saved ones are listed, until connected.
        monkeypatch.setattr(state, "output_root", None)
        assert protocols.protocols({"client": "mock-client", "output_root": root})["protocols"] == []


def test_the_microscopes_offered_are_the_interfaces_mock_then_the_registered_drivers(tmp_path):
    """The Connect step offers the interface's mock, then the controller's list of drivers.

    A driver installed once on the computer (its folder, with
    ``zmart_controller_plugin/``, registered) appears by its name, and connect plugs it in by that name with
    the connection the file gives. The interface's mock is offered once,
    installed or not. A name that is not listed is refused before anything is
    imported.
    """
    plugin = tmp_path / "beads" / "zmart_controller_plugin"
    plugin.mkdir(parents=True)
    (plugin / "zmart_controller_plugin.py").write_text(
        "from zmart_controller.template.zmart_controller_plugin.zmart_controller_plugin import (\n"
        "    ZmartControllerPlugin,\n"
        ")\n"
    )
    (plugin / "zmart_controller_plugin.json").write_text(json.dumps({
        "name": "beads", "connection": {"mock_timing": "instant"},
    }))
    register_driver(plugin.parent)
    register_driver(Path(mock_microscope.__file__).parent)

    assert [one["name"] for one in connecting.instruments()] == ["interface-mock", "beads"]
    assert connecting.saved_connection("beads") == {"mock_timing": "instant"}
    # As the interface offers it: with its own window opened beside the session.
    assert connecting.saved_connection("interface-mock") == {
        **mock_microscope.CONNECTION, "client": "mock-client", "open_window": True,
    }
    with pytest.raises(ValueError, match="no microscope is listed as 'os'"):
        connecting.connect({"instrument": "os"})
