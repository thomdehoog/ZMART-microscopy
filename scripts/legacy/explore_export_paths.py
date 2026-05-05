"""Explore LAS X export file paths and naming structure.

Acquires multiple times and inspects:
  - PyApiImagePathItem.Model.RelativePathName before/after each acquisition
  - export.media_path from LAS X settings
  - actual sibling files on disk (same directory as the last-written file)
  - filename structure analysis
"""

import sys
import time
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent / "controller" / "vendor" / "leica"))

from LasxApi import PYLICamApiConnector as lasx_api
import lasx as drv

# ── Configuration ──────────────────────────────────────────────────
JOB_NAME = "HiRes"        # job to acquire with
N_ACQUISITIONS = 3         # number of acquisitions to run
# ───────────────────────────────────────────────────────────────────


def read_image_path_item(client):
    """Read all available attributes from PyApiImagePathItem.Model."""
    try:
        model = client.PyApiImagePathItem.Model
        attrs = {}
        for attr in dir(model):
            if attr.startswith("_"):
                continue
            try:
                val = getattr(model, attr)
                if not callable(val):
                    attrs[attr] = val
            except Exception as e:
                attrs[attr] = f"<error: {e}>"
        return attrs
    except Exception as e:
        return {"error": str(e)}


def get_relative_path(client):
    """Read RelativePathName from PyApiImagePathItem.Model."""
    try:
        return str(client.PyApiImagePathItem.Model.RelativePathName)
    except Exception:
        return ""


def list_sibling_files(base_dir, relative_file_path):
    """Given base + relative path to a file, list all files in the same dir.

    Returns (file_list, dir_path).
    """
    full = Path(base_dir) / relative_file_path
    # RelativePathName points to a file — list its parent directory
    parent = full.parent if full.suffix else full
    if not parent.is_dir():
        # Maybe it IS a directory
        if full.is_dir():
            parent = full
        else:
            return [], str(parent)

    files = []
    for p in sorted(parent.iterdir()):
        if p.is_file():
            files.append(p.name)
    return files, str(parent)


def analyze_filenames(all_filenames):
    """Analyze the naming structure of collected filenames."""
    if not all_filenames:
        print("\n  No filenames to analyze.")
        return

    extensions = defaultdict(int)
    separators = defaultdict(int)
    prefixes = defaultdict(int)
    segments_by_position = defaultdict(lambda: defaultdict(int))

    for name in all_filenames:
        # Extension (handle double extensions like .ome.tif)
        lower = name.lower()
        if lower.endswith(".ome.tif") or lower.endswith(".ome.tiff"):
            ext = name[lower.rfind(".ome"):]
            stem = name[:lower.rfind(".ome")]
        elif lower.endswith(".ome.xml"):
            ext = name[lower.rfind(".ome"):]
            stem = name[:lower.rfind(".ome")]
        else:
            ext = Path(name).suffix
            stem = Path(name).stem
        extensions[ext] += 1

        # Split on common separators
        if "--" in stem:
            sep = "--"
        elif "__" in stem:
            sep = "__"
        elif "_" in stem:
            sep = "_"
        else:
            sep = None

        if sep:
            separators[sep] += 1
            parts = stem.split(sep)
            for i, part in enumerate(parts):
                segments_by_position[i][part] += 1
            if parts:
                prefixes[parts[0]] += 1

    print("\n  === Filename Structure Analysis ===")
    print(f"\n  Total unique filenames: {len(all_filenames)}")

    print(f"\n  Extensions:")
    for ext, count in sorted(extensions.items()):
        print(f"    {ext}: {count}")

    print(f"\n  Separators used:")
    for sep, count in sorted(separators.items()):
        print(f"    '{sep}': {count}")

    print(f"\n  Prefixes (first segment):")
    for prefix, count in sorted(prefixes.items(), key=lambda x: -x[1]):
        print(f"    {prefix}: {count}")

    print(f"\n  Segments by position:")
    for pos in sorted(segments_by_position.keys()):
        values = segments_by_position[pos]
        unique = len(values)
        examples = list(values.keys())[:8]
        print(f"    Position {pos} ({unique} unique): {examples}")

    print(f"\n  All filenames:")
    for name in all_filenames:
        print(f"    {name}")


def main():
    # ── Connect ────────────────────────────────────────────────────
    client = lasx_api.LasxApiClientPyModel
    if not client.Connect("PythonClient"):
        print("Cannot connect to LAS X.")
        sys.exit(1)
    print("Connected to LAS X")

    # ── Read export settings ───────────────────────────────────────
    settings = drv.get_lasx_settings()
    export = settings.get("export", {}) if settings else {}
    formats = settings.get("export_formats", {}) if settings else {}

    media_path = export.get("media_path", "")
    print(f"\n=== Export Configuration ===")
    print(f"  media_path:       {media_path}")
    print(f"  auto_export:      {export.get('auto_export')}")
    print(f"  auto_save:        {export.get('auto_save')}")
    print(f"  delete_after:     {export.get('delete_after_export')}")

    enabled_fmts = [k for k, v in formats.items() if v and k not in
                    ("compression", "compression_value", "combine_mosaics",
                     "enable_edof", "screenshot")]
    print(f"  enabled formats:  {enabled_fmts}")

    # ── Dump all PyApiImagePathItem attributes once ────────────────
    print(f"\n=== PyApiImagePathItem.Model (all attributes) ===")
    attrs_initial = read_image_path_item(client)
    for k, v in sorted(attrs_initial.items()):
        print(f"  {k}: {v}")

    # ── Acquire N times ────────────────────────────────────────────
    all_filenames_per_acq = []   # list of lists

    for i in range(1, N_ACQUISITIONS + 1):
        print(f"\n{'='*60}")
        print(f"  Acquisition {i}/{N_ACQUISITIONS}")
        print(f"{'='*60}")

        # Read RelativePathName BEFORE
        rel_before = get_relative_path(client)
        print(f"  RelativePathName before: {rel_before!r}")

        # Acquire
        result = drv.acquire(client, JOB_NAME)
        print(f"  acquire() -> success={result['success']}, "
              f"time={result['timing']['total_s']:.1f}s")

        # Small delay for export to finish writing
        time.sleep(2)

        # Read RelativePathName AFTER
        rel_after = get_relative_path(client)
        changed = rel_after != rel_before
        print(f"  RelativePathName after:  {rel_after!r}")
        print(f"  Changed: {changed}")

        # List all sibling files in the same directory
        if media_path and rel_after:
            files, dir_path = list_sibling_files(media_path, rel_after)
            print(f"\n  Files in {dir_path}  ({len(files)} files):")
            for f in files:
                print(f"    {f}")
            all_filenames_per_acq.append(files)
        else:
            print(f"\n  Cannot list files (media_path={media_path!r}, "
                  f"rel={rel_after!r})")
            all_filenames_per_acq.append([])

    # ── Summary ────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  SUMMARY")
    print(f"{'='*60}")

    # Show per-acquisition file counts
    for i, files in enumerate(all_filenames_per_acq, 1):
        print(f"\n  Acquisition {i}: {len(files)} files")

    # Analyze unique filenames across all acquisitions
    all_unique = sorted(set(
        f for files in all_filenames_per_acq for f in files
    ))
    analyze_filenames(all_unique)


if __name__ == "__main__":
    main()
