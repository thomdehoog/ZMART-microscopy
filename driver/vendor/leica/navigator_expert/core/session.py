"""Session-level helpers: connect to LAS X, validate scope state.

Top-of-script setup that every cookbook and the calibration script
share. Each helper raises a clear ``RuntimeError`` (or ``ConnectionError``
when applicable) on failure so callers can wrap one ``try`` and exit
with a short message instead of duplicating connect/validate code.
"""

from __future__ import annotations

from typing import Any

from .. import state_readers as _readers


def connect_python_client(client_name: str = "PythonClient") -> Any:
    """Open the LAS X API client and verify it responds to ``ping``.

    The ``LasxApi`` import lives at the call site so the package
    itself stays import-safe offline. Pass a custom ``client_name`` if
    multiple python clients need to coexist.

    Raises ``ConnectionError`` if the connect call returns False, or
    ``RuntimeError`` if the subsequent ping fails.
    """
    # LAS X ships as a workstation-only Python/.NET package, so static
    # analysis on development machines cannot resolve this import.
    from LasxApi import PYLICamApiConnector as _lasx_api  # type: ignore[import-not-found]
    client = _lasx_api.LasxApiClientPyModel
    if not client.Connect(client_name):
        raise ConnectionError("Cannot connect to LAS X. Is it running?")

    if not _readers.ping(client):
        raise RuntimeError("LAS X ping failed.")
    return client


def require_canonical_scan_orientation() -> None:
    """Verify that LAS X exports images in the orientation our math assumes.

    The pixel↔display-frame mapping ``vx = (col − centre) · pixel_size`` (see
    ``experimental.lrp_edits.roi`` module docstring) only holds when the
    saved TIFF and the on-screen scan field share an axis frame. LAS X
    guarantees that under ``EnableImageTransformation = false`` or
    ``ImageTransformation = TOPLEFT``; any other transformation rotates or
    flips the export and silently misnavigates downstream coordinate math.

    *Stage axis settings* (``FlipX``, ``FlipY``, ``SwapXY``,
    ``InvertXMovement``, ``InvertYMovement``) are NOT validated here: their
    effect is folded into the calibrated ``image_to_stage`` matrix (the
    calibration is measured end-to-end), so changing them would invalidate
    the calibration but does not invalidate this function's derivation. A
    future check could compare the live values to those captured at
    calibration time — that's a separate guarantee from "LAS X exports a
    canonical TIFF".

    Raises ``RuntimeError`` if image export is not in TOPLEFT.
    """
    settings = _readers.get_lasx_settings() or {}
    orient = settings.get("image_orientation", {}) or {}
    if (orient.get("enable_transform", False)
            and orient.get("transformation", "TOPLEFT") != "TOPLEFT"):
        raise RuntimeError(
            f"ImageTransformation = '{orient.get('transformation')}' "
            f"(expected 'TOPLEFT' or EnableImageTransformation = false). "
            f"Pixel↔display-frame math will silently misnavigate. "
            f"Fix in LAS X Advanced Settings, then retry."
        )
