"""Regression tests for the smoke-test polish commits on try/all-four.

Each test pins one behavior introduced by a specific commit so the
visual / structural choice doesn't silently regress in a future pass.

  alpha-default          -> commit 2a2e4aa (TileStyle.alpha None)
  padding_factor effect  -> commit 958d291 (render_scan_field_panel param)
  plot_stage_envelope    -> commit 4a1923a + 46e818e (boundary + fallback)
  scatter single layer   -> commit 762f31d (collapse to selected-only)
  plot_results orphan    -> commit 9a95421 (skip picks without records)
"""
from __future__ import annotations

from pathlib import Path
from unittest import mock

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


# ─── alpha-default ────────────────────────────────────────────────


def test_tile_style_alpha_defaults_to_none():
    """TileStyle.alpha=None lets the rgba face's own alpha govern.
    A default of 1.0 silently overrides 0.25-alpha fills and kills
    tile-overlap visibility in plot_scan_field.
    """
    from workflow.visualize import TileStyle

    s = TileStyle(facecolor="none", edgecolor="white")
    assert s.alpha is None


# ─── padding_factor effect ────────────────────────────────────────


def test_render_scan_field_panel_padding_factor_widens_axes():
    """A larger padding_factor must produce wider xlim than the default."""
    from workflow.visualize import render_scan_field_panel

    scan_field = {
        "n_tiles": 1,
        "tile_positions": {
            "0": {
                "tile_size_um": 100.0,
                "positions": [{"row": 0, "col": 0, "x_um": 0.0, "y_um": 0.0}],
            },
        },
    }

    fig1, ax1 = plt.subplots()
    render_scan_field_panel(ax1, scan_field, None, padding_factor=0.05)
    xlim_default = ax1.get_xlim()
    plt.close(fig1)

    fig2, ax2 = plt.subplots()
    render_scan_field_panel(ax2, scan_field, None, padding_factor=0.20)
    xlim_wide = ax2.get_xlim()
    plt.close(fig2)

    span_default = xlim_default[1] - xlim_default[0]
    span_wide = xlim_wide[1] - xlim_wide[0]
    assert span_wide > span_default


# ─── plot_stage_envelope ──────────────────────────────────────────


def _envelope_ctx(out_dir: Path, *, boundary_limits):
    ctx = mock.MagicMock()
    ctx.out_dir = out_dir
    ctx.boundary_limits = boundary_limits
    return ctx


def test_plot_stage_envelope_with_boundary(tmp_path):
    """Happy path: ctx.boundary_limits set -> draw it, no driver call."""
    from workflow.template import plot_stage_envelope
    import navigator_expert.driver as drv

    boundary = {"x_min": 0.0, "x_max": 1000.0, "y_min": 0.0, "y_max": 800.0}
    ctx = _envelope_ctx(tmp_path, boundary_limits=boundary)

    with mock.patch.object(drv, "get_stage_limits") as get_limits:
        plot_stage_envelope(ctx)
        # Boundary was provided -> no driver fallback call
        get_limits.assert_not_called()

    assert (tmp_path / "stage_envelope.png").exists()


def test_plot_stage_envelope_falls_back_to_driver(tmp_path):
    """Deferred path: ctx.boundary_limits=None -> drv.get_stage_limits().
    Must not raise; must produce a figure using the driver-provided
    envelope.
    """
    from workflow.template import plot_stage_envelope
    import navigator_expert.driver as drv

    ctx = _envelope_ctx(tmp_path, boundary_limits=None)
    physical = {"x_min": -500.0, "x_max": 500.0, "y_min": -400.0, "y_max": 400.0}

    with mock.patch.object(drv, "get_stage_limits", return_value=physical) as get_limits:
        plot_stage_envelope(ctx)
        get_limits.assert_called_once()

    assert (tmp_path / "stage_envelope.png").exists()


# ─── scatter single layer ─────────────────────────────────────────


def test_scatter_layers_is_selected_only():
    """_LAYERS collapsed to one entry (Selected). Any future addition
    would re-introduce the visual noise we deliberately removed.
    """
    from workflow.visualize import _LAYERS

    assert len(_LAYERS) == 1
    assert _LAYERS[0].key == "selected"
    assert _LAYERS[0].label == "Selected"


# ─── plot_results orphan-pick skip ────────────────────────────────


def test_plot_results_skips_picks_without_records(tmp_path):
    """Picks without a matching TargetRecord must NOT plot as 'acquired'.
    The pre-fix behavior silently bucketed orphan picks into the green
    'acquired' category, inflating the on-field count.
    """
    from workflow.overview import Pick, Picks
    from workflow.summary import plot_results
    from workflow.target import TargetRecord

    # Three picks, only one has a record (success). Two are orphans.
    picks_items = [
        Pick(
            pick_id=("0", 0, 0, label),
            tile_stage_xy_um=(0.0, 0.0),
            tile_zwide_um=0.0,
            source_pixel_size_um=(1.0, 1.0),
            source_image_size_px=(100, 100),
            centroid_col_row_px=(50.0, 50.0),
            bbox_px=(0, 0, 10, 10),
            bbox_um=(10.0, 10.0),
            area_px=100,
            eccentricity=0.5,
            mean_intensity=100.0,
            cell_source_stage_xy_um=(float(label) * 10.0, 0.0),
        )
        for label in (1, 2, 3)
    ]
    picks = Picks(items=picks_items)
    records = [
        TargetRecord(
            pick_id=("0", 0, 0, 1),
            cell_source_stage_xy_um=(10.0, 0.0),
            source_zwide_um=0.0,
            target_stage_xy_um=(10.0, 0.0),
            target_zwide_um=0.0,
            target_zoom=None,
            target_pixel_size_um=0.5,
            tif_path=None,
            success=True,
            error=None,
        ),
    ]

    ctx = mock.MagicMock()
    ctx.out_dir = tmp_path
    ctx.scan_field = {
        "n_tiles": 1,
        "tile_positions": {
            "0": {"tile_size_um": 100.0,
                  "positions": [{"row": 0, "col": 0, "x_um": 0.0, "y_um": 0.0}]},
        },
    }
    ctx.boundary_limits = None
    focus_map = mock.MagicMock()

    captured: list[dict] = []
    real_scatter = matplotlib.axes.Axes.scatter

    def capturing_scatter(self, x, y, *args, **kwargs):
        captured.append({"x": list(x), "color": kwargs.get("c")})
        return real_scatter(self, x, y, *args, **kwargs)

    with mock.patch.object(matplotlib.axes.Axes, "scatter", capturing_scatter):
        plot_results(ctx, focus_map, picks, records)

    acquired_calls = [c for c in captured if c["color"] == "#22aa22"]
    assert acquired_calls, "expected an 'acquired' scatter call (green)"
    n_acquired = sum(len(c["x"]) for c in acquired_calls)
    assert n_acquired == 1, (
        f"expected 1 acquired marker (one record with success=True), "
        f"got {n_acquired}. Orphan picks must not appear as acquired."
    )
