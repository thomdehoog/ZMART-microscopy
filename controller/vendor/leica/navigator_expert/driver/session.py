# Compatibility shim. Prefer navigator_expert.driver.api.session.
from .api.session import (  # noqa: F401
    connect_python_client,
    require_canonical_scan_orientation,
)
