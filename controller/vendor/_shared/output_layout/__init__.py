"""Lab-wide output naming convention.

Vendor-neutral schema for smart-microscopy acquisition outputs. Drivers
(Leica navigator_expert, future Zeiss/Nikon) and workflows import from
here. Canonical spec: auto-memory `smart_microscopy_smart_folder_structure.md`.

Import convention: `from _shared.output_layout import Naming, ...`
Requires `controller/vendor/` on sys.path.
"""

from .naming import (
    EPOCH,
    MAX_ACQUISITION_TYPE_LEN,
    MAX_EXPERIMENT_LEN,
    LayoutPlan,
    Naming,
    build_image_name,
    build_layout,
    build_xml_name,
    parse_image_name,
    run_hash,
)

__all__ = [
    "EPOCH",
    "MAX_ACQUISITION_TYPE_LEN",
    "MAX_EXPERIMENT_LEN",
    "LayoutPlan",
    "Naming",
    "build_image_name",
    "build_layout",
    "build_xml_name",
    "parse_image_name",
    "run_hash",
]
