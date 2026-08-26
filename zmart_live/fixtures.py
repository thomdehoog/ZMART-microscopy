"""Small live runs to test against, for anything that reads what we publish.

These four were written inside `zmart_live`'s own tests and grew a second set
of users: the viewer's gates, which need a *real* live run to open, watch and
measure. That worked while both lived in one repository and stops working the
moment they do not -- "install their test suite to run mine" is not a
dependency anyone should be asked to take.

So they live here, beside the code they exercise rather than beside the tests
that first needed them. Both sides import the same builder, which is the point:
a viewer testing against its own idea of a run would drift from what the
publisher actually writes, and the drift would be invisible until a real
acquisition found it.

Nothing here is a test. It is the smallest honest run: one overview profile,
one z plane, two positions, and pixels of a single value so a measurement can
say plainly what it saw.
"""
from __future__ import annotations

import numpy as np

from zmart_live.model import GridCell
from zmart_live.profiles import plan_the_writing

#: The camera frame these runs are written with. Large enough that a piece of
#: the picture is a piece rather than a rounding, small enough to write fast.
FRAME = 1152


def some_specimen(value: int = 1000) -> np.ndarray:
    """One position's pixels, all of one brightness.

    A flat value on purpose: a measurement that reports it has read the right
    thing can then say so with one number, and a window that lands anywhere
    else is wrong in a way nobody has to squint at.
    """
    return np.full((1, FRAME, FRAME), value, "uint16")


def a_live_run(folder, *, timepoints: int = 1, linked_view: str = "per_publish"):
    """A publisher writing two positions side by side, ready to be published to.

    ``linked_view`` defaults to ``"per_publish"`` because the gates that use
    this are largely about the linked view being true while a run is going,
    which is exactly the case that deferring it removes. A caller testing the
    deferral asks for ``"at_run_end"`` and gets the run a real acquisition has.
    """
    from zmart_live.coordinator import LivePublisher

    profile, _ = plan_the_writing("overview", frame=FRAME, z_planes=1,
                                  timepoints=timepoints)
    return LivePublisher(
        folder,
        profile,
        run_id="gateway-run",
        cells={GridCell(0, 0): "posA", GridCell(0, 1): "posB"},
        linked_view=linked_view,
    )


def prepare_without_publishing(run, position_id: str, value: int, *, moment: int = 0):
    """Every step of a publication except the commit that makes it visible.

    What it leaves behind is a run that is complete on disk and has not been
    announced -- the state a reader must refuse to show, and the one a test
    has to be able to build without spelling out four calls and letting them
    drift apart.
    """
    run.write_a_position(position_id, some_specimen(value), timepoint=moment)
    units = frozenset(run._committed_units()) | {(position_id, moment)}
    run.write_the_link_map(units)
    run.write_the_view()
    run.write_the_layout()
