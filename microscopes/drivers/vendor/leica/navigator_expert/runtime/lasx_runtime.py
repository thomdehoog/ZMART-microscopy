"""Load the Leica LAS X CAM API runtime from the licensed LAS X install.

The CAM API assemblies ship with LAS X under the NavigatorExpert add-in
directory, so the repo carries no Leica binaries and no Leica files are copied
into the Python env. ``pythonnet`` is still required as the Python/.NET bridge.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

REQUIRED_DLLS = (
    "PYLICamApiConnector.dll",
    "LMS.CAM.CORE.dll",
    "LMS.CAM.SHARED.OBJECTS.dll",
    "Newtonsoft.Json.dll",
)


def _runtime_root() -> Path:
    """Return the configured LAS X CAM API runtime root."""
    from . import profiles

    return Path(profiles.LASX_API.runtime_root)


def _missing_dlls(root: Path) -> list[str]:
    """Return required DLL names missing from ``root``."""
    return [name for name in REQUIRED_DLLS if not (root / name).exists()]


def load_lasx_api_runtime() -> Any:
    """Load LAS X CAM API assemblies and return a module-like connector.

    The returned object intentionally mirrors the small connector surface the
    driver uses: ``LasxApiClientPyModel``, ``__version__``, ``__file__``, and
    ``base_path``.
    """
    root = _runtime_root()
    missing = _missing_dlls(root)
    if missing:
        raise RuntimeError(
            f"LAS X CAM API runtime not found at {root} "
            f"(missing {', '.join(missing)}). Is LAS X installed?"
        )

    # Keep this import after the filesystem check so the missing-runtime path
    # stays testable on machines without LAS X or pythonnet installed.
    import clr  # type: ignore[import-not-found]  # noqa: F401,PLC0415
    import System  # type: ignore[import-not-found]  # noqa: PLC0415

    dll_paths = [root / name for name in REQUIRED_DLLS]
    refs = [System.Reflection.Assembly.LoadFile(str(path)) for path in dll_paths]
    model_type = refs[0].GetType("PYLICamApiConnector.LasxApiClientPyModel")
    if model_type is None:
        raise RuntimeError(f"PYLICamApiConnector.LasxApiClientPyModel not found in {dll_paths[0]}")
    version = refs[0].GetName().Version.ToString()
    model = System.Activator.CreateInstance(model_type)
    return SimpleNamespace(
        LasxApiClientPyModel=model,
        __version__=version,
        __file__=str(dll_paths[0]),
        base_path=str(root),
    )
