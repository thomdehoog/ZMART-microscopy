"""
Unit tests: the Z readback falls back to the saved experiment on the stacked drive.
================================================================================
Measured on the simulator 2026-08-25/26: LAS X stops refreshing the job
settings' ``zPosition`` for whichever drive carries the job's z-stack, while
the saved experiment (``.lrp``) records the command. ``z_um_from_settings``
is where every Z number in the driver is made, so the fallback lives there:
the free drive is read from the settings as before, at no extra cost; the
stacked drive is read from the ``.lrp`` after one save. Two experiments
saved from the simulator, one per drive, are the fixtures.
"""

import time
from pathlib import Path
from unittest.mock import patch

import pytest
from navigator_expert import readers
from navigator_expert.commands import commands, confirmations
from navigator_expert.readers import derived
from navigator_expert.readers.derived import z_um_from_settings
from navigator_expert.readers.parsing import make_changeable_copy
from navigator_expert.scanfields.lrp import parse_lrp
from navigator_expert.zmart_adapter import zmart_adapter as adapter

TEST_DATA = Path(__file__).resolve().parents[1] / "data"
SAVED = TEST_DATA / "z_readback"
# Saved from the simulator with "AF Job 01" selected: its stack on the galvo
# (galvo at 0 µm, ZUseMode 1) and on z-wide (z-wide at 4999.5 µm, ZUseMode 2).
SAVED_GALVO_STACK = SAVED / "_ScanningTemplate_galvo_stack.lrp"
SAVED_ZWIDE_STACK = SAVED / "_ScanningTemplate_zwide_stack.lrp"


def raw_settings(*, galvo_um=0.0, wide_um=4999.5, stack_on=None):
    """Raw job settings as ``get_job_settings`` returns them (LAS X nests each
    drive's value as ``{"position": ...}``)."""
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


def saved(job_name, drive, z_um):
    """Parsed-.lrp shaped data with one job's Master ZPosition (metres)."""
    return {
        "sequence_name": "collecting pattern",
        "sequence_elements": [],
        "jobs": {
            job_name: {"Master": {"attrs": {"ZPosition": repr(z_um * 1e-6), "ZUseModeName": drive}}}
        },
    }


class TestFreeDrive:
    def test_reads_the_settings_and_never_saves(self, monkeypatch):
        monkeypatch.setattr(derived, "save_and_read_lrp", lambda c, **k: pytest.fail("no save"))
        settings = raw_settings(galvo_um=15.0, stack_on="z-wide")
        assert z_um_from_settings(settings, "z-galvo", client=object(), job_name="J") == 15.0

    def test_no_stack_at_all_is_the_old_path_exactly(self):
        assert z_um_from_settings(raw_settings(galvo_um=3.0, wide_um=7.0), "z-galvo") == 3.0
        assert z_um_from_settings(raw_settings(galvo_um=3.0, wide_um=7.0), "z-wide") == 7.0

    def test_normalised_settings_are_accepted_too(self):
        # The confirmation holds a make_changeable_copy; one extractor serves both.
        ch = make_changeable_copy(raw_settings(galvo_um=15.0))
        assert z_um_from_settings(ch, "z-galvo") == 15.0


class TestStackedDrive:
    def test_saves_once_and_reads_the_job_from_the_lrp(self, monkeypatch):
        saves = []

        def fake_save(client, **kwargs):
            saves.append(client)
            return saved("AF Job 01", "z-galvo", 15.0)

        monkeypatch.setattr(derived, "save_and_read_lrp", fake_save)
        settings = raw_settings(galvo_um=-0.01, stack_on="z-galvo")
        assert z_um_from_settings(
            settings, "z-galvo", client="C", job_name="AF Job 01"
        ) == pytest.approx(15.0)
        assert saves == ["C"]

    def test_the_two_saved_experiments(self, monkeypatch):
        monkeypatch.setattr(
            derived, "save_and_read_lrp", lambda c, **k: parse_lrp(SAVED_ZWIDE_STACK)
        )
        settings = raw_settings(stack_on="z-wide")
        assert z_um_from_settings(
            settings, "z-wide", client=object(), job_name="AF Job 01"
        ) == pytest.approx(4999.5)
        monkeypatch.setattr(
            derived, "save_and_read_lrp", lambda c, **k: parse_lrp(SAVED_GALVO_STACK)
        )
        settings = raw_settings(stack_on="z-galvo")
        assert z_um_from_settings(
            settings, "z-galvo", client=object(), job_name="AF Job 01"
        ) == pytest.approx(0.0)

    def test_refuses_without_a_client_or_job_rather_than_reporting_stale(self):
        settings = raw_settings(galvo_um=-0.01, stack_on="z-galvo")
        with pytest.raises(RuntimeError, match="z-stack"):
            z_um_from_settings(settings, "z-galvo")

    def test_refuses_when_the_save_fails(self, monkeypatch):
        monkeypatch.setattr(derived, "save_and_read_lrp", lambda c, **k: None)
        with pytest.raises(RuntimeError, match="save"):
            z_um_from_settings(
                raw_settings(stack_on="z-galvo"), "z-galvo", client=object(), job_name="J"
            )

    def test_refuses_a_file_that_names_the_other_drive(self, monkeypatch):
        # One ZPosition per job, for the drive its ZUseModeName names.
        monkeypatch.setattr(
            derived, "save_and_read_lrp", lambda c, **k: parse_lrp(SAVED_GALVO_STACK)
        )
        with pytest.raises(RuntimeError, match="z-galvo"):
            z_um_from_settings(
                raw_settings(stack_on="z-wide"), "z-wide", client=object(), job_name="AF Job 01"
            )


class TestCallers:
    """The routed reader, the confirmation and the adapter all get the fallback."""

    def test_read_zwide_um_falls_back(self, monkeypatch):
        monkeypatch.setattr(
            readers.router, "get_job_settings", lambda c, j, **k: raw_settings(stack_on="z-wide")
        )
        monkeypatch.setattr(
            derived, "save_and_read_lrp", lambda c, **k: saved("AF Job 01", "z-wide", 5009.5)
        )
        assert readers.read_zwide_um(object(), "AF Job 01", mode="api") == pytest.approx(5009.5)

    def test_confirm_move_z_confirms_through_the_lrp(self, monkeypatch):
        monkeypatch.setattr(
            derived, "save_and_read_lrp", lambda c, **k: saved("J", "z-galvo", 50.0)
        )
        ch = make_changeable_copy(raw_settings(galvo_um=-0.01, stack_on="z-galvo"))
        with patch.object(confirmations, "_readback", return_value=ch):
            result = confirmations.confirm_move_z(
                object(), job_name="J", z_mode="galvo", target_um=50.0, poll_window=1.0
            )
        assert result["success"] is True

    def test_adapter_snapshot_falls_back(self, monkeypatch):
        monkeypatch.setattr(adapter._readers, "get_xy", lambda c: {"x_um": 1.0, "y_um": 2.0})
        monkeypatch.setattr(
            adapter._readers, "get_selected_job", lambda c, **k: {"Name": "AF Job 01"}
        )
        monkeypatch.setattr(
            adapter._readers,
            "get_job_settings",
            lambda c, j, **k: raw_settings(galvo_um=-0.01, stack_on="z-galvo"),
        )
        monkeypatch.setattr(
            derived, "save_and_read_lrp", lambda c, **k: saved("AF Job 01", "z-galvo", 15.0)
        )
        snap = adapter._hardware_snapshot(type("H", (), {"client": object()})())
        assert snap["z_galvo_um"] == pytest.approx(15.0)
        assert snap["z_wide_um"] == 4999.5


class TestMoveZEndToEnd:
    """Through the command backbone, against the behavioural mock, which
    freezes the stacked drive's zPosition the way LAS X does."""

    def _client(self, stack_on):
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "helpers"))
        from limits_fixtures import install_permissive_limits
        from mock_lasx_api import MockLasxClient

        client = MockLasxClient()
        for job in client._jobs.values():
            if job.get("stack"):
                job["stack"]["mode"] = stack_on
        install_permissive_limits(client, wide_stage=True)
        return client

    def test_the_mock_freezes_the_stacked_drive(self):
        client = self._client("z-galvo")
        before = readers.get_job_settings(client, "HiRes", mode="api")["zPosition"]["z-galvo"][
            "position"
        ]
        with patch.object(
            derived, "save_and_read_lrp", lambda c, **k: saved("HiRes", "z-galvo", 12.0)
        ):
            commands.move_z(client, "HiRes", 12.0, z_mode="galvo")
        after = readers.get_job_settings(client, "HiRes", mode="api")["zPosition"]["z-galvo"][
            "position"
        ]
        assert after == before

    def test_stack_drive_move_is_confirmed_in_one_attempt(self, monkeypatch):
        client = self._client("z-galvo")
        monkeypatch.setattr(
            derived, "save_and_read_lrp", lambda c, **k: saved("HiRes", "z-galvo", 12.0)
        )
        t0 = time.perf_counter()
        result = commands.move_z(client, "HiRes", 12.0, z_mode="galvo")
        assert (result["success"], result["confirmed"], result["timing"]["attempts"]) == (
            True,
            True,
            1,
        )
        assert time.perf_counter() - t0 < 3.0

    def test_free_drive_move_is_confirmed_as_before(self):
        client = self._client("z-galvo")
        result = commands.move_z(client, "HiRes", 25.0, z_mode="zwide")
        assert (result["success"], result["confirmed"]) == (True, True)
