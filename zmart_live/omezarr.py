"""Making a live-written position into an image other people's software can open.

A run writes each position as a folder of numbers: a full-resolution copy in a
subfolder called ``0``, a half-size copy in ``1``, a quarter-size copy in ``2``,
and so on. Those numbers are perfectly real, and on their own they are unusable.
Nothing in them says which dimension is depth and which is time, how large a
voxel is, or where on the stage the picture was taken. Open such a folder in
napari or Fiji and you are told there is no image there — because, as far as the
format is concerned, there is not. A folder of arrays only becomes an *image*
once a small description is written over it, and this module writes that
description.

What is missing without it
--------------------------

OME-Zarr is the agreed way of saying those things. This module writes version
0.5 of it, which is the generation built on zarr version 3 and the one the rest
of this project writes by default. Four pieces are needed, and a position
written by :mod:`zmart_live.coordinator` has none of them until this module
runs:

*The image group.* The position folder itself has to be marked as a group — a
folder that holds arrays — and that mark is a small ``zarr.json`` file at its
top. Without it, ``zarr.open_group`` refuses the folder outright and no reader
gets any further.

*The version.* One line, ``ome.version``, saying which generation of the format
the description follows. A reader uses it to decide how to interpret everything
else.

*The multiscale block.* This names the axes, gives each one a type and a unit,
and lists the progressively smaller copies with what each of them means.

*The dimension names on each copy.* Version 0.5 requires every array to name its
own dimensions, and requires those names to match the axes above. It is what
lets somebody open a single zoomed-out copy on its own and still know which
dimension is depth.

What a coordinate transformation is
-----------------------------------

The phrase sounds forbidding and the idea is simple. A voxel in the file is
addressed by counting: row 40, column 512, plane 3. A place on the specimen is
measured: 14 microns up, 179.2 microns across. A **coordinate transformation** is
the recipe for turning the first into the second, and OME-Zarr writes it as two
plain lists of numbers.

The **scale** says how much ground one step along each axis covers — a voxel
0.35 microns wide and 2 microns deep. Multiply the counted position by the scale
and you have a distance, but measured from the corner of this picture rather
than from anywhere on the microscope.

The **translation** says where that corner sits in the run's shared coordinates.
Add it, and the same voxel now has a place on the stage that a neighbouring
position agrees with. This is what lets two tiles imaged an hour apart line up
when a colleague opens them together.

The order matters and the format fixes it: the scale is written first and the
translation second, because the offset is given in real distance rather than in
voxels. Written the other way round the picture lands a whole run's width away
from where it belongs.

Two further decisions, both taken to match the rest of this project rather than
invented here. The translation is written **beside each copy and nowhere else**;
OME-Zarr also allows one statement for the image as a whole, and saying it in
both places moves the picture twice as far out as it really is. And the number
is the **corner** of the first voxel rather than its middle, so that the copies
nest exactly — a coarse voxel covers precisely the fine voxels it was built
from. ``zmart_storage/VOXEL_PLACEMENT.md`` sets out the arithmetic behind that
choice, and ``docs/design/zmart-ome-zarr-recipe.md`` records both decisions.

Using it
--------

The module works on a position that has already been written. It reads nothing
of the pixels and moves none of them; it adds the small files that turn what is
already on disk into an image::

    from zmart_live.omezarr import describe_the_position

    describe_the_position(
        publisher.position_store("pos00003"),
        publisher.profile,
        name="pos00003",
        channels=("488", "561"),
        origin_pixels=publisher.layout.placement("pos00003").origin,
    )

Afterwards ``zarr.open_group`` opens the folder, ``ngff-zarr`` reads the voxel
size and the corner back, and a colleague can drag the position into napari.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np
import zarr

from zmart_storage.canvas import Channel, written_despite_brief_holds

from .model import AcquisitionProfile, LevelGeometry, ZmartLiveError

__all__ = [
    "OME_ZARR_VERSION",
    "SPACE_UNITS",
    "TIME_UNITS",
    "describe_the_position",
    "the_axes",
    "the_image_description",
]

#: Which generation of OME-Zarr this module writes. Version 0.5 is the one built
#: on zarr version 3, which keeps a store's description inside its own
#: ``zarr.json`` under an ``ome`` key rather than in a separate file beside it.
OME_ZARR_VERSION = "0.5"

#: What each axis name means. A microscope image has at most five axes and this
#: project always declares all five, in this order, whether or not the run had a
#: moment or a colour to put in them. The standard requires the order to run
#: time, then colour, then the axes that measure distance, so a reader knows
#: which dimension to put on the depth slider without measuring anything.
_WHAT_AN_AXIS_MEASURES = {
    "t": "time",
    "c": "channel",
    "z": "space",
    "y": "space",
    "x": "space",
}

#: The rank of each kind of axis in the order the standard demands.
_WHERE_A_KIND_BELONGS = {"time": 0, "channel": 1, "space": 2}

#: The names for distance the standard accepts, which are the UDUNITS-2 names.
#: Only the ones a light microscope plausibly uses are listed. The near-misses
#: are worth knowing about: "um" and "micron" are both wrong here and both are
#: silently ignored by other software, which leaves a scale bar quietly missing
#: rather than obviously broken.
SPACE_UNITS = frozenset(
    {"angstrom", "nanometer", "micrometer", "millimeter", "centimeter", "meter"}
)

#: The names for time the standard accepts, in the same spirit.
TIME_UNITS = frozenset(
    {"nanosecond", "microsecond", "millisecond", "second", "minute", "hour", "day"}
)

#: How long one step along the time axis lasts, when the run has not said. One
#: second is a placeholder rather than a measurement, and a timelapse that knows
#: its real interval should pass it, because a reader will otherwise show times
#: that are simply wrong.
A_SECOND = 1.0

#: How the smaller copies were made, and what that means for somebody reading
#: them. The standard asks every image to say this, and here it is genuinely
#: useful rather than a formality: it tells a reader whether a zoomed-out picture
#: is a smoothed version of the specimen or a sample of it.
#:
#: ``mean`` is what :mod:`zmart_live.coordinator` does today — it averages each
#: two-by-two block of voxels in y and x — and it is the default here for that
#: reason. ``nearest`` is what :mod:`zmart_storage.canvas` does, keeping every
#: second voxel and discarding the rest, and it is offered so that a position
#: written that way can be described truthfully by the same code.
HOW_THE_COPIES_WERE_MADE = {
    "mean": {
        "method": "mean",
        "description": (
            "Each coarse voxel is the average of the two-by-two block of finer "
            "voxels it stands for, in y and x. The depth is never reduced, so "
            "scrolling through a stack always shows the planes that were really "
            "acquired."
        ),
    },
    "nearest": {
        "method": "slice",
        "description": (
            "Every second voxel is kept along y and x at each level and the rest "
            "discarded; nothing is averaged, so each coarse voxel is one "
            "original voxel."
        ),
    },
}


def the_axes(profile: AcquisitionProfile, *, time_unit: str = "second") -> list[dict]:
    """Say what each dimension of a position's pictures means.

    This is the part of the description that tells a reader which dimension is
    depth, which is time, and what the numbers along each of them are measured
    in. Everything else — the voxel size, the corner, the smaller copies — is
    written against this list and has to line up with it.

    Args:
        profile: the sealed description of how this kind of acquisition is
            written. Its ``axes`` give the order and its ``voxel_unit`` gives the
            unit for every axis that measures distance.
        time_unit: what one step along the time axis is measured in. Seconds
            unless the run says otherwise.

    Returns:
        One entry per axis, in the order the pictures are stored, each giving a
        name, what it measures, and — for time and distance — its unit.

    Raises:
        ZmartLiveError: when the profile names an axis this module has never
            heard of, when the axes are not in the order the standard demands,
            or when a unit is not a name other software will recognise. Each of
            these would produce a file that opens somewhere unexpected rather
            than one that fails, which is why they are refused here.
    """
    unknown = [axis for axis in profile.axes if axis not in _WHAT_AN_AXIS_MEASURES]
    if unknown:
        raise ZmartLiveError(
            f"This profile has axes called {unknown}, and there is no way to tell "
            f"whether they measure time, colour or distance. Only "
            f"{sorted(_WHAT_AN_AXIS_MEASURES)} can be described as an OME-Zarr "
            f"image, because a reader has to be told what each dimension means "
            f"before it can draw anything."
        )

    kinds = [_WHAT_AN_AXIS_MEASURES[axis] for axis in profile.axes]
    ranked = [_WHERE_A_KIND_BELONGS[kind] for kind in kinds]
    if ranked != sorted(ranked):
        raise ZmartLiveError(
            f"The axes are stored in the order {profile.axes}, which is not the "
            f"order the format requires: time first, then colour, then the axes "
            f"that measure distance. A reader trusts that order to decide which "
            f"dimension belongs on the depth slider, so an image written this way "
            f"would show the specimen as a thin band rather than reporting "
            f"anything wrong."
        )

    if profile.voxel_unit not in SPACE_UNITS:
        raise ZmartLiveError(
            f"This profile measures its voxels in '{profile.voxel_unit}', which is "
            f"not a name other software recognises. Use one of "
            f"{sorted(SPACE_UNITS)} — 'um' and 'micron' are the usual near-misses, "
            f"and both are quietly ignored elsewhere, which leaves a scale bar "
            f"silently missing rather than visibly wrong."
        )
    if time_unit not in TIME_UNITS:
        raise ZmartLiveError(
            f"The time axis is measured in '{time_unit}', which is not a name "
            f"other software recognises. Use one of {sorted(TIME_UNITS)}."
        )

    described = []
    for axis in profile.axes:
        kind = _WHAT_AN_AXIS_MEASURES[axis]
        entry = {"name": axis, "type": kind}
        if kind == "space":
            entry["unit"] = profile.voxel_unit
        elif kind == "time":
            entry["unit"] = time_unit
        # A colour axis is given no unit, because a channel is not measured in
        # anything; it is simply one of several.
        described.append(entry)
    return described


def _how_far_one_step_reaches(
    profile: AcquisitionProfile,
    level: LevelGeometry,
    *,
    seconds_between_timepoints: float,
) -> list[float]:
    """How much ground one step along each axis covers, at one zoom level.

    This is the ``scale`` half of the coordinate transformation: multiply a
    counted position by these numbers and you have a measured one. For an axis
    that measures distance it is the voxel size, made larger at every zoomed-out
    level by however much that level shrank the picture. A run that halves the
    width and the height at each level therefore doubles those two numbers each
    time, while the depth stays as it was, because no plane is ever dropped.
    """
    reach = []
    for axis in profile.axes:
        kind = _WHAT_AN_AXIS_MEASURES[axis]
        if kind == "space":
            # The voxel size the run declared, made coarser by exactly as much as
            # this level shrank the picture. Reading the shrinkage from the level
            # rather than assuming it doubles is what keeps this honest for a
            # profile whose depth is never reduced.
            reach.append(
                float(profile.voxel_size.get(axis, 1.0)) * float(level.downsampling.get(axis, 1))
            )
        elif kind == "time":
            reach.append(float(seconds_between_timepoints))
        else:
            # One step along the colour axis is one channel. There is nothing to
            # measure, and the format still wants a number for every axis, so it
            # is one.
            reach.append(1.0)
    return reach


def _where_the_corner_sits(
    profile: AcquisitionProfile, origin_pixels: Mapping[str, float]
) -> list[float]:
    """Where this position's first voxel sits, in the run's shared measurements.

    This is the ``translation`` half of the coordinate transformation. The run
    keeps a position's place as a count of full-resolution pixels from the corner
    of the mosaic, because that is the form the tiling arithmetic needs. A reader
    needs it as a distance, so it is multiplied by the voxel size here.

    Every level is given the same corner. A zoomed-out copy covers more ground
    per voxel but it still begins at the same place on the stage, and saying
    otherwise would make the specimen appear to slide sideways as the operator
    zoomed out.
    """
    corner = []
    for axis in profile.axes:
        if _WHAT_AN_AXIS_MEASURES[axis] != "space":
            # Time and colour have no place on the stage, and the format still
            # wants an entry for every axis, so they are left at nought.
            corner.append(0.0)
            continue
        corner.append(
            float(origin_pixels.get(axis, 0.0)) * float(profile.voxel_size.get(axis, 1.0))
        )
    return corner


def _the_brightest_a_pixel_can_be(dtype: str) -> int:
    """The largest number this kind of pixel can hold.

    A channel's description states the camera's whole range as well as the
    brightness the image should first be shown at, and this is the first of
    those. For the integer pixels a camera produces it is an exact fact — 65535
    for a 16-bit camera. Floating-point pixels have no such limit, and one is
    used there only so that the description is complete.
    """
    kind = np.dtype(dtype)
    if kind.kind in "iu":
        return int(np.iinfo(kind).max)
    return 1


# The colours channels take in turn when the run declared none, in the
# panel's own order (see _DEFAULT_CHANNEL_TURNS in the viewer's stores.py):
# green and magenta first because they are the pair colour-blind operators
# tell apart best.
_CHANNEL_TURNS = ("00FF66", "FF33FF", "33CCFF", "FFBF19")


def the_channels_described(channels: Sequence[str | Channel],
                           dtype: str) -> list[dict]:
    """Name and colour each channel, in the form a reader expects.

    The colours and the brightness window are built by
    :class:`zmart_storage.canvas.Channel`, which is the one place in this project
    that decides what a channel's description should look like. Writing a second
    version of that here would be how the two quietly drift apart, and a
    description with an incomplete brightness window is refused outright by
    strict readers.

    One thing is decided here rather than per channel: a run of SEVERAL
    channels that declared no colours does not describe them all white.
    Channels of one picture sum like light on screen, and a replayed grid
    arrived as two white channels summed to pure clipping — every position
    white, no structure (the operator saw it, 2026-08-23). Where nothing was
    declared, the channels take the panel's own palette in turn; a single
    channel keeps the class's own answer, because with nothing to tell it
    from, a colour would be an invention.
    """
    brightest = _the_brightest_a_pixel_can_be(dtype)
    named = [channel if isinstance(channel, Channel) else Channel(str(channel))
             for channel in channels]
    if len(named) > 1:
        turn = 0
        for at, channel in enumerate(named):
            if channel.color is None:
                named[at] = Channel(channel.name,
                                    _CHANNEL_TURNS[turn % len(_CHANNEL_TURNS)],
                                    channel.window)
                turn += 1
    return [channel.described(brightest) for channel in named]


def the_image_description(
    profile: AcquisitionProfile,
    *,
    name: str,
    levels: Sequence[LevelGeometry] | None = None,
    channels: Sequence[str | Channel] = (),
    origin_pixels: Mapping[str, float] | None = None,
    seconds_between_timepoints: float = A_SECOND,
    smaller_copies_made_by: str = "mean",
    time_unit: str = "second",
) -> dict:
    """Build the whole ``ome`` description for one position, without writing it.

    Kept apart from the writing so that it can be read, printed and checked on
    its own. Nothing here touches the disk.

    Args:
        profile: the sealed description of how this kind of acquisition is
            written. It supplies the axes, the voxel size and the list of
            zoomed-out levels.
        name: what to call this picture. A reader shows it when it has nothing
            better, so the position's own identifier is the useful thing to pass.
        levels: the pyramid levels to describe. By default this is the profile's
            complete canonical pyramid; a virtual view may pass its advertised
            subset without changing the sealed profile.
        channels: the colours of light the run records, either as plain names or
            as prepared :class:`zmart_storage.canvas.Channel` values. A run that
            knows roughly how bright its images are should pass prepared channels
            with a brightness window, or the position opens looking almost black.
        origin_pixels: where this position's first voxel sits, counted in
            full-resolution pixels from the corner of the run. Left out, the
            image says nothing about where it sits, which is the honest answer
            for a single position that was never part of a mosaic.
        seconds_between_timepoints: how long one step along the time axis lasts.
        smaller_copies_made_by: how the zoomed-out copies were built, either
            ``"mean"`` or ``"nearest"``. See :data:`HOW_THE_COPIES_WERE_MADE`.
        time_unit: what the time axis is measured in.

    Returns:
        The description, ready to be written under the ``ome`` key of the
        position's own ``zarr.json``.

    Raises:
        ZmartLiveError: when the profile cannot be described as an OME-Zarr image
            at all, or when it advertises no zoomed-out levels, or when the way
            the copies were made is not one this module knows how to state.
    """
    if smaller_copies_made_by not in HOW_THE_COPIES_WERE_MADE:
        raise ZmartLiveError(
            f"'{smaller_copies_made_by}' is not a way of building the smaller "
            f"copies that this module knows how to describe. Use one of "
            f"{sorted(HOW_THE_COPIES_WERE_MADE)}. Saying nothing is not an option: "
            f"a reader that assumed averaging would trust a zoomed-out picture "
            f"more than it should."
        )
    described_levels = tuple(profile.levels if levels is None else levels)
    if not described_levels:
        raise ZmartLiveError(
            "This profile advertises no zoomed-out levels at all, so there is no "
            "picture to describe. Every image has to list at least its "
            "full-resolution copy."
        )

    axes = the_axes(profile, time_unit=time_unit)

    datasets = []
    for level in described_levels:
        # The scale first and the translation second, always and in that order.
        # The offset is given as a real distance rather than as a count of
        # voxels, so a reader applies it after the scale; the two written the
        # other way round put the picture a whole run's width from where it
        # belongs.
        placing = [
            {
                "type": "scale",
                "scale": _how_far_one_step_reaches(
                    profile, level, seconds_between_timepoints=seconds_between_timepoints
                ),
            }
        ]
        if origin_pixels is not None:
            placing.append(
                {
                    "type": "translation",
                    "translation": _where_the_corner_sits(profile, origin_pixels),
                }
            )
        datasets.append({"path": str(level.level), "coordinateTransformations": placing})

    made = HOW_THE_COPIES_WERE_MADE[smaller_copies_made_by]
    multiscale = {
        "name": name,
        "axes": axes,
        "type": smaller_copies_made_by,
        "metadata": dict(made),
        "datasets": datasets,
    }
    # Where the picture sits is stated beside each copy, in the datasets above,
    # and deliberately nowhere else. The format allows a second statement here
    # for the image as a whole, and a reader applies that one on top of the
    # first, so writing both would place the specimen at twice its real distance
    # from the origin — a mistake that looks perfectly reasonable in the file and
    # only shows up when two acquisitions fail to line up.

    described = {
        "version": OME_ZARR_VERSION,
        "multiscales": [multiscale],
    }
    if channels:
        described["omero"] = {
            "channels": the_channels_described(channels, profile.dtype)
        }
    return described


def _write_over_carefully(target: Path, text: str) -> None:
    """Replace a file's contents in a way an interruption cannot leave half-done.

    The new text is written to a temporary file beside the old one and then
    renamed over it. Renaming a file into place is a single step as far as the
    filesystem is concerned, so a reader looking at the same moment sees either
    the whole old description or the whole new one, never a truncated mixture.
    That matters here because the file being replaced is what tells zarr the
    folder holds a picture at all: half of it is not a slightly wrong image, it
    is no image.
    """
    beside = target.with_name(target.name + ".writing")
    beside.write_text(text, encoding="utf-8")
    # The rename is retried through a short patience, because on Windows a
    # viewer's open handle on the old description makes it fail as ``Access is
    # denied`` for a few milliseconds — and these descriptions are rewritten on
    # every commit while a live viewer reads them over and over.
    written_despite_brief_holds(lambda: os.replace(beside, target))


def _name_the_dimensions_of(level_folder: Path, axes: Sequence[dict]) -> None:
    """Write the axis names into one zoomed-out copy's own description.

    OME-Zarr 0.5 requires this and is explicit about it: the names "MUST be
    included in the zarr.json of the Zarr array of a multiscale level and MUST
    match the names in the axes metadata". It is also plainly useful. Without it
    somebody who opens a single level on its own — which is exactly what an
    analysis script does — has five anonymous dimensions and no way to tell depth
    from time.

    The names are added to the description the array already has, rather than the
    array being made again. Remaking it would mean rewriting every voxel, and
    there is nothing wrong with the voxels.
    """
    description_file = level_folder / "zarr.json"
    if not description_file.is_file():
        raise ZmartLiveError(
            f"The copy at {level_folder} has no description of its own, so there "
            f"is no array there to name the dimensions of. Either it was never "
            f"written or the write did not finish."
        )
    held = json.loads(description_file.read_text(encoding="utf-8"))
    if held.get("node_type") != "array":
        raise ZmartLiveError(
            f"{level_folder} is not an array but a {held.get('node_type')!r}. A "
            f"zoomed-out copy of a picture has to be an array of voxels."
        )
    names = [axis["name"] for axis in axes]
    if len(held.get("shape", ())) != len(names):
        raise ZmartLiveError(
            f"The copy at {level_folder} has {len(held.get('shape', ()))} "
            f"dimensions, and the profile describes {len(names)} axes {names}. "
            f"The two have to agree, or a reader cannot tell which dimension is "
            f"which, and the image will not open."
        )
    held["dimension_names"] = names
    _write_over_carefully(description_file, json.dumps(held, indent=2))


def describe_the_position(
    store: Path | str,
    profile: AcquisitionProfile,
    *,
    name: str | None = None,
    levels: Sequence[LevelGeometry] | None = None,
    channels: Sequence[str | Channel] = (),
    origin_pixels: Mapping[str, float] | None = None,
    seconds_between_timepoints: float = A_SECOND,
    smaller_copies_made_by: str = "mean",
    time_unit: str = "second",
) -> dict:
    """Turn a folder of already-written arrays into a proper OME-Zarr image.

    Call this once the position's full-resolution copy and every zoomed-out copy
    the profile promises have been written. It reads none of the pixels and
    changes none of them. What it adds is the description that makes the folder
    an image: the mark at the top saying this is a group of arrays, the axes and
    their units, the voxel size and corner beside each copy, and the dimension
    names inside each copy.

    Running it twice over the same position is harmless and simply writes the
    same description again, which is what you want if a run is resumed.

    Args:
        store: the position's folder, the one named ``<something>.ome.zarr``.
        profile: the sealed description of how this kind of acquisition is
            written.
        name: what to call this picture. Defaults to the folder's own name with
            the ``.ome.zarr`` ending taken off, which for a live run is the
            position's identifier.
        levels: the pyramid levels present below ``store``. By default every
            canonical level in the profile is required and described.
        channels: the colours of light the run records, as names or as prepared
            :class:`zmart_storage.canvas.Channel` values.
        origin_pixels: where this position's first voxel sits, counted in
            full-resolution pixels from the corner of the run. For a live run
            this is ``layout.placement(position_id).origin``. Left out, the image
            says nothing about where it sits.
        seconds_between_timepoints: how long one step along the time axis lasts.
        smaller_copies_made_by: how the zoomed-out copies were built, either
            ``"mean"`` or ``"nearest"``.
        time_unit: what the time axis is measured in.

    Returns:
        The description that was written, so a caller can log it or check it.

    Raises:
        ZmartLiveError: when the folder is not there, when a copy the profile
            promises has not been written, or when the profile cannot be
            described as an OME-Zarr image at all. Nothing is written in any of
            those cases, because an image that lists a copy which is not there
            fails later, somewhere else, in a way nobody can trace back to here.
    """
    store = Path(store)
    if not store.is_dir():
        raise ZmartLiveError(
            f"There is no position at {store}, so there is nothing to describe. "
            f"The pixels are written first and described afterwards, so this is "
            f"usually a sign that the writing has not happened yet."
        )

    described_levels = tuple(profile.levels if levels is None else levels)
    missing = [
        level.level
        for level in described_levels
        if not (store / str(level.level)).is_dir()
    ]
    if missing:
        raise ZmartLiveError(
            f"The position at {store} promises zoomed-out copies at levels "
            f"{[level.level for level in described_levels]}, but {missing} have not "
            f"been written. An image that lists a copy nobody can find is worse "
            f"than one that is plainly unfinished: it opens, and then fails when "
            f"somebody zooms out."
        )

    described = the_image_description(
        profile,
        name=name if name is not None else _the_plain_name_of(store),
        levels=described_levels,
        channels=channels,
        origin_pixels=origin_pixels,
        seconds_between_timepoints=seconds_between_timepoints,
        smaller_copies_made_by=smaller_copies_made_by,
        time_unit=time_unit,
    )

    # The copies are named first and the image declared second, and the order is
    # deliberate. If this were interrupted halfway, the harm of arrays that carry
    # their dimension names while nothing yet claims to be an image is nil — the
    # folder is exactly as unopenable as it was. The other way round leaves
    # something that announces itself as a proper image and is not one, which is
    # the sort of half-truth that travels.
    axes = described["multiscales"][0]["axes"]
    for level in described_levels:
        _name_the_dimensions_of(store / str(level.level), axes)

    # Opened rather than created, and never with ``mode="w"``. Creating would
    # empty the folder first, and everything this run has imaged at this position
    # is inside it.
    group = zarr.open_group(str(store), mode="a", zarr_format=3)
    # Zarr replaces the group's own description atomically underneath this
    # assignment, and that replacement meets the same reader's-hold refusal on
    # Windows as every other per-commit metadata rewrite, so it gets the same
    # short patience.
    written_despite_brief_holds(lambda: group.attrs.__setitem__("ome", described))
    return described


def _the_plain_name_of(store: Path) -> str:
    """A position's folder name without the ``.ome.zarr`` ending on it."""
    suffix = ".ome.zarr"
    return store.name[: -len(suffix)] if store.name.endswith(suffix) else store.name
