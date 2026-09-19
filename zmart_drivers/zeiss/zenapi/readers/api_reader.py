"""
State readers (ZEN API, unary gRPC).
====================================
Every read is one ``client.submit(unary_rpc)`` plus parsing. This is the single
place where SI meters (on the wire) become micrometers (the public unit).

ZEN has no log to tail, so -- unlike the Leica driver -- there is no
api/log/hybrid router; every datum is an api read. ``diagnostics=True`` wraps
the value in a ``Reading`` (value + source + observation time) so
confirmations can apply the freshness gate.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import logging

from ..commands.errors import _status_name
from ..config.profiles import READERS
from ..config.units import m_to_um
from .reading import Reading

log = logging.getLogger(__name__)


def _safe_float(val, default=None):
    """Convert val to float. Returns default on failure or None input.

    API responses are parsed defensively, so a field can arrive as a number,
    a numeric string, or be missing; every reader funnels values through this
    one forgiving conversion.
    """
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _attr(obj, *names, default=None):
    """Return the first present attribute among ``names`` (defensive parsing)."""
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


def _index_of(resp):
    """The position index from an objective-changer response.

    ``GetPosition`` answers with ``value``; an ``ObjectiveData`` entry carries
    ``position``. A bare int is accepted too.
    """
    if isinstance(resp, int):
        return resp
    val = _attr(resp, "value", "position", "position_index", "index")
    return int(val) if val is not None else None


# Fields of ZEN's ExperimentStatus message. The indices are 0-based; ZEN
# reports 0 or -1 for a dimension the experiment does not have.
_STATUS_FIELDS = (
    "tiles_index",
    "tiles_count",
    "scenes_index",
    "scenes_count",
    "time_points_index",
    "time_points_count",
    "zstack_slices_index",
    "zstack_slices_count",
    "channels_index",
    "channels_count",
    "images_acquired_index",
    "images_count",
)


def status_to_dict(item) -> dict:
    """Turn a status message (or a stream item wrapping one) into a plain dict.

    Both ``GetStatus`` and the status stream answer with a ``status`` field
    holding an ``ExperimentStatus``; a bare status object is accepted as well.
    """
    s = getattr(item, "status", item)
    out = {
        "is_experiment_running": bool(getattr(s, "is_experiment_running", False)),
        "is_acquisition_running": bool(getattr(s, "is_acquisition_running", False)),
    }
    for name in _STATUS_FIELDS:
        out[name] = getattr(s, name, None)
    elapsed = getattr(s, "total_elapsed_time", None)
    out["total_elapsed_s"] = (
        elapsed.total_seconds() if hasattr(elapsed, "total_seconds") else _safe_float(elapsed)
    )
    return out


def _wrap(value, diagnostics):
    return Reading.now(value) if diagnostics else value


def get_xy(client, *, diagnostics=False):
    """Read stage XY. Returns ``{"x_m","y_m","x_um","y_um"}`` (or a Reading)."""
    resp = client.submit(
        client.stage.get_position(client.messages.stage_get()),
        timeout=READERS.read_timeout_s,
    )
    x_m = _safe_float(_attr(resp, "x"))
    y_m = _safe_float(_attr(resp, "y"))
    value = {"x_m": x_m, "y_m": y_m, "x_um": m_to_um(x_m), "y_um": m_to_um(y_m)}
    return _wrap(value, diagnostics)


def get_z(client, *, diagnostics=False):
    """Read focus Z in micrometers (or a Reading wrapping the µm float)."""
    resp = client.submit(
        client.focus.get_position(client.messages.focus_get()),
        timeout=READERS.read_timeout_s,
    )
    z_um = m_to_um(_safe_float(_attr(resp, "value", "z")))
    return _wrap(z_um, diagnostics)


def get_objectives(client):
    """The objectives on the changer, as ``[{"index","name","magnification","na","immersion"}]``.

    ``index`` is ZEN's position index on the objective changer (the number
    ``set_objective`` needs). The list is read once and cached on the client
    because the objectives fitted to a microscope do not change during a
    session.
    """
    if client._objectives_cache is not None:
        return client._objectives_cache
    resp = client.submit(
        client.objective.get_objectives(client.messages.objectives_get()),
        timeout=READERS.read_timeout_s,
    )
    items = _attr(resp, "objectives", "items", default=resp) or []
    parsed = []
    for it in items:
        immersion = _attr(it, "immersion_type")
        parsed.append(
            {
                "index": _index_of(it),
                "name": _attr(it, "name"),
                "magnification": _safe_float(_attr(it, "magnification", "mag")),
                "na": _safe_float(_attr(it, "na")),
                "immersion": getattr(immersion, "name", immersion),
            }
        )
    client._objectives_cache = parsed
    return parsed


def get_objective(client, *, diagnostics=False):
    """Read the current objective. Returns ``{"index","name","magnification"}``."""
    resp = client.submit(
        client.objective.get_position(client.messages.objective_get()),
        timeout=READERS.read_timeout_s,
    )
    index = _index_of(resp)
    name = None
    magnification = None
    try:
        for obj in get_objectives(client):
            if obj["index"] == index:
                name = obj["name"]
                magnification = obj["magnification"]
                break
    except Exception:  # noqa: BLE001 - enrichment is best-effort
        log.debug("objective enrichment failed", exc_info=True)
    value = {"index": index, "name": name, "magnification": magnification}
    return _wrap(value, diagnostics)


def get_available_experiments(client) -> list[str]:
    """The names of the experiments ZEN can load (its ``.czexp`` files, without extension)."""
    resp = client.submit(
        client.experiment.get_available_experiments(client.messages.experiments_available()),
        timeout=READERS.read_timeout_s,
    )
    items = _attr(resp, "experiments", default=resp) or []
    return [str(_attr(it, "name", default=it)) for it in items]


def get_image_output_path(client) -> str:
    """The folder on the ZEN computer where acquisitions are written as CZI files.

    ZEN names the file after the ``output_name`` of the acquisition, so the
    full path of an image is ``<this folder>/<output_name>.czi``.
    """
    resp = client.submit(
        client.experiment.get_image_output_path(client.messages.image_output_path()),
        timeout=READERS.read_timeout_s,
    )
    if isinstance(resp, str):
        return resp
    return str(_attr(resp, "image_output_path", "path", default=""))


_IDLE_STATUS = {"is_experiment_running": False, "is_acquisition_running": False}


def get_status(client, experiment=None, *, diagnostics=False):
    """Read an experiment's status with one call (``GetStatus``).

    With an ``experiment`` (or its id string) ZEN answers for that experiment,
    whether it is still running or already finished. Without one ZEN answers
    for whichever experiment is active, and raises an error when nothing is
    running -- that error is turned into a plain "nothing running" answer
    here, so the call is a safe way to ask "is the microscope busy?".
    """
    experiment_id = getattr(experiment, "experiment_id", experiment) or ""
    try:
        resp = client.submit(
            client.experiment.get_status(client.messages.status_get(experiment_id)),
            timeout=READERS.read_timeout_s,
        )
    except Exception as exc:
        # Without an id, ZEN answers "no active experiment" with an error. Only
        # that kind of answer (an error from ZEN itself) means idle; a lost
        # connection, a refused token or a timeout must still surface.
        if experiment_id or _is_connection_problem(exc):
            raise
        log.debug("get_status without experiment: nothing active (%s)", exc)
        return _wrap(dict(_IDLE_STATUS), diagnostics)
    return _wrap(status_to_dict(resp), diagnostics)


# gRPC status codes that mean the gateway or ZEN could not be reached or
# would not let us in -- never "nothing is running".
_CONNECTION_STATUSES = frozenset(
    {"UNAVAILABLE", "UNAUTHENTICATED", "PERMISSION_DENIED", "DEADLINE_EXCEEDED", "CANCELLED"}
)


def _is_connection_problem(exc: BaseException) -> bool:
    """True when the error is about the link or the token, not about ZEN's state."""
    if isinstance(exc, TimeoutError):
        return True
    name = _status_name(exc)
    return name is None or name in _CONNECTION_STATUSES


def monitor(client, experiment=None, *, kind="status", channel_index=0, enable_raw_data=False):
    """Follow a running experiment as a blocking generator of status dicts.

    Subscribes to ZEN's status stream (``RegisterOnStatusChanged``) and yields
    one dict per update until the stream ends. ZEN only accepts the
    subscription while the experiment is active: start it with
    ``start_experiment`` first, then monitor. Subscribing after it finished
    raises a gRPC error (that is ZEN's documented behaviour, not a driver bug).
    Without an ``experiment`` ZEN picks one of the active experiments.

    ``kind="pixels"`` (the live pixel stream to numpy) is not built yet.
    """
    experiment_id = getattr(experiment, "experiment_id", experiment) or ""
    if kind == "status":
        factory = lambda: client.experiment.register_on_status_changed(  # noqa: E731
            client.messages.status_subscribe(experiment_id)
        )
        for item in client.stream(factory, item_timeout=READERS.status_item_timeout_s):
            yield status_to_dict(item)
        return
    raise NotImplementedError(
        "monitor(kind='pixels') is an extension seam (ExperimentStreamingService "
        "-> numpy). See the driver README."
    )


def ping(client) -> bool:
    """Cheap connectivity check: attempt a stage read."""
    try:
        get_xy(client)
        return True
    except Exception:  # noqa: BLE001
        log.debug("ping failed", exc_info=True)
        return False
