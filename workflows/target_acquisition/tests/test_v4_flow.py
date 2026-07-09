"""End-to-end controller-only flow, offline.

Composes the whole v4 workflow surface against the reference mock driver and a
synchronous fake analysis engine -- no hardware, no cellpose, no
``navigator_expert``. This is the integration counterpart to the per-step unit
tests: it proves the pieces fit together in the order the notebook runs them.

    connect -> get_root/get_positions -> get_focus_points -> get/set_state -> fit_focus_surface ->
    run_overview -> build_overview_inputs -> discover_targets ->
    acquire_targets -> summarize_run / plots
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import workflow  # noqa: E402

from zmart_controller.tests.mock_driver import register_mock  # noqa: E402


class _FakeEngine:
    """Synchronous segmentation stub: canned picks per submitted overview."""

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


def test_full_controller_only_flow(tmp_path):
    register_mock()

    # 1. connect
    zmart_controller = workflow.connect("mock", output_root=tmp_path)
    try:
        assert zmart_controller.context["vendor"] == "mock"
        output_root = Path(zmart_controller.run_procedure({"name": "get_root"})["root"])
        assert output_root == tmp_path

        # 2. initial positions
        positions = zmart_controller.run_procedure({"name": "get_positions"})["positions"][:2]
        assert len(positions) == 2

        # 3. collect + reapply a state (one "state" == a selected job/settings)
        state = zmart_controller.get_state()
        zmart_controller.set_state(state)

        # 4. focus surface (measure_focus is unit-tested against a fake session;
        #    here we fit from explicit points -- the same FocusSurface object).
        focus_points = zmart_controller.run_procedure({"name": "get_focus_points"})["positions"]
        focus = workflow.fit_focus_surface(
            [
                {"x_um": focus_points[0]["x"], "y_um": focus_points[0]["y"], "z_um": 3.0},
                {"x_um": focus_points[1]["x"], "y_um": focus_points[1]["y"], "z_um": 3.4},
                {"x_um": focus_points[2]["x"], "y_um": focus_points[2]["y"], "z_um": 3.1},
            ]
        )

        # 5. overview: capture at each position, z from the surface
        overview_records = workflow.run_overview(
            zmart_controller, positions, state=state, focus=focus
        )
        assert [r["acquisition_type"] for r in overview_records] == ["overview", "overview"]
        # z came from the focus surface (plane through the fit points)
        assert overview_records[0]["position"]["z"] == focus.z_at(0.0, 0.0)

        # 6. bridge overview records -> discover_targets inputs. The mock record
        #    carries "position"; a real driver record carries "images" (paths).
        placed = workflow.with_focus_z(positions, focus)
        image_paths = [f"overview_{i}.ome.tiff" for i in range(len(overview_records))]
        overviews = workflow.build_overview_inputs(
            placed,
            image_paths,
            pixel_size_um=0.5,
            image_size_px=(100, 200),  # (H, W)
        )
        assert overviews[1]["center_frame_um"] == (120.0, 0.0)

        # 7. discover: segment each overview (fake engine), centroids -> frame
        engine = _FakeEngine(
            {
                0: [{"centroid_col_row_px": (110, 70), "area_px": 50, "mean_intensity": 12.0}],
                1: [{"centroid_col_row_px": (100, 50), "area_px": 30, "mean_intensity": 8.0}],
            }
        )
        targets = workflow.discover_targets(engine, overviews)
        assert len(targets) == 2
        # overview 0 centered at (0,0): (110-100)*0.5=+5, (70-50)*0.5=+10
        assert targets[0]["x"] == 5.0
        assert targets[0]["y"] == 10.0
        # overview 1 centered at (120,0): centroid at image centre -> (120, 0)
        assert targets[1]["x"] == 120.0
        assert targets[1]["y"] == 0.0

        # 8. acquire each target
        target_records = workflow.acquire_targets(zmart_controller, targets, focus=focus)
        assert [r["acquisition_type"] for r in target_records] == ["target", "target"]

        # 9. summary + plots
        summary = workflow.summarize_run(
            focus=focus,
            overview_positions=placed,
            overview_records=overview_records,
            targets=targets,
        )
        assert summary["n_overviews"] == 2
        assert summary["n_targets"] == 2
        assert summary["targets_per_overview"] == {"0": 1, "1": 1}
        assert summary["focus"]["model"] in {"plane", "constant", "spline"}

        out = workflow.write_summary(summary, tmp_path / "run" / "summary.json")
        assert json.loads(out.read_text()) == summary

        focus_png = tmp_path / "run" / "focus.png"
        layout_png = tmp_path / "run" / "layout.png"
        workflow.plot_focus_surface(focus, save_path=focus_png)
        workflow.plot_frame_layout(
            overview_positions=placed, targets=targets, focus=focus, save_path=layout_png
        )
        assert focus_png.exists() and layout_png.exists()
    finally:
        zmart_controller.disconnect()
