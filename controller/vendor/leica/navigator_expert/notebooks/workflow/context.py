"""Config (immutable operator inputs) + Context (mutable runtime state).

Per TARGET_ACQUISITION_DESIGN.md D11 / section 5.1.
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
    `stage.json` is used as the safety ceiling. The cfg `stage_*_um`
    fields are an opt-in fallback only (escape hatch when LAS X
    markers cannot be used) -- the notebook does not surface them.

    Z-wide limits always come from `stage.json` (the physical
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
    fov_bbox_margin: float = 1.5
    settle_after_job_switch_s: float = 3.0
    restore_template_after_af: bool = True
    restore_source_at_end: bool = True
    smoke_test_pipeline: bool = False

    # Simulation mode (Plan 2): when True, after each acquire_and_save
    # the saved canonical .ome.tiff's pixels are overwritten with mock
    # content (matched shape/dtype) -- gated by the per-frame
    # SystemTypeName=="SIMULATOR" allowlist (see workflow/_hijack.py).
    # mock_image_source names the provider, e.g. "skimage_human_mitosis".
    #
    # This is the single dry-run mechanism. The pre-Plan-2
    # cfg.analysis_image_source knob (which used to branch the
    # engine's image read between "acquired" and a hardcoded
    # skimage source) was removed by the Plan 2 §6 / D1 cleanup --
    # the engine now always reads from image_path, and the hijack
    # is what makes that file contain mock content for a dry run.
    simulate: bool = False
    mock_image_source: str | None = None

    # Boundary marker margin (only consumed when markers are present)
    limit_margin_um: float = 500.0

    # Stage XY fallback (escape hatch -- prefer LAS X markers).
    # All four must be set together. They are validated against the
    # physical envelope from stage.json; a ValueError is raised if
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
    boundary_limits: dict | None
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
    """Mutable runtime state that workflow helpers update in place.

    Contract: preflight returns a fully-validated Context. Every
    field declared here without a default value is a hard
    precondition for the rest of the workflow. Optional fields
    (those with defaults) are populated by later steps.
    """

    cfg: Config
    client: Any
    hw: Any
    calibration: dict
    stage_config: dict
    engine: Any
    out_dir: Path                             # == run.layout.run_dir; kept for compat
    run: Any                                  # driver.RunHandle (loosely typed to avoid driver import)
    templates_dir: Path                       # required after preflight (D9)
    source_slot: int                          # derived from acquisition_job in preflight
    target_slot: int                          # derived from target_job in preflight

    # Defaulted fields (populated during or after preflight):
    current_job: str = ""                     # "" forces first ensure_job_state to run
    boundary_limits: dict | None = None       # set in Step 1
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
            boundary_limits=self.boundary_limits,
            source_slot=self.source_slot,
            target_slot=self.target_slot,
        )

    def shutdown(self) -> None:
        """Idempotent shutdown (D20). Safe to call multiple times.

        Scope: shuts down the analysis engine only. Does NOT disconnect
        the LAS X client; that resource is connected once per session
        (by workflow.connect_lasx() before the first preflight()) and
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
