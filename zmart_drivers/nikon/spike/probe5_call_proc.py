"""Probe 5: how does ``nis.call_proc`` want its arguments for the camera procedures?

``Camera_ExposureSet(double)`` / ``Camera_ExposureGet(double*)`` are registered
procedures (not DLL exports). Calling them through ``nis.call_proc`` with the
documented arity answered "Bad number of parameters", so this probe tries the
plausible shapes and records what each one does. Runs on the main thread from a
macro; nothing moves.
"""

import ctypes as ct
import nis

REPORT = (
    r"C:\Users\t.de\repos\ZMART-microscopy\zmart_drivers\nikon\spike\probe5_call_proc.report.txt"
)
lines = []


def log(*parts):
    lines.append(" ".join(str(p) for p in parts))
    with open(REPORT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def attempt(label, fn):
    try:
        r = fn()
        log(f"[ok]   {label} -> {r!r}")
        return r
    except Exception as exc:  # noqa: BLE001
        log(f"[fail] {label}: {type(exc).__name__}: {exc}")


log("probe5 started; call_proc doc:", nis.call_proc.__doc__)

# Known-good reference: a zero-argument registered procedure we already use.
attempt("call_proc('Freeze')", lambda: nis.call_proc("Freeze"))
attempt("call_proc('StgZ_GetActiveZ')", lambda: nis.call_proc("StgZ_GetActiveZ"))
attempt("call_proc('Stg_GetPFSStatus')", lambda: nis.call_proc("Stg_GetPFSStatus"))

# A DLL function with an output pointer, via call_proc, to learn how outputs come back.
attempt("call_proc('StgGetPosZ', 0)", lambda: nis.call_proc("StgGetPosZ", 0))
attempt("call_proc('StgGetPosZ', 0.0, 0)", lambda: nis.call_proc("StgGetPosZ", 0.0, 0))
attempt("call_proc('StgGetPosXY')", lambda: nis.call_proc("StgGetPosXY"))
attempt("call_proc('StgGetPosXY', 0.0, 0.0)", lambda: nis.call_proc("StgGetPosXY", 0.0, 0.0))
attempt("call_proc('Get_InfoStr', 1)", lambda: nis.call_proc("Get_InfoStr", 1))
attempt("call_proc('Get_InfoStr', 1, '')", lambda: nis.call_proc("Get_InfoStr", 1, ""))

# The camera exposure procedures, several argument shapes.
for name, argsets in {
    "Camera_ExposureGet": [(), (0.0,), (0,), ([0.0],)],
    "CameraGet_Exposure": [(), (2,), (2, 0.0), (2, 0)],
    "Camera_ExposureSet": [(33.0,), (33,), ("33",), (33.0, 0)],
    "CameraSet_Exposure": [(2, 33), (2, 33.0), (33,)],
}.items():
    for args in argsets:
        attempt(f"call_proc({name!r}, *{args!r})", lambda n=name, a=args: nis.call_proc(n, *a))

# Does the DLL happen to export them under a different name?
dll = ct.cdll.g5_regprocs
for name in (
    "Camera_ExposureSet",
    "Camera_ExposureGet",
    "CameraSet_Exposure",
    "CameraGet_Exposure",
    "LiveSync",
    "Live",
    "Freeze",
):
    attempt(f"g5_regprocs has {name}", lambda n=name: bool(getattr(dll, n)))

# PFS on the simulator: turn on, read, turn off.
attempt("Stg_SetPFSStatus(1) via call_proc", lambda: nis.call_proc("Stg_SetPFSStatus", 1))
attempt("Stg_GetPFSStatus after on", lambda: nis.call_proc("Stg_GetPFSStatus"))
attempt("Stg_SetPFSStatus(0) via call_proc", lambda: nis.call_proc("Stg_SetPFSStatus", 0))
attempt("Stg_GetPFSStatus after off", lambda: nis.call_proc("Stg_GetPFSStatus"))

# Autofocus: the plain menu-command variant, to see whether the simulator can focus at all.
attempt("StgFocus() via call_proc", lambda: nis.call_proc("StgFocus"))
log("DONE")
