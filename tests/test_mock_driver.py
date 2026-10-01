"""Tests for the mock driver's parts, following the driver anatomy.

The controller-level tests (test_layer.py) check what an experiment sees.
These check how the driver gets there: that every fault from the mock API is
sorted into the right kind and handled by the rule for that kind, that the
limits gate stops a request before anything is sent, that the configuration
and the coordinate system behave, and that each part only uses the parts
below it.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import ast
import json
import struct
from pathlib import Path

import pytest

from zmart_controller.layer import set_instrument
from zmart_driver_mock.configuration import load_configuration, save, saved_path
from zmart_driver_mock.error_handling import RULES, Kind, classify
from zmart_driver_mock.get_commands import DEFAULT_GET_TUNING
from zmart_driver_mock.set_commands import DEFAULT_SET_TUNING, Gate
from zmart_driver_mock.testing.mock_api import read_mraw
from zmart_driver_mock.vendor_interface import VendorError

PACKAGE = Path(__file__).resolve().parent.parent / "zmart_driver_mock"
MOCK = {"vendor": "mock", "microscope": "mock-scope", "api": "mock-api"}


def _open(tmp_path, **extra):
    return set_instrument({**MOCK, "output_root": str(tmp_path / "images"), **extra})


@pytest.fixture
def mic(tmp_path):
    session = _open(tmp_path, mock_timing="instant")
    yield session
    session.disconnect()


@pytest.fixture
def slow_mic(tmp_path):
    session = _open(tmp_path)
    yield session
    session.disconnect()


def _sent(session, command):
    return [entry for entry in session._handle.scope.history if entry["command"] == command]


# --- part 2: error handling -----------------------------------------------------


class TestErrorHandling:
    def test_every_kind_has_a_rule(self):
        assert set(RULES) == set(Kind)

    @pytest.mark.parametrize(
        ("error", "kind"),
        [
            (VendorError("X", 100, "busy"), Kind.TEMPORARY),
            (VendorError("X", 201, "out of range"), Kind.BAD_REQUEST),
            (VendorError("X", 300, "fault"), Kind.PERMANENT),
            (VendorError("X", 999, "something new"), Kind.PERMANENT),
            (VendorError("X", 12345, "never seen"), Kind.PERMANENT),
            (TimeoutError("lost"), Kind.TEMPORARY),
            (ConnectionError("gone"), Kind.CONNECTION_LOST),
            (KeyError("surprise"), Kind.PERMANENT),
        ],
    )
    def test_classifier(self, error, kind):
        assert classify(error) is kind

    def test_a_reading_fits_inside_a_confirmation_window(self):
        # Otherwise the set dispatcher gives up before the reading arrives.
        assert DEFAULT_GET_TUNING.time_limit_s < DEFAULT_SET_TUNING.confirm_window_s


# --- parts 3 and 4: the dispatchers, under every fault ----------------------------


class TestFaultsThroughTheDriver:
    def test_busy_is_sent_again_and_confirmed(self, mic):
        mic._handle.scope.faults.add("MoveStage", "busy", times=2)
        mic.set_xyz(10, 0, 0)
        assert mic.get_xyz()["report"]["x"]["value"] == 10
        assert [e["code"] for e in _sent(mic, "MoveStage")][-3:] == [100, 100, None]

    def test_busy_too_often_becomes_a_runtime_error(self, mic):
        mic._handle.scope.faults.add("MoveStage", "busy", times=None)
        with pytest.raises(RuntimeError, match="failed 3 times"):
            mic.set_xyz(10, 0, 0)

    def test_lost_reply_is_read_back_not_sent_again(self, mic):
        mic._handle.scope.faults.add("MoveStage", "timeout")
        before = len(_sent(mic, "MoveStage"))
        mic.set_xyz(10, 0, 0)
        assert len(_sent(mic, "MoveStage")) == before + 1
        assert mic.get_xyz()["report"]["x"]["value"] == 10

    def test_ignored_setting_is_sent_again(self, mic):
        mic._handle.scope.faults.add("SetSetting", "ignore")
        answer = mic.set_state({"changeable": {"gain": 3.0}})
        assert answer["success"] is True
        assert len(_sent(mic, "SetSetting")) == 2

    def test_never_confirmed_is_reported_softly(self, mic):
        mic._handle.scope.faults.add("SetSetting", "ignore", times=None)
        answer = mic.set_state({"changeable": {"gain": 3.0}})
        assert answer["success"] is False
        assert "gain" in answer["report"]["unconfirmed"]
        assert answer["report"]["applied"] == {}

    def test_an_unconfirmed_move_is_raised(self, mic):
        mic._handle.scope.faults.add("MoveStage", "ignore", times=None)
        with pytest.raises(RuntimeError, match="could not be confirmed"):
            mic.set_xyz(10, 0, 0)

    def test_stale_reading_only_delays_confirmation(self, mic):
        mic.get_xyz()  # gives the stale fault an old answer to repeat
        mic._handle.scope.faults.add("GetStagePosition", "stale")
        mic.set_xyz(25, 0, 0)
        assert mic.get_xyz()["report"]["x"]["value"] == 25

    @pytest.mark.parametrize("fault", ["hardware_fault", "unknown_error"])
    def test_permanent_problems_are_raised_at_once(self, mic, fault):
        mic._handle.scope.faults.add("SetSetting", fault)
        with pytest.raises(RuntimeError):
            mic.set_state({"changeable": {"gain": 3.0}})
        assert len(_sent(mic, "SetSetting")) == 1

    def test_vendor_refusal_is_a_value_error(self, mic):
        mic._handle.scope.faults.add("MoveStage", "out_of_range")
        with pytest.raises(ValueError, match="out of range"):
            mic.set_xyz(10, 0, 0)

    def test_lost_connection(self, mic):
        mic._handle.scope.faults.add("*", "disconnect")
        with pytest.raises(RuntimeError, match="closed unexpectedly"):
            mic.get_xyz()

    def test_temporary_reading_problem_is_retried(self, mic):
        mic._handle.scope.faults.add("GetSettings", "busy")
        assert mic.get_state()["success"] is True

    def test_reading_that_stays_busy_is_unknown(self, mic):
        mic._handle.scope.faults.add("GetSettings", "busy", times=None)
        with pytest.raises(RuntimeError, match="could not read"):
            mic.get_state()


# --- part 4: the limits gate --------------------------------------------------------


class TestLimitsGate:
    def test_nothing_is_sent_when_the_limits_refuse(self, mic):
        before = len(_sent(mic, "MoveStage"))
        with pytest.raises(ValueError, match="outside the travel range"):
            mic.set_xyz(6000, 0, 0)
        assert len(_sent(mic, "MoveStage")) == before

    def test_settings_have_limits_too(self, mic):
        with pytest.raises(ValueError, match="laser_power = 80.0 is outside the limits"):
            mic.set_state({"changeable": {"laser_power": 80.0}})
        assert _sent(mic, "SetSetting") == []

    def test_a_z_stack_must_stay_inside(self, mic):
        mic.set_xyz(0, 0, 490)
        with pytest.raises(ValueError, match="z-stack"):
            mic.acquire(
                acquisition_type="t",
                position_label="p",
                options={"z_planes": 20, "z_step_um": 1.0, "backlash_correction": False},
            )

    def test_without_limits_everything_is_refused(self):
        assert "not loaded" in Gate(None).check("stage", {"x": 0, "y": 0, "z": 0})

    def test_unknown_keys_are_refused(self):
        limits = load_configuration().limits
        assert "no limit" in Gate(limits).check("teleport", {})

    def test_limits_are_in_stage_coordinates(self, tmp_path):
        # A new origin shifts the user's numbers but never the safe range on the stage.
        save("origin", {"x": 54_000.0, "y": 37_500.0, "z": 5_000.0})
        session = _open(tmp_path, mock_timing="instant")
        try:
            assert session.get_xyz()["report"]["x"]["range"] == [-9000.0, 1000.0]
            with pytest.raises(ValueError):
                session.set_xyz(1500, 0, 0)
        finally:
            session.disconnect()


# --- part 3 and 4: actuators -----------------------------------------------------------


class TestActuators:
    def test_piezo_makes_the_z_change(self, mic):
        mic.set_xyz(0, 0, 30, with_actuators={"z": "piezo"})
        focus = mic._handle.scope.send("GetFocus")["result"]
        assert focus == {"focus": 5000.0, "piezo": 30.0}
        assert mic.get_xyz()["report"]["z"]["value"] == 30

    def test_beyond_the_piezo_reach(self, mic):
        with pytest.raises(ValueError, match="beyond its reach"):
            mic.set_xyz(0, 0, 300, with_actuators={"z": "piezo"})


# --- part 5: procedures ------------------------------------------------------------------


class TestProcedures:
    def test_autofocus_finds_the_sharp_height(self, mic):
        mic.set_xyz(0, 0, 6)
        answer = mic.run_procedure({"name": "autofocus", "range_um": 20, "step_um": 2})
        assert abs(answer["report"]["frame_z_um"]) <= 2
        assert abs(mic.get_xyz()["report"]["z"]["value"]) <= 2

    def test_unknown_entries_are_refused(self, mic):
        with pytest.raises(ValueError, match="does not take"):
            mic.run_procedure({"name": "zero_piezo", "speed": "fast"})

    def test_zero_piezo_keeps_the_height(self, mic):
        mic.set_xyz(0, 0, 30, with_actuators={"z": "piezo"})
        mic.run_procedure({"name": "zero_piezo"})
        assert mic._handle.scope.send("GetFocus")["result"] == {"focus": 5030.0, "piezo": 0.0}

    def test_record_origin_is_used_at_the_next_connect(self, tmp_path):
        from zmart_driver_mock.procedures import record_origin

        session = _open(tmp_path, mock_timing="instant")
        session.set_xyz(100, -50, 0)
        record_origin(session._handle)
        session.disconnect()
        again = _open(tmp_path, mock_timing="instant")
        try:
            # A fresh pretend microscope starts at the slide's centre, which is
            # now (-100, 50) from the recorded origin.
            position = again.get_xyz()["report"]
            assert (position["x"]["value"], position["y"]["value"]) == (-100.0, 50.0)
        finally:
            again.disconnect()


# --- part 6: data handling --------------------------------------------------------------


def _tiff_description(path: Path) -> str:
    """The OME-XML in a TIFF written by the driver (a tiny reader for tests)."""
    raw = path.read_bytes()
    assert raw[:4] == b"II*\0"
    (ifd,) = struct.unpack_from("<I", raw, 4)
    (count,) = struct.unpack_from("<H", raw, ifd)
    for index in range(count):
        tag, _kind, length, offset = struct.unpack_from("<HHII", raw, ifd + 2 + 12 * index)
        if tag == 270:
            return raw[offset : offset + length - 1].decode("utf-8")
    raise AssertionError("no image description")


class TestDataHandling:
    def test_a_z_stack_is_one_file_per_plane(self, mic):
        answer = mic.acquire(
            acquisition_type="stack", position_label="cell 1", options={"z_planes": 3}
        )["report"]
        names = [Path(f).name for f in answer["files"]]
        assert names == ["cell_1_z000.ome.tif", "cell_1_z001.ome.tif", "cell_1_z002.ome.tif"]
        description = _tiff_description(Path(answer["files"][1]))
        assert 'PhysicalSizeX="1.0"' in description
        assert 'PositionZ="1.0"' in description

    def test_never_overwrites(self, mic):
        first = mic.acquire(acquisition_type="t", position_label="A1")["report"]["files"]
        second = mic.acquire(acquisition_type="t", position_label="A1")["report"]["files"]
        assert Path(first[0]).name == "A1.ome.tif"
        assert Path(second[0]).name == "A1_001.ome.tif"

    def test_the_command_log_is_saved(self, mic):
        mic._handle.scope.faults.add("MoveStage", "busy")
        answer = mic.acquire(acquisition_type="t", position_label="log")["report"]
        lines = json.loads(Path(answer["command_log"]).read_text())
        messages = " ".join(line["message"] for line in lines)
        assert "sending again" in messages
        assert "confirmed" in messages

    def test_ome_zarr_holds_the_stack(self, mic):
        answer = mic.acquire(
            acquisition_type="t",
            position_label="z",
            options={"format": "ome-zarr", "z_planes": 4, "z_step_um": 2.0},
        )["report"]
        root = Path(answer["files"][0])
        array = json.loads((root / "0" / ".zarray").read_text())
        assert array["shape"] == [4, 64, 64]
        scale = json.loads((root / ".zattrs").read_text())["multiscales"][0]["datasets"][0]
        assert scale["coordinateTransformations"][0]["scale"] == [2.0, 1.0, 1.0]
        assert (root / "0" / "3" / "0" / "0").stat().st_size == 64 * 64 * 2

    def test_registration_lines_the_image_up_with_the_stage(self, tmp_path):
        # Save the camera orientation the mock really has, then check that a
        # stage step to +x moves the saved picture's content to the left.
        session = _open(tmp_path, mock_timing="instant")
        truth = session._handle.scope.truth()["orientation"]
        session.disconnect()
        save(
            "image_stage_registration",
            {
                "orientation": [list(r) for r in truth],
                "pixel_size_um": {"1": 1.0, "2": 0.5, "3": 0.25},
            },
        )
        session = _open(tmp_path, mock_timing="instant")
        session._handle.scope._noise = False
        try:
            options = {"backlash_correction": False}
            before = session.acquire(acquisition_type="r", position_label="a", options=options)
            session.set_xyz(5, 0, 0)
            after = session.acquire(acquisition_type="r", position_label="b", options=options)
            first = read_mraw_free_tiff(before["report"]["files"][0])
            second = read_mraw_free_tiff(after["report"]["files"][0])
            width = 64
            for row in range(64):
                for col in range(64 - 5):
                    assert abs(second[row * width + col] - first[row * width + col + 5]) <= 1
        finally:
            session.disconnect()

    def test_an_unconfirmed_acquisition_lists_no_files(self, mic):
        mic._handle.scope.faults.add("StartAcquisition", "ignore")
        answer = mic.acquire(
            acquisition_type="t", position_label="lost", options={"backlash_correction": False}
        )
        assert answer["success"] is False
        assert answer["report"]["files"] == []
        # An acquisition is never sent twice by itself.
        assert len(_sent(mic, "StartAcquisition")) == 1


class TestReviewFindings:
    """Regression tests for problems found in review."""

    def test_lost_acquisition_reply_still_saves_the_image(self, mic):
        mic._handle.scope.faults.add("StartAcquisition", "timeout")
        answer = mic.acquire(
            acquisition_type="t", position_label="lost", options={"backlash_correction": False}
        )
        assert answer["success"] is True
        assert Path(answer["report"]["files"][0]).is_file()

    def test_an_ignored_acquisition_is_never_confirmed_by_an_older_one(self, mic):
        options = {"backlash_correction": False}
        first = mic.acquire(acquisition_type="t", position_label="same", options=options)
        assert first["success"] is True
        mic._handle.scope.faults.add("StartAcquisition", "ignore")
        second = mic.acquire(acquisition_type="t", position_label="same", options=options)
        assert second["success"] is False
        assert second["report"]["files"] == []
        assert "not running" in second["report"]["reason"]

    def test_acquire_near_the_lower_limit(self, mic):
        mic.set_xyz(-4980, -5000, 0)  # 20 µm from the x limit, right at the y limit
        answer = mic.acquire(acquisition_type="t", position_label="edge")
        assert answer["success"] is True
        assert mic.get_xyz()["report"]["x"]["value"] == -4980

    def test_lost_stage_reply_still_moves_the_focus_at_once(self, mic):
        import time

        mic._handle.scope.faults.add("MoveStage", "timeout")
        started = time.monotonic()
        mic.set_xyz(10, 10, 20)
        assert time.monotonic() - started < 0.5
        position = mic.get_xyz()["report"]
        assert [position[a]["value"] for a in ("x", "y", "z")] == [10, 10, 20]


@pytest.mark.parametrize(
    "orientation",
    [
        ((1, 0), (0, 1)),
        ((-1, 0), (0, 1)),
        ((1, 0), (0, -1)),
        ((-1, 0), (0, -1)),
        ((0, 1), (1, 0)),
        ((0, -1), (1, 0)),
        ((0, 1), (-1, 0)),
        ((0, -1), (-1, 0)),
    ],
)
def test_alignment_undoes_every_camera_orientation(orientation):
    # Draw the same slide twice, 5 µm apart in x and 3 µm apart in y, with a
    # non-square camera, and check that after alignment the picture moved
    # left by 5 pixels and up by 3, whatever way the camera sits.
    from zmart_driver_mock.data_handling import align_to_stage
    from zmart_driver_mock.testing.mock_api.sample import render

    width, height = 40, 24

    def picture(x, y):
        plane = render(
            seed=0,
            width=width,
            height=height,
            pixel_size_um=1.0,
            centre_x=50_000.0 + x,
            centre_y=37_500.0 + y,
            defocus_um=0.0,
            orientation=orientation,
            signal=2000.0,
            noise=None,
        )
        [aligned], out_width, out_height = align_to_stage(
            [plane], width, height, [list(row) for row in orientation]
        )
        return aligned, out_width, out_height

    before, out_width, out_height = picture(0, 0)
    after, _, _ = picture(5, 3)
    for row in range(out_height - 3):
        for col in range(out_width - 5):
            here = after[row * out_width + col]
            there = before[(row + 3) * out_width + col + 5]
            assert abs(here - there) <= 1


def read_mraw_free_tiff(path: str) -> list[int]:
    """The pixels of a TIFF written by the driver, as a flat list."""
    raw = Path(path).read_bytes()
    (ifd,) = struct.unpack_from("<I", raw, 4)
    (count,) = struct.unpack_from("<H", raw, ifd)
    fields = {}
    for index in range(count):
        tag, kind, _length, value = struct.unpack_from("<HHII", raw, ifd + 2 + 12 * index)
        fields[tag] = value & 0xFFFF if kind == 3 else value
    start, size = fields[273], fields[279]
    return list(struct.unpack_from(f"<{size // 2}H", raw, start))


# --- part 7: configuration and the coordinate system ------------------------------------


class TestConfiguration:
    def test_a_malformed_file_is_refused_by_name(self, tmp_path):
        path = saved_path("limits")
        path.parent.mkdir(parents=True)
        path.write_text('{"stage_um": {}}')
        with pytest.raises(ValueError, match="limits.json"):
            _open(tmp_path)

    def test_a_bad_value_is_never_saved(self):
        with pytest.raises(ValueError, match="lowest value must be below"):
            limits = load_configuration().limits
            save("limits", {**limits, "stage_um": {**limits["stage_um"], "x": [10.0, 5.0]}})
        assert not saved_path("limits").exists()

    def test_configuration_of_another_microscope_is_refused(self, tmp_path):
        save(
            "machine_description",
            {"serial": "OTHER-9", "software": "MockScope Control", "tested_versions": ["2.4.1"]},
        )
        with pytest.raises(RuntimeError, match="belongs to OTHER-9"):
            _open(tmp_path)

    def test_calibration_keeps_the_same_spot_across_objectives(self, tmp_path):
        offsets = {"1": {"x": 0.0, "y": 0.0, "z": 0.0}, "2": {"x": 3.0, "y": -2.0, "z": 1.5}}
        save("optical_calibration", {"objective_offsets_um": {**offsets, "3": offsets["1"]}})
        session = _open(tmp_path, mock_timing="instant")
        try:
            session.set_xyz(0, 0, 0)
            session.set_state({"changeable": {"objective": 2}})
            session.set_xyz(0, 0, 0)
            stage = session._handle.scope.send("GetStagePosition")["result"]
            assert stage == {"x": 50_000.0 - 3.0, "y": 37_500.0 + 2.0}
        finally:
            session.disconnect()

    def test_wrong_token_is_refused_without_showing_it(self, tmp_path):
        with pytest.raises(RuntimeError, match="refused the login") as caught:
            _open(tmp_path, token="s3cret-value")
        assert "s3cret-value" not in str(caught.value)


# --- real timing ------------------------------------------------------------------------


class TestRealisticTiming:
    def test_moves_are_confirmed_after_they_settle(self, slow_mic):
        slow_mic.set_xyz(1000, 500, 0)
        assert slow_mic.get_xyz()["report"]["x"]["value"] == 1000
        reads = _sent(slow_mic, "GetStagePosition")
        assert len(reads) > 1  # it had to read back more than once

    def test_stop_during_an_acquisition(self, slow_mic):
        from zmart_driver_mock import set_commands

        handle = slow_mic._handle
        handle.vendor.start_acquisition("long", z_planes=200, z_step_um=0.1)
        outcome = set_commands.stop(handle)
        assert outcome.confirmed
        status = handle.scope.send("GetStatus")["result"]
        assert status["last_acquisition"]["state"] == "aborted"
        with pytest.raises(ValueError, match="incomplete"):
            read_mraw(status["last_acquisition"]["file"])


# --- the layers ---------------------------------------------------------------------------

# Which parts each part may import. A part may always import from itself.
ALLOWED = {
    "vendor_interface": {"testing"},
    "error_handling": {"vendor_interface"},
    "configuration": set(),
    "get_commands": {"error_handling", "configuration"},
    "set_commands": {"error_handling", "configuration", "get_commands"},
    "data_handling": {"get_commands"},
    "procedures": {"get_commands", "set_commands", "configuration", "data_handling"},
    "zmart_controller": {
        "vendor_interface",
        "error_handling",
        "configuration",
        "get_commands",
        "set_commands",
        "data_handling",
        "procedures",
    },
}


def _imported_parts(path: Path, part: str) -> set[str]:
    tree = ast.parse(path.read_text())
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level == 2:
                names = [module.split(".")[0]] if module else [a.name for a in node.names]
                found.update(names)
            elif node.level == 0 and module.startswith("zmart_driver_mock"):
                pieces = module.split(".")
                if len(pieces) > 1:
                    found.add(pieces[1])
                else:
                    found.update(a.name for a in node.names)
    return found - {part}


@pytest.mark.parametrize("part", sorted(ALLOWED))
def test_each_part_only_uses_the_parts_below_it(part):
    for path in (PACKAGE / part).rglob("*.py"):
        used = _imported_parts(path, part)
        assert used <= ALLOWED[part], f"{path.relative_to(PACKAGE)} imports {used - ALLOWED[part]}"


def test_only_the_vendor_interface_touches_the_mock_api():
    for path in PACKAGE.rglob("*.py"):
        relative = path.relative_to(PACKAGE)
        if relative.parts[0] in ("testing", "vendor_interface"):
            continue
        assert "testing" not in _imported_parts(path, relative.parts[0]), str(relative)
