"""Unit test for drv.move_xy_with_backlash — transit-with-takeup pattern."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from navigator_expert.stage import movement as stage_movement


class TestMoveXyWithBacklash:
    def test_three_call_sequence(self):
        """Overshoot → sleep → final approach. Verifies the order and
        the exact XY values handed to move_xy."""
        calls = []

        def fake_move_xy(client, x, y, unit="um"):
            calls.append(("move", x, y, unit))
            return {"success": True}

        def fake_sleep(s):
            calls.append(("sleep", s))

        with patch.object(stage_movement._commands, "move_xy",
                          side_effect=fake_move_xy), \
             patch.object(stage_movement.time, "sleep", side_effect=fake_sleep):
            stage_movement.move_xy_with_backlash(
                client=None, x_um=100.0, y_um=200.0,
                overshoot_um=50.0, settle_ms=100,
            )

        assert calls == [
            ("move", 50.0, 150.0, "um"),   # overshoot to (x-50, y-50)
            ("sleep", 0.1),                # 100 ms
            ("move", 100.0, 200.0, "um"),  # final approach
        ]

    def test_overshoot_failure_raises(self):
        """Silent continue after a failed overshoot would image at an
        uncompensated position — the bug backlash exists to prevent.
        Fail loud instead."""
        def fake_move_xy(client, x, y, unit="um"):
            return {"success": False, "error": "timeout"}

        with patch.object(stage_movement._commands, "move_xy",
                          side_effect=fake_move_xy), \
             patch.object(stage_movement.time, "sleep"):
            with pytest.raises(RuntimeError, match="backlash overshoot"):
                stage_movement.move_xy_with_backlash(
                    client=None, x_um=100.0, y_um=200.0,
                )

    def test_final_move_failure_raises(self):
        """Final approach failure also raises — the primitive is
        self-contained, callers shouldn't have to recheck the return
        value to detect a half-completed positioning."""
        results = iter([
            {"success": True},                      # overshoot succeeds
            {"success": False, "error": "limit"},   # final fails
        ])

        def fake_move_xy(client, x, y, unit="um"):
            return next(results)

        with patch.object(stage_movement._commands, "move_xy",
                          side_effect=fake_move_xy), \
             patch.object(stage_movement.time, "sleep"):
            with pytest.raises(RuntimeError, match="final approach"):
                stage_movement.move_xy_with_backlash(
                    client=None, x_um=100.0, y_um=200.0,
                )

    def test_returns_final_move_result(self):
        """Return value is the final move's result so callers can check
        success the same way they would for plain move_xy."""
        results = [{"success": True}, {"success": True, "x_um": 100, "y_um": 200}]

        def fake_move_xy(client, x, y, unit="um"):
            return results.pop(0)

        with patch.object(stage_movement._commands, "move_xy",
                          side_effect=fake_move_xy), \
             patch.object(stage_movement.time, "sleep"):
            r = stage_movement.move_xy_with_backlash(
                client=None, x_um=100.0, y_um=200.0,
            )

        assert r == {"success": True, "x_um": 100, "y_um": 200}
