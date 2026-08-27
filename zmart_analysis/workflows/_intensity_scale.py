"""Run-level intensity scaling for object crop display and DINO input."""

from __future__ import annotations

import numpy as np

from _detection_checkpoint import area_filter_params


def compute_foreground_intensity_scale(
    fields,
    *,
    masks_by_tile=None,
    min_area_px=None,
    max_area_px=None,
    min_equivalent_diameter_um=None,
    max_equivalent_diameter_um=None,
    percentiles=(1, 99.5),
    max_samples_per_channel=250_000,
    mode="foreground_run",
):
    """Return shared per-channel intensity limits for a run.

    ``fields`` are dicts with ``image``, ``tile_id`` and pixel-size metadata.
    When ``masks_by_tile`` is provided, percentiles are computed over accepted
    object pixels only; otherwise all image pixels are sampled. The returned
    scale is intentionally run-level and should be recorded with embeddings
    when used for DINO input.
    """
    fields = list(fields if isinstance(fields, (list, tuple)) else [fields])
    if not fields:
        raise ValueError("compute_foreground_intensity_scale needs at least one field.")

    masks_by_tile = masks_by_tile or {}
    percentiles = tuple(float(v) for v in percentiles)
    per_channel = [[] for _ in range(3)]
    used_foreground = False

    for field in fields:
        arr = as_channel_last(field["image"])
        tile_id = tuple(field.get("tile_id", ()))
        masks = masks_by_tile.get(tile_id)
        valid = None
        if masks is not None:
            area_filter = object_size_filter(
                field,
                min_area_px=min_area_px,
                max_area_px=max_area_px,
                min_equivalent_diameter_um=min_equivalent_diameter_um,
                max_equivalent_diameter_um=max_equivalent_diameter_um,
            )
            valid = accepted_mask_pixels(np.asarray(masks), **area_filter)
            if valid.any():
                used_foreground = True
            else:
                valid = None

        for c in range(min(3, arr.shape[-1])):
            values = arr[..., c][valid] if valid is not None else arr[..., c].reshape(-1)
            values = sample_1d(values, max_samples_per_channel)
            if values.size:
                per_channel[c].append(values.astype(np.float32, copy=False))

    lo, hi = [], []
    for parts in per_channel:
        if not parts:
            lo.append(0.0)
            hi.append(1.0)
            continue
        values = np.concatenate(parts)
        c_lo, c_hi = np.percentile(values, percentiles)
        if c_hi <= c_lo:
            c_hi = c_lo + 1.0
        lo.append(float(c_lo))
        hi.append(float(c_hi))

    if per_channel[0] and not per_channel[1] and not per_channel[2]:
        lo[1:] = [lo[0], lo[0]]
        hi[1:] = [hi[0], hi[0]]

    return {
        "mode": "foreground_run" if used_foreground else str(mode),
        "percentiles": percentiles,
        "lo": lo,
        "hi": hi,
        "n_fields": len(fields),
        "foreground": bool(used_foreground),
    }


def dino_input_intensity_scale(scale):
    """Return the scale subset consumed by ``extract_deep_features``."""
    if scale is None:
        return None
    return {
        "mode": str(scale.get("mode", "foreground_run")),
        "foreground": bool(scale.get("foreground", False)),
        "lo": [float(v) for v in scale.get("lo", [])[:3]],
        "hi": [float(v) for v in scale.get("hi", [])[:3]],
    }


def object_size_filter(
    field=None,
    *,
    pixel_um=None,
    min_area_px=None,
    max_area_px=None,
    min_equivalent_diameter_um=None,
    max_equivalent_diameter_um=None,
):
    """Resolve notebook-facing size filters to pixel-area thresholds."""
    min_area_px = None if min_area_px == 0 else min_area_px
    if field is not None:
        source_pixel_size_um = field.get(
            "source_pixel_size_um",
            [field["pixel_um"], field["pixel_um"]],
        )
    elif pixel_um is not None:
        source_pixel_size_um = [float(pixel_um), float(pixel_um)]
    else:
        source_pixel_size_um = None
    return area_filter_params(
        {
            "source_pixel_size_um": source_pixel_size_um,
            "min_area_px": min_area_px,
            "max_area_px": max_area_px,
            "min_equivalent_diameter_um": min_equivalent_diameter_um,
            "max_equivalent_diameter_um": max_equivalent_diameter_um,
        },
        {},
    )


def accepted_mask_pixels(masks, *, min_area_px=None, max_area_px=None, **_):
    """Return a boolean mask of labels surviving the resolved area filter."""
    labels, areas = np.unique(masks[masks > 0], return_counts=True)
    if labels.size:
        keep = np.ones(labels.shape, dtype=bool)
        if min_area_px is not None:
            keep &= areas >= int(min_area_px)
        if max_area_px is not None:
            keep &= areas <= int(max_area_px)
        labels = labels[keep]
    if labels.size == 0:
        return np.zeros(masks.shape, dtype=bool)
    return np.isin(masks, labels)


def as_channel_last(stack):
    arr = np.asarray(stack)
    if arr.ndim == 2:
        return arr[..., None]
    if arr.ndim != 3:
        raise ValueError(f"Expected 2D/3D image, got shape {arr.shape}.")
    if arr.shape[0] <= 4 and arr.shape[1] > 4 and arr.shape[2] > 4:
        return np.moveaxis(arr, 0, -1)
    return arr


def sample_1d(values, max_samples):
    values = np.asarray(values).reshape(-1)
    if max_samples and values.size > max_samples:
        step = int(np.ceil(values.size / int(max_samples)))
        values = values[::step]
    return values
