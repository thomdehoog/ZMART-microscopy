# Compatibility shim. Prefer navigator_expert.driver.templates.parsers.
from .templates.parsers import *  # noqa: F401,F403
from .templates.parsers import (  # noqa: F401 — underscore names for internal callers
    _tile_size_from_image_size_str,
)
