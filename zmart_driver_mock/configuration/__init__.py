"""Part 7 of the driver anatomy: configuration.

Everything the person at the microscope sets up once and saves, loaded every
time the driver connects:

- ``machine_description``: the fixed facts about this instrument, such as its
  serial number, so a configuration is never used on the wrong microscope.
- ``image_stage_registration``: which way the camera sits on the stage, and
  the size of a pixel for each objective.
- ``origin``: the point that reads as (0, 0, 0).
- ``limits``: how far the stage may travel, and the allowed range of each
  setting.
- ``optical_calibration``: how far each objective's view is shifted from
  objective 1.

Each item has shipped defaults in ``defaults/``, a check that refuses a
malformed file, and a saved copy in the computer's ZMART configuration
folder. The arithmetic between stage and user coordinates lives in
:mod:`.coordinates`.
"""

from .coordinates import raw_from_user, sample_point, user_from_raw, user_range
from .store import ITEMS, Configuration, load_configuration, save, saved_path

__all__ = [
    "ITEMS",
    "Configuration",
    "load_configuration",
    "raw_from_user",
    "sample_point",
    "save",
    "saved_path",
    "user_from_raw",
    "user_range",
]
