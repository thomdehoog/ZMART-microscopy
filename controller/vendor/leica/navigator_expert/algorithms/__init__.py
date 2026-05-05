"""Pure image-analysis helpers — no LAS X, no hardware.

Two concerns, two modules:

- ``registration`` — image-to-image alignment (4 methods + voting),
  D4 sign-convention fit. Used by the calibration sign-convention
  phase, the calibration parcentric-shift phase, the registration
  benchmark, and any future cookbook refinement step.

- ``focus`` — Brenner gradient + sub-pixel peak finder for Z-stack
  focus measurement. Used by the calibration parfocal phase.

Importing from this package is safe offline — every function operates
on numpy arrays.
"""

from .focus import (
    brenner,
    brenner_focus,
    subpixel_peak,
)
from .registration import (
    D4_ELEMENTS,
    D4_RESIDUAL_MAX,
    MASK_PCT_DEFAULT,
    VOTING_METHODS,
    VOTING_MIN_AGREE,
    VOTING_TOLERANCE_UM,
    classify_d4,
    masked_pcc,
    ncc,
    orb_ransac,
    pcc,
    prepare_pair,
    register_voting,
    register_phase,
)

__all__ = [
    # registration — sign convention
    "D4_ELEMENTS", "D4_RESIDUAL_MAX", "classify_d4",
    # registration — methods + voting
    "VOTING_METHODS", "VOTING_MIN_AGREE", "VOTING_TOLERANCE_UM",
    "MASK_PCT_DEFAULT",
    "pcc", "masked_pcc", "ncc", "orb_ransac",
    "register_voting", "register_phase",
    # registration — pair preparation for cross-magnification voting
    "prepare_pair",
    # focus
    "brenner", "brenner_focus", "subpixel_peak",
]
