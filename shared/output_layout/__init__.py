"""Lab-wide output naming convention.

Vendor-neutral schema for zmart-microscopy acquisition outputs. Drivers
and workflows import from here; the schema does not depend on any
vendor's API. Vendor-specific extraction logic (e.g. parsing source
filenames into canonical Naming slots) lives in each driver.

Canonical spec: auto-memory `smart_microscopy_smart_folder_structure.md`.

Import convention: `from shared.output_layout import Naming, ...`
Requires the repository root on sys.path.
"""

from .naming import (
    EPOCH,
    MAX_ACQUISITION_TYPE_LEN,
    MAX_EXPERIMENT_LEN,
    MAX_POSITION_LABEL_LEN,
    LayoutPlan,
    Naming,
    acquisition_data_dir,
    acquisition_dir,
    acquisition_metadata_dir,
    build_image_name,
    build_layout,
    build_position_analysis_name,
    build_xml_name,
    parse_image_name,
    run_hash,
)

__all__ = [
    "EPOCH",
    "MAX_ACQUISITION_TYPE_LEN",
    "MAX_EXPERIMENT_LEN",
    "MAX_POSITION_LABEL_LEN",
    "LayoutPlan",
    "Naming",
    "acquisition_data_dir",
    "acquisition_dir",
    "acquisition_metadata_dir",
    "build_image_name",
    "build_layout",
    "build_position_analysis_name",
    "build_xml_name",
    "parse_image_name",
    "run_hash",
]
