"""C to Python: the NIS-Elements functions the bridge calls, one thin wrapper each.

NIS-Elements ships its own Python, and every NIS macro function (``StgMoveXY``,
``Capture``, ``ImageSaveAs`` ...) is also exported by ``g5_regprocs.dll``, a C
library. ``NisDll`` calls them through ``ctypes``, turns their return codes
into Python exceptions and their output values into plain Python, and does
nothing else: the meaning of a request lives in ``readers.py`` and
``commands.py``. Signatures
come from the macro reference installed with NIS (Docs/nis/eng_ar). Units are
micrometres. Tests replace this class with ``fake.FakeNisApi``.

Standard library only: this runs inside NIS-Elements.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB), University of Zurich
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
Date: 2026-09-27
License: MIT
"""

from __future__ import annotations

import ctypes as ct
from typing import Any

from .settings import CLOSE_WITHOUT_ASKING, INFOSTR_VERSION, TIFF_ALL_LAYERS

# What NIS's own codes mean; lookup tables, not settings. 1 and 2 mean success.
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

# Stg_GetPFSStatus values.
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
    """A NIS function returned an error code."""


def _check(rc: int, what: str) -> None:
    if rc not in (1, 2):
        raise NisError(f"{what}: {DR_CODES.get(rc, 'unknown code')} ({rc})")


def _check_negative(value: int, what: str) -> int:
    """Raise for a negative DR code, which every NIS function uses for failure.

    This is for functions whose success value is a count, or is not documented.
    """
    if value < 0:
        _check(value, what)
    return int(value)


# ---------------------------------------------------------------------------
# NIS functions, one small method each. Signatures come from the macro
# reference installed with NIS (Docs/nis/eng_ar). Units: micrometres.
# ---------------------------------------------------------------------------


class NisDll:
    def __init__(self) -> None:
        self._dll = ct.cdll.g5_regprocs
        self._functions: dict[str, Any] = {}

    def _fn(self, name: str, argtypes: list, restype: Any = ct.c_int32) -> Any:
        if name not in self._functions:
            fn = getattr(self._dll, name)
            fn.argtypes, fn.restype = argtypes, restype
            self._functions[name] = fn
        return self._functions[name]

    def version(self) -> str:
        buf = ct.create_unicode_buffer(64)
        self._fn("Get_InfoStr", [ct.c_int32, ct.c_wchar_p])(INFOSTR_VERSION, buf)
        return buf.value

    # stage
    def get_position(self) -> dict[str, float]:
        x, y, z = ct.c_double(), ct.c_double(), ct.c_double()
        fn = self._fn("StgGetPos", [ct.POINTER(ct.c_double)] * 3)
        _check(fn(ct.byref(x), ct.byref(y), ct.byref(z)), "StgGetPos")
        return {"x": x.value, "y": y.value, "z": z.value}

    def get_limits(self) -> dict[str, dict[str, float]]:
        x0, y0, x1, y1 = (ct.c_double() for _ in range(4))
        fn = self._fn("StgXY_GetLimits", [ct.POINTER(ct.c_double)] * 4)
        _check(fn(ct.byref(x0), ct.byref(y0), ct.byref(x1), ct.byref(y1)), "StgXY_GetLimits")
        z0, z1 = ct.c_double(), ct.c_double()
        fn = self._fn("StgZ_GetLimits", [ct.POINTER(ct.c_double)] * 2)
        _check(fn(ct.byref(z0), ct.byref(z1)), "StgZ_GetLimits")
        return {
            "x": {"min": x0.value, "max": x1.value},
            "y": {"min": y0.value, "max": y1.value},
            "z": {"min": z0.value, "max": z1.value},
        }

    def move_xyz(self, x: float, y: float, z: float) -> None:
        fn = self._fn("StgMove", [ct.c_double, ct.c_double, ct.c_double, ct.c_int32])
        _check(fn(x, y, z, 0), "StgMove")

    def move_xy(self, x: float, y: float) -> None:
        _check(self._fn("StgMoveXY", [ct.c_double, ct.c_double, ct.c_int32])(x, y, 0), "StgMoveXY")

    def move_z(self, z: float) -> None:
        _check(self._fn("StgMoveZ", [ct.c_double, ct.c_int32])(z, 0), "StgMoveZ")

    # optical configurations and camera
    def optical_configurations(self) -> list[str]:
        count = self._fn("GetOptConfCount", [])()
        get_name = self._fn("GetOptConfName", [ct.c_int32, ct.c_wchar_p, ct.c_int32])
        names = []
        for index in range(max(count, 0)):
            buf = ct.create_unicode_buffer(256)
            get_name(index, buf, 256)
            names.append(buf.value)
        return names

    def select_optical_configuration(self, name: str) -> None:
        _check_negative(self._fn("SelectOptConf", [ct.c_wchar_p])(name), f"SelectOptConf({name})")

    def set_exposure_ms(self, exposure_ms: float) -> float:
        """Set the camera exposure; return the value NIS applied (it may round it).

        Not exported by the DLL; NIS registers it internally and ``nis.call_proc``
        reaches it by name. It answers with a list: the return value, then each
        argument as it is after the call. (Reading the exposure with
        ``Camera_ExposureGet`` opens a blocking dialog in NIS, so it is never used.)
        """
        import nis  # exists only inside NIS-Elements

        out = nis.call_proc("Camera_ExposureSet", float(exposure_ms))
        out = list(out) if isinstance(out, (list, tuple)) else [out]
        return float(out[1]) if len(out) > 1 else float(exposure_ms)

    # nosepiece
    def nosepiece_present(self) -> bool:
        return bool(self._fn("Stg_IsNosepiecePresent", [])())

    def nosepiece_count(self) -> int:
        count = self._fn("Stg_GetNosepiecePositions", [])()
        return _check_negative(count, "Stg_GetNosepiecePositions")

    def nosepiece_position(self) -> int:
        position = self._fn("Stg_GetNosepiecePosition", [])()
        return _check_negative(position, "Stg_GetNosepiecePosition")

    def objective_name(self, position: int) -> str:
        buf = ct.create_unicode_buffer(256)
        fn = self._fn("Stg_GetNosepieceObjectiveName", [ct.c_int32, ct.c_wchar_p, ct.c_int32])
        _check(fn(position, buf, 256), f"Stg_GetNosepieceObjectiveName({position})")
        return buf.value

    def set_nosepiece_position(self, position: int) -> None:
        fn = self._fn("Stg_SetNosepiecePosition", [ct.c_int32])
        _check(fn(position), f"Stg_SetNosepiecePosition({position})")

    # focus
    def pfs_present(self) -> bool:
        return bool(self._fn("Stg_IsPFSPresent", [])())

    def pfs_status(self) -> int:
        return int(self._fn("Stg_GetPFSStatus", [])())

    def set_pfs(self, on: bool) -> None:
        _check_negative(
            self._fn("Stg_SetPFSStatus", [ct.c_int32])(1 if on else 0), "Stg_SetPFSStatus"
        )

    def wait_for_pfs(self, timeout_s: float) -> None:
        self._fn("Stg_WaitForPFS", [ct.c_double])(timeout_s)

    def autofocus(self, range_um: float, speed: int) -> int:
        """Image-based focus sweep over ``range_um`` around the current Z; 1 = found."""
        return int(self._fn("StgFocusInRangeEx", [ct.c_double, ct.c_double])(range_um, speed))

    # images
    def capture(self) -> None:
        # Checked, so that a failed capture never lets the save and close that follow
        # act on another image open in NIS, such as the operator's own.
        _check_negative(self._fn("Capture", [])(), "Capture")

    def pixel_size_um(self) -> float:
        """Calibration of the current image in um/px; 0 when uncalibrated."""
        name = ct.create_unicode_buffer(256)
        cal, aspect, unit = ct.c_double(), ct.c_double(), ct.c_int32()
        fn = self._fn(
            "Get_Calibration",
            [
                ct.c_wchar_p,
                ct.POINTER(ct.c_double),
                ct.POINTER(ct.c_double),
                ct.POINTER(ct.c_int32),
            ],
            ct.c_double,
        )
        fn(name, ct.byref(cal), ct.byref(aspect), ct.byref(unit))
        return cal.value

    def save_tiff(self, path: str) -> None:
        self._fn("ImageSaveAs", [ct.c_wchar_p, ct.c_int32, ct.c_int32])(path, TIFF_ALL_LAYERS, 0)

    def close_document(self) -> None:
        self._fn("CloseCurrentDocument", [ct.c_int32])(CLOSE_WITHOUT_ASKING)
