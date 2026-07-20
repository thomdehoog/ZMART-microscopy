"""Controller-only run visualization + summary over the new pipeline data.

Everything here works at the workflow's altitude -- the frame positions the
workflow controls, the fitted :class:`~pipeline._focus_surface.FocusSurface`,
and the :func:`~pipeline.discovery.discover_targets` output -- never the
driver's opaque ``acquire`` record (whose shape is driver-defined: the Leica
adapter returns ``{"images": [...]}``; the mock returns
``{"filename": ..., "position": {...}}``). Passing the workflow-owned data
keeps this driver-agnostic.

The summary functions (:func:`summarize_run` / :func:`write_summary`) are pure
and always available. The plotting functions lazy-import ``matplotlib`` (an
optional dependency, see requirements.txt) so importing this module never
requires it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ._figsave import save_figure


def _focus_summary(focus: Any) -> dict | None:
    """Compact, JSON-safe view of a fitted FocusSurface (``None`` -> ``None``)."""
    if focus is None:
        return None
    zs = [float(m["z_um"]) for m in focus.measured]
    z_min = min(zs) if zs else None
    z_max = max(zs) if zs else None
    return {
        "model": focus.model,
        "n_points": len(focus.measured),
        "z_min_um": z_min,
        "z_max_um": z_max,
        "z_range_um": (z_max - z_min) if zs else None,
    }


def _target_stats(targets: list[dict]) -> dict:
    """Per-overview counts and area stats from ``discover_targets`` output."""
    per_overview: dict[str, int] = {}
    areas: list[float] = []
    for t in targets:
        source = t.get("source", {})
        key = str(source.get("naming_p"))
        per_overview[key] = per_overview.get(key, 0) + 1
        area = source.get("area_px")
        if area is not None:
            areas.append(float(area))
    stats: dict[str, Any] = {"targets_per_overview": per_overview}
    if areas:
        stats["area_px"] = {
            "n": len(areas),
            "min": min(areas),
            "max": max(areas),
            "mean": sum(areas) / len(areas),
        }
    return stats


def summarize_run(
    *,
    focus: Any = None,
    overview_positions: list[dict] | None = None,
    overview_records: list[dict] | None = None,
    targets: list[dict] | None = None,
) -> dict:
    """Build a JSON-serializable summary of a controller-only run.

    All inputs are optional and driver-agnostic:

    - ``focus`` -- the fitted :class:`FocusSurface` (its model + z range).
    - ``overview_positions`` -- the frame positions the overview step captured
      at (``[{"x", "y", "z"}]``); preferred count source.
    - ``overview_records`` -- the driver records ``run_overview`` returned; used
      only for the count (and ``acquisition_type`` echo) when
      ``overview_positions`` is absent.
    - ``targets`` -- the :func:`discover_targets` output.
    """
    targets = targets or []
    if overview_positions is not None:
        n_overviews = len(overview_positions)
    elif overview_records is not None:
        n_overviews = len(overview_records)
    else:
        n_overviews = 0

    summary: dict[str, Any] = {
        "n_overviews": n_overviews,
        "n_targets": len(targets),
        "focus": _focus_summary(focus),
    }
    summary.update(_target_stats(targets))
    if overview_records:
        types = sorted({str(r.get("acquisition_type")) for r in overview_records})
        summary["overview_acquisition_types"] = types
    return summary


def write_summary(summary: dict, path: Any) -> Path:
    """Write ``summary`` as pretty JSON to ``path``; return the path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return path


def plot_focus_surface(
    focus: Any,
    *,
    grid: int = 40,
    save_path: Any = None,
    show: bool = False,
):
    """Heatmap of the fitted z(x, y) over the measured bbox, points on top.

    Returns the matplotlib ``Figure``. ``save_path`` (a ``.png``) also writes
    the vector siblings via :func:`~pipeline._figsave.save_figure`.
    """
    import matplotlib

    if not show:
        matplotlib.use("Agg", force=False)
    import matplotlib.pyplot as plt
    import numpy as np

    xs = np.array([m["x_um"] for m in focus.measured], dtype=float)
    ys = np.array([m["y_um"] for m in focus.measured], dtype=float)
    zs = np.array([m["z_um"] for m in focus.measured], dtype=float)

    # Pad a degenerate (single-point / collinear) extent so imshow has area.
    def _span(a: np.ndarray) -> tuple[float, float]:
        lo, hi = float(a.min()), float(a.max())
        if hi - lo < 1e-9:
            lo, hi = lo - 1.0, hi + 1.0
        return lo, hi

    x_lo, x_hi = _span(xs)
    y_lo, y_hi = _span(ys)
    gx = np.linspace(x_lo, x_hi, grid)
    gy = np.linspace(y_lo, y_hi, grid)
    mesh_x, mesh_y = np.meshgrid(gx, gy)
    mesh_z = focus.z_at(mesh_x, mesh_y)
    mesh_z = np.asarray(mesh_z, dtype=float).reshape(mesh_x.shape)

    fig, ax = plt.subplots(figsize=(6, 5))
    im = ax.imshow(
        mesh_z,
        origin="lower",
        extent=(x_lo, x_hi, y_lo, y_hi),
        aspect="auto",
        cmap="viridis",
    )
    ax.scatter(xs, ys, c=zs, cmap="viridis", edgecolors="white", linewidths=1.0, s=60, zorder=3)
    fig.colorbar(im, ax=ax, label="focus z (um)")
    ax.set_xlabel("frame x (um)")
    ax.set_ylabel("frame y (um)")
    ax.set_title(f"focus surface ({focus.model}, {len(focus.measured)} pts)")
    fig.tight_layout()

    if save_path is not None:
        save_figure(fig, save_path)
    if not show:
        plt.close(fig)
    return fig


def plot_frame_layout(
    *,
    overview_positions: list[dict] | None = None,
    targets: list[dict] | None = None,
    focus: Any = None,
    save_path: Any = None,
    show: bool = False,
):
    """Map the run in frame coordinates: overview centers, discovered targets,
    focus points -- all on one equal-aspect, y-up frame.

    Returns the matplotlib ``Figure``. ``save_path`` (a ``.png``) also writes
    the vector siblings.
    """
    import matplotlib

    if not show:
        matplotlib.use("Agg", force=False)
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6, 6))

    if overview_positions:
        ax.scatter(
            [p["x"] for p in overview_positions],
            [p["y"] for p in overview_positions],
            marker="s",
            facecolors="none",
            edgecolors="tab:blue",
            s=90,
            label=f"overviews ({len(overview_positions)})",
        )
    if focus is not None and focus.measured:
        ax.scatter(
            [m["x_um"] for m in focus.measured],
            [m["y_um"] for m in focus.measured],
            marker="x",
            color="tab:green",
            s=70,
            label=f"focus pts ({len(focus.measured)})",
        )
    if targets:
        sources = [t.get("source", {}).get("naming_p") for t in targets]
        ax.scatter(
            [t["x"] for t in targets],
            [t["y"] for t in targets],
            c=sources if any(s is not None for s in sources) else "tab:red",
            cmap="tab10",
            marker="o",
            s=25,
            label=f"targets ({len(targets)})",
        )

    ax.set_aspect("equal", adjustable="datalim")
    ax.set_xlabel("frame x (um)")
    ax.set_ylabel("frame y (um)")
    ax.set_title("run layout (frame coordinates)")
    if ax.get_legend_handles_labels()[1]:
        ax.legend(loc="best", fontsize=8)
    fig.tight_layout()

    if save_path is not None:
        save_figure(fig, save_path)
    if not show:
        plt.close(fig)
    return fig
