# Compatibility shim. Prefer navigator_expert.driver.experimental.lrp_edits.z.
# sys.modules alias so monkey-patching targets the real module globals.
import sys as _sys
from .experimental.lrp_edits import z as _canonical
_sys.modules[__name__] = _canonical
