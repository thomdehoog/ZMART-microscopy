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

import json
import math
import re
import shutil
import uuid
from pathlib import Path

import numpy as np

from zmart_storage.canvas import Channel, _declare_one
from zmart_storage.positions import how_many_copies_a_position_can_keep

#: The chunk edge in y and x, matching the run stores zmart_storage writes.
PIECE = 128

#: Metres and friends, as OME spells them, into micrometres. OME's default
#: unit for a physical size is µm, so a missing unit multiplies by one.
_TO_UM = {"m": 1e6, "mm": 1e3, "µm": 1.0, "um": 1.0, "nm": 1e-3, "": 1.0}


def position_store_from_record(record: dict, into: Path | str) -> Path:
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
    z_model = _the_z_model(record, planes)
    dz = z_model["source_local"]["spacing_um"]
    corner_um = _the_corner_of(
        planes,
        (ny, nx),
        pixel_size_um,
        z_origin_um=-z_model["display_anchor"]["voxel_index"] * dz,
    )

    into = Path(into)
    into.mkdir(parents=True, exist_ok=True)
    # The store's name leads with the acquisition type, the way the run
    # writers name theirs (``overview_pos00000.ome.zarr``): the viewer reads
    # which stores belong together off the names, and a store named only by
    # its position would stand under a heading of its own.
    kind = record.get("acquisition_type") or "capture"
    published = into / f"{kind}_{record['position_label']}.ome.zarr"
    # Written somewhere the viewer is not looking, and moved into place only
    # once every level is filled. The viewer watches ``positions/<type>`` and
    # shows a store the moment its description exists, so a store filled in
    # place was visible while its coarser copies were still empty: the
    # picture asked for a zoomed-out copy, was told there was none, and
    # showed a hole until it happened to ask again. Renaming a finished
    # folder is one step the file system does whole, so the viewer now sees
    # either nothing or the complete store, never something in between.
    store = _a_place_to_write(into, published.name)

    depth_max = _the_depth_of(volume.dtype)
    tile_shape = (nz, ny, nx)
    arrays = _declare_one(
        store,
        canvas_shape=tile_shape,
        frames=frames,
        channels=channels,
        dtype=str(volume.dtype),
        chunk=PIECE,
        levels=how_many_copies_a_position_can_keep(tile_shape, PIECE),
        voxel_size_um=(dz, pixel_size_um[0], pixel_size_um[1]),
        origin_um=corner_um,
        # Each channel opens on a window measured from its own pixels — the
        # pixels are already in hand, so this costs nothing. Declaring the
        # camera's whole range instead is honest but useless on screen: a
        # real acquisition sits in the bottom few per cent of it, and the
        # picture opened very nearly black.
        channel_blocks=[
            Channel(
                f"channel {index}",
                window=_a_window_onto(volume[:, index], depth_max),
            ).described(depth_max)
            for index in range(channels)
        ],
        ome_zarr_version="0.5",
    )
    description_path = store / "zarr.json"
    description = json.loads(description_path.read_text(encoding="utf-8"))
    description.setdefault("attributes", {})["zmart_microscopy"] = {
        "z_coordinate": z_model,
    }
    description_path.write_text(json.dumps(description, indent=2), encoding="utf-8")

    # Fill the levels from the finest down, keeping every second voxel along
    # y and x — the run stores' own convention, declared in their description.
    shrinking = volume
    for level, array in enumerate(arrays):
        if level:
            shrinking = shrinking[..., ::2, ::2]
        array[:] = shrinking
    return _publish(store, published)


def _a_place_to_write(into: Path, name: str) -> Path:
    """A folder beside the acquisition's positions where a store can be built.

    It sits next to the watched folder rather than inside it, so nothing the
    viewer lists can ever be half-written. Its name says what it is, so a
    folder left behind by a crash is recognisable and safe to delete.
    """
    staging = into.parent / f".writing-{into.name}"
    staging.mkdir(parents=True, exist_ok=True)
    return staging / f"{name}.{uuid.uuid4().hex[:8]}"


def _publish(built: Path, published: Path) -> Path:
    """Move a finished store into the watched folder, replacing an older one.

    A rerun writes the same position again. The old store is moved aside
    first and the new one moved in, two renames rather than a slow delete
    with the name missing in between; the old pixels are removed last.
    """
    retired = None
    if published.exists():
        retired = built.parent / f"{published.name}.retired-{uuid.uuid4().hex[:8]}"
        published.rename(retired)
    built.rename(published)
    if retired is not None:
        shutil.rmtree(retired, ignore_errors=True)
    staging = built.parent
    try:
        staging.rmdir()  # only succeeds once nothing else is being written
    except OSError:
        pass
    return published


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


def _the_z_model(record: dict, planes: list[dict]) -> dict:
    """The reversible 2-D display anchor and untouched acquisition-Z evidence.

    Array order comes from the record's z indices. Its signed spacing is kept:
    a stack acquired downwards remains a downward stack. The one placement
    operation maps an explicitly resolved source-local voxel centre to display
    z=0; raw stage/focus Z is provenance, never asserted to be specimen Z.
    """
    numbered = sorted({int(plane.get("z", 0)) for plane in planes})
    centres: list[float | None] = []
    for number in numbered:
        found = [
            float(plane["z_um"])
            for plane in planes
            if int(plane.get("z", 0)) == number
            and plane.get("z_um") is not None
            and math.isfinite(float(plane["z_um"]))
        ]
        centres.append(float(np.median(found)) if found else None)

    known = [(index, value) for index, value in enumerate(centres) if value is not None]
    adjacent_steps = [
        centres[index + 1] - centres[index]
        for index in range(len(centres) - 1)
        if centres[index] is not None and centres[index + 1] is not None
    ]
    spacing = float(np.median(adjacent_steps)) if adjacent_steps else 1.0
    if not math.isfinite(spacing) or spacing == 0:
        spacing = 1.0

    requested = record.get("requested_position_um") or record.get("position") or {}
    requested_z = requested.get("z") if isinstance(requested, dict) else None
    if requested_z is not None:
        requested_z = float(requested_z)
        if not math.isfinite(requested_z):
            requested_z = None

    if len(numbered) == 1:
        anchor = 0
        resolved_by = "only-voxel-center"
        legacy_fallback = False
    elif requested_z is not None and known:
        anchor = min(known, key=lambda item: abs(item[1] - requested_z))[0]
        resolved_by = "requested-stage-focus-z"
        legacy_fallback = False
    else:
        # Old records do not state which stack plane was the reference. Resolve
        # their historical middle-plane convention once, write that decision
        # into the store, and never let Viewer source arrival order choose it.
        anchor = len(numbered) // 2
        resolved_by = "legacy-middle-plane"
        legacy_fallback = True

    return {
        "model": "zmart-microscopy-2d-display-anchor-v1",
        "presentation": "2d-overlay",
        "display_anchor": {
            "axis": "z",
            "voxel_index": anchor,
            "coordinate_um": 0.0,
            "resolved_by": resolved_by,
            "legacy_fallback": legacy_fallback,
        },
        "source_local": {
            "plane_order": numbered,
            "spacing_um": spacing,
            "unit": "micrometer",
            "axis_direction": (
                "single-plane" if len(numbered) == 1
                else "increasing" if spacing > 0
                else "decreasing"
            ),
        },
        "acquisition_provenance": {
            "raw_stage_plane_centres_um": centres,
            "requested_stage_focus_z_um": requested_z,
            "unit": "micrometer",
            "registered_specimen_z": False,
        },
    }


def _the_corner_of(
    planes: list[dict],
    frame_yx: tuple[int, int],
    pixel_size_um: tuple[float, float],
    *,
    z_origin_um: float,
) -> tuple[float, float, float]:
    """Where the store's first voxel sits on the stage, in (z, y, x) µm.

    The record's stage point is the centre of the frame; the store's
    convention is the corner of the first voxel along the sample.

    The z origin was resolved once by :func:`_the_z_model`: it maps the chosen
    source-local anchor centre to the shared 2-D display plane without treating
    raw stage/focus Z as registered specimen geometry.
    """
    x_um = float(planes[0].get("x_um") or 0.0)
    y_um = float(planes[0].get("y_um") or 0.0)
    return (
        z_origin_um,
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
