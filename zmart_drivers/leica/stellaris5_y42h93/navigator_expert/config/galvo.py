"""Galvo pan physics for this scope.

How far a galvo "pan" value moves the sample, as a function of the
objective's base field of view. Used by ``commands.move_galvo_to_pixel``.
"""

# ---------------------------------------------------------------------------
# Galvo pan calibration.
# ---------------------------------------------------------------------------
# The physics
# ------------
# A pan value is a dimensionless angular fraction of the galvo's range.
# Sample displacement per unit of pan = (galvo angle) x (objective focal
# length). Base FOV is also proportional to focal length. So the
# displacement-per-unit-pan (PAN_SCALE) scales linearly with base FOV.
# Writing it in physical form:
#
#     pan_scale_um = base_fov_um * GALVO_FIELD_FRACTION / PAN_LIMIT
#
# where each factor has a concrete meaning:
#
#  PAN_LIMIT (0.00775) — max software-enforced pan value per axis
#                        (hard limit in LAS X; known exactly).
#
#  GALVO_FIELD_FRACTION (0.667) — fraction of base FOV that a maximum
#                                 pan shifts the sample by. This is a
#                                 scope-level constant (galvo mirror
#                                 mechanical range x scan-lens focal
#                                 length), independent of objective.
#                                 Measured on ZMB STELLARIS 8
#                                 (2026-04-23) at 0.667 +- 0.001 across
#                                 10x/20x/40x objectives; matches 2/3
#                                 to 3 decimal places.
#
# Equivalent empirical shortcut:
#     pan_scale_um = base_fov_um * 86.06  (= GALVO_FIELD_FRACTION / PAN_LIMIT)
#
# Callers should use the helper below rather than re-deriving:
#
#     base_fov_um = get_base_fov(client, job)[0] * 1e6
#     pan_scale_um = base_fov_um * GALVO_FIELD_FRACTION / PAN_LIMIT
#
# Re-measure GALVO_FIELD_FRACTION on each new
# instrument — GALVO_FIELD_FRACTION is scope-specific but fixed per
# scope.
#
# WARNING: the committed value was measured on the ZMB STELLARIS 8 while
# this driver targets the STELLARIS 5 (y42h93). Unlike the orientation, which
# is measured per microscope and saved to a config, this constant is not
# stored per machine, so a per-scope error can only be corrected by editing it
# here (config/galvo.py) — verify it before trusting galvo-pan targeting on a new instrument.
PAN_LIMIT = 0.00775  # max pan value per axis (software limit)
GALVO_FIELD_FRACTION = 0.667  # sample shift at max pan, as fraction of base FOV


def pan_scale_um_from_base_fov(base_fov_um):
    """um of sample displacement per unit of pan, for an objective
    with the given base FOV (FOV at zoom 1, in um).

    See module header for the physics: at max pan (``PAN_LIMIT``) the
    galvo shifts the sample by ``GALVO_FIELD_FRACTION`` of base FOV;
    for any smaller pan value the displacement scales linearly.

    Args:
        base_fov_um: Objective's base FOV in um (from ``get_base_fov``).

    Returns:
        um displacement per unit of pan.
    """
    return base_fov_um * GALVO_FIELD_FRACTION / PAN_LIMIT
