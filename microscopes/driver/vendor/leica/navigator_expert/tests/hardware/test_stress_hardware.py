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
        "--allow-template-roundtrip",
        "--allow-acquire",
        "--output",
        str(output),
    ])

    assert exit_code == 0

    records = _records(output)
    steps = _stress_steps(records)
    summary = records[-1]

    expected_steps = 1 + (summary["context"]["cycles"]
                          * summary["context"]["rounds"]) + 2
    assert len(steps) == expected_steps
    assert summary["kind"] == "stress_summary"
    assert summary["context"]["counts"]["FAIL"] == 0
    assert summary["context"]["counts"]["WARN"] == 0
    assert summary["context"]["rounds"] == 12
    assert summary["context"]["cycles"] == 2
    assert summary["context"]["allow_template_roundtrip"] is True
    assert summary["context"]["allow_acquire"] is True
    assert "operation_stats" in summary["context"]
    assert "cycle_stats" in summary["context"]
    assert "template_roundtrip" in summary["context"]["operation_stats"]
    assert "acquire_once" in summary["context"]["operation_stats"]

    setup_step = steps[0]
    assert setup_step["operation"] == "general_workflow_load"
    assert setup_step["status"] == "PASS"
    assert setup_step["context"]["backend"] == "mock_data"

    first_steps = [step for step in steps if step["round"] == 1]
    assert {step["operation"] for step in first_steps} == {"job_selection"}
    assert len(first_steps) == 2
    for step in first_steps:
        assert step["context"]["selected_jobs"] == ["HiRes", "Overview"]
        assert step["context"]["restore_to"] == "HiRes"

    terminal_ops = {
        step["operation"] for step in steps
        if step["cycle"] is None and step["operation"] != "general_workflow_load"
    }
    assert terminal_ops == {"template_roundtrip", "acquire_once"}
    template_step = next(
        step for step in steps if step["operation"] == "template_roundtrip"
    )
    assert template_step["status"] == "PASS"
    assert template_step["context"]["templates_dir"] == setup_step["context"]["templates_dir"]
    assert template_step["context"]["restore_attempted"] is True
    assert template_step["context"]["restore_result"]["success"] is True
    acquire_step = next(step for step in steps if step["operation"] == "acquire_once")
    assert acquire_step["status"] == "PASS"

    for step in steps:
        assert step["seed"] == 123
        assert step["operation"]
        assert step["started_at"]
        assert "op_class" in step["context"]


def test_template_roundtrip_restores_after_strip_failure():
    """A failed strip still triggers restore so the active template is not left stripped."""
    class FakeDriver:
        def __init__(self):
            self.restore_calls = 0

        def strip_template(self, _client, *, save_timeout):
            assert save_timeout == 120
            return {"success": False, "total_s": 0.1}

        def restore_template(self, _client):
            self.restore_calls += 1
            return {"success": True, "total_s": 0.2}

    args = type("Args", (), {"mock": False})()
    driver = FakeDriver()

    workflow = stress_hardware.WorkflowBundle(
        source_dir=Path("unused"),
        backend="lasx_scanning_templates",
        templates_dir=Path("unused"),
    )

    status, message, timing, _driver_message, context = (
        stress_hardware.op_template_roundtrip(
            driver, object(), "HiRes", random.Random(1), args, workflow)
    )

    assert status == "FAIL"
    assert "strip_template failed" in message
    assert "restore_template succeeded" in message
    assert timing == {"restore_s": 0.2}
    assert driver.restore_calls == 1
    assert context["restore_attempted"] is True
    assert context["restore_result"]["success"] is True


def test_general_workflow_load_live_path_copies_loads_and_confirms(monkeypatch, tmp_path):
    """Live setup copies repo data, loads it, then confirm-saves the canonical name."""
    from navigator_expert.templates import files as template_files

    source = tmp_path / "source"
    templates = tmp_path / "ScanningTemplates"
    source.mkdir()
    templates.mkdir()
    base = "repo_general_workflow"
    (source / f"{base}.xml").write_text("<Configuration><ScanFields /></Configuration>", encoding="utf-8")
    (source / f"{base}.rgn").write_text(
        "<StageOverviewRegions><Regions><ShapeList><Items /></ShapeList></Regions></StageOverviewRegions>",
        encoding="utf-8",
    )
    (source / f"{base}.lrp").write_text("<Configuration />", encoding="utf-8")

    calls = []
    monkeypatch.setattr(template_files, "find_scanning_templates_dir", lambda: templates)

    def fake_load(_client, name):
        calls.append(("load", name))
        return {"success": True, "message": f"LoadExperiment '{name}'"}

    def fake_save(_client, name, out_dir, **kwargs):
        calls.append(("save", name, Path(out_dir), kwargs.get("confirm_path")))
        return {"success": True, "confirmed": True}

    monkeypatch.setattr(template_files, "load_experiment", fake_load)
    monkeypatch.setattr(template_files, "save_experiment", fake_save)

    workflow = stress_hardware.WorkflowBundle(
        source_dir=source,
        backend="lasx_scanning_templates",
    )
    args = type("Args", (), {"mock": False})()

    status, message, timing, driver_message, context = (
        stress_hardware.op_load_general_workflow(object(), object(), workflow, args)
    )

    assert status == "PASS"
    assert "loaded general_workflow" in message
    assert driver_message == f"LoadExperiment '{template_files.TEMPLATE_XML}'"
    assert timing["copy_s"] >= 0
    assert workflow.templates_dir == templates
    assert (templates / template_files.TEMPLATE_XML).is_file()
    assert (templates / template_files.TEMPLATE_RGN).is_file()
    assert (templates / template_files.TEMPLATE_LRP).is_file()
    assert calls == [
        ("load", template_files.TEMPLATE_XML),
        (
            "save",
            template_files.TEMPLATE_XML,
            templates,
            templates / template_files.TEMPLATE_RGN,
        ),
    ]
    assert context["templates_dir"] == str(templates)


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
