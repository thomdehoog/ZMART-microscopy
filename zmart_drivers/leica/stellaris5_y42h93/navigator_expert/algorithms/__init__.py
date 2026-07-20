"""Navigator Expert image-analysis helpers with no LAS X or hardware dependency.

Driver-local (this driver owns its own copy so it is self-contained and free to
diverge from other microscopes' analysis). Two concerns, two modules:

- ``registration``: image-to-image alignment, voting, and D4 sign-convention fitting.
- ``focus``: Brenner gradient and sub-pixel peak finding for Z-stack focus measurement.

Importing from this package is safe offline; every function operates on numpy arrays.
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
    register_phase,
    register_voting,
)

__all__ = [
    # registration — sign convention
    "D4_ELEMENTS",
    "D4_RESIDUAL_MAX",
    "classify_d4",
    # registration — methods + voting
    "VOTING_METHODS",
    "VOTING_MIN_AGREE",
    "VOTING_TOLERANCE_UM",
    "MASK_PCT_DEFAULT",
    "pcc",
    "masked_pcc",
    "ncc",
    "orb_ransac",
    "register_voting",
    "register_phase",
    # registration — pair preparation for cross-magnification voting
    "prepare_pair",
    # focus
    "brenner",
    "brenner_focus",
    "subpixel_peak",
]
