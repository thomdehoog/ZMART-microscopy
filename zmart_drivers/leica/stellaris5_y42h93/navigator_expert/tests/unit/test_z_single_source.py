"""
Unit tests: Z has one source, and the stacked drive is handled there once.
========================================================================
The measured LAS X behaviour (2026-08-25/26): the job settings' ``zPosition``
freezes for whichever drive carries the job's z-stack; the saved experiment
(``.lrp``) records the commanded value. ``readers/z_readback`` owns that
decision. These tests pin that every consumer — the routed readers, the
move confirmation, the adapter's hardware snapshot — gets Z from it, that
the stacked-drive policy comes from the state-reader profile, and that a
move on the stacked drive is confirmed by one save instead of a polling
loop that re-sends the command.
"""

import dataclasses
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from navigator_expert import readers
from navigator_expert.commands import commands, confirmations
from navigator_expert.config import profiles
from navigator_expert.readers import z_readback
from navigator_expert.readers.derived import z_um_from_settings
from navigator_expert.readers.parsing import make_changeable_copy
from navigator_expert.readers.z_readback import ZReading, stacked_drive, z_reading
from navigator_expert.scanfields.lrp import parse_lrp
from navigator_expert.zmart_adapter import zmart_adapter as adapter

TEST_DATA = Path(__file__).resolve().parents[1] / "data"
SAVED_GALVO_STACK = TEST_DATA / "z_readback" / "_ScanningTemplate_galvo_stack.lrp"


def raw_settings(*, galvo_um=0.0, wide_um=4999.5, stack_on=None):
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


def lrp_with(job_name, drive, z_um):
    """Parsed-.lrp shaped data with one job's Master ZPosition set (metres)."""
    return {
        "sequence_name": "collecting pattern",
        "sequence_elements": [],
        "jobs": {
            job_name: {
                "Master": {"attrs": {"ZPosition": repr(z_um * 1e-6), "ZUseModeName": drive}},
            }
        },
    }


@pytest.fixture
def policy(monkeypatch):
    """Set the stacked-drive readback policy for one test."""

    def _set(value):
        monkeypatch.setattr(
            profiles,
            "STATE_READERS",
            dataclasses.replace(profiles.STATE_READERS, z_stack_drive_readback=value),
        )

    return _set


class TestProfile:
    def test_the_policy_lives_in_the_state_reader_profile_and_defaults_to_lrp(self):
        assert profiles.STATE_READERS.z_stack_drive_readback == "lrp"


class TestSettingsShape:
    """The decision and the extraction work on raw and on normalised settings."""

    def test_stacked_drive_from_a_changeable_copy(self):
        ch = make_changeable_copy(raw_settings(stack_on="z-wide"))
        assert stacked_drive(ch) == "z-wide"
        assert stacked_drive(make_changeable_copy(raw_settings())) is None

    def test_z_from_a_changeable_copy(self):
        # Normalisation is idempotent, so one extractor serves both shapes.
        ch = make_changeable_copy(raw_settings(galvo_um=15.0))
        assert z_um_from_settings(ch, "z-galvo") == 15.0
        assert z_um_from_settings(raw_settings(galvo_um=15.0), "z-galvo") == 15.0


class TestZReadingPolicy:
    def test_policy_none_refuses_the_stack_drive_without_saving(self, policy, monkeypatch):
        policy("none")
        saves = []
        monkeypatch.setattr(z_readback, "save_and_read_lrp", lambda c, **k: saves.append(1))
        with pytest.raises(RuntimeError, match="z_stack_drive_readback"):
            z_reading(None, "AF Job 01", "z-galvo", raw_settings(stack_on="z-galvo"))
        assert saves == []

    def test_policy_none_leaves_the_free_drive_alone(self, policy):
        policy("none")
        r = z_reading(None, "AF Job 01", "z-wide", raw_settings(stack_on="z-galvo"))
        assert r == ZReading(z_um=4999.5, drive="z-wide", job_name="AF Job 01", source="settings")

    def test_policy_lrp_saves_for_the_stack_drive(self, policy, monkeypatch):
        policy("lrp")
        monkeypatch.setattr(
            z_readback, "save_and_read_lrp", lambda c, **k: lrp_with("AF Job 01", "z-galvo", 15.0)
        )
        r = z_reading(None, "AF Job 01", "z-galvo", raw_settings(stack_on="z-galvo"))
        assert r.source == "lrp"
        assert r.z_um == pytest.approx(15.0)


class TestRoutedReaders:
    """read_zwide_um / read_zgalvo_um are thin over the one source."""

    def test_both_drives_have_a_named_reader(self):
        assert callable(readers.read_zwide_um)
        assert callable(readers.read_zgalvo_um)

    def test_free_drive_costs_one_settings_read_and_no_save(self, monkeypatch):
        calls = {"settings": 0, "save": 0}

        def fake_settings(client, job_name, **kwargs):
            calls["settings"] += 1
            return raw_settings(galvo_um=3.0, stack_on="z-wide")

        monkeypatch.setattr(readers.router, "get_job_settings", fake_settings)
        monkeypatch.setattr(
            z_readback, "save_and_read_lrp", lambda c, **k: calls.__setitem__("save", 1)
        )
        assert readers.read_zgalvo_um(object(), "AF Job 01", mode="api") == 3.0
        assert calls == {"settings": 1, "save": 0}

    def test_stack_drive_reads_the_saved_experiment(self, monkeypatch):
        monkeypatch.setattr(
            readers.router, "get_job_settings", lambda c, j, **k: raw_settings(stack_on="z-wide")
        )
        monkeypatch.setattr(
            z_readback, "save_and_read_lrp", lambda c, **k: lrp_with("AF Job 01", "z-wide", 5009.5)
        )
        assert readers.read_zwide_um(object(), "AF Job 01", mode="api") == pytest.approx(5009.5)

    def test_unreadable_settings_still_return_none(self, monkeypatch):
        monkeypatch.setattr(readers.router, "get_job_settings", lambda c, j, **k: None)
        assert readers.read_zwide_um(object(), "AF Job 01", mode="api") is None


class TestConfirmMoveZOnTheStackDrive:
    """One save, one comparison, no polling loop, no re-fire."""

    def _readback(self, settings):
        return patch.object(confirmations, "_readback", return_value=make_changeable_copy(settings))

    def test_lrp_matching_the_target_is_accepted_not_verified(self, monkeypatch):
        saves = []

        def fake_save(client, **kwargs):
            saves.append(1)
            return lrp_with("J", "z-galvo", 50.0)

        monkeypatch.setattr(z_readback, "save_and_read_lrp", fake_save)
        with self._readback(raw_settings(galvo_um=-0.01, stack_on="z-galvo")):
            t0 = time.perf_counter()
            result = confirmations.confirm_move_z(
                None, job_name="J", z_mode="galvo", target_um=50.0, poll_window=5.0
            )
        assert result["success"] is True
        assert result["confirmed"] is None
        assert saves == [1]
        assert time.perf_counter() - t0 < 1.0, "must not sit in the polling window"
        assert any("stack drive" in str(entry).lower() for entry in result["logs"])

    def test_lrp_disagreeing_with_the_target_fails_so_the_command_is_resent(self, monkeypatch):
        monkeypatch.setattr(
            z_readback, "save_and_read_lrp", lambda c, **k: lrp_with("J", "z-galvo", 10.0)
        )
        with self._readback(raw_settings(galvo_um=-0.01, stack_on="z-galvo")):
            result = confirmations.confirm_move_z(
                None, job_name="J", z_mode="galvo", target_um=50.0, poll_window=0.1
            )
        assert result["success"] is False

    def test_failed_save_is_accepted_not_verified(self, monkeypatch):
        monkeypatch.setattr(z_readback, "save_and_read_lrp", lambda c, **k: None)
        with self._readback(raw_settings(galvo_um=-0.01, stack_on="z-galvo")):
            result = confirmations.confirm_move_z(
                None, job_name="J", z_mode="galvo", target_um=50.0, poll_window=0.1
            )
        assert result["success"] is True
        assert result["confirmed"] is None

    def test_policy_none_is_accepted_not_verified_without_a_save(self, policy, monkeypatch):
        policy("none")
        monkeypatch.setattr(z_readback, "save_and_read_lrp", lambda c, **k: pytest.fail("no save"))
        with self._readback(raw_settings(galvo_um=-0.01, stack_on="z-galvo")):
            result = confirmations.confirm_move_z(
                None, job_name="J", z_mode="galvo", target_um=50.0, poll_window=0.1
            )
        assert result["success"] is True
        assert result["confirmed"] is None

    def test_the_free_drive_still_polls_the_settings(self):
        with self._readback(raw_settings(wide_um=100.0, stack_on="z-galvo")):
            result = confirmations.confirm_move_z(
                None, job_name="J", z_mode="zwide", target_um=100.0, poll_window=1.0
            )
        assert result == {"success": True, "logs": []}


class TestMoveZEndToEnd:
    """Through the command backbone, against the behavioural mock."""

    def _client(self, stack_on):
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "helpers"))
        from limits_fixtures import install_permissive_limits
        from mock_lasx_api import MockLasxClient

        client = MockLasxClient()
        # Only HiRes carries a stack in the mock's default jobs; put it on
        # the drive under test, as the operator would in LAS X.
        for job in client._jobs.values():
            if job.get("stack"):
                job["stack"]["mode"] = stack_on
        install_permissive_limits(client, wide_stage=True)
        return client

    def test_the_mock_freezes_the_stacked_drive_like_lasx(self):
        client = self._client("z-galvo")
        before = readers.get_job_settings(client, "HiRes", mode="api")["zPosition"]["z-galvo"][
            "position"
        ]
        commands.move_z(client, "HiRes", 12.0, z_mode="galvo", max_retries=0)
        after = readers.get_job_settings(client, "HiRes", mode="api")["zPosition"]["z-galvo"][
            "position"
        ]
        assert after == before

    def test_stack_drive_move_fires_once_and_is_accepted(self, monkeypatch):
        client = self._client("z-galvo")
        monkeypatch.setattr(
            z_readback, "save_and_read_lrp", lambda c, **k: lrp_with("HiRes", "z-galvo", 12.0)
        )
        t0 = time.perf_counter()
        result = commands.move_z(client, "HiRes", 12.0, z_mode="galvo")
        assert result["success"] is True
        assert result["confirmed"] is None
        assert result["timing"]["attempts"] == 1
        assert time.perf_counter() - t0 < 3.0

    def test_free_drive_move_is_confirmed_as_before(self):
        client = self._client("z-galvo")
        result = commands.move_z(client, "HiRes", 25.0, z_mode="zwide")
        assert result["success"] is True
        assert result["confirmed"] is True


class TestAdapterSnapshot:
    """The adapter's hardware snapshot takes both Z values from the one source."""

    def test_snapshot_reads_the_stack_drive_from_the_saved_experiment(self, monkeypatch):
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
            z_readback, "save_and_read_lrp", lambda c, **k: lrp_with("AF Job 01", "z-galvo", 15.0)
        )
        snap = adapter._hardware_snapshot(type("H", (), {"client": object()})())
        assert snap["z_galvo_um"] == pytest.approx(15.0)
        assert snap["z_wide_um"] == 4999.5
        assert snap["z_source"] == {"z-galvo": "lrp", "z-wide": "settings"}


class TestRealFixtureThroughTheSource:
    def test_saved_galvo_stack_through_z_reading(self, monkeypatch):
        monkeypatch.setattr(
            z_readback, "save_and_read_lrp", lambda c, **k: parse_lrp(SAVED_GALVO_STACK)
        )
        r = z_reading(None, "AF Job 01", "z-galvo", raw_settings(stack_on="z-galvo"))
        assert r.source == "lrp"
        assert r.z_um == pytest.approx(0.0)
