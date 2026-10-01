"""Part 6 of the driver anatomy: data handling.

Acquiring an image is a set command; data handling starts once it is
confirmed. It finds the vendor's file, waits until it is complete, turns the
picture so that it lines up with the stage, writes it as OME-TIFF or
OME-Zarr with its metadata, keeps the log of the commands behind it, and
reports where everything was saved.
"""

from .collect import wait_for_file
from .command_log import CommandLog
from .orient import align_to_stage
from .save import FORMATS, save_acquisition

__all__ = ["FORMATS", "CommandLog", "align_to_stage", "save_acquisition", "wait_for_file"]
