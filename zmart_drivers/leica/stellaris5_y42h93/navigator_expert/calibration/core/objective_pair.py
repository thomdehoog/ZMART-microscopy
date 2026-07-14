"""Workflow: measure the translation between one objective pair.

Z translation is peak-to-peak between Brenner-fitted reference and
target focus stacks. The operator configures z-stack range / step /
sections in LAS X; this workflow only triggers acquisition and
analyzes what comes back. See CALIBRATION_REF_STACK_UPDATE_PLAN.md.

Five operator steps, each one workflow call:

1. ``start_session`` -- connect, record the source ``calibration.json``
   path (for report provenance), prepare folders.
2. ``measure_parfocality_reference`` -- under the reference objective,
   record home XY and home z-wide (diagnostic), trigger the configured
   reference z-stack, fit the Brenner peak ``focus_z_ref_um``. The
   workflow only *notes* the peak — it does not move z-wide; the
   operator manages z-wide manually until step 4.
3. ``measure_parfocality_target`` -- after the operator switches to
   the target objective, record ``z_post`` then trigger the configured
   target z-stack, fit ``focus_z_target_um``, compute
   ``translation_z_um = focus_z_target_um - focus_z_ref_um``. As in
   step 2, z-wide is not moved here.
4. ``measure_parcentricity_reference`` -- back at the reference
   objective: return to home XY + ``focus_z_ref_um`` and acquire a
   clean reference image.
5. ``measure_parcentricity_target_and_save`` -- after the operator
   switches to the target objective again, acquire at the post-switch
   XY (no return to home XY), register against the reference image,
   compute ``motor_shift_xy`` / ``correction_xy`` / ``translation_xy``,
   write the acquisition report unconditionally, and rebuild the
   session-level ``calibration.json`` from trusted acquisition reports.

The notebook owns the operator-facing markdown and one workflow call
per cell. This module owns LAS X I/O, schema construction, and
visualization.
"""

from __future__ import annotations

import json
import logging
import math
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

import navigator_expert as drv
from navigator_expert.algorithms import VOTING_METHODS, brenner, register_voting

from .common import (
    STAGING_SCHEMA_VERSION,
    SessionPaths,
    acquire_frame_to,
    acquire_stack_to,
    make_session_paths,
    move_xy_and_verify,
    move_zwide_and_verify,
    now_iso,
    plot_brenner_curve,
    plot_overlay,
    read_active_objective,
    read_job_geometry,
    read_selected_job_name,
    read_stack_z_positions,
    write_json_atomic,
)

_log = logging.getLogger(__name__)


@dataclass
class ObjectivePairSession:
    session_id: str
    acquisition_name: str
    paths: SessionPaths
    job_name: str
    client: Any
    from_objective: str | None
    to_objective: str | None
    calibration_name: str | None
    calibration_path: Path
    kind: str
    # Recorded when the reference XY image is acquired (Step 4). The
    # target XY image (Step 5) must match this pixel size so voting
    # registration sees the same scale on both sides.
    ref_xy_pixel_size_um: float | None = None
    home_xy: tuple[float, float] | None = None
    home_z: float | None = None
    z_post: float | None = None
    # Reference focus is the Brenner peak of the operator-configured
    # reference z-stack; home_z is recorded for diagnostics only.
    focus_z_ref_um: float | None = None
    focus_z_target_um: float | None = None
    xy_post: tuple[float, float] | None = None
    ref_image: np.ndarray | None = None
    target_image: np.ndarray | None = None
    corrected_target_image: np.ndarray | None = None
    ref_z_stack: np.ndarray | None = None
    ref_z_positions_um: list[float] | None = None
    ref_z_brenner: list[float] | None = None
    target_z_stack: np.ndarray | None = None
    target_z_positions_um: list[float] | None = None
    target_z_brenner: list[float] | None = None
    raw_files: dict[str, str] = field(default_factory=dict)
    exported_files: dict[str, str] = field(default_factory=dict)
    motor_shift_xy_um: tuple[float, float] | None = None
    motor_shift_z_um: float | None = None
    correction_xy_um: tuple[float, float] | None = None
    correction_z_um: float | None = None
    translation_xy_um: tuple[float, float] | None = None
    translation_z_um: float | None = None
    registration: dict | None = None
    config_written: bool = False
    failure_reason: str | None = None
    # Objective identities are read from the selected Navigator Expert job at
    # measurement time. The operator changes the objective; this workflow only
    # observes and verifies it.
    from_slot: int | None = None
    to_slot: int | None = None
    # {slot_index: objective name} read from the live microscope at start, so
    # the adopted calibration annotates each slot with the objective actually
    # fitted rather than inheriting stale names from the base config.
    hardware_objectives: dict[int, str] = field(default_factory=dict)
    # Wall-clock second the session was opened; the report records how long
    # the whole calibration took, from the first cell to the final save.
    started_at_s: float | None = None


# ---------------------------------------------------------------------
# start_session
# ---------------------------------------------------------------------


def start_session(
    *,
    session_id: str,
    reference_slot: int,
    acquisition_name: str = "objective-pair",
    job_name: str | None = None,
    sessions_root: str | Path | None = None,
    calibration_path: str | Path | None = None,
    calibration_name: str | None = None,
) -> ObjectivePairSession:
    # Objective identities are never typed in: the reference is configured by
    # its turret slot number and resolved to the microscope's own name below;
    # the target is read live when the operator has switched to it. The
    # session folder starts under the operator-provided acquisition name.
    kind = "objective_pair"

    from ...config.machine import MACHINE, validate_calibration_name

    if sessions_root is None:
        sessions_root = MACHINE.subsystem_root("calibration")
    acquisition_name = validate_calibration_name(acquisition_name)
    paths = make_session_paths(
        session_id,
        sessions_root,
        acquisition_name=acquisition_name,
    )

    if calibration_path is not None and calibration_name is not None:
        raise ValueError("pass either calibration_name or calibration_path, not both")
    if calibration_path is None:
        resolved_path = MACHINE.calibration_path(calibration_name).absolute()
    else:
        # absolute(), not resolve(): keep the operator's drive letter intact
        # for the report's source_calibration_file field.
        resolved_path = Path(calibration_path).absolute()

    from . import model as _calibration_model

    existing_config = _calibration_model.load_calibration(resolved_path)
    try:
        stored_reference_slot = _calibration_model.get_reference_slot(existing_config)
    except ValueError as exc:
        if "no reference objective" not in str(exc):
            raise
        stored_reference_slot = None
    # Any stored translation is measured machine state. Bundled defaults are
    # empty and therefore have no reference to protect.
    measured_slots = {
        int(slot)
        for slot, entry in (existing_config.get("objectives") or {}).items()
        if entry.get("translation_um") is not None
    }
    if (
        stored_reference_slot is not None
        and int(reference_slot) != stored_reference_slot
        and measured_slots
    ):
        raise ValueError(
            f"this calibration session already uses reference slot "
            f"{stored_reference_slot}, but the first cell configured "
            f"reference_slot={int(reference_slot)}. Either select/create a "
            f"different calibration session for the new reference objective, "
            f"or change reference_slot in the first cell to "
            f"{stored_reference_slot}. Calibration file: {resolved_path}"
        )
    client = drv.connect_python_client()
    # Calibration moves the stage through gated drv.move_* wrappers, so it
    # needs validated ProgramData limits exactly like any other session.
    limits_state = drv.connect_limits_handshake(client)
    if not limits_state.ok:
        raise RuntimeError(limits_state.error)
    hw = drv.get_hardware_info(client, mode="api")
    if hw is None:
        raise RuntimeError("get_hardware_info returned None; LAS X unreachable")
    if job_name is None:
        job_name = read_selected_job_name(client)
        print(f"Using active Navigator Expert job: {job_name}")

    # The names the microscope reports for each occupied slot — used to annotate
    # the adopted calibration so a named set never carries stale objective names.
    # Slots whose hardware record has no usable name are left out: an empty
    # name must never overwrite the human-set name already in the config.
    from ...commands import objectives as _objectives

    hardware_objectives = {
        slot: name
        for slot, entry in _objectives.objective_by_slot(hw).items()
        if (name := str(entry.get("name") or "").strip())
    }
    reference_slot = int(reference_slot)
    if reference_slot not in hardware_objectives:
        raise ValueError(
            f"reference objective slot {reference_slot} is not occupied; "
            f"available slots: {sorted(hardware_objectives)}"
        )
    from_objective = hardware_objectives[reference_slot]
    print(f"Configured reference objective: slot {reference_slot} — {from_objective}")

    # Calibration sits above orientation in the setup ladder: parcentricity XY
    # is measured in image space and only becomes a stage offset because saved
    # frames are already turned to stage axes. If orientation was never measured
    # (the shipped placeholder), warn — the XY result may come out rotated. This
    # is a soft check by design: a scope whose real turn is 0° is fine once
    # set_orientation has been run and adopted.
    _warn_if_orientation_unmeasured()

    return ObjectivePairSession(
        session_id=session_id,
        acquisition_name=acquisition_name,
        paths=paths,
        job_name=job_name,
        client=client,
        from_objective=from_objective,
        to_objective=None,  # read live from the microscope at the target steps
        calibration_name=calibration_name,
        calibration_path=resolved_path,
        kind=kind,
        from_slot=reference_slot,
        hardware_objectives=hardware_objectives,
        started_at_s=time.time(),
    )


def _read_active_objective(session: ObjectivePairSession) -> tuple[int, str]:
    """Read the selected job's objective identity without changing microscope state."""
    return read_active_objective(
        session.client, session.job_name, known_names=session.hardware_objectives
    )


def _observe_objective_for_step(session: ObjectivePairSession, role: str) -> tuple[int, str]:
    """Record or verify the active reference/target objective, then report it."""
    slot, name = _read_active_objective(session)
    if role == "reference":
        if session.from_slot is None:
            # start_session always configures the reference slot, so this can
            # only happen to a hand-built session object. Refuse rather than
            # silently adopting whatever objective happens to be active.
            raise RuntimeError(
                "this session has no configured reference objective slot; start "
                "the session with reference_slot set in the first cell"
            )
        if slot != session.from_slot:
            raise RuntimeError(
                f"wrong objective for reference step: expected slot {session.from_slot} "
                f"({session.from_objective}), got slot {slot} ({name})"
            )
        session.from_objective = name
        session.hardware_objectives[slot] = name
    elif role == "target":
        if session.from_slot is None:
            raise RuntimeError("measure the reference objective before the target objective")
        if session.to_slot is None:
            if slot == session.from_slot:
                raise RuntimeError(
                    f"target objective is still the reference objective: slot {slot} ({name}). "
                    "Switch only the objective, keep the Navigator Expert job unchanged, and retry."
                )
            session.to_slot = slot
            session.to_objective = name
            session.hardware_objectives[slot] = name
        elif slot != session.to_slot:
            raise RuntimeError(
                f"wrong objective for target step: expected slot {session.to_slot} "
                f"({session.to_objective}), got slot {slot} ({name})"
            )
    else:
        raise ValueError(f"unknown objective role {role!r}")
    print(f"{role.capitalize()} objective: slot {slot} — {name}")
    return slot, name


def _warn_if_orientation_unmeasured() -> None:
    """Warn when this microscope still carries the shipped orientation placeholder.

    Two signals, so the check survives hand edits and schema growth: a file
    that set_orientation adopted carries ``"measured": true`` (never warned),
    and the shipped placeholder carries a ``_notes`` marker instead (warned).
    A file with neither — e.g. one adopted before the ``measured`` marker
    existed — is trusted as measured, so upgrading the driver never starts
    warning on a rig that was already set up.
    """
    from ...config.machine import MACHINE

    try:
        raw = json.loads(MACHINE.orientation_path().read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 -- missing/unreadable orientation is handled elsewhere
        return
    if "_notes" in raw and not raw.get("measured"):
        _log.warning(
            "orientation has not been measured on this microscope yet (still the "
            "shipped placeholder). Calibration assumes saved frames are already "
            "turned to the stage axes; run orientation/notebooks/set_orientation.ipynb "
            "first, or the parcentricity XY offset may come out rotated."
        )


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _f(v: Any) -> float | None:
    """Coerce to float; map None / NaN / inf to None for strict JSON."""
    if v is None:
        return None
    fv = float(v)
    if not math.isfinite(fv):
        return None
    return fv


def _registration_for_report(vote: dict | None) -> dict | None:
    if vote is None:
        return None
    return {
        "image_shift_um": [_f(vote.get("dx_um")), _f(vote.get("dy_um"))],
        "trusted": bool(vote.get("trusted", False)),
        "confidence": int(vote.get("confidence", 0)),
        "agreeing": list(vote.get("agreeing", [])),
    }


# Stack edge slices are less reliable for focus fitting than interior
# slices. On LAS X stacks, slice 0 can arrive before its file is fully
# stable, and either edge can dominate the Brenner score without
# representing the true focal plane. Parfocality analysis therefore fits
# only the interior slices. The full stack and scores stay on the
# session so edge artifacts remain visible in reports.
_STACK_LEADING_SLICES_TO_SKIP = 1
_STACK_TRAILING_SLICES_TO_SKIP = 1
_MIN_FIT_SAMPLES = 3
_BACKLASH_PASSES = 5
_MIN_STACK_SECTIONS_FOR_FOCUS_FIT = (
    _STACK_LEADING_SLICES_TO_SKIP + _STACK_TRAILING_SLICES_TO_SKIP + _MIN_FIT_SAMPLES
)


def _uniform_z_step_um(z_values: np.ndarray) -> float:
    if len(z_values) < 2:
        raise RuntimeError(
            "z-stack focus fitting requires at least "
            f"{_MIN_STACK_SECTIONS_FOR_FOCUS_FIT} sections; got "
            f"{len(z_values)}."
        )
    steps = np.diff(z_values)
    if not np.allclose(steps, steps[0], rtol=1e-6, atol=1e-6):
        raise RuntimeError(
            "z-stack positions are not uniformly spaced; cannot apply "
            "parabolic focus fitting. Re-check the LAS X z-stack setup."
        )
    return float(steps[0])


def _fit_focus_z(z_values: np.ndarray, scores: list[float]) -> float:
    if len(z_values) != len(scores):
        raise RuntimeError(
            f"z-stack position count ({len(z_values)}) does not match "
            f"Brenner score count ({len(scores)})."
        )
    if len(z_values) < _MIN_STACK_SECTIONS_FOR_FOCUS_FIT:
        raise RuntimeError(
            "z-stack focus fitting requires at least "
            f"{_MIN_STACK_SECTIONS_FOR_FOCUS_FIT} sections because the "
            "workflow drops the first and last slices before fitting."
        )

    step = _uniform_z_step_um(z_values)
    lead = _STACK_LEADING_SLICES_TO_SKIP
    trail = _STACK_TRAILING_SLICES_TO_SKIP
    end = len(z_values) - trail
    return _parabolic_peak(z_values[lead:end], scores[lead:end], step)


def _parabolic_peak(z_values: np.ndarray, scores: list[float], z_step_um: float) -> float:
    i_peak = int(np.argmax(scores))
    n = len(z_values)
    if i_peak == 0 or i_peak == n - 1:
        # The operator configures the z-stack around the focal plane, so a
        # valid Brenner peak must be inside the stack. An edge peak means
        # either the first/last slice is an outlier (sensor artifact,
        # partially-written file, stale data) or the stack is not centered
        # on the focal plane. Either way the recorded focus would be wrong;
        # surface the failure rather than silently using a bogus value.
        raise RuntimeError(
            f"Brenner peak found at stack edge (slice {i_peak} of {n}, "
            f"z={float(z_values[i_peak])} um). The peak must be inside the "
            "stack. Likely causes: an artifact slice (often slice 0), or the "
            "stack is not centered on the focal plane. Refocus and re-run."
        )
    s0, s1, s2 = scores[i_peak - 1], scores[i_peak], scores[i_peak + 1]
    denom = s0 - 2.0 * s1 + s2
    if abs(denom) > 1e-12:
        delta = 0.5 * (s0 - s2) / denom
        return float(z_values[i_peak] + delta * z_step_um)
    return float(z_values[i_peak])


def _print_step5_summary(session, summary: dict) -> None:
    """Human-readable operator decision block for the final cell."""
    reg = summary.get("registration") or {}
    trusted = bool(reg.get("trusted"))
    confidence = int(reg.get("confidence", 0))
    shift = reg.get("image_shift_um") or [None, None]
    status = summary.get("status") or ("OK" if summary.get("config_written") else "FAILED")
    # Strip the appended reason: keep the status header short.
    header = status.split(" (", 1)[0]

    print(f"Objective pair calibration: {header}")
    print()
    print(
        f"  Pair:           slot {session.from_slot} ({session.from_objective}) -> "
        f"slot {session.to_slot} ({session.to_objective})"
    )
    state = "trusted" if trusted else "untrusted"
    print(f"  Voting:         {state} ({confidence}/{len(VOTING_METHODS)})")
    if trusted and shift[0] is not None and shift[1] is not None:
        print(f"  Image shift:    ({shift[0]:+.2f}, {shift[1]:+.2f}) um")
    tx = summary.get("translation_xy_um")
    tz = summary.get("translation_z_um")
    if tx is not None and tx[0] is not None and tx[1] is not None:
        print(f"  Translation XY: ({tx[0]:+.2f}, {tx[1]:+.2f}) um")
    if tz is not None:
        print(f"  Translation Z:  {tz:+.2f} um")
    print()
    if summary.get("config_written"):
        print("  Session calibration updated:")
        print(f"    {summary.get('config_path')}")
        print()
        print("  Run the adopt cell below to make it active.")
    else:
        print("  This acquisition was not added to the session calibration.")
        if session.failure_reason:
            print(f"  Reason: {session.failure_reason}")


# ---------------------------------------------------------------------
# Invalidation helpers
# ---------------------------------------------------------------------
#
# Every upstream rerun in a multi-step pipeline must invalidate the old
# report and compiled session calibration, then clear every downstream
# step that depended on what the rerun changed.


def _invalidate_compiled_calibration(session: ObjectivePairSession) -> None:
    (session.paths.reports_dir / f"{session.kind}_report.json").unlink(missing_ok=True)
    (session.paths.session_root / "calibration.json").unlink(missing_ok=True)
    session.config_written = False


def _clear_parcentricity_target(session: ObjectivePairSession) -> None:
    session.xy_post = None
    session.target_image = None
    session.corrected_target_image = None
    session.motor_shift_xy_um = None
    session.correction_xy_um = None
    session.translation_xy_um = None
    session.registration = None
    session.failure_reason = None
    session.raw_files.pop("target_xy", None)
    session.raw_files.pop("target_xy_corrected", None)
    session.exported_files.pop("target_xy", None)
    session.exported_files.pop("target_xy_corrected", None)
    # Keep disk state in sync with the session bookkeeping.
    shutil.rmtree(session.paths.data_dir / "target_xy", ignore_errors=True)
    shutil.rmtree(session.paths.data_dir / "target_xy_corrected", ignore_errors=True)


def _clear_parfocality_target(
    session: ObjectivePairSession,
    *,
    wipe_disk: bool,
) -> None:
    session.z_post = None
    session.focus_z_target_um = None
    session.target_z_stack = None
    session.target_z_positions_um = None
    session.target_z_brenner = None
    session.motor_shift_z_um = None
    session.correction_z_um = None
    session.translation_z_um = None
    for key in list(session.raw_files):
        if key.startswith("target_z_stack/"):
            del session.raw_files[key]
    for key in list(session.exported_files):
        if key.startswith("target_z_stack/"):
            del session.exported_files[key]
    if wipe_disk:
        # The acquisition folder represents the current measurement,
        # not every rerun. A smaller z-range rerun would
        # otherwise leave higher-index TIFFs from the previous run.
        shutil.rmtree(
            session.paths.data_dir / "target_z_stack",
            ignore_errors=True,
        )


def _clear_parcentricity_ref(session: ObjectivePairSession) -> None:
    session.ref_image = None
    session.ref_xy_pixel_size_um = None
    session.raw_files.pop("ref_xy", None)
    session.exported_files.pop("ref_xy", None)
    shutil.rmtree(session.paths.data_dir / "ref_xy", ignore_errors=True)


def _clear_parfocality_reference(
    session: ObjectivePairSession,
    *,
    wipe_disk: bool,
) -> None:
    session.ref_z_stack = None
    session.ref_z_positions_um = None
    session.ref_z_brenner = None
    session.focus_z_ref_um = None
    for key in list(session.raw_files):
        if key.startswith("ref_z_stack/"):
            del session.raw_files[key]
    for key in list(session.exported_files):
        if key.startswith("ref_z_stack/"):
            del session.exported_files[key]
    if wipe_disk:
        shutil.rmtree(
            session.paths.data_dir / "ref_z_stack",
            ignore_errors=True,
        )


# ---------------------------------------------------------------------
# measure_parfocality_reference
# ---------------------------------------------------------------------


def measure_parfocality_reference(
    session: ObjectivePairSession,
    *,
    z_positions_um: list[float] | None = None,
) -> ObjectivePairSession:
    # A 2a rerun invalidates every downstream step: target parfocality
    # (its math anchors on focus_z_ref_um), parcentricity reference
    # (its image is acquired at focus_z_ref_um), and parcentricity
    # target (it depends on translation_z_um). The compiled result is stale.
    _clear_parfocality_reference(session, wipe_disk=True)
    _clear_parfocality_target(session, wipe_disk=True)
    _clear_parcentricity_ref(session)
    _clear_parcentricity_target(session)
    _invalidate_compiled_calibration(session)
    session.home_xy = None
    session.home_z = None

    _observe_objective_for_step(session, "reference")

    try:
        from IPython.display import display
    except Exception:
        display = None

    xy = drv.get_xy(session.client, mode="api") or {}
    if "x_um" not in xy or "y_um" not in xy:
        raise RuntimeError(f"get_xy returned no readback: {xy}")
    session.home_xy = (float(xy["x_um"]), float(xy["y_um"]))
    # home_z is diagnostic -- the operator's approximate focus before
    # the reference stack runs. focus_z_ref_um is the load-bearing
    # value, fitted below.
    session.home_z = float(drv.read_zwide_um(session.client, session.job_name))

    stack = acquire_stack_to(
        session,
        "ref_z_stack",
        backlash_passes=_BACKLASH_PASSES,
    )
    session.ref_z_stack = stack

    positions = read_stack_z_positions(
        session.client,
        session.job_name,
        expected_slices=int(stack.shape[0]),
        override=z_positions_um,
    )
    session.ref_z_positions_um = positions

    scores = [float(brenner(stack[i])) for i in range(stack.shape[0])]
    if not all(math.isfinite(s) for s in scores):
        raise RuntimeError(
            "Brenner scores contain non-finite values; cannot fit focus "
            "peak. Likely cause: blank or corrupted slices in the z-stack. "
            "Re-check the LAS X stack configuration and channel intensity."
        )
    session.ref_z_brenner = scores

    z_arr = np.asarray(positions, dtype=float)
    focus_z = _fit_focus_z(z_arr, scores)
    session.focus_z_ref_um = focus_z

    # The workflow notes the Brenner peak but does not move z-wide.
    # The operator manages z-wide manually.

    fig = plot_brenner_curve(
        positions,
        scores,
        focus_z,
        focus_image=stack[int(np.argmin(np.abs(z_arr - focus_z)))],
    )
    if display is not None:
        display(fig)
    try:
        import matplotlib.pyplot as _plt

        _plt.close(fig)
    except Exception:
        pass

    return session


# ---------------------------------------------------------------------
# measure_parfocality_target
# ---------------------------------------------------------------------


def measure_parfocality_target(
    session: ObjectivePairSession,
    *,
    z_positions_um: list[float] | None = None,
) -> ObjectivePairSession:
    if session.focus_z_ref_um is None:
        raise RuntimeError(
            "measure_parfocality_reference must run before measure_parfocality_target"
        )

    # A 2b rerun changes translation_z_um (which 3b uses to park
    # z-wide before the target acquire), so 3b's outputs are stale.
    # 3a's ref_image is still valid -- home_xy and focus_z_ref_um are
    # unchanged. Wipe the on-disk z-stack so a smaller rerun cannot
    # leave stale higher-index TIFFs in the directory the report
    # points at.
    _clear_parfocality_target(session, wipe_disk=True)
    _clear_parcentricity_target(session)
    _invalidate_compiled_calibration(session)

    _observe_objective_for_step(session, "target")

    try:
        from IPython.display import display
    except Exception:
        display = None

    z_post = float(drv.read_zwide_um(session.client, session.job_name))
    session.z_post = z_post
    # motor_shift_z = post-switch z-wide minus reference focus peak.
    session.motor_shift_z_um = z_post - session.focus_z_ref_um

    stack = acquire_stack_to(
        session,
        "target_z_stack",
        backlash_passes=_BACKLASH_PASSES,
    )
    session.target_z_stack = stack

    positions = read_stack_z_positions(
        session.client,
        session.job_name,
        expected_slices=int(stack.shape[0]),
        override=z_positions_um,
    )
    session.target_z_positions_um = positions

    scores = [float(brenner(stack[i])) for i in range(stack.shape[0])]
    if not all(math.isfinite(s) for s in scores):
        raise RuntimeError(
            "Brenner scores contain non-finite values; cannot fit focus "
            "peak. Likely cause: blank or corrupted slices in the z-stack. "
            "Re-check the LAS X stack configuration and channel intensity."
        )
    session.target_z_brenner = scores

    z_arr = np.asarray(positions, dtype=float)
    focus_z = _fit_focus_z(z_arr, scores)
    session.focus_z_target_um = focus_z
    session.correction_z_um = focus_z - z_post
    # Peak-to-peak: translation_z_um = focus_target - focus_ref.
    # Equivalent to motor_shift_z + correction_z by construction.
    session.translation_z_um = focus_z - session.focus_z_ref_um

    # The workflow notes the Brenner peak but does not move z-wide.
    # The operator manages z-wide manually.

    fig = plot_brenner_curve(
        positions,
        scores,
        focus_z,
        focus_image=stack[int(np.argmin(np.abs(z_arr - focus_z)))],
    )
    if display is not None:
        display(fig)
    try:
        import matplotlib.pyplot as _plt

        _plt.close(fig)
    except Exception:
        pass

    print(
        f"Z-wide translation from {session.from_objective} to "
        f"{session.to_objective}: {session.translation_z_um:+.2f} µm"
    )
    return session


# ---------------------------------------------------------------------
# measure_parcentricity_reference
# ---------------------------------------------------------------------


def measure_parcentricity_reference(
    session: ObjectivePairSession,
) -> ObjectivePairSession:
    if session.home_xy is None or session.focus_z_ref_um is None:
        raise RuntimeError(
            "measure_parfocality_reference must run before measure_parcentricity_reference"
        )

    # A 3a rerun replaces ref_image, against which 3b registers. The
    # previous 3b vote, translation_xy, and compiled calibration are all
    # stale.
    _clear_parcentricity_ref(session)
    _clear_parcentricity_target(session)
    _invalidate_compiled_calibration(session)

    _observe_objective_for_step(session, "reference")

    move_xy_and_verify(session.client, *session.home_xy)
    # Park z-wide at the reference Brenner focus (measured in Step 2)
    # so the XY image is acquired at the best ref-objective focus.
    move_zwide_and_verify(
        session.client,
        session.job_name,
        session.focus_z_ref_um,
    )

    ref_image = acquire_frame_to(
        session,
        "ref_xy",
        backlash_passes=_BACKLASH_PASSES,
    )
    session.ref_image = ref_image

    # Record the ref XY pixel size. The target XY (Step 5) must be
    # acquired at the same pixel size so voting registration sees the
    # same scale on both sides.
    geom = read_job_geometry(session.client, session.job_name, ref_image)
    session.ref_xy_pixel_size_um = float(geom.pixel_size_um)

    print(f"Reference XY image acquired.  pixel size = {session.ref_xy_pixel_size_um:.4f} um")
    return session


# ---------------------------------------------------------------------
# measure_parcentricity_target_and_save
# ---------------------------------------------------------------------


def measure_parcentricity_target_and_save(
    session: ObjectivePairSession,
) -> dict:
    if session.home_xy is None or session.focus_z_ref_um is None:
        raise RuntimeError(
            "measure_parfocality_reference must run before measure_parcentricity_target_and_save"
        )
    if session.ref_image is None:
        raise RuntimeError(
            "measure_parcentricity_reference must run before measure_parcentricity_target_and_save"
        )
    if session.focus_z_target_um is None or session.translation_z_um is None:
        raise RuntimeError(
            "measure_parfocality_target must run before measure_parcentricity_target_and_save"
        )

    # Reset this step's outputs.
    session.xy_post = None
    session.target_image = None
    session.corrected_target_image = None
    session.motor_shift_xy_um = None
    session.correction_xy_um = None
    session.translation_xy_um = None
    session.registration = None
    session.config_written = False
    session.failure_reason = None
    session.raw_files.pop("target_xy", None)
    session.raw_files.pop("target_xy_corrected", None)
    session.exported_files.pop("target_xy", None)
    session.exported_files.pop("target_xy_corrected", None)
    shutil.rmtree(session.paths.data_dir / "target_xy", ignore_errors=True)
    shutil.rmtree(session.paths.data_dir / "target_xy_corrected", ignore_errors=True)

    # Unlink the stale report and compiled calibration BEFORE any driver call. 3b has nine
    # raisable call sites between here and the verdict-mirror block;
    # any of them firing on a rerun would otherwise leave the previous
    # run's objective config adoptable (Section 15 invariant).
    _invalidate_compiled_calibration(session)

    _observe_objective_for_step(session, "target")

    try:
        from IPython.display import display
    except Exception:
        display = None

    xy = drv.get_xy(session.client, mode="api") or {}
    if "x_um" not in xy or "y_um" not in xy:
        raise RuntimeError(f"get_xy returned no readback: {xy}")
    xy_post = (float(xy["x_um"]), float(xy["y_um"]))
    session.xy_post = xy_post
    session.motor_shift_xy_um = (
        xy_post[0] - session.home_xy[0],
        xy_post[1] - session.home_xy[1],
    )

    # Park z-wide at the target Brenner focus (measured in Step 3) so
    # the XY image is acquired at the best target-objective focus.
    move_zwide_and_verify(
        session.client,
        session.job_name,
        session.focus_z_target_um,
    )

    # IMPORTANT: do NOT return to home_xy. We measure at the post-switch
    # XY so the registration captures only the residual the firmware
    # left behind.
    target_image = acquire_frame_to(
        session,
        "target_xy",
        backlash_passes=_BACKLASH_PASSES,
    )
    session.target_image = target_image

    # Reference and target XY must be at the same scale so voting
    # registration sees identical magnification on both sides.
    if tuple(target_image.shape[-2:]) != tuple(session.ref_image.shape[-2:]):
        raise ValueError(
            f"target XY image shape {target_image.shape[-2:]} does not "
            f"match reference shape {session.ref_image.shape[-2:]}. "
            "Reference and target XY must be acquired at the same image size."
        )
    geom = read_job_geometry(session.client, session.job_name, target_image)
    target_pixel_size = float(geom.pixel_size_um)
    if session.ref_xy_pixel_size_um is None or not np.isclose(
        target_pixel_size, session.ref_xy_pixel_size_um, rtol=0, atol=1e-9
    ):
        raise ValueError(
            f"target XY pixel size {target_pixel_size} um does not match "
            f"reference pixel size {session.ref_xy_pixel_size_um} um. "
            "Reference and target XY must be acquired at the same zoom."
        )
    pixel_size_um = session.ref_xy_pixel_size_um

    vote = register_voting(
        session.ref_image,
        target_image,
        pixel_size_um,
    )
    session.registration = vote

    config_written = False
    if vote.get("trusted"):
        image_shift = np.array(
            [float(vote["dx_um"]), float(vote["dy_um"])],
            dtype=float,
        )
        # Calibration frames are acquired stage-aligned (the driver reorients
        # at save time per the rig's measured orientation), so the registered
        # image shift is already in the stage frame -- no rotation needed.
        correction_xy = image_shift
        translation_xy = np.asarray(session.motor_shift_xy_um, dtype=float) + correction_xy
        session.correction_xy_um = (
            float(correction_xy[0]),
            float(correction_xy[1]),
        )
        session.translation_xy_um = (
            float(translation_xy[0]),
            float(translation_xy[1]),
        )
        # Prove the correction with hardware: move the stage by the measured
        # residual and acquire another image. The plot below uses this real
        # acquisition; no pixels are shifted for display.
        move_xy_and_verify(
            session.client,
            xy_post[0] + session.correction_xy_um[0],
            xy_post[1] + session.correction_xy_um[1],
        )
        session.corrected_target_image = acquire_frame_to(
            session,
            "target_xy_corrected",
            backlash_passes=_BACKLASH_PASSES,
        )
        config_written = True
    else:
        session.failure_reason = "voting registration not trusted"

    overlay_shift = (float(vote["dx_um"]), float(vote["dy_um"])) if vote.get("trusted") else None
    fig = plot_overlay(
        session.ref_image,
        target_image,
        "Acquisition without correction",
        subtitle=(
            None
            if overlay_shift is None
            else f"Measured XY shift: ({overlay_shift[0]:+.2f}, {overlay_shift[1]:+.2f}) µm"
        ),
        corrected_target=session.corrected_target_image,
    )
    if display is not None:
        display(fig)
    try:
        import matplotlib.pyplot as _plt

        _plt.close(fig)
    except Exception:
        pass

    # Report -- always written, after every available field is populated.
    images = {}
    if "ref_xy" in session.raw_files:
        images["ref_xy"] = session.raw_files["ref_xy"]
    if "target_xy" in session.raw_files:
        images["target_xy"] = session.raw_files["target_xy"]
    if "target_xy_corrected" in session.raw_files:
        images["target_xy_corrected"] = session.raw_files["target_xy_corrected"]
    # Both z-stacks are referenced as directories rather than
    # enumerating every slice in the report.
    for dirname in ("ref_z_stack", "target_z_stack"):
        z_dir = session.paths.data_dir / dirname
        if z_dir.exists():
            images[dirname] = (
                str(z_dir.relative_to(session.paths.session_dir)).replace("\\", "/") + "/"
            )

    # source_calibration_file: record the absolute source we actually
    # used (current config or override). The operator-supplied path may
    # live outside the package tree, so the absolute string is the only
    # form that round-trips meaningfully.
    source_calibration_file = str(session.calibration_path)

    report = {
        "schema_version": STAGING_SCHEMA_VERSION,
        "kind": "objective_translation_report",
        "created_at": now_iso(),
        "calibration_file": "../calibration.json",
        "config_written": config_written,
        "source_calibration_file": source_calibration_file,
        "session_id": session.session_id,
        "acquisition_name": session.acquisition_name,
        "from_slot": session.from_slot,
        "to_slot": session.to_slot,
        "from_objective": session.from_objective,
        "to_objective": session.to_objective,
        "home_xy_um": [_f(session.home_xy[0]), _f(session.home_xy[1])],
        "home_z_um": _f(session.home_z),
        "focus_z_ref_um": _f(session.focus_z_ref_um),
        "xy_post_um": [_f(session.xy_post[0]), _f(session.xy_post[1])],
        "z_post_um": _f(session.z_post),
        "focus_z_target_um": _f(session.focus_z_target_um),
        "motor_shift_xy_um": [_f(session.motor_shift_xy_um[0]), _f(session.motor_shift_xy_um[1])],
        "motor_shift_z_um": _f(session.motor_shift_z_um),
        "correction_xy_um": (
            [_f(session.correction_xy_um[0]), _f(session.correction_xy_um[1])]
            if session.correction_xy_um is not None
            else None
        ),
        "correction_z_um": _f(session.correction_z_um),
        "translation_xy_um": (
            [_f(session.translation_xy_um[0]), _f(session.translation_xy_um[1])]
            if session.translation_xy_um is not None
            else None
        ),
        "translation_z_um": _f(session.translation_z_um),
        "registration": _registration_for_report(vote),
        "duration_s": (
            None
            if session.started_at_s is None
            else round(time.time() - float(session.started_at_s), 3)
        ),
        "brenner_ref": {
            "peak_z_um": _f(session.focus_z_ref_um),
            "scores": [_f(s) for s in (session.ref_z_brenner or [])],
            "z_positions_um": [_f(z) for z in (session.ref_z_positions_um or [])],
        },
        "brenner_target": {
            "peak_z_um": _f(session.focus_z_target_um),
            "scores": [_f(s) for s in (session.target_z_brenner or [])],
            "z_positions_um": [_f(z) for z in (session.target_z_positions_um or [])],
        },
        "images": images,
    }
    report_out = session.paths.reports_dir / f"{session.kind}_report.json"
    write_json_atomic(report_out, report)

    config_path: str | None = None
    if config_written:
        from .adopt import compile_session_calibration

        config_path = str(compile_session_calibration(session))
        session.config_written = True
    else:
        session.config_written = False

    if config_written:
        status = "OK -- session calibration updated"
    else:
        status = "WEAK VOTE -- report only"
        if session.failure_reason:
            status = f"{status} ({session.failure_reason})"

    summary = {
        "config_written": config_written,
        "config_path": config_path,
        "report_path": str(report_out),
        "session_id": session.session_id,
        "acquisition_name": session.acquisition_name,
        "from_slot": session.from_slot,
        "to_slot": session.to_slot,
        "from_objective": session.from_objective,
        "to_objective": session.to_objective,
        "motor_shift_xy_um": [_f(session.motor_shift_xy_um[0]), _f(session.motor_shift_xy_um[1])],
        "motor_shift_z_um": _f(session.motor_shift_z_um),
        "correction_xy_um": (
            [_f(session.correction_xy_um[0]), _f(session.correction_xy_um[1])]
            if session.correction_xy_um is not None
            else None
        ),
        "correction_z_um": _f(session.correction_z_um),
        "translation_xy_um": (
            [_f(session.translation_xy_um[0]), _f(session.translation_xy_um[1])]
            if session.translation_xy_um is not None
            else None
        ),
        "translation_z_um": _f(session.translation_z_um),
        "focus_z_ref_um": _f(session.focus_z_ref_um),
        "focus_z_target_um": _f(session.focus_z_target_um),
        "registration": {
            "trusted": bool(vote.get("trusted", False)),
            "confidence": int(vote.get("confidence", 0)),
            "image_shift_um": [_f(vote.get("dx_um")), _f(vote.get("dy_um"))],
        },
        "status": status,
    }
    _print_step5_summary(session, summary)
    return summary


def measure(session: ObjectivePairSession) -> dict | None:
    """Run the next unfinished measurement step.

    The active objective still has to match the notebook instruction. This
    function only removes the need to remember four different method names.
    """
    if session.focus_z_ref_um is None:
        measure_parfocality_reference(session)
        return None
    if session.focus_z_target_um is None:
        measure_parfocality_target(session)
        return None
    if session.ref_image is None:
        measure_parcentricity_reference(session)
        return None
    return measure_parcentricity_target_and_save(session)
