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
  - ``--allow-move`` (set_origin + set_xyz round-trip, incl. the z-focus
    additive sub-check) restores the original XY / both z drives in a finally
  - ``--allow-acquire`` runs one real capture+save into a scratch output root
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
import sys
import tempfile
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
# Frame value must equal the raw hardware reading when no origin is set.
EXACT_TOL_UM = 0.05


# --- setup ------------------------------------------------------------------


def _register_adapter() -> Any:
    """Import the adapter (registers on import) and return the module."""
    import navigator_expert.zmart_adapter as adapter  # noqa: PLC0415

    return adapter


def _connect_session(args: argparse.Namespace, adapter: Any, output_root: str) -> Any:
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
    inst["output_root"] = output_root

    if args.mock:
        from mock_lasx_api import MockLasxClient  # noqa: PLC0415

        adapter._session.connect_python_client = lambda **_kw: MockLasxClient(
            latency=args.mock_latency
        )

    return zmart_controller.set_instrument(inst)


def _confirm_live_write(args: argparse.Namespace) -> bool:
    """Prompt before writes against a real LAS X session; bypass for --mock/--yes."""
    if args.read_only or args.yes or args.mock:
        return True
    parts = []
    if args.allow_move:
        parts.append("set_origin + small XY/Z moves (restored)")
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
            # With no origin set, the frame value is the raw hardware reading.
            v.compare(
                "get_xyz: frame x == hardware x_um",
                xyz["x"]["value"],
                hw.get("x_um"),
                tolerance=EXACT_TOL_UM,
            )
            v.compare(
                "get_xyz: frame z == z_wide + z_galvo",
                xyz["z"]["value"],
                (hw.get("z_wide_um") or 0.0) + (hw.get("z_galvo_um") or 0.0),
                tolerance=EXACT_TOL_UM,
            )
            v.compare(
                "get_xyz: objective has a name",
                bool((hw.get("objective") or {}).get("name")),
                True,
            )

        state = v.callable("get_state", sess.get_state)
        opts = v.callable("get_acquisition_options", sess.get_acquisition_options)
        if state is not None and opts is not None:
            v.compare(
                "get_state: mutable job is in the job list",
                state["mutable"]["job"] in opts["job"]["options"],
                True,
            )
            if not args.mock:
                v.compare(
                    "get_state: immutable microscope is non-null",
                    bool(state["immutable"]["microscope"]),
                    True,
                )
            v.compare(
                "get_acquisition_options: active exporter is offered",
                opts["exporter"]["active"] in opts["exporter"]["options"],
                True,
            )

        ctx = v.callable("get_context", sess.get_context)
        if ctx is not None:
            v.compare("get_context: has session_hash6", bool(ctx.get("session_hash6")), True)


def _within(value: float, lo: float, hi: float) -> bool:
    return lo <= value <= hi


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

        v.callable("move: restore z-wide", do_zwide, context={"z_wide_um": orig["z_wide_um"]})
    v.callable(
        "move: restore XY + focus (frame 0,0,0)",
        lambda: sess.set_xyz(0.0, 0.0, 0.0, with_actuators={"z": "z-galvo"}),
        context=dict(orig, job=job),
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
            v.callable("set_origin", sess.set_origin)
            f = v.callable("get_xyz after set_origin", sess.get_xyz)
            if f is not None:
                v.compare("origin: frame x -> 0", f["x"]["value"], 0.0, tolerance=XY_TOL_UM)
                v.compare("origin: frame y -> 0", f["y"]["value"], 0.0, tolerance=XY_TOL_UM)
                v.compare("origin: frame z -> 0", f["z"]["value"], 0.0, tolerance=Z_TOL_UM)

            # XY leg: hold focus via the galvo (keeps z-wide untouched on the sim).
            v.callable(
                "set_xyz: XY move",
                lambda: sess.set_xyz(dx, dy, 0.0, with_actuators={"z": "z-galvo"}),
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


def phase_acquire(v: vh.Validator, sess: Any, args: argparse.Namespace) -> None:
    """One real capture+save through the controller into the scratch output root."""
    if args.mock:
        v.skip("phase: acquire", "save requires real LAS X export files; run live")
        return
    with v.phase("acquire (capture + save)"):
        # Use the instrument's active exporter unless one is forced: the live
        # LAS X session decides where it writes (this sim uses native autosave).
        options: dict[str, Any] = {}
        if args.exporter:
            options["exporter"] = args.exporter
        active = (sess.get_acquisition_options().get("exporter") or {}).get("active")
        rec = v.callable(
            "acquire: capture + save",
            lambda: sess.acquire(
                acquisition_type="adapter-smoke",
                position_label="1",
                options=options,
            ),
            context={"exporter": args.exporter or active},
        )
        if not rec:
            return
        images = rec.get("images") or []
        xml = rec.get("xml") or []
        v.compare("acquire: at least one image", len(images) >= 1, True)
        v.compare("acquire: at least one xml", len(xml) >= 1, True)
        non_empty = all(Path(p).is_file() and Path(p).stat().st_size > 0 for p in images)
        v.compare("acquire: image files exist and are non-empty", non_empty, True)


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
    p.add_argument("--read-only", action="store_true", help="skip all move/acquire phases")
    p.add_argument("--allow-move", action="store_true", help="set_origin + set_xyz round-trip")
    p.add_argument("--allow-acquire", action="store_true", help="one capture+save")

    # deltas
    p.add_argument("--xy-delta-um", type=float, default=25.0)
    p.add_argument("--z-wide-delta-um", type=float, default=3.0)
    p.add_argument("--z-galvo-delta-um", type=float, default=2.0)

    # acquire
    p.add_argument(
        "--exporter",
        default=None,
        choices=["navigator_expert", "lasx_native_autosave"],
        help="force a save exporter for --allow-acquire (default: the instrument's active one)",
    )
    p.add_argument(
        "--output-root", default=None, help="where acquire/set_origin write (default: temp)"
    )

    # output + gating
    p.add_argument("--output", default=None, help="JSONL output path; '-' for stdout")
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
    v = vh.Validator(sink=sink, log=log, strict_confirmation=args.strict_confirmation)

    adapter = _register_adapter()
    vh._apply_state_reader_mode(args.state_reader_mode, log)
    import navigator_expert as drv  # noqa: PLC0415

    output_root = args.output_root or tempfile.mkdtemp(prefix="zmart_adapter_validate_")

    log.info("=== zmart controller<->adapter validator ===")
    log.info(
        "client=%s read_only=%s output_root=%s",
        "python-mock" if args.mock else "LasxApi (sim or scope)",
        args.read_only,
        output_root,
    )

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
            if args.allow_move:
                phase_move(v, sess, drv, args)
            else:
                v.skip("phase: move", "use --allow-move to enable")
            if args.allow_acquire:
                phase_acquire(v, sess, args)
            else:
                v.skip("phase: acquire", "use --allow-acquire to enable")

        try:
            sess.disconnect()
        except Exception:  # noqa: BLE001
            pass
    finally:
        v.summary()

    return v.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())
