"""The microscope, in Python: the procedures that drive it.

Its opposite number is the page's own ``microscope/`` folder, in JavaScript,
and the two mean the same thing on either side of the seam — the code that
talks to the instrument, and nothing else. A browser cannot reach the
controller, so the page's talks HTTP to the bridge; Python can, so this one
holds :class:`~zmart_controller.layer.Session` calls directly.

Everything here obeys one rule: **nothing but the standard library and the
controller.** The operator page's bridge imports these, and the bridge is
plain Python on purpose — that is what lets it run on a microscope PC with
nothing installed on it. The workflow package next door imports tifffile and
matplotlib and is therefore out of the bridge's reach; a procedure written up
there has to be copied to be used here, and a procedure copied is a procedure
that will differ. That is not a hypothetical: it is where every focus map the
page ever ran came back a column of zeros.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""
