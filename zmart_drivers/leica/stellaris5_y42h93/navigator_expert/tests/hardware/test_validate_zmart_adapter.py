"""Pytest gate for the ZMART adapter validator's mock backend.

The canonical validation flow lives in ``validate_zmart_adapter.py`` so the
same checks run against the in-process mock, the LAS X simulator, or a real
scope. This file keeps the mock-backed path (driving the adapter through a real
``zmart_controller`` Session) in the regular offline suite without duplicating
the validator logic.
"""
# ruff: noqa: E402,I001

from __future__ import annotations

import json
import sys
from pathlib import Path

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
    output = tmp_path / "adapter_mock.jsonl"
    original_connect = adapter._session.connect_python_client
    try:
        exit_code = validate_zmart_adapter.main(["--mock", "--output", str(output), *extra])
    finally:
        adapter._session.connect_python_client = original_connect
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
    assert "get_xyz: frame z == z_wide + z_galvo" in names


def test_full_mock_run_move_and_acquire(tmp_path):
    """Read-only + move (both z drives) pass; acquire SKIPs under the mock."""
    exit_code, records = _run_mock(tmp_path, "--allow-move", "--allow-acquire")
    assert exit_code == 0

    summary = records[-1]
    assert summary["name"] == "__summary__"
    counts = summary["context"]["counts"]
    assert counts["FAIL"] == 0
    assert counts["WARN"] == 0
    assert counts["PASS"] >= 30

    by_name = {r["name"]: r for r in records}
    # The controller round-trip and the z-focus additive model are exercised.
    assert {
        "set_origin",
        "xy: frame x",
        "zgalvo: frame z",
        "zgalvo: drive moved by delta (sign check)",
        "zwide: frame z is additive (z-wide + z-galvo)",
    } <= set(by_name)
    assert by_name["zgalvo: frame z"]["status"] == "PASS"
    assert by_name["zwide: frame z is additive (z-wide + z-galvo)"]["status"] == "PASS"
    # Acquire needs real LAS X export files, so it is skipped under the mock.
    assert by_name["phase: acquire"]["status"] == "SKIP"
