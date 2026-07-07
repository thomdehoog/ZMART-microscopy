"""Regression tests for the visualize / template polish behaviors.

Each test pins one behavior so a future refactor cannot silently
revert it:

  TileStyle.alpha default + dispatch
      Pins that an rgba face color with an embedded alpha channel
      survives matplotlib's Patch construction inside
      render_scan_field_panel. Required for tile-overlap visibility
      in plot_scan_field.

  render_scan_field_panel padding_factor
      Pins that the parameter scales axis padding linearly. A pass
      that hardcoded 0.05 again would fail this test.

  plot_stage_envelope dispatch (stage limits set + driver fallback)
      Pins that the function uses ctx.stage_limits when set and
      falls back to drv.get_stage_limits() when None. The fallback
      keeps Step 2a working on the deferred-limits path.

  scatter single-layer invariant
      Pins that _LAYERS contains exactly one structural entry keyed
      "selected". Re-adding near-border / below / qualifying layers
      would fail this test.

  plot_results orphan-pick skip
      Pins that picks without a matching TargetRecord do not appear
      in the "acquired" category, so the on-field marker count never
      exceeds len(records).
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

# ─── TileStyle.alpha behavior ─────────────────────────────────────


def test_tile_style_alpha_default_and_rgba_passthrough():
    """TileStyle.alpha=None lets the rgba face's own alpha govern the
    rendered patch. The previous default of 1.0 silently overrode
    0.25-alpha fills and killed tile-overlap visibility.

    Verified end-to-end: build a TileStyle with an rgba face that has
    alpha=0.25, render through render_scan_field_panel, and confirm
    the resulting Rectangle patch's alpha is None (so matplotlib
    composites with the rgba's own alpha channel rather than
    overriding it).
    """
    from pipeline.retired.visualize import TileStyle, render_scan_field_panel

    # Default-construction sanity
    assert TileStyle(facecolor="none", edgecolor="white").alpha is None

    # Dispatch behavior: a rgba face must reach matplotlib with
    # alpha kwarg == None so the channel survives.
    scan_field = {
        "n_tiles": 1,
        "tile_positions": {
            "0": {
                "tile_size_um": 100.0,
                "positions": [{"row": 0, "col": 0, "x_um": 0.0, "y_um": 0.0}],
            },
        },
    }
    tid = ("0", 0, 0)
    rgba_face = (0.4, 0.6, 0.8, 0.25)
    styles = {tid: TileStyle(facecolor=rgba_face, edgecolor="black")}

    fig, ax = plt.subplots()
    try:
        render_scan_field_panel(ax, scan_field, None, tile_styles=styles)
        # The tile rectangle is the first patch added (boundary is None).
        rect = ax.patches[0]
        assert rect.get_alpha() is None, (
            "TileStyle.alpha=None must reach matplotlib as alpha=None "
            "so the rgba face's own alpha channel survives. "
            f"Got alpha={rect.get_alpha()!r}."
        )
    finally:
        plt.close(fig)


# ─── padding_factor effect ────────────────────────────────────────


def test_render_scan_field_panel_padding_factor_scales_linearly():
    """padding_factor must scale axis padding linearly (not just monotonic).
    A broken implementation that doubled padding regardless of input
    would pass a "greater than" check; the ratio assertion catches it.
    """
    from pipeline.retired.visualize import render_scan_field_panel

    tile_size = 100.0
    scan_field = {
        "n_tiles": 1,
        "tile_positions": {
            "0": {
                "tile_size_um": tile_size,
                "positions": [{"row": 0, "col": 0, "x_um": 0.0, "y_um": 0.0}],
            },
        },
    }

    fig1, ax1 = plt.subplots()
    render_scan_field_panel(ax1, scan_field, None, padding_factor=0.05)
    span_default = ax1.get_xlim()[1] - ax1.get_xlim()[0]
    plt.close(fig1)

    fig2, ax2 = plt.subplots()
    render_scan_field_panel(ax2, scan_field, None, padding_factor=0.20)
    span_wide = ax2.get_xlim()[1] - ax2.get_xlim()[0]
    plt.close(fig2)

    # Span = tile_size + 2 * padding. Padding-only ratio = 0.20 / 0.05 = 4.
    padding_default = (span_default - tile_size) / 2
    padding_wide = (span_wide - tile_size) / 2
    assert padding_default > 0
    ratio = padding_wide / padding_default
    assert abs(ratio - 4.0) < 1e-6, (
        f"padding_factor must scale linearly: 0.20 / 0.05 = 4x. Got ratio={ratio:.3f}."
    )


# ─── plot_stage_envelope dispatch ─────────────────────────────────


def _envelope_ctx(out_dir: Path, *, stage_limits):
    ctx = mock.MagicMock()
    ctx.out_dir = out_dir
    ctx.stage_limits = stage_limits
    ctx.stage_limits_source = "test" if stage_limits is not None else None
    # plot_stage_envelope saves into logs_dir("initialization") and is
    # @_logged-decorated (tees console output into the same dir) --
    # point logs_dir at the real tmp dir so both savefig and the tee
    # have a real path to write to.
    ctx.run.layout.logs_dir.return_value = out_dir
    return ctx


def test_plot_stage_envelope_with_stage_limits(tmp_path, monkeypatch):
    """Happy path: ctx.stage_limits set -> drawn directly, no
    driver fallback call.
    """
    monkeypatch.setattr(plt, "show", lambda *a, **k: None)
    import navigator_expert as drv
    from pipeline.retired.template import plot_stage_envelope

    boundary = {"x_min": 0.0, "x_max": 1000.0, "y_min": 0.0, "y_max": 800.0}
    ctx = _envelope_ctx(tmp_path, stage_limits=boundary)

    with mock.patch.object(drv, "get_stage_limits") as get_limits:
        plot_stage_envelope(ctx)
        get_limits.assert_not_called()

    assert (tmp_path / "stage_envelope.png").exists()


def test_plot_stage_envelope_falls_back_to_driver(tmp_path, monkeypatch):
    """Fallback path: ctx.stage_limits=None -> drv.get_stage_limits()
    is called and its return value is used as the envelope. The
    function must not raise on this path.
    """
    monkeypatch.setattr(plt, "show", lambda *a, **k: None)
    import navigator_expert as drv
    from pipeline.retired.template import plot_stage_envelope

    ctx = _envelope_ctx(tmp_path, stage_limits=None)
    physical = {"x_min": -500.0, "x_max": 500.0, "y_min": -400.0, "y_max": 400.0}

    with mock.patch.object(drv, "get_stage_limits", return_value=physical) as get_limits:
        plot_stage_envelope(ctx)
        get_limits.assert_called_once()

    assert (tmp_path / "stage_envelope.png").exists()


# ─── scatter two-layer invariant ─────────────────────────────────


def test_plot_scan_field_uses_portrait_stage_limit_aspect(tmp_path, monkeypatch):
    """A portrait stage envelope should produce a portrait Step 2b figure."""
    monkeypatch.setattr(plt, "show", lambda *a, **k: None)
    from pipeline.retired.template import plot_scan_field

    created_sizes = []
    original_figure = plt.figure

    def _capture_figure(*args, **kwargs):
        fig = original_figure(*args, **kwargs)
        created_sizes.append(tuple(fig.get_size_inches()))
        return fig

    monkeypatch.setattr(plt, "figure", _capture_figure)

    ctx = _envelope_ctx(
        tmp_path,
        stage_limits={
            "x_min": 0.0,
            "x_max": 12000.0,
            "y_min": 0.0,
            "y_max": 18000.0,
        },
    )
    ctx.scan_field = {
        "template_data": {
            "visualization_data": {"tile_colors": {}},
            "focus_points": [],
            "autofocus_points": [],
        },
        "tile_positions": {
            "0": {
                "job_name": "Overview",
                "tile_size_um": 1000.0,
                "positions": [
                    {"row": 0, "col": 0, "x_um": 5000.0, "y_um": 8000.0},
                ],
            },
        },
        "n_tiles": 1,
    }

    try:
        plot_scan_field(ctx)
        assert created_sizes
        width, height = created_sizes[0]
        assert height > width
    finally:
        plt.close("all")


def test_focus_map_uses_portrait_stage_limit_aspect(tmp_path, monkeypatch):
    """Step 2c uses the same stage-envelope aspect as Steps 2a/2b."""
    monkeypatch.setattr(plt, "show", lambda *a, **k: None)
    import numpy as np
    from pipeline.retired.focus import FocusMap

    created_sizes = []
    original_figure = plt.figure

    def _capture_figure(*args, **kwargs):
        fig = original_figure(*args, **kwargs)
        created_sizes.append(tuple(fig.get_size_inches()))
        return fig

    monkeypatch.setattr(plt, "figure", _capture_figure)

    ctx = _envelope_ctx(
        tmp_path,
        stage_limits={
            "x_min": 0.0,
            "x_max": 12000.0,
            "y_min": 0.0,
            "y_max": 18000.0,
        },
    )
    ctx.scan_field = {
        "tile_positions": {
            "0": {
                "job_name": "Overview",
                "tile_size_um": 1000.0,
                "positions": [
                    {"row": 0, "col": 0, "x_um": 5000.0, "y_um": 8000.0},
                ],
            },
        },
        "n_tiles": 1,
    }
    focus_map = FocusMap(
        model="constant",
        coeffs=np.array([0.0, 0.0, 42.0]),
        origin_xy_um=(0.0, 0.0),
        measured=[{"x_um": 5000.0, "y_um": 8000.0, "zwide_um": 42.0}],
        residuals_um=np.array([0.0]),
    )

    try:
        focus_map.plot(ctx)
        assert created_sizes
        width, height = created_sizes[0]
        assert height > width
    finally:
        plt.close("all")


def test_stage_limit_update_writes_loads_and_applies_current(monkeypatch):
    """The workflow updates limits current through the driver before use."""
    from pipeline.retired import template as template_mod

    ctx = mock.MagicMock()
    stage_um = {
        "x": [10.0, 20.0],
        "y": [30.0, 40.0],
        "z_galvo": [-2.0, 2.0],
        "z_wide": [0.0, 100.0],
    }
    loaded_cfg = {"stage_um": stage_um}
    active = {
        "x_min": 10.0,
        "x_max": 20.0,
        "y_min": 30.0,
        "y_max": 40.0,
        "z_galvo_min": -2.0,
        "z_galvo_max": 2.0,
        "z_wide_min": 0.0,
        "z_wide_max": 100.0,
    }
    calls = []

    def _write(payload, *, source):
        calls.append(("write", payload, source))

    def _load(*, limits_path=None):
        calls.append(("load", limits_path))
        return loaded_cfg

    def _apply(cfg):
        calls.append(("apply", cfg))

    monkeypatch.setattr(template_mod.drv, "write_stage_limits_config", _write)
    monkeypatch.setattr(template_mod.drv, "load_stage_config", _load)
    monkeypatch.setattr(template_mod.drv, "apply_stage_limits_from_config", _apply)
    monkeypatch.setattr(template_mod.drv, "get_stage_limits", lambda: active)

    current_path = object()
    monkeypatch.setattr(
        template_mod.drv,
        "current_stage_limits_path",
        lambda: current_path,
    )

    result = template_mod._write_and_apply_stage_limits(
        ctx,
        stage_um,
        source=template_mod.drv.LIMITS_SOURCE_CFG_FALLBACK,
    )

    assert result == active
    assert ctx.stage_config == loaded_cfg
    assert ctx.stage_limits == active
    assert calls == [
        ("write", stage_um, template_mod.drv.LIMITS_SOURCE_CFG_FALLBACK),
        ("load", current_path),
        ("apply", loaded_cfg),
    ]


def _template_ctx(tmp_path: Path):
    ctx = mock.MagicMock()
    ctx.client = object()
    ctx.templates_dir = tmp_path
    return ctx


def test_read_scan_field_geometry_without_tiles_explains_lifecycle(
    tmp_path,
    monkeypatch,
):
    """A geometry without grid counts still needs an operator action."""
    from pipeline.retired import template as template_mod

    ctx = _template_ctx(tmp_path)
    monkeypatch.setattr(
        template_mod.drv,
        "save_experiment",
        lambda *a, **k: {"success": True},
    )
    monkeypatch.setattr(
        template_mod.drv,
        "parse_scan_positions",
        lambda *a, **k: {
            "geometries": {"g1": {"type": "Rectangle"}},
            "acquisition_positions": {},
        },
    )

    with pytest.raises(RuntimeError) as excinfo:
        template_mod.read_scan_field(ctx)

    message = str(excinfo.value).lower()
    assert "no tile positions" in message
    assert "matrixdata grid counts" in message
    assert "scan-field grid count is set" in message


def test_read_scan_field_empty_template_explains_lifecycle(
    tmp_path,
    monkeypatch,
):
    """An empty template points the operator to the same Step 2 action."""
    from pipeline.retired import template as template_mod

    ctx = _template_ctx(tmp_path)
    monkeypatch.setattr(
        template_mod.drv,
        "save_experiment",
        lambda *a, **k: {"success": True},
    )
    monkeypatch.setattr(
        template_mod.drv,
        "parse_scan_positions",
        lambda *a, **k: {"geometries": {}, "acquisition_positions": {}},
    )

    with pytest.raises(RuntimeError) as excinfo:
        template_mod.read_scan_field(ctx)

    message = str(excinfo.value).lower()
    assert "no tile positions" in message
    assert "draw after prepare_template" in message
    assert "set the scan-field grid" in message


def test_show_template_state_reports_lifecycle_fields(
    tmp_path,
    monkeypatch,
    capsys,
):
    """show_template_state is a diagnostic view, not a parser fallback."""
    from pipeline.retired import template as template_mod
    from pipeline.retired.template import show_template_state

    ctx = _template_ctx(tmp_path)
    monkeypatch.setattr(
        template_mod.drv,
        "save_experiment",
        lambda *a, **k: {"success": True},
    )
    monkeypatch.setattr(
        template_mod.drv,
        "parse_scan_positions",
        lambda *a, **k: {
            "geometries": {"g1": {}, "g2": {}},
            "acquisition_positions": {
                "r1": {"positions": [{"row": 0}, {"row": 1}]},
                "r2": {"positions": [{"row": 0}]},
            },
        },
    )
    monkeypatch.setattr(template_mod, "get_template_state", lambda _p: "stripped")

    report = show_template_state(ctx)
    out = capsys.readouterr().out

    assert report == {
        "state": "stripped",
        "geometries": 2,
        "tile_positions": 3,
    }
    assert "[template] state: stripped" in out
    assert "[template] geometries: 2" in out
    assert "[template] tile positions: 3" in out


def test_scatter_layers_other_then_selected():
    """_LAYERS is the structural invariant for the scatter: two entries,
    "other" (gray background) drawn first, then "selected" (red) on top.
    """
    from pipeline.retired.visualize import _LAYERS

    assert len(_LAYERS) == 2
    assert _LAYERS[0].key == "other"
    assert _LAYERS[1].key == "selected"
    assert _LAYERS[0].zorder < _LAYERS[1].zorder


# ─── plot_results orphan-pick skip ────────────────────────────────


def test_plot_results_skips_picks_without_records(tmp_path, monkeypatch):
    """Picks without a matching TargetRecord must NOT plot as 'acquired'.
    The pre-fix code silently bucketed orphan picks into the "acquired"
    category, inflating the on-field marker count.

    Filters scatter calls by label="acquired" (the dict key in
    plot_results' categories) rather than by hex color, so the test
    survives palette changes.
    """
    monkeypatch.setattr(plt, "show", lambda *a, **k: None)
    from pipeline.retired.overview import Pick
    from pipeline.retired.selection import Picks
    from pipeline.retired.summary import plot_results
    from pipeline.retired.target import TargetRecord

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
            "0": {
                "tile_size_um": 100.0,
                "positions": [{"row": 0, "col": 0, "x_um": 0.0, "y_um": 0.0}],
            },
        },
    }
    ctx.stage_limits = None
    focus_map = mock.MagicMock()

    captured: list[dict] = []
    real_scatter = matplotlib.axes.Axes.scatter

    def capturing_scatter(self, x, y, *args, **kwargs):
        captured.append({"x": list(x), "label": kwargs.get("label")})
        return real_scatter(self, x, y, *args, **kwargs)

    with mock.patch.object(matplotlib.axes.Axes, "scatter", capturing_scatter):
        plot_results(ctx, focus_map, picks, records)

    # plot_results uses label=f"{key} ({n})", e.g. "acquired (1)".
    # Match by prefix so the test doesn't couple to the count.
    acquired_calls = [
        c for c in captured if isinstance(c["label"], str) and c["label"].startswith("acquired")
    ]
    assert acquired_calls, "expected at least one 'acquired' scatter call"
    n_acquired = sum(len(c["x"]) for c in acquired_calls)
    assert n_acquired == 1, (
        f"expected 1 acquired marker (one record with success=True), "
        f"got {n_acquired}. Orphan picks must not appear as acquired."
    )
