"""Acquisition: capture (snap / list) and save into the canonical layout."""

from .capture import acquire, build_acquisition, run_acquisition_list, snap
from .product import (
    AcquisitionMetadata,
    AcquisitionResult,
    ChannelMetadata,
    SavedAcquisition,
)
from .save import save

__all__ = [
    "acquire",
    "snap",
    "run_acquisition_list",
    "build_acquisition",
    "save",
    "AcquisitionResult",
    "AcquisitionMetadata",
    "ChannelMetadata",
    "SavedAcquisition",
]
