"""Shared object crop helpers for object-centered workflows."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from _contracts import to_builtin
from _object_ids import object_name, tile_name


def extract_object_crops(
    *,
    image,
    masks,
    tile_id,
    crop_size_px: int = 128,
    mask: bool = False,
    drop_incomplete: bool = True,
    align_orientation: bool = False,
    min_eccentricity_to_align: float = 0.4,
    output_dir: str | Path | None = None,
) -> dict:
    """Extract square per-object crops from an image and label mask.

    The crop is centered on the object centroid, has the same fixed size for
    every object, and is zero-padded at image borders. Set ``mask=True`` to
    zero non-object pixels while still returning the object mask separately.
    When ``drop_incomplete=True``, objects whose own mask touches the image
    boundary or does not fit inside the fixed crop are skipped. Context crops
    (``mask=False``) also require the full crop window to stay inside the
    image; masked crops may use zero padding outside the tile because the
    background is dark by design. Set ``align_orientation=True`` to rotate
    sufficiently elongated objects by sampling the fixed-size crop directly in
    the object's oriented frame, with the major axis following the top-left to
    bottom-right diagonal.
    """
    if crop_size_px <= 0:
        raise ValueError("crop_size_px must be > 0.")
    if min_eccentricity_to_align < 0 or min_eccentricity_to_align > 1:
        raise ValueError("min_eccentricity_to_align must be in [0, 1].")

    image = np.asarray(image)
    masks = np.asarray(masks)
    if image.shape[:2] != masks.shape:
        raise ValueError(
            f"image shape {image.shape[:2]} and masks shape {masks.shape} differ."
        )

    out_root = Path(output_dir) if output_dir else None
    t_name = tile_name(tile_id)
    tile_artifacts = {}
    if out_root:
        tile_dir = out_root / "tiles" / t_name
        tile_dir.mkdir(parents=True, exist_ok=True)
        tile_artifacts = _write_tile_artifacts(tile_dir, masks, t_name)

    rows = []
    skipped_incomplete = []
    labels = [int(label) for label in np.unique(masks) if int(label) != 0]
    for label in labels:
        rows_px, cols_px = np.nonzero(masks == label)
        if rows_px.size == 0:
            continue
        bbox = (
            int(rows_px.min()),
            int(cols_px.min()),
            int(rows_px.max()) + 1,
            int(cols_px.max()) + 1,
        )
        centroid = (float(rows_px.mean()), float(cols_px.mean()))
        crop = _crop_one(
            image=image,
            masks=masks,
            label=label,
            centroid=centroid,
            bbox=bbox,
            crop_size_px=int(crop_size_px),
            mask=bool(mask),
            align_orientation=bool(align_orientation),
            min_eccentricity_to_align=float(min_eccentricity_to_align),
        )
        if drop_incomplete and not crop["complete"]:
            skipped_incomplete.append(label)
            continue
        row = {
            "label": label,
            "object_id": object_name(tile_id, label),
            "tile_name": t_name,
            "bbox_min_row_px": int(bbox[0]),
            "bbox_min_col_px": int(bbox[1]),
            "bbox_max_row_px": int(bbox[2]),
            "bbox_max_col_px": int(bbox[3]),
            "crop_origin_row_px": int(crop["origin_row_px"]),
            "crop_origin_col_px": int(crop["origin_col_px"]),
            "crop_height_px": int(crop["image"].shape[0]),
            "crop_width_px": int(crop["image"].shape[1]),
            "crop_complete": bool(crop["complete"]),
            "crop_in_bounds": bool(crop["crop_in_bounds"]),
            "object_complete": bool(crop["object_complete"]),
            "object_fits_crop": bool(crop["object_fits_crop"]),
            "crop_aligned_orientation": bool(crop["aligned_orientation"]),
            "crop_rotation_deg": float(crop["rotation_deg"]),
            "crop_orientation_deg": crop["orientation_deg"],
            "crop_eccentricity": crop["eccentricity"],
            "crop_oriented_extent_px": crop["oriented_extent_px"],
            "crop_image": crop["image"],
            "crop_mask": crop["mask"],
            "crop_path": None,
            "mask_path": None,
        }
        if out_root:
            _write_object_artifacts(out_root, row)
        rows.append(row)

    return {
        "tile_name": t_name,
        "n_objects": len(rows),
        "objects": rows,
        "crop_policy": {
            "crop_size_px": int(crop_size_px),
            "mask": bool(mask),
            "drop_incomplete": bool(drop_incomplete),
            "align_orientation": bool(align_orientation),
            "min_eccentricity_to_align": float(min_eccentricity_to_align),
            "orientation_target_deg": 45.0,
        },
        "skipped_incomplete_labels": skipped_incomplete,
        "tile_artifacts": tile_artifacts,
    }


def _crop_one(
    *,
    image,
    masks,
    label: int,
    centroid,
    bbox,
    crop_size_px: int,
    mask: bool,
    align_orientation: bool,
    min_eccentricity_to_align: float,
) -> dict:
    size = int(crop_size_px)
    row_c, col_c = [float(value) for value in centroid]
    row0 = int(np.floor(row_c - size / 2.0))
    col0 = int(np.floor(col_c - size / 2.0))
    row1 = row0 + size
    col1 = col0 + size

    ny, nx = masks.shape
    crop_in_bounds = row0 >= 0 and col0 >= 0 and row1 <= ny and col1 <= nx
    bbox_min_row, bbox_min_col, bbox_max_row, bbox_max_col = [int(v) for v in bbox]
    object_complete = (
        bbox_min_row > 0
        and bbox_min_col > 0
        and bbox_max_row < ny
        and bbox_max_col < nx
    )
    object_fits_crop = (
        bbox_min_row >= row0
        and bbox_min_col >= col0
        and bbox_max_row <= row1
        and bbox_max_col <= col1
    )
    complete = object_complete and object_fits_crop and (mask or crop_in_bounds)

    aligned_orientation = False
    rotation_deg = 0.0
    orientation_deg = None
    eccentricity = None
    oriented_extent_px = None
    orientation = (
        _orientation_metrics(masks == label, centroid=(row_c, col_c))
        if align_orientation
        else None
    )
    if orientation is not None:
        orientation_deg = orientation["orientation_deg"]
        eccentricity = orientation["eccentricity"]
        oriented_extent_px = orientation["oriented_extent_px"]

    if (
        align_orientation
        and orientation is not None
        and orientation["eccentricity"] >= min_eccentricity_to_align
    ):
        crop_image, crop_mask = _sample_oriented_crop(
            image=image,
            object_mask=(masks == label),
            centroid=(row_c, col_c),
            crop_size_px=size,
            rotation_deg=orientation["rotation_deg"],
        )
        aligned_orientation = True
        rotation_deg = orientation["rotation_deg"]
    else:
        crop_image, crop_mask = _crop_window(
            image=image,
            masks=masks,
            label=label,
            row0=row0,
            col0=col0,
            size=size,
        )

    if mask:
        if crop_image.ndim == 2:
            crop_image = np.where(crop_mask, crop_image, 0)
        else:
            crop_image = np.where(crop_mask[..., None], crop_image, 0)

    return {
        "image": crop_image,
        "mask": crop_mask,
        "complete": complete,
        "crop_in_bounds": crop_in_bounds,
        "object_complete": object_complete,
        "object_fits_crop": object_fits_crop,
        "origin_row_px": row0,
        "origin_col_px": col0,
        "aligned_orientation": aligned_orientation,
        "rotation_deg": rotation_deg,
        "orientation_deg": orientation_deg,
        "eccentricity": eccentricity,
        "oriented_extent_px": oriented_extent_px,
    }


def _crop_window(*, image, masks, label: int, row0: int, col0: int, size: int):
    ny, nx = masks.shape
    row1 = row0 + size
    col1 = col0 + size
    src_r0 = max(0, row0)
    src_c0 = max(0, col0)
    src_r1 = min(ny, row1)
    src_c1 = min(nx, col1)
    dst_r0 = src_r0 - row0
    dst_c0 = src_c0 - col0
    dst_r1 = dst_r0 + (src_r1 - src_r0)
    dst_c1 = dst_c0 + (src_c1 - src_c0)

    crop_shape = (size, size) + tuple(image.shape[2:])
    crop_image = np.zeros(crop_shape, dtype=image.dtype)
    crop_mask = np.zeros((size, size), dtype=np.uint8)

    if src_r1 > src_r0 and src_c1 > src_c0:
        crop_image[dst_r0:dst_r1, dst_c0:dst_c1] = image[src_r0:src_r1, src_c0:src_c1]
        crop_mask[dst_r0:dst_r1, dst_c0:dst_c1] = (
            masks[src_r0:src_r1, src_c0:src_c1] == label
        )
    return crop_image, crop_mask


def _orientation_metrics(mask, *, centroid, target_deg: float = 45.0) -> dict | None:
    rows, cols = np.nonzero(mask)
    if rows.size < 10:
        return None
    coords = np.column_stack([cols, rows]).astype(np.float64)
    centered = coords - coords.mean(axis=0)
    if centered.shape[0] < 2:
        return None
    cov = np.cov(centered.T)
    eigvals, eigvecs = np.linalg.eigh(cov)
    major_idx = int(np.argmax(eigvals))
    major = float(eigvals[major_idx])
    minor = float(eigvals[1 - major_idx])
    if major <= 0.0:
        return None
    axis = eigvecs[:, major_idx]
    angle_deg = float(np.degrees(np.arctan2(axis[1], axis[0])) % 180.0)
    rotation_deg = _normalize_axis_rotation(angle_deg - float(target_deg))
    eccentricity = float(np.sqrt(max(0.0, 1.0 - max(minor, 0.0) / major)))
    oriented_extent_px = _oriented_extent_px(
        rows=rows,
        cols=cols,
        centroid=centroid,
        rotation_deg=rotation_deg,
    )
    return {
        "orientation_deg": angle_deg,
        "rotation_deg": rotation_deg,
        "eccentricity": eccentricity,
        "oriented_extent_px": oriented_extent_px,
    }


def _normalize_axis_rotation(angle_deg: float) -> float:
    return float((float(angle_deg) + 90.0) % 180.0 - 90.0)


def _oriented_extent_px(*, rows, cols, centroid, rotation_deg: float) -> int:
    row_c, col_c = [float(value) for value in centroid]
    dx = np.asarray(cols, dtype=np.float64) - col_c
    dy = np.asarray(rows, dtype=np.float64) - row_c
    theta = np.deg2rad(-float(rotation_deg))
    cos_t = float(np.cos(theta))
    sin_t = float(np.sin(theta))
    out_x = cos_t * dx - sin_t * dy
    out_y = sin_t * dx + cos_t * dy
    max_radius = max(float(np.max(np.abs(out_x))), float(np.max(np.abs(out_y))))
    return int(np.ceil(2.0 * max_radius + 1.0))


def _sample_oriented_crop(*, image, object_mask, centroid, crop_size_px: int, rotation_deg: float):
    size = int(crop_size_px)
    row_coords, col_coords = _oriented_source_coordinates(
        centroid=centroid,
        size=size,
        rotation_deg=rotation_deg,
    )
    crop_image = _sample_image(image, row_coords, col_coords, order=1)
    crop_mask = _sample_image(
        np.asarray(object_mask, dtype=np.float32),
        row_coords,
        col_coords,
        order=0,
    )
    return crop_image, (crop_mask > 0.5).astype(np.uint8)


def _oriented_source_coordinates(*, centroid, size: int, rotation_deg: float):
    row_c, col_c = [float(value) for value in centroid]
    grid_rows, grid_cols = np.indices((int(size), int(size)), dtype=np.float64)
    center = (float(size) - 1.0) / 2.0
    dx = grid_cols - center
    dy = grid_rows - center
    theta = np.deg2rad(float(rotation_deg))
    cos_t = float(np.cos(theta))
    sin_t = float(np.sin(theta))
    src_cols = col_c + cos_t * dx - sin_t * dy
    src_rows = row_c + sin_t * dx + cos_t * dy
    return src_rows, src_cols


def _sample_image(image, row_coords, col_coords, *, order: int):
    from scipy.ndimage import map_coordinates

    arr = np.asarray(image)
    if arr.ndim == 2:
        sampled = map_coordinates(
            arr,
            [row_coords, col_coords],
            order=order,
            mode="constant",
            cval=0,
            prefilter=False,
        )
    else:
        sampled = np.stack(
            [
                map_coordinates(
                    arr[..., channel],
                    [row_coords, col_coords],
                    order=order,
                    mode="constant",
                    cval=0,
                    prefilter=False,
                )
                for channel in range(arr.shape[-1])
            ],
            axis=-1,
        )
    return _cast_sampled_image(sampled, arr.dtype)


def _cast_sampled_image(image, dtype):
    if np.issubdtype(dtype, np.bool_):
        return (image > 0.5).astype(dtype)
    if np.issubdtype(dtype, np.integer):
        info = np.iinfo(dtype)
        return np.clip(np.rint(image), info.min, info.max).astype(dtype)
    return image.astype(dtype, copy=False)


def _write_tile_artifacts(tile_dir: Path, masks, t_name: str) -> dict:
    import tifffile

    masks_path = tile_dir / "masks.tif"
    metadata_path = tile_dir / "tile.json"
    tifffile.imwrite(masks_path, np.asarray(masks, dtype=np.int32))
    metadata = {"tile_name": t_name, "masks_path": str(masks_path)}
    with metadata_path.open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2, allow_nan=False)
        handle.write("\n")
    return {
        "masks_path": str(masks_path),
        "tile_json_path": str(metadata_path),
    }


def _write_object_artifacts(out_root: Path, row: dict) -> None:
    import tifffile

    obj_dir = out_root / "objects" / row["object_id"]
    obj_dir.mkdir(parents=True, exist_ok=True)
    crop_path = obj_dir / "crop.tif"
    mask_path = obj_dir / "mask.tif"
    metadata_path = obj_dir / "object.json"
    tifffile.imwrite(crop_path, row["crop_image"])
    tifffile.imwrite(mask_path, row["crop_mask"].astype(np.uint8))
    row["crop_path"] = str(crop_path)
    row["mask_path"] = str(mask_path)

    metadata = {
        key: value
        for key, value in row.items()
        if key not in {"crop_image", "crop_mask"}
    }
    metadata["object_json_path"] = str(metadata_path)
    with metadata_path.open("w", encoding="utf-8") as handle:
        json.dump(to_builtin(metadata), handle, indent=2, allow_nan=False)
        handle.write("\n")
