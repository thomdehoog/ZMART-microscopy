"""The registry: where drivers plug in.

A driver registers a table of functions, one per command, under a
``connection`` dict. Three keys in that dict name the instrument: ``vendor``,
``microscope`` and ``api``. Any other keys are the driver's own, and go to its
``connect`` unchanged.

The registry checks only that a driver fits: every required function is
there, and the three identity keys are present. Everything else is the
driver's job.

A driver is a folder with a ``zmart.json`` naming its instruments and a
module holding its functions. :func:`register_driver` reads the file, checks
it, picks the functions by name and registers each instrument. It remembers
the driver in this computer's configuration folder, so later sessions plug it
in by themselves. A driver installed as a package can instead announce itself
through an entry point; see :func:`discover_installed_drivers`.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import copy
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


# The folder with the driver's controller-facing functions, inside a driver.
PLUGIN_FOLDER = "zmart_controller"


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


CONTRACT = 1
MANIFEST = "zmart.json"


def register_driver(driver: str | Path, *, remember: bool = True) -> list[dict[str, Any]]:
    """Plug a driver in, and return the instruments it provides.

    ``driver`` is the driver's folder, or the name of an installed module.
    The controller looks there for ``zmart_controller/zmart.json`` (or
    ``zmart.json`` directly). That file names the instruments; the functions
    are found by name in the module next to it. See ``docs/driver.md`` for
    the contract.

    Run this once per driver on each microscope computer. The driver is
    remembered in this computer's configuration folder, and every later
    session plugs it in by itself when :func:`get_instruments` runs. Pass
    ``remember=False`` to plug it in for this session only. Calling it twice
    is harmless.

    Raises ``ValueError`` when nothing is found, the file is wrong, or a
    function is missing, and says which.
    """
    plugin_dir, module = _locate_plugin(driver)
    manifest = _read_manifest(plugin_dir / MANIFEST)
    if module is None:
        module = _import_plugin(plugin_dir)
    ops = _collect_ops(module, plugin_dir)
    added = []
    for instrument in manifest["instruments"]:
        register(instrument, ops=ops)
        added.append(copy.deepcopy(instrument))
    if remember:
        key = _driver_key(driver)
        entries = remembered_drivers()
        if key not in entries:
            _save_remembered(entries + [key])
    return added


def _locate_plugin(driver: str | Path):
    """Find the folder holding ``zmart.json``; import first if given a module name."""
    path = Path(driver)
    if path.is_dir():
        for candidate in (path / PLUGIN_FOLDER, path):
            if (candidate / MANIFEST).is_file():
                return candidate, None
        raise ValueError(f"no {PLUGIN_FOLDER}/{MANIFEST} found under {path}")
    if path.exists():
        raise ValueError(f"{path} is a file; give the driver's folder instead")
    try:
        module = importlib.import_module(str(driver))
    except ModuleNotFoundError as exc:
        if exc.name and str(driver).startswith(exc.name):
            raise ValueError(f"no driver found at {driver!s}") from None
        raise
    folder = Path(module.__file__).parent
    if (folder / MANIFEST).is_file():
        return folder, module
    if (folder / PLUGIN_FOLDER / MANIFEST).is_file():
        return folder / PLUGIN_FOLDER, importlib.import_module(f"{driver}.{PLUGIN_FOLDER}")
    raise ValueError(f"module {driver!s} has no {PLUGIN_FOLDER}/{MANIFEST}")


def _read_manifest(path: Path) -> dict[str, Any]:
    """Read and check a driver's ``zmart.json``."""
    try:
        manifest = json.loads(path.read_text())
    except ValueError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from None
    if not isinstance(manifest, dict) or manifest.get("contract") != CONTRACT:
        raise ValueError(
            f'{path} must say "contract": {CONTRACT}; this controller knows no other version'
        )
    instruments = manifest.get("instruments")
    if not isinstance(instruments, list) or not instruments:
        raise ValueError(f'{path} must list at least one instrument under "instruments"')
    for instrument in instruments:
        if not isinstance(instrument, dict):
            raise ValueError(f"{path}: every instrument must be an object")
        _identity(instrument)  # raises ValueError naming any missing identity key
    return manifest


def _import_plugin(plugin_dir: Path):
    """Import the plugin folder under a name of its own, so two drivers never clash."""
    name = f"zmart_controller__{plugin_dir.parent.name}_{abs(hash(str(plugin_dir.resolve()))):x}"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, plugin_dir / "__init__.py", submodule_search_locations=[str(plugin_dir)]
    )
    if spec is None:
        raise ValueError(f"{plugin_dir} has no __init__.py beside its {MANIFEST}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[name]
        raise
    return module


def _collect_ops(module, plugin_dir: Path) -> dict[str, Any]:
    """Pick the driver's functions out of its module, by name."""
    ops = {}
    missing = []
    for name in OPS + ("disconnect",):
        func = getattr(module, name, None)
        if callable(func):
            ops[name] = func
        elif name != "disconnect":
            missing.append(name)
    if missing:
        raise ValueError(f"{plugin_dir} is missing these functions: {missing}")
    return ops


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
            register_driver(entry_point.value.split(":")[0], remember=False)
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
