"""Visible XY move pattern, comparing API vs log position readback.

Moves the stage around a square (default 5000 um per leg) for a couple of
laps so you can watch it move, and after each move reads the position back in
both ``mode="api"`` and ``mode="log"`` to show how the two readers behave.

Safety:
- All waypoints are relative to the CURRENT position (+/- delta), so the stage
  never heads toward the (0,0) corner.
- Every target is checked against ``drv.get_stage_limits()`` before moving, and
  ``move_xy`` re-checks the limits internally.
- The stage is always returned to the exact start position in a finally block.

Usage:
  python move_xy_pattern_api_vs_log.py            # 5000 um square, 2 laps
  python move_xy_pattern_api_vs_log.py --delta-um 5000 --laps 2 --pause-s 0.8
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # vendor/leica

import navigator_expert as drv


def _timed(fn):
    t = time.perf_counter()
    try:
        v, err = fn(), None
    except Exception as e:  # noqa: BLE001
        v, err = None, f"<{type(e).__name__}>"
    return v, (time.perf_counter() - t) * 1000.0, err


def _xy(v):
    return None if not v else (round(v["x_um"]), round(v["y_um"]))


def _inside(x, y, lim):
    return lim["x_min"] <= x <= lim["x_max"] and lim["y_min"] <= y <= lim["y_max"]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--delta-um",
        type=float,
        default=5000.0,
        help="square leg length in micrometers (default 5000)",
    )
    p.add_argument("--laps", type=int, default=2, help="how many times to go around the square")
    p.add_argument(
        "--pause-s", type=float, default=0.8, help="pause at each waypoint so you can see it"
    )
    p.add_argument(
        "--readback",
        choices=["both", "api", "log"],
        default="both",
        help="which reader(s) to read the position back with",
    )
    p.add_argument(
        "--log-poll-s",
        type=float,
        default=1.5,
        help="in log readback, poll up to this long for a fresh value",
    )
    args = p.parse_args(argv)

    client = drv.connect_python_client()
    # Load + apply the calibrated safety limits before ANY movement, exactly
    # like validate_hardware does. Without this the limits are unset.
    stage_cfg = drv.load_stage_config()
    _l = stage_cfg["stage_um"]
    lim = dict(
        x_min=_l["x"][0],
        x_max=_l["x"][1],
        y_min=_l["y"][0],
        y_max=_l["y"][1],
        z_galvo_min=_l["z_galvo"][0],
        z_galvo_max=_l["z_galvo"][1],
        z_wide_min=_l["z_wide"][0],
        z_wide_max=_l["z_wide"][1],
    )
    drv.set_stage_limits(**lim)
    start = drv.get_xy(client, mode="api")
    if not start:
        raise SystemExit("could not read starting XY")
    x0, y0 = float(start["x_um"]), float(start["y_um"])
    d = args.delta_um
    print(f"start (um) = ({x0:.0f}, {y0:.0f})")
    print(
        f"stage limits = x[{lim['x_min']:.0f},{lim['x_max']:.0f}] "
        f"y[{lim['y_min']:.0f},{lim['y_max']:.0f}]"
    )

    # square corners relative to start: right, up, left(=back over x), home
    legs = [
        ("right", x0 + d, y0),
        ("up", x0 + d, y0 + d),
        ("left", x0, y0 + d),
        ("home", x0, y0),
    ]

    # refuse the whole run if any corner is outside the safe envelope
    for name, tx, ty in legs:
        if not _inside(tx, ty, lim):
            raise SystemExit(
                f"target '{name}' ({tx:.0f},{ty:.0f}) outside stage limits - reduce --delta-um"
            )

    def read_back(mode):
        """Read position via `mode`. For log, poll up to --log-poll-s for a
        fresh value (the realistic way to use a freshness-gated reader)."""
        t0 = time.perf_counter()
        tries = 0
        err = None
        while True:
            tries += 1
            v, _, err = _timed(lambda: drv.get_xy(client, mode=mode))
            pos = _xy(v)
            done = pos is not None or mode != "log" or (time.perf_counter() - t0) >= args.log_poll_s
            if done:
                return pos, (time.perf_counter() - t0) * 1000.0, tries, err
            time.sleep(0.05)

    modes = ["api", "log"] if args.readback == "both" else [args.readback]
    label = {"api": "API readback", "log": "LOG readback"}
    hdr = f"{'lap':>3} {'leg':<6} {'target (x,y)':<18} {'moved':<6}"
    for m in modes:
        hdr += f"  {label[m]:<16} {'dX,dY':<9} {m + ' ms':>7}"
        if m == "log":
            hdr += f" {'tries':>5}"
    print("\n" + hdr)
    print("-" * len(hdr))

    rows = []
    try:
        for lap in range(1, args.laps + 1):
            for name, tx, ty in legs:
                res = drv.move_xy(client, tx, ty, unit="um")
                moved = "ok" if res.get("success") else "FAIL"
                time.sleep(args.pause_s)  # settle / be visible
                line = f"{lap:>3} {name:<6} {f'({tx:.0f},{ty:.0f})':<18} {moved:<6}"
                row = {}
                for m in modes:
                    pos, ms, tries, err = read_back(m)
                    dxy = "" if pos is None else f"{pos[0] - tx:+.0f},{pos[1] - ty:+.0f}"
                    line += f"  {(err or str(pos)):<16} {dxy:<9} {ms:>7.0f}"
                    if m == "log":
                        line += f" {tries:>5}"
                    row[m] = (pos, ms)
                print(line)
                rows.append(row)
    finally:
        print("\nrestoring to start...")
        r = drv.move_xy(client, x0, y0, unit="um")
        print(f"restored -> {_xy(drv.get_xy(client, mode='api'))}  (ok={r.get('success')})")

    n = len(rows)
    print(f"\nmoves: {n}")
    for m in modes:
        vals = [row[m] for row in rows if m in row]
        hit = sum(1 for pos, _ms in vals if pos is not None)
        ms = [mm for _p, mm in vals]
        if ms:
            print(
                f"  {m}: returned a value {hit}/{n}; "
                f"ms min={min(ms):.0f} max={max(ms):.0f} "
                f"mean={sum(ms) / len(ms):.0f}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
