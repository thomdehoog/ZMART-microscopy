"""preflight(cfg, client) -- Step 0 of the design.

Substeps 0.1-0.8 per TARGET_ACQUISITION_DESIGN.md section 7.
The notebook owns the LAS X connect handshake; preflight receives
an already-connected client and validates / configures everything
else.
"""
from __future__ import annotations

import atexit
import os
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any

import navigator_expert.driver as drv

from .context import Config, Context

ZGALVO_WARN_THRESHOLD_UM = 0.5
CELLPOSE_ENV_NAME = "SMART--target_acquisition--main"


def preflight(cfg: Config, client: Any) -> Context:
    """Step 0: prepare the world for the workflow.

    Args:
        cfg:    operator inputs (frozen).
        client: an already-connected LAS X CAM API client.
                The notebook is responsible for the connect handshake.

    Raises:
        RuntimeError: if LAS X is unreachable, slot validation fails,
                      or the analysis pipeline cannot register.
        FileNotFoundError: if the analysis repo / overview.yaml is missing.
    """
    # 0.1 -- API mode (set if not already; harmless if notebook already did it)
    _ensure_cam_api_mode(client)

    # 0.2 -- verify the connection (notebook already called .Connect)
    if not drv.ping(client):
        raise RuntimeError(
            "LAS X did not respond to ping. Check that LAS X is running "
            "with the CAM interface enabled, and that the notebook called "
            "client.Connect(...) successfully."
        )

    # 0.3 -- calibration + stage config + hardware
    calibration = drv.load_calibration()
    stage_config = drv.load_stage_config()
    hw = drv.get_hardware_info(client)
    if not hw:
        raise RuntimeError("drv.get_hardware_info returned nothing.")
    drv.validate_slots(hw, cfg.source_slot, [cfg.target_slot])

    # 0.4 -- force source objective for deterministic starting state
    set_result = drv.set_objective(
        client,
        cfg.acquisition_job,
        hw,
        slot_index=cfg.source_slot,
    )
    if not set_result or not set_result.get("success"):
        raise RuntimeError(
            f"drv.set_objective(slot={cfg.source_slot}) failed: {set_result!r}. "
            f"Check that the objective is installed in slot {cfg.source_slot} "
            f"and that the LRP allows objective changes."
        )
    # let the firmware settle parfocal motor + objective turret before
    # we read job settings or use the stage further
    time.sleep(cfg.settle_after_objective_switch_s)

    # 0.5 -- read source z-galvo, warn if non-zero (D3)
    source_zgalvo_um, source_zgalvo_warning = _read_source_zgalvo(
        client, cfg.acquisition_job
    )

    # 0.6a -- boot engine (sys.path tweak so smart-analysis is importable)
    analysis_repo = Path(cfg.analysis_repo)
    if not analysis_repo.exists():
        raise FileNotFoundError(
            f"Config.analysis_repo does not exist: {analysis_repo}"
        )
    if str(analysis_repo) not in sys.path:
        sys.path.insert(0, str(analysis_repo))

    from engine import Engine  # noqa: E402  -- imported after sys.path tweak

    engine = Engine()

    # 0.6b -- register overview pipeline
    overview_yaml = (
        analysis_repo
        / "workflows"
        / "target_acquisition"
        / "pipelines"
        / "overview.yaml"
    )
    if not overview_yaml.exists():
        engine.shutdown()
        raise FileNotFoundError(
            f"overview.yaml not found at {overview_yaml}. "
            f"Check Config.analysis_repo points at the smart-analysis repo "
            f"and that workflows/target_acquisition/pipelines/overview.yaml exists."
        )
    try:
        engine.register("overview", str(overview_yaml))
    except Exception:
        engine.shutdown()
        raise

    # 0.6c -- env presence check (warn, don't abort)
    cellpose_env_present = _check_cellpose_env_present()

    # 0.6d -- locate ScanningTemplates dir; HARD-FAIL.
    # ctx.templates_dir is guaranteed non-None after preflight.
    templates_dir = drv.find_scanning_templates_dir()
    if templates_dir is None:
        try:
            engine.shutdown(wait=False)
        except Exception:
            pass
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

    # 0.7 -- atexit hook is registered after ctx is constructed (below)

    # 0.8 -- output dir
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(cfg.output_root) / timestamp
    (out_dir / "overview").mkdir(parents=True, exist_ok=True)
    (out_dir / "target").mkdir(parents=True, exist_ok=True)
    (out_dir / "logs").mkdir(parents=True, exist_ok=True)

    ctx = Context(
        cfg=cfg,
        client=client,
        hw=hw,
        calibration=calibration,
        stage_config=stage_config,
        engine=engine,
        out_dir=out_dir,
        current_job=cfg.acquisition_job,
        templates_dir=templates_dir,
        source_zgalvo_um=source_zgalvo_um,
        source_zgalvo_warning=source_zgalvo_warning,
        cellpose_env_present=cellpose_env_present,
    )

    # 0.7 (now) -- idempotent shutdown hook
    atexit.register(ctx.shutdown)

    print(
        f"[preflight] ok\n"
        f"  templates_dir : {ctx.templates_dir}\n"
        f"  out_dir       : {ctx.out_dir}\n"
        f"  current_job   : {ctx.current_job}  (slot {cfg.source_slot})\n"
        f"  source z-galvo: {source_zgalvo_um:+.3f} um"
        f"{'  [WARN]' if source_zgalvo_warning else ''}\n"
        f"  cellpose env  : "
        f"{'present' if cellpose_env_present else 'NOT FOUND (ok for v0 stubs)'}"
    )
    return ctx


# ---------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------


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
