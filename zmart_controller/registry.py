"""The registry: where drivers plug in.

A driver registers a table of functions, one per command, under a
``connection`` dict. Three keys in that dict name the instrument: ``vendor``,
``microscope`` and ``api``. Any other keys are the driver's own, and go to its
``connect`` unchanged.

The registry checks only that a driver fits: every required function is
there, and the three identity keys are present. Everything else is the
driver's job.

Drivers register themselves when imported. :func:`register_driver` imports
one from a folder, a file or a module name, and remembers it in this
computer's configuration folder, so later sessions plug it in by themselves.
A driver installed as a package can instead announce itself through an entry
point; see :func:`discover_installed_drivers`.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import copy
import hashlib
import importlib
import importlib.util
import json
import logging
import os
import platform
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

# Every identity passed to register(), in order, including replacements.
# register_driver reads it to see what a driver registered during its call.
_REGISTRATIONS: list[tuple[str, ...]] = []


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
    # A full copy, nested settings included: later edits to the caller's dict,
    # or to a dict from get_instruments(), must never change what is stored.
    REGISTRY[key] = {"connection": copy.deepcopy(connection), "ops": ops}
    _REGISTRATIONS.append(key)


# The folder with the driver's controller-facing functions, inside a driver.
PLUGIN_FOLDER = "zmart_plugin"


def config_root() -> Path:
    """The machine-wide folder where ZMART keeps its configuration.

    ``ZMART_MICROSCOPY_ROOT`` overrides it. Otherwise it is
    ``C:\\ProgramData\\zmart-microscopy`` on Windows,
    ``/Library/Application Support/zmart-microscopy`` on macOS and
    ``/etc/zmart-microscopy`` on Linux. The drivers keep their origin, limits
    and calibration under the same root.
    """
    override = os.environ.get("ZMART_MICROSCOPY_ROOT")
    if override:
        return Path(override)
    system = platform.system()
    if system == "Windows":
        return Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "zmart-microscopy"
    if system == "Darwin":
        return Path("/Library/Application Support/zmart-microscopy")
    return Path("/etc/zmart-microscopy")


def _drivers_file() -> Path:
    return config_root() / "zmart_controller" / "drivers.json"


def remembered_drivers() -> list[str]:
    """The drivers this computer plugs in by itself, as saved by :func:`register_driver`."""
    path = _drivers_file()
    if not path.is_file():
        return []
    try:
        entries = json.loads(path.read_text())
    except ValueError as exc:
        raise RuntimeError(f"the driver list at {path} is not valid JSON: {exc}") from None
    return [str(entry) for entry in entries]


def _save_remembered(entries: list[str]) -> None:
    path = _drivers_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entries, indent=2) + "\n")
    except PermissionError:
        raise PermissionError(
            f"cannot write {path}. Run this once with the rights to write there, "
            f"or point ZMART_MICROSCOPY_ROOT at a folder you can write."
        ) from None


def forget_driver(driver: str | Path) -> bool:
    """Stop plugging a driver in at the start of later sessions.

    Returns whether it was on the list. The driver stays plugged in for the
    rest of this session.
    """
    key = _driver_key(driver)
    entries = remembered_drivers()
    if key not in entries:
        return False
    _save_remembered([e for e in entries if e != key])
    return True


def _driver_key(driver: str | Path) -> str:
    """How a driver is written down: an absolute path, or the module name as given."""
    path = Path(driver)
    if path.exists():
        return str(path.resolve())
    return str(driver)


def register_driver(driver: str | Path, *, remember: bool = True) -> list[dict[str, Any]]:
    """Plug a driver in, and return the instruments it registered.

    ``driver`` is a driver folder, a single ``.py`` file, or a module name. A
    driver folder may keep its controller-facing functions in a
    ``zmart_plugin/`` subfolder; that is what gets imported then. Importing
    registers the instruments.

    Run this once per driver on each microscope computer. The driver is
    remembered in this computer's configuration folder, and every later
    session plugs it in by itself when :func:`get_instruments` runs. Pass
    ``remember=False`` to plug it in for this session only. Calling it twice
    is harmless.

    The answer lists the instruments the driver registered during this call,
    including one that replaced an earlier entry with the same identity.
    Raises ``ValueError`` if nothing is found there, if a different driver
    package with the same name is already loaded, or if a newly imported
    driver registers nothing.
    """
    start = len(_REGISTRATIONS)
    module, fresh = _import_driver(driver)
    if len(_REGISTRATIONS) == start:
        # Some drivers register only when asked, through their own register().
        # That function may be written in a submodule and brought into the
        # package with an import, so it is called wherever it was defined.
        # The one function never called here is this registry's own
        # register, which drivers often import under the same name.
        hook = getattr(module, "register", None)
        if callable(hook) and hook is not register:
            hook()
        if fresh and len(_REGISTRATIONS) == start:
            raise ValueError(f"{driver!s} was imported but registered no instrument")
    touched = sorted(set(_REGISTRATIONS[start:]))
    if remember:
        key = _driver_key(driver)
        entries = remembered_drivers()
        if key not in entries:
            _save_remembered(entries + [key])
    return [copy.deepcopy(REGISTRY[key]["connection"]) for key in touched if key in REGISTRY]


def _is_loaded_from(module, path: Path) -> bool:
    """Whether an already imported module was read from this very file."""
    loaded = getattr(module, "__file__", None)
    return loaded is not None and Path(loaded).resolve() == path.resolve()


def _import_driver(driver: str | Path):
    """Import a driver from a folder, a file or a module name.

    Returns the module, and whether this call was the first to import it.

    Python remembers an imported module by its name alone, so two different
    files that are both called ``driver.py`` could be mistaken for one. A
    module is therefore reused only when it came from the very same file.
    """
    path = Path(driver)
    if path.is_dir() and (path / PLUGIN_FOLDER / "__init__.py").is_file():
        path = path / PLUGIN_FOLDER
    if path.suffix == ".py" and path.is_file():
        return _import_file(path)
    if path.is_dir():
        init = path / "__init__.py"
        if not init.is_file():
            raise ValueError(f"{path} is a folder but not a Python package (no __init__.py)")
        name = path.resolve().name
        known = sys.modules.get(name)
        if known is not None:
            if _is_loaded_from(known, init):
                return known, False
            raise ValueError(
                f"a different driver package called {name!r} is already loaded, from "
                f"{getattr(known, '__file__', 'an unknown place')}. Two packages cannot "
                f"share a name in one Python session, so rename one of the folders or "
                f"restart the notebook kernel."
            )
        parent = str(path.resolve().parent)
        if parent not in sys.path:
            sys.path.insert(0, parent)
        module = importlib.import_module(name)
        if not _is_loaded_from(module, init):
            # Another folder, earlier on Python's search path, holds a package
            # with the same name, and Python imported that one instead.
            del sys.modules[name]
            raise ValueError(
                f"importing {name!r} found {module.__file__} instead of {init}. "
                f"Rename the folder so that its name is unique."
            )
        return module, True
    name = str(driver)
    fresh = name not in sys.modules
    try:
        module = importlib.import_module(name)
    except ModuleNotFoundError as exc:
        if exc.name and name.startswith(exc.name):
            raise ValueError(f"no driver found at {driver!s}") from None
        raise
    return module, fresh


def _import_file(path: Path):
    """Import a single-file driver, keeping files that share a name apart."""
    name = path.stem
    known = sys.modules.get(name)
    if known is not None and not _is_loaded_from(known, path):
        # The plain name is taken by another file. Give this file a name of
        # its own, based on where it lives, so that both drivers can load.
        digest = hashlib.sha1(str(path.resolve()).encode()).hexdigest()[:8]
        name = f"{path.stem}_{digest}"
        known = sys.modules.get(name)
    if known is not None:
        return known, False
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[name]
        raise
    return module, True


ENTRY_POINT_GROUP = "zmart_controller.drivers"

# True once installed and remembered drivers have been asked to register.
_discovered = False


def discover_installed_drivers() -> None:
    """Plug in the remembered and the installed drivers, once.

    Remembered drivers are those saved by :func:`register_driver`. An
    installed package announces itself with one line in its ``pyproject.toml``::

        [project.entry-points."zmart_controller.drivers"]
        acme = "zmart_drivers.acme:register"

    A driver that fails to load is logged and skipped, so one broken driver
    never hides the others.
    """
    global _discovered
    if _discovered:
        return
    _discovered = True
    for entry in remembered_drivers():
        try:
            register_driver(entry, remember=False)
        except Exception:
            logger.exception("remembered driver %r could not be loaded; skipping it", entry)
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
    return [copy.deepcopy(entry["connection"]) for _key, entry in sorted(REGISTRY.items())]


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
