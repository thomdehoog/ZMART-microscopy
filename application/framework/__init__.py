"""The shell: what runs a workflow, and knows none in particular.

Its JavaScript half is ``window/`` and ``rules/`` — the rail, the panels, the
step ordering. Its Python half is the bridge: the HTTP door the page speaks
through, because a browser cannot import the controller.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""
