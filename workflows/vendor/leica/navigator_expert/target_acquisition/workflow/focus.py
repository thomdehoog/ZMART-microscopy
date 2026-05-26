"""focus.py -- Step 3: build a z-wide focus map.

At each focus marker, move XY, run the AF job, read back z-wide,
fit a surface model. The model is used by Step 4 to command z-wide
per tile.

Model selection:
    1 point or flat Z  → constant (mean z)
    2-3 points         → centered lstsq (line or plane by rank)
    4+ non-collinear   → thin plate spline (captures curvature)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

import navigator_expert.driver as drv
from navigator_expert.driver.commands import acquire as drv_acquire
from navigator_expert.driver.scanning_templates import (
    TEMPLATE_BASE,
    TEMPLATE_XML,
)

from .context import Context
from ._job_state import ensure_job_state
from ._logcapture import _logged

FLAT_TOLERANCE_UM = 0.1
SPLINE_SMOOTHING = 0.1


@dataclass
class FocusMap:
    model: str
    coeffs: np.ndarray | None
    origin_xy_um: tuple[float, float]
    measured: list[dict]
    residuals_um: np.ndarray
    scale_um: float = 1.0
    _interpolator: Any = field(default=None, repr=False)

    def interpolate_zwide(self, x, y):
        x0, y0 = self.origin_xy_um
        if self.model == "spline":
            x_arr, y_arr = np.broadcast_arrays(np.asarray(x), np.asarray(y))
            xn = (x_arr.ravel() - x0) / self.scale_um
            yn = (y_arr.ravel() - y0) / self.scale_um
            xy = np.column_stack([xn, yn])
            return self._interpolator(xy).reshape(x_arr.shape)
        return self.coeffs[0] * (x - x0) + self.coeffs[1] * (y - y0) + self.coeffs[2]

    @_logged("initialization", ctx_arg=1)
    def plot(self, ctx: Context) -> None:
        """Render the focus surface model + measured points on top of the
        scan-field tiles.

        Tile geometry, boundary, aspect, and ticks are delegated to the
        shared `render_scan_field_panel`; tiles are drawn with
        transparent faces so the focus colormap shows through. This
        method retains ownership of:
          - z-surface interpolation grid and clipping,
          - colormap normalization and colorbar,
          - focus / autofocus marker drawing,
          - figure title and legend.
        """
        import matplotlib.patches as patches
        import matplotlib.pyplot as plt
        from matplotlib.cm import ScalarMappable
        from matplotlib.colors import Normalize
        from matplotlib.path import Path as MplPath
        from matplotlib.patches import PathPatch

        from .visualize import (
            TileStyle, render_scan_field_panel,
            _FRAME_ASPECT, _FRAME_WIDTH_IN,
            _FIELD_LEFT, _FIELD_BOTTOM, _FIELD_WIDTH, _FIELD_HEIGHT,
            _FIELD_CBAR_EXTRA_IN,
            _FONT_FIGURE_TITLE, _COLOR_INK_PRIMARY, _TITLE_PAD,
        )

        if ctx.scan_field is None:
            raise RuntimeError("Call read_scan_field before focus_map.plot.")

        tile_positions = ctx.scan_field["tile_positions"]
        lim = ctx.boundary_limits

        if not tile_positions:
            print("[focus] No tiles to plot.")
            return

        field_h = _FRAME_WIDTH_IN / _FRAME_ASPECT
        total_h = field_h + _FIELD_CBAR_EXTRA_IN
        s = field_h / total_h
        fig = plt.figure(figsize=(_FRAME_WIDTH_IN, total_h))
        top_margin = (1 - _FIELD_BOTTOM - _FIELD_HEIGHT) * s
        field_bottom = 1 - top_margin - _FIELD_HEIGHT * s
        ax = fig.add_axes([_FIELD_LEFT, field_bottom,
                           _FIELD_WIDTH, _FIELD_HEIGHT * s])
        cbar_bar_in = 0.20
        cbar_below_in = 0.55
        cax_bottom = cbar_below_in / total_h
        cax_height = cbar_bar_in / total_h
        assert cax_bottom + cax_height <= field_bottom, (
            "2c colorbar overlaps the field axes — increase _FIELD_CBAR_EXTRA_IN"
        )
        cax = fig.add_axes([_FIELD_LEFT, cax_bottom,
                            _FIELD_WIDTH, cax_height])
        fig.patch.set_facecolor("white")

        # Force every tile transparent + white-edged so the colormap
        # (drawn behind, at zorder=1) shows through, with crisp tile
        # outlines on top. The shared renderer draws the patches; we
        # then add the colormap below them and the focus markers above.
        transparent_tile = TileStyle(
            facecolor="none", edgecolor="white", linewidth=0.5, zorder=3,
        )
        tile_styles: dict[tuple[str, int, int], TileStyle] = {}
        for rid, region in tile_positions.items():
            for pos in region["positions"]:
                tid = (str(rid), int(pos["row"]), int(pos["col"]))
                tile_styles[tid] = transparent_tile

        rc = render_scan_field_panel(
            ax, ctx.scan_field, lim, tile_styles=tile_styles,
            padding_factor=0.12, frame_aspect=_FRAME_ASPECT,
        )

        if not rc.tile_bounds:
            print("[focus] No tile geometry to overlay focus surface.")
            plt.close(fig)
            return

        # Build the interpolation grid covering the union of tile bounds.
        xs = [b[0] for b in rc.tile_bounds] + [b[2] for b in rc.tile_bounds]
        ys = [b[1] for b in rc.tile_bounds] + [b[3] for b in rc.tile_bounds]
        span = max(max(xs) - min(xs), max(ys) - min(ys))
        step = span / 500 if span > 0 else 1.0
        pad = 3 * step
        gx = np.arange(min(xs) - pad, max(xs) + pad + step, step)
        gy = np.arange(min(ys) - pad, max(ys) + pad + step, step)
        GX, GY = np.meshgrid(gx, gy)
        GZ = self.interpolate_zwide(GX, GY)

        if GZ.min() == GZ.max():
            norm = Normalize(vmin=GZ.min() - 0.5, vmax=GZ.max() + 0.5)
        else:
            norm = Normalize(vmin=GZ.min(), vmax=GZ.max())
        cmap = plt.get_cmap("viridis")

        # Clip the colormap to the union of tile rectangles.
        verts, codes = [], []
        for x0, y0, x1, y1 in rc.tile_bounds:
            verts += [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
            codes += [MplPath.MOVETO, MplPath.LINETO, MplPath.LINETO,
                      MplPath.LINETO, MplPath.CLOSEPOLY]
        clip_patch = PathPatch(
            MplPath(verts, codes),
            transform=ax.transData, facecolor="none", edgecolor="none",
        )
        ax.add_patch(clip_patch)

        im = ax.imshow(
            GZ, cmap=cmap, norm=norm, origin="lower", aspect="equal",
            extent=[gx[0], gx[-1] + step, gy[0], gy[-1] + step],
            interpolation="bilinear", zorder=1,
        )
        im.set_clip_path(clip_patch)

        # render_scan_field_panel drew the sample boundary at zorder=1;
        # the imshow above shares that zorder and was added afterward, so
        # matplotlib draws the colormap on top of the boundary. Redraw
        # the boundary above the image (zorder=2 sits above the colormap
        # and below the transparent tile outlines at zorder=3).
        if lim:
            ax.add_patch(patches.Rectangle(
                (lim["x_min"], lim["y_min"]),
                lim["x_max"] - lim["x_min"],
                lim["y_max"] - lim["y_min"],
                linewidth=0.8, edgecolor="#A5ACB4", facecolor="none",
                linestyle=(0, (4, 3)), zorder=2,
            ))

        cross = (rc.max_tile_size_um * 0.25
                 if rc.max_tile_size_um else span * 0.01)
        circle_r = cross * 0.6
        focus_color = "#e05555"
        for m in self.measured:
            fx, fy = m["x_um"], m["y_um"]
            ax.plot([fx - cross, fx + cross], [fy, fy],
                    "-", color=focus_color, linewidth=1.2, zorder=10)
            ax.plot([fx, fx], [fy - cross, fy + cross],
                    "-", color=focus_color, linewidth=1.2, zorder=10)
            ax.add_patch(patches.Circle(
                (fx, fy), circle_r, linewidth=1.2,
                edgecolor=focus_color, facecolor="none", zorder=11,
            ))
        ax.plot([], [], "+", color=focus_color, markersize=10,
                markeredgewidth=1.5, label="Focus points")
        if lim:
            ax.plot([], [], ls=(0, (4, 3)), color="#A5ACB4",
                    linewidth=0.8, label="Sample boundary")

        sm = ScalarMappable(cmap=cmap, norm=norm)
        sm.set_array([])
        plt.colorbar(sm, cax=cax, label="z-wide (um)",
                      orientation="horizontal")

        ax.set_title(
            "Focus map",
            fontsize=_FONT_FIGURE_TITLE, fontweight="bold",
            color=_COLOR_INK_PRIMARY, pad=_TITLE_PAD,
        )
        ax.legend(loc="upper right", fontsize=9, facecolor="white",
                  edgecolor="#cccccc", labelcolor="#444444")

        logs_dir = ctx.run.layout.logs_dir("initialization")
        logs_dir.mkdir(parents=True, exist_ok=True)
        out_path = logs_dir / "focus_map.png"
        fig.savefig(out_path, dpi=150)
        print(f"[step 2c] Saved {out_path}")
        plt.show()


@_logged("initialization")
def build_focus_map(ctx: Context) -> FocusMap:
    """Step 3: run AF at each focus marker, fit a z-wide surface model.

    Reads focus/autofocus positions from the template, strips the
    template, selects the AF job, moves to each marker, acquires,
    reads back the resulting z-wide, then fits a model.

    Model selection:
        flat Z (< 0.1 um range) → constant
        2-3 points              → centered lstsq (line or plane)
        4+ non-collinear        → thin plate spline
    """
    client = ctx.client
    cfg = ctx.cfg

    save_result = drv.save_experiment(
        client, TEMPLATE_XML, ctx.templates_dir, timeout=60,
    )
    if save_result is None:
        raise RuntimeError(
            "drv.save_experiment failed. Cannot read focus positions."
        )

    af_data = drv.parse_template_positions(
        ctx.templates_dir, TEMPLATE_BASE, client=client,
    )

    focus_positions = (
        af_data.get("focus_points", [])
        or af_data.get("autofocus_points", [])
    )
    if not focus_positions:
        raise RuntimeError(
            "No focus points found. Add focus or autofocus positions "
            "on the scan field in Navigator Expert, then re-run."
        )

    print(f"[step 2c] Focus positions ({len(focus_positions)}):")
    for i, fp in enumerate(focus_positions):
        print(f"  {i + 1}. x={fp['x_um']:.1f}  y={fp['y_um']:.1f} um")

    if not drv.strip_template(client):
        raise RuntimeError("drv.strip_template failed before AF loop.")

    try:
        ensure_job_state(ctx, cfg.af_job)

        measured: list[dict] = []
        for i, fp in enumerate(focus_positions):
            x_um = fp["x_um"]
            y_um = fp["y_um"]
            print(
                f"\n[{i + 1}/{len(focus_positions)}] "
                f"x={x_um:.0f}  y={y_um:.0f}",
                end="", flush=True,
            )
            backlash = ctx.stage_config.get("backlash")
            if backlash is not None:
                r = drv.move_xy_with_backlash(
                    client, x_um, y_um,
                    overshoot_um=backlash.get("overshoot_um", 50.0),
                    settle_ms=backlash.get("settle_ms", 100),
                )
            else:
                r = drv.move_xy(client, x_um, y_um)
            if not r or not r.get("success"):
                raise RuntimeError(
                    f"move_xy({x_um}, {y_um}) failed: {r!r}"
                )
            drv_acquire(client, cfg.af_job)
            settings = drv.get_job_settings(client, cfg.af_job)
            ch = drv.make_changeable_copy(settings)
            zwide_um = float(ch["zPosition"]["z-wide"])
            measured.append({**fp, "zwide_um": zwide_um})
            print(f"  z-wide={zwide_um:.2f} um")
    finally:
        if cfg.restore_template_after_af:
            try:
                drv.restore_template(client)
            except Exception as exc:
                print(f"[step 2c] WARNING: could not restore template: {exc}")

    fm = _fit_focus_model(measured)
    _print_focus_diagnostics(fm, ctx)
    return fm


def _fit_focus_model(measured: list[dict]) -> FocusMap:
    """Select and fit the appropriate focus model."""
    xs = np.array([m["x_um"] for m in measured])
    ys = np.array([m["y_um"] for m in measured])
    zs = np.array([m["zwide_um"] for m in measured])

    x0, y0 = float(xs.mean()), float(ys.mean())
    xc, yc = xs - x0, ys - y0
    z_range = float(zs.max() - zs.min())
    scale_um = 1.0

    if z_range < FLAT_TOLERANCE_UM:
        coeffs = np.array([0.0, 0.0, float(zs.mean())])
        residuals = zs - zs.mean()
        return FocusMap(
            model="constant", coeffs=coeffs,
            origin_xy_um=(x0, y0), measured=measured,
            residuals_um=residuals,
        )

    if len(measured) >= 4 and np.linalg.matrix_rank(np.column_stack([xc, yc])) >= 2:
        from scipy.interpolate import RBFInterpolator
        scale_um = float(max(np.ptp(xc), np.ptp(yc)))
        if scale_um == 0:
            scale_um = 1.0
        xy_n = np.column_stack([xc / scale_um, yc / scale_um])
        interpolator = RBFInterpolator(
            xy_n, zs, kernel="thin_plate_spline",
            smoothing=SPLINE_SMOOTHING,
        )
        residuals = zs - interpolator(xy_n).ravel()
        return FocusMap(
            model="spline", coeffs=None,
            origin_xy_um=(x0, y0), measured=measured,
            residuals_um=residuals, scale_um=scale_um,
            _interpolator=interpolator,
        )

    A = np.column_stack([xc, yc, np.ones(len(measured))])
    coeffs, *_ = np.linalg.lstsq(A, zs, rcond=None)
    residuals = zs - (coeffs[0] * xc + coeffs[1] * yc + coeffs[2])
    rank = np.linalg.matrix_rank(A)
    model = "line" if rank < 3 else "plane"
    return FocusMap(
        model=model, coeffs=coeffs,
        origin_xy_um=(x0, y0), measured=measured,
        residuals_um=residuals,
    )


def _print_focus_diagnostics(fm: FocusMap, ctx: Context) -> None:
    """Print model-aware diagnostics and extrapolation warning."""
    zs = np.array([m["zwide_um"] for m in fm.measured])
    z_range = float(zs.max() - zs.min())

    print(f"\n[step 2c] Focus model: {fm.model} ({len(fm.measured)} points)")

    if fm.model == "constant":
        print(f"  Z mean:       {zs.mean():.2f} um")

    elif fm.model == "line":
        slope = np.sqrt(fm.coeffs[0]**2 + fm.coeffs[1]**2)
        print(f"  Z range:          {z_range:.2f} um")
        print(f"  Directional slope: {np.degrees(np.arctan(slope)):+.4f} deg")
        print(f"  Max residual:     {np.max(np.abs(fm.residuals_um)):.3f} um")

    elif fm.model == "plane":
        print(f"  Z range:      {z_range:.2f} um")
        print(f"  Tilt X:       {np.degrees(np.arctan(fm.coeffs[0])):+.4f} deg")
        print(f"  Tilt Y:       {np.degrees(np.arctan(fm.coeffs[1])):+.4f} deg")
        print(f"  Max residual: {np.max(np.abs(fm.residuals_um)):.3f} um")

    elif fm.model == "spline":
        print(f"  Z range:      {z_range:.2f} um")
        print(f"  Smoothing:    {SPLINE_SMOOTHING}")
        print(f"  Max residual: {np.max(np.abs(fm.residuals_um)):.3f} um")

    if ctx.scan_field is not None:
        tile_positions = ctx.scan_field["tile_positions"]
        tile_xs = [p["x_um"] for r in tile_positions.values()
                   for p in r["positions"]]
        tile_ys = [p["y_um"] for r in tile_positions.values()
                   for p in r["positions"]]
        fx = [m["x_um"] for m in fm.measured]
        fy = [m["y_um"] for m in fm.measured]
        if (min(tile_xs) < min(fx) or max(tile_xs) > max(fx) or
                min(tile_ys) < min(fy) or max(tile_ys) > max(fy)):
            print(f"  WARNING: some tiles are outside the focus marker "
                  f"bounding box -Z values are extrapolated")
