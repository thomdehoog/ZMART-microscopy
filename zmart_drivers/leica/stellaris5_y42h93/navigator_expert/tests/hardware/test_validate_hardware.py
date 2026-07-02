"""Pytest gate for the hardware validator's mock backend.

The canonical validation flow lives in ``validate_hardware.py`` so the
same checks can run against the in-process mock, LAS X simulator, or
real hardware. This pytest file keeps the mock-backed path in the
regular test suite without duplicating the validator logic.
"""
# ruff: noqa: E402,I001

from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

_HELPERS = _HERE.parent / "helpers"
if str(_HELPERS) not in sys.path:
    sys.path.insert(0, str(_HELPERS))
_LEICA_ROOT = _HERE.parents[2]
if str(_LEICA_ROOT) not in sys.path:
    sys.path.insert(0, str(_LEICA_ROOT))

import validate_hardware
from mock_lasx_api import MockLasxClient, _SET_DISPATCH
from navigator_expert.config import profiles


def test_classify_result_statuses():
    """Driver result envelopes map to PASS / WARN / FAIL consistently."""
    assert validate_hardware._classify_result({"success": True, "confirmed": True}) == "PASS"
    assert validate_hardware._classify_result({"success": True}) == "PASS"
    assert validate_hardware._classify_result({"success": True, "confirmed": False}) == "WARN"
    assert validate_hardware._classify_result({"success": False, "confirmed": True}) == "FAIL"


def test_compact_status_includes_driver_timing():
    """Human status strings should include message and useful timing fields."""
    status = validate_hardware._compact_status(
        {
            "message": "Zoom -> 5.0",
            "timing": {
                "total_s": 1.23456,
                "attempts": 2,
                "confirm_attempts": 3,
                "method": "async",
            },
        }
    )

    assert status == "Zoom -> 5.0; [total=1.235s, att=2, conf=3, m=async]"


def test_stage_limit_helpers_report_out_of_bounds_points():
    """Movement phases should explain why a point is outside hard limits."""
    limits = {
        "x_min": 1000.0,
        "x_max": 130000.0,
        "y_min": 1000.0,
        "y_max": 100000.0,
        "z_galvo_min": -50.0,
        "z_galvo_max": 50.0,
        "z_wide_min": -200.0,
        "z_wide_max": 200.0,
    }

    assert validate_hardware._xy_limit_error(50000.0, 30000.0, limits) is None
    assert validate_hardware._z_limit_error(0.0, "galvo", limits) is None
    assert "X=0.0 outside calibrated limits" in (
        validate_hardware._xy_limit_error(0.0, 30000.0, limits) or ""
    )
    assert "Z galvo=60.0 outside calibrated limits" in (
        validate_hardware._z_limit_error(60.0, "galvo", limits) or ""
    )


def test_mock_starts_inside_typical_calibrated_envelope():
    """The Python mock should model a sane stage start, not LAS X's 0,0 quirk."""
    mock = MockLasxClient(latency=0.0)

    assert mock._stage_x >= 0.001
    assert mock._stage_y >= 0.001


def test_mock_scan_window_survives_delayed_first_poll():
    """A starved status poller must still observe the scan.

    Regression for the suite-load acquire flake, which needs two guarantees:

    - The mock's scanning window was purely wall-clock (0.1 s) while the
      driver polls at 0.1 s, so under CPU load the whole window could pass
      between the acquire command and the first status poll.
    - confirm_acquire's fail-closed freshness gate discards a reading
      stamped in the same wall-clock tick as the command start -- and that
      discarded first poll still consumes an observation.

    So the mock guarantees TWO observed scanning reads per command-initiated
    scan: even with the first eaten by the tick gate, the next poll (a
    strictly later tick) still sees the scan.
    """
    import time
    from types import SimpleNamespace

    mock = MockLasxClient(latency=0.0)
    mock._handle_acquire_job(SimpleNamespace(JobName="HiRes"))
    time.sleep(0.25)  # well past the 0.1 s wall-clock window
    assert mock.PyApiStatus.Model.ScanStatus == "eScanStarted"  # may be tick-rejected
    assert mock.PyApiStatus.Model.ScanStatus == "eScanStarted"  # the poll that counts
    assert mock.PyApiStatus.Model.ScanStatus == "eScanIdle"  # then idle

    # StartScan gets the same guarantee.
    mock._handle_start_scan(SimpleNamespace(JobName="HiRes"))
    time.sleep(0.25)
    assert mock.PyApiStatus.Model.ScanStatus == "eScanStarted"
    assert mock.PyApiStatus.Model.ScanStatus == "eScanStarted"
    assert mock.PyApiStatus.Model.ScanStatus == "eScanIdle"


def test_validate_hardware_full_mock_run(tmp_path):
    """Run the full reversible validation flow against the Python mock."""
    output = tmp_path / "hardware_mock.jsonl"

    exit_code = validate_hardware.main(
        [
            "--mock",
            "--allow-xy",
            "--allow-z",
            "--allow-objective",
            "--allow-acquire",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0

    records = [
        json.loads(line) for line in output.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    assert records
    assert records[-1]["name"] == "__summary__"
    assert records[-1]["context"]["counts"]["FAIL"] == 0
    assert records[-1]["context"]["counts"]["WARN"] == 0
    assert records[-1]["context"]["counts"]["PASS"] >= 30

    names = {record["name"] for record in records}
    assert {
        "stage config: load",
        "stage limits: apply",
        "job selection: select job",
        "settings: read",
        "zoom: write alternate",
        "scan_resonant: write alternate",
        "scan_mode: is xyz",
        "sequential_mode: write alternate",
        "scan_field_rotation: write alternate",
        "frame_accumulation: write alternate",
        "frame_average: write alternate",
        "line_accumulation: write alternate",
        "line_average: write alternate",
        "pinhole_airy: write alternate",
        "xy: move 01",
        "z: move alternate",
        "objective: switch alternate",
        "acquire: job",
    } <= names
    xy_moves = [record for record in records if record["name"].startswith("xy: move ")]
    assert len(xy_moves) == 10
    assert {record["context"]["index"] for record in xy_moves} == set(range(1, 11))

    select_job_records = [
        record for record in records if record["name"] == "job selection: select job"
    ]
    selected_job_records = [
        record for record in records if record["name"].startswith("job selection: confirmed ")
    ]
    assert {record["context"]["job"] for record in select_job_records} == {
        "HiRes",
        "Overview",
    }
    assert {
        record["name"].removeprefix("job selection: confirmed ") for record in selected_job_records
    } == {"HiRes", "Overview"}


def test_state_reader_mode_argument_overrides_profile(tmp_path):
    output = tmp_path / "reader_mode.jsonl"
    prior = profiles.STATE_READERS
    try:
        exit_code = validate_hardware.main(
            [
                "--mock",
                "--read-only",
                "--state-reader-mode",
                "api",
                "--output",
                str(output),
            ]
        )
        assert exit_code == 0
        assert profiles.STATE_READERS.xy_mode == "api"
        assert profiles.STATE_READERS.job_settings_mode == "api"
        assert profiles.STATE_READERS.selected_job_mode == "api"
    finally:
        profiles.STATE_READERS = prior


def test_explicit_log_mode_fails_when_no_jobs():
    class DummyDrv:
        @staticmethod
        def ping(_client):
            return True

        @staticmethod
        def get_scan_status(_client):
            return "eScanIdle"

        @staticmethod
        def get_jobs(_client, **_kwargs):
            return None

        @staticmethod
        def get_hardware_info(_client):
            return {"ok": True}

        @staticmethod
        def get_xy(_client):
            return {"x_um": 1.0, "y_um": 1.0}

    records = []
    validator = validate_hardware.Validator(
        sink=records.append,
        log=validate_hardware._configure_logging("ERROR", jsonl_to_stdout=False),
    )
    args = validate_hardware.parse_args(["--state-reader-mode", "log"])

    job = validate_hardware.phase_readonly(DummyDrv, validator, object(), args)

    assert job is None
    assert validator.exit_code() == 1
    resolve = next(r for r in records if r.name == "job: resolve")
    assert resolve.status == "FAIL"


def test_selected_job_api_lag_after_log_confirm_is_warn():
    records = []
    validator = validate_hardware.Validator(
        sink=records.append,
        log=validate_hardware._configure_logging("ERROR", jsonl_to_stdout=False),
    )
    command_result = {
        "success": True,
        "confirmed": True,
        "logs": [
            {
                "level": "info",
                "msg": "SelectJob 'HiRes' | confirmed by log leg (0.578s)",
            },
        ],
    }

    validate_hardware._record_selected_job_postcheck(
        validator,
        command_result,
        {"job": "HiRes"},
        "HiRes",
        "AF Job",
    )

    assert validator.exit_code() == 0
    assert len(records) == 1
    record = records[0]
    assert record.status == "WARN"
    assert record.name == "job selection: API lag after log-confirmed HiRes"
    assert record.context["expected"] == "HiRes"
    assert record.context["api_selected"] == "AF Job"
    assert record.context["confirmation_evidence"] == "log"


def test_selected_job_api_mismatch_without_log_confirm_stays_fail():
    records = []
    validator = validate_hardware.Validator(
        sink=records.append,
        log=validate_hardware._configure_logging("ERROR", jsonl_to_stdout=False),
    )
    command_result = {
        "success": True,
        "confirmed": True,
        "logs": [
            {
                "level": "info",
                "msg": "SelectJob 'HiRes' | confirmed by api leg (0.100s)",
            },
        ],
    }

    validate_hardware._record_selected_job_postcheck(
        validator,
        command_result,
        {"job": "HiRes"},
        "HiRes",
        "AF Job",
    )

    assert validator.exit_code() == 1
    assert len(records) == 1
    record = records[0]
    assert record.status == "FAIL"
    assert record.name == "job selection: confirmed HiRes"
    assert record.message == "expected='HiRes' actual='AF Job'"


def test_job_restore_is_skipped_only_after_confirmed_original():
    """The validator should not force a no-op restore after a proved restore."""
    assert not validate_hardware._needs_select_job_restore(
        "Overview",
        "Overview",
        {"success": True, "confirmed": True},
    )
    assert validate_hardware._needs_select_job_restore(
        "Overview",
        "Overview",
        {"success": True, "confirmed": False},
    )
    assert validate_hardware._needs_select_job_restore(
        "Overview",
        "Overview",
        {"success": False, "confirmed": True},
    )
    assert validate_hardware._needs_select_job_restore(
        "Overview",
        "HiRes",
        {"success": True, "confirmed": True},
    )


def test_job_selection_candidate_enumeration_uses_api_when_log_participates():
    """Candidate discovery must not depend on an incomplete log job catalog."""
    assert validate_hardware._job_selection_read_mode("api") is None
    assert validate_hardware._job_selection_read_mode("log") == "api"
    assert validate_hardware._job_selection_read_mode("hybrid") == "api"


def test_mock_set_dispatch_table_matches_surface():
    """The mock's explicit PyApi command table must stay wired."""
    mock = MockLasxClient(latency=0.0)

    for command_name, handler_name in sorted(_SET_DISPATCH.items()):
        assert hasattr(mock, command_name), command_name
        assert callable(getattr(mock, handler_name)), handler_name
