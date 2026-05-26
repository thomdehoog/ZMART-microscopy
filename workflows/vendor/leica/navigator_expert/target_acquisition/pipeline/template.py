"""template.py -- Stage limits, strip, z-wide, scan field.

prepare_template (Step 1): read boundary markers, set XY + Z stage
  limits, strip the template (removes markers), enforce z-wide.
  All before the operator draws the scan field.

read_scan_field (Step 2): parse the scan field the operator drew,
  synthesize tiles if geometry-only, narrow limits if Step 1
  deferred, populate ctx.scan_field.

plot_scan_field: visualise tiles, boundary, and focus markers.

Z-galvo is never commanded by this pipeline (D2/D3); we still pass
the stage.json z-galvo envelope to drv.set_stage_limits because the
API requires the values.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import shutil
import time

import navigator_expert.driver as drv
from navigator_expert.driver.templates.files import (
    TEMPLATE_BASE,
    TEMPLATE_XML,
    TEMPLATE_LRP,
    TEMPLATE_RGN,
    STRIPPED_BASE,
    STRIPPED_XML,
    STRIPPED_LRP,
    get_template_state,
)

from .context import Context
from ._logcapture import _logged


@_logged("initialization")
def prepare_template(ctx: Context) -> None:
    """Step 1: limits, strip, enforce z-wide.

    Sets stage limits, strips the template (removing boundary markers),
    and enforces z-wide on every job. All before the operator draws
    the scan field in Navigator Expert.

    Limits priority:
      1. Boundary point markers in Navigator Expert (preferred).
         Marker-derived XY is clamped to the physical envelope from
         stage.json with a printed report of any clamp.
      2. Explicit cfg.stage_x/y_min/max_um (escape hatch -- not
         surfaced in the notebook). Validated against the physical
         envelope; ValueError if any value falls outside.
      3. None -- physical envelope is applied for safety; Step 2
         will narrow XY using the scan field.
    """
    cfg = ctx.cfg
    client = ctx.client
    stage_cfg = ctx.stage_config

    # --- Validate cfg shape FIRST (fail fast before any LAS X work) ---
    cfg_xy_values = (cfg.stage_x_min_um, cfg.stage_x_max_um,
                     cfg.stage_y_min_um, cfg.stage_y_max_um)
    cfg_xy_any = any(v is not None for v in cfg_xy_values)
    cfg_xy_all = all(v is not None for v in cfg_xy_values)

    if cfg_xy_any and not cfg_xy_all:
        raise ValueError(
            "cfg stage XY fallback is partially set: "
            f"stage_x_min_um={cfg.stage_x_min_um}, "
            f"stage_x_max_um={cfg.stage_x_max_um}, "
            f"stage_y_min_um={cfg.stage_y_min_um}, "
            f"stage_y_max_um={cfg.stage_y_max_um}. "
            "All four must be set together, or all four left as None "
            "(prefer placing boundary markers in LAS X)."
        )

    # --- Read what's in LAS X right now ---
    save_result = drv.save_experiment(client, TEMPLATE_XML, ctx.templates_dir, timeout=60)
    if save_result is None:
        raise RuntimeError(
            "drv.save_experiment failed (returned None). "
            "Cannot read boundary markers from stale files."
        )
    parsed = drv.parse_template_positions(
        ctx.templates_dir, TEMPLATE_BASE, client=client,
    )
    boundary_points = [
        g["center_um"]
        for g in parsed.get("geometries", {}).values()
        if g.get("type") == "Point" and "center_um" in g
    ]

    # --- Z limits always from physical envelope (stage.json) ---
    z_galvo_min, z_galvo_max = stage_cfg["limits_um"]["z_galvo"]
    z_wide_min, z_wide_max = stage_cfg["limits_um"]["z_wide"]

    # --- Decide where XY limits come from ---
    if boundary_points:
        # Primary path: markers narrow within the envelope
        xs = [p["x_um"] for p in boundary_points]
        ys = [p["y_um"] for p in boundary_points]
        x_min = min(xs) - cfg.limit_margin_um
        x_max = max(xs) + cfg.limit_margin_um
        y_min = min(ys) - cfg.limit_margin_um
        y_max = max(ys) + cfg.limit_margin_um
        x_min, x_max, y_min, y_max = _clamp_xy_to_envelope(
            x_min, x_max, y_min, y_max, stage_cfg
        )
        source = f"{len(boundary_points)} boundary marker(s)"

    elif cfg_xy_all:
        # Fallback: explicit cfg, hard-validated
        _validate_cfg_xy(cfg, stage_cfg)
        x_min = float(cfg.stage_x_min_um)
        x_max = float(cfg.stage_x_max_um)
        y_min = float(cfg.stage_y_min_um)
        y_max = float(cfg.stage_y_max_um)
        source = "cfg fallback"

    else:
        # Defer: apply physical envelope so any intermediate move is
        # still bounded; Step 2 will narrow from the scan field.
        drv.apply_stage_limits_from_config(stage_cfg)
        actual = drv.get_stage_limits()
        ctx.boundary_limits = None
        print(
            "[step 2a] No boundary markers and no cfg XY fallback. "
            "Applied physical envelope from stage.json:\n"
            f"  X: {actual['x_min']:.0f} - {actual['x_max']:.0f} um\n"
            f"  Y: {actual['y_min']:.0f} - {actual['y_max']:.0f} um\n"
            f"  z-wide: {actual['z_wide_min']:.0f} - {actual['z_wide_max']:.0f} um\n"
            "Step 2 will narrow XY using the scan field."
        )
        _strip_and_enforce_zwide(ctx)
        return

    drv.set_stage_limits(
        x_min=x_min, x_max=x_max,
        y_min=y_min, y_max=y_max,
        z_galvo_min=z_galvo_min, z_galvo_max=z_galvo_max,
        z_wide_min=z_wide_min, z_wide_max=z_wide_max,
    )
    actual = drv.get_stage_limits()
    ctx.boundary_limits = actual

    print(
        f"[step 2a] Stage limits from {source} "
        f"(envelope from stage.json):\n"
        f"  X: {actual['x_min']:.0f} - {actual['x_max']:.0f} um\n"
        f"  Y: {actual['y_min']:.0f} - {actual['y_max']:.0f} um\n"
        f"  z-wide: {z_wide_min:.0f} - {z_wide_max:.0f} um (from stage.json)"
    )

    _strip_and_enforce_zwide(ctx)


@_logged("initialization")
def read_scan_field(ctx: Context) -> None:
    """Step 2: parse the scan field, populate ctx.scan_field.

    The operator draws the scan field in Navigator Expert after Step 1
    strips the template. This function saves the current experiment,
    parses tile positions (synthesizing from geometries if needed),
    and optionally narrows stage limits if Step 1 deferred them.
    """
    client = ctx.client
    cfg = ctx.cfg

    save_result = drv.save_experiment(
        client, TEMPLATE_XML, ctx.templates_dir, timeout=60,
    )
    if save_result is None:
        raise RuntimeError(
            "drv.save_experiment failed (returned None). "
            "Cannot read scan field."
        )

    template_data = drv.parse_template_positions(
        ctx.templates_dir, TEMPLATE_BASE, client=client,
    )

    tile_positions = template_data.get("acquisition_positions", {})

    if not tile_positions and template_data.get("geometries"):
        from navigator_expert.driver.templates.parsers import (
            _tile_size_from_image_size_str,
        )
        settings = drv.get_job_settings(client, cfg.acquisition_job)
        tile_size_um = None
        if settings:
            tile_size_um = _tile_size_from_image_size_str(
                settings.get("imageSize", ""),
            )
        if tile_size_um:
            raise RuntimeError(
                "Template has geometries but no pre-computed tile positions. "
                "Tile synthesis (synthesize_tiles) was removed as experimental. "
                "Use LAS X to generate tile positions from the geometry, then "
                "re-run the pipeline."
            )
        else:
            raise RuntimeError(
                "No tile positions found and tile size could not be "
                "determined from the job settings. Draw a scan field "
                "in Navigator Expert and re-run."
            )

    if not tile_positions:
        raise RuntimeError(
            "No tile positions found. Draw a scan field in "
            "Navigator Expert and re-run this cell."
        )

    n_tiles = sum(len(r["positions"]) for r in tile_positions.values())

    # If Step 1 deferred XY limits, narrow from the scan field now
    if ctx.boundary_limits is None:
        stage_cfg = ctx.stage_config
        z_galvo_min, z_galvo_max = stage_cfg["limits_um"]["z_galvo"]
        z_wide_min, z_wide_max = stage_cfg["limits_um"]["z_wide"]

        tile_xs = [p["x_um"] for r in tile_positions.values()
                   for p in r["positions"]]
        tile_ys = [p["y_um"] for r in tile_positions.values()
                   for p in r["positions"]]
        ts_half = max(
            (r.get("tile_size_um") or 0) for r in tile_positions.values()
        ) / 2

        x_min = min(tile_xs) - ts_half - cfg.limit_margin_um
        x_max = max(tile_xs) + ts_half + cfg.limit_margin_um
        y_min = min(tile_ys) - ts_half - cfg.limit_margin_um
        y_max = max(tile_ys) + ts_half + cfg.limit_margin_um
        x_min, x_max, y_min, y_max = _clamp_xy_to_envelope(
            x_min, x_max, y_min, y_max, stage_cfg,
        )

        drv.set_stage_limits(
            x_min=x_min, x_max=x_max,
            y_min=y_min, y_max=y_max,
            z_galvo_min=z_galvo_min, z_galvo_max=z_galvo_max,
            z_wide_min=z_wide_min, z_wide_max=z_wide_max,
        )
        ctx.boundary_limits = drv.get_stage_limits()
        print("[step 2b] Stage limits narrowed from scan field.")

    ctx.scan_field = {
        "template_data": template_data,
        "tile_positions": tile_positions,
        "n_tiles": n_tiles,
    }

    print(f"[step 2b] Scan field: {len(tile_positions)} group(s), "
          f"{n_tiles} tile(s)")
    for rid, region in tile_positions.items():
        print(f"  Group {rid}: {region['job_name']}  "
              f"{region.get('num_rows', '?')}x{region.get('num_cols', '?')}  "
              f"tile={region.get('tile_size_um', '?')} um")


@_logged("initialization")
def plot_stage_envelope(ctx: Context) -> None:
    """Step 2a visual: stage-envelope rectangle.

    Draws an empty 16:9 figure with the current stage envelope as a
    dashed rectangle, using the same axes style as plot_scan_field
    (inverted-y, no ticks, gray spines). No tiles, no focus markers,
    no legend -- this fires after prepare_template, before the operator
    has drawn a scan field in Navigator Expert.

    Envelope source:
      - If `ctx.boundary_limits` is set (boundary markers or cfg
        fallback path), draw that. Title says "boundary".
      - Else (deferred-limits path: no markers, no cfg fallback),
        re-fetch the physical envelope via `drv.get_stage_limits()`.
        prepare_template applied stage_cfg's physical limits in that
        branch; Step 2b will later narrow them from the scan field.
        Title says "physical envelope".
    """
    import matplotlib.pyplot as plt

    from .visualize import render_scan_field_panel

    if ctx.boundary_limits is not None:
        envelope = ctx.boundary_limits
        title = "Stage envelope (boundary)"
    else:
        # Deferred path. The physical envelope was applied by
        # prepare_template but not stashed on ctx; re-fetch.
        envelope = drv.get_stage_limits()
        title = "Stage envelope (physical, no boundary set)"

    from .visualize import (
        _FRAME_ASPECT, _FRAME_WIDTH_IN,
        _FIELD_LEFT, _FIELD_BOTTOM, _FIELD_WIDTH, _FIELD_HEIGHT,
        _FONT_FIGURE_TITLE, _COLOR_INK_PRIMARY, _TITLE_PAD,
    )

    fig = plt.figure(
        figsize=(_FRAME_WIDTH_IN, _FRAME_WIDTH_IN / _FRAME_ASPECT),
    )
    ax = fig.add_axes([_FIELD_LEFT, _FIELD_BOTTOM,
                       _FIELD_WIDTH, _FIELD_HEIGHT])
    fig.patch.set_facecolor("white")

    render_scan_field_panel(
        ax, {"tile_positions": {}, "n_tiles": 0}, envelope,
        padding_factor=0.12, frame_aspect=_FRAME_ASPECT,
    )

    ax.set_title(title, fontsize=_FONT_FIGURE_TITLE, fontweight="bold",
                 color=_COLOR_INK_PRIMARY, pad=_TITLE_PAD)

    logs_dir = ctx.run.layout.logs_dir("initialization")
    logs_dir.mkdir(parents=True, exist_ok=True)
    out_path = logs_dir / "stage_envelope.png"
    fig.savefig(out_path, dpi=150)
    print(f"[step 2a] Saved {out_path}")
    plt.show()


@_logged("initialization")
def plot_scan_field(ctx: Context) -> None:
    """Visualise the scan field: tiles (colored by job), boundary,
    focus / autofocus markers.

    Tile geometry, boundary, axis aspect, and ticks are drawn by the
    shared `render_scan_field_panel` so Step 2b stays visually
    consistent with display_tile (Step 3) and focus_map.plot (Step 2c).
    This function owns:
      - building tile_styles from job colors,
      - drawing focus / autofocus markers on top,
      - the legend and the figure title + save.
    """
    import matplotlib.patches as patches
    import matplotlib.pyplot as plt

    from .visualize import (
        TileStyle, render_scan_field_panel,
        _FRAME_ASPECT, _FRAME_WIDTH_IN, _pad_limits_to_aspect,
        _FIELD_LEFT, _FIELD_BOTTOM, _FIELD_WIDTH, _FIELD_HEIGHT,
        _FONT_FIGURE_TITLE, _COLOR_INK_PRIMARY, _TITLE_PAD,
    )

    if ctx.scan_field is None:
        raise RuntimeError("Call read_scan_field before plot_scan_field.")

    template_data = ctx.scan_field["template_data"]
    tile_positions = ctx.scan_field["tile_positions"]
    lim = ctx.boundary_limits

    fig = plt.figure(
        figsize=(_FRAME_WIDTH_IN, _FRAME_WIDTH_IN / _FRAME_ASPECT),
    )
    ax = fig.add_axes([_FIELD_LEFT, _FIELD_BOTTOM,
                       _FIELD_WIDTH, _FIELD_HEIGHT])
    fig.patch.set_facecolor("white")

    # Build per-tile styles from the template's job-color map. Tiles in
    # regions without a configured color fall back to a neutral gray.
    viz_colors = (template_data.get("visualization_data", {})
                  .get("tile_colors", {}))
    job_color_map = {
        region["job_name"]: tuple(viz_colors[region["job_name"]])
        for region in tile_positions.values()
        if region["job_name"] in viz_colors
    }
    default_rgba = (0.78, 0.78, 0.78, 1.0)

    tile_styles: dict[tuple[str, int, int], TileStyle] = {}
    legend_jobs: set[str] = set()
    for rid, region in tile_positions.items():
        jn = region["job_name"]
        ts = region.get("tile_size_um")
        if ts is None:
            continue
        rgba = job_color_map.get(jn, default_rgba)
        face = (rgba[0], rgba[1], rgba[2], 0.25)
        edge = (rgba[0], rgba[1], rgba[2], 0.80)
        for pos in region["positions"]:
            tid = (str(rid), int(pos["row"]), int(pos["col"]))
            tile_styles[tid] = TileStyle(
                facecolor=face, edgecolor=edge, linewidth=0.6, zorder=2,
            )
        if jn not in legend_jobs:
            label = "No job assigned" if jn == "(unassigned)" else jn
            ax.plot([], [], "s",
                    color=(rgba[0], rgba[1], rgba[2], 0.6),
                    markersize=8, label=label)
            legend_jobs.add(jn)

    # Shared renderer draws tiles + boundary + sets aspect/ticks/spines
    # and returns geometry for our overlays. padding_factor=0.12 widens
    # the axes margin so the boundary dashed line doesn't reach the
    # upper-right legend.
    rc = render_scan_field_panel(
        ax, ctx.scan_field, lim, tile_styles=tile_styles,
        padding_factor=0.12, frame_aspect=_FRAME_ASPECT,
    )
    if lim:
        ax.plot([], [], ls=(0, (4, 3)), color="#A5ACB4",
                linewidth=0.8, label="Sample boundary")

    cross = rc.max_tile_size_um * 0.25 if rc.max_tile_size_um else (
        max(rc.extent_x[1] - rc.extent_x[0],
            rc.extent_y[1] - rc.extent_y[0]) * 0.01
    )
    circle_r = cross * 0.6

    focus_color = "#e05555"
    marker_xs: list[float] = []
    marker_ys: list[float] = []
    for fp_list, label in [
        (template_data.get("focus_points", []), "Focus points"),
        (template_data.get("autofocus_points", []), "AutoFocus points"),
    ]:
        for fp in fp_list:
            fx, fy = fp["x_um"], fp["y_um"]
            ax.plot([fx - cross, fx + cross], [fy, fy],
                    "-", color=focus_color, linewidth=1.2, zorder=10)
            ax.plot([fx, fx], [fy - cross, fy + cross],
                    "-", color=focus_color, linewidth=1.2, zorder=10)
            ax.add_patch(patches.Circle(
                (fx, fy), circle_r,
                linewidth=1.2, edgecolor=focus_color,
                facecolor="none", zorder=11,
            ))
            # The cross arms extend to ±cross from (fx, fy); the circle
            # only reaches ±circle_r = cross * 0.6. Use the arm extent so
            # we don't clip the outer 40% of the cross when a marker sits
            # outside the tile envelope.
            arm = max(cross, circle_r)
            marker_xs.extend([fx - arm, fx + arm])
            marker_ys.extend([fy - arm, fy + arm])
        if fp_list:
            ax.plot([], [], "+", color=focus_color, markersize=10,
                    markeredgewidth=1.5, label=label)

    # render_scan_field_panel set xlim/ylim from tile + boundary bounds
    # only. Expand if focus / autofocus markers sit outside that envelope
    # so they aren't clipped at the axis edge (pre-D behavior).
    if marker_xs:
        cur_xlo, cur_xhi = ax.get_xlim()
        cur_ylo, cur_yhi = ax.get_ylim()
        # ylim is inverted by render_scan_field_panel, so cur_ylo > cur_yhi.
        y_top, y_bot = min(cur_ylo, cur_yhi), max(cur_ylo, cur_yhi)
        new_xlo = min(cur_xlo, min(marker_xs))
        new_xhi = max(cur_xhi, max(marker_xs))
        new_ytop = min(y_top, min(marker_ys))
        new_ybot = max(y_bot, max(marker_ys))
        if (new_xlo, new_xhi) != (cur_xlo, cur_xhi):
            ax.set_xlim(new_xlo, new_xhi)
        if (new_ytop, new_ybot) != (y_top, y_bot):
            ax.set_ylim(new_ybot, new_ytop)  # restore inverted orientation
        _pad_limits_to_aspect(ax, _FRAME_ASPECT)

    ax.set_title("Scan Field", fontsize=_FONT_FIGURE_TITLE, fontweight="bold",
                 color=_COLOR_INK_PRIMARY, pad=_TITLE_PAD)
    ax.legend(loc="upper right", fontsize=9, facecolor="white",
              edgecolor="#cccccc", labelcolor="#444444")

    logs_dir = ctx.run.layout.logs_dir("initialization")
    logs_dir.mkdir(parents=True, exist_ok=True)
    out_path = logs_dir / "overview_field.png"
    fig.savefig(out_path, dpi=150)
    print(f"[step 2b] Saved {out_path}")
    plt.show()


@_logged("initialization")
def archive_and_strip(ctx: Context) -> None:
    """Step 2d: archive the configured workflow, then strip for real.

    Preconditions:
      - ``drv.get_template_state(ctx.templates_dir) == "unstripped"``.
        Refusing otherwise prevents persisting a stripped LAS X state
        over the configured template -- happens when Step 2c ran with
        ``cfg.restore_template_after_af=False`` or when 2d is re-run
        after acquisition.
      - ``metadata_dir("initialization")`` does not already hold any of
        the three template files. The archive is the canonical record
        of the pipeline used for this run; refuse to overwrite it.

    Saves the current LAS X experiment to flush operator edits, waits
    for xml / lrp / rgn to settle on disk (the driver only confirms one
    file per save -- xml / lrp / rgn complete on different schedules),
    copies all three into ``run.layout.metadata_dir("initialization")``,
    then calls ``drv.strip_template`` -- the *final* strip. Step 3 and
    Step 5 no longer strip-or-restore; LAS X stays on the stripped
    template through the rest of the run.
    """
    client = ctx.client
    templates_dir = ctx.templates_dir

    state = get_template_state(templates_dir)
    if state != "unstripped":
        raise RuntimeError(
            f"archive_and_strip refused: template state is {state!r}, "
            f"expected 'unstripped'. If Step 2c ran with "
            f"cfg.restore_template_after_af=False, set it to True and "
            f"re-run 2c; otherwise restart from Step 2a so a fresh "
            f"configured template exists on disk."
        )

    archive_dir = ctx.run.layout.metadata_dir("initialization")
    archive_dir.mkdir(parents=True, exist_ok=True)

    existing = [name for name in (TEMPLATE_XML, TEMPLATE_LRP, TEMPLATE_RGN)
                if (archive_dir / name).is_file()]
    if existing:
        raise RuntimeError(
            f"archive_and_strip refused: archive already populated at "
            f"{archive_dir} ({', '.join(existing)}). The pipeline has "
            f"already been archived for this run; delete the existing "
            f"files manually if you need to re-archive."
        )

    src_xml = templates_dir / TEMPLATE_XML
    src_lrp = templates_dir / TEMPLATE_LRP
    src_rgn = templates_dir / TEMPLATE_RGN
    pre_mtimes = {
        p: (p.stat().st_mtime if p.is_file() else 0.0)
        for p in (src_xml, src_lrp, src_rgn)
    }

    # Confirm on the LRP because the driver flags LRP as the
    # late-updating file under the modify-lrp save path; XML and RGN
    # are then verified independently below.
    save_result = drv.save_experiment(
        client, TEMPLATE_XML, templates_dir,
        timeout=60, confirm_path=str(src_lrp),
    )
    if save_result is None:
        raise RuntimeError(
            "drv.save_experiment failed (returned None). "
            "Cannot archive pipeline files before final strip."
        )

    # save_experiment only confirmed LRP. Wait for XML and RGN to also
    # settle (mtime > snapshot + 3 consecutive stable size reads). A
    # file whose mtime never moves is treated as untouched-by-this-save
    # (LAS X didn't rewrite it because nothing affecting that file
    # changed) -- not an error.
    for path in (src_xml, src_rgn):
        _wait_for_file_stable(path, prev_mtime=pre_mtimes[path], timeout=10.0)

    archived: list[str] = []
    for name in (TEMPLATE_XML, TEMPLATE_LRP, TEMPLATE_RGN):
        src = templates_dir / name
        if not src.is_file():
            print(f"[step 2d] WARNING: {name} not found in templates_dir; "
                  f"skipping archive.")
            continue
        shutil.copy2(src, archive_dir / name)
        archived.append(name)

    print(f"[step 2d] Archived {len(archived)} pipeline file(s) to "
          f"{archive_dir}: {', '.join(archived)}")

    if not drv.strip_template(client):
        raise RuntimeError("drv.strip_template failed in archive_and_strip.")
    print("[step 2d] Template stripped. Scan field and markers will not "
          "be restored.")


# ---------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------


def _wait_for_file_stable(
    path: Path, *, prev_mtime: float,
    timeout: float, poll_interval: float = 0.1,
) -> None:
    """Wait for ``path`` to update past ``prev_mtime`` and stabilise.

    Mirrors save_experiment's confirm loop: poll until mtime > prev,
    then require 3 consecutive equal-size reads. If the mtime never
    advances within ``timeout``, return without raising -- LAS X
    didn't rewrite this file for this save, which is a valid
    no-op (e.g. operator edited only objects that live in the XML,
    so the RGN/LRP are still current from a prior save).
    """
    t0 = time.perf_counter()
    while (time.perf_counter() - t0) < timeout:
        try:
            if (path.is_file()
                    and path.stat().st_size > 0
                    and path.stat().st_mtime > prev_mtime):
                last_size = path.stat().st_size
                stable = 0
                while (time.perf_counter() - t0) < timeout:
                    time.sleep(poll_interval)
                    cur_size = path.stat().st_size
                    if cur_size == last_size:
                        stable += 1
                        if stable >= 3:
                            return
                    else:
                        stable = 0
                    last_size = cur_size
                return
        except OSError:
            pass
        time.sleep(poll_interval)


def _clamp_xy_to_envelope(
    x_min: float, x_max: float, y_min: float, y_max: float,
    stage_cfg: dict,
) -> tuple[float, float, float, float]:
    """Clamp marker-derived XY to the physical envelope, print any clamp."""
    px_min, px_max = stage_cfg["limits_um"]["x"]
    py_min, py_max = stage_cfg["limits_um"]["y"]

    if x_min < px_min:
        print(f"[step 2a] X min clamped from {x_min:.0f} to {px_min:.0f} um by stage_config.")
        x_min = px_min
    if x_max > px_max:
        print(f"[step 2a] X max clamped from {x_max:.0f} to {px_max:.0f} um by stage_config.")
        x_max = px_max
    if y_min < py_min:
        print(f"[step 2a] Y min clamped from {y_min:.0f} to {py_min:.0f} um by stage_config.")
        y_min = py_min
    if y_max > py_max:
        print(f"[step 2a] Y max clamped from {y_max:.0f} to {py_max:.0f} um by stage_config.")
        y_max = py_max

    if x_min >= x_max or y_min >= y_max:
        raise RuntimeError(
            f"After clamping, XY range is degenerate: "
            f"X=[{x_min}, {x_max}], Y=[{y_min}, {y_max}]. "
            f"Markers may be outside the physical envelope "
            f"(X={stage_cfg['limits_um']['x']}, "
            f"Y={stage_cfg['limits_um']['y']}). "
            f"Re-place markers inside the stage range."
        )
    return x_min, x_max, y_min, y_max


def _validate_cfg_xy(cfg: Any, stage_cfg: dict) -> None:
    """Hard-fail if explicit cfg XY limits fall outside the physical envelope."""
    px_min, px_max = stage_cfg["limits_um"]["x"]
    py_min, py_max = stage_cfg["limits_um"]["y"]
    problems: list[str] = []

    for name, value, lo, hi in (
        ("stage_x_min_um", cfg.stage_x_min_um, px_min, px_max),
        ("stage_x_max_um", cfg.stage_x_max_um, px_min, px_max),
        ("stage_y_min_um", cfg.stage_y_min_um, py_min, py_max),
        ("stage_y_max_um", cfg.stage_y_max_um, py_min, py_max),
    ):
        if not (lo <= value <= hi):
            problems.append(
                f"cfg.{name}={value} outside physical envelope [{lo}, {hi}]"
            )

    if cfg.stage_x_min_um >= cfg.stage_x_max_um:
        problems.append(
            f"cfg.stage_x_min_um ({cfg.stage_x_min_um}) "
            f"must be < stage_x_max_um ({cfg.stage_x_max_um})"
        )
    if cfg.stage_y_min_um >= cfg.stage_y_max_um:
        problems.append(
            f"cfg.stage_y_min_um ({cfg.stage_y_min_um}) "
            f"must be < stage_y_max_um ({cfg.stage_y_max_um})"
        )

    if problems:
        raise ValueError(
            "Invalid cfg stage XY fallback values "
            "(prefer placing boundary markers in LAS X instead):\n  "
            + "\n  ".join(problems)
        )


def _strip_and_enforce_zwide(ctx: Context) -> None:
    """Strip the template; best-effort z-wide enforcement (D2)."""
    client = ctx.client

    if not drv.strip_template(client):
        raise RuntimeError("drv.strip_template returned a falsy result.")

    lrp_path = ctx.templates_dir / STRIPPED_LRP
    if not lrp_path.exists():
        print("[step 2a] Template stripped. Skipped z-wide enforcement "
              "(stripped LRP not found on disk).")
        return

    try:
        parsed = drv.parse_lrp(lrp_path)
        for name in parsed["jobs"]:
            drv.lrp_set_z_use_mode(lrp_path, "z-wide", name)
        drv.load_experiment(client, STRIPPED_BASE)
        print("[step 2a] Template stripped and z-wide enforced on every job.")
    except Exception as exc:
        print(f"[step 2a] Template stripped. z-wide enforcement failed "
              f"({exc}); set z-wide manually in LAS X.")
