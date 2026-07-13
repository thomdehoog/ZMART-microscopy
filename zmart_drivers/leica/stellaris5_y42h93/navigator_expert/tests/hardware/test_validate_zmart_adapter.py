"""Pytest gate for the ZMART adapter validator's mock backend.

The canonical validation flow lives in ``validate_zmart_adapter.py`` so the
same checks run against the in-process mock, the LAS X simulator, or a real
scope. This file keeps the mock-backed path (driving the adapter through a real
``zmart_controller`` Session) in the regular offline suite without duplicating
the validator logic.
"""
# ruff: noqa: E402,I001

from __future__ import annotations

import argparse
import json
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

_HERE = Path(__file__).resolve().parent
_HELPERS = _HERE.parent / "helpers"
_LEICA_ROOT = _HERE.parents[2]
_REPO_ROOT = _HERE.parents[6]
for _p in (_HERE, _HELPERS, _LEICA_ROOT, _REPO_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import zmart_controller
import validate_zmart_adapter
from navigator_expert.zmart_adapter import zmart_adapter as adapter


def _run_mock(tmp_path, *extra):
    """Run the validator against the mock, restoring global state afterwards."""
    from navigator_expert.config import profiles

    output = tmp_path / "adapter_mock.jsonl"
    original_connect = adapter._session.connect_python_client
    original_profile = profiles.STATE_READERS
    try:
        exit_code = validate_zmart_adapter.main(
            ["--mock", "--output", str(output), "--report-dir", str(tmp_path), *extra]
        )
    finally:
        adapter._session.connect_python_client = original_connect
        profiles.STATE_READERS = original_profile
        zmart_controller.disconnect()  # clear the module-level active session
    records = [
        json.loads(line) for line in output.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    return exit_code, records


def test_within_envelope_helper():
    assert validate_zmart_adapter._within(5.0, 0.0, 10.0)
    assert validate_zmart_adapter._within(0.0, 0.0, 10.0)
    assert validate_zmart_adapter._within(10.0, 0.0, 10.0)
    assert not validate_zmart_adapter._within(-0.1, 0.0, 10.0)
    assert not validate_zmart_adapter._within(10.1, 0.0, 10.0)


def test_readonly_mock_run(tmp_path):
    exit_code, records = _run_mock(tmp_path, "--read-only")
    assert exit_code == 0
    assert records[-1]["name"] == "__summary__"
    counts = records[-1]["context"]["counts"]
    assert counts["FAIL"] == 0
    assert counts["WARN"] == 0
    names = {r["name"] for r in records}
    assert "registry: leica adapter registered" in names
    assert "get_xyz: hardware block complete" in names


def test_full_mock_run_move_and_acquire(tmp_path):
    """Read-only + move (both z drives) + state pass; acquire SKIPs under the mock."""
    exit_code, records = _run_mock(tmp_path, "--allow-move", "--allow-state", "--allow-acquire")
    assert exit_code == 0

    summary = records[-1]
    assert summary["name"] == "__summary__"
    counts = summary["context"]["counts"]
    assert counts["FAIL"] == 0
    assert counts["WARN"] == 0
    assert counts["PASS"] >= 30

    by_name = {r["name"]: r for r in records}
    # The controller round-trip, z-focus model, and state round-trip are exercised.
    assert {
        "get_info: output_root returned",
        "set_origin",
        "xy: frame x",
        "zgalvo: frame z",
        "zgalvo: drive moved by delta (sign check)",
        "zwide: frame z is additive (z-wide + z-galvo)",
        "state: switched",
        "state: restored",
    } <= set(by_name)
    assert by_name["state: restored"]["status"] == "PASS"
    assert by_name["zgalvo: frame z"]["status"] == "PASS"
    assert by_name["zwide: frame z is additive (z-wide + z-galvo)"]["status"] == "PASS"
    assert by_name["get_info: tile positions available"]["status"] == "SKIP"
    assert by_name["get_info: focus positions available"]["status"] == "SKIP"
    # Acquire needs real LAS X export files, so it is skipped under the mock.
    assert by_name["phase: acquire"]["status"] == "SKIP"

    # The Markdown run report is produced with the summary table and lists the
    # controller-driven moves (incl. restores) as instrument changes.
    reports = sorted(tmp_path.glob("hardware_run_report_*.md"))
    assert len(reports) == 1
    text = reports[0].read_text(encoding="utf-8")
    assert "| Phase | Actions attempted | Passed | Warned | Failed | Skipped " in text
    assert "## Chronological detail (every attempted action)" in text
    assert "set_xyz: XY move" in text
    assert "move: restore XY + focus (frame 0,0,0)" in text
    assert "set_state: restore" in text


def test_state_phase_does_not_switch_away_from_autofocus_job():
    captured = {
        "changeable": {"job": "AF Job"},
        "observed": {"autofocus_jobs": [{"Name": "AF Job"}]},
    }
    session = SimpleNamespace(
        get_state=Mock(return_value=captured),
        get_acquisition_options=Mock(return_value={"job": {"options": ["Overview", "HiRes"]}}),
        set_state=Mock(side_effect=AssertionError("must not switch an autofocus job")),
    )
    validator = SimpleNamespace(
        phase=Mock(return_value=nullcontext()),
        callable=Mock(side_effect=lambda _name, run, **_kwargs: run()),
        compare=Mock(),
        skip=Mock(),
    )

    validate_zmart_adapter.phase_state(validator, session)

    session.set_state.assert_not_called()
    validator.compare.assert_not_called()
    validator.skip.assert_called_once_with(
        "state: switch",
        "current job 'AF Job' is autofocus-only and cannot be restored via set_state",
    )


def test_connect_session_leaves_output_root_for_driver_discovery():
    from navigator_expert.config import profiles

    original_connect = adapter._session.connect_python_client
    original_profile = profiles.STATE_READERS
    args = argparse.Namespace(
        mock=True, mock_latency=0.0, client_name="PythonClient", api_delay_ms=None
    )
    try:
        session = validate_zmart_adapter._connect_session(args, adapter, None)
        assert session._handle.connection.get("output_root") is None
    finally:
        adapter._session.connect_python_client = original_connect
        profiles.STATE_READERS = original_profile
        zmart_controller.disconnect()


def test_acquire_backlash_correction_through_the_controller_seam(tmp_path):
    """acquire(options={"backlash_correction": True}) through the real Session.

    Unlike the adapter-direct unit tests (which patch driver internals and pass
    ``object()`` as the client), this opens a real ``zmart_controller.Session``
    against the in-process mock CAM (same connect path ``phase_acquire`` would
    use live) and only patches the I/O boundary (``_capture``/``_save``) that a
    mock CAM cannot satisfy -- so the seam decision #3 cares about (Session ->
    ops table -> adapter) is what is actually exercised for the
    ``backlash_correction`` acquisition option. ``strip_scan_fields`` is passed
    as ``False`` for the same reason: stripping needs ``PyApiSaveExperiment``,
    which ``MockLasxClient`` does not implement, and scan-field handling is
    unrelated to what this test verifies.
    """
    from navigator_expert.config import profiles

    original_connect = adapter._session.connect_python_client
    original_profile = profiles.STATE_READERS
    args = argparse.Namespace(
        mock=True, mock_latency=0.0, client_name="PythonClient", api_delay_ms=None
    )
    order = []
    try:
        session = validate_zmart_adapter._connect_session(args, adapter, str(tmp_path))
        active_job = session.get_state()["changeable"]["job"]

        def fake_correct_backlash(client, **kwargs):
            order.append(("backlash", client))

        def fake_capture(client, job, **kwargs):
            order.append(("capture", job))
            return SimpleNamespace(job=job)

        def fake_save(client, acq, output_root, naming, **kwargs):
            return SimpleNamespace(image_paths={}, xml_paths={}, naming=naming)

        with (
            patch.object(adapter._motion, "correct_backlash", fake_correct_backlash),
            patch.object(adapter._capture, "acquire", fake_capture),
            patch.object(adapter._save, "save", fake_save),
        ):
            record = session.acquire(
                acquisition_type="prescan",
                position_label="1",
                options={"backlash_correction": True, "strip_scan_fields": False},
            )
    finally:
        adapter._session.connect_python_client = original_connect
        profiles.STATE_READERS = original_profile
        zmart_controller.disconnect()

    # backlash takeup fires before capture, through the real Session -> ops
    # table -> adapter seam (not the adapter called in isolation).
    assert order == [("backlash", order[0][1]), ("capture", active_job)]
    assert record["settle"] == "backlash-corrected"
