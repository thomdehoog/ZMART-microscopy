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
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .overview import Picks, TileEvent
from .target import TargetRecord
from .selection import (
    MODE_EMPTY, MODE_NO_QUALIFYING, MODE_SPARSE, MODE_THRESHOLD,
)


# ─── Style tokens (palette + typography) ──────────────────────────
#
# Single source of truth for the visual style of every renderer in this
# module. When something looks wrong visually, change it here, not at
# the call site.

# Palette. White-background-friendly. The "shown" red and "qualifying"
# blue are chosen so the picked picks pop without competing for attention.
_COLOR_INK_PRIMARY = "#1A2942"   # near-black navy — titles, picked picks
_COLOR_INK_BODY = "#3A4350"      # dark gray — body text, axis labels
_COLOR_INK_MUTED = "#5A6573"     # medium gray — tick labels, secondary
_COLOR_INK_CAPTION = "#7A8794"   # light gray — caption text, thresholds
_COLOR_RULE = "#B5BCC4"          # axis spines
_COLOR_GRID = "#E6E9EE"          # background grid
_COLOR_PANEL = "#FAFBFC"         # axes facecolor
_COLOR_PANEL_FALLBACK = "#F4F5F7"     # placeholder background

# Scatter-category colors (display_selection)
_COLOR_BELOW = "#C8CDD4"         # warm gray — below threshold
_COLOR_NEAR_BORDER = "#D9A14B"   # amber — too close to tile edge
_COLOR_QUALIFYING = "#4A7FB8"    # steel blue — qualified, lost to dedup/limits
_COLOR_SELECTED = _COLOR_INK_PRIMARY   # navy — selected, not shown as crop
_COLOR_SHOWN = "#C8423A"         # red — picks shown as crops; also used as
                                 # the "current tile" highlight in display_tile
_COLOR_THRESHOLD = _COLOR_INK_MUTED   # threshold guide lines

# Scan-field tile coloring (display_tile field panel, plot_scan_field
# secondary tiles, etc.)
_COLOR_TILE_FACE = "#E6E9EE"     # filled tiles, light gray
_COLOR_TILE_EDGE = "#BFC5CC"     # tile outline
_COLOR_BOUNDARY = "#A5ACB4"      # sample boundary outline (dashed)

# Typography scale. Anything not on this scale is a bug.
_FONT_TITLE = 14
_FONT_SUBTITLE = 11
_FONT_CAPTION = 9
_FONT_AXIS_LABEL = 10
_FONT_PANEL_TITLE = 11
_FONT_TICK = 9
_FONT_LEGEND = 9
_FONT_ANNOTATION = 10
_FONT_CROP_TITLE = 9

_CROP_SIZE_PX = 96               # fixed crop side length, in pixels


@dataclass(frozen=True)
class _ScatterLayer:
    """Data-driven scatter layer config. Adding a new category is one
    entry in `_LAYERS`; no branching in the render loop."""
    key: str                 # mask key in _classify_cells_for_scatter
    color: str
    size: int
    alpha: float
    marker: str              # matplotlib marker, e.g. "o", "D"
    edge: str | None         # edge color, or None for no edge
    edge_width: float
    zorder: int
    label: str               # short label; "({n})" is appended automatically


_LAYERS: tuple[_ScatterLayer, ...] = (
    _ScatterLayer("near_border", _COLOR_NEAR_BORDER,  20, 0.65, "o", None,    0.0, 1, "Near edge"),
    _ScatterLayer("below",       _COLOR_BELOW,        22, 0.75, "o", None,    0.0, 2, "Below threshold"),
    _ScatterLayer("qualifying",  _COLOR_QUALIFYING,   28, 0.85, "o", None,    0.0, 3, "Qualifying"),
    _ScatterLayer("selected",    _COLOR_SELECTED,     42, 1.00, "o", "white", 0.6, 4, "Selected"),
    _ScatterLayer("shown",       _COLOR_SHOWN,       130, 1.00, "D", "white", 1.2, 5, "Shown"),
)


# ─── Scan-field rendering primitives ──────────────────────────────
#
# Shared helpers used by:
#   plot_scan_field     (Step 2b, standalone figure)
#   focus_map.plot      (Step 2c, surface overlay on top of the same tiles)
#   display_tile        (Step 3, small "where am I" panel during overview)
#
# Single source of truth for tile rendering + aspect handling so the three
# entry points stay visually consistent.


def render_scan_field_panel(
    ax,
    scan_field: dict,
    boundary_limits: dict | None,
    *,
    highlight_tile_id: tuple[str, int, int] | None = None,
) -> None:
    """Compact scan-field rendering for an embedded panel.

    Light-gray tiles, optional boundary outline, current tile highlighted
    in red. No legend, no focus markers, no axis labels. Equal aspect.
    y-axis inverted to match stage convention.
    """
    import matplotlib.patches as patches

    tile_positions = scan_field.get("tile_positions", {})
    if not tile_positions:
        ax.text(
            0.5, 0.5, "(no scan field)",
            ha="center", va="center", transform=ax.transAxes,
            fontsize=_FONT_CROP_TITLE, color=_COLOR_INK_MUTED,
        )
        ax.set_xticks([])
        ax.set_yticks([])
        return

    all_x: list[float] = []
    all_y: list[float] = []

    for rid, region in tile_positions.items():
        ts = region.get("tile_size_um")
        if ts is None:
            continue
        half = ts / 2
        for pos in region["positions"]:
            cx, cy = pos["x_um"], pos["y_um"]
            tid = (str(rid), int(pos["row"]), int(pos["col"]))
            is_current = (highlight_tile_id is not None
                          and tid == highlight_tile_id)
            if is_current:
                face = _COLOR_SHOWN
                edge = _COLOR_SHOWN
                lw = 1.2
                zorder = 5
            else:
                face = _COLOR_TILE_FACE
                edge = _COLOR_TILE_EDGE
                lw = 0.4
                zorder = 2
            ax.add_patch(patches.Rectangle(
                (cx - half, cy - half), ts, ts,
                linewidth=lw, edgecolor=edge, facecolor=face, zorder=zorder,
            ))
            all_x.extend([cx - half, cx + half])
            all_y.extend([cy - half, cy + half])

    if boundary_limits:
        ax.add_patch(patches.Rectangle(
            (boundary_limits["x_min"], boundary_limits["y_min"]),
            boundary_limits["x_max"] - boundary_limits["x_min"],
            boundary_limits["y_max"] - boundary_limits["y_min"],
            linewidth=0.8, edgecolor=_COLOR_BOUNDARY, facecolor="none",
            linestyle=(0, (4, 3)), zorder=1,
        ))
        all_x.extend([boundary_limits["x_min"], boundary_limits["x_max"]])
        all_y.extend([boundary_limits["y_min"], boundary_limits["y_max"]])

    if all_x:
        span = max(max(all_x) - min(all_x), max(all_y) - min(all_y), 1.0)
        pad = span * 0.05
        ax.set_xlim(min(all_x) - pad, max(all_x) + pad)
        ax.set_ylim(min(all_y) - pad, max(all_y) + pad)
    ax.set_aspect("equal")
    ax.invert_yaxis()
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_color(_COLOR_RULE)
        spine.set_linewidth(0.6)


def scan_field_extent_um(
    scan_field: dict, boundary_limits: dict | None = None,
) -> tuple[float, float]:
    """Return (width_um, height_um) of the scan field's bounding box,
    including the boundary if present. (0, 0) if empty."""
    tile_positions = scan_field.get("tile_positions", {})
    xs: list[float] = []
    ys: list[float] = []
    for region in tile_positions.values():
        ts = region.get("tile_size_um") or 0.0
        half = ts / 2
        for pos in region["positions"]:
            xs.extend([pos["x_um"] - half, pos["x_um"] + half])
            ys.extend([pos["y_um"] - half, pos["y_um"] + half])
    if boundary_limits:
        xs.extend([boundary_limits["x_min"], boundary_limits["x_max"]])
        ys.extend([boundary_limits["y_min"], boundary_limits["y_max"]])
    if not xs or not ys:
        return 0.0, 0.0
    return float(max(xs) - min(xs)), float(max(ys) - min(ys))


def figsize_for_extent(
    width_um: float, height_um: float,
    *, long_inches: float = 14.0,
    short_min_inches: float = 5.0,
    short_max_inches: float = 10.0,
) -> tuple[float, float]:
    """Figure (width, height) inches whose aspect matches the data.

    The longer axis is fixed at `long_inches`; the shorter axis scales
    proportionally but is clamped to [short_min_inches, short_max_inches]
    so degenerate aspects don't produce unusable figures.
    """
    if width_um <= 0 or height_um <= 0:
        return long_inches, long_inches
    aspect = max(width_um, height_um) / min(width_um, height_um)
    short = max(short_min_inches, min(short_max_inches, long_inches / aspect))
    return (long_inches, short) if width_um >= height_um else (short, long_inches)


# ─── Live display (during acquisition) ───────────────────────────


def display_tile(
    event: TileEvent,
    *,
    scan_field: dict | None = None,
    boundary_limits: dict | None = None,
    feedback_dir: Path | None = None,
) -> None:
    """Render one tile inline during overview acquisition.

    If `scan_field` is provided, render a 3-panel figure:
        Field-with-current-tile | Tile image | Segmentation
    Otherwise fall back to the original 2-panel layout (image | segmentation).
    """
    import matplotlib.pyplot as plt
    from IPython.display import display

    rid, row, col = event.tile_id
    is_mock = event.analysis_image_source != "acquired"
    prefix = "(mock) " if is_mock else ""

    show_field = scan_field is not None
    if show_field:
        fig, axes = plt.subplots(
            1, 3, figsize=(15, 5),
            gridspec_kw={"width_ratios": [1, 1, 1], "wspace": 0.15},
        )
        field_ax, tile_ax, seg_ax = axes
    else:
        fig, axes = plt.subplots(1, 2, figsize=(12, 5))
        field_ax = None
        tile_ax, seg_ax = axes

    try:
        fig.patch.set_facecolor("white")

        if field_ax is not None:
            render_scan_field_panel(
                field_ax, scan_field, boundary_limits,
                highlight_tile_id=(str(rid), int(row), int(col)),
            )
            field_ax.set_title(
                "Field position", fontsize=_FONT_PANEL_TITLE,
                color=_COLOR_INK_BODY,
            )

        tile_ax.imshow(event.image_2d, cmap="gray")
        tile_ax.set_title(
            "Tile image", fontsize=_FONT_PANEL_TITLE, color=_COLOR_INK_BODY,
        )
        tile_ax.axis("off")

        _segmentation_overlay(seg_ax, event.image_2d, event.masks)
        seg_ax.set_title(
            f"Segmentation ({event.n_cells} cells)",
            fontsize=_FONT_PANEL_TITLE, color=_COLOR_INK_BODY,
        )
        seg_ax.axis("off")

        fig.suptitle(
            f"{prefix}Tile R{rid} r{row}c{col}  ·  {event.n_cells} cells",
            fontsize=_FONT_TITLE, fontweight="bold",
            color=_COLOR_INK_PRIMARY,
        )
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


# ─── display_selection: Step 4 figure ─────────────────────────────


def display_selection(
    selection,
    analysis_dir: Path,
    *,
    feedback_dir: Path | None = None,
) -> None:
    """Render Step 4 (Target discovery): scatter + 6 example crops.

    Layout (fixed; defined once below, no positional drift):

      top margin (5%)
        Title          "Target discovery"                     14 pt bold
        Subtitle       "{N} picks · {N} qualifying · {N} cells" 11 pt
        Caption        "area ≥ ... · intensity ≥ ... · border ..." 9 pt
      scatter axes (height ratio 2.2 of grid)
        — gridlines, 5 layered scatter categories, threshold lines —
      crop strip (height ratio 1)
        — 6 fixed-size crops with bbox highlighted in red —
      bottom margin (6%)

    Scatter layers (`_LAYERS`):
      amber — Near edge        bbox within `border_margin_px` of any tile edge
      gray  — Below threshold  qualifying mask is False, not near-edge
      blue  — Qualifying       passed threshold, lost to dedup or out-of-limits
      navy  — Selected         in final picks, did not land in the crop strip
      red   — Shown            in final picks AND rendered as a crop below

    Crops use a shift-not-pad window: centered on the cell when possible,
    shifted inward when the cell is near an edge. No zero-padding.
    """
    import matplotlib.pyplot as plt
    from matplotlib.gridspec import GridSpec
    from matplotlib.patches import Rectangle
    from IPython.display import display

    has_crops = bool(selection.selected_picks)
    crops_to_show = (
        _pick_example_crops(selection.selected_picks, n=6) if has_crops else []
    )

    fig, scatter_ax, crop_axes = _build_selection_figure_layout(
        has_crops, plt, GridSpec,
    )

    try:
        fig.patch.set_facecolor("white")

        _render_scatter(scatter_ax, selection, crops_to_show)

        if has_crops:
            tile_cache: dict[tuple, np.ndarray | None] = {}
            for ax, pick in zip(crop_axes, crops_to_show):
                tile_key = (pick.pick_id[0], pick.pick_id[1], pick.pick_id[2])
                if tile_key not in tile_cache:
                    tile_cache[tile_key] = _load_tile_image_for_crop(
                        analysis_dir, tile_key,
                    )
                _render_crop(ax, pick, tile_key, tile_cache[tile_key], Rectangle)
            for ax in crop_axes[len(crops_to_show):]:
                ax.set_visible(False)

        _render_figure_titles(fig, selection)

        if feedback_dir is not None:
            feedback_dir.mkdir(parents=True, exist_ok=True)
            fig.savefig(
                feedback_dir / "selection.png",
                dpi=150, bbox_inches="tight", facecolor="white",
            )

        display(fig)
    finally:
        plt.close(fig)


# ─── display_selection: layout + titles ────────────────────────────


def _build_selection_figure_layout(has_crops: bool, plt, GridSpec):
    """Create the figure and return (fig, scatter_ax, crop_axes).

    Two variants:
      with_crops:   2-row grid, scatter on top spanning 6 columns, 6 crops below
      no_crops:     scatter only, tighter aspect

    Margins (top/bottom/left/right) are chosen so the title block at the
    top has fixed pixel headroom regardless of which variant is used.
    """
    if has_crops:
        fig = plt.figure(figsize=(14, 9))
        gs = GridSpec(
            2, 6,
            height_ratios=[2.2, 1.0],
            hspace=0.40, wspace=0.18,
            figure=fig,
            top=0.86, bottom=0.06, left=0.06, right=0.98,
        )
        scatter_ax = fig.add_subplot(gs[0, :])
        crop_axes = [fig.add_subplot(gs[1, c]) for c in range(6)]
    else:
        fig = plt.figure(figsize=(10, 7))
        gs = GridSpec(
            1, 1,
            figure=fig,
            top=0.83, bottom=0.10, left=0.10, right=0.96,
        )
        scatter_ax = fig.add_subplot(gs[0, 0])
        crop_axes = []
    return fig, scatter_ax, crop_axes


def _render_figure_titles(fig, selection) -> None:
    """Three text blocks above the scatter, vertically stacked at fixed y."""
    fig.text(
        0.5, 0.955, "Target discovery",
        ha="center", fontsize=_FONT_TITLE, fontweight="bold",
        color=_COLOR_INK_PRIMARY,
    )
    fig.text(
        0.5, 0.920,
        f"{selection.n_final} picks  ·  "
        f"{selection.n_qualifying} qualifying  ·  "
        f"{selection.n_total} cells",
        ha="center", fontsize=_FONT_SUBTITLE, color=_COLOR_INK_BODY,
    )
    fig.text(
        0.5, 0.890, _format_provenance(selection),
        ha="center", fontsize=_FONT_CAPTION, color=_COLOR_INK_CAPTION,
    )


def _format_provenance(selection) -> str:
    """Compact threshold / border / seed line for the figure caption."""
    parts = [
        _format_threshold(
            "area", selection.area_threshold,
            selection.area_threshold_auto, suffix=" px",
        ),
        _format_threshold(
            "intensity", selection.intensity_threshold,
            selection.intensity_threshold_auto,
        ),
    ]
    if selection.border_margin_px > 0:
        parts.append(f"border {selection.border_margin_px} px")
    parts.append(selection.seed_material)
    return "   ·   ".join(parts)


def _format_threshold(name: str, value: float, auto: bool, *, suffix: str = "") -> str:
    tag = "auto" if auto else "override"
    return f"{name} ≥ {value:.0f}{suffix} ({tag})"


# ─── display_selection helpers ─────────────────────────────────────


def _classify_cells_for_scatter(
    selection, crops_to_show: list,
) -> dict[str, np.ndarray]:
    """Partition all_cells_* indices into 5 mutually-exclusive masks.

    Priority (later wins; earlier categories are pre-empted by later ones):
      near_border < below < qualifying < selected < shown

    near_border cells were force-excluded from qualifying upstream;
    they sit in their own bucket so the operator can see how many cells
    were dropped for being too close to a tile edge.
    """
    n = int(selection.all_cells_area.size)
    if n == 0:
        empty = np.zeros(0, dtype=bool)
        return dict.fromkeys(
            ("near_border", "below", "qualifying", "selected", "shown"), empty,
        )

    cell_pick_ids = [
        (str(tid[0]), int(tid[1]), int(tid[2]), int(label))
        for tid, label in zip(
            selection.all_cells_tile_ids, selection.all_cells_labels,
        )
    ]
    selected_set = {p.pick_id for p in selection.selected_picks}
    shown_set = {p.pick_id for p in crops_to_show}

    selected_mask = np.array(
        [pid in selected_set for pid in cell_pick_ids], dtype=bool,
    )
    shown_mask = np.array(
        [pid in shown_set for pid in cell_pick_ids], dtype=bool,
    )
    qualifying = np.asarray(selection.qualifying_mask, dtype=bool)
    near_border = np.asarray(selection.near_border_mask, dtype=bool)

    return {
        # near-border cells were forced out of qualifying upstream
        "near_border": near_border,
        # below = neither qualifying nor near_border
        "below": ~qualifying & ~near_border,
        # qualifying but not in the final picks (lost to dedup or limits)
        "qualifying": qualifying & ~selected_mask,
        # in final picks but not in the crop strip
        "selected": selected_mask & ~shown_mask,
        # in final picks and rendered as a crop
        "shown": shown_mask,
    }


def _render_scatter(ax, selection, crops_to_show: list) -> None:
    """Render the scatter panel.

    Iterates `_LAYERS` (single source of truth for the scatter category
    config). Layers with zero cells are skipped (no legend clutter).
    Threshold dashed lines and mode-specific annotation are added on top.
    """
    areas = selection.all_cells_area
    intensities = selection.all_cells_intensity

    # Panel chrome
    ax.set_facecolor(_COLOR_PANEL)
    ax.grid(True, which="major", linewidth=0.5, color=_COLOR_GRID, zorder=0)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_color(_COLOR_RULE)
        spine.set_linewidth(0.8)

    if areas.size == 0:
        ax.text(
            0.5, 0.5, "No cells detected",
            ha="center", va="center", transform=ax.transAxes,
            fontsize=_FONT_ANNOTATION + 1, color=_COLOR_INK_MUTED,
        )
        ax.set_xticks([])
        ax.set_yticks([])
        return

    # Scatter layers (data-driven)
    masks = _classify_cells_for_scatter(selection, crops_to_show)
    for layer in _LAYERS:
        mask = masks[layer.key]
        n = int(mask.sum())
        if n == 0:
            continue
        kwargs: dict = dict(
            s=layer.size, c=layer.color, alpha=layer.alpha,
            marker=layer.marker, zorder=layer.zorder,
            label=f"{layer.label} ({n})",
        )
        if layer.edge is not None:
            kwargs["edgecolors"] = layer.edge
            kwargs["linewidths"] = layer.edge_width
        else:
            kwargs["linewidths"] = 0
        ax.scatter(intensities[mask], areas[mask], **kwargs)

    # Threshold guides (only in modes where thresholds are meaningful)
    if selection.mode in (MODE_THRESHOLD, MODE_NO_QUALIFYING):
        for axis_method, threshold in (
            (ax.axvline, selection.intensity_threshold),
            (ax.axhline, selection.area_threshold),
        ):
            axis_method(
                threshold, color=_COLOR_THRESHOLD,
                linestyle="--", linewidth=1.0, alpha=0.7, zorder=1,
            )

    ax.set_xlabel("Mean intensity (a.u.)", fontsize=_FONT_AXIS_LABEL,
                  color=_COLOR_INK_BODY)
    ax.set_ylabel("Area (px²)", fontsize=_FONT_AXIS_LABEL,
                  color=_COLOR_INK_BODY)
    ax.tick_params(colors=_COLOR_INK_MUTED, labelsize=_FONT_TICK)

    leg = ax.legend(
        loc="upper left", fontsize=_FONT_LEGEND, framealpha=0.95,
        facecolor="white", edgecolor="#D0D5DC", labelcolor=_COLOR_INK_BODY,
    )
    leg.get_frame().set_linewidth(0.6)

    annotation = _MODE_ANNOTATIONS.get(selection.mode)
    if annotation:
        ax.text(
            0.5, 0.04, annotation,
            ha="center", transform=ax.transAxes,
            fontsize=_FONT_ANNOTATION, color=_COLOR_SHOWN, fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.4", facecolor="white",
                      edgecolor=_COLOR_SHOWN, linewidth=0.8, alpha=0.95),
        )


_MODE_ANNOTATIONS: dict[str, str] = {
    MODE_NO_QUALIFYING: "Zero cells qualified — adjust thresholds and re-run.",
    MODE_SPARSE: "Sparse sample: thresholds skipped, all non-border cells treated as qualifying.",
    MODE_EMPTY: "No cells detected in this overview.",
}


def _render_crop(ax, pick, tile_key, img, Rectangle) -> None:
    """Render one fixed-size crop with the cell's bbox outlined in red.

    Always _CROP_SIZE_PX x _CROP_SIZE_PX. The crop window is centered on
    the cell when possible; near the image edge the window shifts inward
    to stay fully inside the image (so the cell appears off-center but
    is NEVER cut off / zero-padded). Cells inside `border_margin_px`
    of any edge should normally be filtered upstream so they don't get
    selected at all -- this shift-not-pad logic is the fallback for
    `border_margin_px=0`."""
    if img is None:
        ax.set_facecolor(_COLOR_PANEL_FALLBACK)
        ax.text(
            0.5, 0.5, "image\nunavailable",
            ha="center", va="center",
            transform=ax.transAxes, fontsize=_FONT_CROP_TITLE,
            color=_COLOR_INK_MUTED,
        )
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)
        return

    cx = int(round(pick.centroid_col_row_px[0]))
    cy = int(round(pick.centroid_col_row_px[1]))
    y_origin, x_origin, size = _safe_crop_window(img.shape, cy, cx, _CROP_SIZE_PX)
    crop = img[y_origin:y_origin + size, x_origin:x_origin + size]

    vmin, vmax = _robust_intensity_range(crop)
    ax.imshow(crop, cmap="gray", vmin=vmin, vmax=vmax, interpolation="nearest")

    # Translate skimage bbox (y0, x0, y1, x1) into crop-window coords.
    # The window may be shifted off-center when the cell is near an edge.
    y0, x0, y1, x1 = pick.bbox_px
    ax.add_patch(Rectangle(
        (x0 - x_origin - 0.5, y0 - y_origin - 0.5),
        max(1, x1 - x0), max(1, y1 - y0),
        fill=False, edgecolor=_COLOR_SHOWN, linewidth=1.4,
    ))

    rid, row, col = tile_key
    ax.set_title(
        f"R{rid} r{row}c{col}  ·  #{pick.pick_id[3]}",
        fontsize=_FONT_CROP_TITLE, color=_COLOR_INK_BODY, pad=3,
    )
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_color(_COLOR_SHOWN)
        spine.set_linewidth(1.2)


def _safe_crop_window(
    img_shape: tuple, cy: int, cx: int, size: int,
) -> tuple[int, int, int]:
    """Compute a (y_origin, x_origin, actual_size) crop window of side `size`
    that fits inside img_shape. Centers on (cy, cx) when possible; shifts
    inward at edges. If the image is smaller than `size`, returns the whole
    image (actual_size < size).
    """
    h, w = img_shape[:2]
    actual = min(size, h, w)
    half = actual // 2
    y_origin = cy - half
    x_origin = cx - half
    y_origin = max(0, min(y_origin, h - actual))
    x_origin = max(0, min(x_origin, w - actual))
    return y_origin, x_origin, actual


def _robust_intensity_range(arr: np.ndarray) -> tuple[float, float]:
    """Per-crop 1st/99th percentile range so a single bright pixel doesn't
    crush the rest of the cell to black."""
    flat = arr[arr > 0] if np.any(arr > 0) else arr
    if flat.size == 0:
        return 0.0, 1.0
    lo, hi = float(np.percentile(flat, 1)), float(np.percentile(flat, 99))
    if hi <= lo:
        hi = lo + 1.0
    return lo, hi


def _pick_example_crops(picks: list, n: int = 6) -> list:
    """Pick up to n example picks for the crop strip:
    1. Group by tile_id, sort within each by area descending.
    2. Take the largest from each of up to n distinct tiles.
    3. Fill remaining slots from already-represented tiles
       (next-largest within each).
    """
    by_tile: dict[tuple, list] = {}
    for p in picks:
        key = (p.pick_id[0], p.pick_id[1], p.pick_id[2])
        by_tile.setdefault(key, []).append(p)
    for group in by_tile.values():
        group.sort(key=lambda p: p.area_px, reverse=True)

    out: list = []
    for key in sorted(by_tile):
        if len(out) >= n:
            break
        out.append(by_tile[key][0])
    round_idx = 1
    while len(out) < n:
        added_this_round = False
        for key in sorted(by_tile):
            if round_idx < len(by_tile[key]):
                out.append(by_tile[key][round_idx])
                added_this_round = True
                if len(out) >= n:
                    break
        if not added_this_round:
            break
        round_idx += 1
    return out


def _load_tile_image_for_crop(
    analysis_dir: Path, tile_key: tuple,
) -> np.ndarray | None:
    """Load image_2d for one tile by scanning v2 NPZ files. Returns None
    if not found or unreadable."""
    if not analysis_dir.exists():
        return None
    for npz_path in sorted(analysis_dir.glob("*.npz")):
        try:
            with np.load(npz_path, allow_pickle=True) as data:
                if "tile_id" not in data.files:
                    continue
                tid = tuple(str(x) for x in data["tile_id"])
                if (tid[0], int(tid[1]), int(tid[2])) == tile_key:
                    return np.asarray(data["image_2d"])
        except Exception:
            continue
    return None


def display_target(
    pick,
    record: TargetRecord,
    analysis_dir: Path,
    *,
    feedback_dir: Path | None = None,
    tile_cache: dict | None = None,
) -> None:
    """Render one target 3-panel figure inline during acquisition.

    Left: full overview tile with cell mask overlay + target FOV rectangle.
    Middle: centroid-centered crop at target FOV.
    Right: acquired high-res target image.

    Pass a shared tile_cache dict across calls to avoid re-loading
    npz files for tiles that appear in multiple targets.
    """
    import matplotlib.patches as patches
    import matplotlib.pyplot as plt
    import tifffile
    from IPython.display import display

    tile_key = _normalize_tile_key(record.pick_id[:3])

    if tile_cache is not None and tile_key in tile_cache:
        tile_data = tile_cache[tile_key]
    else:
        tile_data = None
        for npz_path in analysis_dir.glob("*.npz"):
            loaded = _load_tile_npz(npz_path)
            if loaded is not None and _normalize_tile_key(loaded[2]) == tile_key:
                tile_data = loaded
                break
        if tile_cache is not None:
            tile_cache[tile_key] = tile_data

    target_img = None
    if record.tif_path is not None:
        try:
            target_img = tifffile.imread(str(record.tif_path))
            target_img = _ensure_2d(target_img)
        except Exception:
            pass

    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    try:
        fig.patch.set_facecolor("white")

        # Left: full overview tile with cell mask + target FOV rectangle
        if tile_data is not None and pick is not None:
            image_2d, masks = tile_data[0], tile_data[1]
            axes[0].imshow(image_2d, cmap="gray")

            label = pick.pick_id[3]
            mask_overlay = np.zeros((*masks.shape, 4), dtype=np.float32)
            mask_overlay[masks == label] = [1.0, 0.0, 0.0, 0.4]
            axes[0].imshow(mask_overlay)

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

            axes[0].add_patch(patches.Rectangle(
                (c0, r0), crop_w, crop_h,
                edgecolor="red", facecolor="none",
                linewidth=1.5, zorder=10,
            ))
        elif tile_data is not None:
            axes[0].imshow(tile_data[0], cmap="gray")
        else:
            axes[0].text(0.5, 0.5, "N/A", ha="center", va="center",
                         transform=axes[0].transAxes, fontsize=12,
                         color="#999999")
        axes[0].set_title("Overview tile", fontsize=11)
        axes[0].axis("off")

        # Middle: centroid crop at target FOV
        if pick is not None and tile_data is not None:
            image_2d = tile_data[0]
            crop = _centroid_crop_at_target_fov(
                image_2d, pick, record, target_img,
            )
            axes[1].imshow(crop, cmap="gray")
        else:
            axes[1].text(0.5, 0.5, "N/A", ha="center", va="center",
                         transform=axes[1].transAxes, fontsize=12,
                         color="#999999")
        axes[1].set_title(f"Overview crop (label {record.pick_id[3]})",
                          fontsize=11)
        axes[1].axis("off")

        # Right: acquired high-res target
        if target_img is not None:
            axes[2].imshow(target_img, cmap="gray")
        else:
            axes[2].text(0.5, 0.5, "N/A", ha="center", va="center",
                         transform=axes[2].transAxes, fontsize=12,
                         color="#999999")
        axes[2].set_title("High-res target", fontsize=11)
        axes[2].axis("off")

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
