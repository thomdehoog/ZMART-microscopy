"""visualize.py -- Inline image visualization for the notebook.

Live display (during acquisition):
  display_tile:   per-tile triptych, called via on_tile callback.
  display_target: per-target 3-panel, called via on_target callback.

Batch re-render (Steps 4b/5b, after acquisition):
  plot_overview_tiles: all tiles with final deduped picks.
  plot_target_pairs:   all targets in 3-panel layout.

Path-based API: functions take analysis_dir and picks, not ctx.
Notebook cells provide thin wrappers that pull paths from ctx.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import numpy as np

from .overview import (
    MODE_EMPTY, MODE_NO_QUALIFYING, MODE_SPARSE, MODE_THRESHOLD,
    Picks, TileEvent,
)
from .target import TargetRecord


# ─── Live display (during acquisition) ───────────────────────────


def display_tile(
    event: TileEvent,
    *,
    scan_field: dict | None = None,
    boundary_limits: dict | None = None,
    feedback_dir: Path | None = None,
) -> None:
    """Render one tile 5-panel figure inline during acquisition.

    Row 1: scan field map | scatter plot
    Row 2: grayscale | segmentation | picked
    """
    import matplotlib.pyplot as plt
    from IPython.display import display

    rid, row, col = event.tile_id
    n_cells = int(event.masks.max())
    is_mock = event.analysis_image_source != "acquired"
    prefix = "(mock) " if is_mock else ""
    n_picked = len(event.picked_labels)

    if event.mode == MODE_SPARSE:
        pick_label = f"Picked ({n_picked}, sparse)"
    elif event.mode == MODE_NO_QUALIFYING:
        pick_label = f"Picked ({n_picked}, no qualifying)"
    elif event.mode == MODE_EMPTY:
        pick_label = "No cells"
    else:
        pick_label = f"Picked ({n_picked}, pre-dedup)"

    fig = plt.figure(figsize=(14, 10))
    gs = fig.add_gridspec(2, 6, height_ratios=[1, 1])
    ax_scan = fig.add_subplot(gs[0, :3])
    ax_scatter = fig.add_subplot(gs[0, 3:])
    ax1 = fig.add_subplot(gs[1, :2])
    ax2 = fig.add_subplot(gs[1, 2:4])
    ax3 = fig.add_subplot(gs[1, 4:])

    try:
        fig.patch.set_facecolor("white")

        _scan_field_panel(ax_scan, scan_field, event.tile_id,
                          boundary_limits=boundary_limits)

        _scatter_panel(
            ax_scatter,
            all_labels=np.array(event.all_cells_labels),
            all_area=np.array(event.all_cells_area),
            all_intensity=np.array(event.all_cells_intensity),
            picked_labels=np.array(event.picked_labels),
            area_threshold=event.area_threshold,
            intensity_threshold=event.intensity_threshold,
            mode=event.mode,
        )

        vmin, vmax = np.percentile(event.image_2d, [1, 99])

        ax1.imshow(event.image_2d, cmap="gray", vmin=vmin, vmax=vmax)
        ax1.set_title("Tile image", fontsize=11)
        ax1.axis("off")

        _segmentation_overlay(ax2, event.image_2d, event.masks,
                              vmin=vmin, vmax=vmax)
        ax2.set_title(f"Segmentation ({n_cells} cells)", fontsize=11)
        ax2.axis("off")

        _picked_overlay(ax3, event.image_2d, event.masks,
                        list(event.picked_labels),
                        vmin=vmin, vmax=vmax)
        ax3.set_title(pick_label, fontsize=11)
        ax3.axis("off")

        fig.suptitle(f"{prefix}Tile R{rid} r{row}c{col}",
                     fontsize=13, fontweight="bold")
        plt.tight_layout()

        if feedback_dir is not None:
            feedback_dir.mkdir(parents=True, exist_ok=True)
            fig.savefig(
                feedback_dir / f"live_tile_R{rid}_r{row}c{col}.png",
                dpi=150,
            )

        display(fig)
    finally:
        plt.close(fig)


def display_target(
    pick,
    record: TargetRecord,
    analysis_dir: Path,
    *,
    scan_field: dict | None = None,
    boundary_limits: dict | None = None,
    target_brightness_match: bool = True,
    feedback_dir: Path | None = None,
    tile_cache: dict | None = None,
) -> None:
    """Render one target 5-panel figure inline during acquisition.

    Row 1: scan field map | scatter plot
    Row 2: tile+mask+box | centroid crop | high-res target

    tile_cache stores {tile_key: (tile_data, scatter_data)} and
    {"_index": path_index} for O(1) lookups.
    """
    import matplotlib.patches as patches
    import matplotlib.pyplot as plt
    import tifffile
    from IPython.display import display

    tile_key = _normalize_tile_key(record.pick_id[:3])

    if tile_cache is None:
        tile_cache = {}

    # Build path index once
    if "_index" not in tile_cache:
        tile_cache["_index"] = _build_tile_path_index(analysis_dir)
    path_index = tile_cache["_index"]

    # Load tile + scatter data (cached per tile)
    if tile_key not in tile_cache:
        npz_path = path_index.get(tile_key)
        td = _load_tile_npz(npz_path) if npz_path else None
        sd = _load_scatter_data(npz_path) if npz_path else None
        tile_cache[tile_key] = (td, sd)
    tile_data, scatter_data = tile_cache[tile_key]

    target_img = None
    if record.tif_path is not None:
        try:
            target_img = tifffile.imread(str(record.tif_path))
            target_img = _ensure_2d(target_img)
        except Exception:
            pass

    # Use 5-panel if scatter data available, else 3-panel fallback
    has_scatter = scatter_data is not None
    if has_scatter:
        fig = plt.figure(figsize=(14, 10))
        gs = fig.add_gridspec(2, 6, height_ratios=[1, 1])
        ax_scan = fig.add_subplot(gs[0, :3])
        ax_scatter = fig.add_subplot(gs[0, 3:])
        ax1 = fig.add_subplot(gs[1, :2])
        ax2 = fig.add_subplot(gs[1, 2:4])
        ax3 = fig.add_subplot(gs[1, 4:])
    else:
        fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(15, 5))

    try:
        fig.patch.set_facecolor("white")

        # Row 1 (if scatter available)
        if has_scatter:
            _scan_field_panel(ax_scan, scan_field, record.pick_id[:3],
                              boundary_limits=boundary_limits)
            _scatter_panel(
                ax_scatter,
                all_labels=scatter_data["labels"],
                all_area=scatter_data["area"],
                all_intensity=scatter_data["intensity"],
                picked_labels=scatter_data["picked"],
                area_threshold=scatter_data["area_threshold"],
                intensity_threshold=scatter_data["intensity_threshold"],
                mode=scatter_data["mode"],
                highlight_label=record.pick_id[3],
            )

        # Compute overview brightness range for consistent scaling
        ov_vmin, ov_vmax = (None, None)
        if tile_data is not None:
            ov_vmin, ov_vmax = np.percentile(tile_data[0], [1, 99])

        # Row 2, Panel 1: tile + mask + FOV rectangle
        if tile_data is not None and pick is not None:
            image_2d, masks = tile_data[0], tile_data[1]
            ax1.imshow(image_2d, cmap="gray", vmin=ov_vmin, vmax=ov_vmax)

            label = pick.pick_id[3]
            mask_overlay = np.zeros((*masks.shape, 4), dtype=np.float32)
            mask_overlay[masks == label] = [1.0, 0.0, 0.0, 0.4]
            ax1.imshow(mask_overlay)

            cx, cy = pick.centroid_col_row_px
            src_px_w, src_px_h = pick.source_pixel_size_um
            if (target_img is not None
                    and record.target_pixel_size_um is not None
                    and src_px_w > 0 and src_px_h > 0):
                th, tw = target_img.shape[:2]
                crop_w = int(round(tw * record.target_pixel_size_um / src_px_w))
                crop_h = int(round(th * record.target_pixel_size_um / src_px_h))
            else:
                r0b, c0b, r1b, c1b = pick.bbox_px
                crop_h, crop_w = r1b - r0b, c1b - c0b

            h, w = image_2d.shape[:2]
            crop_h = min(crop_h, h)
            crop_w = min(crop_w, w)
            r0 = int(round(cy - crop_h / 2))
            c0 = int(round(cx - crop_w / 2))
            r0 = max(0, min(r0, h - crop_h))
            c0 = max(0, min(c0, w - crop_w))

            ax1.add_patch(patches.Rectangle(
                (c0, r0), crop_w, crop_h,
                edgecolor="red", facecolor="none",
                linewidth=1.5, zorder=10,
            ))
        elif tile_data is not None:
            ax1.imshow(tile_data[0], cmap="gray", vmin=ov_vmin, vmax=ov_vmax)
        else:
            ax1.text(0.5, 0.5, "N/A", ha="center", va="center",
                     transform=ax1.transAxes, fontsize=12, color="#999999")
        ax1.set_title("Overview tile", fontsize=11)
        ax1.axis("off")

        # Row 2, Panel 2: centroid crop (overview brightness)
        if pick is not None and tile_data is not None:
            image_2d = tile_data[0]
            crop = _centroid_crop_at_target_fov(
                image_2d, pick, record, target_img,
            )
            ax2.imshow(crop, cmap="gray", vmin=ov_vmin, vmax=ov_vmax)
        else:
            ax2.text(0.5, 0.5, "N/A", ha="center", va="center",
                     transform=ax2.transAxes, fontsize=12, color="#999999")
        ax2.set_title(f"Overview crop (label {record.pick_id[3]})",
                      fontsize=11)
        ax2.axis("off")

        # Row 2, Panel 3: high-res target
        if target_img is not None:
            if target_brightness_match and ov_vmin is not None:
                ax3.imshow(target_img, cmap="gray",
                           vmin=ov_vmin, vmax=ov_vmax)
            else:
                t_vmin, t_vmax = np.percentile(target_img, [1, 99])
                ax3.imshow(target_img, cmap="gray",
                           vmin=t_vmin, vmax=t_vmax)
        else:
            ax3.text(0.5, 0.5, "N/A", ha="center", va="center",
                     transform=ax3.transAxes, fontsize=12, color="#999999")
        ax3.set_title("High-res target", fontsize=11)
        ax3.axis("off")

        rid, row, col, label = record.pick_id
        fig.suptitle(f"Target R{rid} r{row}c{col} label {label}",
                     fontsize=13, fontweight="bold")
        plt.tight_layout()

        if feedback_dir is not None:
            feedback_dir.mkdir(parents=True, exist_ok=True)
            fig.savefig(
                feedback_dir / f"live_target_R{rid}_r{row}c{col}_l{label}.png",
                dpi=150,
            )

        display(fig)
    finally:
        plt.close(fig)


# ─── Batch re-render (Steps 4b/5b) ──────────────────────────────


def plot_overview_tiles(
    analysis_dir: Path,
    picks: Picks,
    *,
    feedback_dir: Path | None = None,
) -> None:
    """Render per-tile triptych: grayscale | segmentation overlay | picked mask.

    Reads npz files from analysis_dir.  Picked labels are derived from
    picks.items via pick_id[3] (the cellpose label).
    """
    import matplotlib.pyplot as plt

    npz_files = sorted(analysis_dir.glob("*.npz")) if analysis_dir.exists() else []
    if not npz_files:
        print("[visualize] No tile analysis files found.")
        return

    picked_by_tile: dict[tuple, list[int]] = defaultdict(list)
    for pick in picks.items:
        tile_key = _normalize_tile_key(pick.pick_id[:3])
        picked_by_tile[tile_key].append(pick.pick_id[3])

    n_acquire_fail = len(picks.tile_acquire_failures)
    n_engine_fail = len(picks.engine_failures)
    parts = [f"Showing {len(npz_files)} tile(s)"]
    if n_engine_fail:
        parts.append(f"{n_engine_fail} engine failure(s)")
    if n_acquire_fail:
        parts.append(f"{n_acquire_fail} acquire failure(s)")
    print(f"[visualize] {'. '.join(parts)}.")

    if feedback_dir is not None:
        feedback_dir.mkdir(parents=True, exist_ok=True)

    for npz_path in npz_files:
        loaded = _load_tile_npz(npz_path)
        if loaded is None:
            continue

        image_2d, masks, tile_id, source = loaded
        tile_key = _normalize_tile_key(tile_id)
        labels = picked_by_tile.get(tile_key, [])
        n_cells = int(masks.max())
        is_mock = source != "acquired"

        fig, axes = plt.subplots(1, 3, figsize=(15, 5))
        fig.patch.set_facecolor("white")

        axes[0].imshow(image_2d, cmap="gray")
        axes[0].set_title("Tile image", fontsize=11)
        axes[0].axis("off")

        _segmentation_overlay(axes[1], image_2d, masks)
        axes[1].set_title(f"Segmentation ({n_cells} cells)", fontsize=11)
        axes[1].axis("off")

        _picked_overlay(axes[2], image_2d, masks, labels)
        axes[2].set_title(f"Picked ({len(labels)})", fontsize=11)
        axes[2].axis("off")

        rid, row, col = tile_id
        prefix = "(mock) " if is_mock else ""
        fig.suptitle(f"{prefix}Tile R{rid} r{row}c{col}",
                     fontsize=13, fontweight="bold")
        plt.tight_layout()

        if feedback_dir is not None:
            fig.savefig(
                feedback_dir / npz_path.with_suffix(".png").name,
                dpi=150,
            )

        plt.show()
        plt.close(fig)


def plot_target_pairs(
    analysis_dir: Path,
    picks: Picks,
    records: list[TargetRecord],
    *,
    feedback_dir: Path | None = None,
) -> None:
    """Batch re-render: 3-panel per target (tile + crop + high-res)."""
    import matplotlib.pyplot as plt
    import tifffile

    successful = [r for r in records if r.success and r.tif_path is not None]
    if not successful:
        print("[visualize] No successful targets to display.")
        return

    pick_map = {tuple(p.pick_id): p for p in picks.items}
    tile_path_index = _build_tile_path_index(analysis_dir)
    tile_cache: dict[tuple, tuple | None] = {}

    if feedback_dir is not None:
        feedback_dir.mkdir(parents=True, exist_ok=True)

    for j, rec in enumerate(successful):
        pick = pick_map.get(tuple(rec.pick_id))
        tile_key = _normalize_tile_key(rec.pick_id[:3])

        if tile_key not in tile_cache:
            npz_path = tile_path_index.get(tile_key)
            tile_cache[tile_key] = (
                _load_tile_npz(npz_path) if npz_path else None
            )
        tile_data = tile_cache[tile_key]

        target_img = None
        try:
            target_img = tifffile.imread(str(rec.tif_path))
            target_img = _ensure_2d(target_img)
        except Exception:
            pass

        fig, axes = plt.subplots(1, 3, figsize=(15, 5))
        try:
            fig.patch.set_facecolor("white")

            # Left: full overview tile with marker
            if tile_data is not None:
                image_2d = tile_data[0]
                axes[0].imshow(image_2d, cmap="gray")
                if pick is not None:
                    cx, cy = pick.centroid_col_row_px
                    axes[0].scatter(cx, cy, s=60, marker="o",
                                    facecolor="red", edgecolor="white",
                                    linewidth=0.8, zorder=10)
            else:
                axes[0].text(0.5, 0.5, "N/A", ha="center", va="center",
                             transform=axes[0].transAxes, fontsize=12,
                             color="#999999")
            axes[0].set_title("Overview tile", fontsize=9)
            axes[0].axis("off")

            # Middle: centroid crop at target FOV
            if pick is not None and tile_data is not None:
                image_2d = tile_data[0]
                crop = _centroid_crop_at_target_fov(
                    image_2d, pick, rec, target_img,
                )
                axes[1].imshow(crop, cmap="gray")
            else:
                axes[1].text(0.5, 0.5, "N/A", ha="center", va="center",
                             transform=axes[1].transAxes, fontsize=12,
                             color="#999999")
            axes[1].set_title(
                f"Overview crop (label {rec.pick_id[3]})", fontsize=9)
            axes[1].axis("off")

            # Right: acquired high-res target
            if target_img is not None:
                axes[2].imshow(target_img, cmap="gray")
            else:
                axes[2].text(0.5, 0.5, "N/A", ha="center", va="center",
                             transform=axes[2].transAxes, fontsize=12,
                             color="#999999")
            axes[2].set_title("High-res target", fontsize=9)
            axes[2].axis("off")

            rid, row, col, label = rec.pick_id
            fig.suptitle(f"Target R{rid} r{row}c{col} label {label}",
                         fontsize=13, fontweight="bold")
            plt.tight_layout()

            if feedback_dir is not None:
                fig.savefig(
                    feedback_dir / f"target_R{rid}_r{row}c{col}_l{label}.png",
                    dpi=150,
                )

            plt.show()
        finally:
            plt.close(fig)


# ─── Internal helpers ────────────────────────────────────────────


def _load_tile_npz(path: Path):
    """Load a tile analysis npz. Returns (image_2d, masks, tile_id, source) or None."""
    try:
        data = np.load(path, allow_pickle=True)
        image_2d = data["image_2d"]
        masks = data["masks"]
        tile_id = tuple(str(x) for x in data["tile_id"])
        source = str(data["analysis_image_source"])
        return image_2d, masks, tile_id, source
    except Exception as exc:
        print(f"[visualize] WARNING: skipping {path.name}: {exc}")
        return None


def _load_scatter_data(path: Path) -> dict | None:
    """Load cell metrics from npz. Returns None if keys absent (old format)."""
    try:
        data = np.load(path, allow_pickle=True)
        if "cell_labels" not in data.files:
            return None
        return {
            "labels": data["cell_labels"],
            "area": data["cell_area_px"],
            "intensity": data["cell_mean_intensity"],
            "picked": data["picked_labels"],
            "area_threshold": float(data["area_threshold"]),
            "intensity_threshold": float(data["intensity_threshold"]),
            "mode": str(data["selection_mode"]),
        }
    except Exception:
        return None


def _normalize_tile_key(key: tuple) -> tuple[str, ...]:
    """Normalize a tile key to all-strings for consistent dict lookup."""
    return tuple(str(x) for x in key)


def _build_tile_path_index(
    analysis_dir: Path,
) -> dict[tuple, Path]:
    """Map tile_id → npz path without loading image data. O(N) metadata reads."""
    index: dict[tuple, Path] = {}
    if not analysis_dir.exists():
        return index
    for npz_path in sorted(analysis_dir.glob("*.npz")):
        try:
            with np.load(npz_path, allow_pickle=True) as data:
                tile_id = _normalize_tile_key(data["tile_id"])
                index[tile_id] = npz_path
        except Exception:
            continue
    return index


def _ensure_2d(image: np.ndarray) -> np.ndarray:
    """Collapse a multi-dimensional image to 2D for display."""
    if image.ndim == 2:
        return image
    if image.ndim == 3:
        if image.shape[-1] <= 4:
            return image[..., 0]
        return image[0]
    # 4D+: strip leading dims until 3D, then apply the 3D heuristic
    while image.ndim > 3:
        image = image[0]
    return _ensure_2d(image)


def _centroid_crop_at_target_fov(
    image_2d: np.ndarray,
    pick,
    rec,
    target_img: np.ndarray | None,
) -> np.ndarray:
    """Crop overview tile at the target job's physical field of view.

    Centered on pick centroid. Crop size derived from the target image
    dimensions and the pixel-size ratio between target and source.
    Falls back to pick.bbox_px if target geometry is unavailable.
    """
    cx, cy = pick.centroid_col_row_px  # (col, row) in source pixels
    src_px_w, src_px_h = pick.source_pixel_size_um

    if (target_img is not None
            and rec.target_pixel_size_um is not None
            and src_px_w > 0 and src_px_h > 0):
        th, tw = target_img.shape[:2]
        fov_w_um = tw * rec.target_pixel_size_um
        fov_h_um = th * rec.target_pixel_size_um
        crop_w = int(round(fov_w_um / src_px_w))
        crop_h = int(round(fov_h_um / src_px_h))
    else:
        r0, c0, r1, c1 = pick.bbox_px
        crop_h, crop_w = r1 - r0, c1 - c0

    h, w = image_2d.shape[:2]
    r0 = int(round(cy - crop_h / 2))
    c0 = int(round(cx - crop_w / 2))
    # Clamp to image bounds
    r0 = max(0, min(r0, h - crop_h))
    c0 = max(0, min(c0, w - crop_w))
    r1 = min(h, r0 + crop_h)
    c1 = min(w, c0 + crop_w)
    return image_2d[r0:r1, c0:c1]


def _scan_field_panel(
    ax,
    scan_field: dict | None,
    current_tile_id: tuple,
    boundary_limits: dict | None = None,
) -> None:
    """Scan field with one tile highlighted in red."""
    import matplotlib.patches as patches

    if scan_field is None:
        ax.text(0.5, 0.5, "No scan field", ha="center", va="center",
                transform=ax.transAxes, fontsize=12, color="#999999")
        ax.axis("off")
        return

    tile_positions = scan_field.get("tile_positions", {})
    current_key = _normalize_tile_key(current_tile_id)
    all_x, all_y = [], []

    for rid, region in tile_positions.items():
        ts = region.get("tile_size_um")
        if ts is None:
            continue
        half = ts / 2
        for pos in region["positions"]:
            cx, cy = pos["x_um"], pos["y_um"]
            tile_key = _normalize_tile_key(
                (str(rid), pos["row"], pos["col"]))
            is_current = tile_key == current_key
            ax.add_patch(patches.Rectangle(
                (cx - half, cy - half), ts, ts,
                edgecolor="red" if is_current else "#cccccc",
                facecolor=(1, 0, 0, 0.3) if is_current else "#f0f0f0",
                linewidth=0.6, zorder=10 if is_current else 1,
            ))
            all_x.extend([cx - half, cx + half])
            all_y.extend([cy - half, cy + half])

    if boundary_limits:
        ax.add_patch(patches.Rectangle(
            (boundary_limits["x_min"], boundary_limits["y_min"]),
            boundary_limits["x_max"] - boundary_limits["x_min"],
            boundary_limits["y_max"] - boundary_limits["y_min"],
            edgecolor="#aaaaaa", facecolor="none",
            linestyle=(0, (5, 4)), linewidth=1.0, zorder=2,
        ))

    if all_x:
        span = max(max(all_x) - min(all_x), max(all_y) - min(all_y))
        pad = span * 0.05
        ax.set_xlim(min(all_x) - pad, max(all_x) + pad)
        ax.set_ylim(min(all_y) - pad, max(all_y) + pad)

    ax.set_aspect("equal")
    ax.invert_yaxis()
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title("Scan field", fontsize=11)


def _scatter_panel(
    ax,
    *,
    all_labels: np.ndarray,
    all_area: np.ndarray,
    all_intensity: np.ndarray,
    picked_labels: np.ndarray,
    area_threshold: float,
    intensity_threshold: float,
    mode: str,
    highlight_label: int | None = None,
) -> None:
    """Scatter: intensity (x) vs area (y) with threshold lines."""
    if len(all_labels) == 0:
        ax.text(0.5, 0.5, "No cells detected", ha="center", va="center",
                transform=ax.transAxes, fontsize=12, color="#999999")
        ax.axis("off")
        return

    picked_set = set(int(x) for x in picked_labels)

    ax.scatter(all_intensity, all_area, c="#cccccc", s=15, zorder=5,
               label="All cells")

    picked_mask = np.isin(all_labels, list(picked_set))
    if picked_mask.any():
        ax.scatter(all_intensity[picked_mask], all_area[picked_mask],
                   c="red", s=30, zorder=10, label="Picked")

    if highlight_label is not None:
        hl_mask = all_labels == highlight_label
        if hl_mask.any():
            ax.scatter(all_intensity[hl_mask], all_area[hl_mask],
                       c="red", s=80, edgecolor="white", linewidth=1.2,
                       zorder=20, label="Current")

    if mode == MODE_THRESHOLD:
        ax.axhline(area_threshold, color="red", linestyle="--",
                   linewidth=0.8, alpha=0.6)
        ax.axvline(intensity_threshold, color="red", linestyle="--",
                   linewidth=0.8, alpha=0.6)
    elif mode == MODE_NO_QUALIFYING:
        ax.axhline(area_threshold, color="red", linestyle="--",
                   linewidth=0.8, alpha=0.6)
        ax.axvline(intensity_threshold, color="red", linestyle="--",
                   linewidth=0.8, alpha=0.6)
        ax.annotate("0 qualified — sampled from all",
                    xy=(0.5, 0.02), xycoords="axes fraction",
                    ha="center", fontsize=8, color="#888888")
    elif mode == MODE_SPARSE:
        ax.annotate(f"< {len(all_labels)} cells: thresholds skipped",
                    xy=(0.5, 0.02), xycoords="axes fraction",
                    ha="center", fontsize=8, color="#888888")

    ax.set_xlabel("Mean intensity (a.u.)", fontsize=10)
    ax.set_ylabel("Area (px)", fontsize=10)
    ax.tick_params(labelsize=9)
    ax.set_title("Cell selection", fontsize=11)


def _segmentation_overlay(ax, image_2d: np.ndarray, masks: np.ndarray,
                          vmin=None, vmax=None) -> None:
    """Grayscale background + random-color transparent overlay per cell."""
    ax.imshow(image_2d, cmap="gray", vmin=vmin, vmax=vmax)

    n_labels = int(masks.max())
    if n_labels == 0:
        return

    rng = np.random.RandomState(42)
    colors = rng.rand(n_labels + 1, 4).astype(np.float32)
    colors[:, 3] = 0.4
    colors[0] = [0, 0, 0, 0]

    colored = colors[masks]
    ax.imshow(colored)


def _picked_overlay(
    ax,
    image_2d: np.ndarray,
    masks: np.ndarray,
    picked_labels: list[int],
    vmin=None, vmax=None,
) -> None:
    """Grayscale background + red overlay on picked cells only."""
    ax.imshow(image_2d, cmap="gray", vmin=vmin, vmax=vmax)

    if not picked_labels:
        return

    picked_set = set(picked_labels)
    red_overlay = np.zeros((*masks.shape, 4), dtype=np.float32)
    for label in picked_set:
        region = masks == label
        red_overlay[region] = [1.0, 0.0, 0.0, 0.4]

    ax.imshow(red_overlay)
