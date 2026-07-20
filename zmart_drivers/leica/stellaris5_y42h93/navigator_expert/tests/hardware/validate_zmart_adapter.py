"""ZMART controller <-> Leica adapter validator.

Drives the Navigator Expert ``zmart_adapter`` through the **real
``zmart_controller`` surface** (``get_instruments`` / ``set_instrument`` /
``Session``), not the adapter functions directly -- so it validates the exact
path a workflow takes. The adapter's own unit tests patch the driver internals
and pass ``object()`` as the client; this validator instead runs the adapter
against a live CAM (LAS X simulator or a real scope) or the in-process mock.

Run against the LAS X simulator first to flush out adapter bugs, then point
LAS X at the scope and run the same script.

Safe by default:
  - read-only unless a phase is opted in
  - ``--enforce-ci-default-position`` moves to the rig's four-axis CI
    baseline before any other write phase
  - ``--allow-move`` (set_origin + set_xyz round-trip, incl. the z-focus
    additive sub-check) restores the original XY / both z drives in a finally
  - ``--allow-acquire`` runs one real capture+save into the controller run root
  - interactive 'yes' prompt before live writes unless --yes or --mock

Reuses the record/logging/JSONL machinery from ``validate_hardware`` so results
share one schema.

Usage:
  python validate_zmart_adapter.py --read-only --output -       # CI-safe, live
  python validate_zmart_adapter.py --allow-move --yes           # + set_origin/set_xyz
  python validate_zmart_adapter.py --allow-move --allow-acquire --yes
  python validate_zmart_adapter.py --mock --allow-move          # CI: in-process mock

Status semantics + exit code match validate_hardware (PASS/WARN/FAIL/SKIP;
exit 1 on any FAIL, or WARN with --strict-confirmation).
"""
# ruff: noqa: E402

from __future__ import annotations

import argparse
import math
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

# --- sys.path bootstrap -----------------------------------------------------
# Put the machine root (for ``navigator_expert``), the repo root (for
# ``zmart_controller`` / ``shared``), this dir (for ``validate_hardware``), and
# tests/helpers (for the mock) on the path, regardless of CWD.
_HERE = Path(__file__).resolve()
_NAV_ROOT = _HERE.parents[2]  # navigator_expert/
_MACHINE_ROOT = _NAV_ROOT.parent  # .../leica/stellaris5_y42h93
_REPO_ROOT = _HERE.parents[6]  # repo root (zmart_controller / shared live here)
_HELPERS = _NAV_ROOT / "tests" / "helpers"
for _p in (str(_HERE.parent), str(_MACHINE_ROOT), str(_REPO_ROOT), str(_HELPERS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import validate_hardware as vh  # reuse Record/Validator/sink/logging

import zmart_controller

# Readback tolerances: match the driver's own confirmation gates
# (confirm_move_xy default 20 um, confirm_move_z default 1.0 um).
XY_TOL_UM = 20.0
Z_TOL_UM = 1.0

# Hardware CI always starts its mutating phases from this measured, known-safe
# rig position. Keep the raw drives separate: controller frame-Z is their sum,
# but the safety baseline is a four-coordinate hardware contract.
CI_DEFAULT_POSITION_UM = {
    "x_um": 63_500.0,
    "y_um": 41_500.0,
    "z_wide_um": 0.0,
    "z_galvo_um": 0.0,
}


# --- setup ------------------------------------------------------------------


def _register_adapter() -> Any:
    """Import the adapter (registers on import) and return the implementation module."""
    from navigator_expert.zmart_adapter import zmart_adapter as adapter  # noqa: PLC0415

    return adapter


def _connect_session(args: argparse.Namespace, adapter: Any, output_root: str | None) -> Any:
    """Open a controller Session for the leica instrument.

    In --mock mode the adapter's CAM connect is swapped for the in-process
    Python mock, so the whole controller -> adapter -> driver path runs offline.
    """
    inst = next(
        i
        for i in zmart_controller.get_instruments()
        if i.get("vendor") == "leica" and i.get("api") == "navigator-expert"
    )
    inst = dict(inst)
    inst["client"] = args.client_name
    inst["api_delay_ms"] = args.api_delay_ms
    if output_root is not None:
        inst["output_root"] = output_root

    if args.mock:
        from dataclasses import replace  # noqa: PLC0415

        from limits_fixtures import hermetic_mock_machine_root  # noqa: PLC0415
        from mock_lasx_api import MockLasxClient  # noqa: PLC0415
        from navigator_expert.config import profiles  # noqa: PLC0415

        # Use a hermetic ProgramData fixture so the adapter connect's REAL
        # limits handshake succeeds without touching this developer machine.
        hermetic_mock_machine_root()
        adapter._session.connect_python_client = lambda **_kw: MockLasxClient(
            latency=args.mock_latency
        )
        # The mock has no LAS X log stream, so the default select-job
        # confirmation race would only ever time out waiting on log evidence
        # (same pinning as validate_hardware --mock).
        profiles.STATE_READERS = replace(profiles.STATE_READERS, selected_job_confirm_source="api")

    return zmart_controller.set_instrument(inst)


def _confirm_live_write(args: argparse.Namespace) -> bool:
    """Prompt before writes against a real LAS X session; bypass for --mock/--yes."""
    if args.read_only or args.yes or args.mock:
        return True
    parts = []
    if args.allow_move:
        parts.append("set_origin + small XY/Z moves (restored)")
    if args.allow_state:
        parts.append("a job switch + restore (set_state)")
    if args.allow_autofocus:
        parts.append("one autofocus run")
    if args.allow_acquire:
        parts.append("one acquire")
    if not parts:
        return True
    sys.stdout.write("LAS X session will receive: " + ", ".join(parts) + ".\n")
    sys.stdout.write("Type 'yes' to continue: ")
    sys.stdout.flush()
    return sys.stdin.readline().strip().lower() == "yes"


# --- phases -----------------------------------------------------------------


def phase_readonly(v: vh.Validator, sess: Any, args: argparse.Namespace) -> None:
    """Read-only controller round-trip: no moves, no writes, no acquisition."""
    with v.phase("read-only"):
        insts = v.callable("get_instruments", zmart_controller.get_instruments)
        if insts is not None:
            present = any(
                i.get("vendor") == "leica" and i.get("api") == "navigator-expert" for i in insts
            )
            v.compare("registry: leica adapter registered", present, True)

        act = v.callable("get_actuators", sess.get_actuators)
        if act is not None:
            v.compare(
                "actuators: expected menu",
                act,
                {"x": ["motoric"], "y": ["motoric"], "z": ["z-wide", "z-galvo"]},
            )

        xyz = v.callable("get_xyz", sess.get_xyz)
        if xyz is not None:
            for axis in ("x", "y", "z"):
                v.compare(f"get_xyz: {axis} unit is um", xyz[axis]["unit"], "um")
            hw = xyz.get("hardware") or {}
            needed = {"x_um", "y_um", "z_wide_um", "z_galvo_um", "objective", "job"}
            v.compare("get_xyz: hardware block complete", needed.issubset(hw), True)
            # The origin is session-scoped and never restored at connect, so on
            # this fresh session frame == hardware holds here (origin is all
            # zero until set_origin runs). The origin arithmetic itself is
            # verified in phase_move, right after set_origin, via the
            # "origin: frame -> 0" checks below, which also cover a non-zero
            # origin.
            v.compare(
                "get_xyz: objective has a name",
                bool((hw.get("objective") or {}).get("name")),
                True,
            )

        state = v.callable("get_state", sess.get_state)
        opts = v.callable("get_acquisition_options", sess.get_acquisition_options)
        if state is not None and opts is not None:
            selected_job = state["changeable"]["job"]
            normal_jobs = (opts.get("job") or {}).get("options") or []
            autofocus_jobs = {
                job.get("Name")
                for job in state["observed"].get("autofocus_jobs", [])
                if job.get("Name")
            }
            v.compare(
                "get_state: selected job is catalogued",
                selected_job in normal_jobs or selected_job in autofocus_jobs,
                True,
            )
            observed = state["observed"]
            v.compare(
                "get_state: observed carries an identity",
                bool(
                    observed.get("serial_number")
                    or observed.get("stand")
                    or observed.get("objectives")
                ),
                True,
            )

        info = v.callable("get_info", sess.get_info)
        if info is not None:
            v.compare("get_info: has session_hash6", bool(info.get("session_hash6")), True)
            v.compare("get_info: output_root returned", bool(info.get("output_root")), True)
            if not args.mock and info.get("output_root"):
                v.compare(
                    "get_info: run directory exists",
                    Path(info["output_root"]).is_dir(),
                    True,
                )
            tiles = info.get("tile_positions") or []
            if tiles:
                v.compare(
                    "get_info: tile positions carry tile_size",
                    all(bool(tile.get("tile_size")) for tile in tiles),
                    True,
                )
            else:
                v.skip("get_info: tile positions available", "no tiles in the live template")
            if not info.get("focus_positions"):
                v.skip(
                    "get_info: focus positions available", "no focus points in the live template"
                )


def _within(value: float, lo: float, hi: float) -> bool:
    return lo <= value <= hi


def _nonnegative_finite_float(raw: str) -> float:
    """Argparse type for a Z-wide excursion that can never point below zero."""
    value = float(raw)
    if not math.isfinite(value) or value < 0.0:
        raise argparse.ArgumentTypeError("must be a finite value >= 0")
    return value


def _ci_default_position_error(limits: dict) -> str | None:
    """Return why the fixed four-axis CI baseline cannot be commanded safely."""
    if CI_DEFAULT_POSITION_UM["z_wide_um"] < 0.0:
        return "Z-wide CI target must never be negative"
    for axis in ("x", "y", "z_wide", "z_galvo"):
        target = CI_DEFAULT_POSITION_UM[f"{axis}_um"]
        lo, hi = limits.get(f"{axis}_min"), limits.get(f"{axis}_max")
        if lo is None or hi is None:
            return f"{axis} limits are not configured"
        if not _within(target, float(lo), float(hi)):
            return f"{axis} target {target} um outside [{lo}, {hi}]"
    return None


def phase_ci_default_position(v: vh.Validator, sess: Any, drv: Any) -> bool:
    """Move to and verify the four-coordinate hardware-CI baseline.

    All targets are preflighted before the first command. Z-wide is commanded
    directly to 0 um (never through frame-focus arithmetic), so a non-zero
    z-galvo cannot turn the Z-wide target negative.
    """
    with v.phase("hardware-CI default position"):
        before = v.callable("ci default: read start", lambda: sess.get_xyz()["hardware"])
        limits = v.callable("ci default: read limits", drv.get_stage_limits)
        if not before or not limits:
            return False
        error = _ci_default_position_error(limits)
        if error:
            v.fail("ci default: preflight", error, context=dict(CI_DEFAULT_POSITION_UM))
            return False
        if not v.compare(
            "ci default: Z-wide target is non-negative",
            CI_DEFAULT_POSITION_UM["z_wide_um"] >= 0.0,
            True,
        ):
            return False

        job = before.get("job")
        if not job:
            v.fail("ci default: selected job", "no selected job for the Z commands")
            return False

        x_um = CI_DEFAULT_POSITION_UM["x_um"]
        y_um = CI_DEFAULT_POSITION_UM["y_um"]
        z_wide_um = CI_DEFAULT_POSITION_UM["z_wide_um"]
        z_galvo_um = CI_DEFAULT_POSITION_UM["z_galvo_um"]
        commands = (
            v.command(
                "ci default: move XY",
                lambda: drv.move_xy(sess._handle.client, x_um, y_um, unit="um"),
                context={"target_x_um": x_um, "target_y_um": y_um},
            ),
            v.command(
                "ci default: move Z-wide",
                lambda: drv.move_z(sess._handle.client, job, z_wide_um, unit="um", z_mode="zwide"),
                context={"target_z_wide_um": z_wide_um, "non_negative": True},
            ),
            v.command(
                "ci default: move Z-galvo",
                lambda: drv.move_z(sess._handle.client, job, z_galvo_um, unit="um", z_mode="galvo"),
                context={"target_z_galvo_um": z_galvo_um},
            ),
        )
        if any(not result or not result.get("success") for result in commands):
            return False

        after = v.callable("ci default: readback", lambda: sess.get_xyz()["hardware"])
        if not after:
            return False
        checks = [
            v.compare("ci default: X readback", after.get("x_um"), x_um, tolerance=XY_TOL_UM),
            v.compare("ci default: Y readback", after.get("y_um"), y_um, tolerance=XY_TOL_UM),
            v.compare(
                "ci default: Z-wide readback",
                after.get("z_wide_um"),
                z_wide_um,
                tolerance=Z_TOL_UM,
            ),
            v.compare(
                "ci default: Z-galvo readback",
                after.get("z_galvo_um"),
                z_galvo_um,
                tolerance=Z_TOL_UM,
            ),
        ]
        return all(checks)


def _restore(
    v: vh.Validator, sess: Any, drv: Any, orig: dict, job: str, restore_zwide: bool
) -> None:
    """Return the stage to its captured state.

    z-galvo and XY are restored by driving frame (0,0,0) through the adapter
    (origin was captured at the original spot). z-wide is restored directly
    only if this run actually moved it (its baseline may sit outside the
    envelope on the simulator, so we never touch it there).
    """
    client = sess._handle.client
    if restore_zwide:

        def do_zwide() -> bool:
            r = drv.move_z(client, job, orig["z_wide_um"], unit="um", z_mode="zwide")
            if not r.get("success"):
                raise RuntimeError(f"z-wide restore not accepted: {r}")
            return True

        v.callable(
            "move: restore z-wide",
            do_zwide,
            context={"z_wide_um": orig["z_wide_um"]},
            mutating=True,
        )
    v.callable(
        "move: restore XY + focus (frame 0,0,0)",
        lambda: sess.set_xyz(0.0, 0.0, 0.0, with_actuators={"z": "z-galvo"}),
        context=dict(orig, job=job),
        mutating=True,
    )


def phase_move(v: vh.Validator, sess: Any, drv: Any, args: argparse.Namespace) -> None:
    """set_origin + set_xyz round-trip, incl. the z-focus additive sub-check.

    The z model claims frame z = z-wide + z-galvo (additive, same sign). The
    focus is driven via z-galvo (baseline 0, symmetric envelope) so it works on
    the simulator; the z-wide drive leg is gated on the envelope because the
    simulator's z-wide baseline can sit outside the shipped physical envelope.
    """
    base = sess.get_xyz()["hardware"]
    orig = {k: base[k] for k in ("x_um", "y_um", "z_wide_um", "z_galvo_um")}
    job = base["job"]
    limits = drv.get_stage_limits()
    dx = dy = args.xy_delta_um
    dzw = args.z_wide_delta_um
    dzg = args.z_galvo_delta_um
    restore_zwide = False

    with v.phase("move (set_origin + set_xyz)"):
        try:
            v.callable("set_origin", sess.set_origin, mutating=True)
            f = v.callable("get_xyz after set_origin", sess.get_xyz)
            if f is not None:
                v.compare("origin: frame x -> 0", f["x"]["value"], 0.0, tolerance=XY_TOL_UM)
                v.compare("origin: frame y -> 0", f["y"]["value"], 0.0, tolerance=XY_TOL_UM)
                v.compare("origin: frame z -> 0", f["z"]["value"], 0.0, tolerance=Z_TOL_UM)

            # XY leg: hold focus via the galvo (keeps z-wide untouched on the sim).
            v.callable(
                "set_xyz: XY move",
                lambda: sess.set_xyz(dx, dy, 0.0, with_actuators={"z": "z-galvo"}),
                context={"to_frame": (dx, dy, 0.0), "z_actuator": "z-galvo"},
                mutating=True,
            )
            f = v.callable("get_xyz after XY", sess.get_xyz)
            if f is not None:
                v.compare("xy: frame x", f["x"]["value"], dx, tolerance=XY_TOL_UM)
                v.compare("xy: frame y", f["y"]["value"], dy, tolerance=XY_TOL_UM)

            # z-galvo leg: focus target dzg via z-galvo; z-wide must stay put.
            # This validates the additive relationship, units, and sign against
            # the real CAM readback.
            v.callable(
                "set_xyz: z-galvo move",
                lambda: sess.set_xyz(dx, dy, dzg, with_actuators={"z": "z-galvo"}),
                context={"to_frame": (dx, dy, dzg), "z_actuator": "z-galvo"},
                mutating=True,
            )
            f = v.callable("get_xyz after z-galvo", sess.get_xyz)
            if f is not None:
                v.compare("zgalvo: frame z", f["z"]["value"], dzg, tolerance=Z_TOL_UM)
                v.compare(
                    "zgalvo: drive moved by delta (sign check)",
                    f["hardware"]["z_galvo_um"] - orig["z_galvo_um"],
                    dzg,
                    tolerance=Z_TOL_UM,
                )
                v.compare(
                    "zgalvo: z-wide drive unchanged",
                    f["hardware"]["z_wide_um"],
                    orig["z_wide_um"],
                    tolerance=Z_TOL_UM,
                )

            # z-wide leg (gated): focus target dzg+dzw via z-wide; galvo holds.
            zw_target = orig["z_wide_um"] + dzw
            zw_lo, zw_hi = limits["z_wide_min"], limits["z_wide_max"]
            if _within(orig["z_wide_um"], zw_lo, zw_hi) and _within(zw_target, zw_lo, zw_hi):
                total = dzg + dzw
                v.callable(
                    "set_xyz: z-wide move",
                    lambda: sess.set_xyz(dx, dy, total, with_actuators={"z": "z-wide"}),
                    context={"to_frame": (dx, dy, total), "z_actuator": "z-wide"},
                    mutating=True,
                )
                restore_zwide = True
                f = v.callable("get_xyz after z-wide", sess.get_xyz)
                if f is not None:
                    v.compare(
                        "zwide: frame z is additive (z-wide + z-galvo)",
                        f["z"]["value"],
                        total,
                        tolerance=Z_TOL_UM,
                    )
                    v.compare(
                        "zwide: drive moved by delta",
                        f["hardware"]["z_wide_um"] - orig["z_wide_um"],
                        dzw,
                        tolerance=Z_TOL_UM,
                    )
                    v.compare(
                        "zwide: z-galvo drive unchanged",
                        f["hardware"]["z_galvo_um"] - orig["z_galvo_um"],
                        dzg,
                        tolerance=Z_TOL_UM,
                    )
            else:
                v.skip(
                    "zwide: drive leg",
                    f"z-wide baseline {orig['z_wide_um']} / target {zw_target} outside "
                    f"envelope [{zw_lo}, {zw_hi}] (simulator artifact; validates on a scope)",
                )
        finally:
            _restore(v, sess, drv, orig, job, restore_zwide)


def _get_state_settled(sess: Any, attempts: int = 6, delay_s: float = 0.5) -> dict:
    """``get_state`` with a short settle window.

    Right after a confirmed job switch the API's selected-job readback can
    lag for a moment (the documented api-lag-after-confirm behavior); the
    adapter's fail-closed read raises during that window, so poll briefly
    instead of failing the phase on a transient.
    """
    last: Exception | None = None
    for _ in range(attempts):
        try:
            return sess.get_state()
        except RuntimeError as exc:
            last = exc
            time.sleep(delay_s)
    raise last  # type: ignore[misc]


def phase_state(v: vh.Validator, sess: Any) -> None:
    """Capture → switch job via set_state → restore, fingerprint verified live."""
    with v.phase("state (capture / switch / restore)"):
        captured = v.callable("get_state: capture", sess.get_state)
        if not captured:
            return
        original = captured["changeable"]["job"]
        names = (sess.get_acquisition_options().get("job") or {}).get("options") or []
        autofocus_names = {
            job.get("Name")
            for job in captured["observed"].get("autofocus_jobs", [])
            if job.get("Name")
        }
        if original in autofocus_names:
            v.skip(
                "state: switch",
                f"current job {original!r} is autofocus-only and cannot be restored via set_state",
            )
            return
        if not v.compare("state: current job is a normal job", original in names, True):
            return

        other = next(
            (name for name in names if name != original and name not in autofocus_names),
            None,
        )
        if other is None:
            v.skip("state: switch", "no other normal acquisition job on this instrument")
            return
        v.callable(
            "set_state: switch job",
            lambda: sess.set_state({**captured, "changeable": {"job": other}}),
            context={"to": other, "from": original},
            mutating=True,
        )
        after = v.callable("get_state: after switch (settled)", lambda: _get_state_settled(sess))
        if after:
            v.compare("state: switched", after["changeable"]["job"], other)
        v.callable(
            "set_state: restore",
            lambda: sess.set_state(captured),
            context={"restore_to": original},
            mutating=True,
        )
        restored = v.callable(
            "get_state: after restore (settled)", lambda: _get_state_settled(sess)
        )
        if restored:
            v.compare("state: restored", restored["changeable"]["job"], original)


def phase_autofocus(v: vh.Validator, sess: Any) -> None:
    """Run the autofocus procedure end-to-end; the selection must survive it."""
    with v.phase("autofocus (procedure)"):
        procedures = v.callable("get_procedures", sess.get_procedures)
        if not procedures:
            return
        af_jobs = (procedures.get("autofocus") or {}).get("jobs") or []
        if not af_jobs:
            v.skip("autofocus: run", "no autofocus job on this instrument")
            return
        before = _get_state_settled(sess)["changeable"]["job"]
        result = v.callable(
            "autofocus: run",
            lambda: sess.run_procedure({"name": "autofocus", "job": af_jobs[0]}),
            context={"job": af_jobs[0]},
            mutating=True,
        )
        if result:
            v.compare(
                "autofocus: reports a numeric focus",
                isinstance(result.get("focus_um"), (int, float)),
                True,
            )
        after = v.callable("get_state: after autofocus (settled)", lambda: _get_state_settled(sess))
        if after:
            v.compare("autofocus: selection restored", after["changeable"]["job"], before)


def phase_acquire(v: vh.Validator, sess: Any, args: argparse.Namespace) -> None:
    """One real capture+save through the controller into the scratch output root."""
    if args.mock:
        v.skip("phase: acquire", "save requires real LAS X export files; run live")
        return
    with v.phase("acquire (capture + save)"):
        # The live LAS X session decides where it writes; save collects from
        # the single native AutoSave path.
        options: dict[str, Any] = {"backlash_correction": True}
        rec = v.callable(
            "acquire: capture + save",
            lambda: sess.acquire(
                acquisition_type="adapter-smoke",
                position_label="1",
                options=options,
            ),
            context={"backlash_correction": True},
            mutating=True,
        )
        if not rec:
            return
        images = rec.get("images") or []
        xml = rec.get("xml") or []
        v.compare("acquire: at least one image", len(images) >= 1, True)
        # Canonical ZMART output is flat and no-sidecar: the OME-XML (incl. the
        # embedded machine-state block) lives inside each plane's TIFF, so the
        # manifest carries no companion XML. Contract: acquisition/product.py
        # SavedAcquisition.xml_paths; offline tests assert xml_paths == {}.
        v.compare("acquire: no sidecar xml (state embedded per-plane)", len(xml), 0)
        non_empty = all(Path(p).is_file() and Path(p).stat().st_size > 0 for p in images)
        v.compare("acquire: image files exist and are non-empty", non_empty, True)
        if images:
            from navigator_expert.acquisition import materialize  # noqa: PLC0415

            # The no-sidecar contract means the metadata must be INSIDE the
            # image; prove it on the real produced TIFF (offline tests only
            # exercise the mock export).
            embedded = v.callable(
                "acquire: extract embedded OME-XML",
                lambda: materialize.extract_embedded_ome_xml(Path(images[0])),
            )
            if embedded is not None:
                v.compare("acquire: image carries embedded OME-XML", b"<OME" in embedded, True)
        v.compare("acquire: backlash_correction ran", rec.get("settle"), "backlash-corrected")


# --- CLI --------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--mock", action="store_true", help="in-process Python mock (no LAS X)")
    p.add_argument("--mock-latency", type=float, default=0.0)
    p.add_argument("--client-name", default="PythonClient")
    p.add_argument("--api-delay-ms", type=int, default=None)

    # phase gates
    p.add_argument("--read-only", action="store_true", help="skip all move/state/acquire phases")
    p.add_argument("--allow-move", action="store_true", help="set_origin + set_xyz round-trip")
    p.add_argument(
        "--allow-state", action="store_true", help="get/set_state round-trip (switches jobs)"
    )
    p.add_argument(
        "--allow-autofocus", action="store_true", help="run the autofocus procedure once"
    )
    p.add_argument("--allow-acquire", action="store_true", help="one capture+save")
    p.add_argument(
        "--enforce-ci-default-position",
        action="store_true",
        help="move to the fixed four-axis rig baseline before other write phases",
    )

    # deltas
    p.add_argument("--xy-delta-um", type=float, default=25.0)
    p.add_argument(
        "--z-wide-delta-um",
        type=_nonnegative_finite_float,
        default=3.0,
        help="non-negative Z-wide excursion from the baseline (default: 3 um)",
    )
    p.add_argument("--z-galvo-delta-um", type=float, default=2.0)

    # acquire
    p.add_argument(
        "--output-root", default=None, help="where acquire/set_origin write (default: temp)"
    )

    # output + gating
    p.add_argument("--output", default=None, help="JSONL output path; '-' for stdout")
    p.add_argument(
        "--report-dir",
        default=None,
        help="directory for the Markdown run report "
        "(hardware_run_report_<YYYYMMDD-HHMMSS>.md; default: working directory)",
    )
    p.add_argument("--strict-confirmation", action="store_true")
    p.add_argument("--yes", action="store_true", help="skip the interactive confirm before writes")
    p.add_argument(
        "--allow-missing-lasx",
        action="store_true",
        help="record SKIP instead of FAIL when the CAM cannot connect",
    )
    p.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    p.add_argument("--state-reader-mode", choices=["api", "log", "hybrid"], default=None)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    log = vh._configure_logging(args.log_level, jsonl_to_stdout=(args.output == "-"))
    sink = vh._make_sink(args.output, log)
    report = vh.RunReport(
        script="validate_zmart_adapter",
        backend=(
            "mock (in-process MockLasxClient; no instrument touched)"
            if args.mock
            else "live LAS X (simulator or scope)"
        ),
        report_dir=args.report_dir,
        argv=list(argv) if argv is not None else sys.argv[1:],
    )
    v = vh.Validator(
        sink=sink, log=log, strict_confirmation=args.strict_confirmation, report=report
    )

    adapter = _register_adapter()
    vh._apply_state_reader_mode(args.state_reader_mode, log)
    import navigator_expert as drv  # noqa: PLC0415

    output_root = args.output_root
    if args.mock and output_root is None:
        output_root = tempfile.mkdtemp(prefix="zmart_adapter_validate_")

    log.info("=== ZMART controller<->adapter validator ===")
    log.info(
        "client=%s read_only=%s output_root=%s",
        "python-mock" if args.mock else "LasxApi (sim or scope)",
        args.read_only,
        output_root or "<discovered by get_info>",
    )

    crash: str | None = None
    try:
        try:
            sess = _connect_session(args, adapter, output_root)
        except Exception as exc:  # noqa: BLE001 -- .NET interop / missing LAS X
            if args.allow_missing_lasx:
                v.skip("client: connect", f"could not connect ({type(exc).__name__}: {exc})")
            else:
                v.fail("client: connect", f"{type(exc).__name__}: {exc}")
            return v.exit_code()

        phase_readonly(v, sess, args)

        if args.read_only:
            log.info("read-only mode: skipping move/acquire")
        elif not _confirm_live_write(args):
            log.warning("aborted before live writes")
        else:
            baseline_ready = True
            if args.enforce_ci_default_position:
                baseline_ready = phase_ci_default_position(v, sess, drv)
            if not baseline_ready:
                v.skip(
                    "hardware write phases",
                    "CI default position could not be enforced; refusing remaining writes",
                )
            elif args.allow_move:
                phase_move(v, sess, drv, args)
            else:
                v.skip("phase: move", "use --allow-move to enable")
            if baseline_ready and args.allow_state:
                phase_state(v, sess)
            elif baseline_ready:
                v.skip("phase: state", "use --allow-state to enable")
            if baseline_ready and args.allow_autofocus:
                phase_autofocus(v, sess)
            elif baseline_ready:
                v.skip("phase: autofocus", "use --allow-autofocus to enable")
            if baseline_ready and args.allow_acquire:
                phase_acquire(v, sess, args)
            elif baseline_ready:
                v.skip("phase: acquire", "use --allow-acquire to enable")

        try:
            sess.disconnect()
        except Exception:  # noqa: BLE001
            pass
    except BaseException as exc:
        crash = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        v.summary()
        try:
            report_path = report.write(crashed=crash)
        except OSError as exc:  # never mask the run result with a report error
            log.error("could not write markdown run report: %s", exc)
        else:
            log.info("markdown run report: %s", report_path)

    return v.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())
