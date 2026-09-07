"""Unit tests for commands.routines.correct_backlash — in-place takeup."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from navigator_expert.commands import routines as stage_movement


class TestCorrectBacklash:
    def test_current_position_read_uses_configured_reader_policy(self):
        """The current XY read must not bypass the configured reader policy."""
        get_xy_calls = []
        move_calls = []

        def fake_get_xy(client, **kwargs):
            get_xy_calls.append(kwargs)
            return {"x_um": 100.0, "y_um": 200.0}

        def fake_move_xy(client, x, y, unit="um", tolerance=None):
            move_calls.append((x, y, unit, tolerance))
            return {"success": True, "confirmed": True}

        with (
            patch.object(stage_movement._readers, "get_xy", side_effect=fake_get_xy),
            patch.object(stage_movement._commands, "move_xy", side_effect=fake_move_xy),
            patch.object(stage_movement.time, "sleep"),
        ):
            stage_movement.correct_backlash(
                client=None,
                overshoot_um=50.0,
                settle_ms=100,
                tolerance_um=20.0,
            )

        assert "mode" not in get_xy_calls[0]
        # Three back-and-forth passes by default, every return leg
        # approaching (x, y) from -X -Y.
        assert (
            move_calls
            == [
                (50.0, 150.0, "um", 20.0),
                (100.0, 200.0, "um", 20.0),
            ]
            * 3
        )

    def test_at_skips_the_position_read(self):
        """A caller that just commanded a confirmed move already knows where
        the stage is; ``at=`` must use that position and never touch the
        reader — one less thing that can fail in the acquisition hot path."""
        move_calls = []

        def fake_move_xy(client, x, y, unit="um", tolerance=None):
            move_calls.append((x, y))
            return {"success": True, "confirmed": True}

        def forbidden_get_xy(client, **kwargs):
            raise AssertionError("at= was given; the position read must not run")

        with (
            patch.object(stage_movement._readers, "get_xy", side_effect=forbidden_get_xy),
            patch.object(stage_movement._commands, "move_xy", side_effect=fake_move_xy),
            patch.object(stage_movement.time, "sleep"),
        ):
            stage_movement.correct_backlash(
                client=None, at=(100.0, 200.0), overshoot_um=10.0, passes=1
            )
        assert move_calls == [(90.0, 190.0), (100.0, 200.0)]

    def test_passes_controls_the_number_of_round_trips(self):
        move_calls = []

        def fake_move_xy(client, x, y, unit="um", tolerance=None):
            move_calls.append((x, y))
            return {"success": True, "confirmed": True}

        with (
            patch.object(
                stage_movement._readers,
                "get_xy",
                return_value={"x_um": 0.0, "y_um": 0.0},
            ),
            patch.object(stage_movement._commands, "move_xy", side_effect=fake_move_xy),
            patch.object(stage_movement.time, "sleep"),
        ):
            stage_movement.correct_backlash(client=None, overshoot_um=10.0, passes=1)
        assert move_calls == [(-10.0, -10.0), (0.0, 0.0)]

    def test_zero_passes_is_refused(self):
        with pytest.raises(ValueError, match="at least one"):
            stage_movement.correct_backlash(client=None, passes=0)

    def test_fractional_passes_are_refused(self):
        """3.9 must not silently truncate to 3 — refuse anything non-whole."""
        with pytest.raises(ValueError, match="whole number"):
            stage_movement.correct_backlash(client=None, passes=3.9)

    def test_every_pass_sleeps_and_pass_boundaries_sleep_too(self):
        """The settle pause must separate EVERY consecutive pair of moves.

        Without the pause a controller that blends consecutive commands
        would run the return of one pass straight into the overshoot of
        the next, and the extra passes would settle nothing. Pinning the
        full interleaving also catches a regression that hoists the sleep
        out of the loop (one sleep total instead of one per gap).
        """
        calls = []

        def fake_move_xy(client, x, y, unit="um", tolerance=None):
            calls.append(("move", x, y))
            return {"success": True, "confirmed": True}

        with (
            patch.object(
                stage_movement._readers,
                "get_xy",
                return_value={"x_um": 100.0, "y_um": 200.0},
            ),
            patch.object(stage_movement._commands, "move_xy", side_effect=fake_move_xy),
            patch.object(
                stage_movement.time, "sleep", side_effect=lambda s: calls.append(("sleep", s))
            ),
        ):
            stage_movement.correct_backlash(client=None, overshoot_um=50.0, settle_ms=100)

        pass_moves = [("move", 50.0, 150.0), ("sleep", 0.1), ("move", 100.0, 200.0)]
        boundary = [("sleep", 0.1)]
        assert calls == pass_moves + boundary + pass_moves + boundary + pass_moves

    def test_an_unconfirmed_leg_raises(self):
        """success without confirmed means "accepted, no readback proof" —
        continuing would let the following capture fire while the stage is
        still travelling."""
        results = iter(
            [
                {"success": True, "confirmed": True},
                {"success": True, "confirmed": False},  # return leg unconfirmed
            ]
        )

        with (
            patch.object(
                stage_movement._readers,
                "get_xy",
                return_value={"x_um": 0.0, "y_um": 0.0},
            ),
            patch.object(
                stage_movement._commands, "move_xy", side_effect=lambda *a, **k: next(results)
            ),
            patch.object(stage_movement.time, "sleep"),
        ):
            with pytest.raises(RuntimeError, match="unconfirmed"):
                stage_movement.correct_backlash(client=None)

    def test_a_failed_leg_in_a_later_pass_stops_the_takeup(self):
        """A pass-2 failure must raise and fire no further moves — silently
        continuing (or breaking out early) would hand the stage to the
        following capture in an unknown slack-state, possibly parked at the
        overshoot point."""
        moves = []
        results = iter(
            [
                {"success": True, "confirmed": True},  # pass 1 overshoot
                {"success": True, "confirmed": True},  # pass 1 return
                {"success": True, "confirmed": True},  # pass 2 overshoot
                {"success": False, "error": "limit"},  # pass 2 return fails
            ]
        )

        def fake_move_xy(client, x, y, unit="um", tolerance=None):
            moves.append((x, y))
            return next(results)

        with (
            patch.object(
                stage_movement._readers,
                "get_xy",
                return_value={"x_um": 0.0, "y_um": 0.0},
            ),
            patch.object(stage_movement._commands, "move_xy", side_effect=fake_move_xy),
            patch.object(stage_movement.time, "sleep"),
        ):
            with pytest.raises(RuntimeError, match="return move failed"):
                stage_movement.correct_backlash(client=None, overshoot_um=10.0)
        assert len(moves) == 4  # nothing fired after the failed leg
