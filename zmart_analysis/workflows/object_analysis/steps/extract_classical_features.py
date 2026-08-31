"""extract_classical_features -- per-object features for one detected tile."""
from dataclasses import dataclass
from typing import Callable

import numpy as np


METADATA = {
    "description": "Per-object features (shape / intensity / neighbourhood / texture)",
    "version": "3.0",
    "environment": "ZMART--object_analysis--classical",
}


# ---------------------------------------------------------------------------
# Default feature configuration. Native properties are passed to
# regionprops_table; compatibility properties in SYNTHETIC_PROPERTIES are
# computed below so the output contract is stable across scikit-image
# versions.
# ---------------------------------------------------------------------------

SYNTHETIC_PROPERTIES = {"intensity_median"}
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
    "centroid", "weighted_centroid",
    "area", "num_pixels", "area_convex",
    "equivalent_diameter_area", "feret_diameter_max",
    "perimeter", "perimeter_crofton",
    "axis_major_length", "axis_minor_length", "orientation",
    "eccentricity", "solidity", "extent",
    "intensity_mean", "intensity_min", "intensity_max",
    "intensity_std", "intensity_median",
]


# ---------------------------------------------------------------------------
# Public entry point.
# ---------------------------------------------------------------------------

def run(pipeline_data: dict, state: dict, **params) -> dict:
    """Engine entry point. See module docstring for the full parameter set."""
    from skimage.measure import regionprops_table

    verbose = pipeline_data["metadata"].get("verbose", 0)

    properties = list(params.get("properties", DEFAULT_PROPERTIES))
    requested_extras = list(params.get("extras", []) or [])
    pixel_size_um = params.get("pixel_size_um")

    extras, unknown = _expand_extras(requested_extras)
    if unknown:
        raise ValueError(
            f"Unknown extras {sorted(unknown)}. "
            f"Expected groups {sorted(FEATURE_GROUPS)} or extras "
            f"{sorted(EXTRAS)}."
        )

    masks = np.asarray(pipeline_data["segment"]["masks"])
    img = _normalise_image_axes(pipeline_data["preprocess"]["image"], masks.shape)

    spacing_kw = {"spacing": tuple(pixel_size_um)} if pixel_size_um else {}
    native_properties = [
        prop for prop in properties if prop not in SYNTHETIC_PROPERTIES
    ]
    props = regionprops_table(
        masks, intensity_image=img, properties=native_properties, **spacing_kw
    )
    _add_synthetic_properties(props, masks, img, properties)
    _normalise_intensity_columns(props, img)

    labels = np.asarray(props.get("label", []))
    n_cells = int(len(labels))

    if n_cells > 0:
        _add_derived(props)
        if extras:
            _run_extras(props, masks, img, labels, extras, params, pixel_size_um)

    if verbose >= 2:
        print(f"  [extract_features] cells: {n_cells}, "
              f"properties: {sorted(props)}")

    pipeline_data["extract_features"] = {
        "properties": props,
        "n_cells": n_cells,
    }
    return pipeline_data


def _add_synthetic_properties(
    props: dict, masks: np.ndarray, img: np.ndarray, properties: list[str]
) -> None:
    """Add requested properties that are not portable regionprops names."""
    if "intensity_median" not in properties:
        return

    channels = _channel_images(img)
    if channels is not None:
        for idx, channel in enumerate(channels):
            props[f"intensity_median_c{idx}"] = _intensity_medians(
                masks, channel
            )
        props["intensity_median"] = props["intensity_median_c0"]
        return

    props["intensity_median"] = _intensity_medians(masks, img)


def _intensity_medians(masks: np.ndarray, img: np.ndarray) -> np.ndarray:
    """Return per-label median intensity in ascending label order."""
    from skimage.measure import regionprops

    medians = []
    for region in regionprops(masks, intensity_image=img):
        if hasattr(region, "image_intensity"):
            intensity_image = region.image_intensity
        else:
            intensity_image = region.intensity_image
        values = intensity_image[region.image]
        medians.append(float(np.median(values)) if values.size else np.nan)
    return np.asarray(medians, dtype=float)


def _normalise_image_axes(img, mask_shape: tuple[int, int]) -> np.ndarray:
    """Return image as 2D or channel-last ``(H, W, C)`` aligned to masks."""
    arr = np.asarray(img)
    if arr.ndim == 2 and arr.shape == mask_shape:
        return arr
    if arr.ndim == 3 and arr.shape[:2] == mask_shape:
        return arr
    if arr.ndim == 3 and arr.shape[1:] == mask_shape:
        return np.moveaxis(arr, 0, -1)
    raise ValueError(
        f"image shape {arr.shape} is not aligned to mask shape {mask_shape}."
    )


def _channel_images(img: np.ndarray) -> tuple[np.ndarray, ...] | None:
    """Return per-channel 2D images when ``img`` is channel-last."""
    if np.asarray(img).ndim != 3:
        return None
    return tuple(img[..., idx] for idx in range(img.shape[-1]))


def _primary_image(img: np.ndarray) -> np.ndarray:
    """Return the primary 2D intensity image used for existing base columns."""
    channels = _channel_images(img)
    return img if channels is None else channels[0]


def _normalise_intensity_columns(props: dict, img: np.ndarray) -> None:
    """Expose multichannel intensity stats as base + ``_cN`` columns.

    scikit-image emits multichannel intensity columns as ``name-0`` /
    ``name-1``. The workflow contract uses ``name`` for the primary channel
    and ``name_c0`` / ``name_c1`` / ... for explicit per-channel columns.
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


# ---------------------------------------------------------------------------
# Always-on derived columns.
# Each is added only if its sources are present in ``props``, so trimming
# the native regionprops set naturally trims its derivatives.
# ---------------------------------------------------------------------------

def _add_derived(props: dict) -> None:
    """Cheap algebraic derivatives of the native regionprops set.

    All divisions are wrapped in ``np.errstate`` so degenerate objects
    (zero perimeter, zero minor axis, zero mean intensity) yield NaN
    through the surrounding ``np.where`` without emitting warnings.
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
            # skimage `orientation` is the angle from the row axis in
            # [-pi/2, pi/2]. Convert to angle from the x-axis in [0, 180):
            # horizontal major axis -> 0 deg, vertical major axis -> 90 deg.
            props["orientation_deg"] = (90.0 - np.degrees(props["orientation"])) % 180.0

        if "intensity_mean" in props:
            mean_i = np.asarray(props["intensity_mean"], dtype=float)
            # ``num_pixels`` is the genuine pixel count even when
            # ``spacing=`` is set, which keeps intensity_total a real
            # integrated intensity in any unit configuration.
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
                props[f"intensity_total_c{idx}"] = mean_i * np.asarray(
                    props["area"], dtype=float
                )
            std_key = f"intensity_std_c{idx}"
            if std_key in props:
                std_i = np.asarray(props[std_key], dtype=float)
                props[f"intensity_cv_c{idx}"] = np.where(
                    mean_i > 0, std_i / mean_i, np.nan
                )


def _intensity_channel_indices(props: dict) -> list[int]:
    prefix = "intensity_mean_c"
    indices = []
    for key in props:
        if key.startswith(prefix):
            suffix = key[len(prefix):]
            if suffix.isdigit():
                indices.append(int(suffix))
    return sorted(indices)


# ---------------------------------------------------------------------------
# Extras dispatcher.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Context:
    """Bundle handed to every extras handler. Handlers mutate ``props`` to
    add output columns; everything else is read-only.

    Fields
    ------
    props : dict
        Mutable output dict. Handlers add named columns to it.
    masks : ndarray
        Int label image of shape (H, W).
    img : ndarray
        Primary 2D intensity image (any non-negative dtype).
    channel_images : tuple[ndarray, ...] | None
        Per-channel 2D images when the input was multichannel. Handlers use
        this to add explicit ``_cN`` columns while preserving existing base
        columns as channel 0.
    labels : ndarray
        1D array of label ids, in row order.
    slices : list | None
        ``scipy.ndimage.find_objects(masks)`` when at least one requested
        extra needs per-object bounding boxes; otherwise None. Indexed as
        ``slices[lab - 1]`` for label ``lab``; ``None`` for absent labels.
    params : dict
        Raw YAML params dict; handlers read their own keys with sensible
        defaults so the dispatcher stays handler-agnostic.
    pixel_size_um : tuple | list | None
        ``(dy, dx)`` mirror of the spacing passed to regionprops_table.
        Handlers that own coordinates (e.g. radius of gyration, neighbour
        distances) read this to scale to physical units.
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
    """Build the context once, then dispatch each requested handler.

    Handler execution order is family-then-name so outputs are
    reproducible. Order does not affect correctness because handlers do
    not read each other's columns -- they all consume default regionprops
    and derived columns.
    """
    from scipy.ndimage import find_objects

    needs_bbox = any(EXTRAS[name].needs_bbox for name in extras)
    slices = find_objects(masks) if needs_bbox else None

    ctx = _Context(
        props=props, masks=masks, img=_primary_image(img),
        channel_images=_channel_images(img), labels=labels,
        slices=slices, params=params, pixel_size_um=pixel_size_um,
    )

    for name in sorted(extras, key=lambda n: (EXTRAS[n].family, n)):
        EXTRAS[name].handler(ctx)


def _expand_extras(extras):
    """Expand group names to their constituent extras.

    Returns ``(expanded_set, unknown_names)``. Group names and individual
    extra names may be mixed freely; duplicates de-dupe naturally because
    the result is a set.
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


# ---------------------------------------------------------------------------
# Helpers shared across families.
# ---------------------------------------------------------------------------

def _to_uint8(img: np.ndarray) -> np.ndarray:
    """Map any non-negative image to ``uint8 [0, 255]`` for texture
    features that expect 8-bit input, currently LBP.

    Returns uint8 input unchanged. Otherwise rescales by the global
    ``img.max()`` and clips to [0, 255], returning a new array.
    """
    arr = np.asarray(img)
    if arr.dtype == np.uint8:
        return arr
    vmax = float(arr.max()) if arr.size else 1.0
    if vmax <= 0:
        vmax = 1.0
    return np.clip(arr.astype(np.float64) / vmax * 255.0, 0, 255).astype(np.uint8)


def _per_label_mean(values_image: np.ndarray,
                    label_image: np.ndarray,
                    labels: np.ndarray) -> np.ndarray:
    """Per-label mean of ``values_image`` via two ``np.bincount`` passes.

    Equivalent to ``[values_image[label_image == lab].mean() for lab in
    labels]`` but vectorised: one sum-by-label pass and one count-by-label
    pass over the flattened image, then one division per label. Avoids the
    O(N_labels * H * W) cost of repeated ``label_image == lab`` scans.
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
    """Return a ``(slice, slice)`` pair padded by ``pad`` pixels on every
    side and clipped to ``shape``.

    Used by handlers that need a ring of context around the object's
    bounding box (the local_bg collar, for example).
    """
    sy, sx = slice_pair
    return (
        slice(max(0, sy.start - pad), min(shape[0], sy.stop + pad)),
        slice(max(0, sx.start - pad), min(shape[1], sx.stop + pad)),
    )


def _assign_columns(props: dict, values: dict[str, np.ndarray], suffix: str = "") -> None:
    """Assign feature columns, optionally suffixing each column name."""
    for key, value in values.items():
        props[f"{key}{suffix}"] = value


def _assign_channelised(ctx: _Context, compute: Callable[[np.ndarray], dict]) -> None:
    """Assign base feature columns plus per-channel ``_cN`` columns."""
    _assign_columns(ctx.props, compute(ctx.img))
    if ctx.channel_images is None:
        return
    for idx, image in enumerate(ctx.channel_images):
        _assign_columns(ctx.props, compute(image), suffix=f"_c{idx}")


# ===========================================================================
# Family: Intensity
# ===========================================================================

def _global_bg_mean(ctx: _Context) -> None:
    """Mean intensity over all unlabelled pixels (``label == 0``).

    The result is a single scalar broadcast across all rows so it can be
    selected, sorted, or compared like any per-object column. ``NaN`` if
    every pixel is labelled.

    Adds:
        bg_global_mean
    """
    bg_pixels = ctx.img[ctx.masks == 0]
    scalar = float(bg_pixels.mean()) if bg_pixels.size else float("nan")
    ctx.props["bg_global_mean"] = np.full(len(ctx.labels), scalar)
    if ctx.channel_images is not None:
        for idx, image in enumerate(ctx.channel_images):
            bg_pixels = image[ctx.masks == 0]
            scalar = float(bg_pixels.mean()) if bg_pixels.size else float("nan")
            ctx.props[f"bg_global_mean_c{idx}"] = np.full(len(ctx.labels), scalar)


def _local_bg_collar(ctx: _Context) -> None:
    """Background mean from a per-object collar.

    For each object the collar is constructed inside the bounding box
    padded by ``bg_radius + 1``:

        1. fill internal holes (so a ring's hole is treated as object,
           not background);
        2. dilate by a disk of ``bg_radius`` pixels to reach into the
           surround;
        3. subtract the filled object (we want the surround, not the
           object itself);
        4. intersect with ``crop_lab == 0`` so neighbouring labels whose
           dilation overlaps are excluded.

    Adds:
        bg_local_mean         per-object collar mean
        mean_minus_local_bg   intensity_mean - bg_local_mean
        mean_over_local_bg    intensity_mean / bg_local_mean
        total_minus_local_bg  (intensity_mean - bg_local_mean) * num_pixels
        total_over_local_bg   intensity_total / bg_local_mean
    """
    bg_local = _local_bg_values(ctx.img, ctx.masks, ctx.labels, ctx.slices, ctx.params)
    ctx.props["bg_local_mean"] = bg_local
    _add_local_bg_derivatives(ctx.props, bg_local)

    if ctx.channel_images is not None:
        for idx, image in enumerate(ctx.channel_images):
            bg_local = _local_bg_values(
                image, ctx.masks, ctx.labels, ctx.slices, ctx.params
            )
            suffix = f"_c{idx}"
            ctx.props[f"bg_local_mean{suffix}"] = bg_local
            _add_local_bg_derivatives(ctx.props, bg_local, suffix=suffix)


def _local_bg_values(
    img: np.ndarray,
    masks: np.ndarray,
    labels: np.ndarray,
    slices: list,
    params: dict,
) -> np.ndarray:
    from scipy.ndimage import binary_fill_holes
    from skimage.morphology import dilation, disk

    radius = int(params.get("bg_radius", 5))
    bg_local = np.full(len(labels), np.nan, dtype=np.float64)
    footprint = disk(radius)

    for i, lab in enumerate(labels):
        sl = slices[int(lab) - 1]
        if sl is None:
            continue
        sp = _bbox_padded(sl, radius + 1, masks.shape)
        crop_lab = masks[sp]
        obj = crop_lab == lab
        filled = binary_fill_holes(obj)
        collar = dilation(filled, footprint=footprint) & ~filled & (crop_lab == 0)
        if collar.any():
            bg_local[i] = float(img[sp][collar].mean())
    return bg_local


def _add_local_bg_derivatives(
    props: dict, bg_local: np.ndarray, suffix: str = ""
) -> None:
    """Compute the four background-corrected intensity columns.

    Split out from ``_local_bg_collar`` so the bbox loop stays focussed on
    collar construction and the algebra reads in one place. ``np.errstate``
    suppresses the harmless divide-by-zero that surfaces inside
    ``np.where`` when ``bg_local`` is zero for some objects.
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        mean_key = f"intensity_mean{suffix}"
        if mean_key in props:
            mean_i = np.asarray(props[mean_key], dtype=float)
            props[f"mean_minus_local_bg{suffix}"] = mean_i - bg_local
            props[f"mean_over_local_bg{suffix}"] = np.where(
                bg_local > 0, mean_i / bg_local, np.nan
            )
            n_px_key = (
                "num_pixels" if "num_pixels" in props
                else ("area" if "area" in props else None)
            )
            if n_px_key is not None:
                n_px = np.asarray(props[n_px_key], dtype=float)
                props[f"total_minus_local_bg{suffix}"] = (mean_i - bg_local) * n_px
        total_key = f"intensity_total{suffix}"
        if total_key in props:
            tot = np.asarray(props[total_key], dtype=float)
            props[f"total_over_local_bg{suffix}"] = np.where(
                bg_local > 0, tot / bg_local, np.nan
            )


# ===========================================================================
# Family: Neighbourhood (cKDTree on object centroids)
# ===========================================================================

def _neighbour_features(ctx: _Context) -> None:
    """Object-to-object spatial features.

    Distances and radii are in centroid-coordinate units: pixels by
    default, microns when ``pixel_size_um`` was passed to
    ``regionprops_table`` (centroids come back scaled).

    Adds:
        nn_distance              distance to the closest other object
        nn{K}_mean_distance      mean distance to the K nearest others
                                 (column name reflects ``neighbour_k``,
                                 default ``K = 5``)
        neighbours_within_{R}    one column per radius in
                                 ``neighbour_radii`` (default
                                 ``[5, 50, 250]``); each holds the count of
                                 other objects within ``R`` units.

    For a workflow with fewer than 2 objects all distances are ``NaN`` and
    all counts are zero (no exception).
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
        pts = np.stack([
            np.asarray(ctx.props["centroid-0"], dtype=float),
            np.asarray(ctx.props["centroid-1"], dtype=float),
        ], axis=1)
        tree = cKDTree(pts)
        # k=2 because the closest hit at every point is itself (distance 0).
        d, _ = tree.query(pts, k=2)
        nn_dist = d[:, 1]
        # Cap K at (n - 1) neighbours when the population is smaller than
        # the requested K so the tree query stays well-defined.
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


# ===========================================================================
# Family: Texture
# ===========================================================================

def _gradient_means(ctx: _Context) -> None:
    """Per-object mean of the Prewitt and Roberts gradient magnitudes.

    Each filter is evaluated once over the whole image (cheap
    convolutions), then aggregated per label by ``_per_label_mean`` --
    two ``np.bincount`` passes, no Python-level per-object loop.

    Adds:
        prewitt_magnitude_mean
        roberts_magnitude_mean
    """
    _assign_channelised(
        ctx,
        lambda image: _gradient_values(image, ctx.masks, ctx.labels),
    )


def _gradient_values(
    img: np.ndarray, masks: np.ndarray, labels: np.ndarray
) -> dict[str, np.ndarray]:
    from skimage.filters import prewitt, roberts

    return {
        "prewitt_magnitude_mean": _per_label_mean(prewitt(img), masks, labels),
        "roberts_magnitude_mean": _per_label_mean(roberts(img), masks, labels),
    }


def _statistical_texture(ctx: _Context) -> None:
    """Per-object intensity histogram statistics in a single vector pass.

    The intensity image is quantised to ``n_intensity_bins`` (default
    256). A single ``np.bincount`` over a ``(label * n_bins + value)`` key
    produces every per-label histogram simultaneously; probabilities,
    central moments, and Shannon entropy then follow as standard
    vectorised reductions.

    Adds:
        intensity_uniformity   sum(p^2)              ("Angular Second Moment")
        intensity_entropy      -sum(p log2 p)        (Shannon, base 2)
        intensity_skewness     m3 / m2^(3/2)         (third standardised moment)
        intensity_kurtosis     m4 / m2^2 - 3         (Fisher excess kurtosis)
    """
    _assign_channelised(
        ctx,
        lambda image: _statistical_texture_values(
            image, ctx.masks, ctx.labels, ctx.params
        ),
    )


def _statistical_texture_values(
    img: np.ndarray, masks: np.ndarray, labels: np.ndarray, params: dict
) -> dict[str, np.ndarray]:
    n_bins = int(params.get("n_intensity_bins", 256))
    img_arr = np.asarray(img)
    vmax = float(img_arr.max()) if img_arr.size else 1.0
    if vmax <= 0:
        vmax = 1.0
    img_q = np.clip(img_arr / vmax * (n_bins - 1), 0, n_bins - 1).astype(np.int64)

    fg = masks > 0
    label_to_row = np.full(int(masks.max()) + 1, -1, dtype=np.int64)
    label_to_row[labels] = np.arange(len(labels))

    rows = label_to_row[masks[fg]]
    vals = img_q[fg]
    valid = rows >= 0
    rows = rows[valid]; vals = vals[valid]

    counts = np.bincount(
        rows * n_bins + vals, minlength=len(labels) * n_bins
    ).reshape(len(labels), n_bins).astype(np.float64)
    n_per = counts.sum(axis=1)
    p = np.divide(
        counts, n_per[:, None], out=np.zeros_like(counts), where=n_per[:, None] > 0
    )

    levels = np.arange(n_bins, dtype=np.float64)
    uniformity = (p * p).sum(axis=1)
    logp = np.zeros_like(p)
    np.log2(p, out=logp, where=p > 0)
    entropy = -(p * logp).sum(axis=1)

    mean = (p * levels).sum(axis=1)
    centered = levels[None, :] - mean[:, None]
    m2 = (p * centered ** 2).sum(axis=1)
    m3 = (p * centered ** 3).sum(axis=1)
    m4 = (p * centered ** 4).sum(axis=1)

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


def _lbp_features(ctx: _Context) -> None:
    """Six per-object statistics over the local binary pattern image.

    The LBP image is computed once over the whole intensity image (after
    quantisation to uint8), so border pixels of an object encode neighbour
    pixels from outside the object too. This is the standard whole-image
    convention; for texture *strictly inside* the object, run LBP on
    per-object crops instead.

    Adds:
        lbp_mean, lbp_std, lbp_energy, lbp_entropy,
        lbp_skewness, lbp_kurtosis
    """
    _assign_channelised(
        ctx,
        lambda image: _lbp_values(
            image, ctx.masks, ctx.labels, ctx.slices, ctx.params
        ),
    )


def _lbp_values(
    img: np.ndarray,
    masks: np.ndarray,
    labels: np.ndarray,
    slices: list,
    params: dict,
) -> dict[str, np.ndarray]:
    from skimage.feature import local_binary_pattern
    from skimage.measure import shannon_entropy
    from scipy.stats import skew as sstat_skew, kurtosis as sstat_kurt

    P = int(params.get("lbp_P", 8))
    R = float(params.get("lbp_R", 1))
    method = str(params.get("lbp_method", "default"))

    lbp = local_binary_pattern(_to_uint8(img), P=P, R=R, method=method).astype(
        np.int32
    )

    n = len(labels)
    out = np.full((n, 6), np.nan, dtype=np.float64)
    for i, lab in enumerate(labels):
        sl = slices[int(lab) - 1]
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
        key: out[:, col]
        for col, key in enumerate((
        "lbp_mean", "lbp_std", "lbp_energy",
        "lbp_entropy", "lbp_skewness", "lbp_kurtosis",
        ))
    }


def _fft_features(ctx: _Context) -> None:
    """Six statistics over the magnitude spectrum of each object's bbox FFT.

    For each object the bounding-box crop is multiplied by the object mask
    (background zeroed) and passed through ``np.fft.fft2``. Statistics are
    over ``|F|``; the energy column reports ``sum(|F|**2)`` explicitly.

    Entropy uses an explicit ``fft_entropy_bins``-bin histogram over the
    per-object magnitude range. ``skimage.measure.shannon_entropy`` is
    avoided here because it bins by unique value and degenerates to
    ``log(N)`` on float magnitudes.

    No windowing or padding is applied. Switch to a windowed crop or a
    fixed-size pad if you need cross-object comparability of high-
    frequency power.

    Adds:
        fft_mean, fft_std, fft_energy, fft_entropy,
        fft_skewness, fft_kurtosis
    """
    _assign_channelised(
        ctx,
        lambda image: _fft_values(
            image, ctx.masks, ctx.labels, ctx.slices, ctx.params
        ),
    )


def _fft_values(
    img: np.ndarray,
    masks: np.ndarray,
    labels: np.ndarray,
    slices: list,
    params: dict,
) -> dict[str, np.ndarray]:
    from scipy.stats import skew as sstat_skew, kurtosis as sstat_kurt

    n_bins = int(params.get("fft_entropy_bins", 256))
    n = len(labels)
    out = np.full((n, 6), np.nan, dtype=np.float64)

    for i, lab in enumerate(labels):
        sl = slices[int(lab) - 1]
        if sl is None:
            continue
        m = masks[sl] == lab
        if not m.any():
            continue
        crop = img[sl].astype(np.float64) * m
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
        key: out[:, col]
        for col, key in enumerate((
        "fft_mean", "fft_std", "fft_energy",
        "fft_entropy", "fft_skewness", "fft_kurtosis",
        ))
    }


def _glrlm_features(ctx: _Context) -> None:
    """Four gray-level run-length features summed over four 2D directions.

    The intensity image is quantised to ``glrlm_levels`` (default 16). For
    each object the bounding-box crop is masked to ``-1`` outside the
    object so runs never cross into neighbouring labels or background.
    The four-direction summed run-length matrix ``P(g, r)`` is then built
    one line at a time via ``_runs_in_line``.

    Gray levels are stored 0-indexed in the matrix but 1-indexed in the
    formulas (``g = matrix_row + 1``) to keep ``LGLRE`` finite for the
    darkest gray level.

    Adds:
        glrlm_rlnu   run length non-uniformity     sum_r (sum_g P)^2 / TR
        glrlm_lglre  low gray level run emphasis   sum_{g,r} P / g^2 / TR
        glrlm_hglre  high gray level run emphasis  sum_{g,r} P * g^2 / TR
        glrlm_glnu   gray level non-uniformity     sum_g (sum_r P)^2 / TR
    """
    _assign_channelised(
        ctx,
        lambda image: _glrlm_values(
            image, ctx.masks, ctx.labels, ctx.slices, ctx.params
        ),
    )


def _glrlm_values(
    img: np.ndarray,
    masks: np.ndarray,
    labels: np.ndarray,
    slices: list,
    params: dict,
) -> dict[str, np.ndarray]:
    n_levels = int(params.get("glrlm_levels", 16))
    img_arr = np.asarray(img)
    vmax = float(img_arr.max()) if img_arr.size else 1.0
    if vmax <= 0:
        vmax = 1.0
    img_q = np.clip(
        img_arr.astype(np.float64) / vmax * (n_levels - 1), 0, n_levels - 1
    ).astype(np.int16)

    n = len(labels)
    out = np.full((n, 4), np.nan, dtype=np.float64)
    g = np.arange(1, n_levels + 1, dtype=np.float64)[:, None]

    for i, lab in enumerate(labels):
        sl = slices[int(lab) - 1]
        if sl is None:
            continue
        m = masks[sl] == lab
        if not m.any():
            continue
        crop_q_obj = np.where(m, img_q[sl], -1).astype(np.int16)
        P = _glrlm_matrix_4dir(crop_q_obj, n_levels).astype(np.float64)
        TR = float(P.sum())
        if TR == 0:
            continue
        sum_g = P.sum(axis=0)   # over gray levels -> per run length
        sum_r = P.sum(axis=1)   # over run lengths -> per gray level
        out[i] = [
            float((sum_g ** 2).sum() / TR),
            float((P / (g ** 2)).sum() / TR),
            float((P * (g ** 2)).sum() / TR),
            float((sum_r ** 2).sum() / TR),
        ]

    return {
        key: out[:, col]
        for col, key in enumerate((
        "glrlm_rlnu", "glrlm_lglre", "glrlm_hglre", "glrlm_glnu",
        ))
    }


def _runs_in_line(line: np.ndarray):
    """Run-length decomposition of a 1D integer array.

    Pixels marked as negative (the background sentinel ``-1`` placed by
    ``_glrlm_features`` outside the object) are filtered after run
    detection, so runs never span across the object boundary.

    Returns ``(gray_levels, run_lengths)`` -- two 1D arrays of equal
    length.
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


def _glrlm_matrix_4dir(crop_q: np.ndarray, n_levels: int) -> np.ndarray:
    """Sum of run-length matrices over directions 0, 45, 90, 135 degrees.

    Returns a matrix of shape ``(n_levels, max(H, W))`` where the second
    axis is indexed by ``run_length - 1``. Most entries are zero for
    typical objects; dense storage keeps inner-loop indexing O(1).
    """
    H, W = crop_q.shape
    if H == 0 or W == 0:
        return np.zeros((n_levels, 1), dtype=np.int64)
    P = np.zeros((n_levels, max(H, W)), dtype=np.int64)

    def _accumulate(lines):
        for line in lines:
            vals, lens = _runs_in_line(line)
            if vals.size:
                np.add.at(P, (vals, lens - 1), 1)

    _accumulate(crop_q)                                                          # 0
    _accumulate(crop_q.T)                                                        # 90
    _accumulate(np.diagonal(crop_q, k) for k in range(-H + 1, W))                # 45
    _accumulate(np.diagonal(np.fliplr(crop_q), k) for k in range(-H + 1, W))     # 135
    return P


# ===========================================================================
# Family: Morphology
# ===========================================================================

def _radius_of_gyration_and_spread(ctx: _Context) -> None:
    """Radius of gyration and normalised intensity radial variance.

    Both quantities are computed from the per-object bounding-box crop;
    ``regionprops_table('coords')`` is intentionally avoided because it
    materialises a per-object Python object array that scales poorly with
    object count.

    Closed-form sanity values for a uniform-intensity disk of radius R::

        radius_of_gyration                         = R / sqrt(2)
        intensity_radial_variance_normalised       = 1

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
            spread[i] = float((u * d2).sum() / (u_mean * N * rg_v ** 2))

    ctx.props["radius_of_gyration"] = rg
    ctx.props["intensity_radial_variance_normalised"] = spread


# ===========================================================================
# Registry. Single source of truth for which extras exist, which family
# they belong to, and which need per-object bounding boxes. ``EXTRAS``
# drives dispatch, group expansion, validation messages, and the public
# ``FEATURE_GROUPS`` table.
#
# To add a new extra:
#   1. write a ``_my_handler(ctx)`` function in the appropriate family
#      section above;
#   2. add an entry below.
# ===========================================================================

@dataclass(frozen=True)
class _Extra:
    handler: Callable[[_Context], None]
    family: str
    needs_bbox: bool


EXTRAS: dict[str, _Extra] = {
    "global_bg":    _Extra(_global_bg_mean,                "intensity",     False),
    "local_bg":     _Extra(_local_bg_collar,               "intensity",     True),
    "neighbours":   _Extra(_neighbour_features,            "neighbourhood", False),
    "gradients":    _Extra(_gradient_means,                "texture",       False),
    "stat_texture": _Extra(_statistical_texture,           "texture",       False),
    "lbp":          _Extra(_lbp_features,                  "texture",       True),
    "fft":          _Extra(_fft_features,                  "texture",       True),
    "glrlm":        _Extra(_glrlm_features,                "texture",       True),
    "rg_spread":    _Extra(_radius_of_gyration_and_spread, "morphology",    True),
}


FEATURE_GROUPS: dict[str, set[str]] = {
    family: {name for name, e in EXTRAS.items() if e.family == family}
    for family in {e.family for e in EXTRAS.values()}
}
FEATURE_GROUPS["all"] = set(EXTRAS)
