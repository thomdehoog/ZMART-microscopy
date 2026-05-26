# Compatibility shim. Prefer navigator_expert.driver.experimental.lrp_edits.scan.
# sys.modules alias so monkey-patching targets the real module globals.
import sys as _sys
from .experimental.lrp_edits import scan as _canonical
_sys.modules[__name__] = _canonical
