"""Run-scoped types shared by every pipeline step.

- `Config` is the immutable record of operator inputs, constructed once
  in the notebook config cell. Stage XY limits come from LAS X boundary
  markers by default; the `stage_*_um` cfg fields are an opt-in escape
  hatch when markers cannot be used. The physical envelope comes from
  `limits/.../defaults.json`; Step 2 writes the active working envelope
  to `limits/.../current.json`.
- `Context` is the mutable runtime state that steps read and update in
  place: connected LAS X client, run naming, scan-field geometry, focus
  map, per-step result handles, job-state cache.
- `LimitsContext` is a narrow subset constructed by `select_targets` so
  the selection step can do out-of-limits filtering without holding the
  full Context (and so tests can build one directly).
- `TargetState` records what happened during Step 5 (objective switch,
  post-switch z-galvo readback, drift) for the run summary.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Config:
    """Operator inputs -- constructed once in the notebook config cell.

    Stage XY limits come from boundary point markers placed in
    Navigator Expert (preferred); the physical envelope from
    `limits/.../defaults.json` is used as the safety ceiling. The cfg
    `stage_*_um` fields are an opt-in fallback only (escape hatch when LAS X
    markers cannot be used) -- the notebook does not surface them.

    Z-wide limits always come from `limits/.../defaults.json` (the physical
    envelope); there is no operator-typed override -- focus behaviour
    is controlled by the focus map in Step 3.
    """

    # Jobs
    acquisition_job: str
    target_job: str
    af_job: str

    # Paths + run identity
    analysis_repo: Path
    experiment: str               # operator-typed; output_root is derived as media_path/smart by driver

    # Optional behaviour flags (defaults)
    settle_after_job_switch_s: float = 3.0
    restore_template_after_af: bool = True
    restore_source_at_end: bool = True
    smoke_test_pipeline: bool = False

    # Per-tile / per-target / selection visualization for steps 3, 4, 5.
    # Set False for large runs (e.g. well plates) where rendering and
    # saving every tile/target is prohibitive. Step 2 plots are always
    # rendered -- they're once-per-run setup figures.
    visualize: bool = True

    # Simulation mode: when True, after each acquire_and_save
    # the saved canonical .ome.tiff's pixels are overwritten with mock
    # content (matched shape/dtype) -- gated by the per-frame
    # SystemTypeName=="SIMULATOR" allowlist (see pipeline/_hijack.py).
    # mock_image_source names the provider, e.g. "skimage_human_mitosis".
    #
    # This is the single dry-run mechanism. The engine always reads
    # from image_path; the hijack is what makes that file contain mock
    # content for a dry run.
    simulate: bool = False
    mock_image_source: str | None = None

    # Boundary marker margin (only consumed when markers are present)
    limit_margin_um: float = 500.0

    # Stage XY fallback (escape hatch -- prefer LAS X markers).
    # All four must be set together. They are validated against the
    # physical envelope from limits/.../defaults.json; a ValueError is raised if
    # any value falls outside.
    stage_x_min_um: float | None = None
    stage_x_max_um: float | None = None
    stage_y_min_um: float | None = None
    stage_y_max_um: float | None = None


@dataclass(frozen=True)
class LimitsContext:
    """Subset of Context needed for out-of-limits filtering during selection.

    Carved out so select_targets (in selection.py) can construct a tiny
    typed dependency without taking a full Context (which holds LAS X
    client, engine, etc.). Tests construct one directly.
    """
    calibration: dict
    stage_config: dict
    stage_limits: dict | None
    source_slot: int
    target_slot: int


@dataclass
class TargetState:
    """Run state for Step 5. Explicit model of what happened."""
    started: bool = False
    setup_stage: str | None = None
    setup_error: str | None = None
    post_switch_zgalvo_um: float | None = None
    zgalvo_read_error: str | None = None
    drift_um: float | None = None
    drift_warning: bool = False


@dataclass
class Context:
    """Mutable runtime state that pipeline helpers update in place.

    Contract: preflight returns a fully-validated Context. Every
    field declared here without a default value is a hard
    precondition for the rest of the pipeline. Optional fields
    (those with defaults) are populated by later steps.
    """

    cfg: Config
    client: Any
    hw: Any
    calibration: dict
    stage_config: dict
    engine: Any
    out_dir: Path                             # run.layout.run_dir
    run: Any                                  # driver.RunHandle (loosely typed to avoid driver import)
    templates_dir: Path                       # required after preflight
    source_slot: int                          # derived from acquisition_job in preflight
    target_slot: int                          # derived from target_job in preflight

    # Defaulted fields (populated during or after preflight):
    current_job: str = ""                     # "" forces first ensure_job_state to run
    stage_limits: dict | None = None          # active working envelope
    stage_limits_source: str | None = None    # driver LIMITS_SOURCE_* value
    scan_field: dict | None = None            # set in Step 2

    # Preflight telemetry (consumed by summary.json later)
    source_zgalvo_um: float = 0.0
    source_zgalvo_warning: bool = False
    cellpose_env_present: bool = False

    # Target run state (populated by Step 5)
    target_state: TargetState = field(default_factory=TargetState)

    _shutdown_done: bool = False

    def limits_context(self) -> LimitsContext:
        """Build a LimitsContext snapshot for selection.py consumers."""
        return LimitsContext(
            calibration=self.calibration,
            stage_config=self.stage_config,
            stage_limits=self.stage_limits,
            source_slot=self.source_slot,
            target_slot=self.target_slot,
        )

    def shutdown(self) -> None:
        """Idempotent shutdown. Safe to call multiple times.

        Scope: shuts down the analysis engine only. Does NOT disconnect
        the LAS X client; that resource is connected once per session
        (by pipeline.connect_lasx() before the first preflight()) and
        persists until the Python kernel restarts. To force a disconnect,
        restart the kernel.
        """
        if self._shutdown_done:
            return
        try:
            self.engine.shutdown(wait=False)
        except Exception as exc:
            print(f"[shutdown] engine.shutdown() raised: {exc}")
        self._shutdown_done = True
