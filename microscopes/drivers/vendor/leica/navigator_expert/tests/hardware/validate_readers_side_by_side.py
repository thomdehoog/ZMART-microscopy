"""
Side-by-side reader validation: CAM API vs log_reader.
======================================================
Runs against a live LAS X session (simulator or scope). Compares the
production API readers against ``state_readers.log_reader`` and reports:

  - CORRECTNESS/PARITY: gate on the contract fields the driver actually
    uses, with tolerances (both-None counts as a match). A full dict diff
    would be brittle on harmless vendor metadata. For changes, polls each
    backend for the *expected* value in a bounded window so a valid-but-stale
    log read can't false-fail. EVERY printed check counts toward the exit code.
  - PERFORMANCE: per-backend read latency, API timeout/hang count.
  - FRESHNESS: the age of each log datum, including per-job settings age.
  - DIALOG: whether a modal box is currently blocking the CAM API.

Run order (fail fast): read-only parity -> high-signal write set ->
(optional) selected-job round-trip. Reversible writes only; every write
restored in a finally. Stage/objective/acquire are NOT touched. The
job-switch round-trip is gated behind --allow-job-switch (it pops the
manual-turret dialog and blocks the CAM API); default runs are click-free.

Usage:
  python validate_readers_side_by_side.py --read-only
  python validate_readers_side_by_side.py --yes
  python validate_readers_side_by_side.py --yes --allow-job-switch
  python validate_readers_side_by_side.py --log-path X.log
"""

import argparse
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # vendor/leica

import navigator_expert as drv
from navigator_expert.commands.settings import make_changeable_copy
from navigator_expert.runtime import profiles
from navigator_expert.runtime.utils import parse_tile_geometry
from navigator_expert.state_readers import log_reader as L

API_HANG_MS = 1500.0  # an API read slower than this is treated as a dialog-hang


# --- helpers ---------------------------------------------------------------


def _approx(a, b, tol):
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return a == b


def _eq(a, b, tol=None):
    """Equality for 'expected value appeared' polling: None never matches."""
    if a is None or b is None:
        return False
    if tol is not None:
        return _approx(a, b, tol)
    if isinstance(a, str) and isinstance(b, str):
        return a.strip() == b.strip()
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return _approx(a, b, max(1e-9, abs(a) * 1e-6))
    return a == b


def _ceq(a, b, tol=None):
    """Equality for contract-field parity: both-None is a match (an optional
    field absent on both backends is consistent)."""
    if a is None and b is None:
        return True
    return _eq(a, b, tol)


def _timed(fn):
    t = time.perf_counter()
    try:
        v = fn()
    except Exception as e:  # noqa: BLE001
        return None, (time.perf_counter() - t) * 1000, repr(e)
    return v, (time.perf_counter() - t) * 1000, None


def _ch(raw):
    if not raw:
        return None
    try:
        return make_changeable_copy(raw)
    except Exception:  # noqa: BLE001
        return None


def _row(results, key, ok, extra="", hang=False, latency=0.0):
    print(f"  {'OK ' if ok else 'XX '} {key:<36} {extra}")
    results.append((key, ok, latency, hang))
    return ok


def _ms(x):
    return f"{x:.0f}ms" if x is not None else "TIMEOUT"


# --- contract-field extraction (incl. the nested fields make_changeable_copy
#     defaults to None: beamRoute, lineIndex, across ALL activeSettings) ------


def contract_fields(raw):
    ch = _ch(raw)
    if ch is None:
        return None
    obj = ch.get("objective") or {}
    zp = ch.get("zPosition") or {}
    out = {
        "zoom": (ch.get("zoom") or {}).get("current"),
        "scanSpeed": (ch.get("scanSpeed") or {}).get("value"),
        "isResonant": (ch.get("scanSpeed") or {}).get("isResonant"),
        "scanMode": ch.get("scanMode"),
        "sequentialMode": ch.get("sequentialMode"),
        "scanFieldRotation": (ch.get("scanFieldRotation") or {}).get("value"),
        "format": ch.get("format"),
        "objective.name": (obj.get("name") or "").strip(),
        "objective.slotIndex": obj.get("slotIndex"),
        "z-galvo": zp.get("z-galvo"),
        "z-wide": zp.get("z-wide"),
    }
    st = ch.get("stack") or {}
    for sk in ("begin", "end", "stepSize", "size"):
        out["stack." + sk] = st.get(sk)
    for i, a in enumerate(ch.get("activeSettings") or []):
        p = f"as{i}."
        out[p + "pinholeAiry"] = (a.get("pinholeAiry") or {}).get("value")
        out[p + "frameAccumulation"] = a.get("frameAccumulation")
        out[p + "frameAverage"] = a.get("frameAverage")
        out[p + "lineAccumulation"] = a.get("lineAccumulation")
        out[p + "lineAverage"] = a.get("lineAverage")
        for k, d in enumerate(a.get("activeDetectors") or []):
            out[f"{p}det{k}.beamRoute"] = d.get("_beamRoute")
            out[f"{p}det{k}.gain"] = (d.get("gain") or {}).get("value")
        for k, las in enumerate(a.get("activeLaserLines") or []):
            out[f"{p}laser{k}.beamRoute"] = las.get("_beamRoute")
            out[f"{p}laser{k}.lineIndex"] = las.get("_lineIndex")
            out[f"{p}laser{k}.intensity"] = (las.get("intensity") or {}).get("value")
            out[f"{p}laser{k}.shutterOpen"] = las.get("shutterOpen")
        for k, fw in enumerate(a.get("filterWheels") or []):
            out[f"{p}fw{k}.beamRoute"] = fw.get("_beamRoute")
            out[f"{p}fw{k}.filterIndex"] = fw.get("filterIndex")
            out[f"{p}fw{k}.spectrumPosition"] = fw.get("spectrumPosition")
    try:
        out["tile_w_um"] = round(parse_tile_geometry(raw)["tile_w_um"], 2)
    except Exception:  # noqa: BLE001
        out["tile_w_um"] = None
    return out


# --- phases ----------------------------------------------------------------


def phase_readonly(client, results):
    print("\n=== READ-ONLY PARITY (current state) ===")
    # ONE consistent log snapshot for the whole round so calls don't disagree
    # with each other while a live sim is mid-redump.
    snap = L.parse_log()
    ag = L.ages(snap)
    dlg = L.get_pending_dialog(snap)
    if dlg:
        print(f"  !! modal dialog OPEN (CAM API is blocked): {dlg!r}")

    axy, alat, _ = _timed(lambda: drv.get_xy(client, mode="api"))
    lxy = L.get_xy(snap)
    if axy is None and lxy is not None:
        _row(
            results,
            "get_xy",
            True,
            f"API HANG ({alat:.0f}ms) -> log delivered "
            f"({lxy['x_um']:.0f},{lxy['y_um']:.0f})um  log_age={ag['xy']:.0f}s",
            hang=True,
            latency=alat,
        )
    else:
        ok = bool(
            axy
            and lxy
            and _eq(axy["x_um"], lxy["x_um"], 1.0)
            and _eq(axy["y_um"], lxy["y_um"], 1.0)
        )
        _row(
            results,
            "get_xy",
            ok,
            f"api={alat:.0f}ms" + (f" log_age={ag['xy']:.0f}s" if ag["xy"] else ""),
            hang=alat > API_HANG_MS,
            latency=alat,
        )

    ajobs, alat, _ = _timed(lambda: drv.get_jobs(client, mode="api"))
    ljobs = L.get_jobs(snap)
    an = sorted(j["Name"] for j in (ajobs or []))
    ln = sorted(j["Name"] for j in (ljobs or []))
    asel = sorted(j["Name"] for j in (ajobs or []) if j.get("IsSelected"))
    lsel = sorted(j["Name"] for j in (ljobs or []) if j.get("IsSelected"))
    _row(
        results,
        "get_jobs (names)",
        an == ln,
        f"api={an} log={ln}",
        latency=alat,
        hang=alat > API_HANG_MS,
    )
    _row(results, "get_selected_job", asel == lsel, f"api={asel} log={lsel}")

    astat = drv.get_scan_status(client, mode="api")
    lstat = L.get_scan_status(snap)
    _row(
        results,
        "get_scan_status (idle-sense)",
        ("Idle" in str(astat)) == ("Idle" in str(lstat)),
        f"api={astat!r} log={lstat!r}"
        + (f" log_age={ag['scan_status']:.0f}s" if ag["scan_status"] else ""),
    )

    ahw, _, _ = _timed(lambda: drv.get_hardware_info(client, mode="api"))
    lhw = L.get_hardware_info(snap)
    hw_ok = (
        bool(ahw)
        and bool(lhw)
        and (ahw.get("Microscope", {}).get("name") == lhw.get("Microscope", {}).get("name"))
    )
    _row(results, "get_hardware_info (Microscope.name)", hw_ok)

    for job in ln or an:
        araw = drv.get_job_settings(client, job, mode="api")
        lraw = L.get_job_settings(job, snap)
        af, lf = contract_fields(araw), contract_fields(lraw)
        jage = ag["jobs"].get(job)
        if af is None or lf is None:
            _row(
                results,
                f"settings[{job}]",
                False,
                f"api={af is not None} log={lf is not None}"
                + (f"  (log_age={jage:.0f}s)" if jage is not None else ""),
            )
            continue
        keys = set(af) | set(lf)  # union -> a key on only one side is a clean diff, not a crash
        diffs = [
            k
            for k in keys
            if not _ceq(
                af.get(k),
                lf.get(k),
                0.05 if k.endswith("pinholeAiry") else (0.1 if k == "zoom" else None),
            )
        ]
        _row(
            results,
            f"settings[{job}] ({len(keys)} fields)",
            not diffs,
            (f"log_age={jage:.0f}s" if jage is not None else "")
            + ("" if not diffs else f"  DIFFS {[(k, af.get(k), lf.get(k)) for k in diffs]}"),
        )
        afov, lfov = drv.get_fov(client, job, mode="api"), L.get_fov(job, snap)
        _row(
            results,
            f"get_fov[{job}]",
            bool(afov and lfov and _eq(afov[0] * 1e6, lfov[0] * 1e6, 0.5)),
            f"api={afov} log={lfov}",
        )
        try:
            az = drv.read_zwide_um(client, job, mode="api")
        except Exception as e:  # noqa: BLE001
            az = f"<{e}>"
        try:
            lz = L.read_zwide_um(job, snap)
        except Exception as e:  # noqa: BLE001
            lz = f"<{e}>"
        _row(results, f"read_zwide_um[{job}]", _eq(az, lz, 0.1), f"api={az} log={lz}")


def _poll_both(api_read, log_read, expected, tol, timeout, interval):
    """Poll both backends from one t0. The LOG poller runs on its own thread
    (file-only, CAM-independent) so an API hang/timeout can't starve it and
    false-fail the log. Returns (api_ms, log_ms, api_hang)."""
    t0 = time.perf_counter()
    box = {"log_ms": None}

    def log_loop():
        while (time.perf_counter() - t0) < timeout and box["log_ms"] is None:
            if _eq(log_read(), expected, tol):
                box["log_ms"] = (time.perf_counter() - t0) * 1000
                return
            time.sleep(interval)

    th = threading.Thread(target=log_loop, daemon=True)
    th.start()
    api_ms = None
    api_hang = False
    while (time.perf_counter() - t0) < timeout:
        v, lat, _ = _timed(api_read)
        if lat > API_HANG_MS:
            api_hang = True
        if api_ms is None and _eq(v, expected, tol):
            api_ms = (time.perf_counter() - t0) * 1000
        if api_ms is not None and box["log_ms"] is not None:
            break
        time.sleep(interval)
    th.join(timeout=max(0.1, timeout - (time.perf_counter() - t0)) + 0.5)
    return api_ms, box["log_ms"], api_hang


def phase_changes(client, job, results):
    print(f"\n=== LIVE CHANGES on '{job}' (reversible; restored) ===")
    pt = profiles.LOG_READER.poll_timeout
    pi = profiles.LOG_READER.poll_interval
    specs = [
        (
            "zoom",
            [5.0, 2.0, 1.0],
            0.1,
            lambda j, x: drv.set_zoom(client, j, x),
            lambda ch: (ch["zoom"] or {}).get("current"),
        ),
        (
            "scan_speed",
            [400, 600, 800],
            1.0,
            lambda j, x: drv.set_scan_speed(client, j, x),
            lambda ch: (ch["scanSpeed"] or {}).get("value"),
        ),
        (
            "image_format",
            ["512 x 512", "1024 x 1024"],
            None,
            lambda j, x: drv.set_image_format(client, j, x),
            lambda ch: ch.get("format"),
        ),
        (
            "pinhole_airy",
            [1.0, 1.2, 0.8],
            0.05,
            lambda j, x: drv.set_pinhole_airy(client, j, 0, x),
            lambda ch: ((ch.get("activeSettings") or [{}])[0].get("pinholeAiry") or {}).get(
                "value"
            ),
        ),
    ]
    for name, cands, tol, setfn, readfn in specs:
        cur_ch = _ch(drv.get_job_settings(client, job, mode="api"))
        if cur_ch is None:
            _row(results, f"change[{name}]", False, "cannot read current")
            continue
        cur = readfn(cur_ch)
        target = next((c for c in cands if not _eq(c, cur, tol)), None)
        if target is None:
            _row(results, f"change[{name}]", False, "no alternate candidate")
            continue

        def api_read(readfn=readfn):
            raw = drv.get_job_settings(client, job, mode="api")
            return readfn(_ch(raw)) if raw else None

        def log_read(readfn=readfn):
            raw = L.get_job_settings(job)
            return readfn(_ch(raw)) if raw else None

        try:
            res = setfn(job, target)
            if not (res or {}).get("success"):
                _row(results, f"change[{name}]", False, f"set failed: {(res or {}).get('message')}")
                continue
            api_ms, log_ms, hang = _poll_both(api_read, log_read, target, tol, pt + 1.0, pi)
            both = api_ms is not None and log_ms is not None
            earlier = "tie" if not both else ("log" if log_ms < api_ms else "api")
            _row(
                results,
                f"change[{name}] -> {target}",
                both,
                f"api={_ms(api_ms)} log={_ms(log_ms)} earlier={earlier}"
                + ("  API-HANG" if hang else ""),
                hang=hang or api_ms is None,
                latency=api_ms or 0,
            )
        finally:
            setfn(job, cur)


def phase_select(client, results):
    print("\n=== SELECT-JOB round trip (gated; may pop the objective dialog) ===")
    names = [j["Name"] for j in (drv.get_jobs(client, mode="api") or [])]
    original = (drv.get_selected_job(client, mode="api") or {}).get("Name")
    try:
        for n in names:
            drv.select_job(client, n)
            api_ms, log_ms, _ = _poll_both(
                lambda: (drv.get_selected_job(client, mode="api") or {}).get("Name"),
                lambda: (L.get_selected_job() or {}).get("Name"),
                n,
                None,
                profiles.LOG_READER.poll_timeout + 1.0,
                profiles.LOG_READER.poll_interval,
            )
            both = api_ms is not None and log_ms is not None
            dlg = L.get_pending_dialog()
            note = f"  [BLOCKED BY DIALOG: {dlg!r}]" if dlg else ""
            _row(
                results,
                f"select[{n}]",
                both,
                f"api={_ms(api_ms)} log={_ms(log_ms)}{note}",
                hang=api_ms is None,
                latency=api_ms or 0,
            )
    finally:
        if original:
            drv.select_job(client, original)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--read-only", action="store_true")
    p.add_argument("--yes", action="store_true", help="allow reversible writes")
    p.add_argument(
        "--allow-job-switch",
        action="store_true",
        help="run the select-job round-trip (pops the objective dialog)",
    )
    p.add_argument("--client-name", default="PythonClient")
    p.add_argument("--log-path", default=None)
    p.add_argument("--job", default=None)
    args = p.parse_args(argv)

    if args.log_path:
        profiles.LOG_READER = profiles.LogReaderProfile(lcs_log_path=args.log_path)

    from navigator_expert.runtime.lasx_runtime import load_lasx_api_runtime

    lasx_api = load_lasx_api_runtime()
    client = lasx_api.LasxApiClientPyModel
    print("Connect:", client.Connect(args.client_name))

    results = []
    phase_readonly(client, results)

    if not args.read_only and args.yes:
        sel = drv.get_selected_job(client, mode="api")
        job = args.job or (
            sel["Name"] if sel else (drv.get_jobs(client, mode="api") or [{}])[0].get("Name")
        )
        phase_changes(client, job, results)
        if args.allow_job_switch:
            phase_select(client, results)
    elif not args.read_only:
        print("\n(reversible writes skipped; pass --yes to run change tests)")

    print("\n" + "=" * 60)
    n = len(results)
    ok = sum(1 for r in results if r[1])
    hangs = sum(1 for r in results if r[3])
    print(f"SUMMARY: parity {ok}/{n}  API timeouts/hangs={hangs}")
    dlg = L.get_pending_dialog()
    if dlg:
        print(f"  NOTE: a modal dialog is open and blocking the CAM API: {dlg!r}")
    fails = [r[0] for r in results if not r[1]]
    if fails:
        print("  FAILURES:", fails)
    return 0 if ok == n else 1


if __name__ == "__main__":
    raise SystemExit(main())
