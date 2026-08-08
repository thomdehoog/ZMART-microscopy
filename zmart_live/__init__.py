"""Publishing a run's positions and moments while the microscope is still going.

This holds the machinery described in
``docs/design/live-position-timepoint-publication-decisions.md``: how a run
decides to store itself, how a finished position or moment becomes visible all
at once rather than piece by piece, and how the viewer and any analysis come to
agree about which tile owns which piece of specimen.

:mod:`zmart_live.model` is the vocabulary the rest of it speaks in.
:mod:`zmart_live.profiles` chooses how one kind of acquisition is written.
"""

from .model import (
    AcquisitionProfile,
    Box,
    CommitEvent,
    GridCell,
    Interval,
    LevelGeometry,
    MosaicComponent,
    OverlapBand,
    PositionPlacement,
    SceneLayoutRevision,
    ZmartLiveError,
)
from .profiles import DEFAULTS, AcquisitionDefaults, Geometry, plan_the_writing

__all__ = [
    "DEFAULTS",
    "AcquisitionDefaults",
    "AcquisitionProfile",
    "Box",
    "CommitEvent",
    "Geometry",
    "GridCell",
    "Interval",
    "LevelGeometry",
    "MosaicComponent",
    "OverlapBand",
    "PositionPlacement",
    "SceneLayoutRevision",
    "ZmartLiveError",
    "plan_the_writing",
]
