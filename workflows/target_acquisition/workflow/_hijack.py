"""Per-frame simulation-mode pixel hijack.

After ``acquire`` saves a canonical ``.ome.tiff``, the sim caller overwrites
that file's pixels with mock content so the workflow/analysis runs the real
code path on realistic-looking data. Two entry points share one recipe:

- :func:`hijack_records` -- the controller-only flow's entry: takes the records
  ``run_overview`` / ``acquire_targets`` return (each with ``"images"`` paths)
  and derives everything from the paths. This is what the v4 notebook calls.
- :func:`hijack_frame` -- the retired driver-coupled entry (``result`` +
  ``layout`` + ``kind``), kept for ``pipeline.retired``.

The flat, no-sidecar layout dropped the companion ``.ome.xml``; the overwrite
is gated by a per-frame allowlist on the copied native AutoSave vendor
metadata's ``SystemTypeName`` -- the XLIF the driver copies under
``<acquisition_dir>/vendor/lasx_native_autosave``, which is the frame's own
ground-truth metadata.

Safety properties:

- The allowlist is a **positive** one: overwrite only when
  ``SystemTypeName`` is exactly ``"SIMULATOR"``. Any other value, a
  missing/conflicting element, or unreadable vendor metadata raises
  ``NonSimulatorFrameError`` -- never let an unexpected/missing value
  pass through onto a real frame.
- ``NonSimulatorFrameError`` is a dedicated exception type, **not** a
  generic ``Exception``: the acquisition loop in ``run_overview``
  wraps tile work in a broad ``except Exception`` that records a tile
  failure and continues. A simulator-mismatch must hard-abort the run
  instead -- the loop re-raises ``NonSimulatorFrameError`` explicitly
  ahead of its broad catch.
- The check-and-overwrite are one indivisible operation. There is **no
  exported standalone overwrite function** -- ``hijack_frame`` is the
  only entry point. Anyone overwriting must do so via the check.

OME-rewrite recipe:

1. Read the saved canonical TIFF and the embedded OME-XML description
   (TIFF tag 270) via the public ``tifffile`` API, in a ``with`` block
   (a bare ``TiffFile(...)`` would leak a file handle and break the
   later ``os.replace`` on Windows).
2. Run the provider to produce a mock image matching the saved
   array's exact shape and dtype.
3. Write the mock to a temp file **in the same directory** as the
   target (so step 5's ``os.replace`` is atomic) with
   ``ome=False`` and ``description=<tag-270 bytes>``. ``ome=False`` is
   essential: ``tifffile.imwrite`` auto-enables OME mode on a
   ``.ome.``-named file and *regenerates* the OME-XML, overriding the
   ``description=``. ``ome=False`` writes the description verbatim,
   preserving the ``OriginalMetadata``/``SystemTypeName`` block the
   guard depends on.
4. Re-read the temp file's tag 270 and assert byte-equality with the
   original. (``check_ome_tiff`` alone only catches known schema
   violations -- a silently-regenerated description would pass it.)
   Then ``check_ome_tiff`` for the schema check.
5. Atomically ``os.replace`` the target with the temp file.

The recipe is validated for the workflow's normal single-plane saved
files. A multi-plane saved frame is rejected explicitly in
``hijack_frame`` (RuntimeError -- per-tile, not run-fatal) so the
loop records it and continues rather than producing 100 silent
shape-mismatch hijack failures. Extending to multi-plane support is
a `pipeline/_mock_provider.py` change, not a guard change.
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

# Descendant-XPath for ``OriginalMetadata`` across any namespace. LAS X
# actually places these elements inside a ``<CustomAttributes>`` block
# carrying the CA-2008-09 default namespace, which is DIFFERENT from
# the OME root namespace -- a naive ``root.iter("OriginalMetadata")``
# misses them entirely. The ``{*}`` namespace wildcard (Python 3.8+
# findall/iterfind XPath syntax; NOT supported by ``iter``) matches
# the local name in any namespace, including none. This makes the
# lookup robust to any future LAS X namespace drift.
_ORIGINAL_METADATA_XPATH = ".//{*}OriginalMetadata"
_SYSTEM_TYPE_NAME_ATTR = "Data - Image - Attachment - SystemTypeName"
_NATIVE_AUTOSAVE_VENDOR = "lasx_native_autosave"


class NonSimulatorFrameError(RuntimeError):
    """The saved frame's native AutoSave vendor metadata does not identify
    a simulator.

    Raised by ``hijack_frame`` when the per-frame allowlist fails. The
    acquisition loop must re-raise this explicitly (ahead of its broad
    ``except Exception``) so the run hard-aborts -- a real-hardware
    frame must never be silently logged as a tile failure and the
    loop continued.
    """


def _read_system_type(xml_path: Path) -> str | None:
    """Extract ``SystemTypeName`` from a LAS X-exported companion XML.

    Walks every ``<OriginalMetadata>`` element (across any namespace,
    via ET's ``{*}`` wildcard -- LAS X wraps them in a CustomAttributes
    block under a separate namespace) and returns the ``Value``
    attribute of the one whose ``Name`` is exactly
    ``"Data - Image - Attachment - SystemTypeName"``.

    Returns ``None`` if the element is missing, the XML is unparseable,
    or the file is unreadable. The allowlist treats anything but the
    exact value ``"SIMULATOR"`` (including ``None``) as
    not-a-simulator.

    This replaces an earlier regex implementation; the regex was
    attribute-order-dependent and unaware of namespaces, which made it
    fragile against perfectly-valid LAS X output variations. The ET
    walk is order-independent, namespace-aware, and pinned in
    ``test_hijack.py`` against a real (sanitized) LAS X simulator XML.
    """
    try:
        tree = ET.parse(xml_path)
    except (OSError, ET.ParseError):
        return None
    # ``iter`` does NOT honour the ``{*}`` namespace wildcard, only
    # ``findall``/``iterfind`` do. Using the descendant-or-self XPath
    # form so the OME root namespace and the CustomAttributes CA
    # namespace are both swept.
    for el in tree.getroot().iterfind(_ORIGINAL_METADATA_XPATH):
        if el.get("Name") == _SYSTEM_TYPE_NAME_ATTR:
            return el.get("Value")
    return None


def _read_native_autosave_system_type(base_dir: Path) -> str | None:
    """Read SystemTypeName from copied native AutoSave vendor metadata.

    The flat layout embeds canonical state per-plane and does not carry
    Leica's ``OriginalMetadata`` block. The source XLIF copied under
    ``<base_dir>/vendor/lasx_native_autosave`` (``base_dir`` is the flat
    ``acquisition_dir(kind)``) does carry Leica's ``SystemTypeName``
    attribute. Accept it only when the vendor folder yields exactly one
    distinct non-empty value; missing, unreadable, or conflicting metadata
    fails closed as ``None``.
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


def _assert_simulator(base_dir: Path, display_name: str) -> None:
    """Fail closed unless ``base_dir``'s vendor metadata says ``SIMULATOR``.

    The flat, no-sidecar layout dropped the companion ``.ome.xml``; the
    driver copies the source LAS X XLIF under
    ``<base_dir>/vendor/lasx_native_autosave`` (see
    driver/acquisition/save.py::_persist_vendor_metadata), which is the sole
    ground-truth for the frame's ``SystemTypeName``. ``base_dir`` is the flat
    ``acquisition_dir`` -- i.e. the directory the saved plane lives in.

    Timing: this read is synchronous with respect to save -- the driver
    persists the vendor metadata before ``save`` returns, so the XLIF is on
    disk by the time we get here. A missing/unreadable/conflicting read fails
    closed (``None`` -> not-a-simulator), never a silent overwrite.
    """
    system_type = _read_native_autosave_system_type(base_dir)
    if system_type != "SIMULATOR":
        raise NonSimulatorFrameError(
            f"refusing to overwrite {display_name}: native AutoSave vendor "
            f"metadata SystemTypeName is {system_type!r}, not 'SIMULATOR'. "
            f"(simulation-mode hijack can only run on the LAS X simulator.)"
        )


def _assert_simulator_paths(paths, display_name: str) -> None:
    """Fail closed against the exact vendor files returned by the driver."""

    system_type = _read_native_autosave_system_type_paths(paths)
    if system_type != "SIMULATOR":
        raise NonSimulatorFrameError(
            f"refusing to overwrite {display_name}: native AutoSave vendor "
            f"metadata SystemTypeName is {system_type!r}, not 'SIMULATOR'."
        )


def _overwrite_preserving_ome(image_path: Path, naming, provider: Callable) -> None:
    """OME-preserving pixel overwrite of one single-plane saved TIFF.

    Reads the saved array + its tag-270 OME-XML, asks ``provider`` for mock
    content of the same shape/dtype, writes it with ``ome=False`` (so the
    original description survives verbatim), asserts byte-equality of the
    description and the driver's OME check, then atomically replaces the file.

    The caller MUST run the simulator allowlist (:func:`_assert_simulator`)
    first -- this function does not check it.

    Raises ``RuntimeError`` on any provider/overwrite/validate failure
    (per-frame; never ``NonSimulatorFrameError``).
    """
    image_path = Path(image_path)
    saved = tifffile.imread(image_path)  # closes its own handle
    with tifffile.TiffFile(image_path) as tif:  # explicit -- no leak
        desc = tif.pages[0].description

    # 2D-only scope guard. The provider returns a 2-D image; downstream
    # cellpose / pixel-to-stage chains have been validated for 2-D frames
    # only (single-plane, single-channel). A multi-plane saved frame is a
    # per-frame failure (RuntimeError), NOT a NonSimulatorFrame (which would
    # hard-abort the run). The allowlist the caller runs FIRST still aborts a
    # real-hardware multi-plane frame as it should.
    if saved.ndim != 2:
        raise RuntimeError(
            f"multi-plane simulator hijack unsupported; {image_path.name} has "
            f"shape {saved.shape}. Current overview/target jobs are "
            f"single-plane single-channel; extend pipeline/_mock_provider.py "
            f"for >2D content."
        )

    mock = provider(saved.shape, saved.dtype, naming=naming)
    if mock.shape != saved.shape or mock.dtype != saved.dtype:
        raise RuntimeError(
            f"mock shape/dtype mismatch for {image_path.name}: "
            f"got {mock.shape}/{mock.dtype}, expected {saved.shape}/{saved.dtype}"
        )

    # Driver's OME check, lazy-imported so importing this module (and the
    # controller-only pipeline that re-exports the hijack) pulls in no driver
    # code until a simulation hijack actually fires.
    import navigator_expert.acquisition.ome as ome_tiff

    # Same-directory temp so os.replace is atomic (only atomic within one
    # filesystem).
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
        # Tag-270 byte-equality is the load-bearing assertion: a silently-
        # regenerated description would still pass check_ome_tiff's schema
        # check but lose SystemTypeName.
        with tifffile.TiffFile(tmp_path) as tif:
            new_desc = tif.pages[0].description
        if new_desc != desc:
            raise RuntimeError(
                f"hijack would corrupt OME description on {image_path.name} -- aborting"
            )
        chk = ome_tiff.check_ome_tiff(str(tmp_path))
        # check_ome_tiff returns {corrupted: bool, error: str|None, ...} -- the
        # driver convention treats `error` (e.g. unreadable tag 270, encoding
        # error) as a check failure distinct from a known schema violation.
        # Honour both.
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


def hijack_frame(
    result,
    *,
    kind: str,
    layout,
    provider: Callable,
) -> None:
    """Simulator allowlist + OME-preserving overwrite, indivisible (retired path).

    Retired driver-coupled entry point (``pipeline.retired.overview`` /
    ``target``): takes a workflow-selected single-plane ``result`` (with
    ``image_path`` / ``naming``) and the run ``layout``, locating the vendor
    metadata under ``layout.acquisition_dir(kind)/vendor/lasx_native_autosave``.
    The controller-only flow uses :func:`hijack_records` instead.

    Raises ``NonSimulatorFrameError`` (allowlist failure -- run-fatal) or
    ``RuntimeError`` (provider/overwrite/validate failure -- per-frame).
    """
    _assert_simulator(layout.acquisition_dir(kind), result.image_path.name)
    _overwrite_preserving_ome(result.image_path, result.naming, provider)


def hijack_records(records: list[dict], provider: Callable) -> int:
    """Simulator-gated pixel hijack over the images the controller returned.

    Controller-only entry point. ``records`` is the list
    ``run_overview`` / ``acquire_targets`` returns; each record's ``"images"``
    is a list of saved single-plane ``.ome.tiff`` paths. For every plane:

    1. Derive the flat acquisition dir as the file's own parent, and run the
       positive ``SystemTypeName == "SIMULATOR"`` allowlist against the vendor
       metadata there (:func:`_assert_simulator`).
    2. Read the provider context from the canonical filename.
    3. Overwrite the pixels, preserving the OME-XML (:func:`_overwrite_preserving_ome`).

    ``provider`` is a mock-image callable (see ``pipeline._mock_provider``;
    e.g. ``get_provider("skimage_human_mitosis")``).

    Returns the number of planes overwritten. Re-raises
    ``NonSimulatorFrameError`` on the first non-simulator frame (run-fatal --
    the allowlist guarantees a real-hardware frame is never overwritten).
    ``RuntimeError`` from a provider/overwrite failure also propagates.
    """
    count = 0
    for record in records:
        for image_path in record.get("images", []):
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
