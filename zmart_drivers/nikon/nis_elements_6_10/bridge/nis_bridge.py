"""
The bridge: a small server that lives inside NIS-Elements.
=========================================================
NIS-Elements ships its own Python interpreter, running inside the NIS process.
Every macro command NIS knows (``StgMoveXY``, ``Capture``, ``ImageSaveAs`` ...)
is also a plain function exported by ``g5_regprocs.dll``, and from inside NIS we
can call those functions directly through ``ctypes``. This is exactly how
Nikon's own Python modules (``limpy``, ``limrestapi``) talk to the instrument.

This file is started once per NIS session by ``start_bridge.mac``. It opens a
TCP server on the local machine only (``127.0.0.1``) and then, for each request
line the ZMART driver sends, calls the matching NIS function and writes the
answer back (see ``protocol.py`` for the message format).

Three design rules keep this safe:

* **Only the operations listed in** :data:`OPS` **can be called.** The driver
  cannot send arbitrary macro text; it can only ask for a named operation with
  checked arguments.
* **Every NIS call runs on the NIS main thread.** Camera and image-window
  functions crash NIS-Elements when called from another thread (learned the
  hard way with ``Capture``). So the socket threads only queue requests, and
  the macro loop in ``start_bridge.mac`` runs them one by one on the main
  thread by calling :func:`pump`, which sleeps on the queue between requests.
* **One call at a time.** The queue is drained by that single thread, so two
  requests can never reach the instrument simultaneously.

The file must stay standard-library only: it runs in the Python bundled with
NIS-Elements (3.12 in NIS 6.10), which has no third-party packages besides
numpy.

To test the server logic without NIS, :func:`serve` accepts any object with the
same methods as :class:`NisApi` (see ``tests/helpers/fake_nis_api.py``).

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import ctypes as ct
import logging
import os
import queue
import socket
import socketserver
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

try:  # imported as part of the driver package (tests, tooling)
    from ..protocol import (
        ENCODING,
        PROTOCOL_VERSION,
        ProtocolError,
        decode_request,
        encode_error,
        encode_reply,
    )
except ImportError:  # imported inside NIS, where only this folder's parent is on sys.path
    from protocol import (  # type: ignore[no-redef]
        ENCODING,
        PROTOCOL_VERSION,
        ProtocolError,
        decode_request,
        encode_error,
        encode_reply,
    )

BRIDGE_VERSION = "0.2.0"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 54468

log = logging.getLogger("zmart.nikon.bridge")

# ---------------------------------------------------------------------------
# NIS return codes (the "DR_" family used by every device function)
# ---------------------------------------------------------------------------

DR_CODES = {
    1: "DR_OK",
    2: "DR_PARTIALLYOK",
    0: "DR_CANCELED",
    -1: "DR_UNKNOWNERROR",
    -2: "DR_BADPARAMETER",
    -3: "DR_NOTSUPPORTED",
    -4: "DR_NOTAVAILABLE",
    -5: "DR_NOTAUTOMATIC",
    -6: "DR_NOTCALIBRATED",
    -7: "DR_NOTINITIALIZED",
}

# ImageSaveAs "ImType" values: which layers to write. 18 = all layers as TIFF,
# 14 = all layers as ND2 (Nikon's own format, keeps every piece of metadata).
SAVE_TYPES = {"tif": 18, "tiff": 18, "nd2": 14, "ome.tif": 30}

# CloseCurrentDocument(Save): 2 = close without asking and without saving again.
QUERYSAVE_NO = 2

# Get_InfoStr "what" value for the NIS-Elements version string.
INFOSTR_LUCVER = 1

# Stg_GetPFSStatus return values (already normalised by NIS across microscope models).
PFS_STATUS = {
    -1: "error or not connected",
    0: "off, in range",
    1: "on, focused",
    3: "off, out of range",
    4: "off, PFS optics not set (dichroic mirror out)",
    5: "on, searching",
    6: "on, search stopped (cannot find focus)",
    7: "disabled, objective not supported",
}


class NisError(RuntimeError):
    """A NIS device function returned an error code."""


def _check(rc: int, what: str) -> int:
    """Turn a NIS return code into an exception unless it means success."""
    if rc in (1, 2):
        return rc
    name = DR_CODES.get(rc, "unknown code")
    raise NisError(f"{what}: {name} ({rc})")


# ---------------------------------------------------------------------------
# The ctypes layer: one small Python method per NIS function we use
# ---------------------------------------------------------------------------


class NisApi:
    """Thin, typed wrappers around the NIS functions the driver needs.

    Every method here maps onto exactly one exported function of
    ``g5_regprocs.dll``; the argument types come from the NIS macro reference
    (``Docs/nis/eng_ar`` in the NIS install). Positions and limits are in
    micrometres, as NIS reports them. Text arguments are wide strings.
    """

    def __init__(self, dll: Any | None = None) -> None:
        self._dll = dll if dll is not None else ct.cdll.g5_regprocs
        self._cache: dict[str, Any] = {}

    def _fn(self, name: str, argtypes: list, restype: Any = ct.c_int32) -> Any:
        fn = self._cache.get(name)
        if fn is None:
            fn = getattr(self._dll, name)
            fn.argtypes = argtypes
            fn.restype = restype
            self._cache[name] = fn
        return fn

    # -- identity -----------------------------------------------------------

    def version(self) -> str:
        buf = ct.create_unicode_buffer(64)
        self._fn("Get_InfoStr", [ct.c_int32, ct.c_wchar_p])(INFOSTR_LUCVER, buf)
        return buf.value

    # -- stage: presence, position, limits ----------------------------------

    def xy_present(self) -> bool:
        return bool(self._fn("StgXY_IsPresent", [])())

    def z_present(self, index: int = 0) -> bool:
        return bool(self._fn("StgZ_IsPresent", [ct.c_int32])(int(index)))

    def get_position(self) -> dict[str, float]:
        x, y, z = ct.c_double(), ct.c_double(), ct.c_double()
        rc = self._fn("StgGetPos", [ct.POINTER(ct.c_double)] * 3)(
            ct.byref(x), ct.byref(y), ct.byref(z)
        )
        _check(rc, "StgGetPos")
        return {"x": x.value, "y": y.value, "z": z.value}

    def get_limits(self) -> dict[str, dict[str, float]]:
        a, b, c, d = (ct.c_double() for _ in range(4))
        rc = self._fn("StgXY_GetLimits", [ct.POINTER(ct.c_double)] * 4)(
            ct.byref(a), ct.byref(b), ct.byref(c), ct.byref(d)
        )
        _check(rc, "StgXY_GetLimits")
        lo, hi = ct.c_double(), ct.c_double()
        rc = self._fn("StgZ_GetLimits", [ct.POINTER(ct.c_double)] * 2)(ct.byref(lo), ct.byref(hi))
        _check(rc, "StgZ_GetLimits")
        return {
            "x": {"min": a.value, "max": c.value},
            "y": {"min": b.value, "max": d.value},
            "z": {"min": lo.value, "max": hi.value},
        }

    # -- stage: moves (absolute, micrometres) -------------------------------

    def move_xyz(self, x: float, y: float, z: float) -> None:
        rc = self._fn("StgMove", [ct.c_double, ct.c_double, ct.c_double, ct.c_int32])(
            float(x), float(y), float(z), 0
        )
        _check(rc, "StgMove")

    def move_xy(self, x: float, y: float) -> None:
        rc = self._fn("StgMoveXY", [ct.c_double, ct.c_double, ct.c_int32])(float(x), float(y), 0)
        _check(rc, "StgMoveXY")

    def move_z(self, z: float) -> None:
        rc = self._fn("StgMoveZ", [ct.c_double, ct.c_int32])(float(z), 0)
        _check(rc, "StgMoveZ")

    # -- second Z drive (piezo) ----------------------------------------------
    # NIS can have two Z drives: the microscope's own focus drive and a piezo
    # insert. StgGetPosZ takes the drive index (0 = primary, 1 = secondary);
    # StgZ_GetPiezoDevice says which index is the piezo, or -1 when none.

    def piezo_device(self) -> int:
        return int(self._fn("StgZ_GetPiezoDevice", [])())

    def active_z(self) -> int:
        return int(self._fn("StgZ_GetActiveZ", [])())

    def get_z(self, device: int) -> float:
        z = ct.c_double()
        rc = self._fn("StgGetPosZ", [ct.POINTER(ct.c_double), ct.c_int32])(ct.byref(z), int(device))
        _check(rc, f"StgGetPosZ(device={device})")
        return z.value

    def move_piezo_z(self, z: float) -> None:
        rc = self._fn("StgMovePiezoZ", [ct.c_double, ct.c_int32])(float(z), 0)
        _check(rc, "StgMovePiezoZ")

    # -- autofocus (software, image-based) ----------------------------------
    # StgFocusInRangeEx sweeps Focus_Range um around the current Z, grabbing
    # frames while moving, and ends on the sharpest plane. Speed is 0..90.

    def autofocus(self, range_um: float, speed: int) -> int:
        return int(
            self._fn("StgFocusInRangeEx", [ct.c_double, ct.c_double])(float(range_um), float(speed))
        )

    # -- PFS (Perfect Focus System, hardware focus lock) ---------------------

    def pfs_present(self) -> bool:
        return bool(self._fn("Stg_IsPFSPresent", [])())

    def pfs_status(self) -> int:
        return int(self._fn("Stg_GetPFSStatus", [])())

    def set_pfs(self, on: bool) -> None:
        self._fn("Stg_SetPFSStatus", [ct.c_int32])(1 if on else 0)

    def wait_for_pfs(self, timeout_s: float) -> None:
        self._fn("Stg_WaitForPFS", [ct.c_double])(float(timeout_s))

    # -- Z-series (a Z-stack through the ND Acquisition dialog) -------------
    # ND_SetZSeriesExp fills in the "Z" tab of ND Acquisition; ND_RunZSeriesExp
    # runs it. The resulting ND document becomes the current image, so
    # save_image / image_info work on it afterwards. Type 0 = absolute
    # top/bottom in um; home and shutter options are left at their defaults.

    def set_z_series(self, top: float, bottom: float, step: float, count: int) -> None:
        self._fn(
            "ND_SetZSeriesExp",
            [
                ct.c_int32,
                ct.c_double,
                ct.c_double,
                ct.c_double,
                ct.c_double,
                ct.c_int32,
                ct.c_int32,
                ct.c_int32,
                ct.c_wchar_p,
                ct.c_wchar_p,
                ct.c_wchar_p,
            ],
        )(0, float(top), 0.0, float(bottom), float(step), int(count), 0, 0, "", "", "")

    def run_z_series(self) -> None:
        self._fn("ND_RunZSeriesExp", [])()

    # -- camera and live view: registered procedures, reached by name -------
    # Camera and Live functions are not exported by g5_regprocs.dll; NIS
    # registers them internally, and the built-in ``nis.call_proc`` calls a
    # registered procedure by name. It answers with a list: the procedure's
    # return value first, then every argument as it is after the call, so an
    # output argument (a "double*" in the macro reference) comes back there.
    # An output argument is passed in as a one-element list.

    def _call_proc(self, name: str, *args: Any) -> list:
        import nis  # only exists inside NIS-Elements

        result = nis.call_proc(name, *args)
        return list(result) if isinstance(result, (list, tuple)) else [result]

    # Reading the exposure back is not possible this way: ``Camera_ExposureGet``
    # has an output argument, and calling it through call_proc makes NIS show a
    # modal "Cannot Evaluate the Expression" dialog that blocks everything. So
    # the bridge remembers the last value it set and reports that; None means
    # nothing was set through the bridge yet.
    _exposure_ms: float | None = None

    def get_exposure_ms(self) -> float | None:
        return self._exposure_ms

    def set_exposure_ms(self, exposure_ms: float) -> float:
        out = self._call_proc("Camera_ExposureSet", float(exposure_ms))
        self._exposure_ms = float(out[1]) if len(out) > 1 else float(exposure_ms)
        return self._exposure_ms

    def live(self) -> None:
        self._call_proc("Live")

    def freeze(self) -> None:
        self._call_proc("Freeze")

    # -- nosepiece / objectives ---------------------------------------------

    def nosepiece_present(self) -> bool:
        return bool(self._fn("Stg_IsNosepiecePresent", [])())

    def nosepiece_count(self) -> int:
        return _check_count(
            self._fn("Stg_GetNosepiecePositions", [])(), "Stg_GetNosepiecePositions"
        )

    def nosepiece_position(self) -> int:
        return _check_count(self._fn("Stg_GetNosepiecePosition", [])(), "Stg_GetNosepiecePosition")

    def nosepiece_objective_name(self, position: int) -> str:
        buf = ct.create_unicode_buffer(256)
        rc = self._fn("Stg_GetNosepieceObjectiveName", [ct.c_int32, ct.c_wchar_p, ct.c_int32])(
            int(position), buf, 256
        )
        _check(rc, f"Stg_GetNosepieceObjectiveName({position})")
        return buf.value

    def set_nosepiece_position(self, position: int) -> None:
        rc = self._fn("Stg_SetNosepiecePosition", [ct.c_int32])(int(position))
        _check(rc, f"Stg_SetNosepiecePosition({position})")

    # -- optical configurations ---------------------------------------------

    def optical_configuration_names(self) -> list[str]:
        count = self._fn("GetOptConfCount", [])()
        names = []
        get_name = self._fn("GetOptConfName", [ct.c_int32, ct.c_wchar_p, ct.c_int32])
        for index in range(max(count, 0)):
            buf = ct.create_unicode_buffer(256)
            get_name(index, buf, 256)
            names.append(buf.value)
        return names

    def select_optical_configuration(self, name: str) -> None:
        self._fn("SelectOptConf", [ct.c_wchar_p])(str(name))

    # -- images -------------------------------------------------------------

    def capture(self) -> None:
        self._fn("Capture", [])()

    def image_info(self) -> dict[str, int]:
        w, h, bpc, planes = (ct.c_int32() for _ in range(4))
        self._fn("Get_ImageInfo", [ct.c_wchar_p] + [ct.POINTER(ct.c_int32)] * 4)(
            "", ct.byref(w), ct.byref(h), ct.byref(bpc), ct.byref(planes)
        )
        return {
            "width": w.value,
            "height": h.value,
            "bits_per_component": bpc.value,
            "planes": planes.value,
        }

    def calibration(self) -> dict[str, Any]:
        buf = ct.create_unicode_buffer(256)
        cal, aspect, unit = ct.c_double(), ct.c_double(), ct.c_int32()
        self._fn(
            "Get_Calibration",
            [
                ct.c_wchar_p,
                ct.POINTER(ct.c_double),
                ct.POINTER(ct.c_double),
                ct.POINTER(ct.c_int32),
            ],
            ct.c_double,
        )(buf, ct.byref(cal), ct.byref(aspect), ct.byref(unit))
        return {
            "objective": buf.value,
            "pixel_size": cal.value,
            "aspect": aspect.value,
            "unit": unit.value,
        }

    def save_image(self, path: str, save_type: int, compression: int = 0) -> None:
        self._fn("ImageSaveAs", [ct.c_wchar_p, ct.c_int32, ct.c_int32])(
            str(path), int(save_type), int(compression)
        )

    def close_document(self) -> None:
        self._fn("CloseCurrentDocument", [ct.c_int32])(QUERYSAVE_NO)


def _check_count(value: int, what: str) -> int:
    """Some NIS functions return a count on success and a negative DR code on failure."""
    if value < 0:
        _check(value, what)
    return int(value)


# ---------------------------------------------------------------------------
# The operations the driver may ask for
# ---------------------------------------------------------------------------


def _num(args: dict, key: str) -> float:
    try:
        return float(args[key])
    except KeyError:
        raise ValueError(f"missing argument {key!r}") from None
    except (TypeError, ValueError):
        raise ValueError(f"argument {key!r} must be a number") from None


def _text(args: dict, key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"argument {key!r} must be a non-empty string")
    return value


class Operations:
    """Named operations, each a checked call into :class:`NisApi`.

    The names are what travels on the wire. Keep them boring and explicit; a
    new capability is a new method here plus a line in :data:`OPS`.
    """

    def __init__(self, api: Any, stop: Callable[[], None]) -> None:
        self.api = api
        self._stop = stop

    def ping(self, args: dict) -> dict:
        return {
            "bridge": BRIDGE_VERSION,
            "protocol": PROTOCOL_VERSION,
            "nis": self.api.version(),
            "pid": os.getpid(),
        }

    def get_devices(self, args: dict) -> dict:
        return {
            "xy": self.api.xy_present(),
            "z": self.api.z_present(0),
            "z_secondary": self.api.z_present(1),
            "nosepiece": self.api.nosepiece_present(),
        }

    def get_position(self, args: dict) -> dict:
        return self.api.get_position()

    def get_limits(self, args: dict) -> dict:
        return self.api.get_limits()

    def move_xyz(self, args: dict) -> dict:
        self.api.move_xyz(_num(args, "x"), _num(args, "y"), _num(args, "z"))
        return self.api.get_position()

    def move_xy(self, args: dict) -> dict:
        self.api.move_xy(_num(args, "x"), _num(args, "y"))
        return self.api.get_position()

    def move_z(self, args: dict) -> dict:
        self.api.move_z(_num(args, "z"))
        return self.api.get_position()

    def get_z_drives(self, args: dict) -> dict:
        """Which Z drives exist, which is the piezo, and where each one is (um)."""
        piezo = self.api.piezo_device()
        drives = []
        for index in (0, 1):
            if not self.api.z_present(index):
                continue
            # The simulator reports a second drive as present yet cannot read it
            # (DR_NOTAVAILABLE); such a drive is simply left out.
            try:
                z = self.api.get_z(index)
            except NisError:
                continue
            drives.append(
                {"index": index, "kind": "piezo" if index == piezo else "motoric", "z": z}
            )
        return {"drives": drives, "piezo_index": piezo, "active_index": self.api.active_z()}

    def move_piezo_z(self, args: dict) -> dict:
        if self.api.piezo_device() < 0:
            raise RuntimeError("no piezo Z drive is connected")
        self.api.move_piezo_z(_num(args, "z"))
        return {"z": self.api.get_z(self.api.piezo_device())}

    def autofocus(self, args: dict) -> dict:
        """Software autofocus over ``range_um`` around the current Z; ends on the sharpest plane."""
        range_um = float(args.get("range_um", 50.0))
        speed = int(args.get("speed", 30))
        if range_um <= 0:
            raise ValueError("argument 'range_um' must be a positive number of micrometres")
        if not 0 <= speed <= 90:
            raise ValueError("argument 'speed' must be between 0 and 90")
        started = time.perf_counter()
        rc = self.api.autofocus(range_um, speed)
        if rc != 1:
            reasons = {
                0: "focus failed",
                -2: "range must be positive",
                -3: "no usable image (all black or white)",
            }
            raise RuntimeError(f"StgFocusInRangeEx: {reasons.get(rc, 'unknown result')} ({rc})")
        return {
            "position": self.api.get_position(),
            "duration_s": round(time.perf_counter() - started, 3),
        }

    def get_pfs(self, args: dict) -> dict:
        if not self.api.pfs_present():
            return {"present": False, "status": None, "on": None}
        status = self.api.pfs_status()
        return {
            "present": True,
            "status": status,
            "on": status in (1, 5, 6),
            "focused": status == 1,
            "meaning": PFS_STATUS.get(status, "unknown"),
        }

    def set_pfs(self, args: dict) -> dict:
        if not self.api.pfs_present():
            raise RuntimeError("no PFS (Perfect Focus System) is connected")
        on = args.get("on")
        if not isinstance(on, bool):
            raise ValueError("argument 'on' must be true or false")
        self.api.set_pfs(on)
        if on:
            self.api.wait_for_pfs(float(args.get("timeout_s", 8.0)))
        return self.get_pfs({})

    def get_exposure(self, args: dict) -> dict:
        return {"exposure_ms": self.api.get_exposure_ms()}

    def set_exposure(self, args: dict) -> dict:
        exposure_ms = _num(args, "exposure_ms")
        if exposure_ms <= 0:
            raise ValueError("argument 'exposure_ms' must be positive")
        return {"exposure_ms": self.api.set_exposure_ms(exposure_ms)}

    def live(self, args: dict) -> dict:
        self.api.live()
        return {"live": True}

    def freeze(self, args: dict) -> dict:
        self.api.freeze()
        return {"live": False}

    def capture_z_stack(self, args: dict) -> dict:
        """Acquire a Z-stack between two absolute Z positions (um) with a given step.

        The stack becomes the current NIS document; call ``save_image`` next.
        """
        top, bottom, step = _num(args, "z_top"), _num(args, "z_bottom"), _num(args, "z_step")
        if step <= 0:
            raise ValueError("argument 'z_step' must be positive")
        if top < bottom:
            top, bottom = bottom, top
        count = int(round((top - bottom) / step)) + 1
        started = time.perf_counter()
        self.api.set_z_series(top, bottom, step, count)
        self.api.run_z_series()
        info = self.api.image_info()
        info["z_planes"] = count
        info["duration_s"] = round(time.perf_counter() - started, 3)
        return info

    def get_objectives(self, args: dict) -> dict:
        if not self.api.nosepiece_present():
            return {"present": False, "current": None, "objectives": []}
        count = self.api.nosepiece_count()
        objectives = []
        for position in range(1, count + 1):
            name = self.api.nosepiece_objective_name(position)
            if name:
                objectives.append({"position": position, "name": name})
        return {"present": True, "current": self.api.nosepiece_position(), "objectives": objectives}

    def set_objective(self, args: dict) -> dict:
        position = args.get("position")
        if not isinstance(position, int) or position < 1:
            raise ValueError("argument 'position' must be a nosepiece position (1-based integer)")
        self.api.set_nosepiece_position(position)
        return {"current": self.api.nosepiece_position()}

    def get_optical_configurations(self, args: dict) -> dict:
        return {"names": self.api.optical_configuration_names()}

    def select_optical_configuration(self, args: dict) -> dict:
        name = _text(args, "name")
        if name not in self.api.optical_configuration_names():
            raise ValueError(f"unknown optical configuration {name!r}")
        self.api.select_optical_configuration(name)
        return {"selected": name}

    def get_calibration(self, args: dict) -> dict:
        return self.api.calibration()

    def capture(self, args: dict) -> dict:
        started = time.perf_counter()
        self.api.capture()
        info = self.api.image_info()
        info["duration_s"] = round(time.perf_counter() - started, 4)
        return info

    def save_image(self, args: dict) -> dict:
        path = _text(args, "path")
        fmt = str(args.get("format", "tif")).lower()
        if fmt not in SAVE_TYPES:
            raise ValueError(f"unknown format {fmt!r}; choose one of {sorted(SAVE_TYPES)}")
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        self.api.save_image(path, SAVE_TYPES[fmt], int(args.get("compression", 0)))
        if not os.path.exists(path):
            raise RuntimeError(f"ImageSaveAs returned but no file appeared at {path}")
        if args.get("close", True):
            self.api.close_document()
        return {"path": path, "bytes": os.path.getsize(path)}

    def close_document(self, args: dict) -> dict:
        self.api.close_document()
        return {}

    def shutdown(self, args: dict) -> dict:
        self._stop()
        return {"stopping": True}


# op name on the wire -> Operations method name. Only these can be called.
OPS: dict[str, str] = {
    "ping": "ping",
    "get_devices": "get_devices",
    "get_position": "get_position",
    "get_limits": "get_limits",
    "move_xyz": "move_xyz",
    "move_xy": "move_xy",
    "move_z": "move_z",
    "get_objectives": "get_objectives",
    "set_objective": "set_objective",
    "get_optical_configurations": "get_optical_configurations",
    "select_optical_configuration": "select_optical_configuration",
    "get_calibration": "get_calibration",
    "get_z_drives": "get_z_drives",
    "move_piezo_z": "move_piezo_z",
    "autofocus": "autofocus",
    "get_pfs": "get_pfs",
    "set_pfs": "set_pfs",
    "get_exposure": "get_exposure",
    "set_exposure": "set_exposure",
    "live": "live",
    "freeze": "freeze",
    "capture_z_stack": "capture_z_stack",
    "capture": "capture",
    "save_image": "save_image",
    "close_document": "close_document",
    "shutdown": "shutdown",
}


# ---------------------------------------------------------------------------
# The TCP server
# ---------------------------------------------------------------------------


class _Job:
    """One queued request: what to run, and a slot for the answer."""

    __slots__ = ("op", "args", "done", "result", "error")

    def __init__(self, op: str, args: dict) -> None:
        self.op = op
        self.args = args
        self.done = threading.Event()
        self.result: Any = None
        self.error: BaseException | None = None


# How long a socket thread waits for the main thread to run its job. Captures
# with long exposures are the slow case; everything else answers in milliseconds.
JOB_TIMEOUT_S = 300.0


class BridgeServer(socketserver.ThreadingTCPServer):
    """Loopback JSON-lines server whose NIS calls all run on one chosen thread.

    Why the detour through a queue: NIS-Elements only tolerates camera and
    image-window work (``Capture``, ``ImageSaveAs`` ...) on its main thread; a
    call from a background thread crashes the application. So the socket
    threads never touch NIS. They put each request in a queue and wait; the
    main thread drains that queue by calling :meth:`pump` regularly (the
    ``start_bridge.mac`` loop does this every few milliseconds).
    """

    # On Windows, "reuse address" would let a second bridge bind the same port
    # next to a forgotten one, and clients would then reach the wrong server.
    allow_reuse_address = False
    daemon_threads = True

    def __init__(self, address: tuple[str, int], api: Any) -> None:
        super().__init__(address, _Handler)
        self.ops = Operations(api, self.stop)
        self.jobs: queue.Queue[_Job] = queue.Queue()
        self.job_timeout = JOB_TIMEOUT_S
        self._stop_requested = False
        self._last_pump = 0.0

    @property
    def stop_requested(self) -> bool:
        return self._stop_requested

    def stop(self) -> None:
        """Ask the bridge to finish: the pump loop sees this and ends."""
        self._stop_requested = True

    def pumped_recently(self, within_s: float = 2.0) -> bool:
        """True when a pump loop has served this server in the last ``within_s`` seconds."""
        return (time.monotonic() - self._last_pump) < within_s

    def pump(self, max_jobs: int = 50, wait_s: float = 0.0) -> int:
        """Run queued requests on the calling thread; returns how many ran.

        With ``wait_s`` > 0 the first job is waited for up to that long -- the
        thread sleeps instead of spinning -- so a loop that calls this every
        few tens of milliseconds costs nothing while idle. Once a job has
        arrived, the rest of the queue is drained without waiting.
        """
        self._last_pump = time.monotonic()
        ran = 0
        while ran < max_jobs:
            try:
                job = (
                    self.jobs.get(timeout=wait_s)
                    if (wait_s > 0 and ran == 0)
                    else self.jobs.get_nowait()
                )
            except queue.Empty:
                break
            try:
                job.result = getattr(self.ops, OPS[job.op])(job.args)
            except BaseException as exc:  # noqa: BLE001 - every failure must become a reply
                log.exception("op %s failed", job.op)
                job.error = exc
            finally:
                job.done.set()
            ran += 1
        return ran

    def handle_line(self, line: str) -> str:
        """Queue one request line for the pump and return the reply line. Never raises."""
        request_id = None
        try:
            request_id, op, args = decode_request(line)
            if op not in OPS:
                raise ValueError(f"unknown op {op!r}; known ops: {sorted(OPS)}")
            job = _Job(op, args)
            self.jobs.put(job)
            if not job.done.wait(self.job_timeout):
                raise RuntimeError(
                    f"{op!r} was not run within {self.job_timeout:.0f} s: the bridge loop in "
                    "NIS-Elements is not running (is start_bridge.mac still running?)"
                )
            if job.error is not None:
                raise job.error
            return encode_reply(request_id, job.result)
        except ProtocolError as exc:
            return encode_error(request_id, ValueError(str(exc)))
        except BaseException as exc:  # noqa: BLE001
            return encode_error(request_id, exc)


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        server: BridgeServer = self.server  # type: ignore[assignment]
        log.info("client connected from %s", self.client_address)
        while True:
            raw = self.rfile.readline()
            if not raw:
                break
            line = raw.decode(ENCODING, errors="replace").strip()
            if not line:
                continue
            self.wfile.write(server.handle_line(line).encode(ENCODING))
            self.wfile.flush()
        log.info("client disconnected")


# ---------------------------------------------------------------------------
# Lifecycle helpers used by start_bridge.mac (and by tests)
# ---------------------------------------------------------------------------

# The running server is kept in a place that survives ``importlib.reload`` of
# this module (the start macro reloads it to pick up code changes), so a bridge
# started earlier in the same NIS session can still be found and stopped.
_running: dict[str, Any] = sys.modules["__main__"].__dict__.setdefault(
    "_zmart_nikon_bridge_running", {}
)

# ``stop_bridge.mac`` creates this file; the macro loop in ``start_bridge.mac``
# ends when it appears. A file is used because a running macro cannot read a
# Python value directly, but it can call ``ExistFile``.
STOP_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bridge.stop")


def serve(
    api: Any, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, *, pump_thread: bool = False
) -> BridgeServer:
    """Start a listening server in a background thread and return it.

    With ``pump_thread=True`` a second background thread runs :meth:`BridgeServer.pump`
    continuously -- right for tests against a fake API, wrong inside NIS-Elements,
    where the main thread must pump (see :func:`run_loop`).
    """
    server = BridgeServer((host, port), api)
    threading.Thread(target=server.serve_forever, name="zmart-nikon-bridge", daemon=True).start()
    if pump_thread:

        def _pump_forever() -> None:
            while not server.stop_requested:
                if server.pump() == 0:
                    time.sleep(0.005)

        threading.Thread(target=_pump_forever, name="zmart-nikon-bridge-pump", daemon=True).start()
    log.info("bridge %s listening on %s:%s", BRIDGE_VERSION, host, server.server_address[1])
    return server


def start(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, log_path: str | None = None) -> str:
    """Start the bridge inside NIS-Elements (listening only; :func:`pump` must follow).

    Returns a short status line the macro can show. Logs go to ``log_path``
    (default: ``zmart-nikon-bridge.log`` in the user's temp folder). Calling it
    while a bridge is already up is harmless.
    """
    old = _running.get("server")
    if old is not None:
        if not old.stop_requested and old.pumped_recently():
            return f"bridge already running on {host}:{port}"
        # A bridge from an earlier macro run whose loop was stopped: close it
        # so its port is free again and its clients do not land on a dead server.
        stop()
    if os.path.exists(STOP_FILE):
        os.remove(STOP_FILE)
    if log_path is None:
        log_path = os.path.join(os.environ.get("TEMP", "."), "zmart-nikon-bridge.log")
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.handlers[:] = [handler]
    log.setLevel(logging.INFO)
    try:
        server = serve(NisApi(), host, port)
    except OSError as exc:
        log.error("could not start bridge: %s", exc)
        return (
            f"bridge failed to start on port {port}: {exc}. If a bridge from an earlier "
            "run is still holding the port, restart NIS-Elements."
        )
    _running["server"] = server
    return f"bridge {BRIDGE_VERSION} listening on {host}:{port}; log: {log_path}"


def pump(wait_s: float = 0.05) -> None:
    """Run the queued requests on the calling thread (the macro loop calls this).

    Sleeps up to ``wait_s`` for the first request so an idle bridge costs no
    CPU; NIS's own message loop gets its turn between calls, so the UI stays
    responsive with a delay of at most ``wait_s``. When a client asked for
    ``shutdown``, the stop file is created so the macro loop ends on its next
    check.
    """
    server = _running.get("server")
    if server is None:
        return
    server.pump(wait_s=wait_s)
    if server.stop_requested and not os.path.exists(STOP_FILE):
        open(STOP_FILE, "w").close()


def request_stop() -> str:
    """Ask a running bridge loop to end (what ``stop_bridge.mac`` does)."""
    open(STOP_FILE, "w").close()
    return "stop requested; the bridge loop ends within a moment"


def stop() -> str:
    """Close the server; called by the macro once its loop has ended."""
    if os.path.exists(STOP_FILE):
        os.remove(STOP_FILE)
    server = _running.pop("server", None)
    if server is None:
        return "bridge is not running"
    server.stop()
    server.shutdown()
    server.server_close()
    log.info("bridge stopped")
    return "bridge stopped"


def is_listening(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, timeout: float = 0.5) -> bool:
    """True when something accepts connections on the bridge address."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False
