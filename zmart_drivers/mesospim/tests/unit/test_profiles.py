"""Config profiles: defaults and the confirm/refire guard."""

from __future__ import annotations

from mesospim.config import profiles


def test_connection_defaults():
    assert profiles.CONNECTION.host == "127.0.0.1"
    assert profiles.CONNECTION.port == 42000


def test_command_profile_guard():
    prof = profiles.CommandProfile(max_confirm_attempts=1, refire_on_unconfirmed=True)
    assert prof.refire_on_unconfirmed is False


def test_move_profiles_accept_unconfirmed():
    assert profiles.MOVE.success_on_unconfirmed is True
    assert profiles.MOVE_ROTATION.success_on_unconfirmed is True


def test_hardware_model_present():
    hw = profiles.HARDWARE
    assert any(name == "488 nm" for name, _wl in hw.lasers)
    assert any(name == "1x" for name, _px in hw.zoom_pixel_size_um)
    assert "Both" in hw.shutter_configs


def test_acquisition_formats_and_procedures():
    assert "ome-tiff" in profiles.ACQUISITION.formats
    names = [n for n, _d in profiles.ACQUISITION.procedures]
    assert "autofocus" in names
