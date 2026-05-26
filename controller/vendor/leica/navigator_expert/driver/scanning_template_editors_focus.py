# Compatibility shim. Prefer navigator_expert.driver.experimental.lrp_edits.focus.
from .experimental.lrp_edits.focus import (  # noqa: F401
    STACK_MODES,
    lrp_set_stack_calculation_mode,
    lrp_verify_stack_calculation_mode,
    lrp_set_pinhole_airy,
    lrp_verify_pinhole_airy,
    lrp_set_autofocus_active,
    lrp_verify_autofocus_active,
)
