"""Fit a focus surface z(x, y) from measured autofocus points -- pure, no driver.

The controller-only focus step measures frame-z at operator-chosen (x, y) points
(via ``run_procedure('autofocus')``); this module turns those measurements into a
surface the overview/target steps query for a per-position z. Model by geometry:

    flat z (< 0.1 um range) or 1 point   -> constant (mean z)
    >= 4 non-collinear points            -> thin-plate spline (captures curvature)
    otherwise                            -> least-squares plane
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

FLAT_TOLERANCE_UM = 0.1
SPLINE_SMOOTHING = 0.1


@dataclass(frozen=True)
class FocusSurface:
    """A fitted z(x, y) surface in frame micrometres."""

    model: str
    coeffs: tuple[float, float, float] | None
    origin_xy_um: tuple[float, float]
    measured: list[dict]
    scale_um: float = 1.0
    _interpolator: Any = field(default=None, repr=False, compare=False)

    def z_at(self, x, y):
        """Interpolated frame z at frame (x, y) -- scalar or array, matching input."""
        x0, y0 = self.origin_xy_um
        if self.model == "spline":
            xa, ya = np.broadcast_arrays(np.asarray(x, float), np.asarray(y, float))
            xy = np.column_stack(
                [(xa.ravel() - x0) / self.scale_um, (ya.ravel() - y0) / self.scale_um]
            )
            z = self._interpolator(xy).reshape(xa.shape)
            return float(z) if z.ndim == 0 else z
        c0, c1, c2 = self.coeffs
        return c0 * (x - x0) + c1 * (y - y0) + c2


def fit_focus_surface(measured: list[dict]) -> FocusSurface:
    """Fit a :class:`FocusSurface` from ``[{"x_um","y_um","z_um"}, ...]``."""
    if not measured:
        raise ValueError("need at least one focus measurement")
    xs = np.array([m["x_um"] for m in measured], dtype=float)
    ys = np.array([m["y_um"] for m in measured], dtype=float)
    zs = np.array([m["z_um"] for m in measured], dtype=float)
    x0, y0 = float(xs.mean()), float(ys.mean())
    xc, yc = xs - x0, ys - y0

    if float(zs.max() - zs.min()) < FLAT_TOLERANCE_UM:
        return FocusSurface("constant", (0.0, 0.0, float(zs.mean())), (x0, y0), list(measured))

    if len(measured) >= 4 and np.linalg.matrix_rank(np.column_stack([xc, yc])) >= 2:
        from scipy.interpolate import RBFInterpolator

        scale = float(max(np.ptp(xc), np.ptp(yc))) or 1.0
        interpolator = RBFInterpolator(
            np.column_stack([xc / scale, yc / scale]),
            zs,
            kernel="thin_plate_spline",
            smoothing=SPLINE_SMOOTHING,
        )
        return FocusSurface(
            "spline", None, (x0, y0), list(measured), scale_um=scale, _interpolator=interpolator
        )

    design = np.column_stack([xc, yc, np.ones(len(measured))])
    coeffs, *_ = np.linalg.lstsq(design, zs, rcond=None)
    return FocusSurface(
        "plane", (float(coeffs[0]), float(coeffs[1]), float(coeffs[2])), (x0, y0), list(measured)
    )
