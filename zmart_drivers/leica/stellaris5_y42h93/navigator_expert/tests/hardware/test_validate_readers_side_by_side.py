"""Pytest gate for the side-by-side reader validator's mock backend.

The canonical parity/reader-mode validation lives in
``validate_readers_side_by_side.py`` so the same script runs against the LAS X
simulator or a real scope. This file keeps its execution path (including the
FD-12 profile-field fix and the routed api/log/hybrid reader-mode phase) in
the regular offline suite by driving it against ``MockLasxClient``.
"""
# ruff: noqa: E402,I001

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_HELPERS = _HERE.parent / "helpers"
_LEICA_ROOT = _HERE.parents[2]
for _p in (_HERE, _HELPERS, _LEICA_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import validate_readers_side_by_side as sxs
from navigator_expert.config import profiles


def _run_mock(tmp_path, *extra):
    """Run the validator against the mock, restoring global profile state."""
    original_profile = profiles.STATE_READERS
    try:
        return sxs.main(["--mock", "--report-dir", str(tmp_path), *extra])
    finally:
        profiles.STATE_READERS = original_profile


def test_poll_params_come_from_real_profile_fields():
    """FD-12 regression: the poll knobs must exist on StateReaderProfile.

    The script once read ``profiles.LOG_READER.poll_timeout`` /
    ``.poll_interval``, which never existed on LogReaderProfile, so the
    live-changes phase crashed with AttributeError before touching the scope.
    """
    assert not hasattr(profiles.LOG_READER, "poll_timeout")
    assert not hasattr(profiles.LOG_READER, "poll_interval")

    window, interval = sxs._change_poll_params()
    assert window == max(
        profiles.STATE_READERS.job_settings_timeout_s,
        profiles.STATE_READERS.selected_job_log_poll_timeout_s,
    )
    assert interval == profiles.STATE_READERS.selected_job_log_poll_interval_s

    window, interval = sxs._select_poll_params()
    assert window == profiles.STATE_READERS.selected_job_log_poll_timeout_s
    assert interval == profiles.STATE_READERS.selected_job_log_poll_interval_s


def test_full_mock_run_all_phases(tmp_path, capsys):
    """Parity + routed reader modes + live changes + select run end-to-end."""
    exit_code = _run_mock(tmp_path, "--yes", "--allow-job-switch")
    out = capsys.readouterr().out

    assert exit_code == 0

    # The three reader modes are exercised explicitly for every routed datum.
    for datum in sxs.ROUTED_DATUMS:
        for mode in sxs.READER_MODES:
            assert f"read[{datum}] mode={mode}" in out
    # Hybrid reads work through the router (they degrade to the api leg when
    # the log has no fresh value) and agree with api.
    assert "agree[xy] api vs hybrid" in out
    # The FD-12-fixed live-changes phase ran and restored every change.
    assert "change[zoom]" in out
    assert "restore[zoom]" in out
    assert "select: restore[" in out

    # The Markdown run report is produced with summary + every change.
    reports = sorted(tmp_path.glob("hardware_run_report_*.md"))
    assert len(reports) == 1
    text = reports[0].read_text(encoding="utf-8")
    assert "| Phase | Actions attempted | Passed | Warned | Failed | Skipped " in text
    assert "### Per reader mode (routed read latency)" in text
    assert "## Chronological detail (every attempted action)" in text
    assert "change[zoom]" in text
    assert "restore[zoom]" in text
    assert "success+CONFIRMED" in text


def test_read_only_mock_run(tmp_path, capsys):
    """--read-only stays click-free: no change/select rows, still exit 0."""
    exit_code = _run_mock(tmp_path, "--read-only")
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "read[selected_job] mode=hybrid" in out
    assert "change[" not in out
    assert "select[" not in out
    assert sorted(tmp_path.glob("hardware_run_report_*.md"))
