"""The registry: where drivers plug in.

A driver registers a table of functions, one per command, under a
``connection`` dict. Three keys in that dict name the instrument: ``vendor``,
``microscope`` and ``api``. Any other keys are the driver's own, and go to its
``connect`` unchanged.

The registry checks only that a driver fits: every required function is
there, and the three identity keys are present. Everything else is the
driver's job.

Drivers register themselves when imported. :func:`register_driver` imports
one from a folder, a file or a module name. A driver installed as a package
can also announce itself through an entry point; see
:func:`discover_installed_drivers`.

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

# Every driver must provide a function for each of these. disconnect is optional.
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

# The keys that name an instrument. Any other key in a connection dict is the driver's own.
IDENTITY: tuple[str, ...] = ("vendor", "microscope", "api")

# (vendor, microscope, api) -> {"connection", "ops"}
REGISTRY: dict[tuple[str, ...], dict[str, Any]] = {}


def _identity(connection: dict[str, Any]) -> tuple[str, ...]:
    """The (vendor, microscope, api) triple of a connection dict."""
    missing = [key for key in IDENTITY if key not in connection]
    if missing:
        # Name keys only, never values: a connection dict may hold a password.
        raise ValueError(
            f"connection missing identity keys {missing}; has keys {sorted(connection)}"
        )
    return tuple(connection[key] for key in IDENTITY)


def register(connection: dict[str, Any], *, ops: dict[str, Any]) -> None:
    """Register a driver for one instrument.

    ``connection`` names the instrument and holds whatever the driver needs to
    connect. ``ops`` maps every name in :data:`OPS` to a function;
    ``disconnect`` is optional. Raises ``ValueError`` if a function or an
    identity key is missing. Registering the same instrument twice replaces
    the earlier entry, with a warning.
    """
    missing = [name for name in OPS if name not in ops]
    if missing:
        raise ValueError(f"driver {_identity(connection)} missing ops: {missing}")
    key = _identity(connection)
    if key in REGISTRY:
        logger.warning("driver %s already registered; overwriting", key)
    REGISTRY[key] = {"connection": dict(connection), "ops": ops}


def register_driver(driver: str | Path) -> list[dict[str, Any]]:
    """Plug a driver in, and return the instruments it added.

    ``driver`` is a package folder, a single ``.py`` file, or a module name.
    Importing it registers its instruments. Put this line at the top of a
    notebook, before :func:`get_instruments`. Calling it twice is harmless.
    Raises ``ValueError`` if nothing is found there, or nothing registers.
    """
    before = set(REGISTRY)
    module, fresh = _import_driver(driver)
    if set(REGISTRY) == before:
        # Some drivers register only when asked, through their own register().
        hook = getattr(module, "register", None)
        if callable(hook) and getattr(hook, "__module__", None) == module.__name__:
            hook()
        if fresh and set(REGISTRY) == before:
            raise ValueError(f"{driver!s} was imported but registered no instrument")
    added = sorted(set(REGISTRY) - before)
    return [dict(REGISTRY[key]["connection"]) for key in added]


def _import_driver(driver: str | Path):
    """Import a driver from a folder, a file or a module name.

    Returns the module, and whether this call was the first to import it.
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

# True once installed drivers have been asked to register.
_discovered = False


def discover_installed_drivers() -> None:
    """Ask every installed driver package to register itself, once.

    A package announces itself with one line in its ``pyproject.toml``::

        [project.entry-points."zmart_controller.drivers"]
        acme = "zmart_drivers.acme:register"

    A driver that fails to load is logged and skipped, so one broken driver
    never hides the others.
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

    Each entry is a dict you can pass to :func:`set_instrument`. You may edit
    it first, for example to add a password. Installed driver packages are
    found here automatically.
    """
    discover_installed_drivers()
    return [dict(entry["connection"]) for _key, entry in sorted(REGISTRY.items())]


def resolve(instrument: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Find the driver for an instrument; return ``(ops, connection)``.

    Raises ``ValueError`` if no driver matches.
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
