"""Probe: what does the Python interpreter inside NIS-Elements give us?

Run this once from inside NIS (see ``probe_nis_python.mac``). It never moves
anything; it only reads and writes a report to ``probe_nis_python.report.txt``
next to this file. The report tells us which door into NIS we can use for the
driver: the ``nis`` module (and whether macro commands are reachable through it),
the JOBS "DeviceManager" helpers, or only the classic macro language.
"""

import sys

REPORT = (
    r"C:\Users\t.de\repos\ZMART-microscopy\zmart_drivers\nikon\spike\probe_nis_python.report.txt"
)
lines = []


def flush():
    with open(REPORT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def log(*parts):
    lines.append(" ".join(str(p) for p in parts))
    flush()  # write after every line, so a crash still leaves a partial report


log("probe started")


def attempt(label, fn):
    """Run one probe step and record either its result or its error."""
    try:
        result = fn()
        log(f"[ok]   {label}: {result!r}")
        return result
    except Exception as exc:  # noqa: BLE001 - a probe must survive anything
        log(f"[fail] {label}: {type(exc).__name__}: {exc}")
        return None


log("python:", sys.version)
log("executable:", sys.executable)
log("argv:", sys.argv)
log("sys.path:", sys.path)
log("__name__:", __name__)
log("main module attrs:", sorted(a for a in dir(sys.modules["__main__"]) if not a.startswith("__")))
log("builtins with XY_/Z_:", sorted(n for n in dir(__builtins__) if n.startswith(("XY_", "Z_"))))

nis = attempt("import nis", lambda: __import__("nis"))
if nis is not None:
    log("dir(nis):", sorted(dir(nis)))
    attempt("nis.__file__", lambda: getattr(nis, "__file__", None))
    mac = attempt("nis.mac", lambda: nis.mac)
    if mac is not None:
        attempt("type(nis.mac)", lambda: type(mac))
        names = attempt("dir(nis.mac)", lambda: sorted(dir(mac)))
        if names:
            log("nis.mac count:", len(names))
            log("nis.mac Stg*:", [n for n in names if n.startswith("Stg")][:200])
            log(
                "nis.mac Capture/Live/Image*:",
                [
                    n
                    for n in names
                    if n.startswith(
                        ("Capture", "Live", "Freeze", "ImageSave", "SelectOptConf", "Get_")
                    )
                ],
            )
        for name in (
            "StgGetPosXY",
            "StgMoveXY",
            "StgGetPosZ",
            "Get_Calibration",
            "Capture",
            "ImageSaveAs",
        ):
            attempt(f"getattr(nis.mac, {name!r})", lambda n=name: getattr(mac, n))
    ptr = attempt("nis.ptr", lambda: nis.ptr)
    if ptr is not None:
        attempt("dir(nis.ptr)", lambda: sorted(dir(ptr)))
    # Now the real test: read the XY position through nis.mac, using output pointers.
    if mac is not None and ptr is not None:

        def read_xy():
            x, y = ptr.double(), ptr.double()
            rc = mac.StgGetPosXY(x, y)
            return {"rc": rc, "x": x.value, "y": y.value}

        attempt("nis.mac.StgGetPosXY via nis.ptr.double", read_xy)

        def read_z():
            z = ptr.double()
            rc = mac.StgGetPosZ(z, 0)
            return {"rc": rc, "z": z.value}

        attempt("nis.mac.StgGetPosZ(…, 0)", read_z)

        def read_limits():
            a, b, c, d = (ptr.double() for _ in range(4))
            rc = mac.StgXY_GetLimits(a, b, c, d)
            return {
                "rc": rc,
                "min_x": a.value,
                "min_y": b.value,
                "max_x": c.value,
                "max_y": d.value,
            }

        attempt("nis.mac.StgXY_GetLimits", read_limits)
        attempt("nis.mac.StgXY_IsPresent()", lambda: mac.StgXY_IsPresent())
        attempt("nis.mac.StgZ_IsPresent(0)", lambda: mac.StgZ_IsPresent(0))
        attempt("nis.mac.Stg_GetNosepiecePosition()", lambda: mac.Stg_GetNosepiecePosition())
        attempt(
            "nis.mac.Get_Info(INFO_LIVESTATUS)",
            lambda: mac.Get_Info(getattr(mac, "INFO_LIVESTATUS", 0)),
        )

# The JOBS "DeviceManager API" helpers, if they happen to be globals here too.
for name in ("XY_GetPosition", "Z_GetPosition"):
    fn = globals().get(name) or getattr(__builtins__, name, None)
    if fn is not None:
        attempt(f"{name}()", fn)
    else:
        log(f"[none] {name} is not defined in this context")

for mod in ("limpy", "limpy.macro", "limjob", "limrestapi", "numpy", "fastapi", "uvicorn"):
    attempt(f"import {mod}", lambda m=mod: __import__(m))

attempt("threading works", lambda: __import__("threading").current_thread().name)
log("DONE")
