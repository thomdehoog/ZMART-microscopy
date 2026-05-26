"""Pytest fixtures + import-path setup for navigator_expert tests.

Two jobs:

1. Add the leica vendor dir to ``sys.path`` so tests can do
   ``import navigator_expert.driver as drv``.

2. Install a back-compat alias so the legacy ``import lasx.<submodule>``
   form (used throughout the existing test suite) still resolves to the
   canonical ``navigator_expert.driver.api.<submodule>``.

The alias is a temporary bridge while the test suite is migrated. It
should be removed once every test file uses the ``navigator_expert``
name directly.
"""

import importlib
import sys
from pathlib import Path

# Add vendor/leica/ to sys.path so `import navigator_expert.driver` works
# regardless of where pytest is invoked from.
_VENDOR_LEICA = Path(__file__).resolve().parents[2]
if str(_VENDOR_LEICA) not in sys.path:
    sys.path.insert(0, str(_VENDOR_LEICA))

# Add vendor/ to sys.path so `from _shared.output_layout import ...` resolves.
_VENDOR = Path(__file__).resolve().parents[3]
if str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))

# Add repo root to sys.path so `from algorithms import ...` resolves.
_REPO_ROOT = Path(__file__).resolve().parents[5]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Add target_acquisition dir so `from workflow.focus import ...` resolves.
_TARGET_ACQ = _REPO_ROOT / "workflows" / "vendor" / "leica" / "navigator_expert" / "target_acquisition"
if str(_TARGET_ACQ) not in sys.path:
    sys.path.insert(0, str(_TARGET_ACQ))

# Back-compat alias: tests written before the rename do
# ``import lasx.core``, ``import lasx.errors``, etc. Map the driver
# facade and each API submodule under the ``lasx`` namespace via
# sys.modules so unittest.mock.patch targets the canonical module.
import navigator_expert.driver as _drv  # noqa: E402

sys.modules.setdefault("lasx", _drv)

_API_SUBMODULES = (
    "commands", "confirmations", "core", "errors", "prechecks",
    "profiles", "readers", "settings", "utils",
)
_lasx_pkg = sys.modules["lasx"]
for _sub in _API_SUBMODULES:
    try:
        _mod = importlib.import_module(f"navigator_expert.driver.api.{_sub}")
    except ImportError:
        continue
    sys.modules[f"lasx.{_sub}"] = _mod
    setattr(_lasx_pkg, _sub, _mod)
