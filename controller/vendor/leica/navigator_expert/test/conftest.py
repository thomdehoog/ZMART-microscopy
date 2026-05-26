"""Pytest fixtures + import-path setup for navigator_expert tests.

Two jobs:

1. Add the leica vendor dir to ``sys.path`` so tests can do
   ``import navigator_expert.driver as drv``.

2. Install a back-compat alias so the legacy ``import lasx.<submodule>``
   form (used throughout the existing test suite) still resolves to the
   renamed ``navigator_expert.driver.<submodule>``.

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

# Back-compat alias: tests written before the rename do
# ``import lasx.core``, ``import lasx.errors``, etc. Map every driver
# submodule under the ``lasx`` namespace via sys.modules.
import navigator_expert.driver as _drv  # noqa: E402

sys.modules.setdefault("lasx", _drv)

_DRIVER_SUBMODULES = (
    "alignment", "commands", "confirmations", "core", "errors",
    "calibration", "file_confirmation", "limits", "objective_offsets",
    "ome_tiff", "prechecks", "profiles", "readers", "registration",
    "scanning_template_editors", "scanning_template_editors_focus",
    "scanning_template_editors_roi", "scanning_template_editors_scan",
    "scanning_template_editors_z", "scanning_template_parsers",
    "scanning_template_synthesis", "scanning_templates", "settings",
    "stage_config", "stage_motion", "utils",
)
for _sub in _DRIVER_SUBMODULES:
    try:
        _mod = importlib.import_module(f"navigator_expert.driver.{_sub}")
    except ImportError:
        continue
    sys.modules.setdefault(f"lasx.{_sub}", _mod)
