"""The setup registry: which drivers can be configured, and through which functions.

A driver registers an ops table -- operation name to callable -- under the same
``(vendor, microscope, api)`` identity the controller's registry uses, so the
instrument an operator connected to on the page is the one whose setup is
offered. The two registries are separate on purpose and never import one
another: holding a controller session gives no way to reach anything here.

## The vocabulary a driver supplies

Every op takes the driver's own handle first. Required:

- ``open(connection) -> handle`` -- a driver-level connection that does **not**
  need a published envelope to succeed, since publishing one is what this is
  for. Moves are still fenced: by the driver's bundled default envelope and its
  physical backstop.
- ``close(handle)``.
- ``describe(handle) -> dict`` -- what this driver can configure. Carries
  ``label``, ``checks`` (name to answer, the way ``get_info`` reports them), and
  ``subsystems``: for each of :data:`SUBSYSTEMS`, ``{"supported": bool, ...}``
  with whatever else the page needs to draw it -- the limits document's
  axes and settings, say. A subsystem left out is unsupported.
- ``where(handle) -> {"x_um", "y_um", "z_um", "actuators": {...}}`` -- absolute
  stage coordinates, and under ``actuators`` every drive the instrument has,
  each as ``{"value", "unit"}`` -- a Leica has a motoric X and Y, a Z-wide and
  a Z-galvo. The origin is a reading of all of them, so all of them are shown
  when it is set. No origin is applied here: setting one is this package's job.
- ``move(handle, x_um, y_um, z_um) -> {"x_um", "y_um", "z_um"}`` -- move, then
  read back where the stage actually went, and answer with the readback.
- ``acquire(handle, *, into, name, z_um=None) -> dict`` -- one raw picture, or a
  stack when ``z_um`` lists the heights, written under ``into``. Answers with
  ``images`` (paths in plane order), ``pixel_um``, ``frame_px`` and ``job``.
  *Raw* means before any orientation correction: measuring the orientation
  needs the pixels as the camera recorded them.
- ``read(handle, subsystem, *, fresh=False) -> dict`` -- the document as it
  currently stands, published or bundled default, with ``source`` saying
  which; with ``fresh`` the bundled default regardless, which is what a
  setup that starts over begins from.
- ``publish(handle, subsystem, document, evidence=()) -> dict`` -- validate
  and write a dated snapshot; answer with where it went. The file's schema
  version is the driver's to stamp: a publisher says what the document
  means, never which version of the driver's file it is. ``evidence`` names
  files, or whole folders, to keep beside the document in the snapshot --
  the figures the analysis drew, the measurement's numbers, and the raw
  frames and stacks it was measured from -- so what was measured can be
  shown again when the configuration is reopened. A driver that has nowhere
  to keep them for a subsystem may leave them out.
- ``read(...)`` answers, when published, with ``evidence``: one
  ``{"name", "path"}`` per file kept beside the document, ``name`` being the
  file's path relative to where the evidence is kept, or ``[]``.

Optional -- a driver that cannot do them leaves them out, and the page greys
out what depends on them:

- ``objective(handle) -> {"slot", "name"}`` -- which lens is in. Observed, never
  commanded: an operator changes lenses in the vendor's own software.
- ``objectives(handle) -> [{"slot", "name"}, ...]`` -- every lens the turret
  holds, so a calibration can name its reference and its targets from the
  instrument's own list rather than from typing.
- ``markers(handle) -> {"points": [{"x_um", "y_um"}, ...]}`` -- points the
  operator placed in the vendor's software to say where the safe corners are.
- ``configurations(connection) -> [{"id", "created_at", "has": {...}}, ...]``
  -- every configuration the machine has, newest first, without opening the
  instrument: the folders under the machine's configuration root.
- ``new_configuration(handle) -> {...}`` -- start a configuration as a full
  copy of what stands now, and stand on it.
- ``use_configuration(handle, id) -> {...}`` -- stand on one by id.
- ``configuration(handle) -> {...} | None`` -- the one being stood on.

Error contract: report failure by raising (``ValueError`` for a caller's
mistake, ``RuntimeError`` for an instrument's refusal or failure), never by
encoding it in the returned dict. Error text must never carry credentials.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

#: The four things a driver keeps for a machine, in the order they are set up.
SUBSYSTEMS: tuple[str, ...] = ("limits", "orientation", "calibration", "origin")

#: Every driver's ops table must supply these.
OPS: tuple[str, ...] = (
    "open", "close", "describe", "where", "move", "acquire", "read", "publish",
)

#: A driver may supply these; the page asks before relying on them.
OPTIONAL_OPS: tuple[str, ...] = (
    "objective", "objectives", "markers",
    "configurations", "new_configuration", "use_configuration", "configuration",
)

#: The keys the registry indexes on -- the same three the controller uses.
IDENTITY: tuple[str, ...] = ("vendor", "microscope", "api")

REGISTRY: dict[tuple[str, ...], dict[str, Any]] = {}


def _identity(connection: dict[str, Any]) -> tuple[str, ...]:
    missing = [key for key in IDENTITY if key not in connection]
    if missing:
        # Keys only, never values: a connection dict may carry credentials.
        raise ValueError(
            f"connection missing identity keys {missing}; has keys {sorted(connection)}"
        )
    return tuple(connection[key] for key in IDENTITY)


def register(connection: dict[str, Any], *, ops: dict[str, Any]) -> None:
    """Wire a driver's setup into the registry under its connection identity.

    ``ops`` must cover every name in :data:`OPS`; the names in
    :data:`OPTIONAL_OPS` may be present. Any other name is refused, so that a
    misspelt op is a loud error at registration rather than a silent gap on
    the page. Registering the same identity twice replaces the first.
    """
    identity = _identity(connection)
    missing = [name for name in OPS if name not in ops]
    if missing:
        raise ValueError(f"setup ops table for {identity} is missing {missing}")
    unknown = [name for name in ops if name not in OPS and name not in OPTIONAL_OPS]
    if unknown:
        raise ValueError(f"setup ops table for {identity} names unknown ops {unknown}")
    not_callable = [name for name, fn in ops.items() if not callable(fn)]
    if not_callable:
        raise ValueError(f"setup ops table for {identity} has non-callable ops {not_callable}")
    if identity in REGISTRY:
        logger.info("replacing setup registration for %s", identity)
    REGISTRY[identity] = {"connection": dict(connection), "ops": dict(ops)}


def get_instruments() -> list[dict[str, Any]]:
    """The connection dicts of every driver that can be set up, touching no hardware."""
    return [dict(entry["connection"]) for entry in REGISTRY.values()]


def get_configurations(connection: dict[str, Any]) -> list[dict[str, Any]]:
    """The configurations a machine keeps, newest first, touching no hardware
    -- so a connect card can offer them before anything is opened. A driver
    that keeps none lists none."""
    ops, resolved = resolve(connection)
    if "configurations" not in ops:
        return []
    return list(ops["configurations"](resolved))


def resolve(connection: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """The ops table registered for this identity, and the connection to open with.

    The registered connection is the base, and whatever the caller passed --
    credentials, an output root -- is laid over it, so a driver sees what the
    page asked for and what it registered with together.
    """
    identity = _identity(connection)
    entry = REGISTRY.get(identity)
    if entry is None:
        raise ValueError(f"no setup driver registered for {identity}")
    return entry["ops"], {**entry["connection"], **connection}
