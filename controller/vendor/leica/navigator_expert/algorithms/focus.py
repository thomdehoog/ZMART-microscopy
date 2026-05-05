"""Brenner-gradient focus measurement.

Two-line summary of the math:

    brenner(img)        → scalar sharpness score for one image
    brenner_focus(stack, z_step) → peak slice in a Z-stack with
                                   sub-pixel parabolic refinement

A higher score means a sharper image. The Brenner gradient is the
mean squared horizontal pixel difference at distance 2; it's a cheap
focus metric that's widely used in light microscopy because its peak
matches the visual focus to within ~1/4 of the Nyquist-limited depth
of field.

Sub-pixel peak refinement fits a parabola through the three samples
straddling the integer maximum, returning a fractional slice index.
The caller multiplies by ``z_step`` to get a physical Z position.
"""

from __future__ import annotations

import numpy as np


def brenner(img: np.ndarray) -> float:
    """Brenner gradient sharpness score for one image (scalar)."""
    f = img.astype(np.float64)
    dx = f[:, 2:] - f[:, :-2]
    return float((dx ** 2).mean())


def subpixel_peak(scores: list[float] | np.ndarray, peak: int) -> float:
    """Parabolic sub-pixel refinement of an integer maximum index."""
    if peak <= 0 or peak >= len(scores) - 1:
        return float(peak)
    y0, y1, y2 = scores[peak - 1], scores[peak], scores[peak + 1]
    denom = 2 * (2 * y1 - y0 - y2)
    if abs(denom) < 1e-10:
        return float(peak)
    return peak + (y0 - y2) / denom


def brenner_focus(stack: np.ndarray, z_step: float) -> dict:
    """Return the focus peak of a Z-stack.

    Computes Brenner score per slice, finds the integer maximum, and
    refines sub-pixel via parabolic fit.

    Returns a dict with ``peak_slice`` (int), ``peak_sub`` (float
    fractional slice), ``peak_um`` (peak_sub * z_step), and ``scores``
    (per-slice Brenner values). The caller maps ``peak_um`` to physical
    Z based on the stack's Z origin.
    """
    scores = [brenner(stack[i]) for i in range(stack.shape[0])]
    peak = int(np.argmax(scores))
    peak_sub = subpixel_peak(scores, peak)
    return {
        "peak_slice": peak,
        "peak_sub": float(peak_sub),
        "peak_um": float(peak_sub * z_step),
        "scores": [float(s) for s in scores],
    }
