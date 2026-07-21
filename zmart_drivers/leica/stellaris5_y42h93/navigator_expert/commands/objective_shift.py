"""Keep the sample point when a job or objective change swaps the lens.

A Navigator Expert job carries its own objective choice, so changing the job
can change the objective with it; changing the objective does so by
definition. The stage does not move on its own during either change, but the
new objective looks at a different spot (parcentricity) and a different focal
plane (parfocality). The adopted objective-pair calibration records exactly
that difference per lens, so the driver can keep the operator's sample point.
The order is the whole point:

1. BEFORE the change, record the motoric XY and z-wide positions — while
   they still mean "where the old objective was looking" — and which
   objective is in (:func:`record_before_change`).
2. Perform the change (the command wrapper does this as usual).
3. If the objective changed, add the difference between the two lenses'
   calibration translations to the recorded values and move there
   (:func:`compensate_after_change`).

A later frame move to the same coordinates computes the identical absolute
target — the adapter's per-move compensation uses the same translation table
relative to the origin's objective — so nothing is ever compensated twice.

This lives in the command layer, below the controller adapter, so EVERY
driver-performed job or objective change is covered no matter who asked for
it — but the behaviour is explicit, not hidden: ``set_objective`` and
``select_job`` take a ``compensate`` parameter (decision §8). The default
follows the session's connect-time policy from the per-connection config
(:mod:`navigator_expert.connection.session_state`): compensation runs when
calibration was loaded, and stays off for a client the driver never
connected through (bare command-level use, tests, the setup notebooks) or a
session that declined calibration (``load_calibration=False``). The delta
math itself is single-sourced in
:func:`navigator_expert.calibration.core.model.translation_delta_um`,
shared with the adapter's per-move frame mapping.

Author: Thom de Hoog (ZMB, University of Zurich).
License: MIT
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def _translations_for(client: Any) -> dict | None:
    """The per-slot translation table loaded for *client* at connect.

    ``None`` means compensation is off for this client: either the driver
    never loaded per-connection config for it (bare command-level use,
    tests, the setup notebooks), or the connection explicitly declined
    calibration (``connect_microscope(load_calibration=False)``) — the
    session declared itself uncalibrated, so lens swaps proceed bare.
    An empty dict means the connection *wanted* calibration but none is
    usable (unreadable file, or no pairs measured); an objective swap then
    fails the command's result rather than silently leaving the stage at
    the old lens's spot.
    """
    from ..connection import session_state

    config = session_state.get(client)
    if config is None:
        return None
    return config.translations


def record_before_change(
    client: Any, job_name: str | None = None, *, compensate: bool | None = None
) -> dict | None:
    """Record motoric XY, z-wide, and the active objective BEFORE a change.

    ``compensate`` makes the behaviour explicit at the call site:

    - ``None`` (default) — follow the session's connect-time policy:
      compensate when calibration was loaded, stay bare when the session is
      unarmed or declined calibration (``load_calibration=False``).
    - ``False`` — bare change, no recording, no compensation.
    - ``True`` — require compensation: raises when the session carries no
      calibration to compensate with, instead of proceeding bare.

    Returns ``None`` when compensation is off, in which case the caller
    proceeds exactly as it always has. Raises when compensation is on but
    the pre-change position cannot be read: a change whose starting point
    is unknown could never be compensated afterwards, so it must not be
    fired at all.
    """
    if compensate is False:
        return None
    translations = _translations_for(client)
    if translations is None:
        if compensate:
            raise RuntimeError(
                "compensate=True was requested but this session has no "
                "calibration loaded (connect with load_calibration=True, or "
                "adopt a calibration first)"
            )
        return None

    from .. import readers as _readers

    if job_name is None:
        selected = _readers.get_selected_job(client) or {}
        job_name = selected.get("Name")
        if not job_name:
            raise RuntimeError("could not determine the selected job")
    xy = _readers.get_xy(client) or {}
    if "x_um" not in xy or "y_um" not in xy:
        raise RuntimeError(f"get_xy returned no readback: {xy}")
    settings = _readers.get_job_settings(client, job_name) or {}
    slot = (settings.get("objective") or {}).get("slotIndex")
    z_wide = _readers.read_zwide_um(client, job_name)
    if z_wide is None:
        raise RuntimeError(f"z-wide readback unavailable for job {job_name!r}")
    return {
        "job": job_name,
        "x_um": float(xy["x_um"]),
        "y_um": float(xy["y_um"]),
        "z_wide_um": float(z_wide),
        "slot": None if slot is None else int(slot),
        "translations": translations,
    }


def compensate_after_change(
    client: Any,
    job_name: str,
    before: dict,
    new_slot: int | None = None,
) -> dict:
    """After the change: if the objective swapped, re-realize the sample point.

    ``before`` is what :func:`record_before_change` returned. ``new_slot``
    can be passed when the caller already knows the objective it commanded
    (``set_objective``); otherwise the new job's settings are read.

    Never raises — the change has already happened, so every problem is
    reported in the returned dict instead: ``{"ok": bool, "objective_changed":
    bool | None, "applied_translation_um": [x, y, z] | None, "message":
    str | None}``. The calling command turns ``ok=False`` into a failed
    result so nobody acquires at an uncompensated position by accident.
    """

    def _failed(message: str, *, changed: bool | None = True) -> dict:
        return {
            "ok": False,
            "objective_changed": changed,
            "applied_translation_um": None,
            "message": message,
        }

    try:
        from .. import readers as _readers

        if new_slot is None:
            settings = _readers.get_job_settings(client, job_name) or {}
            new_slot = (settings.get("objective") or {}).get("slotIndex")
        new_slot = None if new_slot is None else int(new_slot)
        old_slot = before["slot"]
        if old_slot == new_slot:
            return {
                "ok": True,
                "objective_changed": False,
                "applied_translation_um": None,
                "message": None,
            }
        if old_slot is None or new_slot is None:
            return _failed(
                f"the objective may have changed (slot {old_slot!r} -> "
                f"{new_slot!r}) but could not be identified on both sides, so "
                "the position was NOT compensated — re-check the objective and "
                "position before acquiring",
                changed=None,
            )
        # The delta math and the missing-pair policy live in ONE place —
        # calibration/core/model.py — shared with the adapter's per-move
        # frame mapping, so the two layers can never drift apart.
        from ..calibration.core import model as _cal_model

        try:
            delta = _cal_model.translation_delta_um(before["translations"], old_slot, new_slot)
        except RuntimeError as exc:
            return _failed(
                f"the change swapped the objective but {exc}; the stage was "
                f"NOT moved and still points at the old lens's spot — "
                f"compensate afterwards or reposition manually."
            )
        if delta != (0.0, 0.0, 0.0):
            log.info(
                "the change to %r swapped the objective (slot %s -> %s); "
                "moving by the calibrated translation (%+.2f, %+.2f, %+.2f) um "
                "to keep the sample point",
                job_name,
                old_slot,
                new_slot,
                *delta,
            )
            # The moves go through the ordinary gated wrappers, so the
            # compensated targets are checked against the machine limits
            # exactly like any other motion; a refusal fails the change.
            from . import commands as _commands

            xy_result = _commands.move_xy(
                client, before["x_um"] + delta[0], before["y_um"] + delta[1], unit="um"
            )
            if not xy_result.get("success") or xy_result.get("confirmed") is False:
                return _failed(
                    f"the compensating XY move after the objective change "
                    f"failed: {xy_result.get('message', xy_result)}"
                )
            z_result = _commands.move_z(
                client,
                job_name,
                before["z_wide_um"] + delta[2],
                unit="um",
                z_mode="zwide",
            )
            if not z_result.get("success") or z_result.get("confirmed") is False:
                return _failed(
                    f"the compensating z-wide move after the objective change "
                    f"failed: {z_result.get('message', z_result)}"
                )
        return {
            "ok": True,
            "objective_changed": True,
            "applied_translation_um": list(delta),
            "message": None,
        }
    except Exception as exc:  # noqa: BLE001 -- the change already fired; report, never mask
        return _failed(f"objective compensation failed after the change: {exc}", changed=None)


def merge_into_result(result: dict, compensation: dict | None) -> dict:
    """Fold a compensation report into a command result dict.

    A failed compensation fails the whole command result: the change itself
    went through, but leaving ``success: True`` would invite acquiring at a
    position that no longer points at the sample.
    """
    if compensation is None:
        return result
    result["objective_compensation"] = {
        "objective_changed": compensation["objective_changed"],
        "applied_translation_um": compensation["applied_translation_um"],
    }
    if not compensation["ok"]:
        result["success"] = False
        prefix = result.get("message")
        result["message"] = (
            f"{prefix} | {compensation['message']}" if prefix else compensation["message"]
        )
    return result
