"""
Command allowlist -- the mesoSPIM API the server accepts (no exec).
==================================================================
Restricted Remote Scripting runs **no client Python**. The client sends one
named call -- a single-key JSON object ``{"<method>": {args}}``; the server looks
the method up in :data:`COMMANDS` -- a fixed table -- and runs the matching mesoSPIM
Core call. An unknown method is rejected before anything touches the instrument, so
this table *is* the allowlist. In every handler ``core`` is the live ``mesoSPIM_Core``.

Each handler is ``fn(core, args) -> dict`` (the JSON result). Writes return
``{}`` (the driver confirms by reading state back); reads build the result from
``core``. Verified against mesoSPIM-control v1.20.0.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

_AXES = ("x", "y", "z", "f", "theta")


# -- writes: the only calls that touch the instrument ------------------------


def _move_absolute(core, a):
    core.move_absolute({k + "_abs": float(v) for k, v in a["targets"].items()}, wait_until_done=True)
    return {}


def _move_relative(core, a):
    core.move_relative({k + "_rel": float(v) for k, v in a["deltas"].items()}, wait_until_done=True)
    return {}


def _zero(core, a):
    core.zero_axes(list(a.get("axes") or _AXES))
    return {}


def _stop(core, a):
    core.sig_stop_movement.emit()
    return {}


def _set_state(core, a):
    core.sig_state_request_and_wait_until_done.emit(dict(a["settings"]))
    return {}


# -- reads: build a result from core, no hardware effect ---------------------


def _hello(core, a):
    cfg = getattr(core, "cfg", None)
    return {"app": "mesoSPIM-control", "version": getattr(cfg, "version", None),
            "protocol": 1, "state": (core.state or {}).get("state")}


def _ping(core, a):
    return {"pong": True, "state": (core.state or {}).get("state")}


def _get_position(core, a):
    pos = (core.state or {}).get("position", {}) or {}
    return {ax: pos.get(ax, pos.get(ax + "_pos")) for ax in _AXES}


def _get_state(core, a):
    st = core.state or {}
    pos = st.get("position", {}) or {}
    keys = ("laser", "intensity", "filter", "zoom", "shutterconfig",
            "etl_l_amplitude", "etl_l_offset", "etl_r_amplitude", "etl_r_offset")
    out = {"state": st.get("state"),
           "position": {ax: pos.get(ax, pos.get(ax + "_pos")) for ax in _AXES}}
    out.update({k: st.get(k) for k in keys})
    return out


def _get_config(core, a):
    cfg = getattr(core, "cfg", None)
    get = lambda n: (getattr(cfg, n, None) or {})  # noqa: E731 - a terse local alias
    ld = get("laserdict")
    lasers = [{"name": n, "wavelength_nm": int("".join(c for c in str(n) if c.isdigit()) or 0) or None}
              for n in ld]
    zd = get("zoomdict")
    zooms = [{"name": z, "pixel_size_um": zd.get(z) if isinstance(zd, dict)
              and isinstance(zd.get(z), (int, float)) else None} for z in zd]
    return {"app": "mesoSPIM-control", "version": getattr(cfg, "version", None),
            "lasers": lasers, "filters": list(get("filterdict")), "zooms": zooms,
            "shutter_configs": list(getattr(cfg, "shutteroptions", ["Left", "Right", "Both"])),
            "axes": list(_AXES),
            "camera": {"pixels_x": int(getattr(cfg, "camera_x_pixels", 2048) or 2048),
                       "pixels_y": int(getattr(cfg, "camera_y_pixels", 2048) or 2048)}}


def _get_progress(core, a):
    st = core.state or {}
    return {"state": st.get("state"), "current_plane": st.get("current_framenumber"),
            "total_planes": st.get("snap_count"), "current_acquisition": st.get("current_acquisition"),
            "total_acquisitions": st.get("total_acquisitions")}


# -- acquisition: three calls so none blocks in the Core event loop ----------


def _acquire_start(core, a):
    import os
    try:
        from mesoSPIM.src.utils.acquisitions import Acquisition, AcquisitionList
    except ImportError:
        from utils.acquisitions import Acquisition, AcquisitionList
    acq = dict(a["acquisition"])
    obj = Acquisition()
    obj.update({k: v for k, v in acq.items() if v is not None})
    st = core.state
    try:
        core._zmart_prev_acq_list = (True, st["acq_list"])  # stash the operator's list on the Core
    except (KeyError, TypeError):
        core._zmart_prev_acq_list = (False, None)
    st["acq_list"] = AcquisitionList([obj])
    core.start(row=0)  # the real Core entry point; the Tiff writer makes one stack
    cfg = getattr(core, "cfg", None)
    fname = acq.get("filename") or ""
    return {"started": True,
            "files": [os.path.join(acq.get("folder") or "", fname)] if fname else [],
            "planes": int(acq.get("planes", 1) or 1),
            "pixels": [int(getattr(cfg, "camera_x_pixels", 2048) or 2048),
                       int(getattr(cfg, "camera_y_pixels", 2048) or 2048)]}


def _stat_files(core, a):
    import os
    files = [str(f) for f in (a.get("files") or [])]
    return {"missing": [f for f in files if not os.path.isfile(f)],
            "sizes": {f: os.path.getsize(f) for f in files if os.path.isfile(f)}}


def _acquire_finish(core, a):
    st = core.state
    had, prev = getattr(core, "_zmart_prev_acq_list", (False, None))
    if had:
        st["acq_list"] = prev
    else:
        try:
            del st["acq_list"]
        except Exception:
            st["acq_list"] = prev
    try:
        del core._zmart_prev_acq_list
    except AttributeError:
        pass
    return {"state": (core.state or {}).get("state")}


def _procedure(core, a):
    # Advertised but not implemented server-side: fail loudly (the client turns a
    # server error into a NAK) so "advertised" is never mistaken for "implemented".
    raise RuntimeError(f"procedure {a.get('name')!r} is not implemented server-side")


COMMANDS = {
    "hello": _hello, "ping": _ping,
    "get_state": _get_state, "get_position": _get_position,
    "get_config": _get_config, "get_progress": _get_progress,
    "move_absolute": _move_absolute, "move_relative": _move_relative,
    "zero": _zero, "stop": _stop, "set_state": _set_state,
    "acquire_start": _acquire_start, "stat_files": _stat_files, "acquire_finish": _acquire_finish,
    "procedure": _procedure,
}


def run(core, call: str, args: dict | None = None) -> dict:
    """Dispatch one named call against the fixed table. Unknown call -> ``KeyError``."""
    handler = COMMANDS.get(call)
    if handler is None:
        raise KeyError(f"unknown command {call!r}; not in the allowlist")
    return handler(core, args or {})
