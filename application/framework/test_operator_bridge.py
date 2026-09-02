"""The operator page's bridge, held to the driver contract it speaks to.

Every fault these cover was invisible from the page: the window drew a focus
map, the rows filled with numbers, and every number was a zero. What the page
cannot see is which key a driver puts its answer under, so that is what is
asserted here — against stubs shaped exactly like the drivers in this repo.

The module is loaded by path rather than by name, so that nothing on the way
to it can pull in a package the bridge itself refuses to need. It wants the
standard library and :mod:`zmart_controller` and no more, which is the property
worth keeping: it runs on a microscope PC with nothing installed on it.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import time
from pathlib import Path

import pytest

def _load_bridge():
    spec = importlib.util.spec_from_file_location(
        "operator_bridge", Path(__file__).parent / "bridge.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bridge = _load_bridge()


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
        self.captured: list[tuple] = []
        self.applied: list[dict] = []
        self.height_key = height_key
        self.staging = Path(tempfile.mkdtemp(prefix="zmart-driver-"))

    def get_xyz(self) -> dict:
        return {axis: {"value": v, "unit": "um"} for axis, v in self.at.items()}

    def set_state(self, state: dict) -> dict:
        self.applied.append(dict(state))
        return {"applied": dict(state)}

    def set_xyz(self, x, y, z, **_kw) -> dict:
        self.drove_to.append((x, y, z))
        self.at = {"x": float(x), "y": float(y), "z": float(z)}
        return {"position": {"x": x, "y": y, "z": z}, "actuators": {"z": "motoric"}}

    def acquire(self, *, acquisition_type, position_label, options=None) -> dict:
        """A focussing capture: a stack around wherever the stage is standing."""
        self.captured.append((acquisition_type, position_label))
        where = self.staging / acquisition_type
        where.mkdir(parents=True, exist_ok=True)
        planes = []
        for index in range(5):
            path = where / f"{position_label}_Z{index:05d}.tiff"
            path.write_bytes(b"a plane")
            planes.append({
                "t": 0, "c": 0, "z": index, "path": str(path),
                "x_um": self.at["x"], "y_um": self.at["y"], "z_um": self.at["z"],
            })
        return {
            "acquisition_type": acquisition_type,
            "acquisition_hash": "aaaaaa",
            "position_label": position_label,
            "images": [plane["path"] for plane in planes],
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
    monkeypatch.setattr(bridge, "_session", stub)
    return stub


# --- driving the stage -------------------------------------------------------


def test_a_drive_answers_with_the_position_the_move_reported(driver):
    """No second read: set_xyz is confirmed and says where it went."""
    went = bridge._drive_to({"x": 61_000, "y": 42_000, "z": -380})
    assert driver.drove_to[-1] == (61_000.0, 42_000.0, -380.0)
    assert {axis: reading["value"] for axis, reading in went.items()} == {
        "x": 61_000.0,
        "y": 42_000.0,
        "z": -380.0,
    }
    assert all(reading["unit"] == "um" for reading in went.values())


def test_an_axis_not_asked_about_is_left_where_it_stands(driver):
    """Driving across the plate is not a request to move the objective."""
    bridge._drive_to({"x": 20_000, "y": 30_000, "z": -390})
    bridge._drive_to({"x": 25_000})
    assert driver.drove_to[-1] == (25_000.0, 30_000.0, -390.0)


def test_a_driver_that_names_no_position_is_asked_where_it_ended_up(monkeypatch):
    """Some may confirm the move and say nothing about where."""

    class Quiet(_Driver):
        def set_xyz(self, x, y, z, **_kw):
            self.at = {"x": float(x), "y": float(y), "z": float(z)}
            return {"ok": True}

    monkeypatch.setattr(bridge, "_session", Quiet())
    went = bridge._drive_to({"x": 7, "y": 8, "z": 9})
    assert {axis: reading["value"] for axis, reading in went.items()} == {
        "x": 7.0,
        "y": 8.0,
        "z": 9.0,
    }


# --- the focus map -----------------------------------------------------------


def _measured(asked):
    """Start a focus map and wait for it, handing back what the page would poll."""
    import time

    bridge._measure_focus(asked)
    for _ in range(200):
        if not bridge._focus["running"]:
            break
        time.sleep(0.01)
    assert bridge._focus["error"] is None, bridge._focus["error"]
    return dict(bridge._focus)


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
    assert [kind for kind, _label in driver.captured] == ["focussing"] * 2


def test_a_measured_point_carries_the_curve_it_was_chosen_from(driver):
    """A height alone cannot be argued with; the plot is how it shows its work."""
    got = _measured({"points": [{"x": 1, "y": 2}]})
    assert got["points"][0]["traces"] == {"brenner": {}}


@pytest.fixture(autouse=True)
def _nothing_scanned_yet(monkeypatch):
    """What one test's scan captured is not the next test's overview."""
    monkeypatch.setattr(bridge, "_records", {})


@pytest.fixture(autouse=True)
def _a_run_to_write_into(tmp_path, monkeypatch):
    """A run folder, as connecting would have made.

    These tests set the session directly instead of connecting, so they get
    the other half of a session too: everything a run captures goes under its
    own folder, and without one there is nothing to write into.
    """
    run = tmp_path / "target-acquisition_000001"
    run.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(bridge, "_run", run)
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
        bridge,
        "_score_a_stack",
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
    bridge._drive_to({"x": 0, "y": 0, "z": -300.0})
    _measured({"points": [{"x": 5, "y": 6}]})
    assert driver.drove_to[-1] == (5.0, 6.0, -300.0)


def test_a_point_nothing_could_be_chosen_from_reports_no_height(monkeypatch):
    """None, not zero.

    The page fits a surface through what it is given, so one invented zero
    drags the whole map towards a place nobody measured.
    """
    monkeypatch.setattr(bridge, "_session", _Driver(height_key=None))
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
    monkeypatch.setattr(bridge, "_session", _Optics(observed))
    return bridge._reading("acquisition")["frameUm"]


def test_a_frame_size_is_read_the_way_a_pixel_size_is(monkeypatch):
    """Measured beats derived.

    `frame_size`, shaped like `pixel_size`: LAS X's ``imageSize``, parsed by
    the driver into micrometres per axis. A format times a pixel size is
    arithmetic on two rounded numbers that can disagree with it. Only `x` is
    read — a plan is laid in square frames.
    """
    assert _frame(
        {"pixel_size": {"x": 0.33}, "frame_size": {"x": 676.4, "y": 676.4, "unit": "um"}},
        monkeypatch) == 676


def test_the_format_and_the_pixel_size_make_the_frame(monkeypatch):
    """When no field of view is reported, the format is what says how wide it
    is — and the format changes, which is the whole point."""
    assert _frame(
        {"pixel_size": {"x": 0.33}, "format": "2048 x 2048"}, monkeypatch) == 676
    assert _frame(
        {"pixel_size": {"x": 0.33}, "format": "512 x 512"}, monkeypatch) == 169


def test_a_format_said_as_numbers_counts_the_same(monkeypatch):
    """A driver may say it as a pair rather than as a string."""
    assert _frame(
        {"pixel_size": {"x": 0.5}, "pixels_x": 1024, "pixels_y": 1024}, monkeypatch) == 512


def test_an_instrument_that_says_neither_gets_a_guess(monkeypatch):
    """And it is a guess, not a measurement: 512 px is a stand-in for a format
    nobody reported, kept only so the page has a frame to draw at all."""
    assert _frame({"pixel_size": {"x": 1.0}}, monkeypatch) == bridge._A_GUESSED_FORMAT_PX


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
        def get_acquisition_options(self):
            return menu

    monkeypatch.setattr(bridge, "_session", Offering())
    assert bridge._acquisition_options() == menu


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

    monkeypatch.setattr(bridge, "_session", Settable())
    answered = bridge._apply_state({"job": "HiRes"})
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

    def acquire(self, *, acquisition_type, position_label, options=None):
        self.asked.append((acquisition_type, position_label, options))
        where = self.staging / acquisition_type
        where.mkdir(parents=True, exist_ok=True)
        path = where / f"{position_label}.tiff"
        path.write_bytes(b"a plane")
        return {
            "acquisition_type": acquisition_type,
            "position_label": position_label,
            "images": [str(path)],
            "planes": [{"t": 0, "z": 0, "c": 0, "path": str(path),
                        "x_um": 0.0, "y_um": 0.0, "z_um": 0.0}],
        }


def test_a_capture_answers_with_the_record_the_driver_made(monkeypatch):
    """The record is the half nothing else can reconstruct.

    Where a run will land is in `get_info`; what one capture wrote is only
    known to the capture — a driver names its own files, and one acquisition
    can be many planes. Answered whole rather than picked over.
    """
    driver = _Capturing()
    monkeypatch.setattr(bridge, "_session", driver)
    record = bridge._capture({
        "acquisition_type": "overview",
        "position_label": "K00_M000001_G000000_P000007_V00",
    })
    assert [Path(p).name for p in record["images"]] == [
        "K00_M000001_G000000_P000007_V00.tiff"
    ]
    assert record["planes"][0]["c"] == 0


def test_the_options_a_capture_is_given_reach_the_driver(monkeypatch):
    """Straight from the menu the page read, straight back to the driver.

    Omitted ones the driver fills from its own actives, which is why nothing
    here invents a default.
    """
    driver = _Capturing()
    monkeypatch.setattr(bridge, "_session", driver)
    bridge._capture({
        "acquisition_type": "target",
        "position_label": "K00_M000002_G000001_P000003_V00",
        "options": {"format": "ome-zarr"},
    })
    assert driver.asked[-1] == (
        "target", "K00_M000002_G000001_P000003_V00", {"format": "ome-zarr"},
    )


# --- the scan ----------------------------------------------------------------


def _scanned(driver, positions, monkeypatch, **asked):
    """Run a scan to completion on this driver and hand back what it kept."""
    monkeypatch.setattr(bridge, "_session", driver)
    kind = asked.get("acquisition_type", "overview")
    bridge._records[kind] = []
    bridge._scan.update(running=True, done=0, of=len(positions), error=None, acquisition_type=kind)
    bridge._scan_worker(positions, **asked)
    assert bridge._scan["error"] is None, bridge._scan["error"]
    return bridge._the_scan()


def test_a_scan_labels_every_position_the_canonical_way(monkeypatch):
    """`pos_00000` named nothing.

    A label says where on the sample a capture was taken: carrier,
    compartment, group, position, view. A running index cannot be traced back
    to a well, so a file named by one is a file nobody can place.
    """
    driver = _Capturing()
    scanned = _scanned(driver, [{"x": 0, "y": 0}, {"x": 10, "y": 0}], monkeypatch)
    assert [label for _, label, _ in driver.asked] == [
        "K00_M000000_G000000_P000000_V00",
        "K00_M000000_G000000_P000001_V00",
    ]
    assert scanned["done"] == 2


def test_a_position_says_where_on_the_plate_it_is(monkeypatch):
    """The page knows which well and which tileset; the label carries it."""
    driver = _Capturing()
    _scanned(driver, [{"x": 0, "y": 0, "compartment": 3, "group": 2}], monkeypatch)
    assert driver.asked[-1][1] == "K00_M000003_G000002_P000000_V00"


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
    assert all(r["images"] for r in scanned["records"])


def test_a_scan_captures_under_the_kind_of_scan_it_is(monkeypatch):
    """The first slot of every filename, so it is the caller's to say."""
    driver = _Capturing()
    _scanned(driver, [{"x": 0, "y": 0}], monkeypatch, acquisition_type="target")
    assert driver.asked[-1][0] == "target"



# --- the scan, against a real driver -----------------------------------------


def test_a_scan_really_captures_at_every_position(monkeypatch, tmp_path):
    """The whole route, with nothing stood in for.

    Every other scan test here drives a fake, which proves the bridge asks
    correctly and not that anything is captured. This one connects the mock
    driver through the controller -- the same path a Leica takes -- and looks
    on disk afterwards. What it asserts is what an operator would check: the
    files are there, one per position, named for where they were taken.
    """
    import zmart_controller
    from zmart_drivers.mock import mock_driver

    mock_driver.register_mock()
    instrument = next(i for i in zmart_controller.get_instruments() if i["vendor"] == "mock")
    instrument["output_root"] = str(tmp_path)
    session = zmart_controller.set_instrument(instrument)
    monkeypatch.setattr(bridge, "_session", session)
    try:
        positions = [
            {"x": 0.0, "y": 0.0, "z": 5_000.0, "compartment": 1, "group": 1},
            {"x": 900.0, "y": 0.0, "z": 5_000.0, "compartment": 1, "group": 1},
            {"x": 0.0, "y": 700.0, "z": 5_000.0, "compartment": 2, "group": 2},
        ]
        bridge._scan.update(
        running=True, done=0, of=len(positions), error=None, acquisition_type="overview"
    )
        bridge._records["overview"] = []
        bridge._scan_worker(positions)
        assert bridge._scan["error"] is None, bridge._scan["error"]
    finally:
        session.disconnect()

    assert bridge._scan["done"] == 3
    records = bridge._records["overview"]
    assert [record["position_label"] for record in records] == [
        "K00_M000001_G000001_P000000_V00",
        "K00_M000001_G000001_P000001_V00",
        "K00_M000002_G000002_P000002_V00",
    ]
    # Every capture wrote what it says it wrote, where a driver writes it.
    written = sorted((bridge._run / "overview" / "data").glob("*.ome.tiff"))
    assert len(written) == 3 * 3  # three positions, one file per channel
    for record in records:
        for path in record["images"]:
            assert Path(path).is_file()
            assert Path(path).parent == bridge._run / "overview" / "data"
    # And the state it was captured under is printed beside them, once each.
    printed = sorted(
        (bridge._run / "overview" / "data" / "metadata" / "ZMART_state").iterdir()
    )
    assert len(printed) == 3


def test_a_scan_stops_and_says_so_when_a_capture_fails(monkeypatch, tmp_path):
    """A run that could not finish must not read as a shorter one that did.

    The driver is the real one and so is the first capture; the second is made
    to fail, because an instrument that refuses mid-run is the case worth
    covering and nothing in a mock will refuse on its own.
    """
    import zmart_controller
    from zmart_drivers.mock import mock_driver

    mock_driver.register_mock()
    instrument = next(i for i in zmart_controller.get_instruments() if i["vendor"] == "mock")
    instrument["output_root"] = str(tmp_path)
    session = zmart_controller.set_instrument(instrument)

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

    monkeypatch.setattr(bridge, "_session", _FailsOnTheSecond(session))
    try:
        positions = [{"x": 0.0, "y": 0.0}, {"x": 900.0, "y": 0.0}, {"x": 1_800.0, "y": 0.0}]
        bridge._scan.update(running=True, done=0, of=3, error=None, acquisition_type="overview")
        bridge._scan_worker(positions)
    finally:
        session.disconnect()

    assert bridge._scan["error"] == "the shutter did not open"
    assert bridge._scan["done"] == 1  # the one that finished, not the one that failed
    assert bridge._scan["running"] is False
    assert len(bridge._records["overview"]) == 1


# --- what the canvas is given to draw ----------------------------------------


def test_the_viewer_makes_a_picture_of_every_field_that_was_imaged(monkeypatch, tmp_path):
    """OME-TIFFs are not something a browser can draw, so the viewer copies them.

    Made when something asks to look, not while the run is going: a scan
    nobody watches makes no pictures. The note says where each field belongs in
    micrometres, which is everything the viewer needs and deliberately all it
    gets -- one that had to open a TIFF to find out where to put something
    would be back to reading large files.
    """
    import zmart_controller
    from zmart_drivers.mock import mock_driver

    mock_driver.register_mock()
    instrument = next(i for i in zmart_controller.get_instruments() if i["vendor"] == "mock")
    instrument["output_root"] = str(tmp_path)
    session = zmart_controller.set_instrument(instrument)
    monkeypatch.setattr(bridge, "_session", session)
    try:
        positions = [
            {"x": 0.0, "y": 0.0, "z": 5_000.0},
            {"x": 900.0, "y": 0.0, "z": 5_000.0},
        ]
        bridge._scan.update(running=True, done=0, of=2, error=None, acquisition_type="overview")
        bridge._scan_worker(positions)
        assert bridge._scan["error"] is None, bridge._scan["error"]

        view = bridge.view_of("overview")
        # Nothing is made while the run goes: the run only acquires.
        assert not view.exists()

        assert bridge._the_view_of("overview") is not None
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
    assert list((bridge._run / "overview" / "data").glob("*.ome.tiff"))
    assert not list(view.glob("*.tiff"))


def test_nothing_is_drawn_for_a_scan_that_has_imaged_nothing(monkeypatch, tmp_path):
    """A place the run has not reached has no picture, which is not an error."""
    import zmart_controller
    from zmart_drivers.mock import mock_driver

    mock_driver.register_mock()
    instrument = next(i for i in zmart_controller.get_instruments() if i["vendor"] == "mock")
    instrument["output_root"] = str(tmp_path)
    session = zmart_controller.set_instrument(instrument)
    monkeypatch.setattr(bridge, "_session", session)
    try:
        bridge._scan.update(running=False, done=0, of=0, error=None, acquisition_type="overview")
        assert bridge._the_view_of("overview") is None
    finally:
        session.disconnect()


# --- the page itself ---------------------------------------------------------


def test_the_bridge_hands_out_the_page_it_was_built_with(tmp_path, monkeypatch):
    """One program on the microscope: the page it draws and the instrument it drives.

    That is also why the page looks for the bridge at its own origin and has
    to be told where it is only in development, where a dev server holds the
    page instead so that edits reload live.
    """
    built = tmp_path / "static"
    (built / "sub").mkdir(parents=True)
    (built / "index.html").write_text("<!doctype html>the page", encoding="utf-8")
    (built / "worker.js").write_text("// a background program", encoding="utf-8")
    (built / "notes.txt").write_text("not part of a page", encoding="utf-8")
    monkeypatch.setattr(bridge._Bridge, "PAGE", dict(bridge._Bridge.PAGE))
    monkeypatch.setattr(bridge, "THE_PAGE", built)

    handed = _asked_for(["/", "/worker.js"])
    assert handed["/"] == (200, "text/html")
    # A browser will not start a background program from a file it was told is
    # anything but JavaScript, and it says nothing when it refuses.
    assert handed["/worker.js"] == (200, "text/javascript")

    refused = _asked_for(["/notes.txt", "/../secrets", "/sub"])
    assert all(status == 404 for status, _kind in refused.values()), refused


def _asked_for(paths):
    """Ask the page-serving route for each path, without a socket."""
    said = {}

    class _Probe(bridge._Bridge):
        def __init__(self):
            self.sent = None

        def _answer(self, payload, status=200):
            self.sent = (status, None)

        def send_response(self, status):
            self.sent = (status, None)

        def send_header(self, name, value):
            if name == "Content-Type":
                self.sent = (self.sent[0], value)

        def end_headers(self):
            pass

        @property
        def wfile(self):
            import io

            return io.BytesIO()

    for path in paths:
        probe = _Probe()
        probe._send_the_page(path)
        said[path] = probe.sent
    return said


# --- discovering targets -----------------------------------------------------


def _an_overview_of_two_fields(monkeypatch):
    """A scanned overview to detect on, and a finder that answers without pixels."""
    records = [
        _Driver().acquire(acquisition_type="overview", position_label=f"P{i}")
        for i in range(2)
    ]
    monkeypatch.setattr(bridge, "_records", {"overview": records})
    monkeypatch.setattr(
        bridge,
        "_find_targets",
        lambda: (lambda record, field, settings: [{
            "id": f"{record['position_label']}_obj1", "field": field,
            "x": 100.0 * field, "y": 2.0, "area": 50.0, "intensity": 3.0, "r": 4.0,
            "diameter_asked": settings.get("diameter"),
        }]),
    )
    return records


def _discovered(asked):
    """Start discovery and wait for it, handing back what the page would poll."""
    import time

    bridge._discover_targets(asked)
    for _ in range(200):
        if not bridge._targets["running"]:
            break
        time.sleep(0.01)
    assert bridge._targets["error"] is None, bridge._targets["error"]
    return dict(bridge._targets)


def test_targets_are_found_field_by_field_over_the_overview(monkeypatch):
    """Every field the scan captured, in the order it captured them."""
    _an_overview_of_two_fields(monkeypatch)
    got = _discovered({"settings": {"diameter": 20.0, "cellprob": 0.0}})
    assert got["done"] == got["of"] == 2
    assert [field["field"] for field in got["fields"]] == [0, 1]
    assert got["fields"][1]["cells"][0]["id"] == "P1_obj1"
    assert got["fields"][1]["cells"][0]["diameter_asked"] == 20.0


def test_one_field_can_be_tried_on_its_own(monkeypatch):
    """Settings are tried on one field before the whole overview is run."""
    _an_overview_of_two_fields(monkeypatch)
    got = _discovered({"fields": [1], "settings": {}})
    assert [field["field"] for field in got["fields"]] == [1]
    assert got["of"] == 1


def test_what_was_found_is_kept_beside_the_overview(monkeypatch):
    """The targets live with the pixels they were found in, not only on screen."""
    _an_overview_of_two_fields(monkeypatch)
    _discovered({"settings": {}})
    kept = sorted((bridge._run / "overview" / "analysis").glob("*_targets.json"))
    assert [path.name for path in kept] == [
        "overview_aaaaaa_P0_T000000_targets.json",
        "overview_aaaaaa_P1_T000000_targets.json",
    ]
    assert json.loads(kept[1].read_text(encoding="utf-8"))[0]["id"] == "P1_obj1"


def test_nothing_to_discover_on_before_an_overview(monkeypatch):
    monkeypatch.setattr(bridge, "_records", {})
    with pytest.raises(RuntimeError, match="overview"):
        bridge._discover_targets({"settings": {}})


def test_the_operators_hand_stops_discovery_between_fields(monkeypatch):
    """Interrupt ends the run after the field in hand; what was found stands."""
    _an_overview_of_two_fields(monkeypatch)
    unbraked = bridge._find_targets

    def finder():
        find = unbraked()

        def find_and_press(record, field, settings):
            cells = find(record, field, settings)
            bridge._stop_targets()
            return cells

        return find_and_press

    monkeypatch.setattr(bridge, "_find_targets", finder)
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
    good = bridge._find_targets

    def finder():
        find = good()

        def find_or_die(record, field, settings):
            if field == 0:
                raise RuntimeError("the pipeline choked on this field")
            return find(record, field, settings)

        return find_or_die

    monkeypatch.setattr(bridge, "_find_targets", finder)
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
            bridge._stop_targets()
            raise RuntimeError("worker crashed: put down by the operator")

        return find_and_die

    monkeypatch.setattr(bridge, "_find_targets", finder)
    bridge._discover_targets({"settings": {}})
    for _ in range(200):
        if not bridge._targets["running"]:
            break
        time.sleep(0.01)
    assert bridge._targets["stopped"] is True
    assert bridge._targets["error"] is None


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


def test_the_reading_survives_a_leica_shaped_state(monkeypatch):
    """The adapter reports `serial_number` and `active_objective`, and its
    `pixel_size` is None when job geometry fails to parse. The reading read
    the mock's keys and crashed on the None."""
    monkeypatch.setattr(bridge, "_session", _Optics({
        "serial_number": "STELLARIS-1", "active_objective": {"magnification": 20.0},
        "pixel_size": None, "frame_size": None,
    }))
    reading = bridge._reading("acquisition")
    assert "20x" in reading["summary"]

    monkeypatch.setattr(bridge, "_session", _Optics({
        "serial_number": "STELLARIS-1", "pixel_size": None, "frame_size": None,
    }))
    assert "STELLARIS-1" in bridge._reading("acquisition")["summary"]


def test_a_fresh_connect_forgets_the_last_sessions_runs(monkeypatch, tmp_path):
    """The bridge outlives the page. A new session opened over old records
    rebuilt the previous scan's pictures into the fresh run's view, so a
    just-connected canvas showed a scan nobody had taken."""
    import zmart_controller
    from zmart_drivers.mock import mock_driver

    mock_driver.register_mock()
    instrument = next(i for i in zmart_controller.get_instruments() if i["vendor"] == "mock")
    instrument["output_root"] = str(tmp_path)
    bridge._records["overview"] = [{"stale": True}]
    bridge._scan.update(running=False, done=5, of=5, error=None, acquisition_type="overview")
    bridge._focus.update(running=False, done=3, of=3, error=None, points=[{"x": 1}])
    try:
        bridge._connect({"connection": instrument})
        assert bridge._records == {}
        assert bridge._the_scan()["done"] == 0 and bridge._the_scan()["records"] == []
        assert bridge._focus["points"] == []
    finally:
        bridge._disconnect()


def test_the_optics_line_names_the_leica_lens(monkeypatch):
    """The Leica's objective is {name, magnification, slotIndex} -- no
    aperture, no immersion. The name is what identifies the lens on the
    shelf, and the line read only the mock's sub-keys."""
    monkeypatch.setattr(bridge, "_session", _Optics({
        "active_objective": {"name": "HC PL APO 63x/1.40 OIL CS2", "magnification": 63.0},
        "pixel_size": None, "frame_size": None,
    }))
    assert "HC PL APO 63x/1.40 OIL CS2" in bridge._reading("acquisition")["summary"]


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
                       state={"job": "Overview"})
    assert driver.applied == [{"changeable": {"job": "Overview"}}]
    assert scanned["done"] == 1


def test_the_view_is_built_once_per_scan_state(monkeypatch, tmp_path):
    """Every file request rebuilt the whole view, and two rebuilding at once
    interleaved their writes into a corrupt note that 400d every request
    after. One builder at a time, and only when the scan has grown."""
    import sys
    import types

    built = []
    stub = types.ModuleType("application.parts.storage.jpeg_tiles")
    stub.make_what_is_missing = lambda into, fields: built.append(len(fields)) or Path(into)
    monkeypatch.setitem(sys.modules, "application.parts.storage.jpeg_tiles", stub)
    record = _Driver().acquire(acquisition_type="overview", position_label="P0")
    monkeypatch.setattr(bridge, "_records", {"overview": [record]})
    monkeypatch.setattr(bridge, "_view_built", {})

    (bridge._run / "overview" / "view").mkdir(parents=True)
    (bridge._run / "overview" / "view" / "tiles.json").write_text("{}", encoding="utf-8")
    bridge._the_view_of("overview")
    bridge._the_view_of("overview")
    assert built == [1], "the second request found nothing new to build"

    bridge._records["overview"].append(
        _Driver().acquire(acquisition_type="overview", position_label="P1"))
    bridge._the_view_of("overview")
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
    stub = types.ModuleType("application.parts.storage.jpeg_tiles")

    def build(into, fields):
        built.append(len(fields))
        if len(built) == 1:
            bridge._records["overview"].append(
                _Driver().acquire(acquisition_type="overview", position_label="P1"))
        return Path(into)

    stub.make_what_is_missing = build
    monkeypatch.setitem(sys.modules, "application.parts.storage.jpeg_tiles", stub)
    record = _Driver().acquire(acquisition_type="overview", position_label="P0")
    monkeypatch.setattr(bridge, "_records", {"overview": [record]})
    monkeypatch.setattr(bridge, "_view_built", {})
    (bridge._run / "overview" / "view").mkdir(parents=True)
    (bridge._run / "overview" / "view" / "tiles.json").write_text("{}", encoding="utf-8")

    bridge._the_view_of("overview")
    bridge._the_view_of("overview")
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
    stub = types.ModuleType("application.parts.storage.jpeg_tiles")
    stub.make_slice_copies = lambda into, planes: (
        handed.append(planes) or [{"z_um": 1.0, "name": "s_Z00000.jpg"}])
    monkeypatch.setitem(sys.modules, "application.parts.storage.jpeg_tiles", stub)
    monkeypatch.setattr(bridge, "_session", _Driver())
    monkeypatch.setattr(
        bridge, "_focus",
        {"running": True, "done": 0, "of": 1, "error": None, "points": []})

    bridge._focus_worker([{"x": 1.0, "y": 2.0}])

    point = bridge._focus["points"][0]
    assert point["slices"] == [{"z_um": 1.0, "name": "s_Z00000.jpg"}]
    assert handed and len(handed[0]) > 0, "the record's planes reached the copier"
    assert all("path" in plane and "z_um" in plane for plane in handed[0])


def test_a_scan_started_again_takes_the_last_ones_stores_down_first(monkeypatch):
    """A rerun accounts for exactly what it captured.

    The position stores and the display copies of the last run stayed on
    disk, so a shorter rerun showed fields it never captured, and the viewer
    kept listing every store it had once seen. Starting a scan of a kind
    closes that kind in the viewer and removes its folders; the new run's
    first position opens it afresh."""
    told = []
    monkeypatch.setattr(
        bridge.viewer_service, "an_acquisition_is_being_replaced",
        lambda kind, folder: told.append((kind, Path(folder))),
    )
    positions = bridge._run / "positions" / "overview"
    stale = positions / "overview_K00_M000000_G000000_P000002_V00.ome.zarr"
    stale.mkdir(parents=True)
    (stale / "zarr.json").write_text("{}", encoding="utf-8")
    half_written = bridge._run / "positions" / ".writing-overview" / "x"
    half_written.mkdir(parents=True)
    copies = bridge.view_of("overview")
    copies.mkdir(parents=True)
    (copies / "tiles.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(bridge, "_view_built", {"overview": 3})
    monkeypatch.setattr(bridge, "_records", {"overview": [{"stale": True}]})

    bridge._replace_the_acquisition("overview")

    assert told == [("overview", positions)]
    assert not positions.exists()
    assert not half_written.parent.exists()
    assert not copies.exists()
    assert "overview" not in bridge._view_built
