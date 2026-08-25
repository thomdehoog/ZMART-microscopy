"""
Unit tests for ``readers/z_readback.py`` — Z readback that stays honest on a
stacked drive (no LAS X needed).
==========================================================================
Background, measured on the simulator 2026-08-25: the ``zPosition`` field of
the job settings freezes for whichever drive carries the job's z-stack, so a
plain settings read reports a stale value for that drive after a move. The
saved experiment (``.lrp``) does update on save. These tests pin the reader
that chooses between the two: the settings path when the requested drive is
free, the save-and-parse path only when the drive is the stack drive — and
that the choice costs nothing on the free path.
"""

from pathlib import Path

import pytest
from navigator_expert.readers import z_readback
from navigator_expert.readers.z_readback import (
    ZReading,
    drive_is_stacked,
    read_z,
    stacked_drive,
    z_um_from_lrp,
)
from navigator_expert.scanfields.lrp import parse_lrp

TEST_DATA = Path(__file__).resolve().parents[1] / "data"
# A LAS X export with a z-galvo stack on every job (ZUseMode=1, Begin/End set).
GALVO_STACK_LRP = TEST_DATA / "scanfield_parsing" / "_ScanningTemplate_Test1.lrp"
# Its Master ZPosition for "AF Job", in metres, as committed.
GALVO_STACK_AF_JOB_Z_M = -3.6358824644270953e-09


def raw_settings(*, galvo_um, wide_um, stack_on=None):
    """Raw job settings in the shape ``get_job_settings`` returns.

    Only the keys ``make_changeable_copy`` requires plus the two the reader
    looks at, so a test states exactly what it depends on. LAS X nests each
    drive's value as ``{"position": ...}``; that is the shape the parser
    unwraps, so it is the shape used here.
    """
    settings = {
        "zoom": {"current": 1.0},
        "scanSpeed": {"value": 400, "isResonant": False},
        "activeSettings": [],
        "scanMode": "xyz",
        "zPosition": {"z-galvo": {"position": galvo_um}, "z-wide": {"position": wide_um}},
    }
    if stack_on is not None:
        settings["stack"] = {
            "begin": -10.0,
            "end": 10.0,
            "stepSize": 1.0,
            "size": 20.0,
            "sections": 21,
            "mode": stack_on,
        }
    return settings


class TestStackedDrive:
    def test_no_stack_block_means_no_stacked_drive(self):
        assert stacked_drive(raw_settings(galvo_um=0.0, wide_um=4999.5)) is None

    def test_stack_names_its_drive(self):
        assert (
            stacked_drive(raw_settings(galvo_um=0.0, wide_um=4999.5, stack_on="z-galvo"))
            == "z-galvo"
        )
        assert (
            stacked_drive(raw_settings(galvo_um=0.0, wide_um=4999.5, stack_on="z-wide")) == "z-wide"
        )

    def test_drive_is_stacked_only_for_the_stack_drive(self):
        settings = raw_settings(galvo_um=0.0, wide_um=4999.5, stack_on="z-galvo")
        assert drive_is_stacked(settings, "z-galvo") is True
        assert drive_is_stacked(settings, "z-wide") is False

    def test_unknown_drive_is_refused(self):
        with pytest.raises(ValueError, match="z-piezo"):
            drive_is_stacked(raw_settings(galvo_um=0.0, wide_um=0.0), "z-piezo")


class TestZFromLrp:
    def test_reads_master_z_position_in_um(self):
        data = parse_lrp(GALVO_STACK_LRP)
        z_um = z_um_from_lrp(data, "AF Job", "z-galvo")
        assert z_um == pytest.approx(GALVO_STACK_AF_JOB_Z_M * 1e6)

    def test_refuses_a_drive_the_file_does_not_hold(self):
        # The file carries ONE ZPosition per job: the drive named by ZUseMode
        # (1 = z-galvo here). Reporting it as z-wide would be a wrong number
        # with a confident label, so it must refuse.
        data = parse_lrp(GALVO_STACK_LRP)
        with pytest.raises(RuntimeError, match="z-wide"):
            z_um_from_lrp(data, "AF Job", "z-wide")

    def test_refuses_a_missing_job(self):
        data = parse_lrp(GALVO_STACK_LRP)
        with pytest.raises(RuntimeError, match="No such job"):
            z_um_from_lrp(data, "Not A Job", "z-galvo")


class TestReadZ:
    """The reader's one decision, and that it costs nothing when it says no."""

    def _install(self, monkeypatch, settings, lrp_data=None):
        calls = {"settings": 0, "save": 0}

        def fake_get_job_settings(client, job_name, *, mode=None, **kwargs):
            calls["settings"] += 1
            return settings

        def fake_save_and_read_lrp(client, *, timeout=5.0):
            calls["save"] += 1
            return lrp_data

        monkeypatch.setattr(z_readback, "get_job_settings", fake_get_job_settings)
        monkeypatch.setattr(z_readback, "save_and_read_lrp", fake_save_and_read_lrp)
        return calls

    def test_free_drive_reads_settings_and_never_saves(self, monkeypatch):
        calls = self._install(monkeypatch, raw_settings(galvo_um=15.0, wide_um=4999.5))
        reading = read_z(None, "AF Job", "z-galvo")
        assert reading == ZReading(z_um=15.0, drive="z-galvo", job_name="AF Job", source="settings")
        assert calls == {"settings": 1, "save": 0}

    def test_other_drive_stays_on_the_settings_path(self, monkeypatch):
        # Stack on the galvo: z-wide is free and must not pay for a save.
        calls = self._install(
            monkeypatch, raw_settings(galvo_um=-0.01, wide_um=4999.5, stack_on="z-galvo")
        )
        reading = read_z(None, "AF Job", "z-wide")
        assert reading.z_um == 4999.5
        assert reading.source == "settings"
        assert calls == {"settings": 1, "save": 0}

    def test_stacked_drive_saves_once_and_reads_the_lrp(self, monkeypatch):
        calls = self._install(
            monkeypatch,
            raw_settings(galvo_um=-0.01, wide_um=4999.5, stack_on="z-galvo"),
            lrp_data=parse_lrp(GALVO_STACK_LRP),
        )
        reading = read_z(None, "AF Job", "z-galvo")
        assert reading.source == "lrp"
        assert reading.z_um == pytest.approx(GALVO_STACK_AF_JOB_Z_M * 1e6)
        assert calls == {"settings": 1, "save": 1}

    def test_stacked_drive_with_failed_save_raises_rather_than_reporting_stale(self, monkeypatch):
        self._install(
            monkeypatch,
            raw_settings(galvo_um=-0.01, wide_um=4999.5, stack_on="z-galvo"),
            lrp_data=None,
        )
        with pytest.raises(RuntimeError, match="save"):
            read_z(None, "AF Job", "z-galvo")

    def test_unreadable_settings_raise(self, monkeypatch):
        self._install(monkeypatch, None)
        with pytest.raises(RuntimeError, match="job settings"):
            read_z(None, "AF Job", "z-galvo")
