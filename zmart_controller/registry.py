"""Driver registry: the one place that points the controller at drivers.

A driver registers an ops table - a mapping of operation name to driver callable
- under a ``connection`` dict. ``get_instruments()`` lists what is registered
(without connecting) as the connection dicts themselves; ``resolve()`` looks one
up for ``set_instrument()``.

The registry keys on the ``(vendor, microscope, api)`` identity carried inside
the connection dict; everything else in that dict is free for the driver to use
(client name, api delay, host, credentials, ...) and is forwarded untouched to
``connect``.

Return contract for ops: every op except ``connect`` and ``disconnect``
returns ``{"success": bool, "report": ...}``, with the report's content the
driver's own. A failure that makes carrying on unsafe is raised instead
(``ValueError`` for a mistake in the request, ``RuntimeError`` for a failure or
refusal on the microscope); the controller forwards return values uninspected
and propagates exceptions unchanged. Error text must be credential-safe:
connection dicts may carry credentials, so messages name keys, never values
(as :func:`_identity` does).

The registry is the plug: it checks only that a driver fits (every required
operation is present, and the identity keys are there). Everything else,
including every refusal about the microscope itself, is the driver's job.
Drivers register themselves, usually when their module is imported; the mock
microscope registers with ``zmart_controller.mock.register()``. A driver that
is installed as its own package can also announce itself, so that it is found
without anyone importing it: it names a function in its ``pyproject.toml``
under the entry-point group ``"zmart_controller.drivers"``, and
:func:`get_instruments` calls that function the first time it runs.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Every driver ops table must provide a callable for each of these operations.
# disconnect is optional.
OPS: tuple[str, ...] = (
    "connect",
    "get_acquisition_options",
    "get_actuators",
    "get_xyz",
    "set_xyz",
    "acquire",
    "get_state",
    "set_state",
    "get_procedures",
    "run_procedure",
    "get_info",
)

# The keys the registry indexes on. Everything else in a connection dict is
# variable and driver-defined (client name, api delay, host, credentials, ...).
IDENTITY: tuple[str, ...] = ("vendor", "microscope", "api")

# (vendor, microscope, api) -> {"connection", "ops"}
REGISTRY: dict[tuple[str, ...], dict[str, Any]] = {}


def _identity(connection: dict[str, Any]) -> tuple[str, ...]:
    """Pull the (vendor, microscope, api) identity out of a connection dict."""
    missing = [key for key in IDENTITY if key not in connection]
    if missing:
        # List only the keys, never the values -- connection dicts may carry credentials.
        raise ValueError(
            f"connection missing identity keys {missing}; has keys {sorted(connection)}"
        )
    return tuple(connection[key] for key in IDENTITY)


def register(connection: dict[str, Any], *, ops: dict[str, Any]) -> None:
    """Wire a driver into the registry under its ``connection`` identity.

    ``connection`` is the variable dict forwarded to ``connect`` at session open.
    It must carry the ``vendor`` / ``microscope`` / ``api`` identity the registry
    keys on, and may carry any driver-specific extras. ``ops`` must cover every
    name in :data:`OPS` (``disconnect`` is optional). Raises ``ValueError`` if an
    op is missing or the connection identity is incomplete. Registering the same
    identity twice logs a warning and overwrites the earlier entry (last wins).
    """
    missing = [name for name in OPS if name not in ops]
    if missing:
        raise ValueError(f"driver {_identity(connection)} missing ops: {missing}")
    key = _identity(connection)
    if key in REGISTRY:
        logger.warning("driver %s already registered; overwriting", key)
    REGISTRY[key] = {"connection": dict(connection), "ops": ops}


def register_driver(driver: str | Path) -> list[dict[str, Any]]:
    """Plug a driver in, and return the instruments it provides.

    ``driver`` is where the driver lives: a folder holding the driver package,
    a single ``.py`` file, or a module name that Python can already import
    (for example ``"zmart_drivers.nikon.nis_elements_6_10"``). The driver is
    imported, which registers its instruments the way drivers always do.

    Put this one line at the top of a notebook, before
    :func:`get_instruments`. Calling it again for the same driver is
    harmless. Raises ``ValueError`` if nothing can be found at ``driver`` or if
    it registers no instrument.
    """
    before = set(REGISTRY)
    module, fresh = _import_driver(driver)
    if fresh and set(REGISTRY) == before:
        # Some drivers register only when asked, through a register() function.
        hook = getattr(module, "register", None)
        if callable(hook):
            hook()
        if set(REGISTRY) == before:
            raise ValueError(f"{driver!s} was imported but registered no instrument")
    added = sorted(set(REGISTRY) - before)
    return [dict(REGISTRY[key]["connection"]) for key in added]


def _import_driver(driver: str | Path):
    """Import a driver from a folder, a file, or a module name.

    Returns the module and whether this call imported it for the first time.
    """
    path = Path(driver)
    if path.suffix == ".py" and path.is_file():
        name = path.stem
        if name in sys.modules:
            return sys.modules[name], False
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            del sys.modules[name]
            raise
        return module, True
    if path.is_dir():
        if not (path / "__init__.py").is_file():
            raise ValueError(f"{path} is a folder but not a Python package (no __init__.py)")
        parent = str(path.resolve().parent)
        if parent not in sys.path:
            sys.path.insert(0, parent)
        name = path.resolve().name
    else:
        name = str(driver)
    fresh = name not in sys.modules
    try:
        module = importlib.import_module(name)
    except ModuleNotFoundError as exc:
        if exc.name and name.startswith(exc.name):
            raise ValueError(f"no driver found at {driver!s}") from None
        raise
    return module, fresh


ENTRY_POINT_GROUP = "zmart_controller.drivers"

# Set once the installed drivers have been asked to register themselves.
_discovered = False


def discover_installed_drivers() -> None:
    """Ask every installed driver package to register itself, once.

    A driver package announces itself with one line in its ``pyproject.toml``::

        [project.entry-points."zmart_controller.drivers"]
        acme = "zmart_drivers.acme:register"

    The named function is called here. A driver that fails to load is
    reported in the log and skipped, so one broken driver never hides the
    others.
    """
    global _discovered
    if _discovered:
        return
    _discovered = True
    for entry_point in entry_points(group=ENTRY_POINT_GROUP):
        try:
            hook = entry_point.load()
            if callable(hook):
                hook()
        except Exception:
            logger.exception("driver %r could not be loaded; skipping it", entry_point.name)


def get_instruments() -> list[dict[str, Any]]:
    """List the available instruments, without connecting to anything.

    Each entry is the connection dict you pass straight to :func:`set_instrument`.
    You may edit it first (e.g. drop in a credential); it is forwarded to the
    driver's ``connect`` untouched. Drivers installed as packages are found
    here automatically; see :func:`discover_installed_drivers`.
    """
    discover_installed_drivers()
    return [dict(entry["connection"]) for _key, entry in sorted(REGISTRY.items())]


def resolve(instrument: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Look up the ops table for a connection dict and return ``(ops, connection)``.

    ``instrument`` is one of the connection dicts from :func:`get_instruments`;
    its identity selects the driver and the whole dict is forwarded to
    ``connect``. Raises ``ValueError`` if no driver matches the identity.
    """
    key = _identity(instrument)
    try:
        entry = REGISTRY[key]
    except KeyError:
        raise ValueError(
            f"no driver registered for {dict(zip(IDENTITY, key, strict=True))}; "
            f"known: {sorted(REGISTRY)}"
        ) from None
    return entry["ops"], instrument
