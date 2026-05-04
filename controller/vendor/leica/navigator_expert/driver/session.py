"""Session-level helpers: connect to LAS X, validate scope state.

Top-of-script setup that every cookbook and the calibration script
share. Each helper raises a clear ``RuntimeError`` (or ``ConnectionError``
when applicable) on failure so callers can wrap one ``try`` and exit
with a short message instead of duplicating connect/validate code.
"""

from __future__ import annotations

from typing import Any

from . import readers as _readers


def connect_python_client(client_name: str = "PythonClient") -> Any:
    """Open the LAS X API client and verify it responds to ``ping``.

    The ``LasxApi`` import lives at the call site so the package
    itself stays import-safe offline. Pass a custom ``client_name`` if
    multiple python clients need to coexist.

    Raises ``ConnectionError`` if the connect call returns False, or
    ``RuntimeError`` if the subsequent ping fails.
    """
    from LasxApi import PYLICamApiConnector as _lasx_api  # type: ignore
    client = _lasx_api.LasxApiClientPyModel
    if not client.Connect(client_name):
        raise ConnectionError("Cannot connect to LAS X. Is it running?")

    if not _readers.ping(client):
        raise RuntimeError("LAS X ping failed.")
    return client


def require_topleft_orientation() -> None:
    """Verify that LAS X image export uses the TOPLEFT origin.

    Pixel-to-stage math (sign-convention matrix, ``pixel_to_stage_xy_um``)
    is calibrated under TOPLEFT. With any other transformation enabled
    the image axes are flipped or rotated and downstream coordinate
    math silently lands at the wrong place.

    Raises ``RuntimeError`` if a non-TOPLEFT transformation is enabled.
    """
    settings = _readers.get_lasx_settings() or {}
    orient = settings.get("image_orientation", {}) or {}
    if (orient.get("enable_transform", False)
            and orient.get("transformation", "TOPLEFT") != "TOPLEFT"):
        raise RuntimeError(
            f"ImageTransformation is '{orient.get('transformation')}'; "
            f"set it to TOPLEFT in LAS X Advanced Settings."
        )
