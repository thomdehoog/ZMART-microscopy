"""Install ZMART on this computer, check it end to end, and say whether it is ready.

Run it from the folder of ZMART Microscopy, with the Python of conda's base
environment (in a Miniforge Prompt on Windows):

    python setup_zmart.py

It asks whether you write code and which microscope this computer is for, and
then does everything else: the ZMART environment, the blocks at the releases
in ``releases.toml``, the microscope's driver, the analysis environments, the
start files with an icon on the desktop, and the checks, end to end. It ends
by saying either "ZMART is ready", or which parts did not work and which file
to give Claude Code so it can find out why
(``.claude/agents/zmart-install-doctor.md``).

``python setup_zmart.py --help`` lists the options; ``--check`` only checks.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

import sys

if sys.version_info < (3, 9):
    sys.exit("setup_zmart.py needs Python 3.9 or newer; run it from conda's base environment "
             "(a Miniforge Prompt), whose Python is new enough.")

from zmart_setup.main import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
