"""Tests for the mock API: the pretend vendor software behind the mock driver.

These check that MockScope behaves like vendor software should, so that a
driver tested against it meets the same situations it will meet on a real
microscope: commands that take time, refusals while busy, files written in
two steps, and every kind of fault.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import pytest

from zmart_driver_mock.testing.mock_api import FAULTS, FakeClock, MockScope, read_mraw
from zmart_driver_mock.testing.mock_api.scope import START_POSITION


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def scope(tmp_path, clock):
    mock = MockScope(output_folder=tmp_path, clock=clock)
    assert mock.send("Login", token="mock-token")["ok"]
    return mock


def _result(reply):
    assert reply["ok"], reply
    return reply["result"]


def _picture(scope, clock, name, **arguments):
    """Acquire, wait until done, and return the first plane and the description."""
    file = _result(scope.send("StartAcquisition", name=name, **arguments))["file"]
    clock.advance(10.0)
    assert _result(scope.send("GetStatus"))["last_acquisition"]["state"] == "done"
    header, planes = read_mraw(file)
    return header, planes


def _brenner(plane, width):
    """A simple sharpness score: large when neighbouring pixels differ a lot."""
    total = 0
    for row in range(len(plane) // width):
        line = plane[row * width : (row + 1) * width]
        total += sum((line[i + 2] - line[i]) ** 2 for i in range(width - 2))
    return total


class TestSession:
    def test_version_needs_no_login(self, tmp_path):
        mock = MockScope(output_folder=tmp_path)
        assert _result(mock.send("GetVersion"))["software"] == "MockScope Control"

    def test_commands_need_a_login(self, tmp_path):
        mock = MockScope(output_folder=tmp_path)
        assert mock.send("GetStagePosition")["code"] == 402

    def test_wrong_token_is_refused(self, tmp_path):
        mock = MockScope(output_folder=tmp_path)
        assert mock.send("Login", token="wrong")["code"] == 401
        assert mock.send("GetStagePosition")["code"] == 402

    def test_history_hides_the_token(self, scope):
        login = scope.history[0]
        assert login["command"] == "Login"
        assert login["arguments"] == {"token": "<hidden>"}

    def test_logout_closes_the_session(self, scope):
        _result(scope.send("Logout"))
        assert scope.send("GetSettings")["code"] == 402

    def test_shutdown_and_restart(self, scope):
        scope.shutdown()
        with pytest.raises(ConnectionError):
            scope.send("GetVersion")
        scope.restart()
        assert scope.send("GetStagePosition")["code"] == 402


class TestRequests:
    def test_unknown_command(self, scope):
        assert scope.send("Teleport")["code"] == 200

    def test_missing_argument(self, scope):
        assert scope.send("SetSetting", name="exposure_ms")["code"] == 203

    def test_unknown_argument(self, scope):
        assert scope.send("MoveStage", x=1.0, w=2.0)["code"] == 204

    def test_invalid_value(self, scope):
        assert scope.send("MoveStage", x="far")["code"] == 205
        assert scope.send("MoveStage", x=float("nan"))["code"] == 205
        assert scope.send("SetObjective", slot=True)["code"] == 205

    def test_unknown_setting(self, scope):
        assert scope.send("SetSetting", name="laser", value=1.0)["code"] == 202

    def test_out_of_travel_is_refused_and_nothing_moves(self, scope):
        reply = scope.send("MoveStage", x=-1.0)
        assert reply["code"] == 201
        assert "x must be between" in reply["message"]
        assert _result(scope.send("GetStagePosition"))["x"] == START_POSITION["x"]

    def test_setting_out_of_range(self, scope):
        assert scope.send("SetSetting", name="laser_power_percent", value=150.0)["code"] == 201


class TestTime:
    def test_a_move_takes_time(self, scope, clock):
        _result(scope.send("MoveStage", x=START_POSITION["x"] + 10_000.0))
        assert _result(scope.send("GetStatus"))["state"] == "moving"
        clock.advance(0.1)  # halfway at 50 mm/s
        halfway = _result(scope.send("GetStagePosition"))["x"]
        assert START_POSITION["x"] < halfway < START_POSITION["x"] + 10_000.0
        clock.advance(1.0)
        assert _result(scope.send("GetStagePosition"))["x"] == START_POSITION["x"] + 10_000.0
        assert _result(scope.send("GetStatus"))["state"] == "idle"

    def test_a_setting_can_lag(self, tmp_path, clock):
        mock = MockScope(output_folder=tmp_path, clock=clock, timing={"setting_delay_s": 0.5})
        mock.send("Login", token="mock-token")
        _result(mock.send("SetSetting", name="detector_gain", value=300.0))
        assert _result(mock.send("GetSettings"))["detector_gain"] == 100.0
        clock.advance(0.5)
        assert _result(mock.send("GetSettings"))["detector_gain"] == 300.0

    def test_an_objective_change_takes_time_and_blocks_focus(self, scope, clock):
        _result(scope.send("SetObjective", slot=2))
        assert _result(scope.send("GetStatus"))["state"] == "changing_objective"
        assert _result(scope.send("GetSettings"))["objective_slot"] == 1
        assert scope.send("MoveFocus", focus=4_000.0)["code"] == 100
        clock.advance(1.0)
        assert _result(scope.send("GetSettings"))["objective_slot"] == 2

    def test_abort_stops_a_move_partway(self, scope, clock):
        _result(scope.send("MoveStage", y=START_POSITION["y"] + 10_000.0))
        clock.advance(0.1)
        _result(scope.send("Abort"))
        stopped = _result(scope.send("GetStagePosition"))["y"]
        clock.advance(1.0)
        assert _result(scope.send("GetStagePosition"))["y"] == stopped
        assert START_POSITION["y"] < stopped < START_POSITION["y"] + 10_000.0

    def test_instant_scope_has_no_waiting(self, tmp_path):
        mock = MockScope.instant(output_folder=tmp_path)
        mock.send("Login", token="mock-token")
        _result(mock.send("MoveStage", x=1_000.0))
        assert _result(mock.send("GetStagePosition"))["x"] == 1_000.0
        file = _result(mock.send("StartAcquisition", name="now"))["file"]
        header, planes = read_mraw(file)
        assert header["planes"] == 1


class TestAcquisition:
    def test_refuses_while_moving(self, scope):
        _result(scope.send("MoveStage", x=60_000.0))
        assert scope.send("StartAcquisition", name="early")["code"] == 100

    def test_file_is_incomplete_until_done(self, scope, clock):
        file = _result(scope.send("StartAcquisition", name="stack", z_planes=3, z_step_um=2.0))[
            "file"
        ]
        with pytest.raises(ValueError, match="incomplete"):
            read_mraw(file)
        assert _result(scope.send("GetStatus"))["state"] == "acquiring"
        clock.advance(1.0)
        # Time only moves on for the pretend microscope when it is asked
        # something, so ask for the status before reading the file.
        assert _result(scope.send("GetStatus"))["last_acquisition"]["state"] == "done"
        header, planes = read_mraw(file)
        assert header["planes"] == 3 and len(planes) == 3
        assert len(planes[0]) == header["width"] * header["height"]
        assert header["stage_um"]["x"] == START_POSITION["x"]
        assert header["objective"]["slot"] == 1

    def test_busy_while_acquiring(self, scope):
        _result(scope.send("StartAcquisition", name="busy"))
        assert scope.send("MoveStage", x=1.0)["code"] == 100
        assert scope.send("SetSetting", name="exposure_ms", value=5.0)["code"] == 100
        assert _result(scope.send("GetStatus"))["state"] == "acquiring"

    def test_never_overwrites(self, scope, clock):
        first = _picture(scope, clock, "same")[0]
        second_file = _result(scope.send("StartAcquisition", name="same"))["file"]
        assert first["name"] == "same"
        assert second_file.endswith("same_001.mraw")

    def test_abort_leaves_the_file_incomplete(self, scope, clock):
        file = _result(scope.send("StartAcquisition", name="stopped", z_planes=10))["file"]
        _result(scope.send("Abort"))
        clock.advance(5.0)
        assert _result(scope.send("GetStatus"))["last_acquisition"]["state"] == "aborted"
        with pytest.raises(ValueError, match="incomplete"):
            read_mraw(file)

    def test_bad_name_is_refused(self, scope):
        assert scope.send("StartAcquisition", name="../escape")["code"] == 205

    def test_not_an_mraw_file(self, tmp_path):
        other = tmp_path / "other.txt"
        other.write_text("hello\nworld")
        with pytest.raises(ValueError):
            read_mraw(other)


class TestPictures:
    def test_same_place_same_picture(self, tmp_path, clock):
        mock = MockScope(output_folder=tmp_path, clock=clock, noise=False)
        mock.send("Login", token="mock-token")
        _, first = _picture(mock, clock, "one")
        _, second = _picture(mock, clock, "two")
        assert first[0] == second[0]

    @pytest.mark.parametrize("orientation", [((1, 0), (0, 1)), ((0, 1), (1, 0)), ((0, -1), (1, 0))])
    def test_stage_steps_shift_the_picture_as_the_orientation_says(
        self, tmp_path, clock, orientation
    ):
        mock = MockScope(output_folder=tmp_path, clock=clock, noise=False, orientation=orientation)
        mock.send("Login", token="mock-token")
        header, before = _picture(mock, clock, "before")
        width, height, pixel = header["width"], header["height"], header["pixel_size_um"]
        step = 5  # pixels
        _result(mock.send("MoveStage", x=START_POSITION["x"] + step * pixel))
        clock.advance(1.0)
        _, after = _picture(mock, clock, "after")
        # A stage step of +x shows up in the picture as this many pixels.
        (a, b), _ = orientation
        shift_col, shift_row = -a * step, -b * step
        compared = 0
        for row in range(height):
            for col in range(width):
                src_row, src_col = row - shift_row, col - shift_col
                if 0 <= src_row < height and 0 <= src_col < width:
                    assert (
                        abs(after[0][row * width + col] - before[0][src_row * width + src_col]) <= 1
                    )
                    compared += 1
        assert compared > width * height // 2

    def test_sharpest_at_the_hidden_focus_height(self, tmp_path, clock):
        mock = MockScope(output_folder=tmp_path, clock=clock, noise=False)
        mock.send("Login", token="mock-token")
        sharp_at = mock.truth()["tilt"]["z0"]
        scores = {}
        for offset in (-10.0, 0.0, 10.0):
            _result(mock.send("MoveFocus", focus=sharp_at + offset))
            clock.advance(1.0)
            header, planes = _picture(mock, clock, f"z{int(offset) + 100}")
            scores[offset] = _brenner(planes[0], header["width"])
        assert scores[0.0] > scores[-10.0]
        assert scores[0.0] > scores[10.0]

    def test_brighter_with_more_laser(self, tmp_path, clock):
        mock = MockScope(output_folder=tmp_path, clock=clock, noise=False)
        mock.send("Login", token="mock-token")
        _, dim = _picture(mock, clock, "dim")
        _result(mock.send("SetSetting", name="laser_power_percent", value=40.0))
        _, bright = _picture(mock, clock, "bright")
        assert sum(bright[0]) > sum(dim[0])

    def test_truth_reports_the_hidden_facts(self, scope):
        truth = scope.truth()
        assert truth["orientation"] == ((0, 1), (1, 0))
        assert truth["objective_offsets_um"][1] == {"x": 0.0, "y": 0.0, "z": 0.0}
        assert set(truth["objective_offsets_um"]) == {1, 2, 3}

    def test_only_turns_and_mirrors_are_allowed(self, tmp_path):
        with pytest.raises(ValueError, match="orientation"):
            MockScope(output_folder=tmp_path, orientation=((1, 1), (0, 1)))


class TestFaults:
    @pytest.mark.parametrize(
        ("fault", "code"),
        [("busy", 100), ("out_of_range", 201), ("hardware_fault", 300), ("unknown_error", 999)],
    )
    def test_refusing_faults_change_nothing(self, scope, fault, code):
        scope.faults.add("MoveStage", fault)
        assert scope.send("MoveStage", x=1_000.0)["code"] == code
        assert _result(scope.send("GetStagePosition"))["x"] == START_POSITION["x"]
        # The fault was used up; the next try works.
        _result(scope.send("MoveStage", x=1_000.0))

    def test_timeout_applies_but_loses_the_reply(self, scope, clock):
        scope.faults.add("MoveStage", "timeout")
        with pytest.raises(TimeoutError):
            scope.send("MoveStage", x=1_000.0)
        clock.advance(5.0)
        assert _result(scope.send("GetStagePosition"))["x"] == 1_000.0

    def test_ignore_says_ok_but_does_nothing(self, scope, clock):
        scope.faults.add("SetSetting", "ignore")
        _result(scope.send("SetSetting", name="exposure_ms", value=50.0))
        clock.advance(1.0)
        assert _result(scope.send("GetSettings"))["exposure_ms"] == 10.0

    def test_stale_repeats_the_last_answer(self, scope, clock):
        before = _result(scope.send("GetStagePosition"))
        _result(scope.send("MoveStage", x=1_000.0))
        clock.advance(5.0)
        scope.faults.add("GetStagePosition", "stale")
        assert _result(scope.send("GetStagePosition")) == before
        assert _result(scope.send("GetStagePosition"))["x"] == 1_000.0

    def test_disconnect_until_restart(self, scope):
        scope.faults.add("GetSettings", "disconnect")
        with pytest.raises(ConnectionError):
            scope.send("GetSettings")
        with pytest.raises(ConnectionError):
            scope.send("GetVersion")
        scope.restart()
        _result(scope.send("Login", token="mock-token"))
        _result(scope.send("GetSettings"))

    def test_disconnect_loses_a_running_acquisition(self, scope):
        _result(scope.send("StartAcquisition", name="lost", z_planes=50))
        scope.faults.add("*", "disconnect")
        with pytest.raises(ConnectionError):
            scope.send("GetStatus")
        scope.restart()
        _result(scope.send("Login", token="mock-token"))
        assert _result(scope.send("GetStatus"))["last_acquisition"]["state"] == "aborted"

    def test_every_time_until_cleared(self, scope):
        scope.faults.add("*", "busy", times=None)
        for _ in range(3):
            assert scope.send("GetSettings")["code"] == 100
        scope.faults.clear()
        _result(scope.send("GetSettings"))

    def test_history_records_faults(self, scope):
        scope.faults.add("GetSettings", "busy")
        scope.send("GetSettings")
        assert scope.history[-1]["fault"] == "busy"
        assert scope.history[-1]["code"] == 100

    def test_unknown_fault_name(self, scope):
        with pytest.raises(ValueError, match="unknown fault"):
            scope.faults.add("GetSettings", "gremlins")

    def test_every_fault_is_described(self):
        assert set(FAULTS) == {
            "busy",
            "out_of_range",
            "hardware_fault",
            "unknown_error",
            "timeout",
            "ignore",
            "stale",
            "disconnect",
        }
