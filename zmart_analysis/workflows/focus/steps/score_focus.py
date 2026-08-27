"""score_focus -- sharpness of every plane in a z-stack, and the sharp height.

Two metrics, both scored on every run so one can be drawn against the other:
``brenner`` is the mean squared difference between pixels two apart, and
``dct`` the Shannon entropy of the normalised DCT coefficient energy. The peak
is refined between planes with a parabola through the best plane and its two
neighbours.

Takes an OME-Zarr position or an OME-TIFF, which must declare a z axis. Heights
come from ``input["z_um"]`` when given, else from the image's own z spacing;
absent both, the peak is a plane index alone. Parameters are in ``focus.yaml``.

Publishes under ``pipeline_data["score_focus"]``::

    z_um        the heights, so a curve plots straight from this
    metrics     per metric: scores in plane order, and its own peak
    metric      which metric the reported peak came from
    peak_index  refined plane index      peak_z_um   the height there
    n_planes    considered               settings    what it was scored with

``considered`` is the first and last plane the peak could come from: the ends
of a drive carry artefacts, an artefact is a hard edge, and a hard edge is what
a sharpness metric rewards. Those planes are still scored and still returned.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from scipy.fft import dctn

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _image_io import load_plane  # noqa: E402

METADATA = {
    "description": "Score plane sharpness in a z-stack and find the peak",
    "version": "1.0",
    "max_workers": 1,
    "environment": "SMART--focus--main",
}


def _brenner(plane: np.ndarray) -> float:
    """Mean squared difference between pixels two apart, along both axes.

    Both axes because a single-axis Brenner is blind to structure running
    along it, and detail in tissue has no preferred direction.
    """
    across = plane[:, 2:] - plane[:, :-2]
    down = plane[2:, :] - plane[:-2, :]
    return float(np.mean(across * across) + np.mean(down * down))


def _dct_entropy(plane: np.ndarray) -> float:
    """Shannon entropy, in bits, of the normalised DCT coefficient energy."""
    energy = np.square(dctn(plane, norm="ortho"))
    total = energy.sum()
    if total <= 0:
        return 0.0
    share = (energy / total).ravel()
    share = share[share > 0]
    return float(-np.sum(share * np.log2(share)))


#: The metrics on offer. Adding one is adding an entry here.
METRICS = {"brenner": _brenner, "dct": _dct_entropy}


def run(pipeline_data: dict, state: dict, **params) -> dict:
    verbose = pipeline_data.get("metadata", {}).get("verbose", 0)
    metric = params.get("metric", "brenner")
    channel = params.get("channel", 0)
    level = params.get("level", 0)
    t = params.get("t", 0)
    skip_ends = int(params.get("skip_ends", 2))
    if metric not in METRICS:
        raise ValueError(f"metric must be one of {tuple(METRICS)}, got {metric!r}.")
    if skip_ends < 0:
        raise ValueError(f"skip_ends must be >= 0, got {skip_ends}.")

    inp = pipeline_data["input"]
    planes, metadata = _planes(inp["image_path"], level=level, t=t, channel=channel)
    z_um = inp.get("z_um") or _heights_from(metadata, len(planes))
    if z_um is not None and len(z_um) != len(planes):
        raise ValueError(
            f"z_um has {len(z_um)} heights but the stack has {len(planes)} planes."
        )
    if len(planes) <= 2 * skip_ends:
        raise ValueError(
            f"skip_ends={skip_ends} leaves no plane to choose from in a "
            f"{len(planes)}-plane stack."
        )

    metrics = {}
    for name, measure in METRICS.items():
        scores = [measure(plane) for plane in planes]
        peak_index = _refine_peak(scores, skip_ends)
        metrics[name] = {
            "scores": scores,
            "peak_index": peak_index,
            "peak_z_um": _height_at(peak_index, z_um),
        }
    chosen = metrics[metric]

    if verbose:
        where = (
            f"plane {chosen['peak_index']:.2f}"
            if chosen["peak_z_um"] is None
            else f"{chosen['peak_z_um']:.2f} um"
        )
        print(f"  [score_focus] {len(planes)} planes, {metric} peaks at {where}")

    pipeline_data["score_focus"] = {
        "z_um": None if z_um is None else [float(z) for z in z_um],
        "metrics": metrics,
        "metric": metric,
        "peak_index": chosen["peak_index"],
        "peak_z_um": chosen["peak_z_um"],
        "n_planes": len(planes),
        "considered": (skip_ends, len(planes) - skip_ends - 1),
        # A curve is only readable beside what produced it, and the pipeline
        # holding these is not saved with the data.
        "settings": {
            "source": str(inp["image_path"]),
            "channel": channel,
            "level": level,
            "t": t,
            "skip_ends": skip_ends,
        },
    }
    return pipeline_data


def _planes(source, *, level, t, channel) -> tuple[list[np.ndarray], dict]:
    """Every z plane of one position, and the metadata they came from.

    One lazy read per plane rather than one read of the whole position, so a
    stack costs its own z and not its channels and timepoints as well.
    """
    first, metadata = load_plane(source, level=level, t=t, c=channel, z=0)
    axes = metadata.get("axes", [])
    if "z" not in axes:
        raise ValueError(
            f"{source} declares axes {axes}, with no z among them, so there "
            f"is no way to tell which axis is depth. A focus stack must say."
        )
    depth = int(metadata["shape"][axes.index("z")])
    planes = [first] + [
        load_plane(source, level=level, t=t, c=channel, z=index)[0]
        for index in range(1, depth)
    ]
    return [plane.astype(np.float64) for plane in planes], metadata


def _heights_from(metadata: dict, depth: int) -> list[float] | None:
    """The heights the planes sit at, out of the image's own z spacing.

    A position that records where it is and how far apart its planes are has
    already said what the caller would otherwise have to pass in. Absent
    either, ``None``: a made-up height is worse than a plane index.
    """
    spacing = metadata.get("pixel_size", {}).get("z")
    if not spacing:
        return None
    origin = metadata.get("origin", {}).get("z", 0.0) or 0.0
    return [float(origin) + index * float(spacing) for index in range(depth)]


def _height_at(index: float, z_um: list[float] | None) -> float | None:
    """The height at a fractional plane index, or None when none were given."""
    if z_um is None:
        return None
    return float(np.interp(index, np.arange(len(z_um)), np.asarray(z_um, dtype=float)))


def _refine_peak(scores: list[float], skip_ends: int) -> float:
    """The peak's plane index, interpolated between planes by a parabola.

    The best plane is chosen from the interior only, so an artefact at either
    end cannot win; its neighbours may still be skipped planes, which are
    excluded from being chosen, not from describing the curve. Falls back to
    the plain index at an edge, or when the parabola has no vertex.
    """
    interior = scores[skip_ends: len(scores) - skip_ends]
    best = skip_ends + int(np.argmax(interior))
    if best == 0 or best == len(scores) - 1:
        return float(best)
    before, here, after = scores[best - 1], scores[best], scores[best + 1]
    curvature = before - 2 * here + after
    if curvature == 0:
        return float(best)
    return float(best + 0.5 * (before - after) / curvature)
