"""The microscope, in Python: the bridge's side of the seam where the instrument goes.

Its opposite number is the page's own ``microscope/`` folder, in JavaScript,
and the two mean the same thing on either side of the seam -- the code that
talks to the instrument, and nothing else. A browser cannot reach the
controller, so the page talks HTTP to the bridge; Python can, so this folder
holds what the bridge does with the controller's session: reading its answers
(``instrument.py``), and filing a captured focus stack and shifting its
height into the stage's frame (``focus_run.py``). What is done with the pixels once they are filed --
scoring a stack, finding objects -- is the analysis's, in ``../analysis/``.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""
