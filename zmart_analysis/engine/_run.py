"""
Internal pipeline state and YAML parsing.

Not part of the public API. Used by the Engine to manage registered
pipelines, track jobs, handle scope completion, and accumulate results.

Phases
------
A pipeline's step list is split into phases at scope boundaries:

    Phase 0 (immediate):   preprocess -> segment     [runs per job]
    -- scope: group --
    Phase 1 (scoped):      stitch -> features         [runs once per group]
    -- scope: all --
    Phase 2 (scoped):      normalize                   [runs once for all]

Phase 0 has no scope trigger -- it runs immediately when a job is submitted.
Subsequent phases wait for scope completion signals.

Scope matching
--------------
When complete="X" is signaled from a submit with scope={"X": val}:
  - If "X" is a key in jobs' scope dicts: match by value (scope["X"] == val)
  - If "X" is not a key: collect everything from the previous phase

This means "all" is not special -- it works because no job has "all" as a
scope key, so the engine collects everything.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


# -- Data structures ---------------------------------------------------


@dataclass
class StepConfig:
    """Configuration for one step in a pipeline phase."""
    name: str
    params: dict


@dataclass
class Phase:
    """A group of sequential steps with an optional scope trigger."""
    steps: list
    scope: str | None = None


# -- YAML parsing ------------------------------------------------------


def parse_yaml(yaml_path):
    """
    Parse a pipeline YAML file.

    Returns
    -------
    tuple of (workflow_name, steps_config, metadata)
    """
    yaml_path = Path(yaml_path)
    with open(yaml_path) as f:
        config = yaml.safe_load(f)

    metadata = config.get("metadata", {})

    workflow_name = None
    for key in config:
        if key != "metadata":
            workflow_name = key
            break

    if not workflow_name:
        raise ValueError(
            "No workflow found in YAML (need a key other than 'metadata')"
        )

    steps = config[workflow_name] or []
    if not steps:
        raise ValueError(f"Workflow '{workflow_name}' has no steps")

    return workflow_name, steps, metadata


def split_phases(steps_config):
    """
    Split a flat step list into phases at scope boundaries.

    A new phase starts when a step declares a scope. Steps before the
    first scope are Phase 0 (immediate). Each subsequent scope starts
    a new phase.
    """
    phases = []
    current_steps = []
    current_scope = None

    for step_dict in steps_config:
        name = list(step_dict.keys())[0]
        raw_params = dict(step_dict[name] or {})
        scope = raw_params.pop("scope", None)

        if scope is not None:
            if current_steps:
                phases.append(Phase(steps=current_steps, scope=current_scope))
            current_steps = []
            current_scope = scope

        current_steps.append(StepConfig(name=name, params=raw_params))

    if current_steps:
        phases.append(Phase(steps=current_steps, scope=current_scope))

    return phases


# -- Pipeline state ----------------------------------------------------


class PipelineState:
    """
    Internal state for one registered pipeline.

    Tracks jobs, scope groups, result accumulation, and status counters.
    Thread-safe: all mutable state is protected by _lock.
    """

    def __init__(self, name, yaml_path, phases, functions_dir,
                 step_settings, verbose):
        self.name = name
        self.yaml_path = Path(yaml_path)
        self.phases = phases
        self.functions_dir = functions_dir
        self.step_settings = step_settings
        self.verbose = verbose
        self.workflow_name = name

        self._lock = threading.Lock()
        self._submission_counter = 0

        # Job tracking: [(future, scope_dict, submission_idx)]
        self._job_entries = []

        # Phase 0 results: [(submission_idx, scope_dict, result)]
        self._phase0_results = []

        # Phase N>0 results: phase_idx -> [result]
        self._phase_results = defaultdict(list)

        # Completed results queue (drained by engine.results())
        self._results_queue = queue.Queue()

        # Status counters. The failed count is always derived from
        # _failures so the two cannot drift apart when scope collection
        # drains consumed failures.
        self._n_submitted = 0
        self._n_pending = 0
        self._n_running = 0
        self._n_completed = 0
        self._failures = []

    def next_submission_idx(self):
        """Get the next submission index (thread-safe)."""
        with self._lock:
            idx = self._submission_counter
            self._submission_counter += 1
            self._n_submitted += 1
            self._n_pending += 1
            return idx

    def add_job_entry(self, future, scope, submission_idx):
        """Record a submitted job's future and scope."""
        with self._lock:
            self._job_entries.append((future, scope, submission_idx))
        future.add_done_callback(
            lambda done: self.record_cancellation(scope)
            if done.cancelled() else None
        )

    def record_start(self, is_submission=True):
        """Move an operation from pending to running."""
        with self._lock:
            if is_submission:
                self._n_pending = max(0, self._n_pending - 1)
            self._n_running += 1

    def store_phase0_result(self, submission_idx, scope, result):
        """Store a Phase 0 result for later scope collection."""
        with self._lock:
            self._phase0_results.append((submission_idx, scope, result))

    def publish_result(self, result, phase_idx, scope, scope_level):
        """Put a completed result in the results queue."""
        result["_phase"] = phase_idx
        result["_scope"] = scope
        result["_scope_level"] = scope_level
        self._results_queue.put(result)

    def record_completion(self):
        """Record that a job/phase completed successfully."""
        with self._lock:
            self._n_running = max(0, self._n_running - 1)
            self._n_completed += 1

    def record_failure(self, scope, step_name, error_msg):
        """Record a job failure."""
        with self._lock:
            self._n_running = max(0, self._n_running - 1)
            self._failures.append({
                "scope": scope,
                "step": step_name,
                "error": error_msg,
            })

    def record_cancellation(self, scope):
        """Record a queued submission cancelled during engine shutdown."""
        with self._lock:
            self._n_pending = max(0, self._n_pending - 1)
            self._failures.append({
                "scope": scope,
                "step": "engine",
                "error": "Cancelled during engine shutdown",
            })

    def get_triggered_phase_idx(self, level):
        """Find the phase index triggered by a scope level."""
        for i, phase in enumerate(self.phases):
            if phase.scope == level:
                return i
        return None

    def collect_for_scope(self, phase_idx, level, value):
        """
        Collect results from the previous phase for a triggered scope.

        For Phase 1 (prev=0): collects from Phase 0 results.
        For Phase N (prev=N-1): collects from phase_results[N-1].

        Returns (results, failures) where results is a list sorted by
        submission order and failures is a list of failure info dicts.
        """
        prev_idx = phase_idx - 1

        with self._lock:
            if prev_idx == 0:
                return self._collect_phase0(level, value)
            else:
                results = list(self._phase_results[prev_idx])
                self._phase_results[prev_idx].clear()
                return results, []

    def _collect_phase0(self, level, value):
        """Collect Phase 0 results matching scope criteria.

        Must be called under _lock.
        """
        if value is not None:
            matching = []
            remaining = []
            for entry in self._phase0_results:
                idx, scope, result = entry
                if scope.get(level) == value:
                    matching.append((idx, result))
                else:
                    remaining.append(entry)
            self._phase0_results = remaining
        else:
            matching = [(idx, r) for idx, _, r in self._phase0_results]
            self._phase0_results = []

        matching.sort(key=lambda x: x[0])
        results = [r for _, r in matching]

        # Collect failures for matching scope
        failures = []
        remaining_failures = []
        for f in self._failures:
            if value is not None and f["scope"].get(level) == value:
                failures.append(f)
            elif value is None:
                failures.append(f)
            else:
                remaining_failures.append(f)
        self._failures = remaining_failures

        return results, failures

    def store_phase_result(self, phase_idx, result):
        """Store a scoped phase result for the next phase."""
        with self._lock:
            self._phase_results[phase_idx].append(result)

    def get_matching_futures(self, level, value):
        """Get Phase 0 futures matching a scope level and value."""
        with self._lock:
            if value is not None:
                return [
                    f for f, scope, _ in self._job_entries
                    if scope.get(level) == value
                ]
            else:
                return [f for f, _, _ in self._job_entries]

    def cleanup_consumed_entries(self, level, value):
        """Remove consumed job entries after scope collection."""
        with self._lock:
            if value is not None:
                self._job_entries = [
                    (f, s, idx) for f, s, idx in self._job_entries
                    if s.get(level) != value
                ]
            else:
                self._job_entries = []

    def drain_results(self):
        """Drain and return all completed results."""
        results = []
        while True:
            try:
                results.append(self._results_queue.get_nowait())
            except queue.Empty:
                break
        return results

    @property
    def status(self):
        """Current pipeline state for observability."""
        with self._lock:
            return {
                "pending": self._n_pending,
                "running": self._n_running,
                "completed": self._n_completed,
                "failed": len(self._failures),
                "failures": list(self._failures),
            }
