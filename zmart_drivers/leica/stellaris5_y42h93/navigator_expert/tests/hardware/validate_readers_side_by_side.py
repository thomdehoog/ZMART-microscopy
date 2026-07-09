"""
Side-by-side reader validation: CAM API vs log_reader, plus routed modes.
=========================================================================
Runs against a live LAS X session (simulator or scope). Compares the
production API readers against ``readers.log_reader`` and reports:

  - CORRECTNESS/PARITY: gate on the contract fields the driver actually
    uses, with tolerances (both-None counts as a match). A full dict diff
    would be brittle on harmless vendor metadata. For changes, polls each
    backend for the *expected* value in a bounded window so a valid-but-stale
    log read can't false-fail. EVERY printed check counts toward the exit code.
  - READER MODES: every routed datum (xy / jobs / selected_job / scan_status /
    hardware_info / job_settings) is read explicitly in mode="api",
    mode="log", AND mode="hybrid" through readers.router, recording value,
    provenance/freshness (age), and latency per mode, then cross-checks the
    modes against each other (xy within 1 um; discrete values equal).
    Disagreements are recorded as findings, not crashes.
  - PERFORMANCE: per-backend read latency, API timeout/hang count.
  - FRESHNESS: the age of each log datum, including per-job settings age.
  - DIALOG: whether a modal box is currently blocking the CAM API.

Run order (fail fast): read-only parity -> routed reader modes ->
high-signal write set -> (optional) selected-job round-trip. Reversible
writes only; every write restored in a finally. Stage/objective/acquire are
NOT touched. The job-switch round-trip is gated behind --allow-job-switch
(it pops the manual-turret dialog and blocks the CAM API); default runs are
click-free.

Every attempted change (including restores) is written to a Markdown run
report (hardware_run_report_<YYYYMMDD-HHMMSS>.md; --report-dir to redirect).

--mock swaps in the in-process Python mock (tests/helpers/mock_lasx_api.py)
so the script's execution path can be proven offline. The mock has no LAS X
log stream, so log-side parity checks record SKIP there instead of FAIL.

Usage:
  python validate_readers_side_by_side.py --read-only
  python validate_readers_side_by_side.py --yes
  python validate_readers_side_by_side.py --yes --allow-job-switch
  python validate_readers_side_by_side.py --log-path X.log
  python validate_readers_side_by_side.py --mock            # offline smoke
"""

import argparse
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # vendor/leica
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests/hardware
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "helpers"))  # mock

import navigator_expert as drv
from _report import RunReport, attempts_of, confirmation_of, replay_envelope_logs
from navigator_expert import readers
from navigator_expert.commands.settings import make_changeable_copy
from navigator_expert.config import profiles
from navigator_expert.readers import capabilities
from navigator_expert.readers import log_reader as L
from navigator_expert.utils import parse_tile_geometry

API_HANG_MS = 1500.0  # an API read slower than this is treated as a dialog-hang

ROUTED_DATUMS = ("xy", "jobs", "selected_job", "scan_status", "hardware_info", "job_settings")
READER_MODES = ("api", "log", "hybrid")


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


def _ms(x):
    return f"{x:.0f}ms" if x is not None else "TIMEOUT"


class Rec:
    """Console rows + exit-code accounting + run-report entries in one place."""

    def __init__(self, report, *, mock):
        self.rows = []  # (key, ok, latency_ms, hang, skipped)
        self.report = report
        self.mock = mock
        self.phase = "setup"

    def row(
        self,
        key,
        ok,
        extra="",
        *,
        hang=False,
        latency=0.0,
        skip=False,
        mutating=False,
        expected="",
        args="",
        confirmation="",
        attempts="",
        reader_mode="",
        age_s=None,
    ):
        tag = "-- " if skip else ("OK " if ok else "XX ")
        print(f"  {tag} {key:<40} {extra}")
        self.rows.append((key, ok, latency, hang, skip))
        if self.report is not None:
            self.report.add(
                phase=self.phase,
                action=key,
                args=args,
                expected=str(expected),
                observed=extra,
                status="SKIP" if skip else ("PASS" if ok else "FAIL"),
                duration_s=latency / 1000.0,
                mutates_scope=mutating,
                confirmation=confirmation,
                attempts=attempts,
                reader_mode=reader_mode,
                age_s=age_s,
            )
        return ok

    def parity(
        self,
        key,
        ok,
        extra="",
        *,
        log_missing=False,
        log_unsupported=False,
        latency=0.0,
        hang=False,
    ):
        """A parity check that SKIPs (with reason) when the log side cannot
        answer: either the datum has no authoritative log leg at all
        (``log_unsupported`` -- e.g. the job LIST is API-only, so a log-vs-api
        comparison has nothing trustworthy to compare against), or the --mock
        backend simply has no LAS X log stream (``log_missing``)."""
        if log_unsupported:
            return self.row(
                key,
                True,
                "no authoritative log leg for this datum (API-only); " + extra,
                skip=True,
                latency=latency,
            )
        if log_missing and self.mock:
            return self.row(
                key,
                True,
                "log leg unavailable under --mock (no LAS X log stream)",
                skip=True,
                latency=latency,
            )
        return self.row(key, ok, extra, latency=latency, hang=hang)

    def counts(self):
        fails = [r[0] for r in self.rows if not r[1] and not r[4]]
        skips = sum(1 for r in self.rows if r[4])
        hangs = sum(1 for r in self.rows if r[3])
        return fails, skips, hangs


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


def _settings_diffs(af, lf):
    """Contract-field keys that disagree between two settings snapshots."""
    keys = set(af) | set(lf)  # union -> a key on only one side is a clean diff
    return [
        k
        for k in sorted(keys)
        if not _ceq(
            af.get(k),
            lf.get(k),
            0.05 if k.endswith("pinholeAiry") else (0.1 if k == "zoom" else None),
        )
    ]


# --- FD-12 fix: profile-sourced polling knobs --------------------------------
#
# The original script referenced profiles.LOG_READER.poll_timeout and
# .poll_interval, which have NEVER existed on LogReaderProfile (that profile
# only holds log paths + freshness windows), so the live-changes phase died
# with AttributeError before touching the instrument. The intended knobs -- a
# bounded wait window for an expected value to appear, plus a poll interval --
# live on profiles.STATE_READERS: the per-datum ``*_timeout_s`` read budgets
# and the ``selected_job_log_poll_*`` fields used by readers/log_wait.py.


def _change_poll_params():
    """(wait_window_s, poll_interval_s) for a post-change settings readback."""
    sr = profiles.STATE_READERS
    window = max(sr.job_settings_timeout_s, sr.selected_job_log_poll_timeout_s)
    return window, sr.selected_job_log_poll_interval_s


def _select_poll_params():
    """(wait_window_s, poll_interval_s) for a post-select-job readback."""
    sr = profiles.STATE_READERS
    return sr.selected_job_log_poll_timeout_s, sr.selected_job_log_poll_interval_s


# --- phases ----------------------------------------------------------------


def phase_readonly(client, rec):
    print("\n=== READ-ONLY PARITY (current state) ===")
    rec.phase = "read-only parity"
    # ONE consistent log snapshot for the whole round so calls don't disagree
    # with each other while a live sim is mid-redump.
    snap = L.parse_log()
    ag = L.ages(snap)
    dlg = L.get_pending_dialog(snap)
    if dlg:
        print(f"  !! modal dialog OPEN (CAM API is blocked): {dlg!r}")
        rec.report.note(f"Modal dialog open during read-only parity: {dlg!r}")

    axy, alat, _ = _timed(lambda: drv.get_xy(client, mode="api"))
    lxy = L.get_xy(snap)
    if axy is None and lxy is not None:
        rec.row(
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
        rec.parity(
            "get_xy",
            ok,
            f"api={alat:.0f}ms" + (f" log_age={ag['xy']:.0f}s" if ag["xy"] else ""),
            log_missing=lxy is None,
            hang=alat > API_HANG_MS,
            latency=alat,
        )

    jobs_log_leg = capabilities.DATUMS["jobs"].log_fn is not None
    ajobs, alat, _ = _timed(lambda: drv.get_jobs(client, mode="api"))
    ljobs = L.get_jobs(snap)
    an = sorted(j["Name"] for j in (ajobs or []))
    ln = sorted(j["Name"] for j in (ljobs or []))
    # The job LIST is API-only: the log stream's job-name cluster omits jobs
    # not re-dumped this session, so an api-vs-log list comparison is expected
    # to disagree on real hardware. Skip the list parity when jobs has no log
    # leg -- the routed reader-modes phase still exercises jobs via api/hybrid.
    rec.parity(
        "get_jobs (names)",
        an == ln,
        f"api={an} log={ln}",
        log_missing=ljobs is None,
        log_unsupported=not jobs_log_leg,
        latency=alat,
        hang=alat > API_HANG_MS,
    )
    # Selection DOES have an authoritative log leg (the selected_job datum),
    # unlike the job list -- compare the API selection against the log's
    # selected-job reader directly, not against the incomplete job-name cluster.
    api_selected = next((j["Name"] for j in (ajobs or []) if j.get("IsSelected")), None)
    lsel_job = L.get_selected_job(snap)
    log_selected = lsel_job.get("Name") if lsel_job else None
    rec.parity(
        "get_selected_job",
        api_selected == log_selected,
        f"api={api_selected!r} log={log_selected!r}",
        log_missing=log_selected is None,
    )

    astat = drv.get_scan_status(client, mode="api")
    lstat = L.get_scan_status(snap)
    rec.parity(
        "get_scan_status (idle-sense)",
        ("Idle" in str(astat)) == ("Idle" in str(lstat)),
        f"api={astat!r} log={lstat!r}"
        + (f" log_age={ag['scan_status']:.0f}s" if ag["scan_status"] else ""),
        log_missing=lstat in (None, "Unknown"),
    )

    ahw, _, _ = _timed(lambda: drv.get_hardware_info(client, mode="api"))
    lhw = L.get_hardware_info(snap)
    hw_ok = (
        bool(ahw)
        and bool(lhw)
        and (ahw.get("Microscope", {}).get("name") == lhw.get("Microscope", {}).get("name"))
    )
    rec.parity("get_hardware_info (Microscope.name)", hw_ok, log_missing=lhw is None)

    for job in ln or an:
        araw = drv.get_job_settings(client, job, mode="api")
        lraw = L.get_job_settings(job, snap)
        af, lf = contract_fields(araw), contract_fields(lraw)
        jage = ag["jobs"].get(job)
        if af is None or lf is None:
            rec.parity(
                f"settings[{job}]",
                False,
                f"api={af is not None} log={lf is not None}"
                + (f"  (log_age={jage:.0f}s)" if jage is not None else ""),
                log_missing=lf is None,
            )
            continue
        diffs = _settings_diffs(af, lf)
        rec.row(
            f"settings[{job}] ({len(set(af) | set(lf))} fields)",
            not diffs,
            (f"log_age={jage:.0f}s" if jage is not None else "")
            + ("" if not diffs else f"  DIFFS {[(k, af.get(k), lf.get(k)) for k in diffs]}"),
        )
        afov, lfov = drv.get_fov(client, job, mode="api"), L.get_fov(job, snap)
        rec.parity(
            f"get_fov[{job}]",
            bool(afov and lfov and _eq(afov[0] * 1e6, lfov[0] * 1e6, 0.5)),
            f"api={afov} log={lfov}",
            log_missing=lfov is None,
        )
        try:
            az = drv.read_zwide_um(client, job, mode="api")
        except Exception as e:  # noqa: BLE001
            az = f"<{e}>"
        try:
            lz = L.read_zwide_um(job, snap)
        except Exception as e:  # noqa: BLE001
            lz = f"<{e}>"
        rec.parity(
            f"read_zwide_um[{job}]",
            _eq(az, lz, 0.1),
            f"api={az} log={lz}",
            log_missing=lz is None,
        )
    return [j["Name"] for j in (ajobs or [])], api_selected


# --- routed reader modes (api / log / hybrid) --------------------------------


def _routed_read(client, datum, mode, job):
    if datum == "xy":
        return readers.get_xy(client, mode=mode, diagnostics=True)
    if datum == "jobs":
        return readers.get_jobs(client, mode=mode, diagnostics=True)
    if datum == "selected_job":
        return readers.get_selected_job(client, mode=mode, diagnostics=True)
    if datum == "scan_status":
        return readers.get_scan_status(client, mode=mode, diagnostics=True)
    if datum == "hardware_info":
        return readers.get_hardware_info(client, mode=mode, diagnostics=True)
    if datum == "job_settings":
        return readers.get_job_settings(client, job, mode=mode, diagnostics=True)
    raise ValueError(f"unknown routed datum {datum!r}")


def _routed_summary(datum, value):
    if value is None:
        return "None"
    if datum == "xy":
        return f"({value['x_um']:.1f},{value['y_um']:.1f})um"
    if datum == "jobs":
        return f"{sorted(j.get('Name') for j in value)}"
    if datum == "selected_job":
        return f"{value.get('Name')!r}"
    if datum == "scan_status":
        return f"{value!r}"
    if datum == "hardware_info":
        return f"Microscope={value.get('Microscope', {}).get('name')!r}"
    if datum == "job_settings":
        fields = contract_fields(value)
        return f"{len(fields)} contract fields" if fields else "unparseable"
    return repr(value)[:80]


def _routed_agree(datum, a, b):
    """(ok, detail) cross-check of two routed values of the same datum."""
    if datum == "xy":
        dx, dy = abs(a["x_um"] - b["x_um"]), abs(a["y_um"] - b["y_um"])
        return (dx <= 1.0 and dy <= 1.0), f"delta=({dx:.2f},{dy:.2f})um tol=1.0um"
    if datum == "jobs":
        an = sorted(j.get("Name") for j in a)
        bn = sorted(j.get("Name") for j in b)
        return an == bn, f"{an} vs {bn}"
    if datum == "selected_job":
        return a.get("Name") == b.get("Name"), f"{a.get('Name')!r} vs {b.get('Name')!r}"
    if datum == "scan_status":
        return ("Idle" in str(a)) == ("Idle" in str(b)), f"{a!r} vs {b!r} (idle-sense)"
    if datum == "hardware_info":
        an = a.get("Microscope", {}).get("name")
        bn = b.get("Microscope", {}).get("name")
        return an == bn, f"{an!r} vs {bn!r}"
    if datum == "job_settings":
        af, bf = contract_fields(a), contract_fields(b)
        if af is None or bf is None:
            return False, "unparseable settings"
        diffs = _settings_diffs(af, bf)
        return not diffs, ("all contract fields agree" if not diffs else f"DIFFS {diffs}")
    return a == b, ""


def phase_reader_modes(client, rec, job):
    """Read every routed datum explicitly in api, log, AND hybrid mode.

    Records value/provenance/freshness/latency per mode and cross-checks the
    modes against each other. A log-mode None is the router's fail-closed
    answer (no fresh-enough log value) and is recorded as SKIP -- a finding,
    not a failure; the read-only parity phase grades raw log correctness
    separately. A hybrid None while api delivered means the hybrid leg was
    blocked or the API hung mid-race; recorded as a structured failure, not
    a crash.
    """
    print("\n=== ROUTED READER MODES (api / log / hybrid per datum) ===")
    rec.phase = "routed reader modes"
    for datum in ROUTED_DATUMS:
        if datum == "job_settings" and not job:
            rec.row("modes[job_settings]", True, "no job available", skip=True)
            continue
        values = {}
        for mode in READER_MODES:
            reading, lat, err = _timed(lambda m=mode, d=datum: _routed_read(client, d, m, job))
            value = getattr(reading, "value", None)
            age = getattr(reading, "age_s", None)
            source = getattr(reading, "source", None)
            rerr = getattr(reading, "error", None)
            values[mode] = value
            key = f"read[{datum}] mode={mode}"
            detail = (
                f"value={_routed_summary(datum, value)} source={source} "
                f"age={'-' if age is None else f'{age:.2f}s'} latency={lat:.0f}ms"
            )
            if err is not None:
                rec.row(key, False, f"raised {err}", latency=lat, reader_mode=mode)
            elif value is not None:
                rec.row(key, True, detail, latency=lat, reader_mode=mode, age_s=age)
            elif mode == "log":
                rec.row(
                    key,
                    True,
                    "no trusted log value (stale/absent log stream; router fails closed)"
                    + (f" err={rerr!r}" if rerr else ""),
                    skip=True,
                    latency=lat,
                    reader_mode=mode,
                )
            elif mode == "hybrid" and values.get("api") is not None:
                rec.row(
                    key,
                    False,
                    "hybrid returned no value while api did -- hybrid leg blocked or API hang",
                    latency=lat,
                    reader_mode=mode,
                )
                rec.report.note(
                    f"hybrid read of {datum!r} returned no value while the api leg "
                    "delivered -- hybrid leg blocked or API hang; investigate."
                )
            else:
                rec.row(
                    key,
                    False,
                    f"no value (source={source} err={rerr!r})",
                    latency=lat,
                    reader_mode=mode,
                )
        # Cross-mode agreement (baseline: api).
        base = values.get("api")
        for mode in ("log", "hybrid"):
            other = values.get(mode)
            key = f"agree[{datum}] api vs {mode}"
            if base is None or other is None:
                rec.row(key, True, "insufficient values to cross-check", skip=True)
                continue
            ok, detail = _routed_agree(datum, base, other)
            rec.row(key, ok, detail)


def _poll_both(api_read, log_read, expected, tol, timeout, interval, *, need_log=True):
    """Poll both backends from one t0. The LOG poller runs on its own thread
    (file-only, CAM-independent) so an API hang/timeout can't starve it and
    false-fail the log. ``need_log=False`` (--mock: no log stream exists)
    stops as soon as the API leg matches instead of waiting out the window.
    Returns (api_ms, log_ms, api_hang)."""
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
        if api_ms is not None and (box["log_ms"] is not None or not need_log):
            break
        time.sleep(interval)
    if need_log:
        th.join(timeout=max(0.1, timeout - (time.perf_counter() - t0)) + 0.5)
    return api_ms, box["log_ms"], api_hang


def phase_changes(client, job, rec):
    print(f"\n=== LIVE CHANGES on '{job}' (reversible; restored) ===")
    rec.phase = "live changes (reversible)"
    pt, pi = _change_poll_params()
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
            rec.row(f"change[{name}]", False, "cannot read current")
            continue
        cur = readfn(cur_ch)
        target = next((c for c in cands if not _eq(c, cur, tol)), None)
        if target is None:
            rec.row(f"change[{name}]", False, "no alternate candidate")
            continue

        def api_read(readfn=readfn):
            raw = drv.get_job_settings(client, job, mode="api")
            return readfn(_ch(raw)) if raw else None

        def log_read(readfn=readfn):
            raw = L.get_job_settings(job)
            return readfn(_ch(raw)) if raw else None

        try:
            res, set_ms, set_err = _timed(lambda f=setfn, t=target: f(job, t))
            if isinstance(res, dict):
                replay_envelope_logs(res, label=f"change[{name}]")
            if set_err is not None or not (res or {}).get("success"):
                rec.row(
                    f"change[{name}] -> {target}",
                    False,
                    f"set failed: {set_err or (res or {}).get('message')}",
                    latency=set_ms,
                    mutating=True,
                    expected=target,
                    args=f"job={job!r} target={target!r} (was {cur!r})",
                    confirmation="FAILED",
                )
                continue
            api_ms, log_ms, hang = _poll_both(
                api_read, log_read, target, tol, pt + 1.0, pi, need_log=not rec.mock
            )
            if rec.mock:
                # No LAS X log stream behind the mock: grade the API leg only.
                ok = api_ms is not None
                earlier = "api"
            else:
                ok = api_ms is not None and log_ms is not None
                earlier = "tie" if not ok else ("log" if log_ms < api_ms else "api")
            rec.row(
                f"change[{name}] -> {target}",
                ok,
                f"set={set_ms:.0f}ms api={_ms(api_ms)} log={_ms(log_ms)} earlier={earlier}"
                + ("  API-HANG" if hang else "")
                + ("  (log leg not graded under --mock)" if rec.mock else ""),
                hang=hang or api_ms is None,
                latency=(set_ms or 0) + (api_ms or 0),
                mutating=True,
                expected=target,
                args=f"job={job!r} target={target!r} (was {cur!r})",
                confirmation=confirmation_of(res),
                attempts=attempts_of(res),
            )
        finally:
            rres, r_ms, r_err = _timed(lambda f=setfn, c=cur: f(job, c))
            rec.row(
                f"restore[{name}] -> {cur}",
                r_err is None and bool((rres or {}).get("success")),
                f"restore={_ms(r_ms)}" + (f" err={r_err}" if r_err else ""),
                latency=r_ms or 0,
                mutating=True,
                expected=cur,
                args=f"job={job!r} restore_to={cur!r}",
                confirmation="FAILED" if r_err else confirmation_of(rres or {}),
                attempts="" if r_err else attempts_of(rres or {}),
            )


def phase_select(client, rec):
    print("\n=== SELECT-JOB round trip (gated; may pop the objective dialog) ===")
    rec.phase = "select-job round trip"
    pt, pi = _select_poll_params()
    names = [j["Name"] for j in (drv.get_jobs(client, mode="api") or [])]
    original = (drv.get_selected_job(client, mode="api") or {}).get("Name")
    try:
        for n in names:
            res, sel_ms, sel_err = _timed(lambda n=n: drv.select_job(client, n))
            api_ms, log_ms, _ = _poll_both(
                lambda: (drv.get_selected_job(client, mode="api") or {}).get("Name"),
                lambda: (L.get_selected_job() or {}).get("Name"),
                n,
                None,
                pt + 1.0,
                pi,
                need_log=not rec.mock,
            )
            if rec.mock:
                both = api_ms is not None
            else:
                both = api_ms is not None and log_ms is not None
            dlg = L.get_pending_dialog()
            note = f"  [BLOCKED BY DIALOG: {dlg!r}]" if dlg else ""
            rec.row(
                f"select[{n}]",
                both and sel_err is None,
                f"select={_ms(sel_ms)} api={_ms(api_ms)} log={_ms(log_ms)}{note}"
                + (f" err={sel_err}" if sel_err else ""),
                hang=api_ms is None,
                latency=(sel_ms or 0) + (api_ms or 0),
                mutating=True,
                expected=n,
                args=f"select_job -> {n!r}",
                confirmation="FAILED" if sel_err else confirmation_of(res or {}),
                attempts="" if sel_err else attempts_of(res or {}),
            )
    finally:
        if original:
            rres, r_ms, r_err = _timed(lambda: drv.select_job(client, original))
            rec.row(
                f"select: restore[{original}]",
                r_err is None and bool((rres or {}).get("success")),
                f"restore={_ms(r_ms)}" + (f" err={r_err}" if r_err else ""),
                latency=r_ms or 0,
                mutating=True,
                expected=original,
                args=f"select_job -> {original!r} (restore)",
                confirmation="FAILED" if r_err else confirmation_of(rres or {}),
                attempts="" if r_err else attempts_of(rres or {}),
            )


def _connect(args):
    if args.mock:
        from limits_fixtures import hermetic_mock_machine_root  # noqa: PLC0415
        from mock_lasx_api import MockLasxClient  # noqa: PLC0415

        # Use a hermetic ProgramData fixture so the REAL limits handshake runs
        # without touching this developer machine.
        root = hermetic_mock_machine_root()
        print("Connect: mock (in-process MockLasxClient)")
        print(f"Limits: hermetic machine root provisioned at {root}")
        return MockLasxClient(latency=args.mock_latency)
    from navigator_expert.connection.lasx_runtime import load_lasx_api_runtime  # noqa: PLC0415

    lasx_api = load_lasx_api_runtime()
    client = lasx_api.LasxApiClientPyModel
    print("Connect:", client.Connect(args.client_name))
    return client


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
    p.add_argument(
        "--mock",
        action="store_true",
        help="use the in-process Python mock (offline; log-side checks SKIP)",
    )
    p.add_argument("--mock-latency", type=float, default=0.0)
    p.add_argument(
        "--report-dir",
        default=None,
        help="directory for the Markdown run report (default: working directory)",
    )
    args = p.parse_args(argv)

    if args.log_path:
        profiles.LOG_READER = profiles.LogReaderProfile(lcs_log_path=args.log_path)
    if args.mock:
        # The mock backend has no LAS X log stream, so the default hybrid
        # select-job confirmation race would only ever time out on the log leg
        # (same pinning as validate_hardware --mock).
        from dataclasses import replace  # noqa: PLC0415

        profiles.STATE_READERS = replace(profiles.STATE_READERS, selected_job_confirm_source="api")

    report = RunReport(
        script="validate_readers_side_by_side",
        backend=(
            "mock (in-process MockLasxClient; no instrument touched)"
            if args.mock
            else "live LAS X (simulator or scope)"
        ),
        report_dir=args.report_dir,
        argv=list(argv) if argv is not None else sys.argv[1:],
    )
    rec = Rec(report, mock=args.mock)
    crash = None
    try:
        client = _connect(args)

        # Connect-time limits handshake: the write phases fire real command
        # wrappers, which refuse fail-closed without validated machine-local
        # limits. Read phases are ungated; a failed handshake only blocks
        # the mutating phases.
        limits_state = drv.connect_limits_handshake(client)
        if not limits_state.ok:
            print(f"limits handshake FAILED: {limits_state.error}")
            if not args.read_only and args.yes:
                # every write phase would refuse fail-closed; record one
                # actionable failure instead of a wall of refusals
                rec.row("limits handshake", False, limits_state.error)
                args = argparse.Namespace(**{**vars(args), "read_only": True})

        jobs, selected = phase_readonly(client, rec)
        job = args.job or selected or next(iter(jobs), None)
        phase_reader_modes(client, rec, job)

        if not args.read_only and args.yes:
            if job:
                phase_changes(client, job, rec)
            else:
                rec.row("live changes", False, "no job available for the write set")
            if args.allow_job_switch:
                phase_select(client, rec)
        elif not args.read_only:
            print("\n(reversible writes skipped; pass --yes to run change tests)")
    except BaseException as exc:
        crash = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        print("\n" + "=" * 60)
        fails, skips, hangs = rec.counts()
        n = len(rec.rows)
        ok = n - len(fails) - skips
        print(f"SUMMARY: parity {ok}/{n - skips}  skipped={skips}  API timeouts/hangs={hangs}")
        dlg = L.get_pending_dialog()
        if dlg:
            print(f"  NOTE: a modal dialog is open and blocking the CAM API: {dlg!r}")
            report.note(f"Modal dialog open at end of run: {dlg!r}")
        if fails:
            print("  FAILURES:", fails)
        try:
            path = report.write(crashed=crash)
        except OSError as exc:
            print(f"  could not write markdown run report: {exc}")
        else:
            print(f"  markdown run report: {path}")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
