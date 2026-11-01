"""segment_cellpose -- find the objects in one image tile with Cellpose.

Takes the image ``read_images`` read. Cellpose answers with a label image:
zero for background, a number of its own for every object. Then objects
within ``border_margin_px`` of the edge are dropped, because the neighbouring
tile holds them too, and so are objects outside the size bounds. The masks,
before and after the filters, and a record of how they were made are filed in
the ``analysis`` folder beside the image's ``data``.

Every setting has its default in the pipeline, and a submit may override any
of them for one image by naming the same key in its input.

``segment`` is everything around the detector: the binning, the filters and
the record. ``segment_watershed`` uses it too, with its own detector.

Publishes under ``pipeline_data["segment_cellpose"]``::

    masks            the label image after the filters
    n_objects        how many objects survived the filters
    n_raw_objects    how many the detector found
    dropped_labels   the labels the filters removed
    detector_params  which detector ran, on which device, with which tuning
    segmentation_params, segmentation_params_hash
                     what decided the masks, and its one-line identity
    artifacts        the files the record wrote, when it wrote any
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping
from functools import partial
from pathlib import Path

import numpy as np

METADATA = {
    "description": "Find the objects in an image tile with Cellpose",
    "version": "1.0",
    "max_workers": 1,
    "environment": "ZMART--object_analysis--cellpose",
}

#: The settings that change the masks themselves. The GPU and the filters are
#: left out: the GPU is where it ran, and the filters can be applied again to
#: the raw masks.
SEGMENTATION_IDENTITY_KEYS = (
    "z_selection",
    "method",
    "threshold",
    "channels",
    "cellprob_threshold",
    "flow_threshold",
    "niter",
    "diameter",
    "segmentation_binning",
)


def run(pipeline_data: dict, state: dict, **params) -> dict:

    verbose = pipeline_data.get("metadata", {}).get("verbose", 0)

    gpu = _setting(pipeline_data["input"], params, "gpu", True)

    # Cellpose on the warm model kept in this worker's state
    find_objects = partial(_cellpose_masks, state=state, gpu=gpu, verbose=verbose)

    pipeline_data["segment_cellpose"] = segment(pipeline_data, params, "robust", find_objects)

    return pipeline_data


def segment(pipeline_data: dict, params: dict, method: str, find_objects: Callable) -> dict:
    """Find the objects with ``find_objects``, filter them, and file the record.

    ``find_objects(image, scale, settings)`` gets the image at 1/binning of
    its size, that scale, and the segmentation settings, and returns the
    label image and the detector's parameters.
    """

    verbose = pipeline_data.get("metadata", {}).get("verbose", 0)

    given = pipeline_data["input"]

    images = pipeline_data["read_images"]

    settings = _segmentation_params(images, given, params, method)

    area = _area_filter_params(given, params)

    border = {"border_margin_px": _none_or_int(_setting(given, params, "border_margin_px"))}

    image = images["image"]

    ny, nx = image.shape[:2]

    # A smaller picture is faster; the masks come back to full size afterwards
    small, scale = _downsample(image, settings["segmentation_binning"])

    masks, detector_params = find_objects(small, scale, settings)

    if scale != 1.0:
        masks = _resize_nearest(masks, (ny, nx))

    raw_masks = np.asarray(masks, dtype=np.int32)

    # Border first, then size: an object cut by the edge looks smaller than it is
    masks, dropped_by_border = _filter_by_border(raw_masks, border["border_margin_px"])

    masks, dropped_by_area = filter_by_area(masks, area["min_area_px"], area["max_area_px"])

    detection = {
        "masks": masks,
        "n_objects": _count(masks),
        "n_raw_objects": _count(raw_masks),
        "dropped_labels": sorted(set(dropped_by_border) | set(dropped_by_area)),
        "area_filter": area,
        "border_filter": border,
        "detector_params": detector_params,
        "segmentation_resize": {
            "binning": _none_or_int(settings["segmentation_binning"]),
            "scale": float(scale),
            "input_size_px": [int(small.shape[1]), int(small.shape[0])],
        },
        "image_size_px": [int(nx), int(ny)],
        "segmentation_params": settings,
        "segmentation_params_hash": _segmentation_hash(settings),
    }

    if verbose >= 1:
        seg_ny, seg_nx = small.shape[:2]

        print(
            f"  [{method}] image={nx}x{ny}, segmentation={seg_nx}x{seg_ny}, objects={detection['n_objects']}"
        )

    artifacts = _write_checkpoint(detection, raw_masks, given, images, params)

    if artifacts:
        detection["artifacts"] = artifacts

    return detection


def filter_by_area(masks, min_area_px=None, max_area_px=None):
    """Drop objects smaller than ``min_area_px`` or larger than ``max_area_px``.

    Returns ``(masks, dropped_labels)``; the survivors keep their labels.
    ``segment_watershed`` uses this inside its detector too.
    """

    min_area_px, max_area_px = _none_or_int(min_area_px), _none_or_int(max_area_px)

    if min_area_px is not None and min_area_px < 0:
        raise ValueError("min_area_px must be >= 0.")

    if max_area_px is not None and max_area_px < 0:
        raise ValueError("max_area_px must be >= 0.")

    if min_area_px is not None and max_area_px is not None and max_area_px < min_area_px:
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

    return _keep_labels(masks, [int(label) for label in present if label and keep[label]])


def to_builtin(obj):
    """A copy of ``obj`` made of plain Python values that JSON can write.

    Arrays become lists, numpy scalars Python numbers, tuples lists, and a
    float that is not a number becomes None. ``build_object_table`` uses this too.
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

    # Only a true scalar is unwrapped: a one-element array stays a list
    if hasattr(obj, "item") and getattr(obj, "ndim", 0) == 0:
        try:
            return to_builtin(obj.item())
        except (TypeError, ValueError):
            pass

    if hasattr(obj, "tolist"):
        return to_builtin(obj.tolist())

    raise TypeError(f"Value of type {type(obj).__name__} is not JSON-native.")


def _setting(given: dict, params: dict, key: str, default=None):
    """One setting: the submit's when it names it, else the pipeline's."""

    return given[key] if key in given else params.get(key, default)


def _none_or_int(value):
    """``int(value)``, or None for None."""

    return None if value is None else int(value)


def _none_or_float(value):
    """``float(value)``, or None for None."""

    return None if value is None else float(value)


def _count(masks: np.ndarray) -> int:
    """How many objects a label image holds."""

    return int(np.count_nonzero(np.bincount(masks.ravel())[1:]))


def _segmentation_params(images: dict, given: dict, params: dict, method: str) -> dict:
    """The settings that decide what the masks look like."""

    return {
        "z_selection": images["z_selection"],
        "channels": images["channels"],
        "method": method,
        "threshold": _none_or_float(_setting(given, params, "threshold")),
        "cellprob_threshold": _setting(given, params, "cellprob_threshold"),
        "flow_threshold": _setting(given, params, "flow_threshold"),
        "niter": _setting(given, params, "niter"),
        "diameter": _setting(given, params, "diameter"),
        "segmentation_binning": _setting(given, params, "segmentation_binning"),
    }


def _segmentation_hash(settings: dict) -> str:
    """One short identity for the way a segmentation was made.

    Two detections with the same hash were made the same way. A key that is
    missing and a key that is None hash the same.
    """

    identity = {key: settings.get(key) for key in SEGMENTATION_IDENTITY_KEYS}

    text = json.dumps(to_builtin(identity), sort_keys=True, separators=(",", ":"))

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _area_filter_params(given: dict, params: dict) -> dict:
    """The size bounds in pixels, given as an area in pixels or a diameter in micrometres.

    One kind per side, not both. A diameter needs ``source_pixel_size_um``.
    """

    min_diameter_um = _setting(given, params, "min_equivalent_diameter_um")

    max_diameter_um = _setting(given, params, "max_equivalent_diameter_um")

    pixel_size = _setting(given, params, "source_pixel_size_um")

    min_area_px = _area_bound_px(
        _setting(given, params, "min_area_px"), min_diameter_um, pixel_size, "min"
    )

    max_area_px = _area_bound_px(
        _setting(given, params, "max_area_px"), max_diameter_um, pixel_size, "max"
    )

    if min_area_px is not None and max_area_px is not None and max_area_px < min_area_px:
        raise ValueError("max object size must be >= min object size.")

    return {
        "min_area_px": min_area_px,
        "max_area_px": max_area_px,
        "min_equivalent_diameter_um": _none_or_float(min_diameter_um),
        "max_equivalent_diameter_um": _none_or_float(max_diameter_um),
    }


def _area_bound_px(area_px, diameter_um, pixel_size_um, bound: str):
    """One size bound in pixels: the area as given, or the disc of the given diameter."""

    area_px, diameter_um = _none_or_int(area_px), _none_or_float(diameter_um)

    if area_px is not None and diameter_um is not None:
        raise ValueError(
            f"Specify either {bound}_area_px or {bound}_equivalent_diameter_um, not both."
        )

    if area_px is not None:
        if area_px < 0:
            raise ValueError(f"{bound}_area_px must be >= 0.")

        return area_px

    if diameter_um is None:
        return None

    if diameter_um < 0:
        raise ValueError(f"{bound}_equivalent_diameter_um must be >= 0.")

    area = math.pi * (diameter_um / 2.0) ** 2 / _pixel_area_um2(pixel_size_um)

    # A minimum rounds up and a maximum down, so neither lets in what it should not
    return int(math.ceil(area)) if bound == "min" else int(math.floor(area))


def _pixel_area_um2(pixel_size_um) -> float:
    """The area of one pixel, from one size or from [x, y]."""

    if pixel_size_um is None:
        raise ValueError("source_pixel_size_um is required when filtering by equivalent diameter.")

    if isinstance(pixel_size_um, (int, float)):
        sx = sy = float(pixel_size_um)

    else:
        values = list(pixel_size_um)

        if not values:
            raise ValueError("source_pixel_size_um cannot be empty.")

        sx, sy = float(values[0]), float(values[1] if len(values) > 1 else values[0])

    if sx <= 0 or sy <= 0:
        raise ValueError("source_pixel_size_um values must be > 0.")

    return sx * sy


def _filter_by_border(masks, border_margin_px=None):
    """Drop objects within ``border_margin_px`` pixels of the edge.

    Tiles overlap, so an object near the edge is likely in the next tile too.
    Rejecting a band at every edge keeps each object once without either tile
    knowing the other. About half the overlap is right. None or 0 drops nothing.
    """

    if border_margin_px is not None and border_margin_px < 0:
        raise ValueError("border_margin_px must be >= 0.")

    if not border_margin_px:
        return masks, []

    masks = np.asarray(masks)

    height, width = masks.shape[:2]

    margin = border_margin_px

    if 2 * margin >= min(height, width):
        raise ValueError(
            f"border_margin_px={margin} leaves no interior in a {height}x{width} tile."
        )

    edges = [masks[:margin, :], masks[-margin:, :], masks[:, :margin], masks[:, -margin:]]

    touching = set(np.unique(np.concatenate([edge.ravel() for edge in edges])).tolist())

    present = np.flatnonzero(np.bincount(masks.ravel()))

    return _keep_labels(masks, [int(label) for label in present if label and label not in touching])


def _keep_labels(masks, keep: list[int]):
    """Keep only the labels in ``keep``, at their own numbers; return (masks, dropped)."""

    present = np.flatnonzero(np.bincount(masks.ravel()))

    keep_set = {int(label) for label in keep}

    dropped = sorted(int(label) for label in present if label and int(label) not in keep_set)

    kept = np.where(np.isin(masks, list(keep_set)), masks, 0)

    return kept.astype(np.int32, copy=False), dropped


def _downsample(image, binning):
    """The image at 1/``binning`` of its size by averaging pixel blocks, and the scale.

    An area average keeps a bright nucleus bright instead of sampling it on
    or off. A binning of None or 1 changes nothing.
    """

    binning = _none_or_int(binning)

    if binning is None or binning == 1:
        return image, 1.0

    if binning <= 0:
        raise ValueError("segmentation_binning must be > 0.")

    ny, nx = image.shape[:2]

    shape = (max(1, int(round(ny / float(binning)))), max(1, int(round(nx / float(binning)))))

    work = np.asarray(image).astype(np.float32, copy=False)

    for axis, size in enumerate(shape):
        work = _area_average(work, size, axis)

    return work, shape[0] / float(ny)


def _area_average(array: np.ndarray, out_size: int, axis: int) -> np.ndarray:
    """Shrink one axis to ``out_size``, each output pixel the weighted mean of the input under it."""

    in_size = array.shape[axis]

    if out_size == in_size:
        return array

    scale = in_size / float(out_size)

    shape = list(array.shape)

    shape[axis] = out_size

    out = np.empty(shape, dtype=np.float32)

    for index in range(out_size):
        start, stop = index * scale, (index + 1) * scale

        lo, hi = int(np.floor(start)), int(np.ceil(stop))

        weights = np.array(
            [max(0.0, min(stop, source + 1) - max(start, source)) for source in range(lo, hi)],
            dtype=np.float32,
        )

        weight_shape = [1] * array.ndim

        weight_shape[axis] = len(weights)

        picked = [slice(None)] * array.ndim

        picked[axis] = slice(lo, hi)

        block = array[tuple(picked)]

        reduced = (block * weights.reshape(weight_shape)).sum(axis=axis) / scale

        target = [slice(None)] * array.ndim

        target[axis] = index

        out[tuple(target)] = reduced

    return out


def _resize_nearest(labels, shape):
    """A label image resized to ``shape``, each pixel taking its nearest label, none blended."""

    out_ny, out_nx = (int(value) for value in shape)

    labels = np.asarray(labels)

    in_ny, in_nx = labels.shape[:2]

    rows = np.minimum(np.arange(out_ny) * in_ny // out_ny, in_ny - 1)

    cols = np.minimum(np.arange(out_nx) * in_nx // out_nx, in_nx - 1)

    return labels[rows[:, None], cols]


def _cellpose_masks(image, scale: float, settings: dict, *, state: dict, gpu: bool, verbose: int):
    """The warm Cellpose model's masks; on a GPU failure, once more on the processor."""

    channel_axis = -1 if image.ndim == 3 else None

    tuning = {
        key: settings[key] for key in ("cellprob_threshold", "flow_threshold", "niter", "diameter")
    }

    # Cellpose is handed only what was set: niter as a whole number, the rest as decimals
    kwargs = {}

    for key, value in tuning.items():
        if value is not None:
            kwargs[key] = int(value) if key == "niter" else float(value)

    model, used_gpu, device = _cellpose_model(state, bool(gpu), verbose)

    try:
        masks, _, _ = model.eval(image, channel_axis=channel_axis, **kwargs)

    except Exception:
        if not gpu:
            raise

        if verbose >= 1:
            print("  [segment_cellpose] GPU Cellpose failed; retrying on CPU")

        _forget_model(state)

        model, used_gpu, device = _cellpose_model(state, False, verbose)

        masks, _, _ = model.eval(image, channel_axis=channel_axis, **kwargs)

    return masks, {
        "method": "robust",
        **_provenance(model),
        "requested_gpu": bool(gpu),
        "used_gpu": bool(used_gpu),
        "device": device,
        "cellprob_threshold": _none_or_float(tuning["cellprob_threshold"]),
        "flow_threshold": _none_or_float(tuning["flow_threshold"]),
        "niter": _none_or_int(tuning["niter"]),
        "diameter": _none_or_float(tuning["diameter"]),
    }


def _cellpose_model(state: dict, gpu: bool, verbose: int):
    """The warm model, on the best device it can get: ``(model, used_gpu, device)``.

    Loading takes seconds, so the model is kept in the worker's ``state``. A
    model that fell back to the processor is offered the graphics card again
    on the next call: the card may only have been full for a moment.
    """

    if "model" in state:
        on_gpu = bool(state.get("_cellpose_model_gpu", gpu))

        if gpu and not on_gpu:
            loaded = _load_model(state, gpu=True, accelerated_only=True, verbose=verbose)

            if loaded is not None:
                return loaded

        return state["model"], on_gpu, state.get("_cellpose_model_device", "cuda" if gpu else "cpu")

    loaded = _load_model(state, gpu=gpu, accelerated_only=False, verbose=verbose)

    if loaded is None:
        raise RuntimeError(
            "Could not initialize CellposeModel on any device: " + state.pop("_cellpose_errors", "")
        )

    return loaded


def _load_model(state: dict, *, gpu: bool, accelerated_only: bool, verbose: int):
    """Try the devices best first (CUDA, Apple MPS, the processor); keep the first that loads."""

    from cellpose import models

    errors = []

    for device, accelerated, kwargs in _devices(gpu):
        if accelerated_only and not accelerated:
            continue

        try:
            if verbose >= 2:
                print(f"  [segment_cellpose] cold start: loading CellposeModel({device})")

            state["model"] = models.CellposeModel(**kwargs)

            state["_cellpose_model_gpu"] = accelerated

            state["_cellpose_model_device"] = device

            return state["model"], accelerated, device

        except Exception as exc:
            errors.append(f"{device}: {exc}")

            if verbose >= 1 and device != "cpu":
                print(f"  [segment_cellpose] Cellpose {device} unavailable; trying next device")

    state["_cellpose_errors"] = "; ".join(errors)

    return None


def _devices(gpu: bool) -> list:
    """The devices to try, best first, each as (name, accelerated, CellposeModel arguments)."""

    if not gpu:
        return [("cpu", False, {"gpu": False})]

    import torch

    devices = []

    if torch.cuda.is_available():
        devices.append(("cuda", True, {"gpu": True, "device": torch.device("cuda")}))

    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        devices.append(("mps", True, {"gpu": True, "device": torch.device("mps")}))

    devices.append(("cpu", False, {"gpu": False}))

    return devices


def _forget_model(state: dict) -> None:
    """Drop the loaded model, so the next call loads afresh."""

    for key in ("model", "_cellpose_model_gpu", "_cellpose_model_device"):
        state.pop(key, None)


def _provenance(model) -> dict:
    """Which Cellpose made the masks: its version, its network and the torch it ran on.

    The masks change with all three. A version that cannot be read is
    recorded as unknown; it never fails a detection.
    """

    try:
        import cellpose

        version = str(
            getattr(cellpose, "version", None) or getattr(cellpose, "__version__", "unknown")
        )
    except Exception:
        version = "unknown"

    try:
        import torch

        torch_version = str(torch.__version__)
    except Exception:
        torch_version = None

    network = getattr(model, "pretrained_model", None)

    if network is not None and not isinstance(network, str):
        network = str(network[0]) if len(network) else None

    return {
        "cellpose_version": version,
        "cellpose_model": Path(network).name if network else "default",
        "torch_version": torch_version,
    }


def _write_checkpoint(detection: dict, raw_masks, given: dict, images: dict, params: dict) -> dict:
    """File the masks and a record of how they were made; return the paths, or ``{}``.

    An image inside an acquisition files in the ``analysis`` folder beside
    its ``data``, under the frame's short name. One outside an acquisition
    writes nothing, unless the submit or the pipeline names an ``output_dir``.
    """

    output_dir = _setting(given, params, "output_dir") or _analysis_dir(given["image_path"])

    if output_dir is None:
        return {}

    import tifffile

    folder = Path(output_dir) / "tiles" / _short_name(given["image_path"])

    folder.mkdir(parents=True, exist_ok=True)

    masks_path, raw_masks_path = folder / "masks.tif", folder / "raw_masks.tif"

    record_path = folder / "detection_checkpoint.json"

    tifffile.imwrite(masks_path, detection["masks"].astype("int32"))

    tifffile.imwrite(raw_masks_path, raw_masks.astype("int32"))

    record = {
        "image_path": str(given["image_path"]),
        "image_sha256": images["sha256"],
        # Geometry as the caller gave it; for an OME-Zarr image alone it comes
        # from the store, in build_object_table, and is not needed here.
        "tile_id": given.get("tile_id"),
        "tile_stage_xy_um": given.get("tile_stage_xy_um"),
        "tile_z_um": given.get("tile_z_um"),
        "z_selection": images["z_selection"],
        **(
            {"synthetic_pixels": given["synthetic_pixels"]} if given.get("synthetic_pixels") else {}
        ),
        "source_pixel_size_um": given.get("source_pixel_size_um"),
        "source_image_size_px": given.get("source_image_size_px", detection["image_size_px"]),
        "image_to_stage": given.get("image_to_stage"),
        "segmentation_params": detection["segmentation_params"],
        "segmentation_params_hash": detection["segmentation_params_hash"],
        "n_objects": detection["n_objects"],
        "n_raw_objects": detection["n_raw_objects"],
        "dropped_labels": detection["dropped_labels"],
        "area_filter": detection["area_filter"],
        "border_filter": detection["border_filter"],
        "detector_params": detection["detector_params"],
        "segmentation_resize": detection["segmentation_resize"],
        "image_size_px": detection["image_size_px"],
        "raw_masks_path": str(raw_masks_path),
        "raw_masks_sha256": hashlib.sha256(raw_masks_path.read_bytes()).hexdigest(),
        "masks_path": str(masks_path),
        "masks_sha256": hashlib.sha256(masks_path.read_bytes()).hexdigest(),
    }

    record_path.write_text(json.dumps(to_builtin(record), indent=2) + "\n", encoding="utf-8")

    return {
        "masks_tif": str(masks_path),
        "raw_masks_tif": str(raw_masks_path),
        "detection_checkpoint_json": str(record_path),
    }


def _short_name(image_path) -> str:
    """The frame's name without its channel and plane: ``..._T000000_C00_Z00000.ome.tiff`` -> ``..._T000000``.

    A name outside the drivers' convention keeps its bare stem.
    """

    name = Path(image_path).name

    frame = re.sub(r"_C\d{2}_Z\d{5}\.ome\.tiff?$", "", name, flags=re.IGNORECASE)

    return frame if frame != name else name.split(".")[0]


def _analysis_dir(image_path) -> Path | None:
    """The ``analysis`` folder beside the nearest ``data`` folder above the image, or None."""

    for folder in Path(image_path).parents:
        if folder.name == "data":
            return folder.parent / "analysis"

    return None
