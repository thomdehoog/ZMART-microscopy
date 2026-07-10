"""End-to-end controller-only flow, offline.

Composes the whole v4 workflow surface against the reference mock driver and a
synchronous fake analysis engine -- no hardware, no cellpose, no
``navigator_expert``. This is the integration counterpart to the per-step unit
tests: it proves the pieces fit together in the order the notebook runs them.

    connect -> get_root/get_positions -> get/set_state -> pick_focus_points ->
    measure -> run_overview -> build_overview_inputs -> discover_targets ->
    acquire_targets -> summarize_run / plots
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import pytest  # noqa: E402
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

        # 4. focus surface, the way the notebook does it: the picker pre-fills
        #    LAS X focus points, the operator (here: code) picks their own, and
        #    Measure autofocuses at each point and fits the surface. The mock's
        #    autofocus reports the current z, so the fit is a flat surface.
        picker = workflow.pick_focus_points(zmart_controller, positions)
        assert picker.points  # pre-filled from the mock's get_focus_points
        picker.points.clear()
        for x, y in [(0.0, 0.0), (100.0, 0.0), (0.0, 80.0)]:
            picker.add_point(x, y)
        focus = picker.measure()
        assert picker.require_focus() is focus
        # The mock autofocuses to wherever the stage sits (start z = 0), so
        # the fitted surface is flat at zero.
        assert focus.z_at(0.0, 0.0) == pytest.approx(0.0)

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

        # 7b. gate in the explorer, the way the notebook does (everything
        #     stays gated here — the gating logic has its own unit tests).
        explorer = workflow.explore_targets(targets, overviews)
        assert len(explorer.gated) == 2

        # 8. acquire through the gallery widget: sample from the gate, then
        #    review. The mock's records carry no image files, so the gallery
        #    shows placeholder rows — the acquisition itself is real.
        gallery = workflow.acquire_gallery(zmart_controller, explorer, overviews, focus=focus)
        target_records = gallery.acquire(2)
        assert [r["acquisition_type"] for r in target_records] == ["target", "target"]
        assert len(gallery.picked) == 2

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
