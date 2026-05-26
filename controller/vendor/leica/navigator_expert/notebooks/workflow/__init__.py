# Compatibility shim. Workflow moved to:
# workflows/vendor/leica/navigator_expert/target_acquisition/workflow/
# sys.modules alias so old imports resolve to the canonical package.
import sys as _sys
from pathlib import Path as _Path

_TARGET_ACQ = _Path(__file__).resolve().parents[6] / "workflows" / "vendor" / "leica" / "navigator_expert" / "target_acquisition"

if str(_TARGET_ACQ) not in _sys.path:
    _sys.path.insert(0, str(_TARGET_ACQ))

import importlib as _il
_real = _il.import_module("workflow")
_sys.modules[__name__] = _real
