"""Environment context header for pytest runs (triage aid; never fatal)."""

from __future__ import annotations

import platform
import sys
from importlib.util import find_spec


def _version(mod: str) -> str:
    try:
        import importlib.metadata as md

        return md.version(mod)
    except Exception:
        return "not installed" if find_spec(mod) is None else "installed"


def header_lines() -> list[str]:
    """Return context lines: OS, Python, and ZEN API dependency availability."""
    return [
        f"zenapi driver | {platform.system()} {platform.release()} | "
        f"Python {sys.version.split()[0]}",
        f"zenapi deps  | zen_api={_version('zen_api')} "
        f"grpclib={_version('grpclib')} numpy={_version('numpy')}",
        "zenapi mode  | offline (fake ZEN API; no gateway). "
        "Hardware tests are marked @pytest.mark.hardware and excluded by default.",
    ]
