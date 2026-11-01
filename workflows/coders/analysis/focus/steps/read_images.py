"""read_images -- read the planes of a focus stack.

The first step of the focus pipeline. It reads the stack the input names, so
score_focus never opens a file. A plane is read from a TIFF, an OME-TIFF or
an OME-Zarr position.

What the input may name:

    image_paths, z_um      a focus stack, one file per plane, in z order
    image_path             a focus stack in one position that has a z axis

Publishes under ``pipeline_data["read_images"]`` the ``stack`` (planes, rows,
columns) in the file's own data type, with ``z_um`` (given, or taken from the
file; None when neither says) and ``source``, ``level``, ``t``. ``channel``
says which channel was read.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

METADATA = {
    "description": "Read the planes of a focus stack",
    "version": "1.0",
    "max_workers": 1,
    "environment": "ZMART--focus--main",
}

#: Metric length units in metres, to put a z step in the unit of the pixel width.
LENGTH_IN_METERS = {
    "meter": 1.0,
    "decimeter": 1e-1,
    "centimeter": 1e-2,
    "millimeter": 1e-3,
    "micrometer": 1e-6,
    "nanometer": 1e-9,
    "picometer": 1e-12,
    "angstrom": 1e-10,
}


def run(pipeline_data: dict, state: dict, **params) -> dict:

    given = pipeline_data["input"]

    channel = params.get("channel", 0)

    level = params.get("level", 0)

    t = params.get("t", 0)

    # A focus stack: one file per plane, or one position with a z axis
    if not (given.get("image_paths") or given.get("image_path")):
        raise ValueError(
            "read_images found no focus stack in the input. Give image_paths "
            "(one file per plane) or image_path (one position with a z axis)."
        )

    images = _focus_stack(given, channel, level, t)

    images["channel"] = channel

    pipeline_data["read_images"] = images

    return pipeline_data


def _focus_stack(given: dict, channel, level, t) -> dict:
    """The planes of a focus stack, their heights, and where they came from.

    One read per plane, so a stack costs its own planes and not the other
    channels and time points of the position.
    """

    paths = given.get("image_paths")

    if paths:
        if len(paths) < 2:
            raise ValueError(
                f"image_paths is a z-stack in plane order and got {len(paths)} "
                f"path(s); one plane cannot be focused."
            )

        planes = [_load_plane(path, level=level, t=t, c=channel, z=0)[0] for path in paths]

        heights = given.get("z_um")

        source = f"{len(paths)} planes from {paths[0]}"

    else:
        source = str(given["image_path"])

        first, metadata = _load_plane(source, level=level, t=t, c=channel, z=0)

        axes = metadata["axes"]

        if "z" not in axes:
            raise ValueError(
                f"{source} declares axes {axes}, with no z among them, so there "
                f"is no way to tell which axis is depth. A focus stack must say."
            )

        depth = int(metadata["shape"][axes.index("z")])

        planes = [first] + [
            _load_plane(source, level=level, t=t, c=channel, z=z)[0] for z in range(1, depth)
        ]

        heights = given.get("z_um") or _heights_from(metadata, depth)

    return {
        "stack": np.stack(planes),
        "z_um": None if heights is None else [float(z) for z in heights],
        "source": source,
        "level": level,
        "t": t,
    }


def _heights_from(metadata: dict, depth: int) -> list[float] | None:
    """The plane heights from the file's own z spacing and origin, or None.

    None when the file records no z spacing: a made-up height is worse than
    a plane index.
    """

    spacing = metadata["pixel_size"].get("z")

    if not spacing:
        return None

    origin = metadata["origin"].get("z", 0.0) or 0.0

    return [float(origin) + index * float(spacing) for index in range(depth)]


def _load_plane(source, level=0, t=0, c=0, z="mid") -> tuple[np.ndarray, dict]:
    """One 2-D plane of an OME-Zarr position or a TIFF, and what the file says about it.

    ``c`` is a channel index or a channel name. ``z`` is a plane index or
    ``"mid"``. Axes the image does not have are ignored.
    """

    text = str(source)

    if _is_ome_zarr(text):
        return _zarr_plane(text, level, t, c, z)

    if text.lower().endswith((".tif", ".tiff")):
        return _tiff_plane(text, level, t, c, z)

    raise ValueError(f"{source} is neither an OME-Zarr position nor a TIFF.")


def _is_ome_zarr(text: str) -> bool:
    """Whether a path is an OME-Zarr store (a folder holding zarr.json or .zattrs)."""

    path = Path(text)

    return path.is_dir() and ((path / "zarr.json").exists() or (path / ".zattrs").exists())


def _zarr_plane(source, level, t, c, z) -> tuple[np.ndarray, dict]:
    """One plane of an OME-Zarr position, read with ngio."""

    import ngio

    container = ngio.open_ome_zarr_container(source, mode="r", cache=True)

    image = container.get_image(path=_level_path(list(container.level_paths), level))

    picked = {}

    if image.has_axis("t"):
        picked["t"] = int(t)

    if image.has_axis("z"):
        picked["z"] = _z_index(z, image.dimensions.get("z"))

    channel = c if image.has_axis("c") else None

    plane = image.get_as_dask(channel_selection=channel, axes_order=("y", "x"), **picked)

    metadata = {
        "axes": list(image.axes),
        "shape": list(image.shape),
        "pixel_size": dict(zip(image.axes, image.dataset.scale, strict=False)),
        "origin": dict(zip(image.axes, image.dataset.translation, strict=False)),
    }

    return plane.compute(), metadata


def _level_path(paths: list[str], level) -> str:
    """The dataset of a resolution level: a number counts from full resolution, text names it."""

    text = str(level)

    if text.lstrip("-").isdigit():
        return paths[_bounded(text, len(paths), "level")]

    if text in paths:
        return text

    raise ValueError(f"Resolution level {level!r} not found. Levels: {', '.join(paths)}")


def _tiff_plane(source, level, t, c, z) -> tuple[np.ndarray, dict]:
    """One plane of a TIFF or OME-TIFF, read lazily through tifffile's Zarr view."""

    import tifffile
    import zarr

    with tifffile.TiffFile(source) as tif:
        if len(tif.series) > 1:
            raise ValueError(f"{source} holds {len(tif.series)} positions; give one per file.")

        levels = tif.series[0].levels

        dataset = levels[_bounded(level, len(levels), "level")]

        array = zarr.open(dataset.aszarr(), mode="r")

        axes = [letter.lower() for letter in dataset.axes]

        pixels = _ome_pixels(tif)

        names = [one.name for one in pixels.channels if one.name] if pixels else []

        # One index per axis that is not y or x
        index = []

        for position, axis in enumerate(axes):
            size = array.shape[position]

            if axis in ("y", "x"):
                index.append(slice(None))

            elif axis == "z":
                index.append(_bounded(_z_index(z, size), size, "z"))

            elif axis == "c":
                index.append(_channel_index(c, size, names))

            elif axis == "t":
                index.append(_bounded(t, size, "t"))

            elif axis == "s" and size > 1:
                raise ValueError(
                    f"{source} is an RGB image; split the samples into channels first."
                )

            else:
                index.append(0)

        plane = np.asarray(array[tuple(index)])

        metadata = {
            "axes": axes,
            "shape": [int(size) for size in array.shape],
            "pixel_size": _z_spacing(pixels),
            "origin": {},
        }

    return plane, metadata


def _ome_pixels(tif):
    """The OME-XML Pixels block of the first series, or None for a plain TIFF."""

    if not tif.is_ome or not tif.ome_metadata:
        return None

    from ome_types import from_xml

    try:
        return from_xml(tif.ome_metadata).images[0].pixels
    except Exception:
        # Unreadable OME-XML costs the metadata, not the pixels
        return None


def _z_spacing(pixels) -> dict:
    """The z step of an OME-TIFF in the unit of its pixel width, as ``{"z": step}``; ``{}`` without one."""

    if pixels is None or pixels.physical_size_z is None:
        return {}

    z_unit, x_unit = (
        _unit_name(pixels.physical_size_z_unit),
        _unit_name(pixels.physical_size_x_unit),
    )

    if z_unit is None or z_unit == x_unit:
        return {"z": float(pixels.physical_size_z)}

    # A z step in another unit than the pixel width is converted, or left out when it cannot be
    if z_unit not in LENGTH_IN_METERS or x_unit not in LENGTH_IN_METERS:
        return {}

    return {
        "z": float(pixels.physical_size_z) * LENGTH_IN_METERS[z_unit] / LENGTH_IN_METERS[x_unit]
    }


def _unit_name(unit) -> str | None:
    """An OME length unit as a plain name, ``"micrometer"``."""

    return None if unit is None else str(getattr(unit, "name", unit)).lower()


def _channel_index(channel, size: int, names: list[str]) -> int:
    """A channel given as a name from the file, or as an index.

    A name is looked up first, so a channel named "488" is that channel.
    """

    if isinstance(channel, str):
        lowered = [name.lower() for name in names]

        if channel.lower() in lowered:
            return lowered.index(channel.lower())

        if not channel.lstrip("-").isdigit():
            raise ValueError(
                f"Channel {channel!r} not found. Available: {names or 'the file names no channels'}"
            )

    return _bounded(channel, size, "c")


def _z_index(z, depth: int) -> int:
    """A plane index from ``z``: a number, or ``"mid"`` (also None) for the middle plane."""

    if z is None or z == "mid":
        return depth // 2

    return int(z)


def _bounded(index, size: int, axis: str) -> int:
    """An index checked against the size of its axis; negative counts from the end."""

    index = int(index)

    if not -size <= index < size:
        raise ValueError(f"Index {index} is out of range for '{axis}' of size {size}.")

    return index % size
