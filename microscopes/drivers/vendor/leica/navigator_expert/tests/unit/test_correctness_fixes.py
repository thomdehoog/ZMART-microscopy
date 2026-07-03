"""Regression tests for the driver correctness fixes (fail-closed behavior)."""

from unittest.mock import patch

import pytest
from navigator_expert.commands import confirmations
from navigator_expert.runtime import session
from navigator_expert.state_readers import derived


def test_base_fov_does_not_clamp_sub_one_zoom():
    """Zoom < 1 must scale the base FOV, not be clamped to 1 (C3)."""
    settings = {"zoom": {"current": 0.75}}
    with patch.object(derived, "parse_tile_geometry", return_value={"tile_w_um": 100.0, "tile_h_um": 100.0}):
        w, h = derived.base_fov_from_settings(settings)
    assert w == pytest.approx(100e-6 * 0.75)
    assert h == pytest.approx(100e-6 * 0.75)


def test_orientation_check_fails_closed_when_settings_unreadable():
    """An unverifiable orientation must raise, not silently pass (C2)."""
    with patch.object(session._readers, "get_lasx_settings", return_value=None):
        with pytest.raises(RuntimeError, match="cannot confirm"):
            session.require_canonical_scan_orientation()


def test_orientation_check_fails_closed_when_section_absent():
    with patch.object(session._readers, "get_lasx_settings", return_value={}):
        with pytest.raises(RuntimeError, match="cannot confirm"):
            session.require_canonical_scan_orientation()


def test_orientation_check_passes_when_topleft():
    settings = {"image_orientation": {"enable_transform": False}}
    with patch.object(session._readers, "get_lasx_settings", return_value=settings):
        session.require_canonical_scan_orientation()  # no raise


def test_confirm_acquire_rejects_unknown_as_scan_start():
    """A transient Unknown read must not latch saw_scanning into a false success (C1).

    Sequence: one Unknown read, then steady Idle. Under the old behavior Unknown
    counted as scanning, so two Idle reads returned success=True for a scan that
    never ran. Fixed, the scan never starts and confirmation fails.
    """
    statuses = [None, "eScanIdle", "eScanIdle", "eScanIdle", "eScanIdle"]

    def fake_get_scan_status(client, **kwargs):
        return statuses.pop(0) if statuses else "eScanIdle"

    with (
        patch.object(confirmations._readers, "get_scan_status", side_effect=fake_get_scan_status),
        patch.object(confirmations, "_check_api_error", return_value=None),
    ):
        result = confirmations.confirm_acquire(
            object(), start_timeout=0.05, poll_interval=0.01
        )
    assert result["success"] is False
