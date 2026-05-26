# Compatibility shim. Prefer navigator_expert.driver.motion.stage.
# sys.modules alias so patch.object targets the real module globals.
import sys as _sys
from .motion import stage as _canonical
_sys.modules[__name__] = _canonical
