"""plot_population: what goes in, what comes out.

The conditioning is pinned on a small table; the components and the UMAP
run for real on a population small enough to be quick.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "steps"))
from plot_population import run  # noqa: E402


def _a_population(where: Path, n: int = 60) -> Path:
    """A population table as the bridge writes it: identity and place first,
    then the measured columns, one of them per-field and one mostly empty.
    Two groups of objects differ in size, shape and brightness."""
    rng = np.random.default_rng(0)
    table = where / "overview_abc123_objects.csv"
    columns = ["field", "position_label", "id", "x_um", "y_um", "area", "intensity", "r",
               "label", "centroid_row_px", "bbox_min_row_px", "bg_global_mean", "eccentricity",
               "intensity_mean", "solidity", "rarely"]
    with table.open("w", encoding="utf-8", newline="") as out:
        rows = csv.writer(out)
        rows.writerow(columns)
        for i in range(n):
            group = i % 2
            rows.writerow([
                i // 10, f"P{i // 10}", f"cell{i}", 100.0 * i, 3.0 * i, 20 + 30 * group + rng.normal(),
                500 + i, 4.0, i, 1.0, 2.0, 99.0, 0.2 + 0.5 * group + 0.01 * rng.normal(),
                400 + 300 * group + rng.normal(), 0.9 - 0.1 * group, "" if i % 5 else 1.0,
            ])
    return table


def _plotted(table: Path, kind: str, ids=None) -> dict:
    payload = {"input": {"table": str(table), "kind": kind, "ids": ids}, "metadata": {"verbose": 0}}
    return run(payload, {})["plot_population"]


def _columns(path: str) -> tuple[list[str], list[str], np.ndarray]:
    with open(path, encoding="utf-8", newline="") as source:
        rows = list(csv.reader(source))
    return rows[0], [row[0] for row in rows[1:]], np.array([[float(v) for v in row[1:]] for row in rows[1:]])


def test_only_the_measured_columns_are_plotted(tmp_path):
    """Identity, place and per-field numbers stay out, and so does a column
    measured for too few objects."""
    got = _plotted(_a_population(tmp_path), "pca")
    assert got["features"] == ["area", "eccentricity", "intensity_mean", "solidity"]
    assert got["objects"] == 60


def test_the_components_are_written_beside_the_table(tmp_path):
    """The first two components, one row an object, beside the table; the
    two groups of the population come apart along the first."""
    table = _a_population(tmp_path)
    got = _plotted(table, "pca")
    assert got["written"] == {"pca": str(table.with_name("overview_abc123_pca.csv"))}
    header, ids, values = _columns(got["written"]["pca"])
    assert header == ["id", "pc_1", "pc_2"] and ids[:3] == ["cell0", "cell1", "cell2"]
    assert abs(values[0::2, 0].mean() - values[1::2, 0].mean()) > 1.0


def test_the_population_can_be_narrowed_to_the_ids_asked(tmp_path):
    table = _a_population(tmp_path)
    asked = [f"cell{i}" for i in range(0, 60, 3)] + ["nobody"]
    got = _plotted(table, "pca", ids=asked)
    assert got["objects"] == 20
    assert _columns(got["written"]["pca"])[1] == asked[:-1]


def test_umap_lands_with_the_components_it_was_laid_out_from(tmp_path):
    pytest.importorskip("umap")
    table = _a_population(tmp_path)
    got = _plotted(table, "umap")
    assert set(got["written"]) == {"pca", "umap"}
    header, ids, first = _columns(got["written"]["umap"])
    assert header == ["id", "umap_1", "umap_2"] and len(ids) == 60
    again = _columns(_plotted(table, "umap")["written"]["umap"])[2]
    assert np.allclose(first, again), "the same population, the same plot"


def test_too_few_objects_or_an_unknown_kind_are_refused(tmp_path):
    table = _a_population(tmp_path)
    with pytest.raises(ValueError, match="at least 10"):
        _plotted(table, "pca", ids=["cell1", "cell2"])
    with pytest.raises(ValueError, match="kind"):
        _plotted(table, "tsne")
