"""Pytest gate for the randomized hardware stress runner's mock backend."""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

_HELPERS = _HERE.parent / "helpers"
if str(_HELPERS) not in sys.path:
    sys.path.insert(0, str(_HELPERS))

import stress_hardware


def test_readback_mismatch_is_warn_by_default_and_fail_when_strict():
    """Stress runs should expose reader lag without hiding command success."""
    rng = random.Random(1)

    def stale_readback():
        return 1

    def successful_write(_value):
        return {
            "success": True,
            "confirmed": True,
            "message": "sent",
            "timing": {"attempts": 1, "confirm_attempts": 1},
        }

    status, _message, _timing, _driver_message, context = (
        stress_hardware._setting_round_trip(
            None, None, "Job", rng,
            setting_name="example",
            read=stale_readback,
            write=successful_write,
            candidates=[2],
        )
    )
    assert status == "WARN"
    assert context["readback_status"] == "mismatch"

    strict_status, _message, _timing, _driver_message, strict_context = (
        stress_hardware._setting_round_trip(
            None, None, "Job", rng,
            setting_name="example",
            read=stale_readback,
            write=successful_write,
            candidates=[2],
            strict_readback=True,
        )
    )
    assert strict_status == "FAIL"
    assert strict_context["readback_status"] == "mismatch"


def _records(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _stress_steps(records: list[dict]) -> list[dict]:
    return [record for record in records if record["kind"] == "stress_step"]


def test_stress_hardware_mock_run_records_step_characteristics(tmp_path):
    """Run a seeded stress pass and verify the structured JSONL contract."""
    output = tmp_path / "stress_mock.jsonl"

    exit_code = stress_hardware.main([
        "--mock",
        "--rounds",
        "12",
        "--cycles",
        "2",
        "--seed",
        "123",
        "--output",
        str(output),
    ])

    assert exit_code == 0

    records = _records(output)
    steps = _stress_steps(records)
    summary = records[-1]

    assert len(steps) == 24
    assert summary["kind"] == "stress_summary"
    assert summary["context"]["counts"]["FAIL"] == 0
    assert summary["context"]["counts"]["WARN"] == 0
    assert summary["context"]["rounds"] == 12
    assert summary["context"]["cycles"] == 2
    assert "operation_stats" in summary["context"]
    assert "cycle_stats" in summary["context"]

    first_steps = [step for step in steps if step["round"] == 1]
    assert {step["operation"] for step in first_steps} == {"job_selection"}
    assert len(first_steps) == 2
    for step in first_steps:
        assert step["context"]["selected_jobs"] == ["HiRes", "Overview"]
        assert step["context"]["restore_to"] == "HiRes"

    for step in steps:
        assert step["seed"] == 123
        assert step["operation"]
        assert step["started_at"]
        assert "op_class" in step["context"]


def test_stress_hardware_seed_reproduces_operation_sequence(tmp_path):
    """Same seed and arguments should produce the same operation order."""
    outputs = [tmp_path / "stress_a.jsonl", tmp_path / "stress_b.jsonl"]
    for output in outputs:
        exit_code = stress_hardware.main([
            "--mock",
            "--rounds",
            "16",
            "--cycles",
            "2",
            "--seed",
            "456",
            "--output",
            str(output),
        ])
        assert exit_code == 0

    seq_a = [
        (step["cycle"], step["round"], step["operation"])
        for step in _stress_steps(_records(outputs[0]))
    ]
    seq_b = [
        (step["cycle"], step["round"], step["operation"])
        for step in _stress_steps(_records(outputs[1]))
    ]

    assert seq_a == seq_b
