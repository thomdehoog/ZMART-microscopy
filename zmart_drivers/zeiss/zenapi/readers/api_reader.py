"""
State readers (ZEN API, unary gRPC).
====================================
Every read is one ``client.submit(unary_rpc)`` plus parsing. This is the single
place where SI meters (on the wire) become micrometers (the public unit).

ZEN has no log leg, so -- unlike the Leica driver -- there is no api/log/hybrid
router; every datum is an api read. ``diagnostics=True`` wraps the value in a
``Reading`` (value + source + observation time) so confirmations can apply the
freshness gate.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import logging

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
    """Extract a turret index from an objective/position response (or a bare int)."""
    if isinstance(resp, int):
        return resp
    val = _attr(resp, "position_index", "position", "index", "value")
    return int(val) if val is not None else None


def status_to_dict(item) -> dict:
    """Normalize a status-stream message into the plain dict of fields we use."""
    s = getattr(item, "status", item)
    return {
        "is_experiment_running": bool(getattr(s, "is_experiment_running", False)),
        "is_acquisition_running": bool(getattr(s, "is_acquisition_running", False)),
        "tiles_index": getattr(s, "tiles_index", None),
        "time_points_index": getattr(s, "time_points_index", None),
        "channels_index": getattr(s, "channels_index", None),
        "zstack_slices_index": getattr(s, "zstack_slices_index", None),
        "images_acquired_index": getattr(s, "images_acquired_index", None),
    }


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
    """Return the fitted objectives as ``[{"index","name","magnification"}]`` (cached)."""
    if client._objectives_cache is not None:
        return client._objectives_cache
    resp = client.submit(
        client.objective.get_objectives(client.messages.objectives_get()),
        timeout=READERS.read_timeout_s,
    )
    items = _attr(resp, "objectives", "items", default=resp) or []
    parsed = []
    for it in items:
        parsed.append(
            {
                "index": _index_of(it),
                "name": _attr(it, "name"),
                "magnification": _attr(it, "magnification", "mag"),
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


def get_status(client, experiment=None, *, diagnostics=False):
    """Read a status snapshot.

    With an ``experiment`` (or experiment id), consumes the first item of its
    status stream. Without one, returns a "not running" sentinel -- a bare-
    instrument status stream is not exposed by this API (see README risks).
    """
    if experiment is None:
        value = {"is_experiment_running": False, "is_acquisition_running": False}
        return _wrap(value, diagnostics)

    experiment_id = getattr(experiment, "experiment_id", experiment)
    factory = lambda: client.experiment.register_on_status_changed(  # noqa: E731
        client.messages.status_subscribe(experiment_id)
    )
    value = {"is_experiment_running": False, "is_acquisition_running": False}
    for item in client.stream(factory, item_timeout=READERS.status_item_timeout_s):
        value = status_to_dict(item)
        break  # snapshot: first item only; generator close cancels the stream
    return _wrap(value, diagnostics)


def monitor(client, experiment, *, kind="status", channel_index=0, enable_raw_data=False):
    """Blocking generator over a ZEN server stream for a running experiment.

    ``kind="status"`` yields status dicts (``status_to_dict``) until the stream
    ends. ``kind="pixels"`` (the ``monitor_experiment`` PixelStream -> numpy
    frame path) is an extension seam, not built in the MVP.
    """
    experiment_id = getattr(experiment, "experiment_id", experiment)
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
