"""Controller-only run summary + plots (pipeline.viz).

Summary functions are pure/JSON; plot functions render headless (Agg) to a
tmp path and must emit the PNG + vector siblings.
"""

from __future__ import annotations

import json

import matplotlib
import pytest

matplotlib.use("Agg")

from pipeline._focus_surface import fit_focus_surface  # noqa: E402
from pipeline.viz import (  # noqa: E402
    plot_focus_surface,
    plot_frame_layout,
    summarize_run,
    write_summary,
)

_TILTED = fit_focus_surface(
    [
        {"x_um": 0.0, "y_um": 0.0, "z_um": 3.0},
        {"x_um": 10.0, "y_um": 0.0, "z_um": 4.0},
        {"x_um": 0.0, "y_um": 10.0, "z_um": 5.0},
    ]
)

_FLAT = fit_focus_surface([{"x_um": 0.0, "y_um": 0.0, "z_um": 2.0}])

_TARGETS = [
    {"x": 1.0, "y": 2.0, "source": {"naming_p": 0, "area_px": 50, "mean_intensity": 12.0}},
    {"x": 3.0, "y": 4.0, "source": {"naming_p": 0, "area_px": 70, "mean_intensity": 9.0}},
    {"x": 5.0, "y": 6.0, "source": {"naming_p": 1, "area_px": 30, "mean_intensity": 8.0}},
]

_OVERVIEW_POSITIONS = [{"x": 0.0, "y": 0.0, "z": 3.0}, {"x": 100.0, "y": 0.0, "z": 3.5}]


# --- summarize_run --------------------------------------------------------


def test_summarize_run_counts_and_focus():
    s = summarize_run(
        focus=_TILTED,
        overview_positions=_OVERVIEW_POSITIONS,
        targets=_TARGETS,
    )
    assert s["n_overviews"] == 2
    assert s["n_targets"] == 3
    assert s["focus"]["model"] == "plane"
    assert s["focus"]["n_points"] == 3
    assert s["focus"]["z_range_um"] == pytest.approx(2.0)
    assert s["targets_per_overview"] == {"0": 2, "1": 1}
    assert s["area_px"] == {"n": 3, "min": 30.0, "max": 70.0, "mean": 50.0}


def test_summarize_run_counts_from_records_when_no_positions():
    records = [{"acquisition_type": "overview"}, {"acquisition_type": "overview"}]
    s = summarize_run(overview_records=records, targets=[])
    assert s["n_overviews"] == 2
    assert s["n_targets"] == 0
    assert s["focus"] is None
    assert s["overview_acquisition_types"] == ["overview"]


def test_summarize_run_empty_is_serializable():
    s = summarize_run()
    assert s == {
        "n_overviews": 0,
        "n_targets": 0,
        "focus": None,
        "targets_per_overview": {},
    }
    json.dumps(s)  # must not raise


def test_write_summary_roundtrip(tmp_path):
    s = summarize_run(focus=_FLAT, overview_positions=_OVERVIEW_POSITIONS, targets=_TARGETS)
    out = write_summary(s, tmp_path / "sub" / "summary.json")
    assert out.exists()
    assert json.loads(out.read_text()) == s
    assert s["focus"]["model"] == "constant"


# --- plots ----------------------------------------------------------------


def _assert_siblings(png):
    assert png.exists()
    assert png.with_suffix(".svg").exists()
    assert png.with_suffix(".pdf").exists()


def test_plot_focus_surface_writes_files(tmp_path):
    png = tmp_path / "focus.png"
    fig = plot_focus_surface(_TILTED, save_path=png)
    _assert_siblings(png)
    assert fig is not None


def test_plot_focus_surface_handles_constant_single_point(tmp_path):
    # Degenerate extent (one point) must still render without raising.
    png = tmp_path / "focus_flat.png"
    plot_focus_surface(_FLAT, save_path=png)
    _assert_siblings(png)


def test_plot_frame_layout_writes_files(tmp_path):
    png = tmp_path / "layout.png"
    plot_frame_layout(
        overview_positions=_OVERVIEW_POSITIONS,
        targets=_TARGETS,
        focus=_TILTED,
        save_path=png,
    )
    _assert_siblings(png)


def test_plot_frame_layout_tolerates_empty_inputs(tmp_path):
    png = tmp_path / "empty.png"
    plot_frame_layout(save_path=png)
    _assert_siblings(png)
