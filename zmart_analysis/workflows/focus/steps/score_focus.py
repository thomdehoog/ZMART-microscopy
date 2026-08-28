"""score_focus -- sharpness of every plane in a z-stack, and the sharp height.

Two metrics, both scored on every run so one can be drawn against the other:
``brenner`` is the mean squared difference between pixels two apart, and
``dct`` the Shannon entropy of the normalised DCT coefficient energy. The peak
is refined between planes with a parabola through the best plane and its two
neighbours.

Takes an OME-Zarr position or an OME-TIFF that declares a z axis
(``input["image_path"]``), or the planes of a stack in z order
(``input["image_paths"]``) -- which is what an acquisition leaves behind, one
2-D plane per file. Heights come from ``input["z_um"]`` when given, else from
the image's own z spacing; absent both, the peak is a plane index alone. A
plane list carries no spacing of its own, so it must bring ``z_um`` to report a
height. Parameters are in ``focus.yaml``.

Publishes under ``pipeline_data["score_focus"]``::

    z_um        the heights, so a curve plots straight from this
    metrics     per metric: scores in plane order, its own peak, and whether
                the stack contained one at all
    metric      which metric the reported peak came from
    peak_index  refined plane index      peak_z_um   the height there, or None
    found       whether the peak is one, or the edge of a curve still rising
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

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "parts"))
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
    planes, metadata = _stack(inp, level=level, t=t, channel=channel)
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
        found = _inside_the_sweep(peak_index, len(scores), skip_ends)
        metrics[name] = {
            "scores": scores,
            "peak_index": peak_index,
            "peak_z_um": _height_at(peak_index, z_um) if found else None,
            "found": found,
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
        "found": chosen["found"],
        "n_planes": len(planes),
        "considered": (skip_ends, len(planes) - skip_ends - 1),
        # A curve is only readable beside what produced it, and the pipeline
        # holding these is not saved with the data.
        "settings": {
            "source": _source_of(inp),
            "channel": channel,
            "level": level,
            "t": t,
            "skip_ends": skip_ends,
        },
    }
    return pipeline_data


def _stack(inp: dict, *, level, t, channel) -> tuple[list[np.ndarray], dict]:
    """The planes to score, however the caller has them.

    ``image_path`` is one position that declares its own z axis -- an OME-Zarr
    position, or a stacked TIFF. ``image_paths`` is what an acquisition
    actually leaves behind: every ZMART driver writes one 2-D plane per file,
    so a stack arrives as a list of paths in z order. Reading them where they
    were written costs nothing and copies nothing.
    """
    paths = inp.get("image_paths")
    if paths:
        if len(paths) < 2:
            raise ValueError(
                f"image_paths is a z-stack in plane order and got {len(paths)} "
                f"path(s); one plane cannot be focused."
            )
        planes = [load_plane(path, level=level, t=t, c=channel, z=0)[0] for path in paths]
        return [plane.astype(np.float64) for plane in planes], {}
    if not inp.get("image_path"):
        raise ValueError(
            "score_focus needs an image_path or image_paths: one position that "
            "declares a z axis, or the planes of a stack in order."
        )
    return _planes(inp["image_path"], level=level, t=t, channel=channel)


def _source_of(inp: dict) -> str:
    """What was scored, for the record kept beside the curve."""
    paths = inp.get("image_paths")
    return f"{len(paths)} planes from {paths[0]}" if paths else str(inp["image_path"])


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


def _inside_the_sweep(peak_index: float, n_planes: int, skip_ends: int) -> bool:
    """Whether the peak is a peak, or the edge of a curve still going up.

    A drive begun far from the tissue sweeps its whole range without reaching
    it, and the sharpest plane it holds is just the last one before it
    stopped. That plane sits at the edge of what could be chosen, with the
    curve still climbing through it -- so there is a height at which this is
    sharp and the stack does not contain it. Saying so is the only honest
    answer: a made-up height is worse than a missing one, because a surface is
    fitted through these.
    """

    return skip_ends < peak_index < n_planes - skip_ends - 1


def _refine_peak(scores: list[float], skip_ends: int) -> float:
    """The peak's plane index, interpolated between planes by a parabola.

    The best plane is chosen from the interior only, so an artefact at either
    end cannot win; its neighbours may still be skipped planes, which are
    excluded from being chosen, not from describing the curve. Falls back to
    the plain index at an edge, and wherever the three points bend the wrong
    way for a maximum.
    """
    interior = scores[skip_ends: len(scores) - skip_ends]
    best = skip_ends + int(np.argmax(interior))
    if best == 0 or best == len(scores) - 1:
        return float(best)
    before, here, after = scores[best - 1], scores[best], scores[best + 1]
    curvature = before - 2 * here + after
    if curvature >= 0:
        # The three points bend the wrong way, so the parabola through them
        # has a minimum and not a maximum: there is nothing between them to
        # refine towards. It happens where a curve is still climbing at the
        # end of what could be chosen, and following the vertex there sends
        # the answer backwards, several planes away from the sharpest one.
        return float(best)
    return float(best + 0.5 * (before - after) / curvature)
