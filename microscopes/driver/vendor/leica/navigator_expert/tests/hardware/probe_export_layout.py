"""Probe the REAL Navigator Expert export layout for one or more jobs.

Read-only diagnostic. Acquires each named LAS X job once via the public
driver, then dumps EXACTLY what the current exporter sees so we stop
guessing the (C, Z, T) / z-stack / companion-XML structure before
restructuring the collector.

It does NOT persist, rename, move, or repair anything -- it only acquires
(which Leica autosaves to the export folder) and reads. Per image file it
prints: filename, parsed L/J/E/X/Y/T/Z/C + repeat, tifffile shape+dtype,
and whether the companion XML that the exporter resolves is the SAME file
the collector waited on (the wait-set vs copy-set check).

The verdict line answers the load-bearing question: does LAS X write a
z-stack as ONE multi-page OME-TIFF, or one TIFF per Z?

Run (lasxapi env), with a job already configured for a z-stack selected
in LAS X, or pass job names explicitly::

    python tests/hardware/probe_export_layout.py [JOB ...]

Dependency direction: imports the package public API + the exporter/save
internals under probe (navigator_expert_export, files). No writes.
"""

from __future__ import annotations

import sys
from pathlib import Path

import tifffile

# -- import bootstrap: add driver/vendor/leica so `navigator_expert`
#    imports; the package self-bootstraps the repo root for `shared`.
_HERE = Path(__file__).resolve()
_LEICA = _HERE.parents[3]  # hardware -> tests -> navigator_expert -> leica
if str(_LEICA) not in sys.path:
    sys.path.insert(0, str(_LEICA))

import navigator_expert as drv  # noqa: E402
from navigator_expert.acquisition.navigator_expert_export import (  # noqa: E402
    _find_companion_xml,
    collect_navigator_expert_export,
)


def _connect():
    """Connect a Python CAM client (mirrors the working scratch pattern)."""
    from navigator_expert.core.lasx_runtime import load_lasx_api_runtime

    lasx_api = load_lasx_api_runtime()
    client = lasx_api.LasxApiClientPyModel
    print("Connect:", client.Connect("PythonClient"))
    return client


def _jobs_to_probe(client, argv):
    if argv:
        return argv
    sel = drv.get_selected_job(client)
    if sel and sel.get("Name"):
        return [sel["Name"]]
    jobs = drv.get_jobs(client) or []
    return [j["Name"] for j in jobs[:1] if j.get("Name")]


def _shape(path):
    try:
        arr = tifffile.imread(str(path))
        return f"{arr.shape} {arr.dtype}"
    except Exception as exc:  # diagnostic only
        return f"<imread failed: {exc}>"


def probe_job(client, job):
    print(f"\n{'=' * 72}\nJOB: {job}\n{'=' * 72}")
    acq = drv.acquire(client, job)
    print(f"acquire ok: started={acq.started_at:.3f} "
          f"finished={acq.finished_at:.3f}")

    exported = collect_navigator_expert_export(client, acq)
    waited_xml = {Path(p).resolve() for p in exported.metadata_files}
    print(f"method     : {exported.method}")
    print(f"source_dir : {exported.source_dir}")
    print(f"images     : {len(exported.image_files)}   "
          f"metadata (waited): {len(exported.metadata_files)}")

    print("\nRaw source listing:")
    for p in sorted(exported.source_dir.iterdir()):
        print(f"  {p.name}")
    meta = exported.source_dir / "metadata"
    if meta.is_dir():
        print(" metadata/:")
        for p in sorted(meta.iterdir()):
            print(f"  metadata/{p.name}")

    cset, zset, tset = set(), set(), set()
    print("\nPer-image:")
    for img in sorted(exported.image_files):
        d = drv.parse_lasx_filename(img.name) or {}
        cset.add(d.get("C"))
        zset.add(d.get("Z"))
        tset.add(d.get("T"))
        companion = None
        if d:
            acq_view = type(
                "Acq",
                (),
                {"started_at": min(p.stat().st_mtime for p in exported.image_files)},
            )()
            companion = _find_companion_xml(img.parent, d, d.get("T"), acq_view)
        in_wait = (companion is not None
                   and companion.resolve() in waited_xml)
        flag = "ok" if in_wait else "NOT-IN-WAIT-SET"
        print(f"  {img.name}")
        print(f"      C={d.get('C')} Z={d.get('Z')} T={d.get('T')} "
              f"J={d.get('J')} repeat={d.get('repeat')}  shape={_shape(img)}")
        print(f"      companion XML: "
              f"{companion.name if companion else None}  [{flag}]")

    # Verdict: one multi-page TIFF vs one file per Z.
    print("\nVERDICT:")
    print(f"  distinct C={sorted(cset)}  Z={sorted(zset)}  T={sorted(tset)}")
    if len(exported.image_files) == 1:
        arr = tifffile.imread(str(exported.image_files[0]))
        if getattr(arr, "ndim", 0) >= 3:
            print("  -> ONE multi-page TIFF (Z/C live in pages). "
                  "save() reading one file CAN yield a stack.")
        else:
            print("  -> ONE 2-D TIFF. No stack dimension in the file.")
    else:
        multi_z = len([z for z in zset if z is not None]) > 1
        print(f"  -> {len(exported.image_files)} separate files"
              f"{'; Z varies across files => ONE FILE PER Z' if multi_z else ''}."
              " save() reading one file returns a single plane, NOT a stack.")


def main(argv):
    client = _connect()
    for job in _jobs_to_probe(client, argv):
        try:
            probe_job(client, job)
        except Exception as exc:
            print(f"\nJOB {job}: probe failed: {exc}")


if __name__ == "__main__":
    main(sys.argv[1:])
