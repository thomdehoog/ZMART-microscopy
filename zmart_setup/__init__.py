"""Setting up ZMART on a computer: the parts of ``setup_zmart.py``.

``setup_zmart.py``, in the top folder of ZMART Microscopy, is the one thing a
person runs to install ZMART. It asks two questions (do you write code, and
which microscope is this computer for), then installs everything, checks
everything, and says plainly whether it worked. The work is split over the
modules here, one per kind of job:

- ``record``: what happened, step by step, in the terminal, in a log file and
  in a report that the install doctor (a Claude Code agent) reads.
- ``shell``: running a command and keeping what it printed.
- ``conda``: finding conda, and the environments it has.
- ``releases``: which versions of the blocks to install (``releases.toml``).
- ``blocks``: the ZMART environment and the five blocks in it.
- ``analysis``: the analysis environments, made from the pipelines' own files.
- ``starting``: the start files and the icons on the desktop.
- ``checks``: the checks, from "is it installed" to "does it work end to end".
- ``main``: the questions, and the order of the work.

Only Python's standard library is used, so the installer runs from any conda
base environment, before anything else is installed.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""
