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
2. otherwise the pixels, sampled from the smallest copy of the image that has
   actually been written. The smallest copy is preferred because it exists
   precisely to be cheap (a megabyte or two against the full volume's many
   gigabytes) and it covers the whole field, so percentiles taken there describe
   the same distribution the full-resolution data has.

   **"That has actually been written" is the important part**, and it is worth a
   moment because it decides whether a live run opens usably. A writer produces
   the smallest copy *last*, so during a run it is the one thing not yet there.
   Asking zarr for an unwritten piece does not raise an error — it hands back the
   fill value, zero — so reading it gives a flawless picture of pure black, a
   percentile window of nought to one, and a histogram of a single bar. The
   operator then sees black, a `BLACK 0` / `WHITE 1` readout, and an `Auto`
   button that restores the same nonsense. Whether a copy has been written is
   therefore asked of the folder on disk, and a larger copy that *has* been
   written is measured instead until the smallest one arrives.

Everything here is measured **per channel** where a store keeps several inside
one image. Measuring them together gives every channel the mixture's window, and
on a two-channel store peaking at 1200 and 39800 that leaves the faint channel's
whole useful range inside about one pixel of its slider.

A percentile rather than min/max because one hot pixel would otherwise stretch
the ramp and darken everything else — exactly the failure this is here to fix.

Both work on any store the viewer can open, whichever generation of the format
wrote it. That is worth saying because it was not always true: while this module
looked for a ``.zattrs`` file only, which is where OME-Zarr 0.4 keeps a store's
description, an OME-Zarr 0.5 store came back as unreadable and was shown over the
whole range of its data type with no histogram at all. Since 0.5 is the format this
project is aiming at, that meant the format we most want to support was the one
that opened on a guess. The description is now read through ``stores``, which knows
every place the format has kept it.

The known limit: signal sparser than the top 0.1% of voxels sits above the
percentile and comes out saturated rather than scaled. That is a deliberate
trade — an over-bright image can be corrected by eye and by ``--range``, a black
one looks like a broken viewer.
"""

from __future__ import annotations

from pathlib import Path

# Where a store keeps its description depends on which version of the format wrote
# it, and ``stores`` already knows every place it has ever been kept: at the top of
# a ``.zattrs`` for OME-Zarr 0.4, under an ``ome`` key for 0.5, and nested inside
# ``zarr.json`` for a zarr version 3 store. Reading it through that one function
# means the brightness measurement works on all of them, and — more importantly —
# that it keeps working when the format moves again, because there is one place to
# teach rather than two. It is spelled with a leading underscore to say "this is
# internal to the viewer's backend", which it is; this module is part of the same
# backend and is a fair caller of it.
from stores import _moments_folder, _read_attrs_at

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


def _omero_window(attrs: dict, channel: int | None = None) -> tuple[float, float] | None:
    """The display window the store asks for, if it declares one.

    Where a channel is named, that channel's own declaration is used and no
    other's. A store that declares a window for its bright channel and none for
    its faint one would otherwise hand the bright channel's window to both, which
    is the same fault as measuring them together — only harder to see, because it
    comes from the file rather than from us.
    """
    declared = attrs.get("omero", {}).get("channels") or []
    if channel is not None:
        wanted = [declared[channel]] if channel < len(declared) else []
    else:
        wanted = declared
    for entry in wanted:
        window = (entry or {}).get("window") or {}
        if "start" in window and "end" in window:
            start, end = float(window["start"]), float(window["end"])
            if end > start:
                return start, end
    return None


def _level_paths(attrs: dict) -> list[str]:
    """Every copy of the image the store keeps, from the largest to the smallest.

    An OME-Zarr image is written several times over at halving sizes, so that a
    viewer zoomed out can read a small copy instead of the whole thing. The
    description lists them largest first, which is the order returned here.
    """
    datasets = (attrs.get("multiscales") or [{}])[0].get("datasets") or []
    return [str(entry["path"]) for entry in datasets if entry.get("path") is not None]


def _coarsest_level_path(attrs: dict) -> str | None:
    levels = _level_paths(attrs)
    return levels[-1] if levels else None


# The small files that describe a copy of the image rather than holding any of its
# picture. A folder containing only these has been declared but never written to.
_DESCRIPTION_FILES = {".zarray", ".zattrs", ".zgroup", "zarr.json"}


def _level_holds_pixels(level: Path) -> bool:
    """Has anything actually been written into this copy of the image yet?

    This is the question that stops a live run from opening at the wrong
    brightness, and it has to be asked of the folder on disk rather than of the
    image itself. When a piece of an image has never been written, zarr does not
    report it as missing — it hands back a block of the fill value, which is
    zero. Reading an untouched copy therefore gives a perfectly well-formed
    picture that is uniformly black, and no amount of looking at those numbers
    can tell it apart from a picture of something genuinely dark.

    Looking at the folder can tell them apart, because a piece that was never
    written leaves no file behind. So the test is simply whether the folder holds
    anything besides the few small files that describe the image.

    **One case this cannot separate, and it is worth knowing.** A picture that is
    entirely zero writes no files either — zarr saves nothing for a piece holding
    only the fill value — so an image of pure nothing looks exactly like an image
    nobody has written to. It is read as the latter, which is the kinder mistake
    of the two: during a run that is almost always what it really is, and the
    answer is then taken again once something lands. The cost of being wrong is
    that a genuinely blank acquisition is measured again on each look rather than
    once, which is a few directory listings and no reading of pixels at all. Such
    a store draws black either way, so nothing an operator sees depends on it.
    """
    holder = _moments_folder(level)
    try:
        return any(entry.name not in _DESCRIPTION_FILES for entry in holder.iterdir())
    except OSError:
        return False


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


def _sample(array, held: dict[int, int] | None = None) -> object:
    """Read at most a few million voxels from anywhere in ``array``.

    Small images are read whole. Large ones are sampled: the last two axes are
    cropped to a square about the middle, and every axis before them is reduced to
    a handful of positions spread through it, so the sample is drawn from the depth
    of the image rather than from one face of it.

    Args:
        held: axes that must stay at one position, given as ``{axis: position}``.
            This is how a single channel is looked at on its own: pinning the
            channel axis to one number means the samples come from that channel
            and no other. Left out, nothing is pinned and the sample is drawn
            from the image as a whole.
    """
    import numpy as np

    held = held or {}
    shape = tuple(int(n) for n in array.shape)
    if not shape:
        return np.asarray(array[...])

    # How much there is to look at once the pinned axes are held still. A
    # two-channel image asked about one channel has half as much to read, and
    # counting it that way is what lets a modest image still be read whole.
    budget = _SAMPLE_PLANES * _SAMPLE_SIDE * _SAMPLE_SIDE
    total = 1
    for axis, extent in enumerate(shape):
        total *= 1 if axis in held else max(int(extent), 1)
    if total <= budget:
        whole = tuple(held.get(axis, slice(None)) for axis in range(len(shape)))
        return np.asarray(array[whole])

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
    #
    # The samples are spread through the last axis that is free to move, which is
    # normally depth. Asking about one channel pins the channel axis, and if that
    # were also the axis being spread through, the sample would quietly be drawn
    # from every channel again and the answer would be the mixture's rather than
    # this channel's.
    free = [axis for axis in range(len(leading)) if axis not in held]
    if not free:
        index = tuple([*(held[axis] for axis in range(len(leading))), *plane])
        try:
            return np.asarray(array[index]).ravel()
        except (OSError, ValueError, IndexError):
            return np.asarray([])

    spread_axis = free[-1]
    depth = leading[spread_axis]
    positions = sorted({int(i * (depth - 1) / max(_SAMPLE_PLANES - 1, 1)) for i in range(_SAMPLE_PLANES)})
    pieces = []
    for position in positions:
        where: list[int] = []
        for axis, extent in enumerate(leading):
            if axis == spread_axis:
                where.append(position)
            elif axis in held:
                where.append(held[axis])
            else:
                where.append(max(0, extent // 2))
        try:
            pieces.append(np.asarray(array[tuple([*where, *plane])]).ravel())
        except (OSError, ValueError, IndexError):
            continue
    if not pieces:
        return np.asarray([])
    return np.concatenate(pieces)


def _samples(store: Path, *, channel: int | None = None):
    """Read a store's description and take one bounded look at its pixels.

    Everything below needs the same two things — what the store says about
    itself, and a modest handful of its values — so they are gathered here once
    and shared. Reading pixels is far and away the most expensive thing this
    viewer does when an acquisition is first opened, and doing it once per store
    rather than once per question is the difference between a folder of several
    hundred acquisitions opening in about a minute and taking three.

    Args:
        channel: which channel to look at, where the store keeps several inside
            one image. Left out, the sample is drawn from all of them together,
            which is the right thing only when there is one.

    Returns ``(attrs, values, settled)``, or ``None`` if nothing has been written
    into the store yet or it could not be read at all. ``values`` is a flat array
    of the finite samples. ``settled`` says whether they came from the smallest
    copy of the image — the one that covers the whole field of view — and so
    whether this measurement is the final one or a good reading taken while the
    run is still filling in. Values that are not finite are dropped here rather
    than in each caller: a stray "not a number" left in would otherwise make
    every percentile come out as "not a number" too, and the window would
    silently be nonsense.

    The description is read through ``stores``, which is what lets this work on an
    OME-Zarr 0.5 store as well as on a 0.4 one. That is not a small detail: 0.5 is
    the format this project is aiming at, and while this function looked only for a
    ``.zattrs`` file, a store written that way came back as "could not be read".
    The consequence was quiet rather than loud — such a store opened with a window
    covering the whole range of a 16-bit camera, which draws real data as a flat
    saturated shape, and with no histogram for the panel to draw or for the Auto
    button to work from.
    """
    import numpy as np
    import zarr

    try:
        attrs = _read_attrs_at(store)
        levels = _level_paths(attrs)
        if not levels:
            return None
        held = _hold_the_channel(attrs, channel)
        group = zarr.open_group(str(store), mode="r")
    except (OSError, KeyError, ValueError, MemoryError):
        return None

    # Smallest copy first, because it is much the cheapest to read and it covers
    # the whole field of view. Where it has not been written yet -- which is the
    # ordinary state of a run still going, since the smallest copy is the last
    # thing a writer produces -- a larger one that *has* been written is asked
    # instead. Measuring a larger copy sees less of the specimen at once, so the
    # answer is good rather than final, and the caller is told which it got.
    for position, level in enumerate(reversed(levels)):
        if not _level_holds_pixels(store / level):
            continue
        try:
            data = _sample(group[level], held)
        except (OSError, KeyError, ValueError, IndexError, MemoryError):
            # IndexError among them because a caller may name a channel the array
            # does not have. A store that cannot be sampled is one this simply has
            # no answer for, and saying so is better than raising into the middle
            # of building the answer to "what is open".
            continue
        values = np.asarray(data, dtype=np.float64).ravel()
        values = values[np.isfinite(values)]
        if values.size == 0:
            continue
        return attrs, values, position == 0
    return None


def coarsest_level_is_written(store: str | Path) -> bool:
    """Has the smallest, whole-field copy of this image been written yet?

    The server asks this to decide whether a brightness measurement taken earlier
    is worth taking again. It only looks at a folder, so it is cheap enough to
    ask on every answer, whereas measuring means reading picture data.

    A run still going has not yet written this copy — it is the last thing a
    writer produces — so this reads ``False`` during the run and ``True``
    afterwards, which is exactly when the measurement is worth repeating.
    """
    store = Path(store)
    try:
        level = _coarsest_level_path(_read_attrs_at(store))
    except (OSError, KeyError, ValueError):
        # A store that cannot be read describes nothing, so there is nothing to
        # say has been written. Answering "not yet" rather than raising keeps the
        # caller free of error handling, and costs only a measurement being taken
        # again later.
        return False
    return False if level is None else _level_holds_pixels(store / level)


def _hold_the_channel(attrs: dict, channel: int | None) -> dict[int, int]:
    """Which axis to pin, and where, so that only one channel is looked at.

    Returns an empty answer when no channel was asked for, or when the store
    keeps its channels in separate files rather than along an axis of one image —
    in that case the whole image already is the one channel.
    """
    if channel is None:
        return {}
    axes = [axis.get("name", "") for axis in (attrs.get("multiscales") or [{}])[0].get("axes") or []]
    return {axes.index("c"): channel} if "c" in axes else {}


def measure(
    store: str | Path, *, channel: int | None = None, bins: int = HISTOGRAM_BINS
) -> dict:
    """Everything the panel needs to know about one channel's brightness.

    This is what the server calls when it meets a store for the first time. It
    answers all three questions at once — how to display a plane, how to display
    a volume, and what the spread of brightness looks like — from a single look at
    the pixels, because asking them separately means reading the same data three
    times over.

    The two windows differ on purpose. A plane wants a window sitting just above
    the background so faint detail is visible; a volume wants one much higher up,
    or every dim background voxel along the line of sight adds a little haze and
    the specimen disappears into fog.

    Args:
        channel: which channel of the store to measure, where several are kept
            inside one image. **Give this whenever the store has a channel axis.**
            Measured without it, a store whose first channel peaks at 1200 and
            whose second peaks at 39800 yields one window covering both, and the
            faint channel's entire useful range then sits in the bottom hundredth
            of its slider — which is the state the slider exists to prevent.
        bins: how many bars the histogram should have.

    Returns a dictionary holding the two windows, the histogram, and ``settled``.
    ``settled`` is ``False`` when the numbers were taken while the run was still
    filling in — either because nothing had been written at all, in which case
    the window is a fallback covering a 16-bit camera's whole range, or because
    the smallest copy of the image was not yet there and a larger one was read
    instead. Either way the answer is worth using now and worth asking again
    later, and the caller should not remember it for the rest of the session.
    """
    store = Path(store)
    read = _samples(store, channel=channel)
    if read is None:
        return {
            "window": (0.0, 65535.0),
            "volumeWindow": (0.0, 65535.0),
            "histogram": None,
            "settled": False,
        }
    attrs, values, settled = read
    declared = _omero_window(attrs, channel)
    return {
        # A window the store itself declares is honoured for the plane view: the
        # microscope software that wrote it knew what it was showing.
        "window": declared if declared is not None else _window(values, volumetric=False),
        "volumeWindow": _window(values, volumetric=True),
        "histogram": _histogram(values, bins=bins),
        "settled": settled,
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


def display_window(
    store: str | Path, *, volumetric: bool = False, channel: int | None = None
) -> tuple[float, float]:
    """Return the ``(low, high)`` intensity window to display ``store`` with.

    With ``volumetric``, the window is measured high in the distribution so the
    background stays transparent, and any declared ``omero`` window is ignored:
    that block describes how to show a *slice*, and following it in a volume is
    what produces fog.

    With ``channel``, only that channel of the store is looked at. A store
    holding several channels needs this, or every channel is handed a window
    measured from the mixture of all of them.

    Falls back to the data type's own range only when the store is unreadable
    or uniform, which keeps the caller free of error handling — a poor window
    still shows an image, whereas an exception shows nothing.

    This asks one store one question. When the server meets a store for the first
    time it wants all three answers at once, and calls :func:`measure` instead so
    the pixels are only read through once.
    """
    store = Path(store)
    if not volumetric:
        # Read through ``stores`` so that a window declared by an OME-Zarr 0.5
        # store is honoured too, rather than only one written the 0.4 way. A store
        # that cannot be read at all simply describes nothing, and the measurement
        # below then falls back on its own.
        declared = _omero_window(_read_attrs_at(store), channel)
        if declared is not None:
            return declared

    read = _samples(store, channel=channel)
    if read is None:
        return 0.0, 65535.0
    return _window(read[1], volumetric=volumetric)


def intensity_histogram(
    store: str | Path, *, channel: int | None = None, bins: int = HISTOGRAM_BINS
) -> dict | None:
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
    read = _samples(Path(store), channel=channel)
    if read is None:
        return None
    return _histogram(read[1], bins=bins)
