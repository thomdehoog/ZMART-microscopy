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
from typing import Any

import numpy as np

from .overview import Picks, TileEvent
from .target import TargetRecord
from .selection import (
    MODE_EMPTY, MODE_NO_QUALIFYING, MODE_SPARSE, MODE_THRESHOLD,
)


# BEGIN VISUALIZE STYLE TOKENS
# ─── Style tokens (palette + typography) ──────────────────────────
#
# Single source of truth for the visual style of every renderer in this
# module. When something looks wrong visually, change it here, not at
# the call site. test_visualize.py enforces that no hex colors or
# fontsize integer literals appear OUTSIDE this block.

# Palette. White-background-friendly. The picked / selected red is the
# only saturated color in the scatter and crop strip so picked picks
# dominate the operator's eye over the muted grays elsewhere.
_COLOR_INK_PRIMARY = "#1A2942"   # near-black navy — titles, picked picks
_COLOR_INK_BODY = "#3A4350"      # dark gray — body text, axis labels
_COLOR_INK_MUTED = "#5A6573"     # medium gray — tick labels, secondary
_COLOR_INK_CAPTION = "#7A8794"   # light gray — caption text, thresholds
_COLOR_RULE = "#B5BCC4"          # axis spines
_COLOR_GRID = "#E6E9EE"          # background grid
_COLOR_PANEL = "#FAFBFC"         # axes facecolor
_COLOR_PANEL_FALLBACK = "#F4F5F7"     # placeholder background
_COLOR_LEGEND_EDGE = "#D0D5DC"   # legend frame edge
_COLOR_NA_PLACEHOLDER = "#999999"   # gray for "N/A" placeholder text

_COLOR_PICK_SHOWN = "#C8423A"    # red — picks rendered as detail crops in
                                 # display_selection; also the target-FOV
                                 # rectangle on the overview tile in
                                 # display_target / plot_target_pairs.
# Selected-pick dot on the scatter. Same red as _COLOR_PICK_SHOWN; kept as
# a distinct name because the two are different UI roles and may diverge.
_COLOR_SELECTED = _COLOR_PICK_SHOWN
# Current-acquiring-tile highlight in render_scan_field_panel / display_tile's
# field-position panel. Currently aliased to _COLOR_PICK_SHOWN for visual
# consistency; kept as a separate name because current-tile highlight and
# shown-pick state are different UI roles and may diverge later.
_COLOR_TILE_HIGHLIGHT = _COLOR_PICK_SHOWN
_COLOR_THRESHOLD = _COLOR_INK_MUTED   # threshold guide lines

# Scan-field tile coloring (display_tile field panel, plot_scan_field
# secondary tiles, etc.)
_COLOR_TILE_FACE = "#E6E9EE"     # filled tiles, light gray
_COLOR_TILE_EDGE = "#BFC5CC"     # tile outline
_COLOR_BOUNDARY = "#A5ACB4"      # sample boundary outline (dashed)

# Typography scale. Anything not on this scale is a bug.
_FONT_TITLE = 14
_FONT_FIGURE_TITLE = 13          # batch-renderer figure suptitle (smaller
                                 # than top-level title; one step above
                                 # panel titles)
_FONT_CAPTION = 9
_FONT_AXIS_LABEL = 10
_FONT_PANEL_TITLE = 11           # subplot title; also serves as the figure-
                                 # subtitle size (the two roles converge at
                                 # 11pt by design)
_FONT_PLACEHOLDER = 12           # "N/A" placeholder text
_FONT_TICK = 9
_FONT_LEGEND = 9
_FONT_ANNOTATION = 10
_FONT_CROP_TITLE = 9

_CROP_SIZE_PX = 96               # fixed crop side length, in pixels

_COLOR_SCATTER_OTHER = "#B5BCC4" # gray — non-selected cells on scatter

_FRAME_ASPECT = 16 / 9
_FRAME_WIDTH_IN = 14.0

# Step 2 field axes rect in normalized figure coordinates [left, bottom,
# width, height]. All Step 2 panels (2a/2b/2c) use these so the field
# axes is pixel-identical across panels. Derived from tight_layout on a
# 14 x 7.875 figure with 13pt bold title and pad=12.
_FIELD_LEFT = 0.0385
_FIELD_BOTTOM = 0.0190
_FIELD_WIDTH = 0.9230
_FIELD_HEIGHT = 0.9230
_FIELD_CBAR_EXTRA_IN = 0.5
# END VISUALIZE STYLE TOKENS


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
    _ScatterLayer("other", _COLOR_SCATTER_OTHER, 18, 0.45, "o", None, 0, 2, "Other"),
    _ScatterLayer("selected", _COLOR_SELECTED, 42, 1.00, "o", "white", 0.6, 4, "Selected"),
)


# Mode-specific annotation banner rendered at the bottom of the scatter
# in display_selection. Declared here (not at first use) so module-level
# constants stay grouped together.
_MODE_ANNOTATIONS: dict[str, str] = {
    MODE_NO_QUALIFYING: "Zero cells qualified — adjust thresholds and re-run.",
    MODE_SPARSE: "Sparse sample: thresholds skipped, all non-border cells treated as qualifying.",
    MODE_EMPTY: "No cells detected in this overview.",
}


# ─── Scan-field rendering primitives ──────────────────────────────
#
# Shared helpers used by:
#   plot_scan_field     (Step 2b, standalone figure)
#   focus_map.plot      (Step 2c, surface overlay on top of the same tiles)
#   display_tile        (Step 3, small "where am I" panel during overview)
#
# Single source of truth for tile rendering + aspect handling so the three
# entry points stay visually consistent.


@dataclass(frozen=True)
class TileStyle:
    """Per-tile drawing style override for render_scan_field_panel.

    alpha=None lets the alpha channel embedded in `facecolor` govern.
    Setting alpha to a float overrides that channel. The previous
    default of 1.0 silently overrode 0.25-alpha face colors and
    eliminated tile-tile overlap visibility in plot_scan_field.
    """
    facecolor: object             # str hex, RGBA tuple, or "none"
    edgecolor: object
    linewidth: float = 0.6
    alpha: float | None = None
    zorder: int = 2


@dataclass(frozen=True)
class ScanFieldRenderContext:
    """Geometry + extent info returned by render_scan_field_panel so
    callers can reuse it for overlays (focus colormap, autofocus markers,
    legend placement, etc.) without recomputing.
    """
    tile_bounds: list[tuple[float, float, float, float]]
    tile_bounds_by_region: dict[str, list[tuple[float, float, float, float]]]
    extent_x: tuple[float, float]
    extent_y: tuple[float, float]
    max_tile_size_um: float


def render_scan_field_panel(
    ax,
    scan_field: dict,
    boundary_limits: dict | None,
    *,
    highlight_tile_id: tuple[str, int, int] | None = None,
    tile_styles: dict[tuple[str, int, int], TileStyle] | None = None,
    padding_factor: float = 0.05,
    frame_aspect: float | None = None,
) -> ScanFieldRenderContext:
    """Render the scan-field tiles + optional boundary on `ax` and return
    a ScanFieldRenderContext describing the geometry.

    Used by display_tile (Step 3, with highlight_tile_id only),
    plot_scan_field (Step 2b, with tile_styles built from job colors),
    and focus_map.plot (Step 2c, with tile_styles forcing transparent
    faces so the focus colormap shows through). The returned context
    lets the caller place overlays without recomputing tile bounds.

    Style precedence per tile:
      1. If `tile_id == highlight_tile_id`, force the highlight style.
         (Deliberate: the current-acquiring-tile indicator must stay
         visually dominant over any per-tile job coloring.)
      2. Else, use `tile_styles[tile_id]` if provided.
      3. Else, use the default (light-gray face + tile-edge gray).

    Boundary is drawn iff `boundary_limits is not None`.

    The renderer is responsible for axes-level concerns (equal aspect,
    y-axis inversion, ticks off, spine styling). Figure-level concerns
    (figsize from data extent) live in `figsize_for_extent` — see the
    docstring there.
    """
    import matplotlib.patches as patches

    tile_positions = scan_field.get("tile_positions", {})
    tile_bounds: list[tuple[float, float, float, float]] = []
    tile_bounds_by_region: dict[str, list[tuple[float, float, float, float]]] = {}
    max_tile_size = 0.0

    if not tile_positions and boundary_limits is None:
        # Nothing to draw at all (no tiles, no envelope).
        ax.text(
            0.5, 0.5, "(no scan field)",
            ha="center", va="center", transform=ax.transAxes,
            fontsize=_FONT_CROP_TITLE, color=_COLOR_INK_MUTED,
        )
        ax.set_xticks([])
        ax.set_yticks([])
        return ScanFieldRenderContext(
            tile_bounds=[],
            tile_bounds_by_region={},
            extent_x=(0.0, 0.0),
            extent_y=(0.0, 0.0),
            max_tile_size_um=0.0,
        )

    all_x: list[float] = []
    all_y: list[float] = []

    for rid, region in tile_positions.items():
        ts = region.get("tile_size_um")
        if ts is None:
            continue
        max_tile_size = max(max_tile_size, float(ts))
        half = ts / 2
        region_key = str(rid)
        region_bounds = tile_bounds_by_region.setdefault(region_key, [])
        for pos in region["positions"]:
            cx, cy = pos["x_um"], pos["y_um"]
            tid = (str(rid), int(pos["row"]), int(pos["col"]))
            bounds = (cx - half, cy - half, cx + half, cy + half)
            tile_bounds.append(bounds)
            region_bounds.append(bounds)

            is_current = (highlight_tile_id is not None
                          and tid == highlight_tile_id)
            if is_current:
                face = _COLOR_TILE_HIGHLIGHT
                edge = _COLOR_TILE_HIGHLIGHT
                lw = 1.2
                zorder = 5
                alpha = 1.0
            elif tile_styles is not None and tid in tile_styles:
                style = tile_styles[tid]
                face = style.facecolor
                edge = style.edgecolor
                lw = style.linewidth
                zorder = style.zorder
                alpha = style.alpha
            else:
                face = _COLOR_TILE_FACE
                edge = _COLOR_TILE_EDGE
                lw = 0.4
                zorder = 2
                alpha = 1.0
            ax.add_patch(patches.Rectangle(
                (cx - half, cy - half), ts, ts,
                linewidth=lw, edgecolor=edge, facecolor=face,
                alpha=alpha, zorder=zorder,
            ))
            all_x.extend([cx - half, cx + half])
            all_y.extend([cy - half, cy + half])

    if boundary_limits is not None:
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
        # Per-axis padding: a wide-format scan field gets the right
        # vertical padding for its y-span (instead of the over-padded
        # max(x, y) the previous code produced). set_aspect("equal")
        # below preserves the visual aspect.
        x_span = max(max(all_x) - min(all_x), 1.0)
        y_span = max(max(all_y) - min(all_y), 1.0)
        pad_x = x_span * padding_factor
        pad_y = y_span * padding_factor
        x_lo, x_hi = min(all_x) - pad_x, max(all_x) + pad_x
        y_lo, y_hi = min(all_y) - pad_y, max(all_y) + pad_y
        ax.set_xlim(x_lo, x_hi)
        ax.set_ylim(y_lo, y_hi)
    else:
        x_lo = x_hi = y_lo = y_hi = 0.0
    ax.set_aspect("equal")
    ax.invert_yaxis()
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_color(_COLOR_RULE)
        spine.set_linewidth(0.6)

    if frame_aspect is not None and all_x:
        _pad_limits_to_aspect(ax, frame_aspect)
        new_xl = ax.get_xlim()
        new_yl = ax.get_ylim()
        x_lo, x_hi = new_xl[0], new_xl[1]
        y_lo, y_hi = min(new_yl), max(new_yl)

    return ScanFieldRenderContext(
        tile_bounds=tile_bounds,
        tile_bounds_by_region=tile_bounds_by_region,
        extent_x=(x_lo, x_hi),
        extent_y=(y_lo, y_hi),
        max_tile_size_um=max_tile_size,
    )


def _pad_limits_to_aspect(ax, aspect: float) -> None:
    """Symmetrically pad axes limits so x_range / y_range == aspect.

    Preserves inverted y-axis orientation (render_scan_field_panel calls
    invert_yaxis, so get_ylim() returns (high, low)).
    """
    xl = ax.get_xlim()
    yl = ax.get_ylim()
    y_inverted = yl[0] > yl[1]

    x_range = abs(xl[1] - xl[0])
    y_range = abs(yl[1] - yl[0])
    if y_range == 0 or x_range == 0:
        return

    current = x_range / y_range
    x_mid = (xl[0] + xl[1]) / 2
    y_lo, y_hi = min(yl), max(yl)
    y_mid = (y_lo + y_hi) / 2

    if current < aspect:
        new_x_half = y_range * aspect / 2
        ax.set_xlim(x_mid - new_x_half, x_mid + new_x_half)
    else:
        new_y_half = x_range / aspect / 2
        y_lo_new, y_hi_new = y_mid - new_y_half, y_mid + new_y_half
        if y_inverted:
            ax.set_ylim(y_hi_new, y_lo_new)
        else:
            ax.set_ylim(y_lo_new, y_hi_new)


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
    live_display: bool = True,
    save_png: bool = True,
    _save_queue: Any = None,
) -> None:
    """Render one tile inline during overview acquisition.

    If `scan_field` is provided, render a 3-panel figure:
        Field-with-current-tile | Tile image | Segmentation
    Otherwise fall back to the original 2-panel layout (image | segmentation).

    live_display: when False, build the figure but skip display(); useful
        in batch mode where only the saved PNG matters.
    save_png: when False, skip fig.savefig even if feedback_dir is set.
        With save_png=False and live_display=False the call is no-op
        rendering (figure built and closed without side effects);
        run_overview avoids it entirely in that combination.
    _save_queue: optional workflow._save_queue._FigureSaveQueue. When
        provided AND save_png=True, the savefig (and plt.close of the
        figure) is queued to the worker thread. Ownership of the figure
        transfers to the worker -- the producer must not close it. When
        None, savefig + close run on the producer thread (existing
        synchronous path; appropriate for ad-hoc invocations outside
        run_overview).
    """
    import matplotlib.pyplot as plt
    from IPython.display import display

    rid, row, col = event.tile_id
    is_mock = event.analysis_image_source != "acquired"
    prefix = "(mock) " if is_mock else ""

    show_field = scan_field is not None
    if show_field:
        # Field panel's share of the figure follows the scan-field aspect
        # so a wide field doesn't get squeezed into a square panel beside
        # the (square) tile + segmentation panels. Tile + segmentation
        # remain equal-width to each other.
        width_um, height_um = scan_field_extent_um(scan_field, boundary_limits)
        if width_um > 0 and height_um > 0:
            field_aspect = width_um / height_um  # >1 = wide, <1 = tall
        else:
            field_aspect = 1.0
        # Clamp to [0.5, 2.5] so very extreme aspect ratios don't squeeze
        # the tile + segmentation panels to unreadable widths.
        field_share = max(0.5, min(2.5, field_aspect))
        fig, axes = plt.subplots(
            1, 3, figsize=(15, 5),
            gridspec_kw={
                "width_ratios": [field_share, 1, 1],
                "wspace": 0.15,
            },
            constrained_layout=True,
        )
        field_ax, tile_ax, seg_ax = axes
    else:
        fig, axes = plt.subplots(
            1, 2, figsize=(12, 5), constrained_layout=True,
        )
        field_ax = None
        tile_ax, seg_ax = axes

    # Figure-ownership flag. When the save is queued to _save_queue,
    # the worker thread closes the figure after savefig; the producer
    # must not also close it (would race the worker / drop the canvas
    # before savefig runs).
    transferred = False
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

        # Segmentation panel (shared per-panel helper).
        _render_tile_segmentation_panel(
            seg_ax, event.image_2d, event.masks, event.n_cells,
            title_fontsize=_FONT_PANEL_TITLE,
        )

        fig.suptitle(
            f"{prefix}Tile R{rid} r{row}c{col}  ·  {event.n_cells} cells",
            fontsize=_FONT_TITLE, fontweight="bold",
            color=_COLOR_INK_PRIMARY,
        )
        # constrained_layout=True at figure creation handles spacing;
        # set_aspect("equal") + invert_yaxis() in the field panel no
        # longer triggers a tight_layout UserWarning.

        if live_display:
            display(fig)

        if feedback_dir is not None and save_png:
            feedback_dir.mkdir(parents=True, exist_ok=True)
            out_path = (
                feedback_dir / f"live_tile_R{rid}_r{row}c{col}.png"
            )
            if _save_queue is not None:
                # Hand the figure off to the worker thread. Worker
                # saves AND closes; producer must not call plt.close.
                def _save_and_close(fig=fig, out_path=out_path):
                    try:
                        fig.savefig(out_path, dpi=150)
                    finally:
                        plt.close(fig)
                _save_queue.submit(_save_and_close, label=out_path.name)
                transferred = True
            else:
                fig.savefig(out_path, dpi=150)
    finally:
        if not transferred:
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
        Title          "Target discovery"                14 pt bold
        Subtitle       "{N} selected · {N} cells"        11 pt
        Caption        "area ≥ ... · intensity ≥ ... · border ..." 9 pt
      scatter axes (height ratio 2.2 of grid)
        — gridlines, threshold lines, selected picks in red —
      crop strip (height ratio 1)
        — 6 fixed-size crops with bbox highlighted in red —
      bottom margin (6%)

    Scatter layers (`_LAYERS`): two layers — gray "other" (all non-
    selected cells) underneath, red "selected" on top. The contrast
    lets the operator see what was picked vs. what wasn't.

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

    fig, scatter_ax, crop_axes, header_ax = _build_selection_figure_layout(
        has_crops, plt, GridSpec,
    )

    try:
        fig.patch.set_facecolor("white")

        _render_scatter(scatter_ax, selection, crops_to_show)

        if has_crops:
            # _load_tile_by_key owns the cache: tile_key -> loaded tuple.
            # We only need image_2d for each crop; the helper caches the
            # full tuple so display_target can reuse if the same cache
            # is shared (not the case here -- display_selection's cache
            # is local to this call).
            tile_cache: dict = {}
            for ax, pick in zip(crop_axes, crops_to_show):
                tile_key = _normalize_tile_key(pick.pick_id[:3])
                loaded = _load_tile_by_key(
                    analysis_dir, tile_key, tile_cache=tile_cache,
                )
                img = loaded[0] if loaded is not None else None
                _render_crop(ax, pick, tile_key, img, Rectangle)
            for ax in crop_axes[len(crops_to_show):]:
                ax.set_visible(False)

        _render_figure_titles(header_ax, selection)

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
    """Create the figure and return (fig, scatter_ax, crop_axes, header_ax).

    Two variants:
      with_crops: 3-row grid (header / scatter / 6 crops)
      no_crops:   2-row grid (header / scatter)

    The header row is a dedicated invisible axes that owns the title +
    subtitle + caption text. Replaces the previous design where titles
    were placed at hardcoded figure-coords (y = 0.955 / 0.920 / 0.890)
    while the gridspec top margin changed between variants -- a recipe
    for drift. constrained_layout=True lets matplotlib size the rows
    without manual margin tuning.
    """
    if has_crops:
        fig = plt.figure(figsize=(14, 9), constrained_layout=True)
        gs = GridSpec(
            3, 6,
            height_ratios=[0.55, 2.2, 1.0],
            hspace=0.30, wspace=0.18,
            figure=fig,
        )
        header_ax = fig.add_subplot(gs[0, :])
        scatter_ax = fig.add_subplot(gs[1, :])
        crop_axes = [fig.add_subplot(gs[2, c]) for c in range(6)]
    else:
        fig = plt.figure(figsize=(10, 7), constrained_layout=True)
        gs = GridSpec(
            2, 1,
            height_ratios=[0.55, 4.0],
            figure=fig,
        )
        header_ax = fig.add_subplot(gs[0, 0])
        scatter_ax = fig.add_subplot(gs[1, 0])
        crop_axes = []

    header_ax.set_xticks([])
    header_ax.set_yticks([])
    header_ax.set_facecolor("white")
    for spine in header_ax.spines.values():
        spine.set_visible(False)
    return fig, scatter_ax, crop_axes, header_ax


def _render_figure_titles(header_ax, selection) -> None:
    """Title + subtitle + caption stacked in the header gridspec row.

    Uses axes-relative coordinates (ax.transAxes) so the text scales
    with the gridspec row, not with the figure. Replaces the previous
    fig.text(0.5, 0.955/0.920/0.890, ...) design that drifted when the
    gridspec top margin changed between variants.
    """
    header_ax.text(
        0.5, 0.85, "Target discovery",
        ha="center", va="top", transform=header_ax.transAxes,
        fontsize=_FONT_TITLE, fontweight="bold",
        color=_COLOR_INK_PRIMARY,
    )
    header_ax.text(
        0.5, 0.50,
        f"{selection.n_final} selected  ·  "
        f"{selection.n_total} cells",
        ha="center", va="top", transform=header_ax.transAxes,
        fontsize=_FONT_PANEL_TITLE, color=_COLOR_INK_BODY,
    )
    header_ax.text(
        0.5, 0.15, _format_provenance(selection),
        ha="center", va="top", transform=header_ax.transAxes,
        fontsize=_FONT_CAPTION, color=_COLOR_INK_CAPTION,
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
    """Classify all_cells_* entries into "selected" and "other" masks.

    Returns two boolean masks keyed by the _LAYERS entries:
      "selected" — cells whose pick_id is in selection.selected_picks
      "other"    — all remaining cells (the complement)
    """
    n = int(selection.all_cells_area.size)
    if n == 0:
        empty = np.zeros(0, dtype=bool)
        return {"selected": empty, "other": empty}

    cell_pick_ids = [
        (str(tid[0]), int(tid[1]), int(tid[2]), int(label))
        for tid, label in zip(
            selection.all_cells_tile_ids, selection.all_cells_labels,
        )
    ]
    selected_set = {p.pick_id for p in selection.selected_picks}
    selected_mask = np.array(
        [pid in selected_set for pid in cell_pick_ids], dtype=bool,
    )
    return {"selected": selected_mask, "other": ~selected_mask}


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
                linestyle="--", linewidth=1.0, alpha=0.7, zorder=3,
            )

    ax.set_xlabel("Mean intensity (a.u.)", fontsize=_FONT_AXIS_LABEL,
                  color=_COLOR_INK_BODY)
    ax.set_ylabel("Area (px²)", fontsize=_FONT_AXIS_LABEL,
                  color=_COLOR_INK_BODY)
    ax.tick_params(colors=_COLOR_INK_MUTED, labelsize=_FONT_TICK)

    leg = ax.legend(
        loc="upper left", fontsize=_FONT_LEGEND, framealpha=0.95,
        facecolor="white", edgecolor=_COLOR_LEGEND_EDGE, labelcolor=_COLOR_INK_BODY,
    )
    leg.get_frame().set_linewidth(0.6)

    annotation = _MODE_ANNOTATIONS.get(selection.mode)
    if annotation:
        ax.text(
            0.5, 0.04, annotation,
            ha="center", transform=ax.transAxes,
            fontsize=_FONT_ANNOTATION, color=_COLOR_PICK_SHOWN, fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.4", facecolor="white",
                      edgecolor=_COLOR_PICK_SHOWN, linewidth=0.8, alpha=0.95),
        )


def _render_crop(ax, pick, tile_key, img, Rectangle) -> None:
    """Render one fixed-size crop with the cell's bbox outlined in red.

    The crop is at most `_CROP_SIZE_PX` square (see `_safe_crop_window`
    for the off-edge clamping; smaller images yield a smaller crop).
    The window is centered on the cell when possible; near the image
    edge the window shifts inward to stay fully inside the image, so
    the cell appears off-center but is never cut off / zero-padded.
    This shift-not-pad behavior is the primary mechanism for edge cells
    -- with `border_margin_px=0` the selection pipeline allows edge
    cells through, and this is how they get rendered. Cells inside
    `border_margin_px > 0` are normally filtered upstream and never
    reach the crop strip."""
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
        fill=False, edgecolor=_COLOR_PICK_SHOWN, linewidth=1.4,
    ))

    rid, row, col = tile_key
    ax.set_title(
        f"R{rid} r{row}c{col}  ·  #{pick.pick_id[3]}",
        fontsize=_FONT_CROP_TITLE, color=_COLOR_INK_BODY, pad=3,
    )
    ax.set_xticks([])
    ax.set_yticks([])
    # Crop frame is a subtle neutral gray so the red bbox rectangle drawn
    # above stays the visually-dominant cue. Coloring the frame the same
    # as the bbox makes the two read as one fat red border at 96x96 and
    # swallows the bbox-specific signal.
    for spine in ax.spines.values():
        spine.set_color(_COLOR_RULE)
        spine.set_linewidth(1.0)


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


def _render_tile_segmentation_panel(
    ax,
    image_2d: np.ndarray,
    masks: np.ndarray,
    n_cells: int,
    *,
    title_fontsize: int = _FONT_PANEL_TITLE,
) -> None:
    """Per-panel renderer: tile image + cellpose mask overlay + title.

    Composed by display_tile (Step 3, live) and plot_overview_tiles
    (Step 4b, batch). Wraps the shared `_segmentation_overlay` plus
    the panel title and axis("off") boilerplate.
    """
    _segmentation_overlay(ax, image_2d, masks)
    ax.set_title(
        f"Segmentation ({n_cells} cells)",
        fontsize=title_fontsize, color=_COLOR_INK_BODY,
    )
    ax.axis("off")


def _render_target_crop_panel(
    ax,
    pick,
    record: "TargetRecord",
    tile_data: tuple | None,
    target_img: np.ndarray | None,
    *,
    title_fontsize: int = _FONT_PANEL_TITLE,
) -> None:
    """Per-panel renderer: centroid-centered crop at target FOV + title.

    Composed by display_target (live) and plot_target_pairs (batch).
    Falls back to an "N/A" placeholder when pick or tile_data is None.
    """
    if pick is not None and tile_data is not None:
        image_2d = tile_data[0]
        crop = _centroid_crop_at_target_fov(image_2d, pick, record, target_img)
        ax.imshow(crop, cmap="gray")
    else:
        ax.text(0.5, 0.5, "N/A", ha="center", va="center",
                transform=ax.transAxes,
                fontsize=_FONT_PLACEHOLDER,
                color=_COLOR_NA_PLACEHOLDER)
    ax.set_title(
        f"Overview crop (label {record.pick_id[3]})",
        fontsize=title_fontsize,
    )
    ax.axis("off")


def _render_highres_target_panel(
    ax,
    target_img: np.ndarray | None,
    *,
    title_fontsize: int = _FONT_PANEL_TITLE,
) -> None:
    """Per-panel renderer: high-res target image + title.

    Composed by display_target and plot_target_pairs. Falls back to an
    "N/A" placeholder when target_img is None (acquisition failure or
    unreadable tif).
    """
    if target_img is not None:
        ax.imshow(target_img, cmap="gray")
    else:
        ax.text(0.5, 0.5, "N/A", ha="center", va="center",
                transform=ax.transAxes,
                fontsize=_FONT_PLACEHOLDER,
                color=_COLOR_NA_PLACEHOLDER)
    ax.set_title("High-res target", fontsize=title_fontsize)
    ax.axis("off")


def display_target(
    pick,
    record: TargetRecord,
    analysis_dir: Path,
    *,
    feedback_dir: Path | None = None,
    tile_cache: dict | None = None,
    live_display: bool = True,
    save_png: bool = True,
    _save_queue: Any = None,
) -> None:
    """Render one target 3-panel figure inline during acquisition.

    Left: full overview tile with cell mask overlay + target FOV rectangle.
    Middle: centroid-centered crop at target FOV.
    Right: acquired high-res target image.

    Pass a shared tile_cache dict across calls to avoid re-loading
    npz files for tiles that appear in multiple targets.

    live_display: when False, build the figure but skip display().
    save_png: when False, skip fig.savefig even if feedback_dir is set.
    _save_queue: optional workflow._save_queue._FigureSaveQueue. Same
        semantics as display_tile's _save_queue -- when provided AND
        save_png=True, the savefig + plt.close are queued to the
        worker; ownership of the figure transfers there.
    """
    import matplotlib.patches as patches
    import matplotlib.pyplot as plt
    import tifffile
    from IPython.display import display

    tile_key = _normalize_tile_key(record.pick_id[:3])

    # Single tile-lookup helper. When tile_cache is shared across calls
    # (e.g. acquire_targets's default callback) the path index is built
    # once and reused; per-tile loads are O(1) thereafter.
    tile_data = _load_tile_by_key(
        analysis_dir, tile_key, tile_cache=tile_cache,
    )

    target_img = None
    if record.tif_path is not None:
        try:
            target_img = tifffile.imread(str(record.tif_path))
            target_img = _ensure_2d(target_img)
        except Exception as exc:
            print(
                f"[visualize] WARNING: could not read target TIF "
                f"{record.tif_path}: {exc}"
            )

    fig, axes = plt.subplots(1, 3, figsize=(15, 5), constrained_layout=True)
    # Figure-ownership flag for the queued-save path; see display_tile.
    transferred = False
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
                edgecolor=_COLOR_PICK_SHOWN, facecolor="none",
                linewidth=1.5, zorder=10,
            ))
        elif tile_data is not None:
            axes[0].imshow(tile_data[0], cmap="gray")
        else:
            axes[0].text(0.5, 0.5, "N/A", ha="center", va="center",
                         transform=axes[0].transAxes,
                         fontsize=_FONT_PLACEHOLDER,
                         color=_COLOR_NA_PLACEHOLDER)
        axes[0].set_title("Overview tile", fontsize=_FONT_PANEL_TITLE)
        axes[0].axis("off")

        # Middle: centroid crop at target FOV (shared per-panel helper)
        _render_target_crop_panel(
            axes[1], pick, record, tile_data, target_img,
            title_fontsize=_FONT_PANEL_TITLE,
        )

        # Right: acquired high-res target (shared per-panel helper)
        _render_highres_target_panel(
            axes[2], target_img, title_fontsize=_FONT_PANEL_TITLE,
        )

        rid, row, col, label = record.pick_id
        fig.suptitle(f"Target R{rid} r{row}c{col} label {label}",
                     fontsize=_FONT_FIGURE_TITLE, fontweight="bold")

        if live_display:
            display(fig)

        if feedback_dir is not None and save_png:
            feedback_dir.mkdir(parents=True, exist_ok=True)
            out_path = (
                feedback_dir
                / f"live_target_R{rid}_r{row}c{col}_l{label}.png"
            )
            if _save_queue is not None:
                def _save_and_close(fig=fig, out_path=out_path):
                    try:
                        fig.savefig(out_path, dpi=150)
                    finally:
                        plt.close(fig)
                _save_queue.submit(_save_and_close, label=out_path.name)
                transferred = True
            else:
                fig.savefig(out_path, dpi=150)
    finally:
        if not transferred:
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

        fig, axes = plt.subplots(1, 3, figsize=(15, 5), constrained_layout=True)
        fig.patch.set_facecolor("white")

        axes[0].imshow(image_2d, cmap="gray")
        axes[0].set_title("Tile image", fontsize=_FONT_PANEL_TITLE)
        axes[0].axis("off")

        # Segmentation panel (shared per-panel helper).
        _render_tile_segmentation_panel(
            axes[1], image_2d, masks, n_cells,
            title_fontsize=_FONT_PANEL_TITLE,
        )

        _picked_overlay(axes[2], image_2d, masks, labels)
        axes[2].set_title(f"Picked ({len(labels)})",
                          fontsize=_FONT_PANEL_TITLE)
        axes[2].axis("off")

        rid, row, col = tile_id
        prefix = "(mock) " if is_mock else ""
        fig.suptitle(f"{prefix}Tile R{rid} r{row}c{col}",
                     fontsize=_FONT_FIGURE_TITLE, fontweight="bold")

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
        except Exception as exc:
            print(
                f"[visualize] WARNING: could not read target TIF "
                f"{rec.tif_path}: {exc}"
            )

        fig, axes = plt.subplots(1, 3, figsize=(15, 5), constrained_layout=True)
        try:
            fig.patch.set_facecolor("white")

            # Left: full overview tile with marker
            if tile_data is not None:
                image_2d = tile_data[0]
                axes[0].imshow(image_2d, cmap="gray")
                if pick is not None:
                    cx, cy = pick.centroid_col_row_px
                    axes[0].scatter(cx, cy, s=60, marker="o",
                                    facecolor=_COLOR_PICK_SHOWN,
                                    edgecolor="white",
                                    linewidth=0.8, zorder=10)
            else:
                axes[0].text(0.5, 0.5, "N/A", ha="center", va="center",
                             transform=axes[0].transAxes,
                             fontsize=_FONT_PLACEHOLDER,
                             color=_COLOR_NA_PLACEHOLDER)
            axes[0].set_title("Overview tile", fontsize=_FONT_CROP_TITLE)
            axes[0].axis("off")

            # Middle: centroid crop at target FOV (shared per-panel helper)
            _render_target_crop_panel(
                axes[1], pick, rec, tile_data, target_img,
                title_fontsize=_FONT_CROP_TITLE,
            )

            # Right: acquired high-res target (shared per-panel helper)
            _render_highres_target_panel(
                axes[2], target_img, title_fontsize=_FONT_CROP_TITLE,
            )

            rid, row, col, label = rec.pick_id
            fig.suptitle(f"Target R{rid} r{row}c{col} label {label}",
                         fontsize=_FONT_FIGURE_TITLE, fontweight="bold")

            if feedback_dir is not None:
                fig.savefig(
                    feedback_dir / f"target_R{rid}_r{row}c{col}_l{label}.png",
                    dpi=150,
                )

            plt.show()
        finally:
            plt.close(fig)


# ─── Internal helpers ────────────────────────────────────────────


_TILE_INDEX_SENTINEL = ("__path_index__",)


def _load_tile_by_key(
    analysis_dir: Path,
    tile_key: tuple,
    *,
    tile_cache: dict | None = None,
):
    """Load a tile npz by tile_key. Returns (image_2d, masks, tile_id,
    source) or None if not found / unreadable.

    Single tile-lookup helper. Uses _build_tile_path_index for the
    tile_id -> path map and _load_tile_npz for the per-path read; both
    are also exposed for callers that iterate the directory directly
    (plot_overview_tiles, plot_target_pairs).

    When tile_cache is provided, it doubles as the per-call cache:
      tile_cache[_TILE_INDEX_SENTINEL] holds the path index once built;
      tile_cache[tile_key]             holds each tile's loaded tuple.
    Subsequent calls with the same tile_key are O(1).
    """
    if tile_cache is not None and tile_key in tile_cache:
        return tile_cache[tile_key]

    index = None
    if tile_cache is not None:
        index = tile_cache.get(_TILE_INDEX_SENTINEL)
    if index is None:
        index = _build_tile_path_index(analysis_dir)
        if tile_cache is not None:
            tile_cache[_TILE_INDEX_SENTINEL] = index

    path = index.get(tile_key)
    loaded = _load_tile_npz(path) if path is not None else None
    if tile_cache is not None:
        tile_cache[tile_key] = loaded
    return loaded


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
        except Exception as exc:
            print(
                f"[visualize] WARNING: could not index "
                f"{npz_path.name}: {exc}"
            )
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
