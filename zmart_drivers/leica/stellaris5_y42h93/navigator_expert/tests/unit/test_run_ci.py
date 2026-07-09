import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def _load_run_ci():
    path = Path(__file__).resolve().parents[2] / "run_ci.py"
    spec = importlib.util.spec_from_file_location("run_ci_under_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_run_ci_exposes_only_mock_and_hardware_modes():
    run_ci = _load_run_ci()

    assert run_ci.parse_args([]).hardware is False
    assert run_ci.parse_args(["--mock"]).mock is True
    assert run_ci.parse_args(["--hardware"]).hardware is True

    with pytest.raises(SystemExit):
        run_ci.parse_args(["--mock", "--hardware"])
    with pytest.raises(SystemExit):
        run_ci.parse_args(["--no-cov"])


def test_hardware_mode_requires_lasx_and_runs_acquire_smoke(monkeypatch, tmp_path):
    run_ci = _load_run_ci()
    captured: list[tuple[str, list[str]]] = []

    monkeypatch.setattr(run_ci, "REPORT_DIR", tmp_path)
    monkeypatch.setattr(run_ci, "build_env", lambda: {})
    monkeypatch.setattr(
        run_ci.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=""),
    )

    def fake_run_step(name, cmd, env, *, fatal):
        captured.append((name, cmd))
        return {
            "name": name,
            "ok": True,
            "fatal": fatal,
            "returncode": 0,
            "seconds": 0.0,
            "error": None,
            "command": cmd,
        }

    monkeypatch.setattr(run_ci, "run_step", fake_run_step)

    assert run_ci.main(["--hardware"]) == 0

    commands = {name: cmd for name, cmd in captured}
    assert "limits: mock self-check (fail-closed gate proven before any hardware)" in commands

    adapter_cmd = _command_for(captured, "validate_zmart_adapter.py")
    assert "--allow-acquire" in adapter_cmd
    assert "--allow-missing-lasx" not in adapter_cmd
    assert "--mock" not in adapter_cmd

    hardware_cmds = _commands_for(captured, "validate_hardware.py")
    assert len(hardware_cmds) == 3
    for cmd in hardware_cmds:
        assert "--allow-acquire" in cmd
        assert "--allow-missing-lasx" not in cmd
        assert "--mock" not in cmd

    assert "--mock" not in _command_for(captured, "validate_readers_side_by_side.py")


def _commands_for(captured: list[tuple[str, list[str]]], script_name: str) -> list[list[str]]:
    return [cmd for _name, cmd in captured if any(part.endswith(script_name) for part in cmd)]


def _command_for(captured: list[tuple[str, list[str]]], script_name: str) -> list[str]:
    matches = _commands_for(captured, script_name)
    assert len(matches) == 1
    return matches[0]
