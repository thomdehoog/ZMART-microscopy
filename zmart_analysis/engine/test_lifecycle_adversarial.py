"""Adversarial lifecycle tests for concurrent registration and shutdown."""

from __future__ import annotations

import threading
import time
from unittest.mock import patch

import pytest

from engine import Engine
import engine._pipeline as pipeline_module


pytestmark = pytest.mark.adversarial


def _workflow_files(tmp_path):
    step_path = tmp_path / "noop.py"
    step_path.write_text(
        "METADATA = {'environment': None, 'max_workers': 1}\n"
        "def run(pipeline_data, state, **params): return pipeline_data\n",
        encoding="utf-8",
    )
    yaml_path = tmp_path / "workflow.yaml"
    yaml_path.write_text(
        "metadata:\n"
        f"  functions_dir: {tmp_path.as_posix()}\n"
        "workflow:\n"
        "  - noop:\n",
        encoding="utf-8",
    )
    return yaml_path


def test_many_concurrent_duplicate_registrations_have_one_winner(tmp_path):
    yaml_path = _workflow_files(tmp_path)
    parse_started = threading.Event()
    release_parse = threading.Event()
    real_parse_yaml = pipeline_module.parse_yaml
    barrier = threading.Barrier(33)
    outcomes = []
    outcomes_lock = threading.Lock()

    def blocked_parse_yaml(path):
        parse_started.set()
        assert release_parse.wait(timeout=10)
        return real_parse_yaml(path)

    def register():
        barrier.wait(timeout=10)
        try:
            engine.register("shared", yaml_path)
        except BaseException as exc:
            outcome = exc
        else:
            outcome = "registered"
        with outcomes_lock:
            outcomes.append(outcome)

    engine = Engine(max_concurrent=1)
    with patch("engine._pipeline.parse_yaml", blocked_parse_yaml):
        threads = [threading.Thread(target=register) for _ in range(32)]
        for thread in threads:
            thread.start()
        barrier.wait(timeout=10)
        assert parse_started.wait(timeout=10)
        deadline = time.monotonic() + 10
        while len(outcomes) < 31 and time.monotonic() < deadline:
            time.sleep(0.005)
        assert len(outcomes) == 31
        release_parse.set()
        for thread in threads:
            thread.join(timeout=10)

    assert all(not thread.is_alive() for thread in threads)
    assert outcomes.count("registered") == 1
    duplicate_errors = [item for item in outcomes if isinstance(item, ValueError)]
    assert len(duplicate_errors) == 31
    assert list(engine.status()) == ["shared"]
    engine.shutdown()


def test_shutdown_rejects_many_inflight_distinct_registrations(tmp_path):
    yaml_path = _workflow_files(tmp_path)
    release_parse = threading.Event()
    all_parsers_started = threading.Event()
    real_parse_yaml = pipeline_module.parse_yaml
    entered = 0
    entered_lock = threading.Lock()
    errors = []
    errors_lock = threading.Lock()
    registration_count = 24

    def blocked_parse_yaml(path):
        nonlocal entered
        with entered_lock:
            entered += 1
            if entered == registration_count:
                all_parsers_started.set()
        assert release_parse.wait(timeout=10)
        return real_parse_yaml(path)

    def register(index):
        try:
            engine.register(f"pipeline-{index}", yaml_path)
        except BaseException as exc:
            with errors_lock:
                errors.append(exc)

    engine = Engine(max_concurrent=1)
    with patch("engine._pipeline.parse_yaml", blocked_parse_yaml):
        threads = [
            threading.Thread(target=register, args=(index,))
            for index in range(registration_count)
        ]
        for thread in threads:
            thread.start()
        assert all_parsers_started.wait(timeout=10)
        engine.shutdown(wait=False)
        release_parse.set()
        for thread in threads:
            thread.join(timeout=10)

    assert all(not thread.is_alive() for thread in threads)
    assert len(errors) == registration_count
    assert all(isinstance(error, RuntimeError) for error in errors)
    assert engine.status() == {}
    assert engine._registering == set()


@pytest.mark.parametrize("attempts", [10])
def test_repeated_parse_failure_never_leaks_name_reservations(tmp_path, attempts):
    valid_yaml = _workflow_files(tmp_path)
    invalid_yaml = tmp_path / "invalid.yaml"
    invalid_yaml.write_text("workflow: [", encoding="utf-8")
    engine = Engine(max_concurrent=1)

    for index in range(attempts):
        name = f"retry-{index}"
        with pytest.raises(Exception):
            engine.register(name, invalid_yaml)
        engine.register(name, valid_yaml)

    assert len(engine.status()) == attempts
    assert engine._registering == set()
    engine.shutdown()
