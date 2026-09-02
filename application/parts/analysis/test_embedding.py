"""The conditioning the map stands on, pinned without umap installed.

`feature_matrix` is where selection, imputation, and scaling live, exactly so
these tests can hold them still on any machine; the one test that draws a
real map skips itself where umap is absent.
"""

from __future__ import annotations

import numpy as np
import pytest

from application.parts.analysis import embedding


def a_cell(an_id: str, **features) -> dict:
    return {"id": an_id, "features": features}


class TestWanted:
    def test_identity_and_position_stay_out(self):
        for name in (
            "label", "bbox_min_row_px", "centroid_col_px",
            "stage_x_um", "stage_y_um", "bg_global_mean", "bg_global_mean_c1",
        ):
            assert not embedding.wanted(name)

    def test_measurements_go_in(self):
        for name in ("area", "intensity_mean_c1", "lbp_entropy", "nn_distance"):
            assert embedding.wanted(name)


class TestFeatureMatrix:
    def test_one_scaled_row_per_cell_in_order(self):
        cells = [a_cell(f"c{i}", area=float(i), glow=float(-i)) for i in range(8)]
        matrix, ids, columns = embedding.feature_matrix(cells)
        assert ids == [f"c{i}" for i in range(8)]
        assert columns == ["area", "glow"]
        assert matrix.shape == (8, 2)
        # Robustly scaled: each kept column's median sits at zero.
        assert np.allclose(np.median(matrix, axis=0), 0.0)

    def test_left_out_columns_never_enter(self):
        cells = [
            a_cell(f"c{i}", area=float(i), label=float(i), stage_x_um=float(i))
            for i in range(6)
        ]
        _, _, columns = embedding.feature_matrix(cells)
        assert columns == ["area"]

    def test_the_odd_missing_value_takes_the_median(self):
        cells = [a_cell(f"c{i}", area=float(i)) for i in range(9)]
        cells.append(a_cell("c9", area=float("nan")))
        matrix, _, columns = embedding.feature_matrix(cells)
        assert columns == ["area"]
        assert np.isfinite(matrix).all()

    def test_a_mostly_missing_column_is_dropped(self):
        cells = [a_cell(f"c{i}", area=float(i)) for i in range(10)]
        for cell in cells[:6]:
            cell["features"]["patchy"] = float("nan")
        for cell in cells[6:]:
            cell["features"]["patchy"] = 1.0
        _, _, columns = embedding.feature_matrix(cells)
        assert columns == ["area"]

    def test_a_constant_column_says_nothing_and_goes(self):
        cells = [a_cell(f"c{i}", area=float(i), flat=7.0) for i in range(6)]
        _, _, columns = embedding.feature_matrix(cells)
        assert columns == ["area"]

    def test_an_outlier_does_not_own_the_scale(self):
        # Robust scaling: one wild value inflates a std-based scale ~30x,
        # while the IQR of the ordinary cells holds the scale steady.
        ordinary = [a_cell(f"c{i}", glow=float(i % 10)) for i in range(30)]
        wild = ordinary + [a_cell("c30", glow=10_000.0)]
        scaled_ordinary, _, _ = embedding.feature_matrix(ordinary)
        scaled_wild, _, _ = embedding.feature_matrix(wild)
        spread_ordinary = np.subtract(*np.percentile(scaled_ordinary[:, 0], [75, 25]))
        spread_wild = np.subtract(*np.percentile(scaled_wild[:30, 0], [75, 25]))
        assert spread_wild == pytest.approx(spread_ordinary, rel=0.2)


class TestUmapEmbedding:
    def test_too_few_cells_is_a_sentence_not_a_map(self):
        cells = [a_cell(f"c{i}", area=float(i)) for i in range(3)]
        with pytest.raises(RuntimeError, match="at least"):
            embedding.umap_embedding(cells)

    def test_no_usable_column_is_a_sentence_not_a_map(self):
        cells = [a_cell(f"c{i}", flat=1.0) for i in range(12)]
        with pytest.raises(RuntimeError, match="feature column"):
            embedding.umap_embedding(cells)

    def test_the_map_answers_every_cell_and_repeats_itself(self):
        pytest.importorskip("umap")
        rng = np.random.default_rng(7)
        cells = [
            a_cell(
                f"c{i}",
                area=float(rng.normal(100 if i % 2 else 400, 10)),
                glow=float(rng.normal(0.2 if i % 2 else 0.8, 0.05)),
                texture=float(rng.normal(0, 1)),
            )
            for i in range(40)
        ]
        first = embedding.umap_embedding(cells)
        assert set(first) == {f"c{i}" for i in range(40)}
        assert all(np.isfinite(at).all() and len(at) == 2 for at in first.values())
        # The seed is pinned: the same population gets the same map.
        again = embedding.umap_embedding(cells)
        assert first == again


class TestApart:
    """The map is drawn in another process, so the bridge stays answerable.

    Measured on the operator's PC with 4010 cells: the map takes 25 s on
    first use and 12 s warm, and while it runs in the bridge's own process
    the picture server sharing that process answers in 365 ms instead of
    3 ms, up to 700 ms -- and past its one-second budget under the real
    run's load, which the operator saw as a viewer error at Step 8.
    """

    def test_work_sent_apart_runs_in_another_process(self):
        import os

        assert embedding.apart(os.getpid) != os.getpid()

    def test_what_comes_back_is_what_the_work_returned(self):
        assert embedding.apart(sorted, [3, 1, 2]) == [1, 2, 3]

    def test_a_failure_apart_is_the_same_sentence_here(self):
        with pytest.raises(RuntimeError, match="only 2 cells"):
            embedding.in_another_process([a_cell("a", area=1.0), a_cell("b", area=2.0)])

    def test_the_map_drawn_apart_is_the_map(self):
        pytest.importorskip("umap")
        rng = np.random.default_rng(7)
        cells = [
            a_cell(f"c{i}", area=float(rng.normal(100 if i % 2 else 400, 10)),
                   glow=float(rng.normal(0.2 if i % 2 else 0.8, 0.05)))
            for i in range(40)
        ]
        assert embedding.in_another_process(cells) == embedding.umap_embedding(cells)
