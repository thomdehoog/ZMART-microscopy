"""Session-level helpers: connect to LAS X, validate scope state.

Top-of-script setup that every cookbook and the calibration script
share. Each helper raises a clear ``RuntimeError`` (or ``ConnectionError``
when applicable) on failure so callers can wrap one ``try`` and exit
with a short message instead of duplicating connect/validate code.
"""

from __future__ import annotations

import logging
from typing import Any

from .. import readers as _readers

_log = logging.getLogger(__name__)


def _profile_api_delay_ms() -> int | None:
    """Return the configured Leica API delay from the active profile."""
    from ..config import profiles

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
