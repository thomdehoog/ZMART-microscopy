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


def _load_objective_translations(calibration_name: str | None = None) -> dict | None:
    """Per-slot objective translations (micrometres), or None when unavailable.

    Loads the active calibration through the calibration model. Any IO or
    schema problem degrades to ``None`` (logged, not raised) so a missing or
    unreadable calibration never fails the connection — the frame math then
    refuses cross-objective moves and warns on cross-objective reads instead of
    silently computing uncompensated values.
    """
    # This import must stay inside the function: the package root imports this
    # module when the driver loads, and the calibration modules import the
    # package root — a module-level import here would be a circular import.
    from ..calibration.core import model as _cal_model

    try:
        return _cal_model.load_translations(calibration_name)
    except Exception as exc:  # noqa: BLE001 -- config IO / schema; degrade, don't crash connect
        _log.warning(
            "objective translations unavailable (%s); cross-objective moves will be refused",
            exc,
        )
        return None


def _load_rig_orientation() -> Any:
    """The measured camera turn, or the identity turn when the file is unreadable.

    Reads the machine's ``orientation.json`` through the machine profile. Any IO
    or schema problem degrades to the identity ("no turn") orientation — logged
    loudly, not raised — so a corrupt file never fails the connection. Saved
    images are then left exactly as the camera produced them (the same defined
    meaning as ``load_orientation=False``) until the operator re-publishes the
    file with ``orientation/notebooks/set_orientation.ipynb`` and reconnects.
    """
    from .. import orientation as _orientation

    try:
        return _orientation.rig_orientation()
    except Exception as exc:  # noqa: BLE001 -- config IO / schema; degrade, don't crash connect
        _log.warning(
            "orientation unavailable (%s); saved images will NOT be turned to the "
            "stage axes this session. Re-publish orientation.json with "
            "orientation/notebooks/set_orientation.ipynb and reconnect.",
            exc,
        )
        return _orientation.Orientation()


def _orientation_info(*, enabled: bool, loaded_orientation: Any) -> dict:
    """Describe the orientation selected at connect, including measurement proof."""
    if not enabled:
        return {
            "enabled": False,
            "loaded": False,
            "measured": False,
            "path": None,
            "rotate_deg": int(loaded_orientation.rotate_deg),
        }
    from ..config.machine import MACHINE

    path = MACHINE.orientation_path().absolute()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        from .. import orientation as _orientation

        validated = _orientation.load_orientation(path)
    except Exception as exc:  # noqa: BLE001 -- evidence for a fail-soft load
        return {
            "enabled": True,
            "loaded": False,
            "measured": False,
            "path": str(path),
            "rotate_deg": int(loaded_orientation.rotate_deg),
            "error": str(exc),
        }
    return {
        "enabled": True,
        "loaded": validated == loaded_orientation,
        # A real measured 0-degree orientation is valid. The explicit marker,
        # not the angle, distinguishes it from the shipped identity placeholder.
        "measured": validated == loaded_orientation and data.get("measured") is True,
        "path": str(path),
        "rotate_deg": int(loaded_orientation.rotate_deg),
    }


def _calibration_info(
    *,
    enabled: bool,
    calibration_name: str | None,
    translations: dict | None,
) -> dict:
    """Describe the objective calibration selected and loaded by the driver.

    ``slots`` lists every objective the loaded file covers. ``measured_slots``
    lists only the objectives whose entry records the calibration session that
    measured it (``session_id``). The difference matters for the preflight
    verdict: a missing calibration file is seeded from the repository's bundled
    placeholder, whose entries carry no session provenance — those values were
    never measured on this microscope and must not count as calibrated.
    """
    from ..config.machine import CALIBRATION_NAME_ENV

    effective_name = calibration_name or os.environ.get(CALIBRATION_NAME_ENV)
    if not enabled:
        return {
            "enabled": False,
            "loaded": False,
            "name": effective_name,
            "path": None,
            "slots": [],
            "measured_slots": [],
        }
    from ..calibration.core import model as _cal_model

    path = _cal_model.default_path(calibration_name).absolute()
    measured_slots: list[int] = []
    if translations is not None:
        try:
            config = _cal_model.load_calibration(path)
            measured_slots = sorted(
                int(slot)
                for slot, entry in (config.get("objectives") or {}).items()
                if entry.get("session_id")
            )
        except Exception as exc:  # noqa: BLE001 -- same fail-soft posture as the translations load
            _log.warning("could not read calibration provenance from %s (%s)", path, exc)
            measured_slots = []
    return {
        "enabled": True,
        "loaded": translations is not None,
        "name": effective_name,
        "path": str(path),
        "slots": sorted(int(slot) for slot in (translations or {})),
        "measured_slots": measured_slots,
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
      produced them (no quarter-turn to stage axes).
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
    from .. import orientation as _orientation
    from ..commands import gate as _gate
    from . import session_state

    client = connect_python_client(client_name=client_name, api_delay_ms=api_delay_ms)
    _gate.connect_handshake(client, load=load_limits)
    orientation = _load_rig_orientation() if load_orientation else _orientation.Orientation()
    translations = _load_objective_translations(calibration_name) if load_calibration else None
    orientation_info = _orientation_info(enabled=load_orientation, loaded_orientation=orientation)
    calibration_info = _calibration_info(
        enabled=load_calibration,
        calibration_name=calibration_name,
        translations=translations,
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
