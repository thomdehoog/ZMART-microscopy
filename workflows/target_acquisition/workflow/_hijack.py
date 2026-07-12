"""Overwrite a saved simulator image with mock pixels, safely.

In simulation mode the workflow runs the real acquire-and-save code path, then
replaces the saved ``.ome.tiff`` pixels with realistic-looking mock content so
the analysis afterwards sees believable cells. This module does that overwrite
for the images the controller-only flow returns, and only when it is certain
the frame came from the LAS X simulator.

The certainty comes from a positive allowlist: the overwrite happens only when
the copied native AutoSave vendor metadata's ``SystemTypeName`` is exactly
``"SIMULATOR"``. Any other value, a missing element, or unreadable metadata
raises :class:`NonSimulatorFrameError` and nothing is written. This matters
because the overwrite is destructive -- a mistake here would replace real
microscope pixels with fabricated ones. The allowlist and the overwrite are one
indivisible step, so there is no way to overwrite a frame without first proving
it is a simulator frame.

The overwrite preserves the file's OME-XML description byte-for-byte. That
description carries the ``SystemTypeName`` block the next run's allowlist reads,
so losing it would break the guard; the recipe re-reads the rewritten file and
refuses if the description changed.
"""

from __future__ import annotations

import os
import re
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import tifffile

from ._records import record_channel_paths

_IMAGE_NAME_RE = re.compile(
    r"^(?P<acq>[a-z0-9]+(?:-[a-z0-9]+)*)_(?P<hash>[0-9a-z]{6})"
    r"_(?P<label>[A-Za-z0-9_-]+)_T(?P<t>\d{6})_C(?P<c>\d{2})_Z(?P<z>\d{5})"
    r"\.ome\.tiff$"
)


def _filename_context(filename: str):
    """Extract only the filename fields simulation providers consume."""

    match = _IMAGE_NAME_RE.fullmatch(filename)
    if match is None:
        raise RuntimeError(f"saved image has a non-canonical filename: {filename}")
    return SimpleNamespace(
        acquisition_type=match.group("acq"),
        hash6=match.group("hash"),
        position_label=match.group("label"),
        t=int(match.group("t")),
        c=int(match.group("c")),
        z=int(match.group("z")),
    )


# LAS X wraps its ``OriginalMetadata`` elements inside a ``<CustomAttributes>``
# block whose namespace differs from the OME root, so a plain name lookup would
# miss them. The ``{*}`` wildcard (an ElementTree XPath feature) matches the
# element in any namespace, which keeps the lookup robust to LAS X changing its
# namespaces later.
_ORIGINAL_METADATA_XPATH = ".//{*}OriginalMetadata"
_SYSTEM_TYPE_NAME_ATTR = "Data - Image - Attachment - SystemTypeName"
_NATIVE_AUTOSAVE_VENDOR = "lasx_native_autosave"


class NonSimulatorFrameError(RuntimeError):
    """The saved frame's vendor metadata does not identify a simulator.

    Raised when the ``SystemTypeName`` allowlist fails. It is a distinct
    exception type on purpose: the acquisition loop catches ordinary tile
    errors and continues, but a simulator-mismatch must stop the whole run so a
    real-hardware frame is never quietly overwritten.
    """


def _read_system_type(xml_path: Path) -> str | None:
    """Return the ``SystemTypeName`` value from a LAS X companion XML, or None.

    Walks every ``OriginalMetadata`` element (across any namespace) and returns
    the value of the one named ``"Data - Image - Attachment - SystemTypeName"``.
    Returns ``None`` when the element is missing, the XML is unparseable, or the
    file cannot be read -- the allowlist treats anything but the exact value
    ``"SIMULATOR"`` (including ``None``) as not-a-simulator.
    """
    try:
        tree = ET.parse(xml_path)
    except (OSError, ET.ParseError):
        return None
    for el in tree.getroot().iterfind(_ORIGINAL_METADATA_XPATH):
        if el.get("Name") == _SYSTEM_TYPE_NAME_ATTR:
            return el.get("Value")
    return None


def _read_native_autosave_system_type(base_dir: Path) -> str | None:
    """Read SystemTypeName from copied native AutoSave vendor metadata.

    The source XLIF the driver copies under
    ``<base_dir>/vendor/lasx_native_autosave`` carries Leica's
    ``SystemTypeName``. Accept it only when the vendor folder yields exactly one
    distinct non-empty value; missing, unreadable, or conflicting metadata fails
    closed as ``None``.
    """
    vendor_dir = base_dir / "vendor" / _NATIVE_AUTOSAVE_VENDOR
    return _read_native_autosave_system_type_paths(vendor_dir.glob("*.xlif"))


def _read_native_autosave_system_type_paths(paths) -> str | None:
    """Read one unambiguous SystemTypeName from explicit XLIF paths."""

    values: set[str] = set()
    for path in sorted(map(Path, paths)):
        try:
            root = ET.parse(path).getroot()
        except (OSError, ET.ParseError):
            continue
        for el in root.iter():
            value = el.get("SystemTypeName")
            if value:
                values.add(value)
    if len(values) == 1:
        return next(iter(values))
    return None


def _assert_simulator_paths(paths, display_name: str) -> None:
    """Fail closed unless the given vendor XLIF files say ``SIMULATOR``."""

    system_type = _read_native_autosave_system_type_paths(paths)
    if system_type != "SIMULATOR":
        raise NonSimulatorFrameError(
            f"refusing to overwrite {display_name}: native AutoSave vendor "
            f"metadata SystemTypeName is {system_type!r}, not 'SIMULATOR'."
        )


def _assert_simulator(base_dir: Path, display_name: str) -> None:
    """Fail closed unless ``base_dir``'s vendor metadata says ``SIMULATOR``.

    The driver persists the vendor XLIF before ``save`` returns, so it is on
    disk by the time this runs. ``base_dir`` is the directory the saved plane
    lives in; a missing, unreadable, or conflicting read fails closed rather
    than allowing an overwrite.
    """
    system_type = _read_native_autosave_system_type(base_dir)
    if system_type != "SIMULATOR":
        raise NonSimulatorFrameError(
            f"refusing to overwrite {display_name}: native AutoSave vendor "
            f"metadata SystemTypeName is {system_type!r}, not 'SIMULATOR'. "
            f"(simulation-mode hijack can only run on the LAS X simulator.)"
        )


def _overwrite_preserving_ome(image_path: Path, naming, provider: Callable) -> None:
    """Overwrite one single-plane saved TIFF's pixels, keeping its OME-XML.

    Reads the saved array and its OME-XML description, asks ``provider`` for
    mock content of the same shape and dtype, writes it with ``ome=False`` (so
    tifffile keeps the original description verbatim instead of regenerating
    it), checks the description survived byte-for-byte and the file still passes
    the driver's OME check, then atomically replaces the file.

    The caller must run the simulator allowlist first -- this function does not
    check it. Raises ``RuntimeError`` on any provider or overwrite failure
    (per-frame; never :class:`NonSimulatorFrameError`).
    """
    image_path = Path(image_path)
    saved = tifffile.imread(image_path)  # closes its own handle
    with tifffile.TiffFile(image_path) as tif:  # explicit -- no leaked handle
        desc = tif.pages[0].description

    # Only single-plane single-channel frames are supported: the mock provider
    # returns a 2-D image, and the downstream cellpose / pixel-to-stage chain is
    # validated for 2-D frames. A multi-plane saved frame is a per-frame failure
    # (RuntimeError), not a safety violation -- the allowlist the caller ran
    # first still aborts a real-hardware frame.
    if saved.ndim != 2:
        raise RuntimeError(
            f"multi-plane simulator hijack unsupported; {image_path.name} has "
            f"shape {saved.shape}. Current overview/target jobs are "
            f"single-plane single-channel; extend _mock_provider.py for >2D content."
        )

    mock = provider(saved.shape, saved.dtype, naming=naming)
    if mock.shape != saved.shape or mock.dtype != saved.dtype:
        raise RuntimeError(
            f"mock shape/dtype mismatch for {image_path.name}: "
            f"got {mock.shape}/{mock.dtype}, expected {saved.shape}/{saved.dtype}"
        )

    # The driver's OME check is lazy-imported so that importing this module (and
    # the workflow package that re-exports the hijack) pulls in no driver code
    # until a simulation hijack actually fires.
    import navigator_expert.acquisition.ome as ome_tiff

    # A same-directory temp file so os.replace is atomic (it is only atomic
    # within one filesystem).
    parent = image_path.parent
    tmp_fd, tmp_name = tempfile.mkstemp(
        suffix=".tmp",
        prefix=image_path.name + ".",
        dir=str(parent),
    )
    os.close(tmp_fd)
    tmp_path = Path(tmp_name)

    try:
        tifffile.imwrite(
            tmp_path,
            mock,
            description=desc,
            ome=False,  # preserve existing OME XML
            photometric="minisblack",
        )
        # The byte-equality check is load-bearing: a silently-regenerated
        # description would still pass check_ome_tiff's schema check but lose the
        # SystemTypeName block the next run's allowlist depends on.
        with tifffile.TiffFile(tmp_path) as tif:
            new_desc = tif.pages[0].description
        if new_desc != desc:
            raise RuntimeError(
                f"hijack would corrupt OME description on {image_path.name} -- aborting"
            )
        chk = ome_tiff.check_ome_tiff(str(tmp_path))
        # check_ome_tiff reports both known schema violations and other read
        # errors (e.g. an unreadable tag 270); treat either as a failure.
        if chk.get("corrupted") or chk.get("error"):
            raise RuntimeError(
                f"hijacked OME-TIFF failed check on {image_path.name}: "
                f"violations={chk.get('violations')} error={chk.get('error')}"
            )

        os.replace(tmp_path, image_path)
        tmp_path = None  # owned by destination now
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except OSError:
                pass


def hijack_records(records: list[dict], provider: Callable) -> int:
    """Simulator-gated pixel hijack over the images the controller returned.

    ``records`` is the list ``run_overview`` / ``acquire_targets`` return. For
    each saved plane in each record (found through the same driver-agnostic
    reader the rest of the workflow uses), this runs the
    ``SystemTypeName == "SIMULATOR"`` allowlist against the frame's vendor
    metadata and, if it passes, overwrites the pixels while preserving the
    OME-XML.

    ``provider`` is a mock-image callable (see ``_mock_provider``; for example
    ``get_provider("skimage_human_mitosis")``).

    Returns the number of planes overwritten. Re-raises
    :class:`NonSimulatorFrameError` on the first non-simulator frame (run-fatal
    -- the allowlist guarantees a real-hardware frame is never overwritten); a
    ``RuntimeError`` from a provider or overwrite failure also propagates.
    """
    count = 0
    for record in records:
        image_paths = record_channel_paths(
            record, context="simulation hijack record", allow_empty=True
        )
        for image_path in image_paths:
            image_path = Path(image_path)
            vendor_metadata = record.get("vendor_metadata") or []
            if vendor_metadata:
                _assert_simulator_paths(vendor_metadata, image_path.name)
            else:
                _assert_simulator(image_path.parent, image_path.name)
            naming = _filename_context(image_path.name)
            _overwrite_preserving_ome(image_path, naming, provider)
            count += 1
    return count
