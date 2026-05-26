"""
LAS X source-side primitives.
================================
Discovery, validation, and parsing of files exported by LAS X.
The canonical naming convention now lives in ``_shared.output_layout``
and is consumed by ``driver.acquisition`` for atomic save under
``media_path / "smart"``.

What stays here (LAS X-specific, used by ``driver.acquisition``):

    parse_lasx_filename   — parse a LAS X export filename into segments
                             (handles both ``.ome.tif`` and ``.ome.xml``).
    read_relative_path    — read ``RelativePathName`` from the API model
                             (baseline before acquisition).
    detect_new_files      — confirm new files appeared after acquisition,
                             resolve directory, list image + XML files.
    wait_all_stable       — poll until files are unlocked and size-stable.
    validate_files        — check counts, sizes, OME-TIFF integrity.
    confirm_arrival       — verify destination files, optionally clean source.

Source naming (LAS X auto-export)::

    image--L0000--J08--E00--X00--Y00--T0000--Z00--C00.ome.tif
    metadata/image--L0000--J08--E00--T0000.ome.xml

The legacy SMART naming convention (``G00000_P00000_T00000_J08_V00_C00_Z00000.ome.tiff``
under a ``Carrier/Compartment`` hierarchy) was deleted on 2026-05-11.
New code uses ``_shared.output_layout`` for canonical output naming.

Dependency direction:
    - Imports: ``_file_utils`` (``_wait_file_stable``),
      ``ome_tiff`` (validation helpers), and stdlib.
    - Imported by: ``acquisition.py``, ``acquire.py``, ``__init__``
      (re-export).
"""

import logging
import re
import time
from pathlib import Path

from .ome import (
    check_ome_tiff, check_ome_xml_file,
    fix_ome_tiff, fix_ome_xml_file,
)
from .._file_utils import _wait_file_stable

log = logging.getLogger(__name__)


# =====================================================================
# LAS X filename parsing
# =====================================================================

_RE_LASX_IMAGE = re.compile(
    r'^image'
    r'--L(?P<L>\d+)'
    r'--J(?P<J>\d+)'
    r'--E(?P<E>\d+)'
    r'--X(?P<X>\d+)'
    r'--Y(?P<Y>\d+)'
    r'--T(?P<T>\d+)'
    r'--Z(?P<Z>\d+)'
    r'--C(?P<C>\d+)'
    r'(?:--(?P<repeat>\d{3}))?'
    r'\.ome\.tif$'
)

_RE_LASX_XML = re.compile(
    r'^image'
    r'--L(?P<L>\d+)'
    r'--J(?P<J>\d+)'
    r'--E(?P<E>\d+)'
    r'--T(?P<T>\d+)'
    r'(?:--(?P<repeat>\d{3}))?'
    r'\.ome\.xml$'
)


def parse_lasx_filename(name):
    """Parse a LAS X export filename into a dict of segment values.

    Handles both image files (``.ome.tif``) and companion XML
    (``.ome.xml``).  Returns None if the filename does not match
    the expected pattern.

    Segment values are returned as integers.  The ``repeat`` key
    is None for first-acquisition files (no ``--NNN`` suffix).
    """
    m = _RE_LASX_IMAGE.match(name)
    if m is None:
        m = _RE_LASX_XML.match(name)
    if m is None:
        return None
    d = m.groupdict()
    for k, v in d.items():
        if v is not None:
            d[k] = int(v)
    return d


# (Legacy SMART filename builders and parser deleted 2026-05-11.
# Canonical naming now lives in _shared.output_layout.)


# =====================================================================
# Step 1: Read baseline RelativePathName
# =====================================================================

def read_relative_path(client):
    """Read ``RelativePathName`` from the LAS X data model.

    Call **before** acquisition to stash the baseline value.
    Returns empty string on failure or when no acquisition has
    occurred in the current session.
    """
    try:
        return str(client.PyApiImagePathItem.Model.RelativePathName)
    except Exception as e:
        log.warning("Could not read RelativePathName: %s", e)
        return ""


# =====================================================================
# Steps 3–5: Detect and list new files
# =====================================================================

def _find_new_files_by_mtime(media_path, acquire_start, poll_timeout=15.0,
                              poll_interval=1.0):
    """Scan *media_path* for ``.ome.tif`` files written after *acquire_start*.

    Searches ``Experiments/experiment--*/`` directories under
    *media_path* for image files whose mtime is after the acquisition
    start timestamp.  Polls until at least one file is found or
    timeout expires (export may still be writing).

    Returns ``(source_dir, image_files, xml_files)`` or
    ``(None, [], [])`` on timeout.
    """
    media = Path(media_path)
    experiments_dir = media / "Experiments"
    if not experiments_dir.is_dir():
        # Try media_path directly
        experiments_dir = media

    deadline = time.perf_counter() + poll_timeout

    while time.perf_counter() < deadline:
        # Scan experiment dirs (newest first by name)
        best_dir = None
        best_files = []

        for exp_dir in sorted(experiments_dir.iterdir(), reverse=True):
            if not exp_dir.is_dir():
                continue
            new_files = []
            for p in exp_dir.iterdir():
                if (p.is_file() and p.name.endswith(".ome.tif")
                        and p.stat().st_mtime >= acquire_start):
                    new_files.append(p)
            if new_files:
                best_dir = exp_dir
                best_files = new_files
                break  # newest experiment dir with new files

        if best_files:
            image_files = sorted(best_files)

            # Determine repeat suffix from the files
            parsed_first = parse_lasx_filename(image_files[0].name)
            target_repeat = parsed_first.get("repeat") if parsed_first else None

            # Filter to same repeat suffix
            if parsed_first:
                image_files = [
                    f for f in image_files
                    if (p := parse_lasx_filename(f.name)) is not None
                    and p.get("repeat") == target_repeat
                ]

            # Companion XMLs
            meta_dir = best_dir / "metadata"
            xml_files = []
            if meta_dir.is_dir():
                for p in sorted(meta_dir.iterdir()):
                    if (p.is_file() and p.name.endswith(".ome.xml")
                            and p.stat().st_mtime >= acquire_start):
                        parsed = parse_lasx_filename(p.name)
                        if parsed is not None and parsed.get("repeat") == target_repeat:
                            xml_files.append(p)

            return best_dir, sorted(image_files), xml_files

        time.sleep(poll_interval)

    return None, [], []


def detect_new_files(client, baseline, media_path, *,
                     acquire_start=None,
                     path_poll_timeout=5.0, path_poll_interval=0.5,
                     mtime_poll_timeout=15.0):
    """Confirm new files appeared after acquisition, resolve paths, list files.

    Combines steps 3 (detection), 4 (path resolution), and 5 (file listing).

    **Primary method**: poll ``RelativePathName`` for a change from
    *baseline*.  **Fallback** (when ``RelativePathName`` is unreliable):
    scan the export directory for ``.ome.tif`` files with mtime after
    *acquire_start*.

    Args:
        client: LAS X API client.
        baseline: Value from ``read_relative_path`` before acquisition.
        media_path: Export root directory
            (``get_lasx_settings()["export"]["media_path"]``).
        acquire_start: ``time.time()`` timestamp taken just before
            ``acquire()``.  Enables mtime fallback when provided.
        path_poll_timeout: Seconds to wait for RelativePathName change.
        path_poll_interval: Seconds between RelativePathName polls.
        mtime_poll_timeout: Seconds to wait for mtime fallback scan.

    Returns:
        dict with ``success``, ``source_dir``, ``image_files``,
        ``xml_files``, ``repeat_suffix``, ``method`` (``"api"`` or
        ``"mtime"``), or ``error`` on failure.
    """
    # ── Primary: poll RelativePathName ──────────────────────────
    deadline = time.perf_counter() + path_poll_timeout
    new_path = ""
    while time.perf_counter() < deadline:
        new_path = read_relative_path(client)
        if new_path and new_path != baseline:
            break
        time.sleep(path_poll_interval)

    if new_path and new_path != baseline:
        log.info("RelativePathName changed: %r -> %r", baseline, new_path)
        full_path = Path(media_path) / new_path.lstrip("\\/")


        if not full_path.is_file():
            log.warning("RelativePathName file not found: %s", full_path)
        else:
            source_dir = full_path.parent
            ref_parsed = parse_lasx_filename(full_path.name)
            if ref_parsed is not None:
                return _collect_files(source_dir, ref_parsed, method="api")

    # ── Fallback: mtime-based scan ──────────────────────────────
    if acquire_start is None:
        return {
            "success": False,
            "error": ("RelativePathName did not change and no "
                      "acquire_start timestamp for mtime fallback "
                      f"(baseline={baseline!r}, current={new_path!r})"),
        }

    log.info("RelativePathName unavailable — falling back to mtime scan "
             "(acquire_start=%.1f)", acquire_start)

    source_dir, image_files, xml_files = _find_new_files_by_mtime(
        media_path, acquire_start, poll_timeout=mtime_poll_timeout)

    if source_dir is None or not image_files:
        return {
            "success": False,
            "error": ("No new .ome.tif files found after acquisition "
                      f"(scanned {media_path})"),
        }

    ref_parsed = parse_lasx_filename(image_files[0].name)
    target_repeat = ref_parsed.get("repeat") if ref_parsed else None
    repeat_str = f"--{target_repeat:03d}" if target_repeat is not None else ""

    log.info("mtime scan found %d image + %d XML files in %s (repeat=%s)",
             len(image_files), len(xml_files), source_dir,
             repeat_str or "none")

    return {
        "success": True,
        "relative_path": None,
        "source_dir": source_dir,
        "image_files": image_files,
        "xml_files": xml_files,
        "repeat_suffix": repeat_str,
        "method": "mtime",
    }


def _collect_files(source_dir, ref_parsed, *, method="api"):
    """Collect image and XML files matching *ref_parsed*'s repeat suffix and job index."""
    target_repeat = ref_parsed.get("repeat")
    target_j = ref_parsed.get("J")

    image_files = []
    for p in sorted(source_dir.iterdir()):
        if not p.is_file() or not p.name.endswith(".ome.tif"):
            continue
        parsed = parse_lasx_filename(p.name)
        if parsed is None:
            continue
        if parsed.get("repeat") != target_repeat:
            continue
        if target_j is not None and parsed.get("J") != target_j:
            continue
        image_files.append(p)

    meta_dir = source_dir / "metadata"
    xml_files = []
    if meta_dir.is_dir():
        for p in sorted(meta_dir.iterdir()):
            if not p.is_file() or not p.name.endswith(".ome.xml"):
                continue
            parsed = parse_lasx_filename(p.name)
            if parsed is None:
                continue
            if parsed.get("repeat") != target_repeat:
                continue
            if target_j is not None and parsed.get("J") != target_j:
                continue
            xml_files.append(p)

    repeat_str = f"--{target_repeat:03d}" if target_repeat is not None else ""

    log.info("Detected %d image + %d XML files in %s (repeat=%s, method=%s)",
             len(image_files), len(xml_files), source_dir,
             repeat_str or "none", method)

    return {
        "success": True,
        "relative_path": None if method == "mtime" else str(source_dir),
        "source_dir": source_dir,
        "image_files": image_files,
        "xml_files": xml_files,
        "repeat_suffix": repeat_str,
        "method": method,
    }


# =====================================================================
# Step 6: Wait for file stability
# =====================================================================

def wait_all_stable(files, *, timeout=60, poll_interval=0.5,
                    stable_readings=3):
    """Block until every file in *files* is unlocked and size-stable.

    Distributes the timeout across all files sequentially.  Uses
    ``_wait_file_stable`` from ``_file_utils`` which requires
    3 consecutive stable-size + unlocked readings.

    Returns:
        dict with ``success`` and list of any ``unstable`` paths.
    """
    t0 = time.perf_counter()
    unstable = []

    for f in files:
        remaining = timeout - (time.perf_counter() - t0)
        if remaining <= 0:
            unstable.append(f)
            continue
        if not _wait_file_stable(f, remaining, poll_interval, stable_readings):
            unstable.append(f)

    if unstable:
        elapsed = time.perf_counter() - t0
        log.warning("%d/%d files not stable after %.1fs",
                    len(unstable), len(files), elapsed)
        return {
            "success": False,
            "error": f"{len(unstable)} file(s) not stable after {timeout}s",
            "unstable": [str(f) for f in unstable],
        }

    elapsed = time.perf_counter() - t0
    log.debug("All %d files stable in %.1fs", len(files), elapsed)
    return {"success": True, "stable_count": len(files),
            "elapsed_s": elapsed}


# =====================================================================
# Step 7: Validate files
# =====================================================================

def validate_files(image_files, xml_files, *,
                   expected_channels=None, expected_z=None,
                   expected_t=None, min_size=1024, fix_ome=False):
    """Check file counts, sizes, and OME-XML integrity.

    Args:
        image_files: ``.ome.tif`` paths from this acquisition.
        xml_files: ``.ome.xml`` paths from this acquisition.
        expected_channels: Expected channel count (for count validation).
        expected_z: Expected Z-slice count.
        expected_t: Expected timepoint count.
        min_size: Minimum acceptable file size in bytes.
        fix_ome: If True, automatically fix OME-XML schema violations.

    Returns:
        dict with ``success``, ``issues`` list, ``logs`` list,
        ``image_count``, ``xml_count``.
    """
    logs = []
    issues = []

    # ── Count check ─────────────────────────────────────────────
    if (expected_channels is not None and expected_z is not None
            and expected_t is not None):
        expected = expected_channels * expected_z * expected_t
        if len(image_files) != expected:
            issues.append(
                f"Expected {expected} images "
                f"({expected_channels}C x {expected_z}Z x {expected_t}T), "
                f"got {len(image_files)}")

        # XML: one per timepoint
        if len(xml_files) != expected_t:
            issues.append(
                f"Expected {expected_t} XML files (one per T), "
                f"got {len(xml_files)}")

    # ── Size check ──────────────────────────────────────────────
    for f in image_files:
        size = f.stat().st_size
        if size < min_size:
            issues.append(f"{f.name}: {size} B < {min_size} B minimum")

    # ── OME-TIFF integrity ──────────────────────────────────────
    for f in image_files:
        r = check_ome_tiff(f)
        if r.get("error"):
            issues.append(f"{f.name}: OME check error — {r['error']}")
        elif r.get("corrupted"):
            if fix_ome:
                fr = fix_ome_tiff(f)
                if fr["success"]:
                    logs.append(f"Fixed {f.name}: {fr['changes']}")
                else:
                    issues.append(
                        f"{f.name}: OME fix failed — {fr.get('error')}")
            else:
                issues.append(
                    f"{f.name}: OME violations — {r['violations']}")

    # ── Companion OME-XML integrity ─────────────────────────────
    for f in xml_files:
        r = check_ome_xml_file(f)
        if r.get("error"):
            issues.append(f"{f.name}: OME-XML error — {r['error']}")
        elif r.get("corrupted"):
            if fix_ome:
                fr = fix_ome_xml_file(f)
                if fr["success"]:
                    logs.append(f"Fixed {f.name}: {fr['changes']}")
                else:
                    issues.append(
                        f"{f.name}: OME-XML fix failed — {fr.get('error')}")
            else:
                issues.append(
                    f"{f.name}: OME-XML violations — {r['violations']}")

    if issues:
        log.warning("Validation found %d issue(s)", len(issues))
    else:
        log.debug("Validation passed: %d images, %d XML",
                  len(image_files), len(xml_files))

    return {
        "success": len(issues) == 0,
        "issues": issues,
        "logs": logs,
        "image_count": len(image_files),
        "xml_count": len(xml_files),
    }


# =====================================================================
# Steps 8–9: Rename and move
# =====================================================================

# =====================================================================
# Step 10: Confirm arrival and clean up
# =====================================================================

def confirm_arrival(moved_files, *, cleanup_source=True):
    """Verify files at destination, optionally delete source files.

    Checks that every destination file exists and has non-zero size.
    (Exact size comparison is skipped because ``update_ome_*_filename``
    may change the file size during the rename step.)

    If *cleanup_source* is True, deletes the source file after
    verification.  Attempts to ``rmdir`` empty source directories.

    Args:
        moved_files: List of ``(src_path, dst_path)`` string pairs.
        cleanup_source: Delete verified source files.

    Returns:
        dict with ``success``, ``verified``, ``cleanup_count``,
        ``errors``.
    """
    verified = 0
    cleanup_count = 0
    errors = []
    source_dirs = set()

    for src_str, dst_str in moved_files:
        src = Path(src_str)
        dst = Path(dst_str)

        if not dst.is_file():
            errors.append(f"Missing at destination: {dst}")
            continue

        if dst.stat().st_size == 0:
            errors.append(f"Zero-size at destination: {dst}")
            continue

        verified += 1

        if cleanup_source and src.is_file():
            try:
                src.unlink()
                cleanup_count += 1
                source_dirs.add(src.parent)
            except OSError as e:
                errors.append(f"Cannot delete source {src.name}: {e}")

    # Try to remove empty source directories (deepest first)
    if cleanup_source:
        for d in sorted(source_dirs, key=lambda p: len(p.parts),
                        reverse=True):
            try:
                d.rmdir()  # only succeeds if empty
                log.debug("Removed empty directory: %s", d)
            except OSError:
                pass

    success = len(errors) == 0 and verified == len(moved_files)
    log.info("Arrival confirmed: %d/%d files, cleaned up %d source files",
             verified, len(moved_files), cleanup_count)
    return {
        "success": success,
        "verified": verified,
        "cleanup_count": cleanup_count,
        "errors": errors,
    }


