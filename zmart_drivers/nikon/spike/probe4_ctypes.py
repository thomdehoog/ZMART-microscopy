"""Probe 4: call NIS macro functions directly through ctypes, from inside NIS.

Nikon's own ``limpy`` and ``limrestapi`` modules do exactly this against
``g5_regprocs.dll``. Here we try the stage getters we need for the driver, and
then check whether a background thread survives after the macro has returned
(a socket server inside NIS needs that). Read-only: nothing moves.
"""

import ctypes as ct
import threading
import time

REPORT = r"C:\Users\t.de\repos\ZMART-microscopy\zmart_drivers\nikon\spike\probe4_ctypes.report.txt"
lines = []


def log(*parts):
    lines.append(" ".join(str(p) for p in parts))
    with open(REPORT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def attempt(label, fn):
    try:
        r = fn()
        log(f"[ok]   {label}: {r!r}")
        return r
    except Exception as exc:  # noqa: BLE001
        log(f"[fail] {label}: {type(exc).__name__}: {exc}")


log("probe4 started")
import nis  # noqa: E402

log("nis.call_proc doc:", getattr(nis.call_proc, "__doc__", None))
log("nis doc:", nis.__doc__)

dll = attempt("load g5_regprocs (cdll)", lambda: ct.cdll.g5_regprocs)
if dll is None:
    raise SystemExit


# Pointer-to-double arguments: the macro reference says StgGetPosXY(double*, double*).
def read_xy():
    f = dll.StgGetPosXY
    f.argtypes = [ct.POINTER(ct.c_double), ct.POINTER(ct.c_double)]
    f.restype = ct.c_int32
    x, y = ct.c_double(), ct.c_double()
    rc = f(ct.byref(x), ct.byref(y))
    return {"rc": rc, "x_um": x.value, "y_um": y.value}


attempt("StgGetPosXY", read_xy)


def read_z(dev):
    f = dll.StgGetPosZ
    f.argtypes = [ct.POINTER(ct.c_double), ct.c_int32]
    f.restype = ct.c_int32
    z = ct.c_double()
    rc = f(ct.byref(z), dev)
    return {"rc": rc, "z_um": z.value}


attempt("StgGetPosZ(dev=0)", lambda: read_z(0))
attempt("StgGetPosZ(dev=1)", lambda: read_z(1))


def read_xyz():
    f = dll.StgGetPos
    f.argtypes = [ct.POINTER(ct.c_double)] * 3
    f.restype = ct.c_int32
    x, y, z = ct.c_double(), ct.c_double(), ct.c_double()
    rc = f(ct.byref(x), ct.byref(y), ct.byref(z))
    return {"rc": rc, "x": x.value, "y": y.value, "z": z.value}


attempt("StgGetPos", read_xyz)


def xy_limits():
    f = dll.StgXY_GetLimits
    f.argtypes = [ct.POINTER(ct.c_double)] * 4
    f.restype = ct.c_int32
    a, b, c, d = (ct.c_double() for _ in range(4))
    rc = f(ct.byref(a), ct.byref(b), ct.byref(c), ct.byref(d))
    return {"rc": rc, "min_x": a.value, "min_y": b.value, "max_x": c.value, "max_y": d.value}


attempt("StgXY_GetLimits", xy_limits)


def z_limits():
    f = dll.StgZ_GetLimits
    f.argtypes = [ct.POINTER(ct.c_double)] * 2
    f.restype = ct.c_int32
    a, b = ct.c_double(), ct.c_double()
    rc = f(ct.byref(a), ct.byref(b))
    return {"rc": rc, "min_z": a.value, "max_z": b.value}


attempt("StgZ_GetLimits", z_limits)

for name in (
    "StgXY_IsPresent",
    "Stg_GetNosepiecePosition",
    "StgZ_GetActiveZ",
    "StgZ_GetPiezoDevice",
    "Stg_IsNosepiecePresent",
):

    def call0(n=name):
        f = getattr(dll, n)
        f.argtypes = []
        f.restype = ct.c_int32
        return f()

    attempt(f"{name}()", call0)


def z_present(i):
    f = dll.StgZ_IsPresent
    f.argtypes = [ct.c_int32]
    f.restype = ct.c_int32
    return f(i)


attempt("StgZ_IsPresent(0)", lambda: z_present(0))
attempt("StgZ_IsPresent(1)", lambda: z_present(1))


def objective_name(pos):
    f = dll.Stg_GetNosepieceObjectiveName
    f.argtypes = [ct.c_int32, ct.c_wchar_p, ct.c_int32]
    f.restype = ct.c_int32
    buf = ct.create_unicode_buffer(256)
    rc = f(pos, buf, 256)
    return {"rc": rc, "name": buf.value}


for pos in range(1, 7):
    attempt(f"Stg_GetNosepieceObjectiveName({pos})", lambda p=pos: objective_name(p))


def calibration():
    # Get_Calibration(char *objective, double *cal, double *aspect, int *unit); macro 'char' is wide in NIS 6.
    f = dll.Get_Calibration
    f.argtypes = [
        ct.c_wchar_p,
        ct.POINTER(ct.c_double),
        ct.POINTER(ct.c_double),
        ct.POINTER(ct.c_int32),
    ]
    f.restype = ct.c_double
    buf = ct.create_unicode_buffer(256)
    cal, asp, unit = ct.c_double(), ct.c_double(), ct.c_int32()
    rc = f(buf, ct.byref(cal), ct.byref(asp), ct.byref(unit))
    return {
        "rc": rc,
        "objective": buf.value,
        "cal": cal.value,
        "aspect": asp.value,
        "unit": unit.value,
    }


attempt("Get_Calibration (needs an open image)", calibration)


def info_str(i):
    f = dll.Get_InfoStr
    f.argtypes = [ct.c_int32, ct.c_wchar_p]
    f.restype = ct.c_int32
    buf = ct.create_unicode_buffer(256)
    f(i, buf)
    return buf.value


attempt("Get_InfoStr(1) version", lambda: info_str(1))

# Does a background thread outlive the macro?  It writes a heartbeat every second for 10 s.
HEART = r"C:\Users\t.de\repos\ZMART-microscopy\zmart_drivers\nikon\spike\probe4_heartbeat.txt"


def heartbeat():
    for i in range(10):
        time.sleep(1)
        try:
            xy = read_xy()
        except Exception as exc:  # noqa: BLE001
            xy = f"error {exc}"
        with open(HEART, "a", encoding="utf-8") as fh:
            fh.write(f"beat {i} at {time.strftime('%H:%M:%S')} xy={xy}\n")


open(HEART, "w").close()
threading.Thread(target=heartbeat, name="zmart-heartbeat", daemon=True).start()
log("heartbeat thread started; macro returns now")
log("DONE")
