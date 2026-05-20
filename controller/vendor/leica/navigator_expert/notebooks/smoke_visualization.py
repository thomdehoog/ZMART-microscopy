"""End-to-end visualization smoke test using skimage human_mitosis + cellpose.

Generates synthetic run data (npz + tif) matching the real pipeline
schema, then calls plot_overview_tiles and plot_target_pairs.

Requires: cellpose, scikit-image (with pooch), tifffile, matplotlib.
Run with an env that has these (e.g. dino3_test):

    cd notebooks/
    python smoke_visualization.py
"""
from __future__ import annotations

import sys
import shutil
from pathlib import Path

import numpy as np

# ── Path setup (same as notebook boot cell) ──────────────────────
_HERE = Path(__file__).resolve().parent
for _c in [_HERE, _HERE / "notebooks", _HERE.parent / "notebooks"]:
    if (_c / "workflow" / "__init__.py").exists():
        sys.path.insert(0, str(_c))
        break

_LEICA = _HERE.parents[1]
_VENDOR = _LEICA.parent
for p in [str(_LEICA), str(_VENDOR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from workflow.overview import Pick, Picks, _save_tile_analysis
from workflow.target import TargetRecord
from workflow.visualize import plot_overview_tiles, plot_target_pairs


def main():
    out_dir = Path(__file__).resolve().parent / "_test_viz_output"
    if out_dir.exists():
        shutil.rmtree(out_dir)

    analysis_dir = out_dir / "overview-scan" / "analysis"
    logs_overview = out_dir / "overview-scan" / "logs"
    logs_target = out_dir / "target-acquisition" / "logs"
    target_data_dir = out_dir / "target-acquisition" / "data"

    # ── 1. Load image + segment with cellpose ────────────────────
    print("Loading skimage human_mitosis...")
    from skimage.data import human_mitosis
    image = human_mitosis().astype(np.float64)

    print("Running cellpose segmentation...")
    from cellpose.models import CellposeModel
    model = CellposeModel(model_type="cyto3", gpu=False)
    masks, _, _ = model.eval(image, diameter=30, channels=[0, 0])
    masks = masks.astype(np.int32)
    n_cells = int(masks.max())
    print(f"  Found {n_cells} cells")

    # ── 2. Simulate 4 tiles (quarters of the image) ─────────────
    h, w = image.shape
    hh, hw = h // 2, w // 2
    tiles = [
        {"tile_id": ("0", 0, 0), "slice": (slice(0, hh), slice(0, hw))},
        {"tile_id": ("0", 0, 1), "slice": (slice(0, hh), slice(hw, w))},
        {"tile_id": ("0", 1, 0), "slice": (slice(hh, h), slice(0, hw))},
        {"tile_id": ("0", 1, 1), "slice": (slice(hh, h), slice(hw, w))},
    ]

    hash6 = "tstv1z"
    buffer = []
    for i, tile in enumerate(tiles):
        rs, cs = tile["slice"]
        tile_img = image[rs, cs]
        tile_masks = masks[rs, cs]
        # Post-Plan-2 §6 / D1: simulate=True is the single dry-run
        # signal. Mirrors what run_overview's submit dict carries on
        # a hijack-mode run; _save_tile_analysis persists the same
        # `simulated` key the production hijack path writes, so the
        # smoke render exercises the post-cut figure-title path.
        buffer.append({
            "input": {
                "tile_id": tile["tile_id"],
                "naming_p": i,
                "image_path": f"/fake/tile_{i}.ome.tiff",
                "simulated": True,
                "mock_image_source": "skimage_human_mitosis",
            },
            "segment_tile": {
                "image_2d": tile_img,
                "masks": tile_masks,
                "n_cells": int(tile_masks.max()),
            },
            "pick_targets": {"picks": []},
        })

    # ── 3. Save tile analysis (same as overview.py does) ─────────
    print("Saving tile analysis artifacts...")
    _save_tile_analysis(
        analysis_dir, buffer,
        hash6=hash6, acquisition_type="overview-scan",
    )

    # ── 4. Build picks (top-3 largest cells per tile) ────────────
    from skimage.measure import regionprops
    all_picks = []
    for i, tile in enumerate(tiles):
        rs, cs = tile["slice"]
        tile_masks = masks[rs, cs]
        props = regionprops(tile_masks)
        if not props:
            continue
        top3 = sorted(props, key=lambda p: p.area, reverse=True)[:3]
        rid, row, col = tile["tile_id"]
        for prop in top3:
            all_picks.append(Pick(
                pick_id=(str(rid), int(row), int(col), int(prop.label)),
                tile_stage_xy_um=(1000.0 + col * 500.0, 2000.0 + row * 500.0),
                tile_zwide_um=100.0,
                source_pixel_size_um=(0.5, 0.5),
                source_image_size_px=(hh, hw),
                centroid_col_row_px=(prop.centroid[1], prop.centroid[0]),
                bbox_px=prop.bbox,
                bbox_um=(prop.bbox[3] - prop.bbox[1], prop.bbox[2] - prop.bbox[0]),
                area_px=prop.area,
                eccentricity=prop.eccentricity,
                mean_intensity=0.0,
                cell_source_stage_xy_um=(
                    1000.0 + col * 500.0 + prop.centroid[1] * 0.5,
                    2000.0 + row * 500.0 + prop.centroid[0] * 0.5,
                ),
            ))

    picks = Picks(items=all_picks, n_picks_raw=len(all_picks))
    print(f"  {len(all_picks)} picks across {len(tiles)} tiles")

    # ── 5. Simulate target TIFs (crop from image at 2x zoom) ────
    import tifffile

    target_data_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for j, pick in enumerate(all_picks[:6]):
        r0, c0, r1, c1 = pick.bbox_px
        rs = tiles[[t["tile_id"] for t in tiles].index(
            (str(pick.pick_id[0]), int(pick.pick_id[1]), int(pick.pick_id[2]))
        )]["slice"]
        crop = image[rs[0], rs[1]][r0:r1, c0:c1]
        # Simulate higher-res target by upsampling 2x
        target_img = np.repeat(np.repeat(crop, 2, axis=0), 2, axis=1)
        tif_path = target_data_dir / f"target_{j:03d}.ome.tiff"
        tifffile.imwrite(str(tif_path), target_img.astype(np.uint16))

        records.append(TargetRecord(
            pick_id=pick.pick_id,
            cell_source_stage_xy_um=pick.cell_source_stage_xy_um,
            source_zwide_um=100.0,
            target_stage_xy_um=(pick.cell_source_stage_xy_um[0] + 10,
                                pick.cell_source_stage_xy_um[1] + 10),
            target_zwide_um=100.0,
            target_zoom=None,
            target_pixel_size_um=0.25,
            tif_path=tif_path,
            success=True,
            error=None,
        ))

    print(f"  {len(records)} target TIFs written")

    # ── 6. Run visualization ─────────────────────────────────────
    print("\n=== Step 4b: Overview triptychs ===")
    plot_overview_tiles(
        analysis_dir, picks,
        logs_dir=logs_overview,
    )

    print("\n=== Step 5b: Target pairs ===")
    plot_target_pairs(
        analysis_dir, picks, records,
        logs_dir=logs_target,
    )

    # ── 7. Report ────────────────────────────────────────────────
    print(f"\nOutput saved to: {out_dir}")
    for png in sorted(out_dir.rglob("*.png")):
        print(f"  {png.relative_to(out_dir)}")


if __name__ == "__main__":
    main()
