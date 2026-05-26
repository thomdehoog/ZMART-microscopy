# Compatibility shim. Prefer navigator_expert.driver.templates.parsers.
# sys.modules alias so monkey-patching and underscore imports work.
import sys as _sys
from .templates import parsers as _canonical
_sys.modules[__name__] = _canonical
