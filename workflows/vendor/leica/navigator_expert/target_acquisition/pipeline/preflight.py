"""preflight(cfg, client) -- validate and configure a run.

pipeline.connect_lasx() owns the LAS X CAM API connect handshake (the
notebook calls connect_lasx() to obtain the client). preflight() then
receives an already-connected client and validates / configures
everything else; it does not open the client itself.

preflight() is re-run-safe in the same Python session: a module-level
_LAST_CTX reference holds the most recently returned ctx. On a second
call, the prior ctx is shut down before the new run begins, so the
operator can re-execute Cell 3 without a globals() guard.
"""
from __future__ import annotations

import atexit
import os
import sys
import time
import warnings
from pathlib import Path
from typing import Any

import navigator_expert.driver as drv

from .context import Config, Context
from ._job_state import ensure_job_state, _read_objective_slot
from ._logcapture import capture_console_deferred

ZGALVO_WARN_THRESHOLD_UM = 0.5
CELLPOSE_ENV_NAME = "lasxapi_extended"


# Module-level handle on the most recent ctx, used to make preflight()
# re-run-safe inside one Python session. Plain reference (no weakref):
# easier to reason about; the lifecycle is single-threaded and bounded
# to the kernel's lifetime.
_LAST_CTX: Context | None = None


def _shutdown_prior_ctx_if_any() -> None:
    """Re-run safety: if preflight() ran earlier in this Python session,
    shut down the prior ctx's engine before starting fresh.

    Called at the top of preflight(). Idempotent: clears the slot even
    if shutdown raises (so a single failure doesn't lock the slot).
    """
    global _LAST_CTX
    if _LAST_CTX is not None:
        prior = _LAST_CTX
        _LAST_CTX = None
        try:
            prior.shutdown()
        except Exception as exc:
            print(f"[preflight] prior ctx.shutdown() raised: {exc}")


def preflight(cfg: Config, client: Any) -> Context:
    """Step 0: prepare the world for the pipeline.

    Thin wrapper around `_preflight_impl`: tees console output to
    `initialization/logs/initialization.log` — buffered from the start,
    flushed once the run dir exists (`_cap.bind`). `connect_lasx()`
    runs in an earlier notebook cell, so connection output is not in
    scope.
    """
    with capture_console_deferred() as _cap:
        return _preflight_impl(cfg, client, _cap)


def _preflight_impl(cfg: Config, client: Any, _cap) -> Context:
    """Step 0: prepare the world for the pipeline.

    Args:
        cfg:    operator inputs (frozen).
        client: an already-connected LAS X CAM API client, usually returned
                by pipeline.connect_lasx(). preflight() validates and
                configures it; it does not open the client itself.

    Raises:
        RuntimeError: if LAS X is unreachable, job/slot validation fails,
                      or the analysis pipeline cannot register.
        FileNotFoundError: if the analysis repo / overview.yaml is missing.
    """
    # 0.0 -- re-run safety: tear down any prior ctx left over from an
    # earlier preflight() call in this Python session.
    _shutdown_prior_ctx_if_any()

    # 0.1 -- API mode (set if not already; harmless if notebook already did it)
    _ensure_cam_api_mode(client)

    # 0.2 -- verify the connection (connect_lasx already called .Connect)
    if not drv.ping(client):
        raise RuntimeError(
            "LAS X did not respond to ping. Check that LAS X is running "
            "with the CAM interface enabled, and that pipeline.connect_lasx() "
            "connected successfully."
        )

    # 0.3 -- calibration + stage config + hardware
    calibration = drv.load_calibration()
    stage_config = drv.load_stage_config()
    hw = drv.get_hardware_info(client)
    if not hw:
        raise RuntimeError("drv.get_hardware_info returned nothing.")

    # 0.4a -- derive objective slots from LAS X job settings
    source_slot, target_slot = _derive_slots(client, cfg, calibration)

    # 0.4b -- verify derived slots are physically installed
    if source_slot != target_slot:
        drv.validate_slots(hw, source_slot, [target_slot])

    # 0.5 -- boot engine (sys.path tweak so smart-analysis is importable)
    analysis_repo = Path(cfg.analysis_repo)
    if not analysis_repo.exists():
        raise FileNotFoundError(
            f"Config.analysis_repo does not exist: {analysis_repo}"
        )
    if str(analysis_repo) not in sys.path:
        sys.path.insert(0, str(analysis_repo))

    try:
        from workflows.target_acquisition.steps.pick_targets import (  # noqa: E402
            SUPPORTS_NONE_NPICKS,
        )
        if not SUPPORTS_NONE_NPICKS:
            raise RuntimeError
    except (ImportError, AttributeError, RuntimeError):
        raise RuntimeError(
            f"smart-analysis at {analysis_repo} does not support n_picks=None. "
            f"Update to the latest version."
        )

    from engine import Engine  # noqa: E402  -- imported after sys.path tweak

    engine = Engine()

    try:
        # 0.6a -- register overview pipeline
        overview_yaml = (
            analysis_repo
            / "workflows"
            / "target_acquisition"
            / "pipelines"
            / "overview.yaml"
        )
        if not overview_yaml.exists():
            raise FileNotFoundError(
                f"overview.yaml not found at {overview_yaml}. "
                f"Check Config.analysis_repo points at the smart-analysis repo "
                f"and that workflows/target_acquisition/pipelines/overview.yaml exists."
            )
        engine.register("overview", str(overview_yaml))

        # 0.6b -- env presence check (warn, don't abort)
        cellpose_env_present = _check_cellpose_env_present()

        # 0.6c -- locate ScanningTemplates dir; HARD-FAIL.
        templates_dir = drv.find_scanning_templates_dir()
        if templates_dir is None:
            raise RuntimeError(
                "drv.find_scanning_templates_dir() returned None. "
                "LAS X may not be installed/configured for this Windows "
                "user, or the kernel was launched without inheriting "
                "APPDATA. See navigator_expert.driver.find_scanning_templates_dir "
                "for the exact lookup logic."
            )

        # 0.6d -- optional synchronous smoke test (D9)
        if cfg.smoke_test_pipeline:
            _run_smoke_test(engine)

        # 0.7 -- run dir (driver derives output_root = media_path / "smart")
        run = drv.start_run(client, cfg.experiment)
        out_dir = run.layout.run_dir
        _cap.bind(
            run.layout.logs_dir("initialization") / "initialization.log"
        )

        # 0.8 -- construct Context (current_job="" forces ensure_job_state to run)
        ctx = Context(
            cfg=cfg,
            client=client,
            hw=hw,
            calibration=calibration,
            stage_config=stage_config,
            engine=engine,
            out_dir=out_dir,
            run=run,
            templates_dir=templates_dir,
            source_slot=source_slot,
            target_slot=target_slot,
            cellpose_env_present=cellpose_env_present,
        )

        # 0.9 -- select and verify source job (deterministic starting state)
        ensure_job_state(ctx, cfg.acquisition_job)

        # 0.10 -- read source z-galvo (AFTER job is ensured)
        source_zgalvo_um, source_zgalvo_warning = _read_source_zgalvo(
            client, cfg.acquisition_job
        )
        ctx.source_zgalvo_um = source_zgalvo_um
        ctx.source_zgalvo_warning = source_zgalvo_warning

    except Exception:
        try:
            engine.shutdown(wait=False)
        except Exception:
            pass
        raise

    # 0.11 -- idempotent shutdown hook
    atexit.register(ctx.shutdown)

    # 0.12 -- record this ctx so the next preflight() in this session
    # can tear it down (_shutdown_prior_ctx_if_any). atexit and _LAST_CTX
    # compose cleanly because ctx.shutdown() is idempotent.
    global _LAST_CTX
    _LAST_CTX = ctx

    print(
        f"[step 1] preflight ok\n"
        f"  templates_dir : {ctx.templates_dir}\n"
        f"  out_dir       : {ctx.out_dir}\n"
        f"  current_job   : {ctx.current_job}  (slot {ctx.source_slot})\n"
        f"  target_job    : {cfg.target_job}  (slot {ctx.target_slot})\n"
        f"  source z-galvo: {source_zgalvo_um:+.3f} um"
        f"{'  [WARN]' if source_zgalvo_warning else ''}\n"
        f"  cellpose env  : "
        f"{'present' if cellpose_env_present else 'NOT FOUND (ok for v0 stubs)'}"
    )
    return ctx


# ---------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------


def _derive_slots(
    client: Any, cfg: Config, calibration: dict,
) -> tuple[int, int]:
    """Read each job's objective slot from LAS X, validate against calibration."""

    # Role collision checks
    if cfg.acquisition_job == cfg.target_job:
        raise ValueError(
            f"acquisition_job and target_job are both {cfg.acquisition_job!r}. "
            f"They must be different jobs with different objectives.")
    if cfg.af_job == cfg.target_job:
        raise ValueError(
            f"af_job and target_job are both {cfg.target_job!r}. "
            f"The AF job must use the source objective, not the target.")

    source_slot = _read_objective_slot(client, cfg.acquisition_job)
    target_slot = _read_objective_slot(client, cfg.target_job)
    af_slot = _read_objective_slot(client, cfg.af_job)

    if af_slot != source_slot:
        raise RuntimeError(
            f"af_job {cfg.af_job!r} uses objective slot {af_slot}, but "
            f"acquisition_job {cfg.acquisition_job!r} uses slot {source_slot}. "
            f"The AF job must use the same objective as the acquisition job.")

    # Validate calibration has entries for both slots
    objectives = calibration.get("objectives", {})
    for slot, job in [(source_slot, cfg.acquisition_job),
                      (target_slot, cfg.target_job)]:
        if str(slot) not in objectives:
            available = sorted(int(s) for s in objectives)
            raise ValueError(
                f"Job {job!r} uses objective slot {slot}, but the "
                f"calibration has no entry for that slot. "
                f"Calibrated slots: {available}. "
                f"Run the calibration notebooks first and promote the config.")

    # Dry-run translation to verify calibration completeness
    drv.translate_xyz_between_objectives(
        0, 0, 0, calibration,
        from_slot=source_slot, to_slot=target_slot,
    )

    return int(source_slot), int(target_slot)


def _ensure_cam_api_mode(client: Any) -> None:
    """Set CAM-only API mode and a sane request delay if not already set."""
    try:
        mode_attr = client.PyApiSetApiInterfaceToUse.Model.ApiInterfaceToUse
        cam_only = type(mode_attr).Only_the_CAM_interface_is_used
        if mode_attr != cam_only:
            client.PyApiSetApiInterfaceToUse.Model.ApiInterfaceToUse = cam_only
        if getattr(client.PyApiClient, "DelayInMilliseconds", 0) < 300:
            client.PyApiClient.DelayInMilliseconds = 300
    except AttributeError:
        # Different LAS X build or a mock client; ping will decide.
        pass


def _read_source_zgalvo(client: Any, job: str) -> tuple[float, bool]:
    """Read z-galvo from the active job's settings; warn if non-zero."""
    try:
        settings = drv.get_job_settings(client, job)
        ch = drv.make_changeable_copy(settings)
        zgalvo_um = float(ch["zPosition"]["z-galvo"])
    except Exception as exc:
        warnings.warn(
            f"Could not read source z-galvo from job '{job}': {exc}. "
            f"Continuing without preflight z-galvo telemetry.",
            stacklevel=3,
        )
        return 0.0, False

    warn = abs(zgalvo_um) > ZGALVO_WARN_THRESHOLD_UM
    if warn:
        warnings.warn(
            f"Source z-galvo = {zgalvo_um:+.3f} um "
            f"(>{ZGALVO_WARN_THRESHOLD_UM} um). "
            f"For best accuracy, set z-galvo to 0 in LAS X and re-run. "
            f"Workflow will continue.",
            stacklevel=3,
        )
    return zgalvo_um, warn


def _check_cellpose_env_present() -> bool:
    """Cheap on-disk check for the cellpose env.

    Probes the usual conda *root* env vars (CONDA_ROOT / CONDA_PREFIX_1
    -- both point at the base install) *plus* the ZMB AppLocker
    install path (`C:\\ProgramData\\MinicondaZMB`). CONDA_PREFIX is
    intentionally NOT used: when an env is active it points at
    `<root>/envs/<active_env>`, where `<root>/envs/envs/<name>` would
    be looked up wrongly.

    v0 stubs run in the orchestrator env, so a miss is a warning,
    never an abort.
    """
    candidates: list[Path] = []
    for var in ("CONDA_ROOT", "CONDA_PREFIX_1"):
        val = os.environ.get(var)
        if val:
            candidates.append(Path(val))
    # ZMB-specific fallback (per AppLocker setup)
    candidates.append(Path(r"C:\ProgramData\MinicondaZMB"))

    for root in candidates:
        env_dir = root / "envs" / CELLPOSE_ENV_NAME
        if env_dir.exists():
            return True

    warnings.warn(
        f"Conda env '{CELLPOSE_ENV_NAME}' not found under any of: "
        f"{[str(c / 'envs' / CELLPOSE_ENV_NAME) for c in candidates]}. "
        f"v0 stubs do not need it; create it before wiring real "
        f"cellpose into segment_tile.",
        stacklevel=3,
    )
    return False


def _run_smoke_test(engine: Any, timeout_s: float = 30.0) -> None:
    """Submit one synthetic tile, drain the result, report failures.

    On timeout this **hard-fails** (and shuts down the engine) rather
    than continuing -- a late-completing smoke job would otherwise leak
    a result into Step 4's buffer. The smoke path is opt-in
    (`Config.smoke_test_pipeline=True`), so a hard fail is the right
    posture.

    Failures are cumulative in the Engine and cannot be removed; D19's
    `failure_count_before` snapshot (taken in Step 4 *after* preflight
    returns) is what excludes any pre-Step-4 entries from this run's
    accounting. We print + warn here so the operator sees them.
    """
    try:
        engine.submit("overview", {"image_path": "<smoke>"})
    except Exception as exc:
        # wait=False so a stuck submit cannot block our hard-fail
        try:
            engine.shutdown(wait=False)
        except Exception:
            pass
        raise RuntimeError(f"Smoke submit raised: {exc}") from exc

    start = time.time()
    drained_within_timeout = False
    while time.time() - start < timeout_s:
        s = engine.status("overview")
        if s["pending"] == 0 and s["running"] == 0:
            drained_within_timeout = True
            break
        time.sleep(0.1)

    if not drained_within_timeout:
        s = engine.status("overview")
        # wait=False so a stuck worker cannot block our hard-fail; the
        # default wait=True joins executor threads and would itself hang.
        try:
            engine.shutdown(wait=False)
        except Exception:
            pass
        raise RuntimeError(
            f"Smoke test did not drain within {timeout_s}s "
            f"(pending={s['pending']}, running={s['running']}). "
            f"Engine has been shut down (wait=False) to prevent a late "
            f"completion from leaking into Step 4. Disable smoke_test_pipeline "
            f"or investigate the engine, then re-run preflight."
        )

    # Drain any results so they cannot leak into Step 4
    drained = engine.results("overview")
    failures = engine.status("overview")["failures"]

    if failures:
        print(f"[preflight smoke] {len(failures)} failure(s):")
        for f in failures:
            print(f"  - step={f.get('step')!r} error={f.get('error')!r}")
        warnings.warn(
            f"Smoke test produced {len(failures)} failure(s). "
            f"They are historical and will not be counted in Step 4 "
            f"(D19's failure_count_before snapshot excludes them).",
            stacklevel=3,
        )
    else:
        print(f"[preflight smoke] ok ({len(drained)} result(s) drained)")
