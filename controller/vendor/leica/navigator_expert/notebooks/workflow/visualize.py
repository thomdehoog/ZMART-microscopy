"""visualize.py -- Inline image visualization for the notebook.

plot_overview_tiles: per-tile triptych (grayscale / segmentation / picked).
plot_target_pairs:   side-by-side overview crop vs. high-res target.

Path-based API: functions take analysis_dir and picks, not ctx.
Notebook cells provide thin wrappers that pull paths from ctx.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import numpy as np

from .overview import Picks
from .target import TargetRecord


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
    """Side-by-side: overview crop (left) vs. high-res target (right)."""
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

    MAX_PER_FIG = 20
    for batch_start in range(0, len(successful), MAX_PER_FIG):
        batch = successful[batch_start:batch_start + MAX_PER_FIG]
        n = len(batch)

        fig, axes = plt.subplots(n, 2, figsize=(8, 3 * n),
                                 squeeze=False)
        fig.patch.set_facecolor("white")

        for i, rec in enumerate(batch):
            pick = pick_map.get(tuple(rec.pick_id))
            tile_key = _normalize_tile_key(rec.pick_id[:3])

            if tile_key not in tile_cache:
                npz_path = tile_path_index.get(tile_key)
                tile_cache[tile_key] = (
                    _load_tile_npz(npz_path) if npz_path else None
                )
            tile_data = tile_cache[tile_key]

            # Left: cropped cell from overview tile
            if pick is not None and tile_data is not None:
                image_2d = tile_data[0]
                r0, c0, r1, c1 = pick.bbox_px
                r0, c0 = max(0, r0), max(0, c0)
                r1 = min(image_2d.shape[0], r1)
                c1 = min(image_2d.shape[1], c1)
                crop = image_2d[r0:r1, c0:c1]
                axes[i, 0].imshow(crop, cmap="gray")
            else:
                axes[i, 0].text(
                    0.5, 0.5, "N/A", ha="center", va="center",
                    transform=axes[i, 0].transAxes, fontsize=12,
                    color="#999999",
                )
            axes[i, 0].set_title(
                f"Overview crop (label {rec.pick_id[3]})", fontsize=9)
            axes[i, 0].axis("off")

            # Right: high-res target image
            try:
                target_img = tifffile.imread(str(rec.tif_path))
                target_img = _ensure_2d(target_img)
                axes[i, 1].imshow(target_img, cmap="gray")
            except Exception as exc:
                axes[i, 1].text(
                    0.5, 0.5, f"Load error:\n{exc}",
                    ha="center", va="center",
                    transform=axes[i, 1].transAxes, fontsize=8,
                    color="#cc3333",
                )
            axes[i, 1].set_title("High-res target", fontsize=9)
            axes[i, 1].axis("off")

        fig.suptitle("Target Pairs: Overview Crop vs. High-Res",
                     fontsize=13, fontweight="bold")
        plt.tight_layout()

        if feedback_dir is not None:
            suffix = f"_{batch_start // MAX_PER_FIG}" if len(successful) > MAX_PER_FIG else ""
            fig.savefig(feedback_dir / f"target_pairs{suffix}.png", dpi=150)

        plt.show()
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


def _segmentation_overlay(ax, image_2d: np.ndarray, masks: np.ndarray) -> None:
    """Grayscale background + random-color transparent overlay per cell."""
    ax.imshow(image_2d, cmap="gray")

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
) -> None:
    """Grayscale background + red overlay on picked cells only."""
    ax.imshow(image_2d, cmap="gray")

    if not picked_labels:
        return

    picked_set = set(picked_labels)
    red_overlay = np.zeros((*masks.shape, 4), dtype=np.float32)
    for label in picked_set:
        region = masks == label
        red_overlay[region] = [1.0, 0.0, 0.0, 0.4]

    ax.imshow(red_overlay)
