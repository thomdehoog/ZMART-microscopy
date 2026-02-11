#!/usr/bin/env python3
"""
lasx_visualizer.py

Visualization for LAS X template data.
Works entirely from parsed JSON - no access to original XML/LRP/RGN files.

Usage:
    from vendors.lasx.visualizer import visualize
    visualize(data, "output.png")
    
    # Or from command line:
    python lasx_visualizer.py input.json output.png
"""

import json
import sys
from typing import Dict, Any, Optional
import matplotlib
# Only use Agg backend for CLI usage (not in notebooks)
if not hasattr(sys, 'ps1') and 'ipykernel' not in sys.modules:
    matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as patches


def _draw_geometry(ax, geom: Dict[str, Any]):
    """Draw a geometry shape using pre-computed visualization properties."""
    gtype = geom.get("type", "")
    verts = geom.get("vertices_um", [])
    
    if gtype == "Ellipse":
        center = geom.get("center_um")
        sa = geom.get("semi_axis_a_um", 0)
        sb = geom.get("semi_axis_b_um", 0)
        if center and sa > 0 and sb > 0:
            ell = patches.Ellipse(
                (center["x_um"], center["y_um"]), 2 * sa, 2 * sb,
                linewidth=1.5, edgecolor='white', facecolor='none', zorder=5)
            ax.add_patch(ell)
    
    elif gtype == "CircleDiameter":
        center = geom.get("center_um")
        radius = geom.get("radius_um", 0)
        if center and radius > 0:
            circ = patches.Circle(
                (center["x_um"], center["y_um"]), radius,
                linewidth=1.5, edgecolor='white', facecolor='none', zorder=5)
            ax.add_patch(circ)
    
    elif gtype == "Rectangle":
        bb = geom.get("bounding_box_um")
        if bb:
            rect = patches.Rectangle(
                (bb["x_min_um"], bb["y_min_um"]),
                bb.get("width_um", bb["x_max_um"] - bb["x_min_um"]),
                bb.get("height_um", bb["y_max_um"] - bb["y_min_um"]),
                linewidth=1.5, edgecolor='white', facecolor='none', zorder=5)
            ax.add_patch(rect)
    
    elif gtype in ("AreaLine", "Polygon") and len(verts) >= 3:
        poly_xy = [(v["x_um"], v["y_um"]) for v in verts]
        poly = patches.Polygon(
            poly_xy, closed=True,
            linewidth=1.5, edgecolor='white', facecolor='none', zorder=5)
        ax.add_patch(poly)
        for v in verts:
            ax.plot(v["x_um"], v["y_um"], 'o', color='white',
                    markersize=5, markeredgewidth=1.0, markeredgecolor='white', zorder=6)
    
    elif gtype == "MagicWand" and len(verts) >= 1:
        for v in verts:
            ax.plot(v["x_um"], v["y_um"], 'o', color='white',
                    markersize=5, markeredgewidth=1.0, markeredgecolor='white', zorder=6)


def visualize(data: Dict[str, Any], output_path: Optional[str] = None, 
              figsize: tuple = (14, 10), dpi: int = 300, show: bool = False):
    """
    Generate visualization from parsed JSON data.
    
    This function does NOT access original XML/LRP/RGN files.
    All required data comes from the JSON structure.
    
    Args:
        data: Parsed template data (dict or path to JSON file)
        output_path: Path to save PNG (optional)
        figsize: Figure size in inches
        dpi: Resolution for saved image
        show: If True, display the plot (for notebooks)
    
    Returns:
        matplotlib Figure object
    """
    # Load JSON if path provided
    if isinstance(data, str):
        with open(data) as f:
            data = json.load(f)
    
    positions = data.get("acquisition_positions", {})
    if not positions:
        print("No positions to visualize")
        return None
    
    fig, ax = plt.subplots(figsize=figsize)
    fig.patch.set_facecolor('white')
    ax.set_facecolor('#f5f5f8')
    
    # Get visualization data
    viz_data = data.get("visualization_data", {})
    tile_colors = viz_data.get("tile_colors", {})
    geometries = data.get("geometries", {})
    focus_points = data.get("focus_points", [])
    autofocus_points = data.get("autofocus_points", [])
    
    # Fallback colors
    fallback_colors = [
        (0.78, 0.51, 0.35, 1.0),
        (0.30, 0.69, 0.69, 1.0),
        (0.80, 0.36, 0.36, 1.0),
        (0.55, 0.71, 0.35, 1.0),
        (0.65, 0.45, 0.75, 1.0),
    ]
    
    # Build job color map
    job_color_map: Dict[str, tuple] = {}
    fallback_idx = 0
    for gid, g in positions.items():
        jn = g["job_name"]
        if jn not in job_color_map:
            if jn in tile_colors:
                job_color_map[jn] = tuple(tile_colors[jn])
            else:
                job_color_map[jn] = fallback_colors[fallback_idx % len(fallback_colors)]
                fallback_idx += 1
    
    # Track coordinates for axis limits
    all_x, all_y = [], []
    
    # Draw tiles
    legend_jobs = set()
    for gid, g in positions.items():
        jn = g["job_name"]
        ts = g.get("tile_size_um")
        if ts is None:
            print(f"Warning: tile_size_um is None for group {gid} (job: {jn}). "
                  "Run enrich_with_api_data() to obtain tile sizes from the API.")
            continue
        rgba = job_color_map.get(jn, (0.5, 0.5, 0.5, 1.0))
        face_color = (rgba[0], rgba[1], rgba[2], 0.25)
        edge_color = (rgba[0], rgba[1], rgba[2], 0.80)
        h = ts / 2.0
        
        for pos in g["positions"]:
            cx, cy = pos["x_um"], pos["y_um"]
            rect = patches.Rectangle(
                (cx - h, cy - h), ts, ts,
                linewidth=0.6, edgecolor=edge_color, facecolor=face_color, zorder=2)
            ax.add_patch(rect)
            all_x.extend([cx - h, cx + h])
            all_y.extend([cy - h, cy + h])
        
        if jn not in legend_jobs:
            ax.plot([], [], 's', color=(rgba[0], rgba[1], rgba[2], 0.6),
                    markersize=8, label=jn)
            legend_jobs.add(jn)
    
    # Draw geometries (only those linked to active position groups)
    drawn_geom = set()
    for gid, g in positions.items():
        geom_id = g.get("geometry_id")
        if geom_id and geom_id in geometries:
            _draw_geometry(ax, geometries[geom_id])
            drawn_geom.add(geom_id)
    
    # Calculate crosshair sizes
    if all_x and all_y:
        data_range = max(max(all_x) - min(all_x), max(all_y) - min(all_y))
    else:
        data_range = 10000
    cross_size = data_range * 0.006
    circle_r = cross_size * 0.6
    
    # Draw focus points (turquoise)
    if focus_points:
        fp_color = '#4EB8B8'
        for fp in focus_points:
            fx, fy = fp["x_um"], fp["y_um"]
            ax.plot([fx - cross_size, fx + cross_size], [fy, fy],
                    '-', color=fp_color, linewidth=0.8, zorder=10)
            ax.plot([fx, fx], [fy - cross_size, fy + cross_size],
                    '-', color=fp_color, linewidth=0.8, zorder=10)
            circ = patches.Circle(
                (fx, fy), circle_r,
                linewidth=0.8, edgecolor=fp_color, facecolor='none', zorder=11)
            ax.add_patch(circ)
            all_x.append(fx)
            all_y.append(fy)
        ax.plot([], [], '+', color=fp_color, markersize=10,
                markeredgewidth=1.8, label='Focus Points')
    
    # Draw autofocus points (green)
    if autofocus_points:
        afp_color = '#5CBF5C'
        for afp in autofocus_points:
            fx, fy = afp["x_um"], afp["y_um"]
            ax.plot([fx - cross_size, fx + cross_size], [fy, fy],
                    '-', color=afp_color, linewidth=0.8, zorder=10)
            ax.plot([fx, fx], [fy - cross_size, fy + cross_size],
                    '-', color=afp_color, linewidth=0.8, zorder=10)
            circ = patches.Circle(
                (fx, fy), circle_r,
                linewidth=0.8, edgecolor=afp_color, facecolor='none', zorder=11)
            ax.add_patch(circ)
            all_x.append(fx)
            all_y.append(fy)
        ax.plot([], [], '+', color=afp_color, markersize=10,
                markeredgewidth=1.8, label='AutoFocus Points')
    
    # Set axis limits with padding
    if all_x and all_y:
        x_range = max(all_x) - min(all_x)
        y_range = max(all_y) - min(all_y)
        padding = max(x_range, y_range) * 0.05
        ax.set_xlim(min(all_x) - padding, max(all_x) + padding)
        ax.set_ylim(min(all_y) - padding, max(all_y) + padding)
    
    ax.set_aspect('equal')
    ax.invert_yaxis()
    ax.set_xticklabels([])
    ax.set_yticklabels([])
    ax.tick_params(axis='both', which='both', length=0)
    ax.grid(False)
    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_linewidth(0.8)
        spine.set_edgecolor('#cccccc')
    ax.set_title("LAS X Acquisition Layout", fontsize=13, fontweight='bold',
                 color='#222222', pad=12)
    ax.legend(loc='upper right', fontsize=9, facecolor='white',
              edgecolor='#cccccc', labelcolor='#444444')
    plt.tight_layout()
    
    if output_path:
        plt.savefig(output_path, dpi=dpi, bbox_inches='tight', facecolor=fig.get_facecolor())
        print(f"✓ Visualization saved to {output_path}")
    
    if show:
        plt.show()
    else:
        if not output_path:
            plt.close()
    
    return fig


def print_summary(data: Dict[str, Any]):
    """Print a summary of the parsed data."""
    if isinstance(data, str):
        with open(data) as f:
            data = json.load(f)
    
    n_jobs = len(data.get("acquisition_jobs", {}))
    n_groups = len(data.get("acquisition_positions", {}))
    n_tiles = sum(len(g["positions"]) for g in data.get("acquisition_positions", {}).values())
    n_fps = len(data.get("focus_points", []))
    n_afps = len(data.get("autofocus_points", []))
    n_geoms = len(data.get("geometries", {}))
    
    print(f"Template Summary:")
    print(f"  {n_jobs} acquisition job(s): {', '.join(data.get('acquisition_jobs', {}).keys())}")
    print(f"  {n_groups} position group(s) with {n_tiles} total tiles")
    print(f"  {n_fps} focus point(s), {n_afps} autofocus point(s)")
    print(f"  {n_geoms} geometr(y/ies)")
    
    viz = data.get("visualization_data", {})
    if viz:
        print(f"\nTile sizes:")
        for jn, ts in viz.get('job_tile_sizes', {}).items():
            print(f"  {jn}: {ts} µm")


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python lasx_visualizer.py <input.json> [output.png]")
        print("       python lasx_visualizer.py <input.json> --summary")
        sys.exit(1)
    
    json_path = sys.argv[1]
    
    with open(json_path) as f:
        data = json.load(f)
    
    if len(sys.argv) > 2 and sys.argv[2] == "--summary":
        print_summary(data)
    else:
        output_path = sys.argv[2] if len(sys.argv) > 2 else json_path.replace('.json', '_viz.png')
        print_summary(data)
        print()
        visualize(data, output_path)
