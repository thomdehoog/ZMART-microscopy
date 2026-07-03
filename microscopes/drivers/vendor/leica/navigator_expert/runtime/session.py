"""Session-level helpers: connect to LAS X, validate scope state.

Top-of-script setup that every cookbook and the calibration script
share. Each helper raises a clear ``RuntimeError`` (or ``ConnectionError``
when applicable) on failure so callers can wrap one ``try`` and exit
with a short message instead of duplicating connect/validate code.
"""

from __future__ import annotations

import logging
from typing import Any

from .. import state_readers as _readers

_log = logging.getLogger(__name__)


def _profile_api_delay_ms() -> int | None:
    """Return the configured Leica API delay from the active profile."""
    from . import profiles

    return profiles.LASX_API.delay_ms


def configure_lasx_api_delay(lasx_api_module: Any, delay_ms: int | None = None) -> int | None:
    """Set Leica's ``PyApiClient.DelayInMilliseconds`` pacing knob.

    ``delay_ms=None`` means "use the current profile value." A profile value
    of ``None`` disables explicit configuration.

    Returns the applied value, or ``None`` when disabled.
    """
    if delay_ms is None:
        delay_ms = _profile_api_delay_ms()
    if delay_ms is None:
        return None

    pyapi_client = getattr(lasx_api_module, "PyApiClient", None)
    if pyapi_client is None:
        client_model = getattr(lasx_api_module, "LasxApiClientPyModel", None)
        pyapi_client = getattr(client_model, "PyApiClient", None)
    if pyapi_client is None:
        raise RuntimeError(
            "LasxApi.PyApiClient is unavailable; cannot configure DelayInMilliseconds"
        )

    try:
        pyapi_client.DelayInMilliseconds = int(delay_ms)
    except Exception as exc:  # noqa: BLE001 - .NET interop exceptions vary
        raise RuntimeError("Could not set LasxApi.PyApiClient.DelayInMilliseconds") from exc
    return int(delay_ms)


def connect_python_client(
    client_name: str = "PythonClient", api_delay_ms: int | None = None
) -> Any:
    """Open the LAS X API client and verify it responds to ``ping``.

    The runtime loader is imported at the call site so this module
    stays import-safe on machines without LAS X. Pass a custom ``client_name`` if
    multiple python clients need to coexist. ``api_delay_ms`` overrides the
    profile's ``LASX_API.delay_ms`` for this connection attempt.

    Raises ``ConnectionError`` if the connect call returns False, or
    ``RuntimeError`` if the subsequent ping fails.
    """
    from .lasx_runtime import load_lasx_api_runtime

    _lasx_api = load_lasx_api_runtime()
    client = _lasx_api.LasxApiClientPyModel
    if not client.Connect(client_name):
        raise ConnectionError("Cannot connect to LAS X. Is it running?")
    applied_delay = configure_lasx_api_delay(_lasx_api, api_delay_ms)
    _log.info(
        "LAS X runtime=%s version=%s api_delay_ms=%s",
        getattr(_lasx_api, "base_path", "unknown"),
        getattr(_lasx_api, "__version__", "unknown"),
        "profile-disabled" if applied_delay is None else applied_delay,
    )

    if not _readers.ping(client):
        raise RuntimeError("LAS X ping failed.")
    return client


def require_canonical_scan_orientation() -> None:
    """Verify that LAS X exports images in the orientation our math assumes.

    The pixel↔display-frame mapping ``vx = (col − centre) · pixel_size`` (see
    ``experimental.lrp_edits.pan`` module docstring) only holds when the
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

    Raises ``RuntimeError`` if image export is not in TOPLEFT, or if the
    orientation settings cannot be read (fail closed — an unverifiable
    orientation is not a safe one).
    """
    settings = _readers.get_lasx_settings()
    if settings is None or "image_orientation" not in settings:
        raise RuntimeError(
            "Could not read LAS X image-orientation settings; cannot confirm "
            "the export is in TOPLEFT. Check the LAS X settings path, then retry."
        )
    orient = settings.get("image_orientation") or {}
    if orient.get("enable_transform", False) and orient.get("transformation", "TOPLEFT") != "TOPLEFT":
        raise RuntimeError(
            f"ImageTransformation = '{orient.get('transformation')}' "
            f"(expected 'TOPLEFT' or EnableImageTransformation = false). "
            f"Pixel↔display-frame math will silently misnavigate. "
            f"Fix in LAS X Advanced Settings, then retry."
        )
