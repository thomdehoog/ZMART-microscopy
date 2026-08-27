"""What every test under `application/` needs on the path before it runs.

The tests live beside what they test — a part's tests in the part, a step's in
the step — so there is no one tests folder to hang this on. It hangs on the
application instead, which is the one thing they all belong to.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
# navigator_expert (and navigator_expert.calibration) needs its parent folder
# on the path; it is a driver, and drivers are found where they are installed
# rather than imported from the repository as packages.
_DRIVER_PARENT = _REPO_ROOT / "zmart_drivers" / "leica" / "stellaris5_y42h93"

for p in (str(_DRIVER_PARENT), str(_REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

# Pre-loaded so its package identity is established before anything else
# triggers the same import.
import navigator_expert  # noqa: E402,F401
