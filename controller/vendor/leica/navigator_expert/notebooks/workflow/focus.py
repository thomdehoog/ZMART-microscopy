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

    def plot(self, ctx: Context) -> None:
        import matplotlib.patches as patches
        import matplotlib.pyplot as plt
        from matplotlib.cm import ScalarMappable
        from matplotlib.colors import Normalize
        from matplotlib.path import Path as MplPath
        from matplotlib.patches import PathPatch
        from mpl_toolkits.axes_grid1 import make_axes_locatable

        if ctx.scan_field is None:
            raise RuntimeError("Call read_scan_field before focus_map.plot.")

        tile_positions = ctx.scan_field["tile_positions"]
        lim = ctx.boundary_limits

        tile_data = [
            (p["x_um"], p["y_um"], r.get("tile_size_um", 0) / 2)
            for r in tile_positions.values()
            for p in r["positions"]
        ]

        ts_um = max(
            (r.get("tile_size_um") or 0) for r in tile_positions.values()
        ) if tile_positions else 0

        fig, ax = plt.subplots(figsize=(14, 10))
        fig.patch.set_facecolor("white")
        ax.set_facecolor("#f5f5f8")

        if not tile_data:
            print("[focus] No tiles to plot.")
            plt.close(fig)
            return

        tcx = [t[0] for t in tile_data]
        tcy = [t[1] for t in tile_data]
        th = [t[2] for t in tile_data]

        all_tx = ([cx - h for cx, h in zip(tcx, th)]
                  + [cx + h for cx, h in zip(tcx, th)])
        all_ty = ([cy - h for cy, h in zip(tcy, th)]
                  + [cy + h for cy, h in zip(tcy, th)])
        span = max(max(all_tx) - min(all_tx),
                   max(all_ty) - min(all_ty))

        step = span / 500 if span > 0 else 1.0
        pad = 3 * step
        gx = np.arange(min(all_tx) - pad, max(all_tx) + pad + step, step)
        gy = np.arange(min(all_ty) - pad, max(all_ty) + pad + step, step)
        GX, GY = np.meshgrid(gx, gy)
        GZ = self.interpolate_zwide(GX, GY)

        if GZ.min() == GZ.max():
            norm = Normalize(vmin=GZ.min() - 0.5, vmax=GZ.max() + 0.5)
        else:
            norm = Normalize(vmin=GZ.min(), vmax=GZ.max())
        cmap = plt.get_cmap("viridis")

        verts, codes = [], []
        for cx, cy, h in zip(tcx, tcy, th):
            x0, y0, x1, y1 = cx - h, cy - h, cx + h, cy + h
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

        for cx, cy, h in zip(tcx, tcy, th):
            ax.add_patch(patches.Rectangle(
                (cx - h, cy - h), 2 * h, 2 * h,
                linewidth=0.5, edgecolor="white",
                facecolor="none", zorder=3,
            ))

        cross = ts_um * 0.25 if ts_um else span * 0.01
        circle_r = cross * 0.6
        for m in self.measured:
            fx, fy = m["x_um"], m["y_um"]
            ax.plot([fx - cross, fx + cross], [fy, fy],
                    "-", color="#e05555", linewidth=1.2, zorder=10)
            ax.plot([fx, fx], [fy - cross, fy + cross],
                    "-", color="#e05555", linewidth=1.2, zorder=10)
            ax.add_patch(patches.Circle(
                (fx, fy), circle_r, linewidth=1.2,
                edgecolor="#e05555", facecolor="none", zorder=11,
            ))
        ax.plot([], [], "+", color="#e05555", markersize=10,
                markeredgewidth=1.5, label="Focus points")

        all_view_x = list(all_tx)
        all_view_y = list(all_ty)
        if lim:
            ax.add_patch(patches.Rectangle(
                (lim["x_min"], lim["y_min"]),
                lim["x_max"] - lim["x_min"],
                lim["y_max"] - lim["y_min"],
                linewidth=1.0, edgecolor="#aaaaaa", facecolor="none",
                linestyle=(0, (5, 4)), zorder=2,
            ))
            ax.plot([], [], ls=(0, (5, 4)), color="#aaaaaa",
                    linewidth=1.0, label="Sample boundary")
            all_view_x.extend([lim["x_min"], lim["x_max"]])
            all_view_y.extend([lim["y_min"], lim["y_max"]])

        view_span = max(max(all_view_x) - min(all_view_x),
                        max(all_view_y) - min(all_view_y))
        pad_plot = view_span * 0.05
        ax.set_xlim(min(all_view_x) - pad_plot,
                    max(all_view_x) + pad_plot)
        ax.set_ylim(min(all_view_y) - pad_plot,
                    max(all_view_y) + pad_plot)

        divider = make_axes_locatable(ax)
        cax = divider.append_axes("right", size="2%", pad=0.15)
        sm = ScalarMappable(cmap=cmap, norm=norm)
        sm.set_array([])
        plt.colorbar(sm, cax=cax, label="z-wide (um)")

        ax.set_aspect("equal")
        ax.invert_yaxis()
        ax.set_xticks([])
        ax.set_yticks([])
        ax.grid(False)
        for spine in ax.spines.values():
            spine.set_linewidth(0.8)
            spine.set_edgecolor("#cccccc")
        zs = np.array([m["zwide_um"] for m in self.measured])
        z_range = zs.max() - zs.min()
        ax.set_title(
            f"Focus: {self.model}  (range {z_range:.2f} um)",
            fontsize=13, fontweight="bold", color="#222222", pad=12,
        )
        ax.legend(loc="upper right", fontsize=9, facecolor="white",
                  edgecolor="#cccccc", labelcolor="#444444")
        plt.tight_layout()

        out_path = ctx.out_dir / "focus_map.png"
        fig.savefig(out_path, dpi=150)
        print(f"[step 3] Saved {out_path}")
        plt.show()


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

    print(f"[step 3] Focus positions ({len(focus_positions)}):")
    for i, fp in enumerate(focus_positions):
        print(f"  {i + 1}. x={fp['x_um']:.1f}  y={fp['y_um']:.1f} um")

    if not drv.strip_template(client):
        raise RuntimeError("drv.strip_template failed before AF loop.")

    try:
        ensure_job_state(ctx, cfg.af_job)

        measured: list[dict] = []
        for i, fp in enumerate(focus_positions):
            print(
                f"\n[{i + 1}/{len(focus_positions)}] "
                f"x={fp['x_um']:.0f}  y={fp['y_um']:.0f}",
                end="", flush=True,
            )
            drv.move_xy(client, fp["x_um"], fp["y_um"])
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
                print(f"[step 3] WARNING: could not restore template: {exc}")

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

    print(f"\n[step 3] Focus model: {fm.model} ({len(fm.measured)} points)")

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
