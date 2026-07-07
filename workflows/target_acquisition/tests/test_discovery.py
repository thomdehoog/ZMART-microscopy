"""discover_targets: reuse the analysis engine, convert centroids -> frame targets.

The analysis engine is stubbed synchronously (the real one needs cellpose); we
test the wiring (submitted jobs) and the pixel->frame conversion of its results.
"""

from __future__ import annotations

import pytest
from pipeline.discovery import discover_targets


class _FakeEngine:
    """Synchronous stand-in: segmentation returns canned picks per submitted job."""

    def __init__(self, picks_by_index):
        self.picks_by_index = picks_by_index
        self.jobs = []
        self._results = []

    def submit(self, queue, job):
        self.jobs.append(job)
        self._results.append(
            {"input": job, "pick_targets": {"picks": self.picks_by_index.get(job["naming_p"], [])}}
        )

    def status(self, queue):
        return {"pending": 0, "running": 0, "failures": []}

    def results(self, queue):
        out, self._results = self._results, []
        return out


def _ov(image_path, center, pixel_size, shape_hw):
    return {
        "image_path": image_path,
        "center_frame_um": center,
        "pixel_size_um": pixel_size,
        "image_size_px": shape_hw,
    }


def test_single_cell_centroid_maps_to_frame():
    engine = _FakeEngine(
        {0: [{"centroid_col_row_px": (110, 70), "area_px": 50, "mean_intensity": 12.0}]}
    )
    overviews = [_ov("ov0.tif", (1000.0, 2000.0), 0.5, (100, 200))]  # (H, W)

    targets = discover_targets(engine, overviews)

    assert len(targets) == 1
    # (110-100)*0.5 = +5 ; (70-50)*0.5 = +10
    assert targets[0]["x"] == pytest.approx(1005.0)
    assert targets[0]["y"] == pytest.approx(2010.0)
    assert targets[0]["source"]["area_px"] == 50
    # engine fed a valid segmentation job
    assert engine.jobs[0]["image_path"] == "ov0.tif"
    assert engine.jobs[0]["image_to_stage"] == [[0.5, 0.0], [0.0, 0.5]]
    assert engine.jobs[0]["feature"] == "area"


def test_multiple_overviews_and_cells():
    engine = _FakeEngine(
        {
            0: [{"centroid_col_row_px": (100, 50)}],
            1: [{"centroid_col_row_px": (100, 50)}, {"centroid_col_row_px": (150, 50)}],
        }
    )
    overviews = [
        _ov("a", (0.0, 0.0), 1.0, (100, 200)),
        _ov("b", (500.0, 0.0), 1.0, (100, 200)),
    ]

    targets = discover_targets(engine, overviews)

    assert sorted(t["x"] for t in targets) == [0.0, 500.0, 550.0]
    assert all(t["y"] == 0.0 for t in targets)


def test_no_cells_returns_empty():
    engine = _FakeEngine({0: []})
    assert discover_targets(engine, [_ov("a", (0.0, 0.0), 1.0, (100, 200))]) == []
