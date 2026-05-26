# Compatibility shim. Prefer navigator_expert.driver.output.acquisition.
# sys.modules alias so patch.object targets the real module globals.
import sys as _sys
from .output import acquisition as _canonical
_sys.modules[__name__] = _canonical
