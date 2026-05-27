"""Pytest gate for the hardware validator's mock backend.

The canonical validation flow lives in ``validate_hardware.py`` so the
same checks can run against the in-process mock, LAS X simulator, or
real hardware. This pytest file keeps the mock-backed path in the
regular test suite without duplicating the validator logic.
"""

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

import validate_hardware
from mock_lasx_api import MockLasxClient, _SET_DISPATCH


def test_classify_result_statuses():
    """Driver result envelopes map to PASS / WARN / FAIL consistently."""
    assert validate_hardware._classify_result(
        {"success": True, "confirmed": True}) == "PASS"
    assert validate_hardware._classify_result(
        {"success": True}) == "PASS"
    assert validate_hardware._classify_result(
        {"success": True, "confirmed": False}) == "WARN"
    assert validate_hardware._classify_result(
        {"success": False, "confirmed": True}) == "FAIL"


def test_compact_status_includes_driver_timing():
    """Human status strings should include message and useful timing fields."""
    status = validate_hardware._compact_status({
        "message": "Zoom -> 5.0",
        "timing": {
            "total_s": 1.23456,
            "attempts": 2,
            "confirm_attempts": 3,
            "method": "async",
        },
    })

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
        validate_hardware._xy_limit_error(0.0, 30000.0, limits) or "")
    assert "Z galvo=60.0 outside calibrated limits" in (
        validate_hardware._z_limit_error(60.0, "galvo", limits) or "")


def test_mock_starts_inside_typical_calibrated_envelope():
    """The Python mock should model a sane stage start, not LAS X's 0,0 quirk."""
    mock = MockLasxClient(latency=0.0)

    assert mock._stage_x >= 0.001
    assert mock._stage_y >= 0.001


def test_validate_hardware_full_mock_run(tmp_path):
    """Run the full reversible validation flow against the Python mock."""
    output = tmp_path / "hardware_mock.jsonl"

    exit_code = validate_hardware.main([
        "--mock",
        "--allow-xy",
        "--allow-z",
        "--allow-objective",
        "--allow-acquire",
        "--output",
        str(output),
    ])

    assert exit_code == 0

    records = [
        json.loads(line)
        for line in output.read_text(encoding="utf-8").splitlines()
        if line.strip()
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
        "job selection: select alternate",
        "job selection: selected alternate",
        "settings: read",
        "zoom: write alternate",
        "frame_accumulation: write alternate",
        "xy: move alternate",
        "z: move alternate",
        "objective: switch alternate",
        "acquire: single",
    } <= names


def test_mock_set_dispatch_table_matches_surface():
    """The mock's explicit PyApi command table must stay wired."""
    mock = MockLasxClient(latency=0.0)

    for command_name, handler_name in sorted(_SET_DISPATCH.items()):
        assert hasattr(mock, command_name), command_name
        assert callable(getattr(mock, handler_name)), handler_name
