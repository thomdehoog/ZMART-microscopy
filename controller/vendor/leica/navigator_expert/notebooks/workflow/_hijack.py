"""Per-frame simulation-mode pixel hijack (Plan 2 §2 + §4c).

After ``acquire_and_save`` returns a canonical ``.ome.tiff``, the
workflow calls ``hijack_frame(...)`` to overwrite that file's pixels
with mock content. The overwrite is gated by a per-frame allowlist on
the saved companion ``.ome.xml``'s ``SystemTypeName`` -- read from the
**very file pair about to be overwritten**, using that file pair's
own ground-truth metadata.

Safety properties (Plan 2 §2):

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

OME-rewrite recipe (Plan 2 §4c):

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
files. Multi-page or multi-series OME-TIFFs would need the
tag-preservation test extended (Plan 2 §4c scope).
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Callable

import tifffile

import navigator_expert.driver.ome_tiff as ome_tiff

from _shared.output_layout import build_xml_name


class NonSimulatorFrameError(RuntimeError):
    """The saved frame's companion XML does not identify a simulator.

    Raised by ``hijack_frame`` when the per-frame allowlist fails. The
    acquisition loop must re-raise this explicitly (ahead of its broad
    ``except Exception``) so the run hard-aborts -- a real-hardware
    frame must never be silently logged as a tile failure and the
    loop continued.
    """


# OriginalMetadata element carrying the system type, embedded by LAS X
# into the companion .ome.xml for every acquisition. Verified across
# ~30 simulator XMLs / overview and target jobs / positions 0-15
# (Plan 2 §1-C). On the simulator the Value is "SIMULATOR"; on a real
# STELLARIS it is e.g. "STELLARIS 8".
_SYS_TYPE_RE = re.compile(
    r'<OriginalMetadata[^>]*Name="Data - Image - Attachment - '
    r'SystemTypeName"[^>]*Value="([^"]*)"',
)


def _read_system_type(xml_path: Path) -> str | None:
    """Extract ``SystemTypeName`` from a LAS X-exported companion XML.

    Returns the string value, or ``None`` if the element is missing or
    the file is unreadable. The §2 allowlist treats anything but the
    exact value ``"SIMULATOR"`` (including ``None``) as not-a-simulator.
    """
    try:
        text = xml_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = _SYS_TYPE_RE.search(text)
    return m.group(1) if m else None


def hijack_frame(
    result,
    *,
    kind: str,
    layout,
    provider: Callable,
) -> None:
    """§2 allowlist + §4c overwrite, indivisible.

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
        Mock-image callable; see ``workflow._mockprovider``. Signature:
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
    # ── §2: per-frame allowlist on the companion XML ──────────────────
    # Derive the companion XML path from the *canonical* naming -- do
    # NOT use the driver's _find_companion_xml (that resolves LAS X
    # source filenames, not canonical workflow names).
    xml_path = layout.metadata_dir(kind) / build_xml_name(result.naming)
    system_type = _read_system_type(xml_path)
    if system_type != "SIMULATOR":
        raise NonSimulatorFrameError(
            f"refusing to overwrite {result.image_path.name}: "
            f"companion XML SystemTypeName is {system_type!r}, not "
            f"'SIMULATOR'. (cfg.simulate=True can only run on the "
            f"LAS X simulator.)"
        )

    # ── §4c: OME-preserving pixel overwrite ──────────────────────────
    saved = tifffile.imread(result.image_path)        # closes its own handle
    with tifffile.TiffFile(result.image_path) as tif:  # explicit -- no leak
        desc = tif.pages[0].description

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
            ome=False,                       # essential -- see §4c
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
        if chk.get("corrupted"):
            raise RuntimeError(
                f"hijacked OME-TIFF failed check on "
                f"{result.image_path.name}: {chk.get('violations')}"
            )
        # Companion XML is untouched by a pixel rewrite -- validate
        # for completeness.
        chk_xml = ome_tiff.check_ome_xml_file(str(xml_path))
        if chk_xml.get("corrupted"):
            raise RuntimeError(
                f"companion XML failed check on "
                f"{xml_path.name}: {chk_xml.get('violations')}"
            )

        os.replace(tmp_path, result.image_path)
        tmp_path = None                      # owned by destination now
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except OSError:
                pass
