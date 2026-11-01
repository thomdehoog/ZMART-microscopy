"""score_focus -- how sharp each plane of a z-stack is, and the height of the sharpest.

Takes the stack ``read_images`` read: its planes in z order and their heights.
Every plane is scored with four sharpness measures, so their curves can be
compared, and ``metric`` says which one decides the height:

``brenner``     the mean squared difference between pixels two apart. A sharp
                peak on structured tissue; noise in a dim image can look sharp.
``dct``         the entropy of the image's frequency content. Independent of
                brightness; a broader peak.
``vollath_f4``  how much each pixel resembles its neighbour more than the pixel
                after it. Best in dim, noisy fluorescence.
``intensity``   the mean of the brightest ``intensity_percentile`` of pixels.
                Confocal only, where the pinhole makes brightness peak at focus.

Pertuz, Puig and Garcia (2013, Pattern Recognition 46:1415) compare these
measures. The peak is refined between planes with a parabola through the best
plane and its two neighbours. The first and last ``skip_ends`` planes may not
win: the ends of a drive carry hard-edged artefacts that every measure rewards.

Publishes under ``pipeline_data["score_focus"]``::

    z_um        the plane heights, or None
    metrics     per measure: the scores, its peak, and whether it found one
    metric      the measure that decided
    peak_index  the refined plane index     peak_z_um   the height there, or None
    found       False when the sharpest plane is the edge of a curve still rising
    n_planes, considered (the first and last plane allowed to win), settings
"""

from __future__ import annotations

import numpy as np
from scipy.fft import dctn

METADATA = {
    "description": "Score plane sharpness in a z-stack and find the peak",
    "version": "1.0",
    "max_workers": 1,
    "environment": "ZMART--focus--main",
}


def run(pipeline_data: dict, state: dict, **params) -> dict:

    verbose = pipeline_data.get("metadata", {}).get("verbose", 0)

    images = pipeline_data.pop("read_images")

    metric = params.get("metric", "brenner")

    percentile = float(params.get("intensity_percentile", 99.0))

    skip_ends = int(params.get("skip_ends", 2))

    measures = _measures(percentile)

    _check(metric, measures, percentile, skip_ends)

    planes = [plane.astype(np.float64) for plane in images["stack"]]

    z_um = images["z_um"]

    if z_um is not None and len(z_um) != len(planes):
        raise ValueError(f"z_um has {len(z_um)} heights but the stack has {len(planes)} planes.")

    # A short stack skips what it can spare instead of being refused
    skip = min(skip_ends, max(0, (len(planes) - 1) // 2))

    # Every measure is scored, so the curves can be drawn against each other
    metrics = {name: _curve(measure, planes, skip, z_um) for name, measure in measures.items()}

    chosen = metrics[metric]

    if verbose:
        where = (
            f"plane {chosen['peak_index']:.2f}"
            if chosen["peak_z_um"] is None
            else f"{chosen['peak_z_um']:.2f} um"
        )

        print(f"  [score_focus] {len(planes)} planes, {metric} peaks at {where}")

    pipeline_data["score_focus"] = {
        "z_um": z_um,
        "metrics": metrics,
        "metric": metric,
        "peak_index": chosen["peak_index"],
        "peak_z_um": chosen["peak_z_um"],
        "found": chosen["found"],
        "n_planes": len(planes),
        "considered": (skip, len(planes) - skip - 1),
        "settings": {
            "source": images["source"],
            "channel": images["channel"],
            "level": images["level"],
            "t": images["t"],
            "skip_ends": skip_ends,
            "skip_ends_applied": skip,
            "intensity_percentile": percentile,
        },
    }

    return pipeline_data


def brenner(plane: np.ndarray) -> float:
    """The mean squared difference between pixels two apart, along both axes.

    Both axes, because structure in tissue has no preferred direction.
    """

    across = plane[:, 2:] - plane[:, :-2]

    down = plane[2:, :] - plane[:-2, :]

    return float(np.mean(across * across) + np.mean(down * down))


def _measures(percentile: float) -> dict:
    """The four sharpness measures, by the name the pipeline uses."""

    return {
        "brenner": brenner,
        "dct": _dct_entropy,
        "vollath_f4": _vollath_f4,
        "intensity": lambda plane: _intensity(plane, percentile),
    }


def _check(metric: str, measures: dict, percentile: float, skip_ends: int) -> None:
    """Refuse settings that cannot be scored."""

    if not 0.0 <= percentile < 100.0:
        raise ValueError(
            f"intensity_percentile must be at least 0 and below 100, got {percentile}."
        )

    if metric not in measures:
        raise ValueError(f"metric must be one of {tuple(measures)}, got {metric!r}.")

    if skip_ends < 0:
        raise ValueError(f"skip_ends must be >= 0, got {skip_ends}.")


def _curve(measure, planes: list[np.ndarray], skip: int, z_um) -> dict:
    """One measure over the stack: its scores, its refined peak, and whether that is a peak."""

    scores = [measure(plane) for plane in planes]

    best = skip + int(np.argmax(scores[skip : len(scores) - skip]))

    peak_index = _refine(scores, best)

    found = _is_a_peak(scores, best, skip)

    peak_z_um = None

    if found and z_um is not None:
        peak_z_um = float(
            np.interp(peak_index, np.arange(len(z_um)), np.asarray(z_um, dtype=float))
        )

    return {"scores": scores, "peak_index": peak_index, "peak_z_um": peak_z_um, "found": found}


def _is_a_peak(scores: list[float], best: int, skip: int) -> bool:
    """Whether the sharpest allowed plane has a lower plane on both sides.

    When it does not, the curve is still rising at the edge: the sharp height
    lies outside the stack, and no height is better than a wrong one.
    """

    if best <= 0 or best >= len(scores) - 1:
        return False

    if best < skip or best > len(scores) - skip - 1:
        return False

    return scores[best - 1] < scores[best] and scores[best + 1] < scores[best]


def _refine(scores: list[float], best: int) -> float:
    """The peak's plane index, between planes, from a parabola through three scores.

    The parabola goes through the logarithm of the scores when all three are
    positive: a sharpness curve falls off like a Gaussian, and a Gaussian is a
    parabola in the log. At an edge, or where the three bend the wrong way,
    the plane itself is the answer.
    """

    if best == 0 or best == len(scores) - 1:
        return float(best)

    triple = np.asarray(scores[best - 1 : best + 2], dtype=float)

    if np.all(triple > 0):
        triple = np.log(triple)

    before, here, after = triple

    curvature = before - 2 * here + after

    if curvature >= 0:
        return float(best)

    return float(best + 0.5 * (before - after) / curvature)


def _dct_entropy(plane: np.ndarray) -> float:
    """The Shannon entropy, in bits, of the plane's DCT energy without its mean.

    The (0, 0) term is the mean brightness and carries no sharpness; left in,
    it would make the measure follow brightness instead.
    """

    energy = np.square(dctn(plane, norm="ortho"))

    energy[0, 0] = 0.0

    total = energy.sum()

    if total <= 0:
        return 0.0

    share = (energy / total).ravel()

    share = share[share > 0]

    return float(-np.sum(share * np.log2(share)))


def _vollath_f4(plane: np.ndarray) -> float:
    """Vollath's F4 along both axes: neighbour correlation minus next-neighbour correlation.

    Noise that differs from pixel to pixel cancels in the subtraction.
    """

    across = np.mean(plane[:, :-2] * plane[:, 1:-1]) - np.mean(plane[:, :-2] * plane[:, 2:])

    down = np.mean(plane[:-2, :] * plane[1:-1, :]) - np.mean(plane[:-2, :] * plane[2:, :])

    return float(across + down)


def _intensity(plane: np.ndarray, percentile: float) -> float:
    """The mean of the pixels at or above the given brightness percentile.

    Not the maximum, so one hot pixel cannot win on its own.
    """

    threshold = np.percentile(plane, percentile)

    return float(np.mean(plane[plane >= threshold]))
