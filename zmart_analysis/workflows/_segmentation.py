"""Shared image loading and Cellpose segmentation helpers.

Reads through :mod:`_image_io`, so a position is segmented the same whether
the driver wrote it as OME-TIFF planes or as an OME-Zarr store.
"""

from __future__ import annotations

import operator

import numpy as np

from _image_io import load_channels


def segment_position(
    image_path,
    state: dict,
    *,
    channels=None,
    channel_axis=None,
    border_margin_px=None,
    min_area_px=None,
    max_area_px=None,
    cellprob_threshold=None,
    flow_threshold=None,
    niter=None,
    diameter=None,
    segmentation_binning=None,
    gpu: bool = True,
    verbose: int = 0,
    log_prefix: str = "segment",
) -> dict:
    """Load a position, select up to three channels, and run a warm Cellpose model.

    ``image_path`` is an OME-Zarr position or an OME-TIFF; both are read
    through the same contract, so nothing below this line knows which it was.
    Cellpose runs on the selected channels (2D or up to 3-channel). ``image``
    preserves those selected channels for downstream feature extraction, while
    ``image_2d`` is the primary channel for code paths that require a plane.

    ``channel_axis`` applies only to an array already in memory and is kept
    for callers that hand one over; a file's axes come from its own metadata.
    """
    seg_input, _ = load_channels(image_path, channels)
    ny, nx = seg_input.shape[:2]
    seg_eval, scale = _downsample_for_segmentation(
        seg_input,
        binning=segmentation_binning,
    )

    cellpose_channel_axis = -1 if seg_eval.ndim == 3 else None
    eval_kwargs = _cellpose_eval_kwargs(
        cellprob_threshold=cellprob_threshold,
        flow_threshold=flow_threshold,
        niter=niter,
        diameter=diameter,
    )
    model, used_gpu, used_device = _get_cellpose_model(
        state,
        requested_gpu=bool(gpu),
        verbose=verbose,
        log_prefix=log_prefix,
    )
    try:
        masks, flows, styles = model.eval(
            seg_eval,
            channel_axis=cellpose_channel_axis,
            **eval_kwargs,
        )
    except Exception:
        if not gpu:
            raise
        if verbose >= 1:
            print(f"  [{log_prefix}] GPU Cellpose failed; retrying on CPU")
        state.pop("model", None)
        state.pop("_cellpose_model_gpu", None)
        state.pop("_cellpose_model_device", None)
        model, used_gpu, used_device = _get_cellpose_model(
            state,
            requested_gpu=False,
            verbose=verbose,
            log_prefix=log_prefix,
        )
        masks, flows, styles = model.eval(
            seg_eval,
            channel_axis=cellpose_channel_axis,
            **eval_kwargs,
        )
    if scale != 1.0:
        masks = _resize_nearest(masks, (ny, nx))
    raw_masks = np.asarray(masks, dtype=np.int32)
    raw_n_objects = int(raw_masks.max())
    # Border first, then size: an object clipped by the tile edge has a
    # smaller area than the object really is, so filtering by size before
    # dropping it would judge it on a measurement the edge invented.
    masks, dropped_labels = filter_masks_by_border(
        raw_masks, border_margin_px=border_margin_px
    )
    masks, dropped_by_area = filter_masks_by_area(
        masks,
        min_area_px=min_area_px,
        max_area_px=max_area_px,
    )
    dropped_labels = sorted(set(dropped_labels) | set(dropped_by_area))
    n_objects = int(masks.max())

    image_2d = seg_input if seg_input.ndim == 2 else seg_input[..., 0]

    if verbose >= 1:
        seg_ny, seg_nx = seg_eval.shape[:2]
        print(
            f"  [{log_prefix}] image={nx}x{ny}, "
            f"segmentation={seg_nx}x{seg_ny}, objects={n_objects}"
        )

    return {
        "image": seg_input,
        "image_2d": image_2d,
        "raw_masks": raw_masks,
        "masks": masks,
        "n_objects": n_objects,
        "n_raw_objects": raw_n_objects,
        "dropped_labels": dropped_labels,
        "area_filter": {
            "min_area_px": _none_or_int(min_area_px),
            "max_area_px": _none_or_int(max_area_px),
        },
        "border_filter": {"border_margin_px": _none_or_int(border_margin_px)},
        "cellpose_params": {
            "requested_gpu": bool(gpu),
            "used_gpu": bool(used_gpu),
            "device": used_device,
            "cellprob_threshold": _none_or_float(cellprob_threshold),
            "flow_threshold": _none_or_float(flow_threshold),
            "niter": _none_or_int(niter),
            "diameter": _none_or_float(diameter),
        },
        "segmentation_resize": {
            "binning": _none_or_int(segmentation_binning),
            "scale": float(scale),
            "input_size_px": [int(seg_eval.shape[1]), int(seg_eval.shape[0])],
        },
        "image_size_px": [int(nx), int(ny)],
    }


def _get_cellpose_model(state, *, requested_gpu: bool, verbose: int, log_prefix: str):
    if "model" in state:
        return (
            state["model"],
            bool(state.get("_cellpose_model_gpu", requested_gpu)),
            state.get("_cellpose_model_device", "cuda" if requested_gpu else "cpu"),
        )

    from cellpose import models

    errors = []
    for device_name, is_accelerated, kwargs in _cellpose_device_candidates(requested_gpu):
        try:
            if verbose >= 2:
                print(f"  [{log_prefix}] cold start: loading CellposeModel({device_name})")
            state["model"] = _instantiate_cellpose_model(models, kwargs)
            state["_cellpose_model_gpu"] = is_accelerated
            state["_cellpose_model_device"] = device_name
            return state["model"], is_accelerated, device_name
        except Exception as exc:
            errors.append(f"{device_name}: {exc}")
            if verbose >= 1 and device_name != "cpu":
                print(f"  [{log_prefix}] Cellpose {device_name} unavailable; trying next device")

    raise RuntimeError("Could not initialize CellposeModel on any device: " + "; ".join(errors))


def _cellpose_device_candidates(prefer_accelerator: bool):
    if not prefer_accelerator:
        return [("cpu", False, {"gpu": False})]

    candidates = []
    try:
        import torch
    except Exception:
        torch = None

    if torch is not None and torch.cuda.is_available():
        candidates.append(("cuda", True, {"gpu": True, "device": torch.device("cuda")}))
    if (
        torch is not None
        and hasattr(torch.backends, "mps")
        and torch.backends.mps.is_available()
    ):
        candidates.append(("mps", True, {"gpu": True, "device": torch.device("mps")}))
    candidates.append(("cpu", False, {"gpu": False}))
    return candidates


def _instantiate_cellpose_model(models, kwargs):
    try:
        return models.CellposeModel(**kwargs)
    except TypeError:
        if "device" not in kwargs:
            raise
        return models.CellposeModel(gpu=bool(kwargs.get("gpu", False)))


def select_channels(image, channels=None, channel_axis=None):
    """Return up to three channels for Cellpose as ``(H, W)`` or ``(H, W, k)``.

    ``channels`` chooses which channels to keep; ``None`` uses the first up to
    three. A single selected channel is returned as a 2D plane.

    ``channel_axis`` declares the orientation of a 3D input explicitly: ``0``
    for channel-first ``(C, H, W)`` or ``-1``/``2`` for channel-last
    ``(H, W, C)``. When it is ``None`` the orientation is inferred by treating
    the smaller end axis as the channel axis. Inference is refused when the two
    end axes are equal, because channel-first and channel-last are then
    indistinguishable; pass ``channel_axis`` in that case.
    """
    if image.ndim == 2:
        if channels is not None:
            indices = _channel_indices(channels)
            if indices not in ([], [0]):
                raise ValueError("channels for a 2D image must be None or [0].")
        return image
    if image.ndim != 3:
        raise ValueError(
            f"Cannot select channels from image with shape {image.shape}. "
            f"Expected 2D (H, W) or 2D plus channels: (C, H, W) / (H, W, C)."
        )

    stack = _to_channel_last(image, channel_axis)
    n_channels = stack.shape[-1]
    if channels is None:
        indices = list(range(min(n_channels, 3)))
    else:
        indices = _channel_indices(channels)
        if not indices:
            raise ValueError("channels must contain at least one channel.")
        if len(indices) > 3:
            raise ValueError("Cellpose accepts at most 3 channels.")
        if any(c < 0 or c >= n_channels for c in indices):
            raise ValueError(
                f"channels {indices} out of range for {n_channels} channels."
            )

    selected = stack[..., indices]
    if selected.shape[-1] == 1:
        return selected[..., 0]
    return selected


def _to_channel_last(image, channel_axis):
    """Normalize a 3D array to channel-last ``(H, W, C)``.

    With ``channel_axis`` given, the orientation is taken as declared. With
    ``channel_axis=None`` it is inferred from axis sizes: the smaller end axis
    is the channel axis. Equal end axes are ambiguous and raise ``ValueError``.
    """
    if channel_axis is not None:
        if isinstance(channel_axis, (bool, np.bool_)):
            raise ValueError(
                f"channel_axis must be 0, 2, -1, or None; got {channel_axis}."
            )
        try:
            channel_axis = operator.index(channel_axis)
        except TypeError as exc:
            raise ValueError(
                f"channel_axis must be 0, 2, -1, or None; got {channel_axis}."
            ) from exc
        if channel_axis in (-1, 2):
            return image
        if channel_axis == 0:
            return np.moveaxis(image, 0, -1)
        raise ValueError(
            f"channel_axis must be 0, 2, -1, or None; got {channel_axis}."
        )

    first, last = image.shape[0], image.shape[-1]
    if first == last:
        raise ValueError(
            f"Cannot infer channel axis for image with shape {image.shape}: "
            f"the first and last axes are equal, so channel-first (C, H, W) "
            f"and channel-last (H, W, C) are indistinguishable. Pass "
            f"channel_axis explicitly (0 for channel-first, -1 for "
            f"channel-last)."
        )
    # Channels are fewer than spatial pixels, so the smaller end is the
    # channel axis; channel-first is normalized to channel-last.
    if first < last:
        return np.moveaxis(image, 0, -1)
    return image


def _channel_indices(channels) -> list[int]:
    if isinstance(channels, (int, np.integer)):
        return [int(channels)]
    return [int(c) for c in channels]


def filter_masks_by_area(masks, *, min_area_px=None, max_area_px=None):
    min_area_px = _none_or_int(min_area_px)
    max_area_px = _none_or_int(max_area_px)
    if min_area_px is not None and min_area_px < 0:
        raise ValueError("min_area_px must be >= 0.")
    if max_area_px is not None and max_area_px < 0:
        raise ValueError("max_area_px must be >= 0.")
    if (
        min_area_px is not None
        and max_area_px is not None
        and max_area_px < min_area_px
    ):
        raise ValueError("max_area_px must be >= min_area_px.")
    if min_area_px is None and max_area_px is None:
        return masks, []

    masks = np.asarray(masks)
    areas = np.bincount(masks.ravel())
    keep = np.ones(len(areas), dtype=bool)
    keep[0] = False
    if min_area_px is not None:
        keep &= areas >= min_area_px
    if max_area_px is not None:
        keep &= areas <= max_area_px

    present = np.flatnonzero(areas)
    return _keep_labels(masks, [int(l) for l in present if l and keep[l]])


def filter_masks_by_border(masks, *, border_margin_px=None):
    """Drop objects lying within ``border_margin_px`` pixels of the edge.

    Tiles overlap, so an object near a tile's edge is very likely to appear
    again in the neighbouring tile. Rejecting a band at every edge keeps each
    object once, and does it without either tile having to know the other
    exists -- which is why a margin is preferred here over reconciling
    duplicates afterwards.

    The margin is the width of the rejected band at each edge, in pixels of
    the mask. ``None`` or ``0`` rejects nothing. Set it to about half the
    overlap and an object counted twice becomes an object counted once; set
    it wider and objects are lost from the seam instead.

    Returns ``(masks, dropped_labels)`` with the survivors relabelled from 1,
    matching :func:`filter_masks_by_area`.
    """
    border_margin_px = _none_or_int(border_margin_px)
    if border_margin_px is not None and border_margin_px < 0:
        raise ValueError("border_margin_px must be >= 0.")
    if not border_margin_px:
        return masks, []

    masks = np.asarray(masks)
    height, width = masks.shape[:2]
    if 2 * border_margin_px >= min(height, width):
        raise ValueError(
            f"border_margin_px={border_margin_px} leaves no interior in a "
            f"{height}x{width} tile."
        )

    margin = border_margin_px
    touching = set(np.unique(np.concatenate([
        masks[:margin, :].ravel(), masks[-margin:, :].ravel(),
        masks[:, :margin].ravel(), masks[:, -margin:].ravel(),
    ])).tolist())
    present = np.flatnonzero(np.bincount(masks.ravel()))
    return _keep_labels(masks, [int(l) for l in present if l and l not in touching])


def _keep_labels(masks, keep: list[int]):
    """Renumber *keep* from 1 and drop the rest; return (masks, dropped).

    Both filters end here, because relabelling after a drop is one operation
    however the labels were chosen.
    """
    mapping = np.zeros(int(masks.max()) + 1, dtype=np.int32)
    mapping[keep] = np.arange(1, len(keep) + 1, dtype=np.int32)
    dropped = sorted(set(np.flatnonzero(np.bincount(masks.ravel())).tolist())
                     - set(keep) - {0})
    return mapping[masks].astype(np.int32, copy=False), [int(d) for d in dropped]


_filter_masks_by_area = filter_masks_by_area


def _downsample_for_segmentation(image, *, binning=None):
    binning = _none_or_int(binning)
    if binning is None:
        return image, 1.0
    if binning <= 0:
        raise ValueError("segmentation_binning must be > 0.")
    if binning == 1:
        return image, 1.0
    ny, nx = image.shape[:2]
    out_shape = (
        max(1, int(round(ny / float(binning)))),
        max(1, int(round(nx / float(binning)))),
    )
    return _resize_area(image, out_shape), out_shape[0] / float(ny)


def _resize_area(image, shape):
    out_ny, out_nx = [int(v) for v in shape]
    if out_ny <= 0 or out_nx <= 0:
        raise ValueError("resize shape must be positive.")

    arr = np.asarray(image)
    in_ny, in_nx = arr.shape[:2]
    if out_ny > in_ny or out_nx > in_nx:
        raise ValueError("area resize is downsample-only.")
    if out_ny == in_ny and out_nx == in_nx:
        return arr

    work = arr.astype(np.float32, copy=False)
    work = _area_resize_axis(work, out_ny, axis=0)
    work = _area_resize_axis(work, out_nx, axis=1)
    return work


def _area_resize_axis(arr, out_size, axis):
    arr = np.asarray(arr)
    in_size = arr.shape[axis]
    if out_size == in_size:
        return arr

    scale = in_size / float(out_size)
    out_shape = list(arr.shape)
    out_shape[axis] = out_size
    out = np.empty(out_shape, dtype=np.float32)

    for out_idx in range(out_size):
        start = out_idx * scale
        stop = (out_idx + 1) * scale
        lo = int(np.floor(start))
        hi = int(np.ceil(stop))
        weights = np.array(
            [
                max(0.0, min(stop, src_idx + 1) - max(start, src_idx))
                for src_idx in range(lo, hi)
            ],
            dtype=np.float32,
        )
        selector = [slice(None)] * arr.ndim
        selector[axis] = slice(lo, hi)
        segment = arr[tuple(selector)]
        weight_shape = [1] * arr.ndim
        weight_shape[axis] = len(weights)
        reduced = (segment * weights.reshape(weight_shape)).sum(axis=axis) / scale
        out_selector = [slice(None)] * arr.ndim
        out_selector[axis] = out_idx
        out[tuple(out_selector)] = reduced
    return out


def _resize_nearest(image, shape):
    out_ny, out_nx = [int(v) for v in shape]
    if out_ny <= 0 or out_nx <= 0:
        raise ValueError("resize shape must be positive.")

    arr = np.asarray(image)
    in_ny, in_nx = arr.shape[:2]
    rows = np.minimum((np.arange(out_ny) * in_ny // out_ny), in_ny - 1)
    cols = np.minimum((np.arange(out_nx) * in_nx // out_nx), in_nx - 1)
    if arr.ndim == 2:
        return arr[rows[:, None], cols]
    return arr[rows[:, None], cols, :]


def _cellpose_eval_kwargs(
    *,
    cellprob_threshold=None,
    flow_threshold=None,
    niter=None,
    diameter=None,
):
    kwargs = {}
    if cellprob_threshold is not None:
        kwargs["cellprob_threshold"] = float(cellprob_threshold)
    if flow_threshold is not None:
        kwargs["flow_threshold"] = float(flow_threshold)
    if niter is not None:
        kwargs["niter"] = int(niter)
    if diameter is not None:
        kwargs["diameter"] = float(diameter)
    return kwargs


def _none_or_int(value):
    return None if value is None else int(value)


def _none_or_float(value):
    return None if value is None else float(value)
