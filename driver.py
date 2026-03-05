"""
Backwards-compatible shim.
==========================
Imports everything from the lasx package so that existing code using
``import driver as drv`` continues to work unchanged.

New code should import from the package directly::

    from lasx import set_zoom, get_job_settings
    from lasx.core import confirm_and_fire
"""

from lasx import *                  # noqa: F401,F403
from lasx import __version__        # noqa: F401
from lasx import log                # noqa: F401
