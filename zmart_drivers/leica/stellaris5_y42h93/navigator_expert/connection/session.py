"""Session-level helpers: connect to LAS X, validate scope state.

Top-of-script setup that every cookbook and the calibration script
share. Each helper raises a clear ``RuntimeError`` (or ``ConnectionError``
when applicable) on failure so callers can wrap one ``try`` and exit
with a short message instead of duplicating connect/validate code.
"""

from __future__ import annotations

import json
import logging
import os
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


def _load_objective_calibration(
    calibration_name: str | None = None,
    *,
    enabled: bool = True,
) -> tuple[dict | None, dict]:
    """Load translations and readiness provenance from one exact document.

    Resolving/loading twice can straddle an atomic snapshot adoption: old
    translations could otherwise be paired with new ``measured_slots`` and be
    reported ready. This function deliberately resolves one path, parses it
    once, and derives both outputs from that immutable in-memory config.
    """
    # This import must stay inside the function: the package root imports this
    # module when the driver loads, and the calibration modules import the
    # package root — a module-level import here would be a circular import.
    from ..config.machine import CALIBRATION_NAME_ENV

    effective_name = calibration_name or os.environ.get(CALIBRATION_NAME_ENV)
    empty_info = {
        "enabled": enabled,
        "loaded": False,
        "name": effective_name,
        "path": None,
        "slots": [],
        "measured_slots": [],
    }
    if not enabled:
        return None, empty_info

    from ..calibration.core import model as _cal_model

    path = None
    try:
        path = _cal_model.default_path(calibration_name).absolute()
        config = _cal_model.load_calibration(path)
        translations = {
            int(slot): _cal_model.get_translation_um(config, int(slot))
            for slot, entry in (config.get("objectives") or {}).items()
            if entry.get("translation_um") is not None
        }
    except Exception as exc:  # noqa: BLE001 -- config IO / schema; degrade, don't crash connect
        _log.warning(
            "objective translations unavailable (%s); cross-objective moves will be refused",
            exc,
        )
        empty_info["path"] = None if path is None else str(path)
        return None, empty_info

    info = {
        "enabled": True,
        "loaded": True,
        "name": effective_name,
        "path": str(path),
        "slots": sorted(translations),
        "measured_slots": sorted(
            int(slot)
            for slot, entry in (config.get("objectives") or {}).items()
            if entry.get("session_id")
        ),
    }
    return translations, info


def _load_rig_orientation(*, enabled: bool = True) -> tuple[Any, dict]:
    """Load orientation and readiness evidence from one exact document.

    A single resolve/read supplies both the orientation used for images and the
    provenance used by preflight, so snapshot adoption cannot mix old geometry
    with new readiness evidence. Invalid or disabled configuration returns the
    identity mapping with an explicit not-ready record.
    """
    from .. import orientation as _orientation
    from ..config.machine import MACHINE

    identity = _orientation.Orientation()
    if not enabled:
        return identity, {
            "enabled": False,
            "loaded": False,
            "measured": False,
            "path": None,
            "rotate_deg": int(identity.rotate_deg),
            "mirrored": identity.mirrored,
        }

    path = None
    try:
        path = MACHINE.orientation_path().absolute()
        data = json.loads(path.read_text(encoding="utf-8"))
        # Match orientation.load_orientation's validation without reading the
        # file a second time: readiness evidence and runtime geometry must come
        # from this same in-memory document.
        orientation = _orientation.orientation_from_config(data)
    except Exception as exc:  # noqa: BLE001 -- config IO / schema; degrade, don't crash connect
        _log.warning(
            "orientation unavailable (%s); saved images will NOT be corrected to the "
            "stage axes this session. Re-publish orientation.json with "
            "orientation/notebooks/set_orientation.ipynb and reconnect.",
            exc,
        )
        return identity, {
            "enabled": True,
            "loaded": False,
            "measured": False,
            "path": None if path is None else str(path),
            "rotate_deg": int(identity.rotate_deg),
            "mirrored": identity.mirrored,
            "error": str(exc),
        }
    return orientation, {
        "enabled": True,
        "loaded": True,
        # A real measured 0-degree orientation is valid. The explicit marker,
        # not the angle, distinguishes it from the shipped identity placeholder.
        "measured": data.get("measured") is True,
        "path": str(path),
        "rotate_deg": int(orientation.rotate_deg),
        "mirrored": orientation.mirrored,
        "axis_signs": orientation.axis_signs,
        "axis_mapping": orientation.axis_mapping,
        "image_to_stage": [list(row) for row in orientation.image_to_stage],
    }


def connect_microscope(
    *,
    client_name: str = "PythonClient",
    api_delay_ms: int | None = None,
    load_limits: bool = True,
    load_orientation: bool = True,
    load_calibration: bool = True,
    calibration_name: str | None = None,
) -> Any:
    """Connect to the microscope and load its machine-local configuration.

    Every connect attempt first creates the microscope's ProgramData API root
    and four subsystem directories if they do not exist yet. This is independent
    of the per-file load switches below.

    This is the driver's own front door for a normal session. It opens the CAM
    client (:func:`connect_python_client`) and then loads the three files this
    microscope keeps next to each other in its machine snapshot — its **stage
    limits**, its **camera-to-stage orientation**, and its **per-objective
    calibration** — so the rest of the driver works from one consistent picture
    of the instrument for the whole session.

    Each config can be skipped independently, which is what the
    ``load_limits`` / ``load_orientation`` / ``load_calibration`` switches are
    for. Skipping one is a deliberate choice with a defined, safe meaning:

    - ``load_limits=False`` — the session is governed by the bundled **default**
      limits rather than this machine's measured envelope. It is never left
      ungated, and the hardcoded physical backstop still bounds every move.
    - ``load_orientation=False`` — saved images are left exactly as the camera
      produced them (no turn or mirror correction to stage axes).
    - ``load_calibration=False`` — no objective translations are loaded, so the
      driver refuses cross-objective moves rather than computing uncompensated
      ones.

    A file that fails to load degrades the same way, loudly, instead of failing
    the connection: an invalid ``limits.json`` falls back to the bundled default
    envelope, an unreadable ``orientation.json`` falls back to the identity turn,
    and an unreadable ``calibration.json`` leaves translations unloaded. Only an
    unreachable LAS X (or a failed ping) raises.

    Returns the CAM client. The loaded limits live in the commands gate; the
    loaded orientation and calibration live in the per-connection session
    registry (:mod:`.session_state`), where the acquire/save path reads them.
    """
    from ..commands import gate as _gate
    from ..config.machine import MACHINE
    from . import session_state

    MACHINE.ensure_layout()
    client = connect_python_client(client_name=client_name, api_delay_ms=api_delay_ms)
    _gate.connect_handshake(client, load=load_limits)
    orientation, orientation_info = _load_rig_orientation(enabled=load_orientation)
    translations, calibration_info = _load_objective_calibration(
        calibration_name,
        enabled=load_calibration,
    )
    session_state.install(
        client,
        session_state.SessionConfig(
            orientation=orientation,
            translations=translations,
            calibration_name=calibration_info["name"],
            orientation_info=orientation_info,
            calibration_info=calibration_info,
        ),
    )
    return client
