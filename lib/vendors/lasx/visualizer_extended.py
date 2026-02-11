#!/usr/bin/env python3
"""
lasx_visualizer_extended.py

Extended visualization functions for autofocus workflow:
- Z-surface heatmap overlay
- Acquired image overlay
- Autofocus path visualization with diagnostics
- Consistent Y-axis inversion (microscope convention: high Y at top)

Works with the original lasx_visualizer.py — can be used standalone or imported.

Usage:
    from vendors.lasx.visualizer_extended import (
        visualize_z_surface,
        visualize_with_images,
        visualize_acquisition_path,
        visualize_comparison,
    )
"""

import json
import math
import numpy as np
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.colors import Normalize
from matplotlib.cm import ScalarMappable
from mpl_toolkits.axes_grid1 import make_axes_locatable

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


# ━━━ Shared helpers ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _setup_axes(ax, *, clean: bool = True):
    """
    Consistent axis setup for all plots.

    - aspect equal
    - Y-axis inverted (high values at top — standard microscope orientation)
    - optionally remove tick labels / grid for a clean look
    """
    ax.set_aspect("equal")
    ax.invert_yaxis()

    if clean:
        ax.set_xticklabels([])
        ax.set_yticklabels([])
        ax.tick_params(axis="both", which="both", length=0)
        ax.grid(False)
        for spine in ax.spines.values():
            spine.set_visible(True)
            spine.set_linewidth(0.8)
            spine.set_edgecolor("#cccccc")


def _auto_limits(ax, all_x: list, all_y: list, padding_frac: float = 0.05):
    """Set axis limits with padding."""
    if all_x and all_y:
        x_range = max(all_x) - min(all_x)
        y_range = max(all_y) - min(all_y)
        pad = max(x_range, y_range) * padding_frac
        ax.set_xlim(min(all_x) - pad, max(all_x) + pad)
        ax.set_ylim(min(all_y) - pad, max(all_y) + pad)


def _draw_geometry(ax, geom: Dict[str, Any], color: str = "white"):
    """Draw a geometry shape (ellipse, circle, rectangle, polygon)."""
    gtype = geom.get("type", "")
    verts = geom.get("vertices_um", [])

    if gtype == "Ellipse":
        center = geom.get("center_um")
        sa = geom.get("semi_axis_a_um", 0)
        sb = geom.get("semi_axis_b_um", 0)
        if center and sa > 0 and sb > 0:
            ell = patches.Ellipse(
                (center["x_um"], center["y_um"]), 2 * sa, 2 * sb,
                linewidth=1.5, edgecolor=color, facecolor="none", zorder=5,
            )
            ax.add_patch(ell)

    elif gtype == "CircleDiameter":
        center = geom.get("center_um")
        radius = geom.get("radius_um", 0)
        if center and radius > 0:
            circ = patches.Circle(
                (center["x_um"], center["y_um"]), radius,
                linewidth=1.5, edgecolor=color, facecolor="none", zorder=5,
            )
            ax.add_patch(circ)

    elif gtype == "Rectangle":
        bb = geom.get("bounding_box_um")
        if bb:
            rect = patches.Rectangle(
                (bb["x_min_um"], bb["y_min_um"]),
                bb.get("width_um", bb["x_max_um"] - bb["x_min_um"]),
                bb.get("height_um", bb["y_max_um"] - bb["y_min_um"]),
                linewidth=1.5, edgecolor=color, facecolor="none", zorder=5,
            )
            ax.add_patch(rect)

    elif gtype in ("AreaLine", "Polygon") and len(verts) >= 3:
        poly_xy = [(v["x_um"], v["y_um"]) for v in verts]
        poly = patches.Polygon(
            poly_xy, closed=True,
            linewidth=1.5, edgecolor=color, facecolor="none", zorder=5,
        )
        ax.add_patch(poly)


def _draw_focus_crosshairs(
    ax, fp_list, all_x, all_y, *,
    ordered: bool = False,
    data_range: float | None = None,
):
    """Draw crosshair markers for focus points."""
    if not fp_list:
        return

    if data_range is None:
        data_range = max(
            max(all_x) - min(all_x), max(all_y) - min(all_y)
        ) if all_x else 10_000

    cross_size = data_range * 0.006
    circle_r = cross_size * 0.6

    for idx, fp in enumerate(fp_list):
        fx, fy = fp["x_um"], fp["y_um"]
        fp_color = "#FF6B6B" if fp.get("z_measured", False) else "#4EB8B8"

        ax.plot([fx - cross_size, fx + cross_size], [fy, fy],
                "-", color=fp_color, linewidth=1.0, zorder=10)
        ax.plot([fx, fx], [fy - cross_size, fy + cross_size],
                "-", color=fp_color, linewidth=1.0, zorder=10)
        circ = patches.Circle(
            (fx, fy), circle_r,
            linewidth=1.0, edgecolor=fp_color, facecolor="none", zorder=11,
        )
        ax.add_patch(circ)

        if ordered and "acquisition_order" in fp:
            ax.text(fx + cross_size * 1.5, fy, str(fp["acquisition_order"]),
                    fontsize=7, color=fp_color, ha="left", va="center", zorder=12)

        all_x.append(fx)
        all_y.append(fy)


# ━━━ Z-Surface Heatmap ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def visualize_z_surface(
    data: Dict[str, Any],
    z_surface: Dict[str, Dict[int, float]],
    workflow_data: Optional[Dict[str, Any]] = None,
    show_heatmap: bool = True,
    show_focus_points: bool = True,
    show_acquisition_path: bool = False,
    ordered_focus_points: Optional[List[Dict[str, Any]]] = None,
    colormap: str = "viridis",
    figsize: Tuple[int, int] = (14, 10),
    output_path: Optional[str] = None,
    show: bool = False,
) -> plt.Figure:
    """
    Visualize the Z-surface as a heatmap overlay on tile positions.
    """
    if isinstance(data, str):
        with open(data) as f:
            data = json.load(f)

    positions = data.get("acquisition_positions", {})
    geometries = data.get("geometries", {})
    focus_points = data.get("focus_points", [])

    # Collect all Z for normalisation
    all_z: list[float] = []
    for group_z in z_surface.values():
        all_z.extend(group_z.values())
    z_min, z_max = (min(all_z), max(all_z)) if all_z else (0, 1)

    fig, ax = plt.subplots(figsize=figsize)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("#f5f5f8")

    cmap = plt.get_cmap(colormap)
    norm = Normalize(vmin=z_min, vmax=z_max)

    all_x: list[float] = []
    all_y: list[float] = []

    # Draw tiles
    for gid, group in positions.items():
        group_z = z_surface.get(gid, {})
        ts = group.get("tile_size_um")
        if ts is None:
            continue
        h = ts / 2.0

        for i, pos in enumerate(group["positions"]):
            cx, cy = pos["x_um"], pos["y_um"]
            all_x.extend([cx - h, cx + h])
            all_y.extend([cy - h, cy + h])

            if show_heatmap and i in group_z:
                color = cmap(norm(group_z[i]))
                face_color = (*color[:3], 0.6)
            else:
                face_color = (0.5, 0.5, 0.5, 0.2)

            rect = patches.Rectangle(
                (cx - h, cy - h), ts, ts,
                linewidth=0.5, edgecolor="gray", facecolor=face_color, zorder=2,
            )
            ax.add_patch(rect)

    # Geometries
    for geom in geometries.values():
        _draw_geometry(ax, geom, color="white")

    # Focus points
    if show_focus_points:
        fp_to_draw = ordered_focus_points or focus_points
        _draw_focus_crosshairs(
            ax, fp_to_draw, all_x, all_y,
            ordered=ordered_focus_points is not None,
        )

    # Acquisition path
    if show_acquisition_path and ordered_focus_points and len(ordered_focus_points) > 1:
        px = [p["x_um"] for p in ordered_focus_points]
        py = [p["y_um"] for p in ordered_focus_points]
        ax.plot(px, py, "-", color="#FF6B6B", linewidth=1.0, alpha=0.5, zorder=9)
        for i in range(len(px) - 1):
            ax.annotate(
                "", xy=(px[i + 1], py[i + 1]), xytext=(px[i], py[i]),
                arrowprops=dict(arrowstyle="->", color="#FF6B6B", alpha=0.5, lw=1.0),
                zorder=9,
            )

    # Limits & axes
    _auto_limits(ax, all_x, all_y)
    _setup_axes(ax, clean=True)

    # Colorbar
    if show_heatmap and all_z:
        divider = make_axes_locatable(ax)
        cax = divider.append_axes("right", size="3%", pad=0.1)
        sm = ScalarMappable(cmap=cmap, norm=norm)
        sm.set_array([])
        cbar = plt.colorbar(sm, cax=cax)
        cbar.set_label("Z Position (µm)", fontsize=10)

    z_range = z_max - z_min if all_z else 0
    ax.set_title(
        f"Z-Surface Map (Range: {z_range:.2f} µm)",
        fontsize=13, fontweight="bold", color="#222222", pad=12,
    )

    # Legend
    legend_elements = []
    if show_focus_points:
        legend_elements.append(
            plt.Line2D([0], [0], marker="+", color="#FF6B6B",
                       markersize=10, markeredgewidth=2, linestyle="",
                       label="Measured Focus Points"))
        legend_elements.append(
            plt.Line2D([0], [0], marker="+", color="#4EB8B8",
                       markersize=10, markeredgewidth=2, linestyle="",
                       label="Unmeasured Focus Points"))
    if legend_elements:
        ax.legend(handles=legend_elements, loc="upper right", fontsize=9)

    plt.tight_layout()
    if output_path:
        plt.savefig(output_path, dpi=300, bbox_inches="tight",
                    facecolor=fig.get_facecolor())
        print(f"✓ Z-surface visualization saved to {output_path}")
    if show:
        plt.show()
    return fig


# ━━━ Image Overlay ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def visualize_with_images(
    data: Dict[str, Any],
    image_dir: str,
    updated_positions: Optional[Dict[str, Dict[str, Any]]] = None,
    image_pattern: str = "tile_{group}_{index}.tif",
    show_focus_points: bool = True,
    show_geometries: bool = True,
    figsize: Tuple[int, int] = (16, 12),
    output_path: Optional[str] = None,
    show: bool = False,
) -> plt.Figure:
    """Visualize acquired images overlaid on tile positions."""
    if not PIL_AVAILABLE:
        raise ImportError("Pillow required: pip install Pillow")

    if isinstance(data, str):
        with open(data) as f:
            data = json.load(f)

    positions = updated_positions or data.get("acquisition_positions", {})
    geometries = data.get("geometries", {})
    focus_points = data.get("focus_points", [])
    image_dir = Path(image_dir)

    fig, ax = plt.subplots(figsize=figsize)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("#1a1a1a")

    all_x: list[float] = []
    all_y: list[float] = []
    images_loaded = 0

    for gid, group in positions.items():
        ts = group.get("tile_size_um")
        if ts is None:
            continue
        h = ts / 2.0
        tiles = group.get("positions", group.get("tiles", []))

        for i, pos in enumerate(tiles):
            cx, cy = pos["x_um"], pos["y_um"]
            all_x.extend([cx - h, cx + h])
            all_y.extend([cy - h, cy + h])

            img_path = image_dir / image_pattern.format(group=gid, index=i)
            if img_path.exists():
                try:
                    img = Image.open(img_path)
                    img_array = np.array(img)
                    if img_array.dtype != np.uint8:
                        lo, hi = img_array.min(), img_array.max()
                        if hi > lo:
                            img_array = ((img_array - lo) / (hi - lo) * 255).astype(np.uint8)
                        else:
                            img_array = np.zeros_like(img_array, dtype=np.uint8)
                    extent = [cx - h, cx + h, cy + h, cy - h]
                    ax.imshow(img_array, extent=extent, cmap="gray", aspect="auto", zorder=1)
                    images_loaded += 1
                except Exception as e:
                    print(f"Warning: Could not load {img_path}: {e}")
                    _draw_placeholder(ax, cx, cy, h, ts)
            else:
                _draw_placeholder(ax, cx, cy, h, ts)

    # Tile outlines
    for gid, group in positions.items():
        ts = group.get("tile_size_um")
        if ts is None:
            continue
        h = ts / 2.0
        tiles = group.get("positions", group.get("tiles", []))
        for pos in tiles:
            rect = patches.Rectangle(
                (pos["x_um"] - h, pos["y_um"] - h), ts, ts,
                linewidth=0.3, edgecolor="cyan", facecolor="none", alpha=0.5, zorder=3,
            )
            ax.add_patch(rect)

    if show_geometries:
        for geom in geometries.values():
            _draw_geometry(ax, geom, color="yellow")

    if show_focus_points and focus_points:
        _draw_focus_crosshairs(ax, focus_points, all_x, all_y)

    _auto_limits(ax, all_x, all_y)
    _setup_axes(ax, clean=True)

    ax.set_title(
        f"Acquired Images ({images_loaded} loaded)",
        fontsize=13, fontweight="bold", color="#222222", pad=12,
    )

    plt.tight_layout()
    if output_path:
        plt.savefig(output_path, dpi=300, bbox_inches="tight",
                    facecolor=fig.get_facecolor())
        print(f"✓ Image visualization saved to {output_path}")
    if show:
        plt.show()
    return fig


def _draw_placeholder(ax, cx, cy, h, ts):
    rect = patches.Rectangle(
        (cx - h, cy - h), ts, ts,
        linewidth=0.5, edgecolor="gray",
        facecolor=(0.2, 0.2, 0.2, 0.5), zorder=1,
    )
    ax.add_patch(rect)


# ━━━ Acquisition Path ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def visualize_acquisition_path(
    focus_points: List[Dict[str, Any]],
    positions: Optional[Dict[str, Dict[str, Any]]] = None,
    title: Optional[str] = None,
    figsize: Tuple[int, int] = (12, 10),
    output_path: Optional[str] = None,
    show: bool = False,
) -> plt.Figure:
    """
    Visualize the acquisition path with numbered markers, arrows,
    and total travel distance annotation.
    """
    fig, ax = plt.subplots(figsize=figsize)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("#f5f5f8")

    all_x: list[float] = []
    all_y: list[float] = []

    # Background: position group bounding boxes
    if positions:
        for gid, group in positions.items():
            bb = group.get("group_bounding_box", {})
            if bb:
                rect = patches.Rectangle(
                    (bb["x_min_um"], bb["y_min_um"]),
                    bb["x_max_um"] - bb["x_min_um"],
                    bb["y_max_um"] - bb["y_min_um"],
                    linewidth=1, edgecolor="gray",
                    facecolor=(0.9, 0.9, 0.9, 0.3), zorder=1,
                )
                ax.add_patch(rect)
                all_x.extend([bb["x_min_um"], bb["x_max_um"]])
                all_y.extend([bb["y_min_um"], bb["y_max_um"]])

    # Connecting lines + arrows
    if len(focus_points) > 1:
        px = [p["x_um"] for p in focus_points]
        py = [p["y_um"] for p in focus_points]

        ax.plot(px, py, "-", color="#3498db", linewidth=2, alpha=0.7, zorder=5)

        for i in range(len(px) - 1):
            mid_x = (px[i] + px[i + 1]) / 2
            mid_y = (py[i] + py[i + 1]) / 2
            dx = px[i + 1] - px[i]
            dy = py[i + 1] - py[i]
            ax.annotate(
                "", xy=(mid_x + dx * 0.1, mid_y + dy * 0.1),
                xytext=(mid_x - dx * 0.1, mid_y - dy * 0.1),
                arrowprops=dict(arrowstyle="->", color="#3498db", lw=1.5),
                zorder=6,
            )

    # Numbered point markers
    for i, fp in enumerate(focus_points):
        fx, fy = fp["x_um"], fp["y_um"]
        all_x.append(fx)
        all_y.append(fy)

        if i == 0:
            color = "#2ecc71"   # green  = start
        elif i == len(focus_points) - 1:
            color = "#e74c3c"   # red    = end
        else:
            color = "#3498db"   # blue   = waypoint

        circle = patches.Circle(
            (fx, fy), radius=50,
            facecolor=color, edgecolor="white", linewidth=2, zorder=10,
        )
        ax.add_patch(circle)

        order = fp.get("acquisition_order", i)
        ax.text(fx, fy, str(order), ha="center", va="center",
                fontsize=8, fontweight="bold", color="white", zorder=11)

    # Limits & axes
    _auto_limits(ax, all_x, all_y, padding_frac=0.1)
    _setup_axes(ax, clean=False)
    ax.set_xlabel("X Position (µm)", fontsize=10)
    ax.set_ylabel("Y Position (µm)", fontsize=10)

    # Travel distance annotation
    total_dist = _total_dist(focus_points)
    default_title = (
        f"Acquisition Path ({len(focus_points)} points, "
        f"total: {total_dist:.0f} µm / {total_dist / 1000:.2f} mm)"
    )
    ax.set_title(
        title or default_title,
        fontsize=13, fontweight="bold", pad=12,
    )

    legend_elements = [
        patches.Circle((0, 0), radius=1, facecolor="#2ecc71", label="Start"),
        patches.Circle((0, 0), radius=1, facecolor="#e74c3c", label="End"),
        patches.Circle((0, 0), radius=1, facecolor="#3498db", label="Waypoint"),
    ]
    ax.legend(handles=legend_elements, loc="upper right")

    plt.tight_layout()
    if output_path:
        plt.savefig(output_path, dpi=300, bbox_inches="tight")
        print(f"✓ Path visualization saved to {output_path}")
    if show:
        plt.show()
    return fig


def _total_dist(pts: list[dict]) -> float:
    if len(pts) < 2:
        return 0.0
    return sum(
        math.hypot(pts[i + 1]["x_um"] - pts[i]["x_um"],
                    pts[i + 1]["y_um"] - pts[i]["y_um"])
        for i in range(len(pts) - 1)
    )


# ━━━ Comparison View ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def visualize_comparison(
    data: Dict[str, Any],
    z_surface: Dict[str, Dict[int, float]],
    ordered_focus_points: List[Dict[str, Any]],
    figsize: Tuple[int, int] = (20, 8),
    output_path: Optional[str] = None,
    show: bool = False,
) -> plt.Figure:
    """Side-by-side: acquisition path + Z-surface heatmap."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=figsize)

    positions = data.get("acquisition_positions", {})

    all_x: list[float] = []
    all_y: list[float] = []

    # ── Left: layout + path ──
    for gid, group in positions.items():
        ts = group.get("tile_size_um")
        if ts is None:
            continue
        h = ts / 2.0
        for pos in group["positions"]:
            cx, cy = pos["x_um"], pos["y_um"]
            rect = patches.Rectangle(
                (cx - h, cy - h), ts, ts,
                linewidth=0.5, edgecolor="gray", facecolor=(0.7, 0.7, 0.7, 0.3),
            )
            ax1.add_patch(rect)
            all_x.extend([cx - h, cx + h])
            all_y.extend([cy - h, cy + h])

    if ordered_focus_points:
        px = [p["x_um"] for p in ordered_focus_points]
        py = [p["y_um"] for p in ordered_focus_points]
        ax1.plot(px, py, "o-", color="#e74c3c", markersize=6, linewidth=1.5)
        all_x.extend(px)
        all_y.extend(py)

    _auto_limits(ax1, all_x, all_y)
    _setup_axes(ax1, clean=True)
    ax1.set_title("Acquisition Layout & Path", fontsize=12, fontweight="bold")

    # ── Right: Z heatmap ──
    all_z = [z for gz in z_surface.values() for z in gz.values()]
    z_min, z_max = (min(all_z), max(all_z)) if all_z else (0, 1)
    cmap = plt.get_cmap("viridis")
    norm = Normalize(vmin=z_min, vmax=z_max)

    for gid, group in positions.items():
        group_z = z_surface.get(gid, {})
        ts = group.get("tile_size_um")
        if ts is None:
            continue
        h = ts / 2.0

        for i, pos in enumerate(group["positions"]):
            cx, cy = pos["x_um"], pos["y_um"]
            if i in group_z:
                color = cmap(norm(group_z[i]))
                face_color = (*color[:3], 0.6)
            else:
                face_color = (0.5, 0.5, 0.5, 0.2)

            rect = patches.Rectangle(
                (cx - h, cy - h), ts, ts,
                linewidth=0.5, edgecolor="gray", facecolor=face_color,
            )
            ax2.add_patch(rect)

    for fp in ordered_focus_points:
        if fp.get("z_measured", False):
            ax2.plot(fp["x_um"], fp["y_um"], "o", color="red", markersize=8)

    ax2.set_xlim(ax1.get_xlim())
    ax2.set_ylim(ax1.get_ylim())
    _setup_axes(ax2, clean=True)
    ax2.set_title(
        f"Interpolated Z-Surface (Range: {z_max - z_min:.2f} µm)",
        fontsize=12, fontweight="bold",
    )

    sm = ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = plt.colorbar(sm, ax=ax2, fraction=0.046, pad=0.04)
    cbar.set_label("Z (µm)")

    plt.tight_layout()
    if output_path:
        plt.savefig(output_path, dpi=300, bbox_inches="tight")
        print(f"✓ Comparison visualization saved to {output_path}")
    if show:
        plt.show()
    return fig


# ━━━ CLI ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":
    print("lasx_visualizer_extended.py")
    print("Extended visualization functions for autofocus workflow.")
    print("\nAvailable functions:")
    print("  - visualize_z_surface(data, z_surface, ...)")
    print("  - visualize_with_images(data, image_dir, ...)")
    print("  - visualize_acquisition_path(focus_points, ...)")
    print("  - visualize_comparison(data, z_surface, ordered_points, ...)")
