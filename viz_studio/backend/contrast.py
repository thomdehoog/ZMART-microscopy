"""Work out the intensity window a store should first be displayed with.

Without this the viewer shows real acquisitions as black. neuroglancer's default
image shader stretches the *type's* full range — 0..65535 for the 16-bit data
every camera here produces — while a real mesoSPIM volume occupies a sliver of
it (a few hundred counts of background with signal barely above). Everything
therefore maps to the bottom of the ramp and the screen stays dark, even though
the volume loaded, the geometry is right, and chunks are on the GPU.

Two sources of truth, in order:

1. the store's own ``omero`` block, if it has one — that is the format's way of
   saying how the acquisition should look, and second-guessing it would be
   wrong;
2. otherwise the pixels, sampled from the *coarsest* pyramid level. That level
   exists precisely to be cheap (a megabyte or two against the full volume's
   many gigabytes) and it covers the whole field, so percentiles taken there
   describe the same distribution the full-resolution data has.

A percentile rather than min/max because one hot pixel would otherwise stretch
the ramp and darken everything else — exactly the failure this is here to fix.

The known limit: signal sparser than the top 0.1% of voxels sits above the
percentile and comes out saturated rather than scaled. That is a deliberate
trade — an over-bright image can be corrected by eye and by ``--range``, a black
one looks like a broken viewer.
"""

from __future__ import annotations

import json
from pathlib import Path

LOW_PERCENTILE = 1.0
HIGH_PERCENTILE = 99.9

# Volume rendering needs a different window from a cross-section, for a reason
# that is physical rather than cosmetic. A slice shows one plane, so a window
# starting at the background merely makes the background dark grey. A volume
# accumulates every voxel along the line of sight, so that same window makes
# hundreds of background voxels contribute a little haze each and the specimen
# disappears into fog. Starting the window near the top of the distribution
# leaves the background fully transparent and lets only real structure show.
VOLUME_LOW_PERCENTILE = 99.0
VOLUME_HIGH_PERCENTILE = 99.99
HISTOGRAM_BINS = 64
HISTOGRAM_LOW_PERCENTILE = 0.1
HISTOGRAM_HIGH_PERCENTILE = 99.9


def _omero_window(attrs: dict) -> tuple[float, float] | None:
    """The display window the store asks for, if it declares one."""
    channels = attrs.get("omero", {}).get("channels") or []
    for channel in channels:
        window = channel.get("window") or {}
        if "start" in window and "end" in window:
            start, end = float(window["start"]), float(window["end"])
            if end > start:
                return start, end
    return None


def _coarsest_level_path(attrs: dict) -> str | None:
    datasets = (attrs.get("multiscales") or [{}])[0].get("datasets") or []
    return datasets[-1].get("path") if datasets else None


# How much of an image to look at when measuring how bright it is. The smallest
# copy in the pyramid is usually tiny and can simply be read whole — but that is
# only true if the image *has* a pyramid. An acquisition written without one, or
# with only a couple of levels, leaves the smallest copy as big as the image, and
# on a four-hundred-gigabyte acquisition reading it whole does not merely take a
# while: it asks for more memory than the machine has and brings the viewer down
# before it has shown anything.
#
# So a bounded sample is taken instead: a few planes, each cropped to a square
# around the middle. That is plenty to judge brightness by — the measurement is a
# percentile, not an inventory — and it costs the same whether the image is a
# megabyte or a terabyte.
_SAMPLE_PLANES = 4
_SAMPLE_SIDE = 1024


def _sample(array) -> object:
    """Read at most a few million voxels from anywhere in ``array``.

    Small images are read whole. Large ones are sampled: the last two axes are
    cropped to a square about the middle, and every axis before them is reduced to
    a handful of positions spread through it, so the sample is drawn from the depth
    of the image rather than from one face of it.
    """
    import numpy as np

    shape = tuple(int(n) for n in array.shape)
    if not shape:
        return np.asarray(array[...])

    budget = _SAMPLE_PLANES * _SAMPLE_SIDE * _SAMPLE_SIDE
    total = 1
    for extent in shape:
        total *= max(int(extent), 1)
    if total <= budget:
        return np.asarray(array[...])

    # Crop the image plane (the last two axes) to a square about the middle.
    plane: list[slice] = []
    for extent in shape[-2:]:
        if extent <= _SAMPLE_SIDE:
            plane.append(slice(None))
        else:
            start = (extent - _SAMPLE_SIDE) // 2
            plane.append(slice(start, start + _SAMPLE_SIDE))

    leading = shape[: len(shape) - len(plane)]
    if not leading:
        return np.asarray(array[tuple(plane)])

    # Spread a few samples through whatever comes before the plane -- depth,
    # channels, time -- taking one position at a time so nothing large is ever
    # asked for at once.
    depth = leading[-1]
    positions = sorted({int(i * (depth - 1) / max(_SAMPLE_PLANES - 1, 1)) for i in range(_SAMPLE_PLANES)})
    middles = [max(0, extent // 2) for extent in leading[:-1]]
    pieces = []
    for position in positions:
        index = tuple([*middles, position, *plane])
        try:
            pieces.append(np.asarray(array[index]).ravel())
        except (OSError, ValueError, IndexError):
            continue
    if not pieces:
        return np.asarray([])
    return np.concatenate(pieces)


def _samples(store: Path):
    """Read a store's description and take one bounded look at its pixels.

    Everything below needs the same two things — what the store says about
    itself, and a modest handful of its values — so they are gathered here once
    and shared. Reading pixels is far and away the most expensive thing this
    viewer does when an acquisition is first opened, and doing it once per store
    rather than once per question is the difference between a folder of several
    hundred acquisitions opening in about a minute and taking three.

    Returns ``(attrs, values)`` where ``values`` is a flat array of the finite
    samples, or ``None`` if the store could not be read at all. Values that are
    not finite are dropped here rather than in each caller: a stray "not a
    number" left in would otherwise make every percentile come out as "not a
    number" too, and the window would silently be nonsense.
    """
    import numpy as np
    import zarr

    try:
        attrs = json.loads((store / ".zattrs").read_text(encoding="utf-8"))
        level = _coarsest_level_path(attrs)
        if level is None:
            return None
        data = _sample(zarr.open_group(str(store), mode="r")[level])
    except (OSError, KeyError, ValueError, MemoryError, json.JSONDecodeError):
        return None
    values = np.asarray(data, dtype=np.float64).ravel()
    values = values[np.isfinite(values)]
    if values.size == 0:
        return None
    return attrs, values


def measure(store: str | Path, *, bins: int = HISTOGRAM_BINS) -> dict:
    """Everything the panel needs to know about one store's brightness.

    This is what the server calls when it meets a store for the first time. It
    answers all three questions at once — how to display a plane, how to display
    a volume, and what the spread of brightness looks like — from a single look at
    the pixels, because asking them separately means reading the same data three
    times over.

    The two windows differ on purpose. A plane wants a window sitting just above
    the background so faint detail is visible; a volume wants one much higher up,
    or every dim background voxel along the line of sight adds a little haze and
    the specimen disappears into fog.
    """
    store = Path(store)
    read = _samples(store)
    if read is None:
        return {
            "window": (0.0, 65535.0),
            "volumeWindow": (0.0, 65535.0),
            "histogram": None,
        }
    attrs, values = read
    declared = _omero_window(attrs)
    return {
        # A window the store itself declares is honoured for the plane view: the
        # microscope software that wrote it knew what it was showing.
        "window": declared if declared is not None else _window(values, volumetric=False),
        "volumeWindow": _window(values, volumetric=True),
        "histogram": _histogram(values, bins=bins),
    }


def _window(values, *, volumetric: bool) -> tuple[float, float]:
    """The intensity window for one view, from samples already in hand."""
    import numpy as np

    low_pct = VOLUME_LOW_PERCENTILE if volumetric else LOW_PERCENTILE
    high_pct = VOLUME_HIGH_PERCENTILE if volumetric else HIGH_PERCENTILE
    low, high = (float(v) for v in np.percentile(values, [low_pct, high_pct]))
    if high <= low:
        # Deliberately *not* min/max here. Falling back to the extremes would
        # let one hot pixel set the top of the ramp and crush everything else
        # to black — the very failure the percentile is here to avoid. A window
        # one count wide instead leaves the image bright rather than blank.
        return low, low + 1.0
    return low, high


def _histogram(values, *, bins: int) -> dict:
    """The shape of the brightness distribution, from samples already in hand."""
    import numpy as np

    # All four percentiles in one call. Each one otherwise re-sorts the whole
    # sample, so asking separately does the same expensive work four times.
    plot_low, plot_high, auto_low, auto_high = (
        float(v)
        for v in np.percentile(
            values,
            [
                HISTOGRAM_LOW_PERCENTILE,
                HISTOGRAM_HIGH_PERCENTILE,
                LOW_PERCENTILE,
                HIGH_PERCENTILE,
            ],
        )
    )
    if plot_high <= plot_low:
        plot_high = plot_low + 1.0
    if auto_high <= auto_low:
        auto_high = auto_low + 1.0
    counts, _ = np.histogram(
        np.clip(values, plot_low, plot_high), bins=bins, range=(plot_low, plot_high)
    )
    return {
        "low": plot_low,
        "high": plot_high,
        "counts": [int(value) for value in counts],
        "autoWindow": {"low": auto_low, "high": auto_high},
    }


def display_window(store: str | Path, *, volumetric: bool = False) -> tuple[float, float]:
    """Return the ``(low, high)`` intensity window to display ``store`` with.

    With ``volumetric``, the window is measured high in the distribution so the
    background stays transparent, and any declared ``omero`` window is ignored:
    that block describes how to show a *slice*, and following it in a volume is
    what produces fog.

    Falls back to the data type's own range only when the store is unreadable
    or uniform, which keeps the caller free of error handling — a poor window
    still shows an image, whereas an exception shows nothing.

    This asks one store one question. When the server meets a store for the first
    time it wants all three answers at once, and calls :func:`measure` instead so
    the pixels are only read through once.
    """
    store = Path(store)
    if not volumetric:
        try:
            attrs = json.loads((store / ".zattrs").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return 0.0, 65535.0
        declared = _omero_window(attrs)
        if declared is not None:
            return declared

    read = _samples(store)
    if read is None:
        return 0.0, 65535.0
    return _window(read[1], volumetric=volumetric)


def intensity_histogram(store: str | Path, *, bins: int = HISTOGRAM_BINS) -> dict | None:
    """Return a compact histogram measured from the coarsest pyramid level.

    The plotted range is percentile-clipped so one defective hot pixel cannot
    compress the useful distribution into the first bar. Counts still include
    every finite sample: values outside that robust range are clipped into the
    edge bins. ``autoWindow`` is the same percentile window used for an
    undeclared 2-D display and is what the panel's Auto button restores.

    ``None`` means the store could not be read. The viewer can still render it
    with its fallback window; it simply omits the histogram rather than
    inventing one.
    """
    if bins < 2:
        raise ValueError("a histogram needs at least two bins")
    read = _samples(Path(store))
    if read is None:
        return None
    return _histogram(read[1], bins=bins)
