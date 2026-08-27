"""
Pipeline Engine v4 -- Simplified orchestrator with scoped execution.

Runs YAML-defined workflows where every step executes in a worker subprocess.
Supports scoped triggering, per-step concurrency (max_workers), priority
scheduling, and system-wide observability.

API
---
    from engine import Engine

    engine = Engine()
    engine.register("overview", "overview_pipeline.yaml")
    engine.submit("overview", data, scope={"group": "R3"})
    engine.submit("overview", data, scope={"group": "R3"}, complete="group")
    results = engine.results("overview")
    engine.shutdown()

Architecture
------------
    _loader.py        AST-based METADATA extraction (no code execution)
    _run.py           Internal pipeline state, scope tracking, YAML parsing
    _pipeline.py      Engine orchestrator (register, submit, status, results)
    _pool.py          WorkerPool with per-env pools and per-step concurrency
    _worker.py        Per-environment subprocess lifecycle
    worker_script.py  Runs inside target conda env (self-contained)
    _errors.py        WorkerError + ScopeError hierarchies
"""

from ._pipeline import Engine
from ._errors import (
    WorkerError,
    WorkerSpawnError,
    WorkerCrashedError,
    WorkerTimeoutError,
    StepExecutionError,
    ScopeError,
)

__version__ = "4.0.0"
__all__ = [
    "Engine",
    "WorkerError",
    "WorkerSpawnError",
    "WorkerCrashedError",
    "WorkerTimeoutError",
    "StepExecutionError",
    "ScopeError",
]
