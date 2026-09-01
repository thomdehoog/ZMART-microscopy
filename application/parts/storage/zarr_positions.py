"""Each capture becomes one OME-Zarr 0.5 position, beside the vendor's files.

The instrument writes what it writes — LAS X's autosave leaves OME-TIFFs, and
fighting a vendor's own export is a losing game — so the vendor's files are
used as well as possible and then, the moment a capture lands, converted into
the run's canonical form: **one OME-Zarr 0.5 image per position, axes
t/c/z/y/x**, its stage corner recorded inside it where nobody can rename it
away. The TIFFs stay untouched in ``data/``; the positions stand in
``positions/`` beside them.

One folder per acquisition type, holding nothing but position stores, is
exactly the shape the ZMART viewer opens as one acquisition — the overview,
the focussing, and the target scans each become a source of their own, and the
viewer links a folder's positions into one picture without copying a voxel.

The declaration of the store is not done here: :func:`zmart_storage.canvas`
already writes the five axes, the per-level scale and translation, and the
channel description, and saying any of that twice is how the two copies drift.
This module only reads the vendor's planes into the declared arrays and shrinks
them level by level, keeping every second voxel the way the whole linked
arrangement requires.

What the vendor's file does not say, the run's record does: a TIFF's OME block
carries the pixel size, but where a capture was taken comes from the record's
own planes (``x_um``/``y_um``/``z_um``), because the acquisition is the only
party that knows. The image axes are taken to lie along the stage axes — the
same single-place assumption as ``detection.IMAGE_TO_STAGE`` — and the
recorded stage point is the centre of the frame, so the corner written into
the store is half a frame up and left of it.

Author: Thom de Hoog (ZMB, University of Zurich).
License: MIT
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from application.parts.storage.acquisition_description import (
    AcquisitionDescriptionError,
    ome_channel_blocks,
    read_acquisition_description,
    validate_acquisition_description,
)
from zmart_storage.canvas import Channel, _declare_one
from zmart_storage.positions import how_many_copies_a_position_can_keep

#: The chunk edge in y and x, matching the run stores zmart_storage writes.
PIECE = 128

#: How small a position's smallest copy of itself is allowed to get, in voxels
#: along its shorter side.
#:
#: A folder of positions is linked into one picture by pointing at the copies
#: the positions already keep, so **the picture has exactly as many zoomed-out
#: copies as a single position does**. Left to the chunk size, a 256-voxel
#: field keeps two — itself and a half-size copy — and that is ample for
#: looking at one well and hopeless for looking at a plate: ninety-six wells
#: across a screen is about a hundred and sixty micrometres to a screen pixel,
#: where the coarsest copy of a 4 µm field offers eight. The engine then draws
#: the whole plate out of the second-finest copy, which is some thousands of
#: pieces of picture, each composed on demand; most never arrive, and a plate
#: that is entirely imaged looks half empty.
#:
#: Shrinking to eight voxels gives a field six copies instead of two, so the
#: coarsest is 128 µm to the voxel and a whole plate is a few dozen pieces
#: rather than thousands. The copies cost a third of the field again in disk,
#: which is the usual price of a pyramid and is small beside the TIFFs the
#: instrument already wrote.
#:
#: **What this rests on.** Shrinking keeps every second voxel rather than
#: averaging four, so a voxel of a coarse copy belongs to exactly one position
#: — that is what lets the picture point at the positions instead of writing
#: its own copies. It holds only while each position begins on a whole number
#: of coarse voxels, which for a run laid out on a grid it does. A run whose
#: stage has drifted off the grid is the open question in the viewer's
#: `PLAN_showing_many_stores_as_one.md`, and it is no more open now than it
#: was: this makes the same arrangement reach further out, it does not change
#: what the arrangement assumes.
THE_SMALLEST_COPY_WORTH_KEEPING = 8

#: Metres and friends, as OME spells them, into micrometres. OME's default
#: unit for a physical size is µm, so a missing unit multiplies by one.
_TO_UM = {"m": 1e6, "mm": 1e3, "µm": 1.0, "um": 1.0, "nm": 1e-3, "": 1.0}


def position_store_from_record(
    record: dict, into: Path | str, *, acquisition_description: dict | None = None
) -> Path:
    """Write one OME-Zarr 0.5 position from a capture's record, and return it.

    ``record`` is what the driver's acquire returned — its ``planes`` name the
    vendor's files and where each was taken. ``into`` is the acquisition's
    ``positions`` folder; the store lands there as
    ``<position_label>.ome.zarr``, an ordinary OME-Zarr image that opens on
    its own in napari, Fiji, or the ZMART viewer.
    """
    planes = record.get("planes") or []
    if not planes:
        raise RuntimeError("the capture reported no planes, so there is nothing to keep")

    volume, pixel_size_um = _the_volume_of(planes)
    frames, channels, nz, ny, nx = volume.shape
    dz = _the_z_step_of(planes)
    corner_um = _the_corner_of(planes, (ny, nx), pixel_size_um)

    into = Path(into)
    into.mkdir(parents=True, exist_ok=True)
    # The store's name leads with the acquisition type, the way the run
    # writers name theirs (``overview_pos00000.ome.zarr``): the viewer reads
    # which stores belong together off the names, and a store named only by
    # its position would stand under a heading of its own.
    kind = record.get("acquisition_type") or "capture"
    store = into / f"{kind}_{record['position_label']}.ome.zarr"

    depth_max = _the_depth_of(volume.dtype)
    try:
        published = read_acquisition_description(into, channel_count=channels)
        description = acquisition_description
        if description is not None:
            description = validate_acquisition_description(
                description, acquisition_type=kind, channel_count=channels
            )
            if published is None:
                raise ValueError(
                    "an acquisition description was supplied for a position, but the "
                    "run-start publisher has not created zmart-acquisition.json"
                )
            if published != description:
                raise ValueError(
                    "the position's acquisition description differs from the published "
                    "run-start contract"
                )
        else:
            description = published
    except ValueError as exc:
        raise AcquisitionDescriptionError(
            f"the {kind!r} acquisition display contract cannot describe this position: {exc}"
        ) from exc

    local_windows = [
        _a_window_onto(volume[:, index], depth_max) for index in range(channels)
    ]
    channel_blocks = (
        ome_channel_blocks(
            description,
            depth_max=depth_max,
            # Kept deliberately during M1. The acquisition sidecar is the
            # composed Viewer's authority; this local value keeps older readers
            # usable until M2/M3 can remove it safely.
            fallback_windows=local_windows,
        )
        if description is not None
        else [
            Channel(f"channel {index}", window=local_windows[index]).described(depth_max)
            for index in range(channels)
        ]
    )
    tile_shape = (nz, ny, nx)
    arrays = _declare_one(
        store,
        canvas_shape=tile_shape,
        frames=frames,
        channels=channels,
        dtype=str(volume.dtype),
        chunk=PIECE,
        levels=how_many_copies_a_position_can_keep(
            tile_shape, THE_SMALLEST_COPY_WORTH_KEEPING,
        ),
        voxel_size_um=(dz, pixel_size_um[0], pixel_size_um[1]),
        origin_um=corner_um,
        # Each channel opens on a window measured from its own pixels — the
        # pixels are already in hand, so this costs nothing. Declaring the
        # camera's whole range instead is honest but useless on screen: a
        # real acquisition sits in the bottom few per cent of it, and the
        # picture opened very nearly black.
        channel_blocks=channel_blocks,
        ome_zarr_version="0.5",
    )

    # Fill the levels from the finest down, keeping every second voxel along
    # y and x — the run stores' own convention, declared in their description.
    shrinking = volume
    for level, array in enumerate(arrays):
        if level:
            shrinking = shrinking[..., ::2, ::2]
        array[:] = shrinking
    return store


# -- reading what the vendor wrote ------------------------------------------


def _the_volume_of(planes: list[dict]) -> tuple[np.ndarray, tuple[float, float]]:
    """The capture as one ``(t, c, z, y, x)`` array, and its (y, x) µm/voxel.

    The vendor may have written one file per plane or one file for the whole
    capture — the record's plane entries say which slot each file (or slice of
    a file) fills, so both arrive the same way here.
    """
    import tifffile

    files: dict[str, tifffile.TiffFile] = {}
    try:
        for plane in planes:
            path = str(plane["path"])
            if path not in files:
                files[path] = tifffile.TiffFile(path)

        first = files[str(planes[0]["path"])]
        pixel_size_um = _the_pixel_size_of(first.ome_metadata or "")

        # The vendor's own numbering is packed down to 0..n-1 per axis: a
        # Leica job numbers its channels from 1, and taking the numbers as
        # array indices left channel 0 an empty black plane.
        frames = _packed(planes, "t")
        channels = _packed(planes, "c")
        depth = _packed(planes, "z")

        volume: np.ndarray | None = None
        for plane in planes:
            held = files[str(plane["path"])]
            image = _one_plane_of(held, plane)
            if volume is None:
                volume = np.zeros(
                    (len(frames), len(channels), len(depth), *image.shape),
                    dtype=image.dtype,
                )
            volume[
                frames[int(plane.get("t", 0))],
                channels[int(plane.get("c", 0))],
                depth[int(plane.get("z", 0))],
            ] = image
        assert volume is not None  # planes was checked non-empty above
        return volume, pixel_size_um
    finally:
        for held in files.values():
            held.close()


def _packed(planes: list[dict], axis: str) -> dict[int, int]:
    """The vendor's numbers along one axis, packed down to 0..n-1 in order."""
    seen = sorted({int(p.get(axis, 0)) for p in planes})
    return {number: index for index, number in enumerate(seen)}


def _one_plane_of(held, plane: dict) -> np.ndarray:
    """One y/x image out of a vendor file, whichever axes the file declares."""
    series = held.series[0]
    axes = series.axes.upper()
    data = series.asarray()
    if axes == "YX":
        return data
    # Everything before the trailing YX is indexed by the record's own
    # numbers; an axis the record does not speak of would be silently
    # mis-sliced, so it is refused by name instead.
    if not axes.endswith("YX"):
        raise RuntimeError(f"the vendor file's axes are {axes!r}, which do not end in YX")
    taken = {"T": int(plane.get("t", 0)), "C": int(plane.get("c", 0)), "Z": int(plane.get("z", 0))}
    index = []
    for axis in axes[:-2]:
        if axis not in taken:
            raise RuntimeError(
                f"the vendor file declares a {axis!r} axis the record says nothing about"
            )
        index.append(taken[axis])
    return data[tuple(index)]


def _the_pixel_size_of(ome_xml: str) -> tuple[float, float]:
    """The (y, x) µm per voxel, read from the vendor's own OME description.

    A file that says nothing gets 1 µm — honest enough to draw, and plainly
    wrong enough to notice — rather than a refusal that would cost the pixels.
    """

    def one(name: str) -> float:
        size = re.search(rf'PhysicalSize{name}="([^"]+)"', ome_xml)
        if not size:
            return 1.0
        unit = re.search(rf'PhysicalSize{name}Unit="([^"]+)"', ome_xml)
        return float(size.group(1)) * _TO_UM.get(unit.group(1) if unit else "", 1.0)

    return one("Y"), one("X")


def _the_z_step_of(planes: list[dict]) -> float:
    """The µm between two z planes, from the recorded heights; 1 µm when flat."""
    heights = sorted({float(p.get("z_um") or 0.0) for p in planes if p.get("z_um") is not None})
    if len(heights) < 2:
        return 1.0
    steps = np.diff(heights)
    return float(np.median(steps))


def _the_corner_of(
    planes: list[dict], frame_yx: tuple[int, int], pixel_size_um: tuple[float, float]
) -> tuple[float, float, float]:
    """Where the store's first voxel sits on the stage, in (z, y, x) µm.

    The record's stage point is the centre of the frame; the store's
    convention is the corner of the first voxel. So half a frame comes off
    each of the two axes that lie along the sample.

    **Every position begins at height nought, and that is deliberate.** The
    height a capture was taken at is kept — it is in the run's record and in
    the vendor's own files — but it is not written into the store as where
    the picture *sits*, and this is the single most important line in this
    module for whether an operator ever sees their scan.

    Here is what happens if the measured height is written in. A scan follows
    the focus map, so each position is taken at a slightly different height:
    on a plate of six wells that is a couple of dozen distinct heights across
    fifty-four fields. The viewer links a folder of positions into one
    picture by laying each store where it says it sits — along depth as much
    as across the sample — so a *flat* scan composes into a stack twenty-two
    planes deep, holding two or three fields on each plane. The canvas shows
    one plane at a time. So the operator sees two fields out of fifty-four,
    or none, with nothing on screen to say why: every file is present, every
    layer is placed correctly, and the picture is simply somewhere else in
    depth. That was measured on the mock instrument, and it is what "the
    overview never shows up" turned out to be.

    Beginning every position at nought puts a flat scan on one plane, which
    is what a map of a plate is. A focus stack keeps its own planes and
    spans them from nought, so stepping through the depth still walks the
    stack. What is lost is the *stored* height of a capture, which no part of
    the viewer uses; what is gained is a scan the operator can see.
    """
    x_um = float(planes[0].get("x_um") or 0.0)
    y_um = float(planes[0].get("y_um") or 0.0)
    return (
        0.0,
        y_um - frame_yx[0] * pixel_size_um[0] / 2.0,
        x_um - frame_yx[1] * pixel_size_um[1] / 2.0,
    )


def _a_window_onto(channel: np.ndarray, depth_max: int) -> tuple[int, int]:
    """The brightness range this channel should first be shown with.

    The darkest percentile to just past the brightest, so a stray hot pixel
    cannot stretch the window and flatten everything else. A channel with
    nothing in it (all one value) falls back to the camera's whole range —
    a degenerate window is refused by readers.
    """
    low, high = np.percentile(channel, [1.0, 99.9])
    low, high = int(low), int(np.ceil(high))
    if high <= low:
        return (0, depth_max)
    return (low, min(high, depth_max))


def _the_depth_of(dtype: np.dtype) -> int:
    """The brightest value the dtype can hold, for the channel description."""
    try:
        return int(np.iinfo(dtype).max)
    except ValueError:
        return 65535
