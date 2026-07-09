"""CommandProfile construction, the coherence guard, and per-command postures."""

import pytest
from zenapi.config.profiles import (
    FOCUS_MOVE,
    OBJECTIVE,
    RUN_EXPERIMENT,
    SNAP,
    STAGE_MOVE,
    CommandProfile,
)


def test_guard_rejects_single_attempt_with_refire():
    with pytest.raises(ValueError, match="refire_on_unconfirmed"):
        CommandProfile(max_confirm_attempts=1, refire_on_unconfirmed=True)


def test_single_attempt_without_refire_is_ok():
    p = CommandProfile(max_confirm_attempts=1, refire_on_unconfirmed=False)
    assert p.max_confirm_attempts == 1


def test_move_postures():
    assert STAGE_MOVE.confirm_tolerance == 1.0
    assert FOCUS_MOVE.confirm_tolerance == 0.5
    for p in (STAGE_MOVE, FOCUS_MOVE, OBJECTIVE):
        assert p.max_confirm_attempts == 1
        assert p.refire_on_unconfirmed is False


def test_acquire_never_refires():
    for p in (SNAP, RUN_EXPERIMENT):
        assert p.max_retries == 0
        assert p.refire_on_unconfirmed is False
        assert p.success_on_unconfirmed is True
        assert p.call_timeout is None  # long acquisition; stream is the gate
