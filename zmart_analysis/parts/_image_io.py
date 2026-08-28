"""
image_io — Image loading shared by the workflow steps.

OME-Zarr and OME-TIFF are read through the same contract, so a step works
the same either way: pick a plane with level / t / c / z and get back a 2D
YX array plus a metadata dict of the same shape.

  * OME-Zarr is read with ngio, which covers NGFF 0.4 and 0.5 behind one
    API. One Zarr per position, axes TCZYX.
  * TIFF is read with tifffile, and its OME-XML with ome-types. Both are
    light and pull nothing else into the step environment. tifffile
    exposes a TIFF as a Zarr array, so both formats reach the same plane
    selection code.
  * skimage covers PNG/JPEG and the sample datasets, and is imported only
    when one of those is actually asked for.

Reads stay lazy in both formats: only the chunks, shards or tiles backing
the requested plane are fetched, so a position costs one plane of memory
rather than the whole TCZYX array, and a z-projection reduces over one
z-stack.

The analysis steps are 2D, so loading always returns a single YX plane.
"""

# Metric length units, for reconciling a stage position recorded in one
# unit against a pixel size recorded in another.
_LENGTH_IN_METERS = {
    "meter": 1.0, "decimeter": 1e-1, "centimeter": 1e-2,
    "millimeter": 1e-3, "micrometer": 1e-6, "nanometer": 1e-9,
    "picometer": 1e-12, "angstrom": 1e-10,
}


def is_ome_zarr(source) -> bool:
    """
    True if `source` looks like a Zarr store rather than an image file.

    Local stores are recognised by their layout, remote ones by suffix.
    Reading a remote store also needs the matching fsspec driver
    installed, s3fs for s3:// or gcsfs for gs://, which the workflow
    environment does not install by default.
    """
    from pathlib import Path

    text = str(source)

    if text.startswith(("s3://", "gs://", "http://", "https://")):
        return ".zarr" in text.lower()

    path = Path(text)
    return path.is_dir() and (
        (path / "zarr.json").exists() or (path / ".zattrs").exists()
    )


def _open_position(source):
    """
    Open one OME-Zarr position.

    Pointing at a plate or a well instead of a position is the easy
    mistake to make, so those get their own message with the positions
    listed. Any other failure is raised untouched.
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


def _resolve_level(container, level):
    """
    Resolve a resolution level to a multiscale dataset path.

    An integer counts levels from full resolution, which works whatever a
    writer named its datasets: "0", "1", ... is only a convention, and
    bioformats2raw and friends use their own. A string is taken as the
    dataset path itself.
    """
    paths = list(container.level_paths)

    text = str(level)
    if text.lstrip("-").isdigit():
        return paths[_bounded(int(text), len(paths), "level")]

    if text in paths:
        return text

    raise ValueError(
        f"Resolution level {level!r} not found. Levels: {', '.join(paths)}"
    )


def _positions_below(source):
    """
    (kind, position paths) if `source` holds positions, else (None, []).

    Covers HCS plates and wells, and the layout bioformats2raw writes,
    where the root carries a marker and the positions are numbered
    subgroups.
    """
    import ngio

    for kind, opener, lister in (
        ("plate", ngio.open_ome_zarr_plate, lambda g: g.images_paths()),
        ("well", ngio.open_ome_zarr_well, lambda g: g.paths()),
    ):
        try:
            return kind, list(lister(opener(str(source))))
        except Exception:
            continue

    try:
        import zarr

        group = zarr.open_group(str(source), mode="r")
        attributes = dict(group.attrs)
        marker = attributes.get("bioformats2raw.layout")
        if marker is None and isinstance(attributes.get("ome"), dict):
            marker = attributes["ome"].get("bioformats2raw.layout")

        if marker is not None:
            # OME holds the metadata document, not an image.
            paths = sorted(name for name in group.group_keys() if name != "OME")
            if paths:
                return "bioformats2raw container", paths
    except Exception:
        pass

    return None, []


def _load_ome_zarr(source, level, t, c, z):
    """Load one YX plane from an OME-Zarr position."""
    import numpy as np

    container = _open_position(source)
    image = container.get_image(path=_resolve_level(container, level))

    projection = _projection_mode(z) if image.has_axis("z") else None

    slicing = {}
    if image.has_axis("t"):
        slicing["t"] = int(t)
    if image.has_axis("z") and projection is None:
        slicing["z"] = _z_index(z, image.dimensions.get("z"))

    axes_order = ("z", "y", "x") if projection else ("y", "x")
    channel = c if image.has_axis("c") else None

    plane = image.get_as_dask(
        channel_selection=channel, axes_order=axes_order, **slicing
    )

    if projection:
        # Reduce lazily, then cast back so downstream steps keep the
        # dtype they would see for a single plane. Integer dtypes are
        # rounded rather than truncated.
        plane = getattr(plane, projection)(axis=0)
        if np.dtype(image.dtype).kind in "iu":
            plane = plane.round()
        plane = plane.astype(image.dtype)

    plane = plane.compute()

    if image.has_axis("c"):
        channel_index = (container.get_channel_idx(c) if isinstance(c, str)
                         else int(c))
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
        "level": _resolve_level(container, level),
        "index": {k: int(v) for k, v in slicing.items()},
        "projection": projection,
        "channel": channel_index,
        "channel_name": (channel_labels[channel_index]
                         if channel_index is not None and channel_labels
                         else None),
        "pixel_size": dict(zip(image.axes, image.dataset.scale)),
        "origin": dict(zip(image.axes, image.dataset.translation)),
        "space_unit": image.space_unit,
    }

    return plane, metadata


def is_tiff(source) -> bool:
    """True if `source` names a TIFF, OME-TIFF included."""
    return str(source).lower().endswith((".tif", ".tiff"))


def _pick_series(tif, series, source):
    """
    Choose one series, which for a multi-position OME-TIFF is one position.

    Mirrors the one-Zarr-per-position rule: when a file holds several
    positions, the caller says which one rather than getting the first.
    """
    names = [s.name or str(i) for i, s in enumerate(tif.series)]

    if series is None:
        if len(tif.series) > 1:
            raise ValueError(
                f"{source} holds {len(tif.series)} positions, so the "
                f"position has to be named: pass series with an index or a "
                f"name.\nPositions: {', '.join(names)}"
            )
        return tif.series[0]

    if isinstance(series, str) and series in names:
        return tif.series[names.index(series)]

    try:
        return tif.series[_bounded(int(series), len(tif.series), "series")]
    except (TypeError, ValueError):
        raise ValueError(
            f"Position {series!r} not found in {source}. "
            f"Positions: {', '.join(names)}"
        ) from None


def _ome_pixels(tif, series_index):
    """The OME-XML Pixels block for one series, or None if there is none."""
    if not tif.is_ome or not tif.ome_metadata:
        return None

    from ome_types import from_xml

    try:
        images = from_xml(tif.ome_metadata).images
    except Exception:
        # Unreadable OME-XML costs the metadata, not the pixels.
        return None

    if series_index >= len(images):
        return None
    return images[series_index].pixels


def _unit_name(unit):
    """ome-types units are enums; report them the way ngio does."""
    if unit is None:
        return None
    return str(getattr(unit, "name", unit)).lower()


def _convert_length(value, from_unit, to_unit):
    """Convert between metric length units, or None if that is not possible."""
    if value is None:
        return None
    if from_unit is None or from_unit == to_unit:
        return float(value)

    source_scale = _LENGTH_IN_METERS.get(from_unit)
    target_scale = _LENGTH_IN_METERS.get(to_unit)
    if not source_scale or not target_scale:
        return None
    return float(value) * source_scale / target_scale


def _tiff_pixel_size(pixels, downsample):
    """
    Pixel size in physical units, scaled for the resolution level.

    Returns ({axis: size}, unit). Empty when the file records no
    physical size, which is the case for a plain TIFF.
    """
    if pixels is None:
        return {}, None

    unit = _unit_name(pixels.physical_size_x_unit)
    sizes = {}

    for axis, value, value_unit, factor in (
        ("y", pixels.physical_size_y, pixels.physical_size_y_unit, downsample),
        ("x", pixels.physical_size_x, pixels.physical_size_x_unit, downsample),
        ("z", pixels.physical_size_z, pixels.physical_size_z_unit, 1.0),
    ):
        converted = _convert_length(value, _unit_name(value_unit), unit)
        if converted is not None:
            sizes[axis] = converted * factor

    return sizes, (unit if sizes else None)


def _tiff_origin(pixels, chosen, unit):
    """
    Stage position of the loaded plane, from the OME Plane entries.

    Acquisitions record it per plane, so the entry matching the selected
    t / c / z is used, falling back to the first one.

    Returns {} when no position was recorded, which means the origin is
    the image corner. Returns None when one was recorded but could not be
    expressed in the same unit as the pixel size: no coordinate is better
    than one that looks like a stage position and is not.
    """
    if pixels is None or not pixels.planes or unit is None:
        return {}

    def matches(plane):
        for key, attribute in (("t", "the_t"), ("c", "the_c"), ("z", "the_z")):
            wanted = chosen.get(key)
            if wanted is not None and getattr(plane, attribute, None) not in (
                    None, wanted):
                return False
        return True

    plane = next((p for p in pixels.planes if matches(p)), pixels.planes[0])

    origin = {}
    for axis, value, value_unit in (
        ("y", plane.position_y, plane.position_y_unit),
        ("x", plane.position_x, plane.position_x_unit),
    ):
        converted = _convert_length(value, _unit_name(value_unit), unit)
        if converted is None:
            if value is not None:
                return None
            continue
        origin[axis] = converted

    return origin


def _load_tiff(source, level, t, c, z, series):
    """Load one YX plane from a TIFF, using its OME-XML when it has one."""
    import tifffile
    import zarr

    with tifffile.TiffFile(str(source)) as tif:
        chosen_series = _pick_series(tif, series, source)
        series_index = list(tif.series).index(chosen_series)
        levels = chosen_series.levels

        try:
            dataset = levels[_bounded(int(level), len(levels), "level")]
        except (TypeError, ValueError):
            raise ValueError(
                f"Resolution level {level!r} not found in {source}, which "
                f"has {len(levels)} level(s)."
            ) from None

        # tifffile hands out a Zarr view of the TIFF, so only the tiles
        # backing the plane are decoded.
        array = zarr.open(dataset.aszarr(), mode="r")
        axes = [letter.lower() for letter in dataset.axes]

        pixels = _ome_pixels(tif, series_index)
        channel_names = ([channel.name for channel in pixels.channels
                          if channel.name] if pixels else [])

        plane, chosen, projection = _select_plane(
            array, axes, t, c, z, channel_names
        )

        downsample = chosen_series.shape[axes.index("y")] / array.shape[
            axes.index("y")]
        pixel_size, unit = _tiff_pixel_size(pixels, downsample)

        channel_index = chosen.get("c")
        metadata = {
            "source": str(source),
            "format": "ome-tiff" if tif.is_ome else "tiff",
            "ngff_version": None,
            "axes": axes,
            "shape": [int(s) for s in array.shape],
            "dtype": str(array.dtype),
            "level": str(level),
            # The channel is reported on its own, as the OME-Zarr path
            # does, so index holds only the plane coordinates.
            "index": {k: v for k, v in chosen.items() if k != "c"},
            "projection": projection,
            "channel": channel_index,
            "channel_name": (channel_names[channel_index]
                             if channel_index is not None
                             and channel_index < len(channel_names) else None),
            "pixel_size": pixel_size,
            "origin": _tiff_origin(pixels, chosen, unit),
            "space_unit": unit,
        }

        return plane, metadata


def _bounded(index, size, axis):
    """Bounds check one axis index, allowing negative indexing."""
    index = int(index)
    if not -size <= index < size:
        raise ValueError(
            f"Index {index} is out of range for '{axis}' of size {size}."
        )
    return index % size


def _resolve_channel(channel, size, channel_names):
    """Resolve a channel given as an index or as a name from the metadata."""
    if isinstance(channel, str):
        lowered = [name.lower() for name in channel_names]
        if channel.lower() in lowered:
            return lowered.index(channel.lower())
        if channel.lstrip("-").isdigit():
            return _bounded(channel, size, "c")
        raise ValueError(
            f"Channel {channel!r} not found. "
            f"Available: {channel_names or 'the file names no channels'}"
        )
    return _bounded(channel, size, "c")


def _select_plane(array, axes, t, c, z, channel_names):
    """
    Reduce an array to a single YX plane, driven by its axis names.

    Used for the TIFF path; ngio does the equivalent for OME-Zarr.
    Returns (plane, chosen indices, projection mode).
    """
    import numpy as np

    index = [slice(None)] * len(axes)
    chosen = {}
    projection = _projection_mode(z) if "z" in axes else None
    z_position = None
    reduced = 0

    for position, name in enumerate(axes):
        size = array.shape[position]

        if name in ("y", "x"):
            continue

        if name == "z" and projection:
            z_position = position - reduced
            continue

        if name == "z":
            index[position] = _bounded(_z_index(z, size), size, "z")
            chosen["z"] = index[position]
        elif name == "c":
            index[position] = _resolve_channel(c, size, channel_names)
            chosen["c"] = index[position]
        elif name == "t":
            index[position] = _bounded(t, size, "t")
            chosen["t"] = index[position]
        elif name == "s" and size > 1:
            raise ValueError(
                f"This is a {size}-sample (RGB) image. The steps here work "
                f"on a single greyscale plane; split the samples into "
                f"channels first."
            )
        else:
            index[position] = 0

        reduced += 1

    source_dtype = np.dtype(array.dtype)
    plane = np.asarray(array[tuple(index)])

    if projection:
        plane = getattr(plane, projection)(axis=z_position)
        if source_dtype.kind in "iu":
            plane = plane.round()
        plane = plane.astype(source_dtype)

    if plane.ndim != 2:
        raise ValueError(
            f"Expected a 2D plane, got shape {plane.shape} from axes {axes}."
        )

    return plane, chosen, projection


def _projection_mode(z):
    """The projection z asks for, or None if it names a single plane."""
    if isinstance(z, str) and z.lower() in ("max", "mean"):
        return z.lower()
    return None


def _z_index(z, n_z):
    """Resolve z to a plane index."""
    if z is None or (isinstance(z, str) and z.lower() == "mid"):
        return n_z // 2
    try:
        return int(z)
    except (TypeError, ValueError):
        raise ValueError(
            f"Unknown z selection {z!r}. Use an index, \"mid\", or a "
            f"projection: \"max\" or \"mean\"."
        ) from None


def _basic_metadata(source, fmt, image):
    """Metadata for inputs that carry no NGFF spatial information."""
    return {
        "source": str(source),
        "format": fmt,
        "ngff_version": None,
        "axes": ["y", "x"],
        "shape": [int(s) for s in image.shape],
        "dtype": str(image.dtype),
        "index": {},
        "projection": None,
        "channel": None,
        "channel_name": None,
        "pixel_size": {},
        "origin": {},
        "space_unit": None,
    }


def load_plane(source, level=0, t=0, c=0, z="mid", series=None):
    """
    Load a single 2D YX plane.

    Parameters
    ----------
    source : str
        One of:
          * a path or URL of an OME-Zarr position (NGFF 0.4 or 0.5).
            A URL needs the matching fsspec driver installed.
          * a path to a TIFF or OME-TIFF
          * a path to a PNG, JPEG or other 2D image file
          * "skimage.<name>", e.g. "skimage.human_mitosis"
    level : int or str
        Resolution level, 0 being full resolution. For OME-Zarr this is
        matched against the multiscale dataset paths, "0", "1", ... by
        convention; for TIFF it indexes the sub-resolutions of a pyramid.
    t : int
        Time point index.
    c : int or str
        Channel index, or a channel name from the OMERO metadata of an
        OME-Zarr or the OME-XML of an OME-TIFF.
    z : int or str
        Z index, "mid" for the middle plane, or "max" / "mean" for a
        projection along z.
    series : int or str, optional
        Which position to read from a TIFF holding several. Required
        when the file holds more than one. Ignored for OME-Zarr, which
        keeps one position per store.

    Axes the image does not have are ignored, so the same parameters work
    across positions of different shapes.

    Returns
    -------
    (numpy.ndarray, dict)
        The plane, and metadata describing where it came from.
    """
    import numpy as np

    text = str(source)

    if text.startswith("skimage."):
        from skimage import data as skimage_data

        name = text.split(".", 1)[1]
        loader = getattr(skimage_data, name, None)
        if not callable(loader) or name.startswith("_"):
            raise ValueError(f"Unknown skimage sample dataset: {name}")
        image = _require_2d(np.asarray(loader()), text)
        return image, _basic_metadata(text, "skimage-sample", image)

    if is_ome_zarr(text):
        return _load_ome_zarr(text, level, t, c, z)

    if is_tiff(text):
        return _load_tiff(text, level, t, c, z, series)

    # PNG, JPEG and friends. skimage is imported here and nowhere else in
    # the file path, so a step environment that only reads microscopy data
    # does not need it.
    from skimage.io import imread

    image = _require_2d(np.asarray(imread(text)), text)
    return image, _basic_metadata(text, "image-file", image)


def _require_2d(image, source):
    """
    Reject anything that is not a single greyscale plane.

    The steps downstream are 2D, so a stack or an RGB image would fail
    later with a much less obvious error. OME-Zarr input picks its plane
    through the level / t / c / z parameters instead.
    """
    if image.ndim != 2:
        raise ValueError(
            f"Expected a single 2D plane, got shape {image.shape} from "
            f"{source}. RGB and multi-dimensional inputs are not supported "
            f"here; convert to OME-Zarr and select a plane with the "
            f"level / t / c / z parameters."
        )
    return image


def to_physical(centroid_y, centroid_x, metadata):
    """
    Map a pixel centroid to physical coordinates for the loaded level.

    Applies the scale and translation of the multiscale dataset, so the
    result is in stage coordinates and directly usable as microscope
    feedback. Returns None when the input carries no spatial metadata.
    """
    pixel_size = metadata.get("pixel_size") or {}
    if "y" not in pixel_size or "x" not in pixel_size:
        return None

    origin = metadata.get("origin")
    if origin is None:
        # A stage position was recorded but could not be reconciled with
        # the pixel size, so there is no coordinate to give.
        return None

    return {
        "y": centroid_y * float(pixel_size["y"]) + float(origin.get("y", 0.0)),
        "x": centroid_x * float(pixel_size["x"]) + float(origin.get("x", 0.0)),
        "unit": metadata.get("space_unit"),
    }


def load_channels(source, channels=None, *, level=0, t=0, z="mid", series=None,
                  max_channels=3):
    """
    Load up to `max_channels` channels of one plane, for a segmenter.

    Cellpose takes a 2D plane or up to three channels of one, so this is
    `load_plane` repeated over channels and stacked channel-last -- the
    shape `select_channels` produces for an array already in memory.

    `channels` chooses which to keep, by index or by name; None takes the
    first `max_channels` the image has. A single channel comes back 2D, so
    a one-channel image is indistinguishable from a plain plane.

    Each channel is a separate lazy read, so a position costs the channels
    asked for rather than its whole TCZYX array.

    Returns
    -------
    (numpy.ndarray, dict)
        The plane or channel stack, and the metadata of its first channel.
    """
    import numpy as np

    first_index = 0 if channels is None else list(channels)[0]
    first, metadata = load_plane(source, level=level, t=t, c=first_index, z=z,
                                 series=series)

    if channels is None:
        axes, shape = metadata.get("axes", []), metadata.get("shape", [])
        available = shape[axes.index("c")] if "c" in axes else 1
        wanted = list(range(min(int(available), max_channels)))
    else:
        wanted = list(channels)
        if not wanted:
            raise ValueError("channels must name at least one channel.")
        if len(wanted) > max_channels:
            raise ValueError(
                f"at most {max_channels} channels, got {len(wanted)}: {wanted}"
            )

    if len(wanted) == 1:
        return first, metadata

    planes = [first] + [
        load_plane(source, level=level, t=t, c=c, z=z, series=series)[0]
        for c in wanted[1:]
    ]
    return np.stack(planes, axis=-1), metadata
