"""
Post-acquisition file confirmation.
====================================
Confirm, validate, rename, and move files exported by LAS X after
acquisition.

Ten-step workflow::

    1. ``read_relative_path`` — stash baseline before acquisition.
    2. (external) — ``acquire()`` and wait for idle.
    3–5. ``detect_new_files`` — confirm path changed, resolve directory,
         list image and metadata files.
    6. ``wait_all_stable`` — poll until all files are unlocked and
       size-stable.
    7. ``validate_files`` — check counts, sizes, OME-TIFF integrity.
    8–9. ``rename_and_move`` — apply naming convention, copy to
         destination, update embedded filenames.
    10. ``confirm_arrival`` — verify destination files, clean up source.

Orchestrator: ``confirm_acquisition`` chains steps 3–10 after an
``acquire()`` call.

Target naming convention::

    SMART/
        [YYYYMMDD_HHMMSS]_[experiment]/
            Overview_Scan/
                data/
                    Carrier_000/
                        Compartment_Z00_Y00_X00/
                            G00000_P00000_T00000_J08_V00_C00_Z00000.ome.tiff
                            metadata/
                                G00000_P00000_T00000_J08_V00.ome.xml
                analysis/
                feedback/

Source naming (LAS X auto-export)::

    image--L0000--J08--E00--X00--Y00--T0000--Z00--C00.ome.tif
    metadata/image--L0000--J08--E00--T0000.ome.xml

Relevant source segments: T (timepoint), Z (z-slice), C (channel).
L, E, X, Y are replaced by caller-supplied G, P, V values.
J is preserved from the source filename (LAS X internal job number).

Dependency direction:
    - Imports: ``scanning_templates`` (_wait_file_stable),
      ``ome_tiff`` (check/fix/update functions), and stdlib.
    - Imported by: ``__init__`` (re-export).
"""

import logging
import re
import shutil
import struct
import time
from pathlib import Path

from .ome_tiff import (
    check_ome_tiff, check_ome_xml_file,
    fix_ome_tiff, fix_ome_xml_file,
    _read_tiff_tag_270, _RE_IMAGE_NAME, _RE_DESCRIPTION,
)
from .scanning_templates import _wait_file_stable

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


# =====================================================================
# Target filename builders
# =====================================================================

def _build_image_name(parsed, naming):
    """Build target image filename from parsed segments and naming dict.

    Target: ``G00000_P00000_T00000_J08_V00_C00_Z00000.ome.tiff``

    *naming* supplies G, P, V.  T, Z, C come from *parsed*.
    J comes from *parsed* (LAS X internal job number) with fallback
    to *naming*.
    """
    return (
        f"G{naming.get('G', 0):05d}"
        f"_P{naming.get('P', 0):05d}"
        f"_T{parsed['T']:05d}"
        f"_J{parsed.get('J', naming.get('J', 0)):02d}"
        f"_V{naming.get('V', 0):02d}"
        f"_C{parsed['C']:02d}"
        f"_Z{parsed['Z']:05d}"
        ".ome.tiff"
    )


def _build_xml_name(parsed, naming):
    """Build target companion XML filename.

    Target: ``G00000_P00000_T00000_J08_V00.ome.xml``

    J comes from *parsed* (LAS X internal job number) with fallback
    to *naming*.
    """
    return (
        f"G{naming.get('G', 0):05d}"
        f"_P{naming.get('P', 0):05d}"
        f"_T{parsed['T']:05d}"
        f"_J{parsed.get('J', naming.get('J', 0)):02d}"
        f"_V{naming.get('V', 0):02d}"
        ".ome.xml"
    )


# ── Target filename parser (for auto-counter) ──────────────────

_RE_TARGET_IMAGE = re.compile(
    r'^G(?P<G>\d{5})'
    r'_P(?P<P>\d{5})'
    r'_T(?P<T>\d{5})'
    r'_J(?P<J>\d{2})'
    r'_V(?P<V>\d{2})'
    r'_C(?P<C>\d{2})'
    r'_Z(?P<Z>\d{5})'
    r'\.ome\.tiff$'
)


def next_position_index(destination):
    """Scan *destination* for existing target-convention files and
    return the next available ``P`` (position) index.

    If the directory is empty or does not exist, returns 0.
    Otherwise returns ``max(existing P values) + 1``.

    This mimics LAS X repeat-counter behaviour: the first
    acquisition gets P=0, the second P=1, etc.
    """
    destination = Path(destination)
    if not destination.is_dir():
        return 0
    max_p = -1
    for p in destination.iterdir():
        if not p.is_file():
            continue
        m = _RE_TARGET_IMAGE.match(p.name)
        if m:
            max_p = max(max_p, int(m.group("P")))
    return max_p + 1


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
# Predicted manifest
# =====================================================================

def predict_manifest(expected_channels, expected_z, expected_t, naming,
                     *, job_index=None):
    """Predict the filenames that should appear after acquisition.

    Builds the complete list of target image and XML filenames that
    would result from an acquisition with the given dimensions and
    naming parameters.  Useful for pre-logging the expected outcome
    before files are actually checked.

    Args:
        expected_channels: Number of channels (C dimension).
        expected_z: Number of Z slices.
        expected_t: Number of timepoints.
        naming: dict with ``G``, ``P``, ``V`` integer values.
        job_index: LAS X internal job number (e.g. 8 for J08).
            Overrides ``naming["J"]``.  If None, falls back to
            ``naming.get("J", 0)``.

    Returns:
        dict with ``image_names`` (list of str), ``xml_names``
        (list of str), and ``total`` count.
    """
    j_val = job_index if job_index is not None else naming.get("J", 0)

    image_names = []
    for t in range(expected_t):
        for z in range(expected_z):
            for c in range(expected_channels):
                parsed = {"T": t, "Z": z, "C": c, "J": j_val}
                image_names.append(_build_image_name(parsed, naming))

    xml_names = []
    for t in range(expected_t):
        parsed = {"T": t, "J": j_val}
        xml_names.append(_build_xml_name(parsed, naming))

    return {
        "image_names": sorted(image_names),
        "xml_names": sorted(xml_names),
        "total": len(image_names) + len(xml_names),
    }


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
    ``_wait_file_stable`` from ``scanning_templates`` which requires
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
# OME path patching (full path → bare filename)
# =====================================================================

def _replace_full_path_in_xml(xml_bytes, new_filename):
    """Replace full paths in ``<Image Name>`` and ``<Description>`` with bare filename.

    Unlike ``_update_filenames_in_xml`` (which preserves the directory),
    this replaces the *entire* value with just the bare filename.  This
    is needed after rename-and-move so the embedded paths don't point
    back to the old source directory.

    Returns:
        ``(updated_xml_bytes, list_of_change_descriptions)``.
    """
    xml_str = xml_bytes.decode('utf-8')
    changes = []

    def _replace_name(m):
        old_val = m.group(2)
        if old_val == new_filename:
            return m.group(0)
        changes.append(f'Image Name: "{old_val}" -> "{new_filename}"')
        return m.group(1) + new_filename + m.group(3)

    def _replace_desc(m):
        old_val = m.group(2)
        if '\\' not in old_val and '/' not in old_val:
            return m.group(0)
        if old_val == new_filename:
            return m.group(0)
        changes.append(f'Description: "{old_val}" -> "{new_filename}"')
        return m.group(1) + new_filename + m.group(3)

    xml_str = _RE_IMAGE_NAME.sub(_replace_name, xml_str)
    xml_str = _RE_DESCRIPTION.sub(_replace_desc, xml_str)

    return xml_str.encode('utf-8'), changes


def _set_ome_paths_tiff(path, new_filename):
    """Patch ``<Image Name>`` and ``<Description>`` in an OME-TIFF to a bare filename.

    Reads TIFF tag 270, replaces the full path values with *new_filename*,
    and writes the patched binary back in-place.
    """
    try:
        with open(path, 'rb') as f:
            data = bytearray(f.read())
    except OSError as e:
        log.warning("Cannot read %s for OME path patching: %s", path, e)
        return

    xml_raw, desc_offset, desc_count, desc_entry_pos, endian_or_err = \
        _read_tiff_tag_270(data)

    if xml_raw is None:
        return

    try:
        updated_xml, changes = _replace_full_path_in_xml(xml_raw, new_filename)
    except UnicodeDecodeError as e:
        log.warning("Cannot decode XML in %s: %s", path, e)
        return

    if not changes:
        return

    for c in changes:
        log.debug("  TIFF %s: %s", path, c)

    updated_with_null = updated_xml + b'\x00'
    new_len = len(updated_with_null)

    if new_len <= desc_count:
        padded = updated_with_null + b'\x00' * (desc_count - new_len)
        data[desc_offset:desc_offset + desc_count] = padded
    elif desc_offset + desc_count >= len(data):
        data[desc_offset:] = updated_with_null
        struct.pack_into(endian_or_err + 'I', data, desc_entry_pos + 4, new_len)
    else:
        data[desc_offset:desc_offset + desc_count] = b'\x00' * desc_count
        new_offset = len(data)
        data.extend(updated_with_null)
        struct.pack_into(endian_or_err + 'I', data, desc_entry_pos + 4, new_len)
        struct.pack_into(endian_or_err + 'I', data, desc_entry_pos + 8, new_offset)

    with open(path, 'wb') as f:
        f.write(data)


def _set_ome_paths_xml(path, new_filename):
    """Patch ``<Image Name>`` and ``<Description>`` in a companion OME-XML to a bare filename."""
    try:
        with open(path, 'rb') as f:
            raw = f.read()
    except OSError as e:
        log.warning("Cannot read %s for OME path patching: %s", path, e)
        return

    try:
        updated, changes = _replace_full_path_in_xml(raw, new_filename)
    except UnicodeDecodeError as e:
        log.warning("Cannot decode %s: %s", path, e)
        return

    if not changes:
        return

    for c in changes:
        log.debug("  XML %s: %s", path, c)

    with open(path, 'wb') as f:
        f.write(updated)


# =====================================================================
# Steps 8–9: Rename and move
# =====================================================================

def rename_and_move(image_files, xml_files, destination, naming):
    """Rename files to target convention and copy to *destination*.

    Creates the destination directory tree.  After copying:

    - Each ``.ome.tiff``'s embedded XML is patched so ``<Image Name>``
      references its own new filename (via ``update_ome_tiff_filename``).
    - Each companion ``.ome.xml``'s ``<Image Name>`` is patched to
      reference the first corresponding ``.ome.tiff`` for that
      timepoint (the original points to the old source TIFF).

    Args:
        image_files: Source ``.ome.tif`` paths.
        xml_files: Source ``.ome.xml`` paths.
        destination: Target directory (leaf level).
        naming: dict with ``G``, ``P``, ``V`` integer values.

    Returns:
        dict with ``success``, ``moved_files`` (src/dst pairs),
        ``errors``.
    """
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)

    moved = []
    errors = []

    # ── Pass 1: copy and rename TIFF files ──────────────────────
    # Track first TIFF destination path per timepoint for XML cross-referencing
    tiff_by_timepoint = {}  # T -> first new TIFF full path

    for src in image_files:
        parsed = parse_lasx_filename(src.name)
        if parsed is None:
            errors.append(f"Cannot parse: {src.name}")
            continue

        new_name = _build_image_name(parsed, naming)
        dst = destination / new_name

        if dst.exists():
            errors.append(f"Destination already exists: {dst}")
            continue

        try:
            shutil.copy2(src, dst)
            _set_ome_paths_tiff(dst, str(dst))
            moved.append((str(src), str(dst)))
            log.debug("  %s -> %s", src.name, new_name)
        except OSError as e:
            errors.append(f"Copy failed {src.name}: {e}")
            continue

        # Record first TIFF for each timepoint (lowest C, Z)
        t_val = parsed["T"]
        if t_val not in tiff_by_timepoint:
            tiff_by_timepoint[t_val] = str(dst)

    # ── Pass 2: copy and rename companion XML files ─────────────
    if xml_files:
        meta_dst = destination / "metadata"
        meta_dst.mkdir(parents=True, exist_ok=True)

        for src in xml_files:
            parsed = parse_lasx_filename(src.name)
            if parsed is None:
                errors.append(f"Cannot parse: {src.name}")
                continue

            new_name = _build_xml_name(parsed, naming)
            dst = meta_dst / new_name

            if dst.exists():
                errors.append(f"Destination already exists: {dst}")
                continue

            try:
                shutil.copy2(src, dst)
            except OSError as e:
                errors.append(f"Copy failed {src.name}: {e}")
                continue

            # Patch <Image Name> to reference the first new TIFF
            # for this timepoint (full destination path)
            t_val = parsed["T"]
            ref_tiff = tiff_by_timepoint.get(t_val, str(dst))
            _set_ome_paths_xml(dst, ref_tiff)

            moved.append((str(src), str(dst)))
            log.debug("  %s -> %s", src.name, new_name)

    log.info("Moved %d files (%d errors)", len(moved), len(errors))
    return {
        "success": len(errors) == 0,
        "moved_files": moved,
        "errors": errors,
    }


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


# =====================================================================
# Orchestrator: full confirmation flow (steps 3–10)
# =====================================================================

def _result(success, steps, t0, *, error=None):
    """Build a result dict with timing."""
    d = {
        "success": success,
        "steps": steps,
        "total_s": time.perf_counter() - t0,
    }
    if error is not None:
        d["error"] = error
    return d


def confirm_acquisition(client, baseline, media_path, destination, naming,
                        *, expected_channels=None, expected_z=None,
                        expected_t=None, acquire_start=None,
                        min_size=1024, fix_ome=True,
                        stability_timeout=60, cleanup_source=True):
    """Run the full post-acquisition file confirmation flow.

    Call ``read_relative_path(client)`` **before** acquisition to get
    *baseline*, then call this after ``acquire()`` returns.

    Steps executed:
        3–5: Detect new files via ``RelativePathName`` change.
        6: Wait for all files to become stable (unlocked, constant size).
        7: Validate file counts, sizes, and OME-XML integrity.
        8–9: Rename to target convention and copy to *destination*.
        10: Confirm arrival at destination and clean up source.

    When *expected_channels*, *expected_z*, and *expected_t* are all
    provided, a **predicted manifest** is logged before any file
    operations begin — this records exactly which filenames the routine
    expects to produce, making it easy to compare against the actual
    outcome in the logs.

    Args:
        client: LAS X API client.
        baseline: ``RelativePathName`` stashed before acquisition.
        media_path: LAS X export root directory.
        destination: Target directory for renamed files.
        naming: dict with ``G``, ``P``, ``V`` integer values.
        expected_channels: Expected channel count (optional validation).
        expected_z: Expected Z-slice count (optional validation).
        expected_t: Expected timepoint count (optional validation).
        acquire_start: ``time.time()`` taken just before ``acquire()``.
            Enables mtime-based file detection fallback when
            ``RelativePathName`` is unavailable.
        min_size: Minimum acceptable file size in bytes.
        fix_ome: Automatically fix OME-XML schema violations.
        stability_timeout: Max seconds to wait for file stability.
        cleanup_source: Delete source files after confirmation.

    Returns:
        dict with ``success``, ``steps`` (per-step results),
        ``manifest`` (predicted file list), ``total_s``, and ``error``
        on failure.
    """
    t0 = time.perf_counter()
    steps = {}
    manifest = None

    # ── Predicted manifest (log before any file ops) ────────────
    if (expected_channels is not None and expected_z is not None
            and expected_t is not None):
        manifest = predict_manifest(
            expected_channels, expected_z, expected_t, naming)
        log.info("=== Predicted manifest (%d files) ===", manifest["total"])
        log.info("  destination: %s", destination)
        for name in manifest["image_names"]:
            log.info("  [image] %s", name)
        for name in manifest["xml_names"]:
            log.info("  [xml]   metadata/%s", name)
        log.info("=== End predicted manifest ===")

    # ── Steps 3–5: detect new files ─────────────────────────────
    detect = detect_new_files(client, baseline, media_path,
                              acquire_start=acquire_start)
    steps["detect"] = detect
    if not detect["success"]:
        return _result(False, steps, t0, error=detect["error"])

    all_files = detect["image_files"] + detect["xml_files"]

    # Log actual files found vs predicted
    if manifest:
        actual_count = len(detect["image_files"]) + len(detect["xml_files"])
        if actual_count == manifest["total"]:
            log.info("File count matches prediction: %d", actual_count)
        else:
            log.warning("File count MISMATCH: predicted %d, found %d",
                        manifest["total"], actual_count)

    # ── Step 6: wait for stability ──────────────────────────────
    stable = wait_all_stable(all_files, timeout=stability_timeout)
    steps["stability"] = stable
    if not stable["success"]:
        return _result(False, steps, t0, error=stable["error"])

    # ── Step 7: validate ────────────────────────────────────────
    valid = validate_files(
        detect["image_files"], detect["xml_files"],
        expected_channels=expected_channels,
        expected_z=expected_z,
        expected_t=expected_t,
        min_size=min_size,
        fix_ome=fix_ome,
    )
    steps["validation"] = valid
    if not valid["success"]:
        return _result(False, steps, t0,
                       error=f"Validation: {valid['issues']}")

    # ── Steps 8–9: rename and move ──────────────────────────────
    log.info("Renaming and moving files to %s", destination)
    move = rename_and_move(
        detect["image_files"], detect["xml_files"],
        destination, naming,
    )
    steps["move"] = move
    if not move["success"]:
        return _result(False, steps, t0,
                       error=f"Move: {move['errors']}")

    # Log actual vs predicted filenames
    if manifest:
        actual_image_names = sorted([
            Path(dst).name for _, dst in move["moved_files"]
            if dst.endswith(".ome.tiff")])
        actual_xml_names = sorted([
            Path(dst).name for _, dst in move["moved_files"]
            if dst.endswith(".ome.xml")])

        img_match = actual_image_names == manifest["image_names"]
        xml_match = actual_xml_names == manifest["xml_names"]

        if img_match and xml_match:
            log.info("All filenames match predicted manifest")
        else:
            if not img_match:
                predicted = set(manifest["image_names"])
                actual = set(actual_image_names)
                missing = predicted - actual
                extra = actual - predicted
                if missing:
                    log.warning("Missing predicted images: %s", missing)
                if extra:
                    log.warning("Unexpected images: %s", extra)
            if not xml_match:
                predicted = set(manifest["xml_names"])
                actual = set(actual_xml_names)
                missing = predicted - actual
                extra = actual - predicted
                if missing:
                    log.warning("Missing predicted XMLs: %s", missing)
                if extra:
                    log.warning("Unexpected XMLs: %s", extra)

    # ── Step 10: confirm arrival ────────────────────────────────
    confirm = confirm_arrival(
        move["moved_files"], cleanup_source=cleanup_source,
    )
    steps["confirm"] = confirm

    total_s = time.perf_counter() - t0
    log.info("File confirmation %s in %.1fs",
             "complete" if confirm["success"] else "FAILED", total_s)

    result = {
        "success": confirm["success"],
        "steps": steps,
        "total_s": total_s,
    }
    if manifest:
        result["manifest"] = manifest
    return result
