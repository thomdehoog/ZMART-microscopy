"""Per-frame simulation-mode pixel hijack.

After ``acquire_and_save`` returns a canonical ``.ome.tiff``, the
workflow calls ``hijack_frame(...)`` to overwrite that file's pixels
with mock content. The overwrite is gated by a per-frame allowlist on
the saved companion ``.ome.xml``'s ``SystemTypeName`` -- read from the
**very file pair about to be overwritten**, using that file pair's
own ground-truth metadata.

Safety properties:

- The allowlist is a **positive** one: overwrite only when
  ``SystemTypeName`` is exactly ``"SIMULATOR"``. Any other value, a
  missing element, or an unreadable XML raises
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
   Then ``check_ome_tiff`` for the schema check and
   ``check_ome_xml_file`` for the companion.
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
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable

import tifffile

import navigator_expert.acquisition.ome as ome_tiff

from shared.output_layout import build_xml_name


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


class NonSimulatorFrameError(RuntimeError):
    """The saved frame's companion XML does not identify a simulator.

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


def hijack_frame(
    result,
    *,
    kind: str,
    layout,
    provider: Callable,
) -> None:
    """Simulator allowlist + OME-preserving overwrite, indivisible.

    Parameters
    ----------
    result
        ``SavedAcquisition`` from ``drv.acquire_and_save`` (carries
        ``image_path`` and ``naming``).
    kind
        The acquisition kind -- ``"overview-scan"`` or
        ``"target-acquisition"``. Used to locate the companion XML
        under ``layout.metadata_dir(kind)``.
    layout
        ``ctx.run.layout`` -- ``LayoutPlan`` for the run.
    provider
        Mock-image callable; see ``pipeline._mock_provider``. Signature:
        ``provider(shape, dtype, *, naming) -> ndarray``.

    Raises
    ------
    NonSimulatorFrameError
        Allowlist failure: the companion XML's ``SystemTypeName`` is
        not exactly ``"SIMULATOR"``, the element is missing, or the
        XML is unreadable. **Run-fatal** -- caller must let it
        propagate.
    RuntimeError
        Provider / overwrite / validate failure (e.g. shape mismatch,
        OME description not preserved, atomic-replace failure).
        Per-tile -- caller records it in ``hijack_failures`` and
        continues.
    """
    # Per-frame allowlist on the companion XML.
    # Derive the companion XML path from the *canonical* naming -- do
    # NOT use the driver's _find_companion_xml (that resolves LAS X
    # source filenames, not canonical pipeline names).
    #
    # Timing: this call is synchronous with respect to acquire_and_save
    # -- driver/acquisition/save.py calls _save_atomic(image, xml) which
    # copies both to .tmp + size-validates + os.replaces both before
    # acquire_and_save returns at line 190. By the time we get here the
    # canonical-named XML is on disk. No retry
    # needed; a missing-file read here would be a genuine bug, not a
    # race.
    xml_path = layout.metadata_dir(kind) / build_xml_name(result.naming)
    system_type = _read_system_type(xml_path)
    if system_type != "SIMULATOR":
        raise NonSimulatorFrameError(
            f"refusing to overwrite {result.image_path.name}: "
            f"companion XML SystemTypeName is {system_type!r}, not "
            f"'SIMULATOR'. (cfg.simulate=True can only run on the "
            f"LAS X simulator.)"
        )

    # OME-preserving pixel overwrite.
    saved = tifffile.imread(result.image_path)        # closes its own handle
    with tifffile.TiffFile(result.image_path) as tif:  # explicit -- no leak
        desc = tif.pages[0].description

    # 2D-only scope guard. The provider returns a 2-D image; downstream
    # cellpose / pixel-to-stage chains have been validated for 2-D
    # frames only (single-plane, single-channel). A multi-plane saved
    # frame is a per-tile failure (RuntimeError -- recorded in
    # hijack_failures and the loop continues), NOT a NonSimulatorFrame
    # (which would hard-abort the run). The allowlist above runs FIRST
    # so a real-hardware multi-plane frame still aborts on the
    # allowlist as it should.
    if saved.ndim != 2:
        raise RuntimeError(
            f"multi-plane simulator hijack unsupported; "
            f"{result.image_path.name} has shape {saved.shape}. Current "
            f"overview/target jobs are single-plane single-channel; extend "
            f"pipeline/_mock_provider.py for >2D content."
        )

    mock = provider(saved.shape, saved.dtype, naming=result.naming)
    if mock.shape != saved.shape or mock.dtype != saved.dtype:
        raise RuntimeError(
            f"mock shape/dtype mismatch for {result.image_path.name}: "
            f"got {mock.shape}/{mock.dtype}, expected "
            f"{saved.shape}/{saved.dtype}"
        )

    # Same-directory temp so os.replace is atomic (only atomic within
    # one filesystem).
    parent = Path(result.image_path).parent
    tmp_fd, tmp_name = tempfile.mkstemp(
        suffix=".tmp",
        prefix=Path(result.image_path).name + ".",
        dir=str(parent),
    )
    os.close(tmp_fd)
    tmp_path = Path(tmp_name)

    try:
        tifffile.imwrite(
            tmp_path, mock,
            description=desc,
            ome=False,                       # preserve existing OME XML
            photometric="minisblack",
        )
        # Tag-270 byte-equality is the load-bearing assertion: a
        # silently-regenerated description would still pass
        # check_ome_tiff's schema check but lose SystemTypeName.
        with tifffile.TiffFile(tmp_path) as tif:
            new_desc = tif.pages[0].description
        if new_desc != desc:
            raise RuntimeError(
                f"hijack would corrupt OME description on "
                f"{result.image_path.name} -- aborting"
            )
        chk = ome_tiff.check_ome_tiff(str(tmp_path))
        # check_ome_tiff returns {corrupted: bool, error: str|None, ...}
        # -- the driver convention treats `error` (e.g. unreadable tag
        # 270, encoding error) as a check failure distinct from a known
        # schema violation. Honour both.
        if chk.get("corrupted") or chk.get("error"):
            raise RuntimeError(
                f"hijacked OME-TIFF failed check on "
                f"{result.image_path.name}: "
                f"violations={chk.get('violations')} error={chk.get('error')}"
            )
        # Companion XML is untouched by a pixel rewrite -- validate
        # for completeness. Same {corrupted|error} contract.
        chk_xml = ome_tiff.check_ome_xml_file(str(xml_path))
        if chk_xml.get("corrupted") or chk_xml.get("error"):
            raise RuntimeError(
                f"companion XML failed check on "
                f"{xml_path.name}: "
                f"violations={chk_xml.get('violations')} "
                f"error={chk_xml.get('error')}"
            )

        os.replace(tmp_path, result.image_path)
        tmp_path = None                      # owned by destination now
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except OSError:
                pass
