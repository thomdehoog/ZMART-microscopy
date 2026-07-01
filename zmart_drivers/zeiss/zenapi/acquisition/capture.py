"""Microscope acquisition only.

    acq = acquire(client, experiment)

``acquire`` runs a loaded ZEN experiment (or a snap) to completion and returns
a save-agnostic context; it does not touch files. ``acquisition.save.save``
persists the CZI ZEN wrote.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from ..commands import commands as _commands


@dataclass(frozen=True)
class AcquisitionResult:
    """Save-agnostic result of one ZEN acquisition."""

    experiment_id: str
    output_name: str | None
    started_at: float
    finished_at: float
    command_result: dict


def acquire(client: Any, experiment: Any, *, mode: str = "experiment", **kwargs) -> AcquisitionResult:
    """Acquire ``experiment`` and return save-agnostic context.

    ``mode="experiment"`` runs the full experiment (a CZI is written on the ZEN
    side); ``mode="snap"`` acquires a single snap. Raises ``RuntimeError`` if the
    command did not succeed.
    """
    started_at = time.time()
    if mode == "snap":
        result = _commands.run_snap(client, experiment, **kwargs)
        output_name = None
    elif mode == "experiment":
        result = _commands.run_experiment(client, experiment, **kwargs)
        output_name = result.get("output_name")
    else:
        raise ValueError(f"Unknown acquire mode {mode!r}. Use 'experiment' or 'snap'.")
    finished_at = time.time()

    if not result or not result.get("success"):
        raise RuntimeError(f"acquire failed: {result}")

    return AcquisitionResult(
        experiment_id=getattr(experiment, "experiment_id", experiment),
        output_name=output_name,
        started_at=started_at,
        finished_at=finished_at,
        command_result=result,
    )
