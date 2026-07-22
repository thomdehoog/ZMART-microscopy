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

# How far beyond the measured z range a queried focus is allowed to wander.
# Outside the region where focus was actually measured, both the plane and
# (especially) the thin-plate spline can extrapolate to a z far from anything
# real — a thin-plate spline grows without bound away from its points. A tile
# that lands outside the measured footprint therefore gets its focus CLAMPED to
# the measured range plus this margin, so a stray extrapolation can never drive
# the objective to an extreme z. The margin also grows with the measured
# variation (see :func:`fit_focus_surface`), so a genuinely tilted sample still
# gets sensible focus a little past its measured edge.
EXTRAPOLATION_MARGIN_UM = 10.0


@dataclass(frozen=True)
class FocusSurface:
    """A fitted z(x, y) surface in frame micrometres."""

    model: str
    coeffs: tuple[float, float, float] | None
    origin_xy_um: tuple[float, float]
    measured: list[dict]
    scale_um: float = 1.0
    # The safe focus range: queries are clamped here so an extrapolated z
    # outside the measured region can never reach the objective unbounded.
    z_bounds_um: tuple[float, float] | None = None
    _interpolator: Any = field(default=None, repr=False, compare=False)

    def z_at(self, x, y):
        """Interpolated frame z at frame (x, y) -- scalar or array, matching input.

        The result is clamped to :attr:`z_bounds_um` (the measured z range plus
        a margin) so a position outside the measured focus footprint cannot be
        driven to a wild extrapolated z. Within the measured region the clamp
        never bites; only a far-outside query is capped.
        """
        x0, y0 = self.origin_xy_um
        if self.model == "spline":
            xa, ya = np.broadcast_arrays(np.asarray(x, float), np.asarray(y, float))
            xy = np.column_stack(
                [(xa.ravel() - x0) / self.scale_um, (ya.ravel() - y0) / self.scale_um]
            )
            z = self._interpolator(xy).reshape(xa.shape)
            z = self._clamp(z)
            return float(z) if z.ndim == 0 else z
        c0, c1, c2 = self.coeffs
        return self._clamp(c0 * (x - x0) + c1 * (y - y0) + c2)

    def _clamp(self, z):
        """Hold z inside the safe focus range (a no-op within the measured area)."""
        if self.z_bounds_um is None:
            return z
        return np.clip(z, self.z_bounds_um[0], self.z_bounds_um[1])


def residuals_um(surface: FocusSurface) -> list[dict]:
    """How far each measured point sits from the fitted surface, in µm.

    Returns one entry per measured point: ``{"x_um", "y_um", "z_um",
    "residual_um"}`` where ``residual_um`` is measured z minus fitted z.
    A single large residual usually means that one autofocus landed badly
    (dust, a bubble, an empty spot) and is quietly bending the whole
    surface — re-measure or remove that point rather than trusting the fit.
    """
    out = []
    for m in surface.measured:
        fitted = float(surface.z_at(m["x_um"], m["y_um"]))
        out.append({**m, "residual_um": float(m["z_um"]) - fitted})
    return out


def worst_residual_um(surface: FocusSurface) -> tuple[int, float] | None:
    """The (index, residual) of the point farthest from the fit, or None.

    ``None`` when nothing was measured. The index counts the measured
    points in order, starting at 0 — the same order the widgets draw them.
    """
    residuals = residuals_um(surface)
    if not residuals:
        return None
    index = max(range(len(residuals)), key=lambda i: abs(residuals[i]["residual_um"]))
    return index, residuals[index]["residual_um"]


def _z_bounds(zs: np.ndarray) -> tuple[float, float]:
    """The safe focus range: measured z span plus a margin that grows with it.

    The clamp in :meth:`FocusSurface.z_at` holds every queried focus inside
    this range. The margin is the fixed floor (:data:`EXTRAPOLATION_MARGIN_UM`)
    plus the measured span, so a flat sample keeps a small allowance while a
    genuinely tilted one is allowed to extend a bit past its measured edge.
    """
    z_lo, z_hi = float(zs.min()), float(zs.max())
    margin = EXTRAPOLATION_MARGIN_UM + (z_hi - z_lo)
    return (z_lo - margin, z_hi + margin)


def fit_focus_surface(measured: list[dict]) -> FocusSurface:
    """Fit a :class:`FocusSurface` from ``[{"x_um","y_um","z_um"}, ...]``.

    Every returned surface carries a safe focus range (measured z span plus a
    margin); :meth:`FocusSurface.z_at` clamps to it, so a position outside the
    measured footprint can never be driven to a runaway extrapolated z. Use
    :func:`fit_warning` after fitting to catch a point that badly disagrees
    with the surface (usually one bad autofocus).
    """
    if not measured:
        raise ValueError("need at least one focus measurement")
    xs = np.array([m["x_um"] for m in measured], dtype=float)
    ys = np.array([m["y_um"] for m in measured], dtype=float)
    zs = np.array([m["z_um"] for m in measured], dtype=float)
    x0, y0 = float(xs.mean()), float(ys.mean())
    xc, yc = xs - x0, ys - y0
    bounds = _z_bounds(zs)

    if float(zs.max() - zs.min()) < FLAT_TOLERANCE_UM:
        return FocusSurface(
            "constant", (0.0, 0.0, float(zs.mean())), (x0, y0), list(measured), z_bounds_um=bounds
        )

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
            "spline",
            None,
            (x0, y0),
            list(measured),
            scale_um=scale,
            z_bounds_um=bounds,
            _interpolator=interpolator,
        )

    # Fewer than four points, or all measured points lie on a line: the plane
    # is under-determined across the line. numpy's least-squares returns the
    # minimum-norm solution — the tilt ALONG the measured line, flat across it
    # — which is the conservative choice (it never invents a cross-line slope).
    design = np.column_stack([xc, yc, np.ones(len(measured))])
    coeffs, *_ = np.linalg.lstsq(design, zs, rcond=None)
    return FocusSurface(
        "plane",
        (float(coeffs[0]), float(coeffs[1]), float(coeffs[2])),
        (x0, y0),
        list(measured),
        z_bounds_um=bounds,
    )


def fit_warning(surface: FocusSurface) -> str | None:
    """A one-line caution when the fit looks untrustworthy, else ``None``.

    Right now it flags a single measured point sitting more than
    :data:`RESIDUAL_WARN_UM` from the fitted surface — the classic sign that
    one autofocus landed on dust, a bubble, or an empty spot and is bending
    the whole surface. The operator-facing widgets can show this so a bad
    focus point is caught before it defocuses the run.
    """
    worst = worst_residual_um(surface)
    if worst is None:
        return None
    index, residual = worst
    if abs(residual) <= RESIDUAL_WARN_UM:
        return None
    return (
        f"focus point {index + 1} sits {abs(residual):.1f} um from the fitted "
        "surface — that usually means one autofocus landed badly (dust, a bubble, "
        "an empty spot). Re-measure or remove it, or the whole surface is bent."
    )
