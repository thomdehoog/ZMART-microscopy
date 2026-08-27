"""The operator's application: the shell, the parts, and the workflows.

Both languages live here, each file where its meaning puts it rather than
where its file extension does. ``framework/`` is the shell that runs a
workflow — the window the operator sees, in JavaScript, and the HTTP door onto
the controller, in Python. ``parts/`` is what a step reaches for: the canvas,
and the microscope. ``workflows/`` is one folder per workflow, and anything
belonging to a single step lives in that step's folder.

Below this sit the things the application is built on and does not own:
``zmart_controller`` (the vendor-neutral contract), ``zmart_drivers`` (the
instruments, mock included), and the storage and live packages.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""
