"""Publishing a live run so that the viewer and the analysis always agree.

While a smart experiment is running, two quite different readers are watching the
same folder. The operator has a viewer open and wants to see each position appear
as it is acquired. An analysis is working through the same positions counting
cells. Both are reading data that is still being written, and the whole risk of
that situation is that they see *different* things, or see something before it is
finished.

This package is the part that makes those two readers safe. Its rule is short:

    Nothing becomes visible until a whole position, or a whole timepoint added to
    an existing position, has finished being written and has been checked.

The reasoning, and the decisions that follow from it, are written out in
``docs/design/live-position-timepoint-publication-decisions.md``. The modules here
are that document turned into code.

Where to start reading
----------------------

:mod:`zmart_live.model` holds the shared vocabulary — what a region is, what a
tile's place in the mosaic is, what a published revision is. Everything else is
written in those terms, so it is the natural first file to read.

Nothing in this package talks to a microscope, and nothing in it draws anything.
It sits between the writer and the viewer, and its only job is to be certain
about what is finished.
"""

from .model import (
    AcquisitionProfile,
    Box,
    CommitEvent,
    FrozenMap,
    GridCell,
    Interval,
    LevelGeometry,
    MosaicComponent,
    OverlapBand,
    PositionPlacement,
    SceneLayoutRevision,
    ZmartLiveError,
)

__all__ = [
    "AcquisitionProfile",
    "Box",
    "CommitEvent",
    "FrozenMap",
    "GridCell",
    "Interval",
    "LevelGeometry",
    "MosaicComponent",
    "OverlapBand",
    "PositionPlacement",
    "SceneLayoutRevision",
    "ZmartLiveError",
]
