"""read_images -- read the image an object analysis works on.

The first step of every object-analysis pipeline. It opens the image once, so
no step after it opens a file. The image is an OME-Zarr position, as a ZMART
driver saves one; it is read lazily, so a position costs the planes asked
for, not its whole array.

Takes ``input["image_path"]``, ``channels`` (up to three channels to find the
objects on, by index or name; None for the first three), ``z_selection`` (a
plane index, ``"mid"``, or a projection: ``"max"`` or ``"mean"``), and the other
colours to measure: ``extra_channel_indices`` (channels of the same position).

Publishes under ``pipeline_data["read_images"]``::

    image            the channels to segment: one plane, or channels last
    extra_channels   the other colours, one plane each, for the features
    channels         the channels and z_selection as asked; they are part of
    z_selection      how the segmentation was made
    image_size_px    [width, height]
    pixel_size_um    [x, y], when the file records it in micrometres
    first_pixel_xy_um
                     where the centre of the first pixel lies on the stage,
                     [x, y], as OME-NGFF defines it
    sha256           a digest of the file or position, for the record

``load_plane`` is also how the ZMART interface reads its previews, so a
preview and a detection read a stack the same way.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

METADATA = {
    "description": "Read the image an object analysis works on",
    "version": "1.0",
    "max_workers": 1,
    "environment": "ZMART--target_acquisition_for_coders--classical",
}

# Cellpose takes one plane, or up to three channels of one
MAX_CHANNELS = 3


def run(pipeline_data: dict, state: dict, **params) -> dict:

    given = pipeline_data["input"]

    image_path = given["image_path"]

    channels = given.get("channels", params.get("channels"))

    z_selection = given.get("z_selection", "mid")

    # The channels the objects are found on, and what the file says about them
    image, metadata = _load_channels(image_path, channels, z_selection)

    # The other colours, measured but not segmented
    extra_channels = _extra_channels(given, z_selection)

    pipeline_data["read_images"] = {
        "image": image,
        "extra_channels": extra_channels,
        "channels": channels,
        "z_selection": z_selection,
        "image_size_px": [int(image.shape[1]), int(image.shape[0])],
        "pixel_size_um": _xy_in_micrometres(metadata, "pixel_size"),
        "first_pixel_xy_um": _xy_in_micrometres(metadata, "origin"),
        "sha256": _sha256(image_path),
    }

    return pipeline_data


def _xy_in_micrometres(metadata: dict, key: str) -> list[float] | None:
    """``metadata[key]`` as [x, y] in micrometres; None when the file does not record both."""

    values = metadata.get(key) or {}

    if metadata.get("space_unit") != "micrometer" or "x" not in values or "y" not in values:
        return None

    return [float(values["x"]), float(values["y"])]


def load_plane(source, level=0, t=0, c=0, z="mid"):
    """One 2-D plane of an OME-Zarr position, and what the position says about it.

    ``level`` is the resolution level, 0 for full resolution. ``c`` is a
    channel index or a channel name. ``z`` is a plane index, ``"mid"``, or
    ``"max"`` / ``"mean"`` for a projection along z. Axes the image does not
    have are ignored.

    Returns the plane and a dict: source, format, axes, shape, dtype, level,
    the chosen indices, the projection, the channel and its name, the pixel
    size, the origin and the unit.
    """

    text = str(source)

    if _is_ome_zarr(text):
        return _load_ome_zarr(text, level, t, c, z)

    raise ValueError(f"{source} is not an OME-Zarr position.")


def _load_channels(source, channels, z) -> tuple[np.ndarray, dict]:
    """The channels to segment: one plane, or up to three stacked channels last.

    ``channels`` names them by index or by name; None takes the first three
    the image has. A single channel comes back as a plain 2-D plane. Each
    channel is its own lazy read, so a position costs only the channels
    asked for. The file's metadata, as :func:`load_plane` answers it, comes
    with them.
    """

    first_index = 0 if channels is None else list(channels)[0]

    first, metadata = load_plane(source, c=first_index, z=z)

    if channels is None:
        axes = metadata["axes"]

        available = metadata["shape"][axes.index("c")] if "c" in axes else 1

        wanted = list(range(min(int(available), MAX_CHANNELS)))

    else:
        wanted = list(channels)

        if not wanted:
            raise ValueError("channels must name at least one channel.")

        if len(wanted) > MAX_CHANNELS:
            raise ValueError(f"at most {MAX_CHANNELS} channels, got {len(wanted)}: {wanted}")

    if len(wanted) == 1:
        return first, metadata

    planes = [first] + [load_plane(source, c=channel, z=z)[0] for channel in wanted[1:]]

    return np.stack(planes, axis=-1), metadata


def _extra_channels(given: dict, z_selection) -> list[np.ndarray]:
    """The other colours of the frame, for the features: channels of the same position."""

    indices = given.get("extra_channel_indices") or []

    return [
        np.asarray(load_plane(given["image_path"], c=int(channel), z=z_selection)[0])
        for channel in indices
    ]


def _sha256(path) -> str:
    """A digest of the OME-Zarr position: each file's relative name and bytes, in path order.

    A changed chunk and a moved chunk both give a different digest.
    """

    root = Path(path)

    digest = hashlib.sha256()

    files = sorted(one for one in root.rglob("*") if one.is_file()) if root.is_dir() else [root]

    for file in files:
        if root.is_dir():
            digest.update(file.relative_to(root).as_posix().encode("utf-8"))
            digest.update(b"\0")

        with file.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)

    return digest.hexdigest()


def _is_ome_zarr(source) -> bool:
    """Whether ``source`` is an OME-Zarr store: a folder holding zarr.json or .zattrs."""

    path = Path(str(source))

    return path.is_dir() and ((path / "zarr.json").exists() or (path / ".zattrs").exists())


def _load_ome_zarr(source, level, t, c, z):
    """One plane of an OME-Zarr position, read with ngio, and its metadata."""

    container = _open_position(source)

    level_path = _resolve_level(container, level)

    image = container.get_image(path=level_path)

    projection = _projection_mode(z) if image.has_axis("z") else None

    slicing = {}

    if image.has_axis("t"):
        slicing["t"] = int(t)

    if image.has_axis("z") and projection is None:
        slicing["z"] = _z_index(z, image.dimensions.get("z"))

    # A projection keeps z so it can be reduced
    axes_order = ("z", "y", "x") if projection else ("y", "x")

    channel = c if image.has_axis("c") else None

    plane = image.get_as_dask(channel_selection=channel, axes_order=axes_order, **slicing)

    if projection:
        # Reduce lazily, then cast back to the file's dtype; integers are rounded, not truncated
        plane = getattr(plane, projection)(axis=0)

        if np.dtype(image.dtype).kind in "iu":
            plane = plane.round()

        plane = plane.astype(image.dtype)

    plane = plane.compute()

    if image.has_axis("c"):
        channel_index = container.get_channel_idx(c) if isinstance(c, str) else int(c)
    else:
        channel_index = None

    channel_labels = image.channel_labels

    metadata = {
        "source": str(source),
        "format": "ome-zarr",
        "ngff_version": str(container.meta.version),
        "axes": list(image.axes),
        "shape": list(image.shape),
        "dtype": str(image.dtype),
        "level": level_path,
        "index": {axis: int(value) for axis, value in slicing.items()},
        "projection": projection,
        "channel": channel_index,
        "channel_name": (
            channel_labels[channel_index] if channel_index is not None and channel_labels else None
        ),
        "pixel_size": dict(zip(image.axes, image.dataset.scale, strict=False)),
        "origin": dict(zip(image.axes, image.dataset.translation, strict=False)),
        "space_unit": image.space_unit,
    }

    return plane, metadata


def _open_position(source):
    """Open one OME-Zarr position.

    A plate or a well given instead of a position is the easy mistake, so it
    gets its own message listing the positions. Any other failure is raised
    as it is.
    """

    import ngio

    try:
        return ngio.open_ome_zarr_container(str(source), mode="r", cache=True)

    except ngio.NgioValidationError as error:
        kind, paths = _positions_below(source)

        if not paths:
            raise error

        listed = ", ".join(paths[:8]) + (" ..." if len(paths) > 8 else "")

        raise ValueError(
            f"{source} is an OME-Zarr {kind}, not a position. This workflow "
            f"reads one Zarr per position, so point data_source at one of "
            f"them, for example {str(source).rstrip('/')}/{paths[0]}\n"
            f"Positions: {listed}"
        ) from error


def _positions_below(source):
    """What kind of container ``source`` is and the positions in it, or (None, []).

    Knows HCS plates and wells, and the bioformats2raw layout: a marker on
    the root and the positions as numbered groups below it.
    """

    import ngio

    try:
        plate = ngio.open_ome_zarr_plate(str(source))

        return "plate", list(plate.images_paths())

    except Exception:
        pass

    try:
        well = ngio.open_ome_zarr_well(str(source))

        return "well", list(well.paths())

    except Exception:
        pass

    try:
        import zarr

        group = zarr.open_group(str(source), mode="r")

        attributes = dict(group.attrs)

        marker = attributes.get("bioformats2raw.layout")

        if marker is None and isinstance(attributes.get("ome"), dict):
            marker = attributes["ome"].get("bioformats2raw.layout")

        if marker is not None:
            # The OME group holds the metadata document, not an image
            paths = sorted(name for name in group.group_keys() if name != "OME")

            if paths:
                return "bioformats2raw container", paths

    except Exception:
        pass

    return None, []


def _resolve_level(container, level):
    """The dataset path of a resolution level.

    A whole number counts levels from full resolution, whatever the writer
    named its datasets ("0", "1", ... is only a convention). Text is taken as
    the dataset path itself.
    """

    paths = list(container.level_paths)

    text = str(level)

    if text.lstrip("-").isdigit():
        return paths[_bounded(int(text), len(paths), "level")]

    if text in paths:
        return text

    raise ValueError(f"Resolution level {level!r} not found. Levels: {', '.join(paths)}")


def _projection_mode(z):
    """The projection ``z`` asks for ("max" or "mean"), or None for a single plane."""

    if isinstance(z, str) and z.lower() in ("max", "mean"):
        return z.lower()

    return None


def _z_index(z, n_z):
    """The plane index ``z`` names: a number, or "mid" (also None) for the middle plane."""

    if z is None or (isinstance(z, str) and z.lower() == "mid"):
        return n_z // 2

    try:
        return int(z)

    except (TypeError, ValueError):
        raise ValueError(
            f'Unknown z selection {z!r}. Use an index, "mid", or a projection: "max" or "mean".'
        ) from None


def _bounded(index, size, axis):
    """An index checked against its axis size; a negative one counts from the end."""

    index = int(index)

    if not -size <= index < size:
        raise ValueError(f"Index {index} is out of range for '{axis}' of size {size}.")

    return index % size
