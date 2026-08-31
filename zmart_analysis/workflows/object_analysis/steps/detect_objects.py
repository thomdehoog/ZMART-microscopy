"""detect_objects -- Cellpose object detection for one image tile."""

from __future__ import annotations
from typing import Any
from collections.abc import Mapping

import hashlib
import json
import math
import operator
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


METADATA = {
    "description": "Detect objects in a TIFF tile with Cellpose",
    "version": "1.0",
    "max_workers": 1,
    "environment": "ZMART--object_analysis--vision",
}


def run(pipeline_data: dict, state: dict, **params) -> dict:
    verbose = pipeline_data.get("metadata", {}).get("verbose", 0)
    inp = pipeline_data["input"]
    seg_params = segmentation_params(inp, params)
    area_params = area_filter_params(inp, params)
    border_params = border_filter_params(inp, params)
    gpu = inp.get("gpu", params.get("gpu", True))
    detection = segment_position(
        inp["image_path"],
        state,
        channels=seg_params["channels"],
        channel_axis=seg_params["channel_axis"],
        border_margin_px=border_params["border_margin_px"],
        min_area_px=area_params["min_area_px"],
        max_area_px=area_params["max_area_px"],
        cellprob_threshold=seg_params["cellprob_threshold"],
        flow_threshold=seg_params["flow_threshold"],
        niter=seg_params["niter"],
        diameter=seg_params["diameter"],
        segmentation_binning=seg_params["segmentation_binning"],
        gpu=gpu,
        verbose=verbose,
        log_prefix="detect_objects",
    )
    detection["area_filter"] = area_params
    detection["border_filter"] = border_params
    raw_masks = detection.pop("raw_masks")
    detection["segmentation_params"] = seg_params
    detection["segmentation_params_hash"] = segmentation_params_hash(seg_params)
    artifacts = _write_detection_checkpoint(detection, raw_masks, inp, params)
    if artifacts:
        detection["artifacts"] = artifacts

    if bool(params.get("persist_only", False)):
        detection = _slim_detection_result(detection)
        pipeline_data["detect_objects"] = detection
        return pipeline_data

    pipeline_data["detect_objects"] = detection
    # Bridge to the shared classical feature extractor's current input contract.
    # Extra channels ride along channel-last, so intensity features come out
    # per colour (name, name_c0, name_c1, ...); segmentation itself stays on
    # the single image it was handed.
    image = detection["image"]
    extra_paths = inp.get("extra_channel_paths") or []
    if extra_paths:
        from tifffile import imread

        planes = [np.asarray(image)]
        planes += [np.asarray(imread(str(path))) for path in extra_paths]
        image = np.stack(planes, axis=-1)
    pipeline_data["preprocess"] = {"image": image}
    pipeline_data["segment"] = {
        "masks": detection["masks"],
        "n_cells": detection["n_objects"],
    }
    return pipeline_data


def _write_detection_checkpoint(detection: dict, raw_masks, inp: dict, params: dict) -> dict:
    output_dir = inp.get("output_dir", params.get("output_dir", None))
    # An image inside an acquisition files itself, in the `analysis` folder
    # beside the `data` it came from. One kept outside an acquisition has no
    # such place, and writes nothing unless the caller says where.
    if output_dir is None:
        output_dir = analysis_dir(inp["image_path"])
    if output_dir is None:
        return {}

    import tifffile

    # Filed under the frame's own short name -- the name the driver wrote,
    # minus the channel and plane, which analysis of a frame spans.
    tile_dir = Path(output_dir) / "tiles" / short_name(inp["image_path"])
    tile_dir.mkdir(parents=True, exist_ok=True)
    masks_path = tile_dir / "masks.tif"
    raw_masks_path = tile_dir / "raw_masks.tif"
    checkpoint_path = tile_dir / "detection_checkpoint.json"
    tifffile.imwrite(masks_path, detection["masks"].astype("int32"))
    tifffile.imwrite(raw_masks_path, raw_masks.astype("int32"))

    checkpoint = {
        "image_path": str(inp["image_path"]),
        "image_sha256": file_sha256(inp["image_path"]),
        "tile_id": inp["tile_id"],
        "tile_stage_xy_um": inp["tile_stage_xy_um"],
        "tile_z_um": inp.get("tile_z_um"),
        "source_pixel_size_um": inp["source_pixel_size_um"],
        "source_image_size_px": inp.get("source_image_size_px", detection.get("image_size_px")),
        "image_to_stage": inp["image_to_stage"],
        "segmentation_params": detection["segmentation_params"],
        "segmentation_params_hash": detection["segmentation_params_hash"],
        "n_objects": detection["n_objects"],
        "n_raw_objects": detection["n_raw_objects"],
        "dropped_labels": detection["dropped_labels"],
        "area_filter": detection["area_filter"],
        "border_filter": detection["border_filter"],
        "cellpose_params": detection["cellpose_params"],
        "segmentation_resize": detection["segmentation_resize"],
        "image_size_px": detection["image_size_px"],
        "raw_masks_path": str(raw_masks_path),
        "raw_masks_sha256": file_sha256(raw_masks_path),
        "masks_path": str(masks_path),
        "masks_sha256": file_sha256(masks_path),
    }
    checkpoint_path.write_text(json.dumps(to_builtin(checkpoint), indent=2) + "\n", encoding="utf-8")
    return {
        "masks_tif": str(masks_path),
        "raw_masks_tif": str(raw_masks_path),
        "detection_checkpoint_json": str(checkpoint_path),
    }


def _slim_detection_result(detection: dict) -> dict:
    """Return checkpoint metadata without large image/mask arrays."""
    return {
        key: value
        for key, value in detection.items()
        if key not in {"image", "image_2d", "masks"}
    }


#: A driver writes one file per C and Z of a frame; this is the tail that
#: varies within one, and everything before it names the frame.
_PLANE = re.compile(r"_C\d{2}_Z\d{5}\.ome\.tiff?$", re.IGNORECASE)


def short_name(image_path: Path | str) -> str:
    """``..._T000000_C00_Z00000.ome.tiff`` -> ``..._T000000``.

    Results are filed under the frame, not one plane of it. A name outside the
    convention keeps its bare stem.
    """
    name = Path(image_path).name
    frame = _PLANE.sub("", name)
    return frame if frame != name else name.split(".")[0]


def analysis_dir(image_path: Path | str) -> Path | None:
    """The ``analysis`` folder beside the ``data`` an image came from.

    The nearest ``data`` wins. ``None`` for an image kept outside an
    acquisition, which has no folder to be filed under and is a thing that
    happens rather than a thing that is wrong.
    """
    for folder in Path(image_path).parents:
        if folder.name == "data":
            return folder.parent / "analysis"
    return None


SEGMENTATION_IDENTITY_KEYS = (
    "channels",
    "channel_axis",
    "cellprob_threshold",
    "flow_threshold",
    "niter",
    "diameter",
    "segmentation_binning",
)


def segmentation_params(inp: dict, params: dict) -> dict:
    """Return params that define mask generation, excluding runtime details."""
    return {
        "channels": inp.get("channels", params.get("channels", None)),
        "channel_axis": _channel_axis(
            inp.get("channel_axis", params.get("channel_axis", None))
        ),
        # From the submission when it names one, else the pipeline's default.
        # That is what lets an operator tune detection on a single position
        # and see the answer without re-registering a pipeline.
        "cellprob_threshold": _setting(inp, params, "cellprob_threshold"),
        "flow_threshold": _setting(inp, params, "flow_threshold"),
        "niter": _setting(inp, params, "niter"),
        "diameter": _setting(inp, params, "diameter"),
        "segmentation_binning": _setting(inp, params, "segmentation_binning"),
    }


def border_filter_params(inp: dict, params: dict) -> dict:
    """The overlap guard: how wide a band at each tile edge is rejected."""
    return {"border_margin_px": _none_or_int(
        _setting(inp, params, "border_margin_px")
    )}


def area_filter_params(inp: dict, params: dict) -> dict:
    """Return post-segmentation object-size filtering params."""
    min_area_px = _setting(inp, params, "min_area_px")
    max_area_px = _setting(inp, params, "max_area_px")
    min_diameter_um = _setting(inp, params, "min_equivalent_diameter_um")
    max_diameter_um = _setting(inp, params, "max_equivalent_diameter_um")

    min_area_px = _area_bound_px(
        area_px=min_area_px,
        diameter_um=min_diameter_um,
        source_pixel_size_um=_setting(inp, params, "source_pixel_size_um"),
        bound="min",
    )
    max_area_px = _area_bound_px(
        area_px=max_area_px,
        diameter_um=max_diameter_um,
        source_pixel_size_um=_setting(inp, params, "source_pixel_size_um"),
        bound="max",
    )
    if (
        min_area_px is not None
        and max_area_px is not None
        and max_area_px < min_area_px
    ):
        raise ValueError("max object size must be >= min object size.")
    return {
        "min_area_px": min_area_px,
        "max_area_px": max_area_px,
        "min_equivalent_diameter_um": _none_or_float(min_diameter_um),
        "max_equivalent_diameter_um": _none_or_float(max_diameter_um),
    }


def _setting(inp: dict, params: dict, key: str):
    return inp.get(key, params.get(key, None))


def _area_bound_px(*, area_px, diameter_um, source_pixel_size_um, bound: str):
    area_px = _none_or_int(area_px)
    diameter_um = _none_or_float(diameter_um)
    if area_px is not None and diameter_um is not None:
        raise ValueError(
            f"Specify either {bound}_area_px or {bound}_equivalent_diameter_um, "
            "not both."
        )
    if area_px is not None:
        if area_px < 0:
            raise ValueError(f"{bound}_area_px must be >= 0.")
        return area_px
    if diameter_um is None:
        return None
    if diameter_um < 0:
        raise ValueError(f"{bound}_equivalent_diameter_um must be >= 0.")
    pixel_area_um2 = _pixel_area_um2(source_pixel_size_um)
    area_um2 = math.pi * (diameter_um / 2.0) ** 2
    area_px_float = area_um2 / pixel_area_um2
    if bound == "min":
        return int(math.ceil(area_px_float))
    if bound == "max":
        return int(math.floor(area_px_float))
    raise ValueError("bound must be 'min' or 'max'.")


def _pixel_area_um2(source_pixel_size_um):
    if source_pixel_size_um is None:
        raise ValueError(
            "source_pixel_size_um is required when filtering by equivalent diameter."
        )
    if isinstance(source_pixel_size_um, (int, float)):
        sx = sy = float(source_pixel_size_um)
    else:
        values = list(source_pixel_size_um)
        if len(values) == 0:
            raise ValueError("source_pixel_size_um cannot be empty.")
        sx = float(values[0])
        sy = float(values[1] if len(values) > 1 else values[0])
    if sx <= 0 or sy <= 0:
        raise ValueError("source_pixel_size_um values must be > 0.")
    return sx * sy


def _none_or_int(value):
    if value is None:
        return None
    return int(value)


def _none_or_float(value):
    if value is None:
        return None
    return float(value)


def _channel_axis(value):
    """Validate and normalize equivalent channel-last axis declarations."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(
            f"channel_axis must be 0, 2, -1, or None; got {value}."
        )
    try:
        value = operator.index(value)
    except TypeError as exc:
        raise ValueError(
            f"channel_axis must be 0, 2, -1, or None; got {value}."
        ) from exc
    if value == 0:
        return 0
    if value in (-1, 2):
        return -1
    raise ValueError(
        f"channel_axis must be 0, 2, -1, or None; got {value}."
    )


def segmentation_params_hash(params: dict) -> str:
    """Stable hash of true segmentation identity params.

    This deliberately excludes GPU/CPU placement and area filters. GPU is an
    execution detail, while area filters are applied after Cellpose and can be
    retuned from persisted raw masks.
    """
    identity = {key: params.get(key, None) for key in SEGMENTATION_IDENTITY_KEYS}
    identity["channel_axis"] = _channel_axis(identity["channel_axis"])
    text = json.dumps(to_builtin(identity), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_sha256(path: str | Path) -> str:
    """Return a SHA256 digest for a persisted artifact."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


REQUIRED_OBJECT_COLUMNS = (
    "label",
    "centroid_row_px",
    "centroid_col_px",
    "bbox_min_row_px",
    "bbox_min_col_px",
    "bbox_max_row_px",
    "bbox_max_col_px",
    "area",
    "intensity_mean",
    "eccentricity",
    "stage_x_um",
    "stage_y_um",
)

REQUIRED_GEOMETRY_FIELDS = (
    "tile_id",
    "tile_stage_xy_um",
    "source_pixel_size_um",
    "source_image_size_px",
    "image_to_stage",
)

REQUIRED_TARGET_FIELDS = (
    "target_id",
    "tile_id",
    "object_label",
    "score",
    "source_feature",
    "centroid_row_px",
    "centroid_col_px",
    "bbox_min_row_px",
    "bbox_min_col_px",
    "bbox_max_row_px",
    "bbox_max_col_px",
    "stage_x_um",
    "stage_y_um",
)


def to_builtin(obj: Any) -> Any:
    """Return a JSON-native copy of ``obj``.

    Numpy arrays/scalars are converted via ``tolist``/``item`` without
    importing numpy. Tuples become lists, and non-finite floats become
    ``None`` so ``json.dump(..., allow_nan=False)`` remains valid.
    """
    if obj is None or type(obj) in (str, bool, int):
        return obj
    if type(obj) is float:
        return obj if math.isfinite(obj) else None
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, Mapping):
        return {str(key): to_builtin(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_builtin(value) for value in obj]
    if hasattr(obj, "item"):
        try:
            return to_builtin(obj.item())
        except (TypeError, ValueError):
            pass
    if hasattr(obj, "tolist"):
        return to_builtin(obj.tolist())
    raise TypeError(f"Value of type {type(obj).__name__} is not JSON-native.")


def validate_tile_detection(tile: Mapping[str, Any]) -> dict:
    """Validate and return a JSON-native per-tile detection output."""
    tile = _json_checked(to_builtin(tile), "tile detection")
    if not isinstance(tile, dict):
        raise ValueError("tile detection must be a dict.")

    objects = _require_dict(tile, "objects", "tile detection")
    props = _require_dict(objects, "properties", "objects")
    n_objects = objects.get("n_objects")
    if not isinstance(n_objects, int) or isinstance(n_objects, bool) or n_objects < 0:
        raise ValueError("objects.n_objects must be a non-negative int.")

    for name in REQUIRED_OBJECT_COLUMNS:
        if name not in props:
            raise ValueError(f"objects.properties missing required column {name!r}.")

    for name, values in props.items():
        if not isinstance(values, list):
            raise ValueError(f"objects.properties[{name!r}] must be a list.")
        if len(values) != n_objects:
            raise ValueError(
                f"objects.properties[{name!r}] has length {len(values)}; "
                f"expected n_objects={n_objects}."
            )

    geometry = _require_dict(tile, "geometry", "tile detection")
    for name in REQUIRED_GEOMETRY_FIELDS:
        if name not in geometry:
            raise ValueError(f"geometry missing required field {name!r}.")

    _require_list_len(geometry, "tile_id", None, "geometry")
    _require_list_len(geometry, "tile_stage_xy_um", 2, "geometry")
    _require_list_len(geometry, "source_pixel_size_um", 2, "geometry")
    _require_list_len(geometry, "source_image_size_px", 2, "geometry")
    matrix = _require_list_len(geometry, "image_to_stage", 2, "geometry")
    for row in matrix:
        if not isinstance(row, list) or len(row) != 2:
            raise ValueError("geometry.image_to_stage must be a 2x2 list.")

    embeddings = objects.get("embeddings")
    if embeddings is not None:
        if not isinstance(embeddings, dict):
            raise ValueError("objects.embeddings must be a dict when present.")
        if "label" in embeddings:
            labels = embeddings["label"]
            if not isinstance(labels, list) or len(labels) != n_objects:
                raise ValueError(
                    "objects.embeddings.label must be a list aligned to n_objects."
                )
            if labels != props["label"]:
                raise ValueError(
                    "objects.embeddings.label must match objects.properties.label."
                )
        if "vectors" in embeddings:
            vectors = embeddings["vectors"]
            if not isinstance(vectors, list) or len(vectors) != n_objects:
                raise ValueError(
                    "objects.embeddings.vectors must be a list aligned to n_objects."
                )
            for idx, vector in enumerate(vectors):
                if not isinstance(vector, list):
                    raise ValueError(
                        f"objects.embeddings.vectors[{idx}] must be a list."
                    )

    return tile


def validate_targets(result: Mapping[str, Any]) -> dict:
    """Validate and return JSON-native target discovery output."""
    result = _json_checked(to_builtin(result), "targets result")
    if not isinstance(result, dict):
        raise ValueError("targets result must be a dict.")
    targets = result.get("targets")
    if not isinstance(targets, list):
        raise ValueError("targets must be a list.")

    for idx, target in enumerate(targets):
        if not isinstance(target, dict):
            raise ValueError(f"targets[{idx}] must be a dict.")
        for name in REQUIRED_TARGET_FIELDS:
            if name not in target:
                raise ValueError(f"targets[{idx}] missing required field {name!r}.")
        if not isinstance(target["target_id"], list):
            raise ValueError(f"targets[{idx}].target_id must be a list.")
        if not isinstance(target["tile_id"], list):
            raise ValueError(f"targets[{idx}].tile_id must be a list.")
        for name in REQUIRED_TARGET_FIELDS:
            if name in {"target_id", "tile_id"}:
                continue
            if isinstance(target[name], (dict, list)):
                raise ValueError(f"targets[{idx}].{name} must be a scalar.")

    return result


def _json_checked(obj: Any, label: str) -> Any:
    try:
        json.dumps(obj, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} is not JSON round-trippable: {exc}") from exc
    return obj


def _require_dict(parent: Mapping[str, Any], key: str, label: str) -> dict:
    value = parent.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{label}.{key} must be a dict.")
    return value


def _require_list_len(
    parent: Mapping[str, Any], key: str, expected_len: int | None, label: str
) -> list:
    value = parent.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{label}.{key} must be a list.")
    if expected_len is not None and len(value) != expected_len:
        raise ValueError(f"{label}.{key} must have length {expected_len}.")
    return value


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
