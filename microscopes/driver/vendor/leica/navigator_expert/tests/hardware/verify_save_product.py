"""Verify the revised save() persists the FULL flat LAS X export product.

Run AFTER the driver fix lands (save() returns image_paths / xml_paths and
writes one canonical file per (c, z, t)). Acquires one job, saves to a
THROWAWAY output_root, and checks the contract end-to-end on the sim:

  1. data/ has one canonical .ome.tiff per exported (C, Z, T) plane, with
     LAS X C->c, Z->z, T->t.
  2. data/metadata/ has one .ome.xml per T position.
  3. The Leica source export bytes are UNCHANGED (OME repair hit the copy,
     not the producer's folder).
  4. The returned manifest maps every plane (image_paths) and position
     (xml_paths); save() exposes no single loaded pixel array.

Non-destructive to the Leica export folder; writes only under a temp
output_root (path printed at the end for inspection/cleanup).

    python tests/hardware/verify_save_product.py [JOB]

If a check FAILs after Codex's build, the label says which contract point
drifted. Manifest field names (image_paths/xml_paths) follow the spec;
adjust the two getattr lines if Codex named them differently.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

# -- import bootstrap: driver/vendor/leica so `navigator_expert` imports.
_HERE = Path(__file__).resolve()
_LEICA = _HERE.parents[3]  # hardware -> tests -> navigator_expert -> leica
if str(_LEICA) not in sys.path:
    sys.path.insert(0, str(_LEICA))

import navigator_expert as drv  # noqa: E402
from shared.output_layout import Naming, run_hash, parse_image_name  # noqa: E402


def _connect():
    from navigator_expert.core.lasx_runtime import load_lasx_api_runtime

    lasx_api = load_lasx_api_runtime()
    client = lasx_api.LasxApiClientPyModel
    print("Connect:", client.Connect("PythonClient"))
    return client


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fresh_source_files(media_path: Path, since: float) -> dict[Path, str]:
    """All .ome.tif/.ome.xml under Experiments newer than `since` -> sha256."""
    out: dict[Path, str] = {}
    exp = media_path / "Experiments"
    root = exp if exp.is_dir() else media_path
    dirs = list(root.iterdir()) if root.is_dir() else []
    for d in dirs:
        if not d.is_dir():
            continue
        candidates = list(d.glob("*.ome.tif"))
        candidates += list((d / "metadata").glob("*.ome.xml"))
        for p in candidates:
            try:
                if p.stat().st_mtime >= since:
                    out[p] = _sha(p)
            except OSError:
                pass
    return out


def _save_source_roots(exporter: str) -> list[Path]:
    return [drv.save_source_root(exporter)]


def _source_snapshot(roots: list[Path]) -> dict[Path, str]:
    out: dict[Path, str] = {}
    suffixes = (".ome.tif", ".ome.tiff", ".ome.xml", ".xlef", ".xlif")
    for root in roots:
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if p.is_file() and p.name.lower().endswith(suffixes):
                out[p.resolve()] = _sha(p)
    return out


def _summary_source_files(out_root: Path, roots: list[Path]) -> tuple[set[Path], list[str]]:
    summary = out_root / "summary.json"
    if not summary.is_file():
        return set(), ["summary.json missing"]
    data = json.loads(summary.read_text(encoding="utf-8"))
    rels = []
    for record in data.get("acquisitions", []):
        if record.get("source"):
            rels.append(record["source"])
        for vendor in record.get("vendor_metadata", []):
            if vendor.get("source"):
                rels.append(vendor["source"])

    files: set[Path] = set()
    missing: list[str] = []
    for rel in rels:
        raw = Path(rel)
        candidates = [raw] if raw.is_absolute() else [root / rel for root in roots]
        for candidate in candidates:
            if candidate.is_file():
                files.add(candidate.resolve())
                break
        else:
            missing.append(rel)
    return files, missing


def _planes_from_source(files) -> tuple[set, set]:
    """(C, Z, T) tuples + distinct T from source image filenames."""
    czt, ts = set(), set()
    for p in files:
        if not p.name.lower().endswith((".ome.tif", ".ome.tiff")):
            continue
        d = drv.parse_lasx_filename(p.name) or {}
        if d.get("C") is not None:
            czt.add((d["C"], d["Z"], d["T"]))
            ts.add(d["T"])
            continue
        from navigator_expert.acquisition.lasx_native_autosave import (
            _plane_sources_from_tiff,
        )

        for idx in _plane_sources_from_tiff(p):
            czt.add((idx.c, idx.z, idx.t))
            ts.add(idx.t)
    return czt, ts


def main(argv) -> None:
    client = _connect()
    job = argv[0] if argv else (drv.get_selected_job(client) or {}).get("Name")
    if not job:
        print("No job selected and none given.")
        return
    exporter = drv.active_save_exporter()
    source_roots = _save_source_roots(exporter)

    acq = drv.acquire(client, job)
    before_sources = _source_snapshot(source_roots)

    out_root = Path(tempfile.mkdtemp(prefix="verify_save_"))
    naming = Naming(acquisition_type="verify-save", hash6=run_hash(), p=0)
    saved = drv.save(client, acq, out_root, naming, exporter=exporter)
    source_files, missing_sources = _summary_source_files(out_root, source_roots)
    source_images = {
        p: before_sources.get(p)
        for p in source_files
        if p.name.lower().endswith((".ome.tif", ".ome.tiff"))
    }
    if not source_images and source_roots:
        source_images = _fresh_source_files(source_roots[0], acq.started_at)
    src_czt, src_t = _planes_from_source(source_images)
    print(f"job={job}  source planes={len(src_czt)}  distinct T={len(src_t)}")

    data = out_root / "verify-save" / "data"
    meta = data / "metadata"
    out_imgs = sorted(data.glob("*.ome.tiff"))
    out_xml = sorted(meta.glob("*.ome.xml"))
    out_czt = set()
    for p in out_imgs:
        n = parse_image_name(p.name)
        if n is not None:
            out_czt.add((n.c, n.z, n.t))

    def check(name: str, ok: bool, extra: str = "") -> None:
        tag = "PASS" if ok else "FAIL"
        print(f"  [{tag}] {name}{(' -- ' + extra) if extra else ''}")

    img_paths = getattr(saved, "image_paths", None)
    xml_paths = getattr(saved, "xml_paths", None)
    source_unchanged = (
        not missing_sources
        and bool(source_files)
        and all(p in before_sources for p in source_files)
        and all(p.exists() for p in source_files)
        and all(_sha(p) == before_sources[p] for p in source_files)
    )

    print("\nChecks:")
    check("summary source files resolved",
          not missing_sources, ", ".join(missing_sources[:3]))
    check("one data/ file per source plane",
          len(out_imgs) == len(src_czt), f"{len(out_imgs)} vs {len(src_czt)}")
    check("output (c,z,t) == source (C,Z,T)", out_czt == src_czt)
    check("one XML per T", len(out_xml) == len(src_t),
          f"{len(out_xml)} vs {len(src_t)}")
    check("Leica source export bytes UNCHANGED (repair hit the copy)",
          source_unchanged)
    check("manifest image_paths complete",
          isinstance(img_paths, dict) and len(img_paths) == len(src_czt),
          f"{len(img_paths) if isinstance(img_paths, dict) else img_paths}")
    check("manifest xml_paths complete",
          isinstance(xml_paths, dict) and len(xml_paths) == len(src_t))
    check("save() exposes no loaded pixel array (manifest only)",
          not hasattr(saved, "image"))

    print(f"\noutput_root (temp -- inspect, then delete): {out_root}")


if __name__ == "__main__":
    main(sys.argv[1:])
