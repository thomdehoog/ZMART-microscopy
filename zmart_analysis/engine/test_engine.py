"""
Test suite for the v4 pipeline engine.

Covers: exception hierarchy, AST-based METADATA extraction, phase splitting,
per-environment workers with state dicts, worker pool with per-step
concurrency (semaphores), Engine API (register/submit/status/results),
scope tracking with single-axis completion, concurrent execution,
graceful failure handling, and lifecycle management.

Structure
---------
- TestErrors                  Exception hierarchy
- TestLoader                  AST-based METADATA extraction
- TestPhases                  Phase splitting from YAML step lists
- TestWorkerProtocol          Per-env workers, state dict, caching
- TestWorkerErrorPaths        Crash, timeout, missing file
- TestPool                    Per-env pools, semaphores, reaper
- TestEngineRegister          Pipeline registration
- TestEngineSubmit            Job submission, immediate execution
- TestEngineScopes            Single-axis scope completion
- TestEngineResults           Results queue, phase tagging
- TestEngineConcurrency       Parallel jobs, max_workers
- TestEngineErrors            Graceful failure handling
- TestEngineLifecycle         Shutdown, context manager
- TestEngineStatus            Observability
- TestEngineMultiPipeline     Multiple registered pipelines
- TestPackageAPI              Public exports and versioning

Usage
-----
    python -m pytest engine/test_engine.py -v
    python -m pytest engine/test_engine.py -k Scopes -v
"""

import atexit
import os
import shutil
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from unittest.mock import patch
from pathlib import Path

import pytest

# Ensure the engine package is importable
ENGINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE_DIR.parent))

from engine._loader import get_step_settings
from engine._run import split_phases, parse_yaml, StepConfig, Phase
from engine._errors import (
    WorkerError, WorkerSpawnError, WorkerCrashedError,
    WorkerTimeoutError, StepExecutionError, ScopeError,
)

# Test fixtures
BASIC_TEST = ENGINE_DIR.parent / "workflows" / "basic_test"
STEPS_DIR = BASIC_TEST / "steps"
PIPELINES_DIR = BASIC_TEST / "pipelines"

# All temp files go here; cleaned up on exit
_TEMP_DIR = tempfile.mkdtemp(prefix="engine_test_")
atexit.register(shutil.rmtree, _TEMP_DIR, True)
_counter = 0


def _next_id():
    global _counter
    _counter += 1
    return _counter


def _temp_step(code, name=None):
    """Write a temporary step .py file to _TEMP_DIR."""
    path = Path(_TEMP_DIR) / (f"{name}.py" if name else
                               f"step_{_next_id()}.py")
    path.write_text(textwrap.dedent(code))
    return str(path)


def _temp_yaml(content):
    """Write a temporary YAML pipeline file to _TEMP_DIR."""
    text = textwrap.dedent(content)
    if "functions_dir" not in text:
        functions_dir = Path(_TEMP_DIR).as_posix()
        header = f'metadata:\n  functions_dir: "{functions_dir}"\n'
        if "metadata:" in text:
            text = text.replace("metadata:", header.rstrip("\n"), 1)
        else:
            text = header + text
    path = Path(_TEMP_DIR) / f"pipeline_{_next_id()}.yaml"
    path.write_text(text)
    return str(path)


def _capture_exception(errors, function):
    """Run ``function`` and append any raised exception for thread assertions."""
    try:
        function()
    except BaseException as exc:
        errors.append(exc)


def _wait_for_results(engine, name, expected, timeout=30):
    """Poll engine.results() until expected count is reached or timeout.

    Replaces fixed time.sleep() patterns with bounded polling -- fast when
    work is fast, robust when it isn't.
    """
    t0 = time.monotonic()
    collected = []
    while time.monotonic() - t0 < timeout:
        collected.extend(engine.results(name))
        if len(collected) >= expected:
            return collected
        time.sleep(0.05)
    return collected


def _wait_for_status(engine, name, expected_total, timeout=30):
    """Poll engine.status() until completed+failed >= expected_total.

    Use when a test cares about pipeline status (failed counts, etc.)
    rather than draining results.
    """
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        s = engine.status(name)
        if s["completed"] + s["failed"] >= expected_total:
            return s
        time.sleep(0.05)
    return engine.status(name)


# ---- Errors ----------------------------------------------------------


class TestErrors(unittest.TestCase):

    def test_worker_hierarchy(self):
        self.assertTrue(issubclass(WorkerSpawnError, WorkerError))
        self.assertTrue(issubclass(WorkerCrashedError, WorkerError))
        self.assertTrue(issubclass(WorkerTimeoutError, WorkerError))
        self.assertTrue(issubclass(StepExecutionError, WorkerError))

    def test_timeout_error_is_not_step_execution_error(self):
        # A killed-on-timeout worker is an infrastructure failure, not a
        # user-code exception, so the two types must stay distinct.
        self.assertFalse(issubclass(WorkerTimeoutError, StepExecutionError))
        self.assertFalse(issubclass(StepExecutionError, WorkerTimeoutError))

    def test_step_execution_error_stores_traceback(self):
        err = StepExecutionError("boom", remote_traceback="tb")
        self.assertEqual(str(err), "boom")
        self.assertEqual(err.remote_traceback, "tb")

    def test_step_execution_error_traceback_default_none(self):
        self.assertIsNone(StepExecutionError("x").remote_traceback)

    def test_scope_error_independent(self):
        self.assertFalse(issubclass(ScopeError, WorkerError))
        self.assertTrue(issubclass(ScopeError, Exception))


# ---- Loader ----------------------------------------------------------


class TestLoader(unittest.TestCase):

    def test_defaults_no_metadata(self):
        path = _temp_step("def run(pd, state, **p): return pd")
        s = get_step_settings(Path(path))
        self.assertIsNone(s["environment"])
        self.assertEqual(s["max_workers"], 1)

    def test_explicit_environment(self):
        path = _temp_step("""
            METADATA = {"environment": "gpu_env"}
            def run(pd, state, **p): return pd
        """)
        s = get_step_settings(Path(path))
        self.assertEqual(s["environment"], "gpu_env")

    def test_max_workers(self):
        path = _temp_step("""
            METADATA = {"max_workers": 5}
            def run(pd, state, **p): return pd
        """)
        s = get_step_settings(Path(path))
        self.assertEqual(s["max_workers"], 5)

    def test_max_workers_default_1(self):
        path = _temp_step('METADATA = {"environment": "some_env"}')
        s = get_step_settings(Path(path))
        self.assertEqual(s["max_workers"], 1)

    def test_no_device_in_output(self):
        """v4 does not have a device field."""
        path = _temp_step('METADATA = {"environment": "e", "device": "gpu"}')
        s = get_step_settings(Path(path))
        self.assertNotIn("device", s)

    def test_does_not_execute_module_code(self):
        path = _temp_step("""
            import nonexistent_package_xyz
            METADATA = {"environment": "safe", "max_workers": 3}
            def run(pd, state, **p): return pd
        """)
        s = get_step_settings(Path(path))
        self.assertEqual(s["environment"], "safe")
        self.assertEqual(s["max_workers"], 3)


# ---- Phases ----------------------------------------------------------


class TestPhases(unittest.TestCase):

    def test_no_scope_single_phase(self):
        steps = [{"a": None}, {"b": {"x": 1}}]
        phases = split_phases(steps)
        self.assertEqual(len(phases), 1)
        self.assertIsNone(phases[0].scope)
        self.assertEqual(phases[0].steps[0].name, "a")
        self.assertEqual(phases[0].steps[1].params, {"x": 1})

    def test_one_scope_two_phases(self):
        steps = [
            {"preprocess": None},
            {"segment": None},
            {"stitch": {"scope": "group"}},
            {"analyze": None},
        ]
        phases = split_phases(steps)
        self.assertEqual(len(phases), 2)
        self.assertIsNone(phases[0].scope)
        self.assertEqual([s.name for s in phases[0].steps],
                         ["preprocess", "segment"])
        self.assertEqual(phases[1].scope, "group")
        self.assertEqual([s.name for s in phases[1].steps],
                         ["stitch", "analyze"])

    def test_two_scopes_three_phases(self):
        steps = [
            {"a": None},
            {"b": {"scope": "group"}},
            {"c": None},
            {"d": {"scope": "all"}},
        ]
        phases = split_phases(steps)
        self.assertEqual(len(phases), 3)
        self.assertIsNone(phases[0].scope)
        self.assertEqual(phases[1].scope, "group")
        self.assertEqual(phases[2].scope, "all")

    def test_scope_params_separated(self):
        steps = [{"step": {"scope": "region", "sigma": 1.0}}]
        phases = split_phases(steps)
        self.assertEqual(phases[0].steps[0].params, {"sigma": 1.0})
        self.assertNotIn("scope", phases[0].steps[0].params)

    def test_scope_on_first_step(self):
        steps = [{"a": {"scope": "region"}}, {"b": None}]
        phases = split_phases(steps)
        self.assertEqual(len(phases), 1)
        self.assertEqual(phases[0].scope, "region")


# ---- Worker (protocol) -----------------------------------------------


class TestWorkerProtocol(unittest.TestCase):

    def test_execute_returns_result(self):
        from engine._worker import Worker
        path = _temp_step("""
            def run(pd, state, **p):
                pd["ran"] = True
                pd["x"] = p.get("x")
                return pd
        """)
        w = Worker(environment=None, connect_timeout=10)
        try:
            result = w.execute(path, {"input": 1}, {"x": 42}, timeout=10)
        finally:
            w.shutdown()
        self.assertTrue(result["ran"])
        self.assertEqual(result["x"], 42)
        self.assertEqual(result["input"], 1)

    def test_different_steps_same_worker(self):
        from engine._worker import Worker
        path_a = _temp_step("""
            def run(pd, state, **p): pd["from"] = "a"; return pd
        """)
        path_b = _temp_step("""
            def run(pd, state, **p): pd["from"] = "b"; return pd
        """)
        w = Worker(environment=None, connect_timeout=10)
        try:
            ra = w.execute(path_a, {}, {}, timeout=10)
            rb = w.execute(path_b, {}, {}, timeout=10)
            self.assertEqual(ra["from"], "a")
            self.assertEqual(rb["from"], "b")
        finally:
            w.shutdown()

    def test_module_caching(self):
        from engine._worker import Worker
        path = _temp_step("""
            _n = 0
            def run(pd, state, **p):
                global _n
                _n += 1
                pd["n"] = _n
                return pd
        """)
        w = Worker(environment=None, connect_timeout=10)
        try:
            r1 = w.execute(path, {}, {}, timeout=10)
            r2 = w.execute(path, {}, {}, timeout=10)
            self.assertEqual(r1["n"], 1)
            self.assertEqual(r2["n"], 2)
        finally:
            w.shutdown()

    def test_state_dict_persists(self):
        """State dict persists across calls for the same step."""
        from engine._worker import Worker
        path = _temp_step("""
            def run(pd, state, **p):
                state.setdefault("count", 0)
                state["count"] += 1
                pd["count"] = state["count"]
                return pd
        """)
        w = Worker(environment=None, connect_timeout=10)
        try:
            r1 = w.execute(path, {}, {}, timeout=10)
            r2 = w.execute(path, {}, {}, timeout=10)
            r3 = w.execute(path, {}, {}, timeout=10)
            self.assertEqual(r1["count"], 1)
            self.assertEqual(r2["count"], 2)
            self.assertEqual(r3["count"], 3)
        finally:
            w.shutdown()

    def test_state_dict_isolated_per_step(self):
        """Different steps get separate state dicts."""
        from engine._worker import Worker
        path_a = _temp_step("""
            def run(pd, state, **p):
                state.setdefault("key", "a")
                pd["state_key"] = state["key"]
                return pd
        """)
        path_b = _temp_step("""
            def run(pd, state, **p):
                state.setdefault("key", "b")
                pd["state_key"] = state["key"]
                return pd
        """)
        w = Worker(environment=None, connect_timeout=10)
        try:
            ra = w.execute(path_a, {}, {}, timeout=10)
            rb = w.execute(path_b, {}, {}, timeout=10)
            self.assertEqual(ra["state_key"], "a")
            self.assertEqual(rb["state_key"], "b")
        finally:
            w.shutdown()

    def test_persistent_reuses_process(self):
        from engine._worker import Worker
        path = _temp_step("""
            import os
            def run(pd, state, **p): pd["pid"] = os.getpid(); return pd
        """)
        w = Worker(environment=None, connect_timeout=10)
        try:
            r1 = w.execute(path, {}, {}, timeout=10)
            r2 = w.execute(path, {}, {}, timeout=10)
            self.assertEqual(r1["pid"], r2["pid"])
        finally:
            w.shutdown()

    def test_shutdown_and_respawn(self):
        from engine._worker import Worker
        path = _temp_step("""
            import os
            def run(pd, state, **p): pd["pid"] = os.getpid(); return pd
        """)
        w = Worker(environment=None, connect_timeout=10)
        try:
            r1 = w.execute(path, {}, {}, timeout=10)
            w.shutdown()
            r2 = w.execute(path, {}, {}, timeout=10)
            self.assertNotEqual(r1["pid"], r2["pid"])
        finally:
            w.shutdown()

    def test_complex_types(self):
        from engine._worker import Worker
        path = _temp_step("def run(pd, state, **p): return pd")
        data = {
            "tuple": (1, 2), "set": {3, 4}, "bytes": b"\xff",
            "nested": {"a": [None, True, {"b": 2.5}]},
        }
        w = Worker(environment=None, connect_timeout=10)
        try:
            r = w.execute(path, data, {}, timeout=10)
        finally:
            w.shutdown()
        self.assertEqual(r["tuple"], (1, 2))
        self.assertEqual(r["set"], {3, 4})
        self.assertEqual(r["nested"]["a"][2]["b"], 2.5)

    def test_worker_status(self):
        from engine._worker import Worker
        w = Worker(environment=None, connect_timeout=10)
        s = w.status
        self.assertEqual(s["state"], "stopped")
        w.shutdown()


# ---- Worker Error Paths ----------------------------------------------


class TestWorkerErrorPaths(unittest.TestCase):

    def test_crash_raises_worker_crashed(self):
        from engine._worker import Worker
        path = _temp_step("""
            import os
            def run(pd, state, **p): os._exit(1)
        """)
        w = Worker(environment=None, connect_timeout=10)
        with self.assertRaises(WorkerCrashedError):
            w.execute(path, {}, {}, timeout=10)
        w.shutdown()

    def test_timeout_raises_worker_timeout_error(self):
        from engine._worker import Worker
        path = _temp_step("""
            import time
            def run(pd, state, **p): time.sleep(30); return pd
        """)
        w = Worker(environment=None, connect_timeout=10)
        with self.assertRaises(WorkerTimeoutError) as ctx:
            w.execute(path, {}, {}, timeout=1)
        self.assertIn("timed out", str(ctx.exception))
        # A slow step is not a user-code exception; keep the types distinct.
        self.assertNotIsInstance(ctx.exception, StepExecutionError)
        w.shutdown()

    def test_step_error_has_traceback(self):
        from engine._worker import Worker
        path = _temp_step("""
            def run(pd, state, **p): raise ValueError("test")
        """)
        w = Worker(environment=None, connect_timeout=10)
        with self.assertRaises(StepExecutionError) as ctx:
            w.execute(path, {}, {}, timeout=10)
        self.assertIn("test", str(ctx.exception))
        self.assertIn("ValueError", ctx.exception.remote_traceback)
        w.shutdown()

    def test_spawn_command_passes_engine_pid_as_parent_pid(self):
        # Orphan detection must watch the engine PID explicitly, because a
        # conda-env worker's real parent is the `conda run` wrapper.
        import subprocess as _sp
        from engine import _worker

        captured = {}
        real_popen = _sp.Popen

        def fake_popen(cmd, *a, **k):
            captured["cmd"] = list(cmd)
            # Fail the spawn immediately so no real subprocess is created;
            # we only care about the command that would have been run.
            raise OSError("blocked for test")

        w = _worker.Worker(environment=None, connect_timeout=1)
        _worker.subprocess.Popen = fake_popen
        try:
            with self.assertRaises(WorkerSpawnError):
                w.ensure_running()
        finally:
            _worker.subprocess.Popen = real_popen
            w.shutdown()

        cmd = captured["cmd"]
        self.assertIn("--parent-pid", cmd)
        pid_arg = cmd[cmd.index("--parent-pid") + 1]
        self.assertEqual(pid_arg, str(os.getpid()))

    def test_worker_exits_when_watched_parent_pid_dies(self):
        # End-to-end: the worker watches the --parent-pid it is given, not
        # its real parent. Here the worker's real parent is this test process
        # (alive throughout); its watched parent is a throwaway process we
        # kill. The worker must exit anyway -- proving it does not rely on
        # os.getppid(), which is the conda-wrapper failure mode.
        import subprocess as _sp
        from multiprocessing.connection import Listener
        from engine._worker import WORKER_SCRIPT

        authkey = os.urandom(16)
        listener = Listener(("localhost", 0), authkey=authkey)
        port = listener.address[1]
        listener._listener._socket.settimeout(15)

        fake_parent = _sp.Popen(
            [sys.executable, "-c", "import time; time.sleep(300)"]
        )
        worker = _sp.Popen([
            sys.executable, str(WORKER_SCRIPT),
            "--port", str(port),
            "--authkey", authkey.hex(),
            "--parent-pid", str(fake_parent.pid),
        ], stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)

        try:
            conn = listener.accept()  # worker connected -> it is running
            self.assertIsNone(worker.poll(), "worker exited before parent died")

            fake_parent.terminate()
            fake_parent.wait(timeout=10)

            # Worker polls parent liveness on a <=5s cycle; allow margin.
            worker.wait(timeout=20)
            self.assertIsNotNone(
                worker.poll(),
                "worker did not exit after its watched parent died",
            )
            conn.close()
        finally:
            for proc in (worker, fake_parent):
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=10)
            listener.close()

    def test_windows_parent_check_distinguishes_running_and_terminated(self):
        from engine.worker_script import _windows_process_alive

        class FakeKernel32:
            def __init__(self, wait_result, handle=123):
                self.wait_result = wait_result
                self.handle = handle
                self.closed = []

            def OpenProcess(self, access, inherit, process_id):
                self.open_args = (access, inherit, process_id)
                return self.handle

            def WaitForSingleObject(self, handle, timeout_ms):
                self.wait_args = (handle, timeout_ms)
                return self.wait_result

            def CloseHandle(self, handle):
                self.closed.append(handle)

        cases = (
            (0x00000102, True),   # WAIT_TIMEOUT: process still running
            (0x00000000, False),  # WAIT_OBJECT_0: process terminated
            (0xFFFFFFFF, False),  # WAIT_FAILED: do not claim it is alive
        )
        for wait_result, expected in cases:
            with self.subTest(wait_result=wait_result):
                kernel32 = FakeKernel32(wait_result)
                self.assertEqual(
                    _windows_process_alive(4321, kernel32), expected
                )
                self.assertEqual(
                    kernel32.open_args, (0x00100000, False, 4321)
                )
                self.assertEqual(kernel32.wait_args, (123, 0))
                self.assertEqual(kernel32.closed, [123])

        unavailable = FakeKernel32(0x00000102, handle=0)
        self.assertFalse(_windows_process_alive(4321, unavailable))
        self.assertEqual(unavailable.closed, [])


# ---- Pool ------------------------------------------------------------


class TestPool(unittest.TestCase):

    def test_per_env_worker_reuse(self):
        from engine._pool import WorkerPool
        path = _temp_step("""
            import os
            def run(pd, state, **p): pd["pid"] = os.getpid(); return pd
        """)
        pool = WorkerPool(idle_timeout=60)
        r1 = pool.execute(None, path, {}, {}, timeout=10)
        r2 = pool.execute(None, path, {}, {}, timeout=10)
        self.assertEqual(r1["pid"], r2["pid"])
        pool.shutdown_all()

    def test_shutdown_before_use(self):
        from engine._pool import WorkerPool
        path = _temp_step("def run(pd, state, **p): return pd")
        pool = WorkerPool()
        pool.shutdown_all()
        with self.assertRaisesRegex(RuntimeError, "shut down"):
            pool.execute(None, path, {}, {}, timeout=10)

    def test_error_through_pool(self):
        from engine._pool import WorkerPool
        path = _temp_step("""
            def run(pd, state, **p): raise ValueError("pool err")
        """)
        pool = WorkerPool()
        with self.assertRaises(StepExecutionError) as ctx:
            pool.execute(None, path, {}, {}, timeout=10)
        self.assertIn("pool err", str(ctx.exception))
        pool.shutdown_all()

    def test_reaper_removes_idle(self):
        from engine._pool import WorkerPool
        path = _temp_step("def run(pd, state, **p): return pd")
        pool = WorkerPool(idle_timeout=0.2)
        pool.execute(None, path, {}, {}, timeout=10)

        env_pool = pool._env_pools[None]
        self.assertTrue(len(env_pool._idle) > 0
                        or len(env_pool._busy) > 0)

        time.sleep(0.4)
        env_pool.reap_idle()
        self.assertEqual(len(env_pool._idle), 0)
        pool.shutdown_all()

    def test_semaphore_limits_concurrency(self):
        """max_workers=1 serializes execution of the same step."""
        from engine._pool import WorkerPool
        path = _temp_step("""
            import time
            def run(pd, state, **p):
                time.sleep(0.3)
                pd["done"] = True
                return pd
        """)
        pool = WorkerPool()
        results = []

        def run_one():
            r = pool.execute(None, path, {}, {}, max_workers=1, timeout=15)
            results.append(r)

        t0 = time.monotonic()
        threads = [threading.Thread(target=run_one) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        elapsed = time.monotonic() - t0
        pool.shutdown_all()

        self.assertEqual(len(results), 2)
        self.assertGreater(elapsed, 0.5,
                           "max_workers=1 should serialize execution")

    def test_semaphore_allows_parallelism(self):
        """max_workers=4 allows parallel execution."""
        from engine._pool import WorkerPool
        path = _temp_step("""
            import time
            def run(pd, state, **p):
                time.sleep(0.3)
                pd["done"] = True
                return pd
        """)
        pool = WorkerPool()
        results = []

        def run_one():
            r = pool.execute(None, path, {}, {}, max_workers=4, timeout=15)
            results.append(r)

        t0 = time.monotonic()
        threads = [threading.Thread(target=run_one) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        elapsed = time.monotonic() - t0
        pool.shutdown_all()

        self.assertEqual(len(results), 4)
        self.assertLess(elapsed, 1.0,
                        "max_workers=4 should allow parallel execution")


# ---- Engine (register) -----------------------------------------------


class TestEngineRegister(unittest.TestCase):

    def test_register_simple(self):
        _temp_step("def run(pd, state, **p): return pd", name="reg_a")
        yaml = _temp_yaml("wf:\n  - reg_a:")
        from engine import Engine
        with Engine() as e:
            e.register("test", yaml)

    def test_register_duplicate_raises(self):
        _temp_step("def run(pd, state, **p): return pd", name="reg_b")
        yaml = _temp_yaml("wf:\n  - reg_b:")
        from engine import Engine
        with Engine() as e:
            e.register("test", yaml)
            with self.assertRaises(ValueError):
                e.register("test", yaml)

    def test_register_bad_yaml(self):
        path = Path(_TEMP_DIR) / f"bad_{_next_id()}.yaml"
        path.write_text("metadata:\n  functions_dir: .")
        from engine import Engine
        with Engine() as e:
            with self.assertRaises(ValueError):
                e.register("bad", str(path))

    def test_concurrent_register_same_name_raises_once(self):
        # The duplicate check and the insert must be atomic: with the check
        # and insert split across two lock holds, two threads racing on the
        # same name both passed and the second silently clobbered the first.
        _temp_step("def run(pd, state, **p): return pd", name="reg_race")
        yaml = _temp_yaml("wf:\n  - reg_race:")
        from engine import Engine

        with Engine() as e:
            start = threading.Barrier(8)
            errors = []
            lock = threading.Lock()

            def worker():
                start.wait()
                try:
                    e.register("dup", yaml)
                except ValueError:
                    with lock:
                        errors.append(1)

            threads = [threading.Thread(target=worker) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # Exactly one registration wins; every other thread sees ValueError.
            self.assertEqual(sum(errors), 7)
            self.assertIn("dup", e._pipelines)


# ---- Engine (submit) -------------------------------------------------


class TestEngineSubmit(unittest.TestCase):

    def test_simple_submit(self):
        _temp_step("""
            def run(pd, state, **p):
                pd["ok"] = True
                return pd
        """, name="sub_a")
        yaml = _temp_yaml("wf:\n  - sub_a:")
        from engine import Engine
        with Engine() as e:
            e.register("test", yaml)
            e.submit("test", {})
            results = _wait_for_results(e, "test", 1, timeout=10)
        self.assertTrue(len(results) > 0)
        self.assertTrue(results[0]["ok"])

    def test_multi_step(self):
        _temp_step("""
            def run(pd, state, **p):
                pd["s1"] = 1
                return pd
        """, name="ms_a")
        _temp_step("""
            def run(pd, state, **p):
                pd["s2"] = pd["s1"] + 1
                return pd
        """, name="ms_b")
        yaml = _temp_yaml("wf:\n  - ms_a:\n  - ms_b:")
        from engine import Engine
        with Engine() as e:
            e.register("test", yaml)
            e.submit("test", {})
            results = _wait_for_results(e, "test", 1, timeout=10)
        self.assertEqual(results[0]["s1"], 1)
        self.assertEqual(results[0]["s2"], 2)

    def test_data_flows_between_steps(self):
        _temp_step("""
            def run(pd, state, **p):
                pd["from_a"] = "hello"
                return pd
        """, name="df_a")
        _temp_step("""
            def run(pd, state, **p):
                pd["saw"] = pd.get("from_a")
                return pd
        """, name="df_b")
        yaml = _temp_yaml("wf:\n  - df_a:\n  - df_b:")
        from engine import Engine
        with Engine() as e:
            e.register("test", yaml)
            e.submit("test", {})
            results = _wait_for_results(e, "test", 1, timeout=10)
        self.assertEqual(results[0]["saw"], "hello")

    def test_input_data(self):
        _temp_step("def run(pd, state, **p): return pd", name="inp")
        yaml = _temp_yaml("wf:\n  - inp:")
        from engine import Engine
        with Engine() as e:
            e.register("test", yaml)
            e.submit("test", {"key": "val"})
            results = _wait_for_results(e, "test", 1, timeout=10)
        self.assertEqual(results[0]["input"]["key"], "val")

    def test_params_from_yaml(self):
        _temp_step("""
            def run(pd, state, **p):
                pd["x"] = p.get("x")
                return pd
        """, name="par")
        yaml = _temp_yaml("wf:\n  - par:\n      x: 42")
        from engine import Engine
        with Engine() as e:
            e.register("test", yaml)
            e.submit("test", {})
            results = _wait_for_results(e, "test", 1, timeout=10)
        self.assertEqual(results[0]["x"], 42)

    def test_concurrent_submits(self):
        _temp_step("""
            def run(pd, state, **p):
                pd["job"] = pd["input"]["job"]
                return pd
        """, name="conc")
        yaml = _temp_yaml("wf:\n  - conc:")
        from engine import Engine
        with Engine() as e:
            e.register("test", yaml)
            for i in range(5):
                e.submit("test", {"job": i})
            results = _wait_for_results(e, "test", 5, timeout=15)
        self.assertEqual(len(results), 5)
        self.assertEqual(sorted(r["job"] for r in results), list(range(5)))


# ---- Engine (scopes) -------------------------------------------------


class TestEngineScopes(unittest.TestCase):

    def test_scope_collects_results(self):
        """Scoped step receives accumulated results from all jobs."""
        _temp_step("""
            def run(pd, state, **p):
                pd["tile"] = pd["input"]["tile"]
                return pd
        """, name="sc_seg")
        _temp_step("""
            def run(pd, state, **p):
                tiles = [r["tile"] for r in pd["results"]]
                pd["tiles"] = sorted(tiles)
                return pd
        """, name="sc_stitch")
        yaml = _temp_yaml("""
            wf:
              - sc_seg:
              - sc_stitch:
                  scope: group
        """)
        from engine import Engine
        with Engine() as e:
            e.register("test", yaml)
            for i in range(3):
                complete = "group" if i == 2 else None
                e.submit("test", {"tile": i},
                         scope={"group": "R1"},
                         complete=complete)
            results = _wait_for_results(e, "test", 4, timeout=15)

        # Should have 3 Phase 0 results + 1 scoped result
        phase0 = [r for r in results if r.get("_phase") == 0]
        scoped = [r for r in results if r.get("_phase") == 1]
        self.assertEqual(len(phase0), 3)
        self.assertEqual(len(scoped), 1)
        self.assertEqual(scoped[0]["tiles"], [0, 1, 2])

    def test_scope_preserves_submission_order(self):
        _temp_step("""
            import time
            def run(pd, state, **p):
                time.sleep(0.05)
                pd["val"] = pd["input"]["val"]
                return pd
        """, name="ord_step")
        _temp_step("""
            def run(pd, state, **p):
                pd["order"] = [r["val"] for r in pd["results"]]
                return pd
        """, name="ord_collect")
        yaml = _temp_yaml("""
            wf:
              - ord_step:
              - ord_collect:
                  scope: group
        """)
        from engine import Engine
        with Engine() as e:
            e.register("test", yaml)
            for i in range(5):
                complete = "group" if i == 4 else None
                e.submit("test", {"val": i},
                         scope={"group": "G1"},
                         complete=complete)
            results = _wait_for_results(e, "test", 6, timeout=20)

        scoped = [r for r in results if r.get("_phase") == 1]
        self.assertEqual(len(scoped), 1)
        self.assertEqual(scoped[0]["order"], [0, 1, 2, 3, 4])

    def test_multiple_scope_groups(self):
        """Different scope groups are collected independently."""
        _temp_step("""
            def run(pd, state, **p):
                pd["val"] = pd["input"]["val"]
                return pd
        """, name="mg_step")
        _temp_step("""
            def run(pd, state, **p):
                pd["vals"] = sorted([r["val"] for r in pd["results"]])
                return pd
        """, name="mg_collect")
        yaml = _temp_yaml("""
            wf:
              - mg_step:
              - mg_collect:
                  scope: group
        """)
        from engine import Engine
        with Engine() as e:
            e.register("test", yaml)
            # Group A: values 10, 20
            e.submit("test", {"val": 10}, scope={"group": "A"})
            e.submit("test", {"val": 20}, scope={"group": "A"},
                     complete="group")
            # Group B: values 30, 40, 50
            e.submit("test", {"val": 30}, scope={"group": "B"})
            e.submit("test", {"val": 40}, scope={"group": "B"})
            e.submit("test", {"val": 50}, scope={"group": "B"},
                     complete="group")
            results = _wait_for_results(e, "test", 7, timeout=20)

        scoped = [r for r in results if r.get("_phase") == 1]
        scoped_vals = sorted([tuple(r["vals"]) for r in scoped])
        self.assertIn((10, 20), scoped_vals)
        self.assertIn((30, 40, 50), scoped_vals)

    def test_complete_list(self):
        """complete parameter accepts a list of scope levels."""
        _temp_step("""
            def run(pd, state, **p):
                pd["v"] = pd["input"]["v"]
                return pd
        """, name="cl_step")
        _temp_step("""
            def run(pd, state, **p):
                pd["group_vals"] = [r["v"] for r in pd["results"]]
                return pd
        """, name="cl_group")
        _temp_step("""
            def run(pd, state, **p):
                pd["all_vals"] = [r.get("group_vals", [])
                                   for r in pd["results"]]
                return pd
        """, name="cl_all")
        yaml = _temp_yaml("""
            wf:
              - cl_step:
              - cl_group:
                  scope: group
              - cl_all:
                  scope: all
        """)
        from engine import Engine
        with Engine() as e:
            e.register("test", yaml)
            e.submit("test", {"v": 1}, scope={"group": "G1"})
            e.submit("test", {"v": 2}, scope={"group": "G1"},
                     complete=["group", "all"])
            results = _wait_for_results(e, "test", 4, timeout=20)

        phase2 = [r for r in results if r.get("_phase") == 2]
        self.assertEqual(len(phase2), 1)

    def test_all_scope_collects_everything(self):
        """Scope 'all' (not a key in any scope dict) collects everything."""
        _temp_step("""
            def run(pd, state, **p):
                pd["v"] = pd["input"]["v"]
                return pd
        """, name="al_step")
        _temp_step("""
            def run(pd, state, **p):
                pd["total"] = sum(r["v"] for r in pd["results"])
                return pd
        """, name="al_sum")
        yaml = _temp_yaml("""
            wf:
              - al_step:
              - al_sum:
                  scope: all
        """)
        from engine import Engine
        with Engine() as e:
            e.register("test", yaml)
            e.submit("test", {"v": 10}, scope={"group": "A"})
            e.submit("test", {"v": 20}, scope={"group": "B"})
            e.submit("test", {"v": 30}, scope={"group": "C"},
                     complete="all")
            results = _wait_for_results(e, "test", 4, timeout=15)

        scoped = [r for r in results if r.get("_phase") == 1]
        self.assertEqual(len(scoped), 1)
        self.assertEqual(scoped[0]["total"], 60)

    def test_failures_reach_scoped_step(self):
        """Phase 0 failures are aggregated into pipeline_data['failures']
        for the scoped step to inspect."""
        _temp_step("""
            def run(pd, state, **p):
                if pd["input"]["v"] == 99:
                    raise ValueError("deliberate failure")
                pd["v"] = pd["input"]["v"]
                return pd
        """, name="fr_step")
        _temp_step("""
            def run(pd, state, **p):
                pd["n_results"] = len(pd["results"])
                pd["n_failures"] = len(pd["failures"])
                pd["failure_steps"] = [f.get("step") for f in pd["failures"]]
                pd["failure_errors"] = [f.get("error") for f in pd["failures"]]
                return pd
        """, name="fr_collect")
        yaml = _temp_yaml("""
            wf:
              - fr_step:
              - fr_collect:
                  scope: group
        """)
        from engine import Engine
        with Engine() as e:
            e.register("test", yaml)
            e.submit("test", {"v": 1}, scope={"group": "G"})
            e.submit("test", {"v": 99}, scope={"group": "G"})
            e.submit("test", {"v": 2}, scope={"group": "G"},
                     complete="group")
            results = _wait_for_results(e, "test", 3, timeout=15)

        scoped = [r for r in results if r.get("_phase") == 1]
        self.assertEqual(len(scoped), 1)
        self.assertEqual(scoped[0]["n_results"], 2)
        self.assertEqual(scoped[0]["n_failures"], 1)
        self.assertEqual(scoped[0]["failure_steps"], ["fr_step"])
        self.assertIn("deliberate failure", scoped[0]["failure_errors"][0])

    def test_scope_collection_prunes_consumed_failures(self):
        """Consumed scope failures leave status; unrelated failures remain."""
        _temp_step("""
            def run(pd, state, **p):
                if pd["input"].get("fail"):
                    raise ValueError(f"failed {pd['input']['group']}")
                pd["group"] = pd["input"]["group"]
                return pd
        """, name="pf_step")
        _temp_step("""
            def run(pd, state, **p):
                pd["n_results"] = len(pd["results"])
                pd["failure_errors"] = [f["error"] for f in pd["failures"]]
                return pd
        """, name="pf_collect")
        yaml = _temp_yaml("""
            wf:
              - pf_step:
              - pf_collect:
                  scope: group
        """)
        from engine import Engine
        with Engine() as e:
            e.register("test", yaml)
            e.submit("test", {"group": "A", "fail": True},
                     scope={"group": "A"})
            e.submit("test", {"group": "B", "fail": True},
                     scope={"group": "B"})
            _wait_for_status(e, "test", expected_total=2, timeout=15)

            e.submit("test", {"group": "A", "fail": False},
                     scope={"group": "A"}, complete="group")
            results = _wait_for_results(e, "test", 2, timeout=15)
            status = e.status("test")

        scoped = [r for r in results if r.get("_phase") == 1]
        self.assertEqual(len(scoped), 1)
        self.assertEqual(scoped[0]["n_results"], 1)
        self.assertEqual(len(scoped[0]["failure_errors"]), 1)
        self.assertIn("failed A", scoped[0]["failure_errors"][0])

        remaining_errors = [f["error"] for f in status["failures"]]
        self.assertEqual(len(remaining_errors), 1)
        self.assertIn("failed B", remaining_errors[0])


# ---- Engine (environment isolation) ----------------------------------


@pytest.mark.conda_env
class TestEngineEnvironmentIsolation(unittest.TestCase):
    """Verify the engine actually launches steps in their declared conda env.

    Requires the SMART--basic_test--env_a conda env (Python 3.10) created
    by workflows/basic_test/environments/setup_env.py. The conda_env marker
    lets CI exclude this class via ``pytest -m "not conda_env"``.
    """

    @classmethod
    def setUpClass(cls):
        from engine.conda_utils import get_conda_info, env_exists
        cls.env_name = "SMART--basic_test--env_a"
        # Skip if env_a doesn't exist (don't fail the suite for missing fixture)
        try:
            info = get_conda_info()
        except FileNotFoundError:
            raise unittest.SkipTest("conda not found")
        if not env_exists(info, cls.env_name):
            raise unittest.SkipTest(
                f"conda env '{cls.env_name}' not found; "
                f"run workflows/basic_test/environments/setup_env.py"
            )

    def test_step_runs_in_declared_environment(self):
        """A step with METADATA={'environment': 'SMART--basic_test--env_a'}
        runs in env_a's Python (3.10), not the orchestrator's Python."""
        _temp_step(f"""
            import sys

            METADATA = {{"environment": "{self.env_name}"}}

            def run(pd, state, **p):
                pd["py_major"] = sys.version_info[0]
                pd["py_minor"] = sys.version_info[1]
                pd["executable"] = sys.executable
                return pd
        """, name="env_a_check")
        yaml = _temp_yaml("wf:\n  - env_a_check:")
        from engine import Engine
        with Engine() as e:
            e.register("test", yaml)
            e.submit("test", {})
            results = _wait_for_results(e, "test", 1, timeout=60)

        self.assertEqual(len(results), 1, "step did not execute")
        self.assertEqual(results[0]["py_major"], 3)
        self.assertEqual(results[0]["py_minor"], 10,
                         f"expected Python 3.10 from env_a, "
                         f"got {results[0]['py_major']}.{results[0]['py_minor']}")
        self.assertIn(self.env_name, results[0]["executable"])


# ---- Engine (results) ------------------------------------------------


class TestEngineResults(unittest.TestCase):

    def test_results_consumed_on_retrieval(self):
        _temp_step("def run(pd, state, **p): return pd", name="drain")
        yaml = _temp_yaml("wf:\n  - drain:")
        from engine import Engine
        with Engine() as e:
            e.register("test", yaml)
            e.submit("test", {})
            r1 = _wait_for_results(e, "test", 1, timeout=10)
            r2 = e.results("test")
        self.assertEqual(len(r1), 1)
        self.assertEqual(len(r2), 0)

    def test_results_tagged_with_phase(self):
        _temp_step("def run(pd, state, **p): return pd", name="tag")
        yaml = _temp_yaml("wf:\n  - tag:")
        from engine import Engine
        with Engine() as e:
            e.register("test", yaml)
            e.submit("test", {})
            results = _wait_for_results(e, "test", 1, timeout=10)
        self.assertEqual(results[0]["_phase"], 0)
        self.assertIsNone(results[0]["_scope_level"])

    def test_unregistered_pipeline_raises(self):
        from engine import Engine
        with Engine() as e:
            with self.assertRaises(KeyError):
                e.results("nonexistent")


# ---- Engine (concurrency) -------------------------------------------


class TestEngineConcurrency(unittest.TestCase):

    def test_many_concurrent_jobs(self):
        _temp_step("""
            def run(pd, state, **p):
                pd["idx"] = pd["input"]["idx"]
                return pd
        """, name="many")
        yaml = _temp_yaml("wf:\n  - many:")
        from engine import Engine
        with Engine(max_concurrent=8) as e:
            e.register("test", yaml)
            for i in range(20):
                e.submit("test", {"idx": i})
            results = _wait_for_results(e, "test", 20, timeout=30)
        self.assertEqual(len(results), 20)
        self.assertEqual(sorted(r["idx"] for r in results), list(range(20)))


# ---- Engine (errors) -------------------------------------------------


class TestEngineErrors(unittest.TestCase):

    def test_failed_job_does_not_crash_pipeline(self):
        """Other jobs continue when one fails."""
        _temp_step("""
            def run(pd, state, **p):
                if pd["input"].get("fail"):
                    raise ValueError("deliberate failure")
                pd["ok"] = True
                return pd
        """, name="graceful")
        yaml = _temp_yaml("wf:\n  - graceful:")
        from engine import Engine
        with Engine() as e:
            e.register("test", yaml)
            e.submit("test", {"fail": True})
            e.submit("test", {"fail": False})
            e.submit("test", {"fail": False})
            status = _wait_for_status(e, "test", 3, timeout=15)
        self.assertGreaterEqual(status["completed"], 2)
        self.assertGreaterEqual(status["failed"], 1)

    def test_failures_in_status(self):
        _temp_step("""
            def run(pd, state, **p): raise RuntimeError("boom")
        """, name="fail_status")
        yaml = _temp_yaml("wf:\n  - fail_status:")
        from engine import Engine
        with Engine() as e:
            e.register("test", yaml)
            e.submit("test", {})
            status = _wait_for_status(e, "test", 1, timeout=10)
        self.assertEqual(status["failed"], 1)
        self.assertTrue(len(status["failures"]) > 0)
        self.assertIn("boom", status["failures"][0]["error"])

    def test_return_non_dict_raises(self):
        _temp_step("""
            def run(pd, state, **p): return "not a dict"
        """, name="bad_ret")
        yaml = _temp_yaml("wf:\n  - bad_ret:")
        from engine import Engine
        with Engine() as e:
            e.register("test", yaml)
            e.submit("test", {})
            status = _wait_for_status(e, "test", 1, timeout=10)
        self.assertEqual(status["failed"], 1)


# ---- Engine (lifecycle) ----------------------------------------------


class TestEngineLifecycle(unittest.TestCase):

    def test_context_manager(self):
        _temp_step("def run(pd, state, **p): return pd", name="ctx")
        yaml = _temp_yaml("wf:\n  - ctx:")
        from engine import Engine
        with Engine() as e:
            e.register("test", yaml)
            e.submit("test", {})
            results = _wait_for_results(e, "test", 1, timeout=10)
        self.assertEqual(len(results), 1)

    def test_shutdown_then_register_raises(self):
        """register() after shutdown raises RuntimeError."""
        from engine import Engine
        _temp_step("def run(pd, state, **p): return pd", name="shut_reg")
        yaml = _temp_yaml("wf:\n  - shut_reg:")
        e = Engine()
        e.shutdown()
        with self.assertRaises(RuntimeError):
            e.register("test", yaml)

    def test_concurrent_registration_reserves_pipeline_name(self):
        """Only one parser may build a given pipeline name at a time."""
        import engine._pipeline as pipeline_module
        from engine import Engine

        _temp_step("def run(pd, state, **p): return pd", name="reg_race")
        yaml = _temp_yaml("wf:\n  - reg_race:")
        parse_started = threading.Event()
        release_parse = threading.Event()
        real_parse_yaml = pipeline_module.parse_yaml
        errors = []

        def blocked_parse_yaml(path):
            parse_started.set()
            if not release_parse.wait(timeout=5):
                raise TimeoutError("test did not release YAML parsing")
            return real_parse_yaml(path)

        e = Engine()
        with patch("engine._pipeline.parse_yaml", blocked_parse_yaml):
            thread = threading.Thread(
                target=lambda: _capture_exception(
                    errors, lambda: e.register("test", yaml)
                )
            )
            thread.start()
            self.assertTrue(parse_started.wait(timeout=5))
            with self.assertRaisesRegex(ValueError, "already registered"):
                e.register("test", yaml)
            release_parse.set()
            thread.join(timeout=5)

        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertIn("test", e.status())
        e.shutdown()

    def test_registration_cannot_complete_after_shutdown_starts(self):
        """A registration parsing during shutdown must not become visible."""
        import engine._pipeline as pipeline_module
        from engine import Engine

        _temp_step("def run(pd, state, **p): return pd", name="reg_shutdown")
        yaml = _temp_yaml("wf:\n  - reg_shutdown:")
        parse_started = threading.Event()
        release_parse = threading.Event()
        real_parse_yaml = pipeline_module.parse_yaml
        errors = []

        def blocked_parse_yaml(path):
            parse_started.set()
            if not release_parse.wait(timeout=5):
                raise TimeoutError("test did not release YAML parsing")
            return real_parse_yaml(path)

        e = Engine()
        with patch("engine._pipeline.parse_yaml", blocked_parse_yaml):
            thread = threading.Thread(
                target=lambda: _capture_exception(
                    errors, lambda: e.register("late", yaml)
                )
            )
            thread.start()
            self.assertTrue(parse_started.wait(timeout=5))
            e.shutdown(wait=False)
            release_parse.set()
            thread.join(timeout=5)

        self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], RuntimeError)
        self.assertNotIn("late", e.status())

    def test_failed_registration_releases_pipeline_name(self):
        """A parse failure must not leave the name permanently reserved."""
        from engine import Engine

        _temp_step("def run(pd, state, **p): return pd", name="reg_retry")
        invalid_yaml = _temp_yaml("wf: [")
        valid_yaml = _temp_yaml("wf:\n  - reg_retry:")
        e = Engine()
        with self.assertRaises(Exception):
            e.register("retry", invalid_yaml)
        e.register("retry", valid_yaml)
        self.assertIn("retry", e.status())
        e.shutdown()

    def test_shutdown_then_submit_raises(self):
        """submit() after shutdown raises RuntimeError."""
        _temp_step("def run(pd, state, **p): return pd", name="shut_sub")
        yaml = _temp_yaml("wf:\n  - shut_sub:")
        from engine import Engine
        e = Engine()
        e.register("test", yaml)
        e.shutdown()
        with self.assertRaises(RuntimeError):
            e.submit("test", {})

    def test_double_shutdown(self):
        from engine import Engine
        e = Engine()
        e.shutdown()
        e.shutdown()  # should not raise

    def test_shutdown_without_wait_cancels_queue_and_closes_workers(self):
        _temp_step("""
            import time
            def run(pd, state, **p):
                time.sleep(0.3)
                return pd
        """, name="shutdown_slow")
        yaml = _temp_yaml("wf:\n  - shutdown_slow:")
        from engine import Engine

        e = Engine(max_concurrent=1)
        e.register("test", yaml)
        for i in range(12):
            e.submit("test", {"i": i})

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if e.status("test")["running"] == 1:
                break
            time.sleep(0.01)
        self.assertEqual(e.status("test")["running"], 1)

        e.shutdown(wait=False)

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status = e.status("test")
            if status["pending"] == 0 and status["running"] == 0:
                break
            time.sleep(0.01)

        status = e.status("test")
        self.assertEqual(status["pending"], 0)
        self.assertEqual(status["running"], 0)
        self.assertEqual(status["completed"] + status["failed"], 12)
        self.assertEqual(e._pool.status["workers"], [])


# ---- Engine (status) -------------------------------------------------


class TestEngineStatus(unittest.TestCase):

    def test_status_single_pipeline(self):
        _temp_step("def run(pd, state, **p): return pd", name="st")
        yaml = _temp_yaml("wf:\n  - st:")
        from engine import Engine
        with Engine() as e:
            e.register("test", yaml)
            e.submit("test", {})
            status = _wait_for_status(e, "test", 1, timeout=10)
        self.assertIn("completed", status)
        self.assertIn("failed", status)
        self.assertIn("pending", status)
        self.assertEqual(status["completed"], 1)

    def test_status_all_pipelines(self):
        _temp_step("def run(pd, state, **p): return pd", name="st2")
        yaml = _temp_yaml("wf:\n  - st2:")
        from engine import Engine
        with Engine() as e:
            e.register("a", yaml)
            e.register("b", yaml)
            status = e.status()
        self.assertIn("a", status)
        self.assertIn("b", status)

    def test_status_nonexistent_raises(self):
        from engine import Engine
        with Engine() as e:
            with self.assertRaises(KeyError):
                e.status("ghost")

    def test_status_failed_count_matches_failures_after_scope_completion(self):
        # Regression: scope collection drains the consumed failure records out
        # of the failures list. The failed COUNT must be derived from that
        # list, not held in a separate counter that keeps the stale failure
        # and desyncs status() -- which also made the documented poll pattern
        # `status["failures"][0] if status["failed"]` raise IndexError.
        _temp_step("""
            def run(pd, state, **p):
                if pd["input"]["tile"] == 1:
                    raise ValueError("bad tile")
                pd["tile"] = pd["input"]["tile"]
                return pd
        """, name="drift_seg")
        _temp_step("""
            def run(pd, state, **p):
                pd["tiles"] = sorted(r["tile"] for r in pd["results"])
                return pd
        """, name="drift_stitch")
        yaml = _temp_yaml("""
            wf:
              - drift_seg:
              - drift_stitch:
                  scope: group
        """)
        from engine import Engine

        with Engine() as e:
            e.register("test", yaml)
            for i in range(3):
                complete = "group" if i == 2 else None
                e.submit("test", {"tile": i},
                         scope={"group": "R1"}, complete=complete)

            # 2 surviving Phase-0 results + 1 scoped result (the failed tile
            # produces no Phase-0 result).
            results = _wait_for_results(e, "test", 3, timeout=15)

            # Let scope collection drain the consumed failure.
            deadline = time.monotonic() + 5
            status = e.status("test")
            while time.monotonic() < deadline and status["failures"]:
                time.sleep(0.02)
                status = e.status("test")

        self.assertEqual(len(results), 3)
        # The invariant: failed count always equals the failure-record count.
        self.assertEqual(status["failed"], len(status["failures"]))
        # The poll pattern used by run_pipeline.py must never IndexError.
        if status["failed"]:
            _ = status["failures"][0]

    def test_status_tracks_pending_and_running_jobs(self):
        _temp_step("""
            import time
            def run(pd, state, **p):
                time.sleep(0.3)
                return pd
        """, name="status_slow")
        yaml = _temp_yaml("wf:\n  - status_slow:")
        from engine import Engine

        with Engine(max_concurrent=1) as e:
            e.register("test", yaml)
            e.submit("test", {})
            e.submit("test", {})

            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                status = e.status("test")
                if status["running"] == 1 and status["pending"] == 1:
                    break
                time.sleep(0.01)

            self.assertEqual(status["pending"], 1)
            self.assertEqual(status["running"], 1)
            self.assertEqual(status["completed"], 0)
            results = _wait_for_results(e, "test", 2, timeout=5)
            status = e.status("test")

        self.assertEqual(len(results), 2)
        self.assertEqual(status["pending"], 0)
        self.assertEqual(status["running"], 0)
        self.assertEqual(status["completed"], 2)


# ---- Engine (multi-pipeline) ----------------------------------------


class TestEngineMultiPipeline(unittest.TestCase):

    def test_two_pipelines_shared_workers(self):
        _temp_step("""
            def run(pd, state, **p):
                pd["from"] = p.get("from", "unknown")
                return pd
        """, name="shared")
        yaml_a = _temp_yaml("wf_a:\n  - shared:\n      from: a")
        yaml_b = _temp_yaml("wf_b:\n  - shared:\n      from: b")
        from engine import Engine
        with Engine() as e:
            e.register("a", yaml_a)
            e.register("b", yaml_b)
            e.submit("a", {})
            e.submit("b", {})
            ra = _wait_for_results(e, "a", 1, timeout=10)
            rb = _wait_for_results(e, "b", 1, timeout=10)
        self.assertEqual(len(ra), 1)
        self.assertEqual(len(rb), 1)
        self.assertEqual(ra[0]["from"], "a")
        self.assertEqual(rb[0]["from"], "b")


# ---- Engine (priority) -----------------------------------------------


class TestEnginePriority(unittest.TestCase):
    """Optional priority parameter orders pending jobs."""

    def test_higher_priority_runs_before_lower(self):
        """High-priority pending jobs execute before low-priority pending ones."""
        _temp_step("""
            import time
            def run(pd, state, **p):
                time.sleep(0.15)
                pd["mark"] = pd["input"]["mark"]
                return pd
        """, name="prio_step")
        yaml = _temp_yaml("wf:\n  - prio_step:")
        from engine import Engine
        with Engine(max_concurrent=1) as e:
            e.register("test", yaml)
            # First submit grabs the only worker thread immediately.
            e.submit("test", {"mark": "blocker"})
            time.sleep(0.05)
            # The next 4 queue up while blocker is mid-flight.
            e.submit("test", {"mark": "low_a"}, priority=0)
            e.submit("test", {"mark": "low_b"}, priority=0)
            e.submit("test", {"mark": "high_a"}, priority=10)
            e.submit("test", {"mark": "high_b"}, priority=10)
            results = _wait_for_results(e, "test", 5, timeout=10)

        marks = [r["mark"] for r in results]
        self.assertEqual(len(marks), 5)
        self.assertEqual(marks[0], "blocker")
        # High-priority pending jobs come before low-priority pending ones.
        idx = {m: i for i, m in enumerate(marks)}
        self.assertLess(idx["high_a"], idx["low_a"])
        self.assertLess(idx["high_a"], idx["low_b"])
        self.assertLess(idx["high_b"], idx["low_a"])
        self.assertLess(idx["high_b"], idx["low_b"])
        # FIFO within same priority.
        self.assertLess(idx["high_a"], idx["high_b"])
        self.assertLess(idx["low_a"], idx["low_b"])

    def test_default_priority_preserves_fifo(self):
        """No priority specified -> submission order is preserved."""
        _temp_step("""
            def run(pd, state, **p):
                pd["i"] = pd["input"]["i"]
                return pd
        """, name="fifo_step")
        yaml = _temp_yaml("wf:\n  - fifo_step:")
        from engine import Engine
        with Engine(max_concurrent=1) as e:
            e.register("test", yaml)
            for i in range(5):
                e.submit("test", {"i": i})
            results = _wait_for_results(e, "test", 5, timeout=10)

        order = [r["i"] for r in results]
        self.assertEqual(order, [0, 1, 2, 3, 4])

    def test_scope_completion_does_not_block_lower_priority_phase0(self):
        _temp_step("""
            def run(pd, state, **p):
                pd["value"] = pd["input"]["value"]
                return pd
        """, name="priority_scoped_input")
        _temp_step("""
            def run(pd, state, **p):
                pd["total"] = sum(item["value"] for item in pd["results"])
                return pd
        """, name="priority_scoped_collect")
        yaml = _temp_yaml("""
            wf:
              - priority_scoped_input:
              - priority_scoped_collect:
                  scope: group
        """)
        from engine import Engine

        with Engine(max_concurrent=1) as e:
            e.register("test", yaml)
            e.submit(
                "test",
                {"value": 7},
                scope={"group": "G"},
                priority=-10,
                complete="group",
            )
            results = _wait_for_results(e, "test", 2, timeout=5)

        scoped = [result for result in results if result["_phase"] == 1]
        self.assertEqual(len(results), 2)
        self.assertEqual(len(scoped), 1)
        self.assertEqual(scoped[0]["total"], 7)


# ---- Package API -----------------------------------------------------


class TestPackageAPI(unittest.TestCase):

    def test_public_imports(self):
        from engine import Engine
        from engine import WorkerError, WorkerSpawnError
        from engine import WorkerCrashedError, StepExecutionError
        from engine import ScopeError

    def test_version(self):
        import engine
        self.assertEqual(engine.__version__, "4.0.0")

    def test_engine_in_all(self):
        import engine
        self.assertIn("Engine", engine.__all__)

    def test_no_run_pipeline(self):
        """v4 does not have run_pipeline."""
        import engine
        self.assertFalse(hasattr(engine, "run_pipeline"))

    def test_no_pipeline_engine(self):
        """v4 does not have PipelineEngine (renamed to Engine)."""
        import engine
        self.assertFalse(hasattr(engine, "PipelineEngine"))


if __name__ == "__main__":
    unittest.main()
