"""What the bridge keeps between two requests: the open session, the run folder, and what was captured.

One module owns every fact the bridge's general part keeps between two
requests, so that the other modules read and write the same thing and none
of them has to know which thread last touched it. Each is a plain module
attribute and is read through this module (``state.session``, never a
copied name), so a value one module sets is the value the next one sees.

``records`` keeps every capture by the workflow's own name for its
acquisition (overview, focussing, targets, ...), which no driver reports:
the bridge stamps it on each record from what it asked for. How far a
workflow's own runs have got is that workflow's, in its Python half.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import threading
from pathlib import Path

from ..microscope.instrument import Instrument

#: The one lock that guards the instrument. Every route that touches the
#: session takes it first, so two requests can never move the stage at once.
the_instruments_turn = threading.Lock()

#: The open microscope, or None: the controller's session, read through
#: :class:`Instrument` so every answer is a report. One at a time: the window
#: is one operator at one instrument.
session: Instrument | None = None

#: How the driver was chosen; filled by connect, shown by /api/connect replies.
context: dict = {}

#: The stage's last known position, in ``get_xyz``'s shape: what the page's
#: clock is answered with while a run holds the instrument's turn.
last_xyz: dict | None = None

#: This session's run folder: ``<output root>/<experiment>_<hash6>``, made at
#: connect under the name the workflow gave (``target-acquisition`` for
#: Target acquisition). Everything a session captures goes under it, which is what
#: makes one run a run -- without it every scan piles into the same folder and
#: the second is indistinguishable from the first.
run: Path | None = None

#: Where runs go, when this bridge was started with somewhere to put them.
#: A driver that discovers its own (the Leica finds the root beside LAS X)
#: needs none of this; one that cannot has to be told, and the page has
#: nowhere to say it -- it connects with the entry the list offered.
output_root: str | None = None


def require_session() -> Instrument:
    """The open session, or a refusal that says what to do."""
    if session is None:
        raise RuntimeError("no session is open — connect first")
    return session


def the_run() -> Path:
    """This session's run folder, or a refusal that says what to do."""
    if run is None:
        raise RuntimeError("no run is open — connect first")
    return run


# --- what every run captured, and the pictures made from it ------------------
#
# How far a workflow's own runs have got (a scan, a focus map) is that
# run's ledger; see ``ledgers.py``.

#: What every scan captured, by the kind of scan. The kind -- ``acquisition_type``
#: throughout the bridge -- is the interface's own name for an acquisition
#: (overview, focussing, targets, ...), not part of the controller's contract:
#: the bridge stamps it on every record it keeps, from what it asked for, and
#: never reads it back from a driver. The overview's records are
#: what discovery reads and what its pictures are made from, and a targets
#: scan taken afterwards must not replace them -- it did, when there was one
#: list, and the overview's view filled with the targets' pictures.
records: dict[str, list] = {}

#: Copies drawn with a display, by (kind, label, the display as asked), in
#: the order they were last used and no more than ``pictures.DISPLAYED_KEPT``
#: of them; a scan start empties it, since the pixels behind a label may change.
displayed_pictures: dict[tuple, bytes] = {}

#: One view-builder at a time, and only when the scan has grown: every file
#: request used to rebuild the whole view, and two rebuilding at once
#: interleaved their writes into a corrupt note that failed every request
#: after it. ``view_built`` says how many records each kind's view was last
#: built from.
view_lock = threading.Lock()
view_built: dict[str, int] = {}
