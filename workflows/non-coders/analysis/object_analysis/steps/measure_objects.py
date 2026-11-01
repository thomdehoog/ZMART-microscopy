"""measure_objects -- measure every object the segmentation found.

Takes the label image from ``segment_cellpose`` or ``segment_watershed``, and
the image and its other colours from ``read_images``, and measures each
object: its size and shape, how bright it is in every channel, how far its
neighbours are, and, when asked, its texture. Each measurement is one column,
one value per object, in the order of the labels. ``build_object_table`` turns
them into the table that readers rely on.

The base set is scikit-image's ``regionprops_table``: area, perimeter, axes,
orientation, bounding box, intensity mean, min, max and standard deviation. A
few cheap ratios are always added to it (circularity, aspect ratio, the
integrated intensity). The optional families are chosen with ``extras`` in the
pipeline:

    intensity       global_bg, local_bg      the background around each object
    neighbourhood   neighbours               distances to and counts of neighbours
    texture         gradients, stat_texture, lbp, fft, glrlm
    morphology      rg_spread                radius of gyration

A name may be a family or one of its members, and ``all`` takes every one. The
per-object texture families (lbp, fft, glrlm) loop over every object in Python
and are the slow ones; the fast pipeline leaves them out.

When the image has several channels, every intensity measurement is reported
per channel too: ``intensity_mean`` is the first channel, and
``intensity_mean_c0``, ``intensity_mean_c1``, ... are each channel by index.

Publishes under ``pipeline_data["measure_objects"]``::

    properties   one column per measurement, one value per object
    n_objects    how many objects were measured
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

METADATA = {
    "description": "Per-object features (shape / intensity / neighbourhood / texture)",
    "version": "1.0",
    "max_workers": 1,
    "environment": "ZMART--object_analysis--classical",
}


# Measured here, not by scikit-image, which offers no stable name for it.
SYNTHETIC_PROPERTIES = {"intensity_median"}

# The intensity columns that get one ``_cN`` column per channel.
INTENSITY_PROPERTIES = (
    "intensity_mean",
    "intensity_min",
    "intensity_max",
    "intensity_std",
    "intensity_median",
)

DEFAULT_PROPERTIES = [
    "label",
    "bbox",
    "centroid",
    "weighted_centroid",
    "area",
    "num_pixels",
    "area_convex",
    "equivalent_diameter_area",
    "feret_diameter_max",
    "perimeter",
    "perimeter_crofton",
    "axis_major_length",
    "axis_minor_length",
    "orientation",
    "eccentricity",
    "solidity",
    "extent",
    "intensity_mean",
    "intensity_min",
    "intensity_max",
    "intensity_std",
    "intensity_median",
]


def run(pipeline_data: dict, state: dict, **params) -> dict:
    """Measure every object and publish one column per measurement."""

    verbose = pipeline_data["metadata"].get("verbose", 0)

    properties = list(params.get("properties", DEFAULT_PROPERTIES))

    pixel_size_um = params.get("pixel_size_um")

    extras, unknown = _expand_extras(list(params.get("extras", []) or []))

    if unknown:
        raise ValueError(
            f"Unknown extras {sorted(unknown)}. "
            f"Expected groups {sorted(FEATURE_GROUPS)} or extras "
            f"{sorted(EXTRAS)}."
        )

    masks = np.asarray(_segmentation(pipeline_data)["masks"])

    img = _normalise_image_axes(_image(pipeline_data["read_images"]), masks.shape)

    props = _base_measurements(masks, img, properties, pixel_size_um)

    labels = np.asarray(props.get("label", []))

    n_objects = int(len(labels))

    if n_objects > 0:
        _add_derived(props)

        _run_extras(props, masks, img, labels, extras, params, pixel_size_um)

    if verbose >= 2:
        print(f"  [measure_objects] objects: {n_objects}, columns: {sorted(props)}")

    pipeline_data["measure_objects"] = {
        "properties": props,
        "n_objects": n_objects,
    }

    return pipeline_data


# The inputs


def _segmentation(pipeline_data: dict) -> dict:
    """What the segmentation step published, whichever of the two ran."""

    if "segment_cellpose" in pipeline_data:
        return pipeline_data["segment_cellpose"]

    return pipeline_data["segment_watershed"]


def _image(images: dict) -> np.ndarray:
    """The image to measure: the segmented channels, with the other colours after them."""

    if not images["extra_channels"]:
        return images["image"]

    return np.stack([np.asarray(images["image"]), *images["extra_channels"]], axis=-1)


def _normalise_image_axes(img, mask_shape: tuple[int, int]) -> np.ndarray:
    """The image as one plane, or as channels-last ``(H, W, C)``, the size of the masks."""

    arr = np.asarray(img)

    if arr.ndim == 2 and arr.shape == mask_shape:
        return arr

    if arr.ndim == 3 and arr.shape[:2] == mask_shape:
        return arr

    if arr.ndim == 3 and arr.shape[1:] == mask_shape:
        return np.moveaxis(arr, 0, -1)

    raise ValueError(f"image shape {arr.shape} is not aligned to mask shape {mask_shape}.")


def _channel_images(img: np.ndarray) -> tuple[np.ndarray, ...] | None:
    """One plane per channel when the image has several; None for a single plane."""

    if np.asarray(img).ndim != 3:
        return None

    return tuple(img[..., idx] for idx in range(img.shape[-1]))


# The base measurements


def _base_measurements(
    masks: np.ndarray, img: np.ndarray, properties: list[str], pixel_size_um
) -> dict:
    """The base set: scikit-image's regionprops_table, the median, and per-channel names.

    With a pixel size, lengths and areas are in micrometres.
    """

    from skimage.measure import regionprops_table

    spacing_kw = {"spacing": tuple(pixel_size_um)} if pixel_size_um else {}

    native_properties = [prop for prop in properties if prop not in SYNTHETIC_PROPERTIES]

    props = regionprops_table(
        masks, intensity_image=img, properties=native_properties, **spacing_kw
    )

    _add_synthetic_properties(props, masks, img, properties)

    _normalise_intensity_columns(props, img)

    return props


def _add_synthetic_properties(
    props: dict, masks: np.ndarray, img: np.ndarray, properties: list[str]
) -> None:
    """Measure the median intensity, which scikit-image does not offer under a stable name."""

    if "intensity_median" not in properties:
        return

    channels = _channel_images(img)

    if channels is not None:
        for idx, channel in enumerate(channels):
            props[f"intensity_median_c{idx}"] = _intensity_medians(masks, channel)

        props["intensity_median"] = props["intensity_median_c0"]

        return

    props["intensity_median"] = _intensity_medians(masks, img)


def _intensity_medians(masks: np.ndarray, img: np.ndarray) -> np.ndarray:
    """The median intensity inside each object, in label order."""

    from skimage.measure import regionprops

    medians = []

    for region in regionprops(masks, intensity_image=img):
        # Newer scikit-image calls it image_intensity, older intensity_image.
        if hasattr(region, "image_intensity"):
            intensity_image = region.image_intensity
        else:
            intensity_image = region.intensity_image

        values = intensity_image[region.image]

        medians.append(float(np.median(values)) if values.size else np.nan)

    return np.asarray(medians, dtype=float)


def _normalise_intensity_columns(props: dict, img: np.ndarray) -> None:
    """Name the per-channel intensity columns the way the table promises them.

    scikit-image calls them ``name-0``, ``name-1``, ...; the table uses ``name``
    for the first channel and ``name_c0``, ``name_c1``, ... for each channel.
    """

    channels = _channel_images(img)

    if channels is None:
        return

    n_channels = len(channels)

    for base in INTENSITY_PROPERTIES:
        for idx in range(n_channels):
            skimage_key = f"{base}-{idx}"

            public_key = f"{base}_c{idx}"

            if public_key in props:
                values = props[public_key]
            elif skimage_key in props:
                values = props.pop(skimage_key)
            elif idx == 0 and base in props:
                values = props[base]
            else:
                continue

            props[public_key] = values

            if idx == 0:
                props[base] = values


# The ratios that are always added


def _add_derived(props: dict) -> None:
    """A few ratios of the base measurements that are useful for gating.

    Each ratio is added only when its base columns are there. A division by
    zero gives NaN, quietly.
    """

    with np.errstate(divide="ignore", invalid="ignore"):
        if {"area", "perimeter_crofton"} <= props.keys():
            a = np.asarray(props["area"], dtype=float)

            p = np.asarray(props["perimeter_crofton"], dtype=float)

            props["circularity"] = np.where(p > 0, 4 * np.pi * a / (p * p), np.nan)

        if {"axis_major_length", "axis_minor_length"} <= props.keys():
            maj = np.asarray(props["axis_major_length"], dtype=float)

            mn = np.asarray(props["axis_minor_length"], dtype=float)

            props["aspect_ratio"] = np.where(mn > 0, maj / mn, np.nan)

        if "orientation" in props:
            # scikit-image gives the angle from the row axis, -90 to 90 degrees.
            # Here it is the angle from the x axis, 0 to 180: lying flat is 0.
            props["orientation_deg"] = (90.0 - np.degrees(props["orientation"])) % 180.0

        if "intensity_mean" in props:
            mean_i = np.asarray(props["intensity_mean"], dtype=float)

            # num_pixels counts pixels even when area is in micrometres,
            # so the total stays a sum of pixel values.
            if "num_pixels" in props:
                n_px = np.asarray(props["num_pixels"], dtype=float)

                props["intensity_total"] = mean_i * n_px

            elif "area" in props:
                props["intensity_total"] = mean_i * np.asarray(props["area"], dtype=float)

            if "intensity_std" in props:
                std_i = np.asarray(props["intensity_std"], dtype=float)

                props["intensity_cv"] = np.where(mean_i > 0, std_i / mean_i, np.nan)

        for idx in _intensity_channel_indices(props):
            mean_key = f"intensity_mean_c{idx}"

            mean_i = np.asarray(props[mean_key], dtype=float)

            if "num_pixels" in props:
                n_px = np.asarray(props["num_pixels"], dtype=float)

                props[f"intensity_total_c{idx}"] = mean_i * n_px

            elif "area" in props:
                props[f"intensity_total_c{idx}"] = mean_i * np.asarray(props["area"], dtype=float)

            std_key = f"intensity_std_c{idx}"

            if std_key in props:
                std_i = np.asarray(props[std_key], dtype=float)

                props[f"intensity_cv_c{idx}"] = np.where(mean_i > 0, std_i / mean_i, np.nan)


def _intensity_channel_indices(props: dict) -> list[int]:
    """The channel indices N that have an ``intensity_mean_cN`` column, sorted."""

    prefix = "intensity_mean_c"

    indices = []

    for key in props:
        if key.startswith(prefix):
            suffix = key[len(prefix) :]

            if suffix.isdigit():
                indices.append(int(suffix))

    return sorted(indices)


# Running the optional families


@dataclass(frozen=True)
class _Context:
    """What every optional family is handed.

    A family adds its columns to ``props`` and changes nothing else. ``img`` is
    the first channel; ``channel_images`` holds one plane per channel when there
    are several. ``slices[label - 1]`` is an object's bounding box, present when
    a family needs it. ``pixel_size_um`` is ``(dy, dx)`` or None.
    """

    props: dict
    masks: np.ndarray
    img: np.ndarray
    channel_images: tuple[np.ndarray, ...] | None
    labels: np.ndarray
    slices: list | None
    params: dict
    pixel_size_um: tuple | list | None


def _run_extras(props, masks, img, labels, extras, params, pixel_size_um) -> None:
    """Build the context once, then run each family asked for.

    They run in a fixed order (family, then name), so the columns always come in
    the same order. No family reads another's columns.
    """

    from scipy.ndimage import find_objects

    needs_bbox = any(EXTRAS[name].needs_bbox for name in extras)

    slices = find_objects(masks) if needs_bbox else None

    channels = _channel_images(img)

    ctx = _Context(
        props=props,
        masks=masks,
        img=img if channels is None else channels[0],
        channel_images=channels,
        labels=labels,
        slices=slices,
        params=params,
        pixel_size_um=pixel_size_um,
    )

    for name in sorted(extras, key=lambda n: (EXTRAS[n].family, n)):
        extra = EXTRAS[name]

        if extra.per_channel:
            _add_per_channel(ctx, extra.handler)
        else:
            extra.handler(ctx)


def _add_per_channel(ctx: _Context, compute: Callable[[np.ndarray, _Context], dict]) -> None:
    """Add the columns for the first channel, then ``_cN`` ones for every channel."""

    for key, value in compute(ctx.img, ctx).items():
        ctx.props[key] = value

    if ctx.channel_images is None:
        return

    for idx, image in enumerate(ctx.channel_images):
        for key, value in compute(image, ctx).items():
            ctx.props[f"{key}_c{idx}"] = value


def _expand_extras(extras):
    """The families asked for, with each family name opened into its members.

    Returns ``(names, unknown)``: the members to run, and any name that is
    neither a family nor a member.
    """

    expanded: set[str] = set()

    unknown: set[str] = set()

    for name in extras:
        if name in FEATURE_GROUPS:
            expanded |= FEATURE_GROUPS[name]
        elif name in EXTRAS:
            expanded.add(name)
        else:
            unknown.add(name)

    return expanded, unknown


# Helpers shared by the families


def _texture_scale(img: np.ndarray, masks: np.ndarray, params: dict) -> float:
    """The intensity that maps to the top texture bin.

    ``intensity_scale`` from the pipeline when given (the camera's full range,
    e.g. 4095 for 12-bit data); otherwise the 99.9th percentile of the pixels
    inside objects, which a single bright pixel cannot move.
    """

    given = params.get("intensity_scale")

    if given is not None and float(given) > 0:
        return float(given)

    arr = np.asarray(img, dtype=np.float64)

    inside = arr[masks > 0] if masks is not None and np.any(masks > 0) else arr.ravel()

    scale = float(np.percentile(inside, 99.9)) if inside.size else 1.0

    return scale if scale > 0 else 1.0


def _per_label_mean(
    values_image: np.ndarray, label_image: np.ndarray, labels: np.ndarray
) -> np.ndarray:
    """The mean of ``values_image`` inside each object.

    A sum and a count per label over the whole image at once, which is fast
    on a tile with thousands of objects.
    """

    n_lbl = int(label_image.max()) + 1

    flat_lbl = label_image.ravel()

    flat_v = values_image.ravel().astype(np.float64)

    sums = np.bincount(flat_lbl, weights=flat_v, minlength=n_lbl)

    counts = np.bincount(flat_lbl, minlength=n_lbl)

    out = np.full(len(labels), np.nan, dtype=np.float64)

    valid = counts[labels] > 0

    out[valid] = sums[labels][valid] / counts[labels][valid]

    return out


def _bbox_padded(slice_pair, pad: int, shape) -> tuple:
    """An object's bounding box widened by ``pad`` pixels on every side, kept inside the image."""

    sy, sx = slice_pair

    return (
        slice(max(0, sy.start - pad), min(shape[0], sy.stop + pad)),
        slice(max(0, sx.start - pad), min(shape[1], sx.stop + pad)),
    )


# Family: intensity


def _global_background(image: np.ndarray, ctx: _Context) -> dict[str, np.ndarray]:
    """The mean of every pixel that belongs to no object.

    One number for the whole tile, repeated on every row; NaN when every pixel
    is inside an object.

    Adds:
        bg_global_mean
    """

    bg_pixels = image[ctx.masks == 0]

    scalar = float(bg_pixels.mean()) if bg_pixels.size else float("nan")

    return {"bg_global_mean": np.full(len(ctx.labels), scalar)}


def _local_bg_collar(ctx: _Context) -> None:
    """The background right around each object, from a collar.

    The collar is the ring of pixels within ``bg_radius`` of the object that
    belong to no object; the object's holes do not count as background.

    Adds:
        bg_local_mean         per-object collar mean
        mean_minus_local_bg   intensity_mean - bg_local_mean
        mean_over_local_bg    intensity_mean / bg_local_mean
        total_minus_local_bg  (intensity_mean - bg_local_mean) * num_pixels
        total_over_local_bg   intensity_total / bg_local_mean
    """

    bg_local = _local_bg_values(ctx.img, ctx)

    ctx.props["bg_local_mean"] = bg_local

    _add_local_bg_derivatives(ctx.props, bg_local)

    if ctx.channel_images is not None:
        for idx, image in enumerate(ctx.channel_images):
            bg_local = _local_bg_values(image, ctx)

            suffix = f"_c{idx}"

            ctx.props[f"bg_local_mean{suffix}"] = bg_local

            _add_local_bg_derivatives(ctx.props, bg_local, suffix=suffix)


def _local_bg_values(img: np.ndarray, ctx: _Context) -> np.ndarray:
    """The mean of each object's collar in ``img``; NaN when the collar is empty."""

    from scipy.ndimage import binary_fill_holes
    from skimage.morphology import dilation, disk

    masks = ctx.masks

    radius = int(ctx.params.get("bg_radius", 5))

    bg_local = np.full(len(ctx.labels), np.nan, dtype=np.float64)

    footprint = disk(radius)

    for i, lab in enumerate(ctx.labels):
        sl = ctx.slices[int(lab) - 1]

        if sl is None:
            continue

        sp = _bbox_padded(sl, radius + 1, masks.shape)

        crop_lab = masks[sp]

        obj = crop_lab == lab

        # Fill the holes, grow by the radius, then take out the object and its neighbours.
        filled = binary_fill_holes(obj)

        collar = dilation(filled, footprint=footprint) & ~filled & (crop_lab == 0)

        if collar.any():
            bg_local[i] = float(img[sp][collar].mean())

    return bg_local


def _add_local_bg_derivatives(props: dict, bg_local: np.ndarray, suffix: str = "") -> None:
    """The four intensity columns corrected for the local background.

    A zero collar gives NaN for the ratios instead of a division warning.
    """

    with np.errstate(divide="ignore", invalid="ignore"):
        mean_key = f"intensity_mean{suffix}"

        if mean_key in props:
            mean_i = np.asarray(props[mean_key], dtype=float)

            props[f"mean_minus_local_bg{suffix}"] = mean_i - bg_local

            props[f"mean_over_local_bg{suffix}"] = np.where(bg_local > 0, mean_i / bg_local, np.nan)

            n_px_key = (
                "num_pixels" if "num_pixels" in props else ("area" if "area" in props else None)
            )

            if n_px_key is not None:
                n_px = np.asarray(props[n_px_key], dtype=float)

                props[f"total_minus_local_bg{suffix}"] = (mean_i - bg_local) * n_px

        total_key = f"intensity_total{suffix}"

        if total_key in props:
            tot = np.asarray(props[total_key], dtype=float)

            props[f"total_over_local_bg{suffix}"] = np.where(bg_local > 0, tot / bg_local, np.nan)


# Family: neighbourhood


def _neighbour_features(ctx: _Context) -> None:
    """How close each object is to the others, from the object centres.

    Distances are in pixels, or micrometres when ``pixel_size_um`` was given.
    With fewer than two objects every distance is NaN and every count zero.

    Adds:
        nn_distance              distance to the closest other object
        nn{K}_mean_distance      mean distance to the K nearest others
                                 (``neighbour_k``, default 5)
        neighbours_within_{R}    count of other objects within R, one column
                                 per R in ``neighbour_radii`` (default 5, 50, 250)
    """

    from scipy.spatial import cKDTree

    k = int(ctx.params.get("neighbour_k", 5))

    radii = list(ctx.params.get("neighbour_radii", [5, 50, 250]))

    n = len(ctx.labels)

    nn_dist = np.full(n, np.nan, dtype=np.float64)

    nnk_mean = np.full(n, np.nan, dtype=np.float64)

    counts_per_radius = {r: np.zeros(n, dtype=np.int64) for r in radii}

    have_centroids = "centroid-0" in ctx.props and "centroid-1" in ctx.props

    if have_centroids and n >= 2:
        pts = np.stack(
            [
                np.asarray(ctx.props["centroid-0"], dtype=float),
                np.asarray(ctx.props["centroid-1"], dtype=float),
            ],
            axis=1,
        )

        tree = cKDTree(pts)

        # Two neighbours are asked for because the closest one is the point itself.
        d, _ = tree.query(pts, k=2)

        nn_dist = d[:, 1]

        # A small population has fewer than K others; ask for what there is.
        k_query = min(k + 1, n)

        if k_query > 1:
            d_k, _ = tree.query(pts, k=k_query)

            nnk_mean = d_k[:, 1:].mean(axis=1)

        for r in radii:
            counts_per_radius[r] = np.array(
                [len(x) - 1 for x in tree.query_ball_point(pts, r=float(r))],
                dtype=np.int64,
            )

    ctx.props["nn_distance"] = nn_dist

    ctx.props[f"nn{k}_mean_distance"] = nnk_mean

    for r in radii:
        ctx.props[f"neighbours_within_{r}"] = counts_per_radius[r]


# Family: texture


def _gradient_values(image: np.ndarray, ctx: _Context) -> dict[str, np.ndarray]:
    """How much the intensity changes across each object, on average.

    Two edge filters (Prewitt and Roberts) run once over the whole image; the
    result is averaged inside each object.

    Adds:
        prewitt_magnitude_mean
        roberts_magnitude_mean
    """

    from skimage.filters import prewitt, roberts

    return {
        "prewitt_magnitude_mean": _per_label_mean(prewitt(image), ctx.masks, ctx.labels),
        "roberts_magnitude_mean": _per_label_mean(roberts(image), ctx.masks, ctx.labels),
    }


def _statistical_texture_values(image: np.ndarray, ctx: _Context) -> dict[str, np.ndarray]:
    """The shape of each object's intensity histogram.

    The intensities are quantised into ``n_intensity_bins`` levels (default 256)
    and one histogram is made per object, all in one pass.

    Adds:
        intensity_uniformity   sum(p^2)              ("Angular Second Moment")
        intensity_entropy      -sum(p log2 p)        (Shannon, base 2)
        intensity_skewness     m3 / m2^(3/2)         (third standardised moment)
        intensity_kurtosis     m4 / m2^2 - 3         (Fisher excess kurtosis)
    """

    masks = ctx.masks

    labels = ctx.labels

    n_bins = int(ctx.params.get("n_intensity_bins", 256))

    img_arr = np.asarray(image)

    vmax = _texture_scale(img_arr, masks, ctx.params)

    img_q = np.clip(img_arr / vmax * (n_bins - 1), 0, n_bins - 1).astype(np.int64)

    # Each object pixel's row in the table, and its quantised value.
    fg = masks > 0

    label_to_row = np.full(int(masks.max()) + 1, -1, dtype=np.int64)

    label_to_row[labels] = np.arange(len(labels))

    rows = label_to_row[masks[fg]]

    vals = img_q[fg]

    valid = rows >= 0

    rows = rows[valid]

    vals = vals[valid]

    # One histogram per object, made into probabilities.
    counts = (
        np.bincount(rows * n_bins + vals, minlength=len(labels) * n_bins)
        .reshape(len(labels), n_bins)
        .astype(np.float64)
    )

    n_per = counts.sum(axis=1)

    p = np.divide(counts, n_per[:, None], out=np.zeros_like(counts), where=n_per[:, None] > 0)

    levels = np.arange(n_bins, dtype=np.float64)

    uniformity = (p * p).sum(axis=1)

    logp = np.zeros_like(p)

    np.log2(p, out=logp, where=p > 0)

    entropy = -(p * logp).sum(axis=1)

    # The central moments of each histogram.
    mean = (p * levels).sum(axis=1)

    centered = levels[None, :] - mean[:, None]

    m2 = (p * centered**2).sum(axis=1)

    m3 = (p * centered**3).sum(axis=1)

    m4 = (p * centered**4).sum(axis=1)

    skewness = np.full(len(labels), np.nan)

    kurtosis = np.full(len(labels), np.nan)

    nz = m2 > 0

    skewness[nz] = m3[nz] / (m2[nz] ** 1.5)

    kurtosis[nz] = m4[nz] / (m2[nz] ** 2) - 3.0

    return {
        "intensity_uniformity": uniformity,
        "intensity_entropy": entropy,
        "intensity_skewness": skewness,
        "intensity_kurtosis": kurtosis,
    }


def _lbp_values(image: np.ndarray, ctx: _Context) -> dict[str, np.ndarray]:
    """Six numbers describing the local binary pattern inside each object.

    The pattern codes each pixel by which neighbours are brighter than it. It is
    computed once over the 8-bit image, so a pixel at an object's edge also sees
    the neighbours just outside, which is the usual convention.

    Adds:
        lbp_mean, lbp_std, lbp_energy, lbp_entropy,
        lbp_skewness, lbp_kurtosis
    """

    from scipy.stats import kurtosis as sstat_kurt
    from scipy.stats import skew as sstat_skew
    from skimage.feature import local_binary_pattern
    from skimage.measure import shannon_entropy

    masks = ctx.masks

    P = int(ctx.params.get("lbp_P", 8))

    R = float(ctx.params.get("lbp_R", 1))

    method = str(ctx.params.get("lbp_method", "default"))

    # The image as 8-bit, with the texture scale at 255 and brighter values clipped.
    scale = _texture_scale(image, masks, ctx.params)

    image_8bit = np.clip(np.asarray(image).astype(np.float64) / scale * 255.0, 0, 255).astype(
        np.uint8
    )

    lbp = local_binary_pattern(image_8bit, P=P, R=R, method=method).astype(np.int32)

    out = np.full((len(ctx.labels), 6), np.nan, dtype=np.float64)

    for i, lab in enumerate(ctx.labels):
        sl = ctx.slices[int(lab) - 1]

        if sl is None:
            continue

        v = lbp[sl][masks[sl] == lab]

        if v.size == 0:
            continue

        out[i, 0] = v.mean()

        out[i, 1] = v.std()

        h = np.bincount(v.astype(np.int64))

        if h.sum() > 0:
            p = h / h.sum()

            out[i, 2] = float((p * p).sum())

        out[i, 3] = float(shannon_entropy(v))

        if v.size > 1 and v.std() > 0:
            out[i, 4] = float(sstat_skew(v))

            out[i, 5] = float(sstat_kurt(v, fisher=True, bias=True))

    return {
        "lbp_mean": out[:, 0],
        "lbp_std": out[:, 1],
        "lbp_energy": out[:, 2],
        "lbp_entropy": out[:, 3],
        "lbp_skewness": out[:, 4],
        "lbp_kurtosis": out[:, 5],
    }


def _fft_values(image: np.ndarray, ctx: _Context) -> dict[str, np.ndarray]:
    """Six numbers describing each object's frequency content.

    Each object's bounding box, background set to zero, goes through a 2-D
    Fourier transform, without windowing or padding. The entropy uses a
    histogram of ``fft_entropy_bins`` bins (default 256).

    Adds:
        fft_mean, fft_std, fft_energy, fft_entropy,
        fft_skewness, fft_kurtosis
    """

    from scipy.stats import kurtosis as sstat_kurt
    from scipy.stats import skew as sstat_skew

    masks = ctx.masks

    n_bins = int(ctx.params.get("fft_entropy_bins", 256))

    out = np.full((len(ctx.labels), 6), np.nan, dtype=np.float64)

    for i, lab in enumerate(ctx.labels):
        sl = ctx.slices[int(lab) - 1]

        if sl is None:
            continue

        m = masks[sl] == lab

        if not m.any():
            continue

        crop = image[sl].astype(np.float64) * m

        F = np.abs(np.fft.fftshift(np.fft.fft2(crop)))

        flat = F.ravel()

        out[i, 0] = float(flat.mean())

        out[i, 1] = float(flat.std())

        out[i, 2] = float((F * F).sum())

        hist, _ = np.histogram(F, bins=n_bins)

        s = hist.sum()

        if s > 0:
            p = hist / s

            nz = p > 0

            out[i, 3] = float(-(p[nz] * np.log2(p[nz])).sum())

        if flat.size > 1 and flat.std() > 0:
            out[i, 4] = float(sstat_skew(flat))

            out[i, 5] = float(sstat_kurt(flat, fisher=True, bias=True))

    return {
        "fft_mean": out[:, 0],
        "fft_std": out[:, 1],
        "fft_energy": out[:, 2],
        "fft_entropy": out[:, 3],
        "fft_skewness": out[:, 4],
        "fft_kurtosis": out[:, 5],
    }


def _glrlm_values(image: np.ndarray, ctx: _Context) -> dict[str, np.ndarray]:
    """Four gray-level run-length features, summed over four directions.

    A run is a stretch of pixels in a line with the same gray level, after
    quantising to ``glrlm_levels`` levels (default 16). Runs stop at the object's
    edge and are counted along rows, columns and both diagonals. Gray levels
    count from one in the formulas, so the darkest level does not divide by zero.

    Adds:
        glrlm_rlnu   run length non-uniformity     sum_r (sum_g P)^2 / TR
        glrlm_lglre  low gray level run emphasis   sum_{g,r} P / g^2 / TR
        glrlm_hglre  high gray level run emphasis  sum_{g,r} P * g^2 / TR
        glrlm_glnu   gray level non-uniformity     sum_g (sum_r P)^2 / TR
    """

    masks = ctx.masks

    n_levels = int(ctx.params.get("glrlm_levels", 16))

    img_arr = np.asarray(image)

    vmax = _texture_scale(img_arr, masks, ctx.params)

    img_q = np.clip(img_arr.astype(np.float64) / vmax * (n_levels - 1), 0, n_levels - 1).astype(
        np.int16
    )

    out = np.full((len(ctx.labels), 4), np.nan, dtype=np.float64)

    g = np.arange(1, n_levels + 1, dtype=np.float64)[:, None]

    for i, lab in enumerate(ctx.labels):
        sl = ctx.slices[int(lab) - 1]

        if sl is None:
            continue

        m = masks[sl] == lab

        if not m.any():
            continue

        # Pixels outside the object are marked -1, so no run crosses into them.
        crop_q_obj = np.where(m, img_q[sl], -1).astype(np.int16)

        P = _glrlm_matrix_4dir(crop_q_obj, n_levels).astype(np.float64)

        TR = float(P.sum())

        if TR == 0:
            continue

        # Summed over gray levels: one value per run length.
        sum_g = P.sum(axis=0)

        # Summed over run lengths: one value per gray level.
        sum_r = P.sum(axis=1)

        out[i] = [
            float((sum_g**2).sum() / TR),
            float((P / (g**2)).sum() / TR),
            float((P * (g**2)).sum() / TR),
            float((sum_r**2).sum() / TR),
        ]

    return {
        "glrlm_rlnu": out[:, 0],
        "glrlm_lglre": out[:, 1],
        "glrlm_hglre": out[:, 2],
        "glrlm_glnu": out[:, 3],
    }


def _glrlm_matrix_4dir(crop_q: np.ndarray, n_levels: int) -> np.ndarray:
    """The run count table summed over 0, 45, 90 and 135 degrees.

    Row ``g`` is a gray level and column ``r`` a run length of ``r + 1``.
    """

    H, W = crop_q.shape

    if H == 0 or W == 0:
        return np.zeros((n_levels, 1), dtype=np.int64)

    P = np.zeros((n_levels, max(H, W)), dtype=np.int64)

    def count_runs(lines):
        for line in lines:
            vals, lens = _runs_in_line(line)

            if vals.size:
                np.add.at(P, (vals, lens - 1), 1)

    # 0 degrees: along the rows.
    count_runs(crop_q)

    # 90 degrees: along the columns.
    count_runs(crop_q.T)

    # 45 degrees: along the diagonals.
    count_runs(np.diagonal(crop_q, k) for k in range(-H + 1, W))

    # 135 degrees: along the anti-diagonals.
    count_runs(np.diagonal(np.fliplr(crop_q), k) for k in range(-H + 1, W))

    return P


def _runs_in_line(line: np.ndarray):
    """The runs in one line of pixels: ``(gray_levels, run_lengths)``.

    Runs of the negative background mark are dropped, so no run crosses the
    object's edge.
    """

    if line.size == 0:
        return np.empty(0, dtype=line.dtype), np.empty(0, dtype=np.int64)

    diff = np.diff(line, prepend=line[0] - 1, append=line[-1] + 1)

    idx = np.flatnonzero(diff)

    starts = idx[:-1]

    lengths = np.diff(idx).astype(np.int64)

    vals = line[starts]

    valid = vals >= 0

    return vals[valid], lengths[valid]


# Family: morphology


def _radius_of_gyration_and_spread(ctx: _Context) -> None:
    """How spread out each object is, and whether its brightness sits at the centre.

    The radius of gyration is the root mean square distance of the object's
    pixels from its centre. The radial variance is 1 for an evenly bright
    object, below 1 when the brightness sits at the centre, above 1 at the rim.
    For an evenly bright disc of radius R, Rg = R / sqrt(2).

    Adds:
        radius_of_gyration                       Rg = sqrt( (1/N) sum r_i^2 )
        intensity_radial_variance_normalised     sum( I_i * r_i^2 )
                                                  / ( mean(I) * N * Rg^2 )
    """

    dy, dx = ctx.pixel_size_um if ctx.pixel_size_um else (1.0, 1.0)

    n = len(ctx.labels)

    rg = np.full(n, np.nan, dtype=np.float64)

    spread = np.full(n, np.nan, dtype=np.float64)

    for i, lab in enumerate(ctx.labels):
        sl = ctx.slices[int(lab) - 1]

        if sl is None:
            continue

        sy, sx = sl

        crop_lab = ctx.masks[sl]

        obj = crop_lab == lab

        if not obj.any():
            continue

        # Pixel positions in the whole image, in micrometres when a pixel size is given.
        ys, xs = np.where(obj)

        ys = (ys + sy.start) * dy

        xs = (xs + sx.start) * dx

        cm_y = ys.mean()

        cm_x = xs.mean()

        d2 = (ys - cm_y) ** 2 + (xs - cm_x) ** 2

        rg_v = float(np.sqrt(d2.mean()))

        rg[i] = rg_v

        u = ctx.img[sl][obj].astype(np.float64)

        u_mean = float(u.mean())

        N = u.size

        if rg_v > 0 and u_mean > 0:
            spread[i] = float((u * d2).sum() / (u_mean * N * rg_v**2))

    ctx.props["radius_of_gyration"] = rg

    ctx.props["intensity_radial_variance_normalised"] = spread


# The optional families: name, family, whether they need the bounding boxes,
# and whether they are measured per channel. This table must come after the
# functions it names. To add a measurement, write its function and add a line.


@dataclass(frozen=True)
class _Extra:
    """One optional measurement: what runs it, its family, and what it needs."""

    handler: Callable
    family: str
    needs_bbox: bool
    per_channel: bool


EXTRAS: dict[str, _Extra] = {
    "global_bg": _Extra(_global_background, "intensity", False, True),
    "local_bg": _Extra(_local_bg_collar, "intensity", True, False),
    "neighbours": _Extra(_neighbour_features, "neighbourhood", False, False),
    "gradients": _Extra(_gradient_values, "texture", False, True),
    "stat_texture": _Extra(_statistical_texture_values, "texture", False, True),
    "lbp": _Extra(_lbp_values, "texture", True, True),
    "fft": _Extra(_fft_values, "texture", True, True),
    "glrlm": _Extra(_glrlm_values, "texture", True, True),
    "rg_spread": _Extra(_radius_of_gyration_and_spread, "morphology", True, False),
}


FEATURE_GROUPS: dict[str, set[str]] = {
    family: {name for name, e in EXTRAS.items() if e.family == family}
    for family in {e.family for e in EXTRAS.values()}
}

FEATURE_GROUPS["all"] = set(EXTRAS)
