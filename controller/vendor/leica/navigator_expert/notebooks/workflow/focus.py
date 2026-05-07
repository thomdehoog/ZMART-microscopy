"""focus.py -- Step 3: build a z-wide focus map.

At each focus marker, move XY, run the AF job, read back z-wide,
fit a plane. The fitted plane is used by Step 4 to command z-wide
per tile.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

import navigator_expert.driver as drv
from navigator_expert.driver.commands import acquire as drv_acquire
from navigator_expert.driver.scanning_templates import (
    TEMPLATE_BASE,
    TEMPLATE_XML,
)

from .context import Context
from ._job_state import ensure_job_state


@dataclass
class FocusMap:
    coeffs: np.ndarray
    measured: list[dict]
    residuals_um: np.ndarray

    def interpolate_zwide(self, x, y):
        return self.coeffs[0] * x + self.coeffs[1] * y + self.coeffs[2]

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
            f"Focus Plane  (range {z_range:.2f} um)",
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
    """Step 3: run AF at each focus marker, fit a z-wide plane.

    Reads focus/autofocus positions from the template, strips the
    template, selects the AF job, moves to each marker, acquires,
    reads back the resulting z-wide, then fits a plane.

    Optionally restores the template after AF (cfg.restore_template_after_af).
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

    xs = np.array([m["x_um"] for m in measured])
    ys = np.array([m["y_um"] for m in measured])
    zs = np.array([m["zwide_um"] for m in measured])
    A = np.column_stack([xs, ys, np.ones(len(measured))])
    coeffs, *_ = np.linalg.lstsq(A, zs, rcond=None)
    residuals = zs - (coeffs[0] * xs + coeffs[1] * ys + coeffs[2])

    fm = FocusMap(coeffs=coeffs, measured=measured, residuals_um=residuals)

    print(f"\n[step 3] Focus plane (z-wide):")
    print(f"  Z range:      {zs.max() - zs.min():.2f} um")
    print(f"  Tilt X:       {np.degrees(np.arctan(coeffs[0])):+.4f} deg")
    print(f"  Tilt Y:       {np.degrees(np.arctan(coeffs[1])):+.4f} deg")
    print(f"  Max residual: {np.max(np.abs(residuals)):.3f} um")

    return fm
