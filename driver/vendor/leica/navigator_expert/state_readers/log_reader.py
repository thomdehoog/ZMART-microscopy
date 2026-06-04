"""
Log-file state probe.
=====================
Reads LAS X state from the hardware log (``lcsCommand.log``, written by
``LCS.exe``) instead of the NavigatorExpert CAM API. The CAM API can
freeze for seconds while a modal dialog blocks its channel; the log keeps
flowing, so a log read never hangs.

This is a **fresh-state probe, not a drop-in reader**. The log records the
*last value dumped* for each datum, so it is byte-accurate for state LAS X
is actively dumping (current XY, the active job) and can be silently stale
for state that changed without that job being re-dumped. Every datum
carries the timestamp of its log line; callers inspect freshness via
:func:`ages` (including per-job settings age). Ambiguous state (duplicate
job names, unmappable selection) fails closed to ``None`` — never a wrong
value.

Not provided here on purpose: ``ping`` (log mtime is not liveness — keep it
on the API) and any API fallback (that would re-introduce the hang path).
``get_scan_status`` maps the numeric ``AcquisitionState`` to a state string.

Parameters live in ``core.profiles.LOG_READER`` - no hardcoded values in the
read paths.

Dependency direction:
    - Imports: stdlib, ``utils`` (parse_tile_geometry), ``settings``
      (make_changeable_copy), ``readers`` (get_lasx_settings re-export).
    - Imported by: tests / the side-by-side validator. NOT wired into the
      production read path (deferred until validated on hardware).
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime

from ..core.utils import parse_tile_geometry
from ..core.settings import make_changeable_copy
from .api_reader import get_lasx_settings  # disk-based, backend-independent

log = logging.getLogger(__name__)


# =============================================================================
# Profile (all tunables live here)
# =============================================================================

def _profile():
    """Return the active low-level log-reader profile."""
    from ..core import profiles
    return profiles.LOG_READER


# =============================================================================
# Parsing
# =============================================================================

_RE_TS = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d+)")
_RE_XY = re.compile(r'GetStageHwPosition\s+\'<Result HwStagePosX="([^"]+)" HwStagePosY="([^"]+)"')
_RE_SEL = re.compile(r'SetCurrentSelectedElementID"\s+ElementID="(\d+)"')
_RE_ACQ = re.compile(r"AcquisitionState = (\d+)")
_RE_MSGBOX = re.compile(r"MessageBox : (.+)")


def _parse_ts(line):
    """Epoch seconds (local) for a log line's leading timestamp, or None."""
    m = _RE_TS.match(line)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S.%f").timestamp()
    except ValueError:
        return None


def _json_in_line(line):
    """Decode the inline LAS X JSON (``<LF>``/``<TAB>`` tokens) from a line.
    Uses raw_decode from the first ``{`` so trailing wrapper content can't
    corrupt the parse."""
    raw = line.replace("<LF>", "\n").replace("<TAB>", "\t")
    i = raw.find("{")
    if i == -1:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(raw[i:])
        return obj
    except (ValueError, json.JSONDecodeError):
        return None


@dataclass
class Snapshot:
    """Latest value + source-line timestamp for each datum. ``now`` is the
    reference time used for age computations."""
    now: float = 0.0
    xy: tuple = None
    xy_ts: float = None
    atl_by_block: dict = field(default_factory=dict)   # block_id(str) -> (json, ts)
    selected_element: int = None
    selected_ts: float = None
    hw_info: dict = None
    hw_ts: float = None
    scan_state: int = None
    scan_ts: float = None
    pending_dialog: str = None   # open modal dialog text (blocks the CAM API), or None
    pending_dialog_ts: float = None


def parse_log(lcs_path=None, msgbox_path=None, now=None, lines=None):
    """Parse the LAS X logs into a :class:`Snapshot` (single forward pass).

    Latin-1 decode (preserves the µ byte; never utf-8 replacement).
    "Latest valid wins" per datum. Tolerant of partial/malformed final
    lines. ``lines``/``now`` are injectable for tests.
    """
    profile = _profile()
    lcs_path = lcs_path or profile.lcs_log_path
    msgbox_path = msgbox_path or profile.msgbox_log_path
    snap = Snapshot(now=now if now is not None else time.time())

    if lines is None:
        try:
            with open(lcs_path, "r", encoding="latin-1") as f:
                lines = f.readlines()
        except OSError:
            lines = []

    for ln in lines:
        ts = _parse_ts(ln)
        try:
            m = _RE_XY.search(ln)
            if m:
                snap.xy = (float(m.group(1)), float(m.group(2)))
                snap.xy_ts = ts
                continue
            m = _RE_SEL.search(ln)
            if m:
                snap.selected_element = int(m.group(1))
                snap.selected_ts = ts
                continue
            if "ATL_GetBlockApiInfoAsJsonString" in ln and "'<Result" in ln:
                j = _json_in_line(ln)
                # "latest VALID wins": skip blank-imageSize dumps (the engine
                # emits these transiently during a zoom/format change), matching
                # the API reader's staleness guard.
                if (j is not None and j.get("jobName") is not None
                        and j.get("id") is not None and j.get("imageSize")):
                    snap.atl_by_block[str(j["id"])] = (j, ts)
                continue
            if "GetConfocalHardwareInfoAsJson" in ln and "'<Result" in ln:
                j = _json_in_line(ln)
                if j is not None:
                    snap.hw_info, snap.hw_ts = j, ts
                continue
        except (ValueError, AttributeError):
            continue  # tolerate a malformed/partial line

    # scan status + modal-dialog state live in the NavigatorExpert log.
    # Dialog open/close is decided by LINE ORDER (not timestamps, which can tie).
    dialog_open, dialog_text, dialog_ts = False, None, None
    try:
        with open(msgbox_path, "r", encoding="latin-1") as f:
            for ln in f:
                m = _RE_ACQ.search(ln)
                if m:
                    snap.scan_state, snap.scan_ts = int(m.group(1)), _parse_ts(ln)
                    continue
                if "MessageBox Result" in ln:
                    dialog_open = False
                elif "MessageBox :" in ln:
                    mo = _RE_MSGBOX.search(ln)
                    if mo:
                        dialog_open = True
                        dialog_text = mo.group(1).rstrip("' \"\t")
                        dialog_ts = _parse_ts(ln)
    except OSError:
        pass
    if dialog_open:
        snap.pending_dialog = dialog_text
        snap.pending_dialog_ts = dialog_ts

    return snap


# =============================================================================
# Current-block resolution (recency-scoped, fail-closed on ambiguity)
# =============================================================================

def _current_blocks(s, apply_max_age=True, *, max_age_s=None):
    """(name -> (block_id, json, ts) for one block per name among CURRENT
    blocks, set-of-ambiguous-names).

    "Current" = within ``current_window_s`` of the newest ATL dump, so an
    older session's blocks (reassigned ids, possibly same names) are excluded
    rather than guessed at. A name carried by >=2 current blocks is ambiguous
    and fails closed. With ``apply_max_age`` (default), blocks past ``max_age_s``
    are also dropped; ``ages()`` passes False so diagnostics keep refused jobs."""
    items = list(s.atl_by_block.items())
    timestamped = [ts for _, (_, ts) in items if ts is not None]
    newest = max(timestamped) if timestamped else None

    current = []
    for bid, (j, ts) in items:
        if apply_max_age and _too_old(ts, s.now, max_age_s=max_age_s):
            continue
        if newest is None or (ts is not None and ts >= newest - _profile().current_window_s):
            current.append((bid, j, ts))

    by_name = {}
    for bid, j, ts in current:
        name = j.get("jobName")
        if name is not None:
            by_name.setdefault(name, []).append((bid, j, ts))

    latest, ambiguous = {}, set()
    for name, hits in by_name.items():
        if len(hits) >= 2:
            ambiguous.add(name)            # fail closed — don't pick one
        latest[name] = max(hits, key=lambda h: (h[2] is not None, h[2] or 0))
    return latest, ambiguous


def _too_old(ts, now, *, max_age_s=None):
    if max_age_s is None:
        max_age_s = _profile().max_age_s
    if max_age_s is None:
        return False                      # no policy -> expose age, never refuse
    if ts is None:
        return True                       # can't verify freshness under a policy -> refuse
    return (now - ts) > max_age_s


# =============================================================================
# Freshness
# =============================================================================

def ages(snapshot=None):
    """Age in seconds of each datum (None if absent), including per-job
    settings age. Lets callers/tests judge freshness instead of trusting a
    possibly-stale value silently."""
    s = snapshot or parse_log()

    def age(ts):
        return None if ts is None else s.now - ts

    # apply_max_age=False so a job refused for staleness still shows its age here
    latest, _ = _current_blocks(s, apply_max_age=False)
    return {
        "xy": age(s.xy_ts),
        "scan_status": age(s.scan_ts),
        "hardware_info": age(s.hw_ts),
        "selected": age(s.selected_ts),
        "dialog": age(s.pending_dialog_ts),
        "jobs": {name: age(ts) for name, (_, _, ts) in latest.items()},
    }


# =============================================================================
# Readers (API-shaped values; None when stale/ambiguous/absent — never wrong)
# =============================================================================

def get_xy(snapshot=None, *, max_age_s=None):
    s = snapshot or parse_log()
    if s.xy is None or _too_old(s.xy_ts, s.now, max_age_s=max_age_s):
        return None
    x, y = s.xy
    return {"x": x, "y": y, "x_um": x * 1e6, "y_um": y * 1e6}


def get_job_settings(job_name, snapshot=None, *, max_age_s=None):
    s = snapshot or parse_log()
    latest, ambiguous = _current_blocks(s, max_age_s=max_age_s)
    if job_name in ambiguous or job_name not in latest:
        if job_name in ambiguous:
            log.warning("log_reader: ambiguous job name %r (>=2 current blocks)", job_name)
        return None
    _bid, j, ts = latest[job_name]
    if _too_old(ts, s.now, max_age_s=max_age_s):
        return None
    return j


def _block_id_int(bid):
    try:
        return int(bid)
    except (TypeError, ValueError):
        return None


def get_jobs(snapshot=None, *, max_age_s=None):
    """Jobs present in the *current* dump cluster, with selection. Note: this is
    a passive list — a job not (re)dumped this session is absent, so the list can
    be shorter than the API's. `IsSelected` is None unless selection can be mapped
    safely. Honors `max_age_s` (stale blocks are dropped)."""
    s = snapshot or parse_log()
    latest, ambiguous = _current_blocks(s, max_age_s=max_age_s)
    if not latest:
        return None
    ids_ok = all(_block_id_int(v[0]) is not None for v in latest.values())
    ordered = (sorted(latest.items(), key=lambda kv: _block_id_int(kv[1][0]))
               if ids_ok else list(latest.items()))
    # SetCurrentSelectedElementID is a 1-based index into the FULL job sequence.
    # Mapping it onto the current cluster is only safe when the cluster is the
    # complete job list — otherwise a partial re-dump shifts positions and we'd
    # return the wrong job. Require every observed job name to be current; else
    # fail closed (IsSelected = None).
    all_names = {j.get("jobName") for (j, _t) in s.atl_by_block.values() if j.get("jobName")}
    complete = set(latest.keys()) == all_names
    sel = s.selected_element
    can_map = (complete and ids_ok and not ambiguous and sel is not None
               and not _too_old(s.selected_ts, s.now, max_age_s=max_age_s)
               and 1 <= sel <= len(ordered))
    out = []
    for idx, (name, _bjt) in enumerate(ordered, start=1):
        out.append({"Name": name, "IsSelected": (idx == sel) if can_map else None})
    return out


def get_selected_job(snapshot=None, *, max_age_s=None):
    jobs = get_jobs(snapshot, max_age_s=max_age_s)
    if not jobs:
        return None
    sel = [j for j in jobs if j.get("IsSelected") is True]
    return sel[0] if len(sel) == 1 else None


def get_job_by_name(job_name, snapshot=None, *, max_age_s=None):
    jobs = get_jobs(snapshot, max_age_s=max_age_s)
    if jobs:
        for j in jobs:
            if j.get("Name") == job_name:
                return j
    return None


def get_hardware_info(snapshot=None, *, max_age_s=None):
    s = snapshot or parse_log()
    if s.hw_info is None or _too_old(s.hw_ts, s.now, max_age_s=max_age_s):
        return None
    return s.hw_info


# AcquisitionState -> driver scan-status string. 0 = idle (confirmed on sim);
# any non-zero acquisition state maps to a running string. Re-confirm the
# non-idle codes on real hardware. Returns "Unknown" if absent or too old.
def get_scan_status(snapshot=None, *, max_age_s=None):
    s = snapshot or parse_log()
    if s.scan_state is None or _too_old(s.scan_ts, s.now, max_age_s=max_age_s):
        return "Unknown"
    return "eScanIdle" if s.scan_state == 0 else "eScanRunning"


def get_pending_dialog(snapshot=None):
    """Text of an open modal dialog (e.g. the manual-turret box) that is
    blocking the CAM API right now, or None. Lets a caller explain an API
    hang instead of timing out blindly — the API can't report this because
    it is the thing being blocked.

    Freshness caveat: detection is by line order (an unmatched ``MessageBox :``
    with no later ``Result:``). An unmatched open left by a *crashed* prior
    session would look open forever. Before wiring this into command-error
    handling, check ``ages()["dialog"]`` and treat an implausibly old open as
    stale (a genuinely-open modal blocks NavigatorExpert, so it is normally the
    most recent log activity)."""
    s = snapshot or parse_log()
    return s.pending_dialog


def get_fov(job_name, snapshot=None, *, max_age_s=None):
    settings = get_job_settings(job_name, snapshot, max_age_s=max_age_s)
    if not settings:
        return None
    try:
        geo = parse_tile_geometry(settings)
        return (geo["tile_w_um"] * 1e-6, geo["tile_h_um"] * 1e-6)
    except (ValueError, KeyError):
        return None


def get_base_fov(job_name, snapshot=None, *, max_age_s=None):
    settings = get_job_settings(job_name, snapshot, max_age_s=max_age_s)
    if not settings:
        return None
    try:
        geo = parse_tile_geometry(settings)
        zoom = float((settings.get("zoom") or {}).get("current", 1) or 1)
        zoom = zoom if zoom >= 1 else 1
        return (geo["tile_w_um"] * 1e-6 * zoom, geo["tile_h_um"] * 1e-6 * zoom)
    except (ValueError, KeyError):
        return None


def read_zwide_um(job_name, snapshot=None, *, max_age_s=None):
    """Live z-wide (µm) for *job_name*. Raises RuntimeError if unavailable —
    parity with the API reader."""
    settings = get_job_settings(job_name, snapshot, max_age_s=max_age_s)
    if not settings:
        raise RuntimeError(f"log_reader: no fresh settings for '{job_name}'")
    ch = make_changeable_copy(settings)
    if not ch or "zPosition" not in ch:
        raise RuntimeError("log_reader: zPosition not in job settings")
    val = ch["zPosition"].get("z-wide")
    if val is None:
        raise RuntimeError(f"log_reader: z-wide readback missing; got {ch['zPosition']!r}")
    return float(val)
