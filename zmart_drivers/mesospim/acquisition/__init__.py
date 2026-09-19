"""Acquisition: capture (snap / list) and save into the canonical layout."""

from .capture import acquire, build_acquisition, run_acquisition_list, snap
from .product import (
    AcquisitionMetadata,
    AcquisitionResult,
    ChannelMetadata,
    SavedAcquisition,
)
from .save import canonical_stem, data_dir, metadata_dir, save, state_dir, vendor_dir

__all__ = [
    "acquire",
    "snap",
    "run_acquisition_list",
    "build_acquisition",
    "save",
    "canonical_stem",
    "data_dir",
    "metadata_dir",
    "state_dir",
    "vendor_dir",
    "AcquisitionResult",
    "AcquisitionMetadata",
    "ChannelMetadata",
    "SavedAcquisition",
]
