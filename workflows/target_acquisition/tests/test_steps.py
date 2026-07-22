"""Controller-only step functions: connect, load_positions, overview, targets."""

from __future__ import annotations

import json

import pytest
from workflow._focus_surface import fit_focus_surface
from workflow.steps import (
    acquire_targets,
    connect,
    hijack_if_simulating,
    load_analysis_engine,
    load_positions,
    overview_inputs_from_records,
    preflight_analysis_engine,
    run_overview,
    with_focus_z,
    write_run_report,
)

from zmart_controller.tests.mock_driver import register_mock

_TILTED = fit_focus_surface(
    [
        {"x_um": 0, "y_um": 0, "z_um": 3.0},
        {"x_um": 10, "y_um": 0, "z_um": 4.0},
        {"x_um": 0, "y_um": 10, "z_um": 5.0},
    ]
)


@pytest.fixture
def mic():
    register_mock()
    session = connect("mock")
    yield session
    session.disconnect()


def test_connect_selects_vendor_and_sets_output_root(tmp_path):
    register_mock()
    session = connect("mock", output_root=tmp_path)
    assert session.context["vendor"] == "mock"
    session.disconnect()


def test_connect_unknown_vendor_raises():
    with pytest.raises(ValueError, match="no registered instrument"):
        connect("does-not-exist")


def test_load_positions_reads_json(tmp_path):
    path = tmp_path / "positions.json"
    path.write_text(json.dumps([{"x": 1, "y": 2}, {"x": 3, "y": 4, "z": 5}]), encoding="utf-8")
    assert load_positions(path) == [{"x": 1.0, "y": 2.0}, {"x": 3.0, "y": 4.0, "z": 5.0}]


def test_load_analysis_engine_uses_configured_repo(tmp_path):
    pipeline = tmp_path / "workflows" / "target_acquisition" / "pipelines" / "overview.yaml"
    pipeline.parent.mkdir(parents=True)
    pipeline.write_text("overview: []\n", encoding="utf-8")
    (tmp_path / "engine.py").write_text(
        "class Engine:\n"
        "    marker = 'ok'\n"
        "    def __init__(self): self.registered = []\n"
        "    def register(self, name, path): self.registered.append((name, path))\n"
        "    def shutdown(self): pass\n",
        encoding="utf-8",
    )
    engine = load_analysis_engine(tmp_path)
    assert engine.marker == "ok"
    assert engine.registered == [("overview", pipeline)]


def test_load_analysis_engine_requires_v4_pipeline(tmp_path):
    with pytest.raises(FileNotFoundError, match="v4-engine"):
        load_analysis_engine(tmp_path)


def test_analysis_preflight_runs_a_real_pipeline_submission():
    class FakeEngine:
        def __init__(self):
            self.jobs = []
            self._results = []

        def submit(self, queue, job):
            self.jobs.append(job)
            self._results.append({"input": job, "pick_targets": {"picks": []}})

        def status(self, queue):
            return {"pending": 0, "running": 0, "failed": 0, "failures": []}

        def results(self, queue):
            results, self._results = self._results, []
            return results

    engine = FakeEngine()
    preflight_analysis_engine(engine)
    assert len(engine.jobs) == 1
    assert engine.jobs[0]["source_image_size_px"] == (64, 64)


def test_with_focus_z_uses_the_surface():
    placed = with_focus_z([{"x": 5, "y": 5}], focus=_TILTED)
    assert placed[0]["z"] == pytest.approx(4.5)


def test_with_focus_z_preserves_vendor_location_indices():
    position = {
        "x": 5,
        "y": 5,
        "group": {"region": "3", "row": 0, "col": 1},
        "location": {"carrier": 1, "compartment": 7, "position": 9, "view": 2},
    }
    assert with_focus_z([position], focus=_TILTED)[0] == {**position, "z": pytest.approx(4.5)}


def test_with_focus_z_keeps_an_explicit_z_without_a_surface():
    # A position that carries its own z is honoured as-is (including a
    # deliberate z=0) when there is no fitted surface.
    assert with_focus_z([{"x": 1, "y": 2, "z": 3.5}]) == [{"x": 1, "y": 2, "z": 3.5}]
    assert with_focus_z([{"x": 1, "y": 2, "z": 0.0}]) == [{"x": 1, "y": 2, "z": 0.0}]


def test_with_focus_z_refuses_without_a_surface_or_an_explicit_z():
    # The dangerous case: no focus surface AND no z. Silently moving to
    # frame z=0 could defocus the run or crash the objective, so refuse.
    with pytest.raises(ValueError, match="no safe focus height"):
        with_focus_z([{"x": 1, "y": 2}])


def test_run_overview_captures_each_at_focus_z(mic):
    records = run_overview(mic, [{"x": 5.0, "y": 5.0}], focus=_TILTED)
    assert records[0]["acquisition_type"] == "overview"
    assert records[0]["position"]["z"] == pytest.approx(4.5)


def test_overview_inputs_from_records_pairs_positions_and_images():
    records = [{"images": ["a.ome.tiff"]}]
    overviews = overview_inputs_from_records(
        [{"x": 5.0, "y": 5.0}],
        records,
        focus=_TILTED,
        pixel_size_um=0.5,
        image_size_px=(10, 20),
    )
    assert overviews[0]["image_path"] == "a.ome.tiff"
    assert overviews[0]["channel_paths"] == ["a.ome.tiff"]
    assert overviews[0]["center_frame_um"] == (5.0, 5.0)


def test_overview_inputs_from_records_requires_saved_images():
    with pytest.raises(ValueError, match="no saved image"):
        overview_inputs_from_records(
            [{"x": 0.0, "y": 0.0}],
            [{"images": []}],
            pixel_size_um=1.0,
            image_size_px=(10, 10),
        )


def test_overview_inputs_preserve_indexed_channels():
    records = [
        {
            "images": ["c0.tiff", "c1.tiff"],
            "planes": [
                {"t": 0, "z": 0, "c": 1, "path": "c1.tiff"},
                {"t": 0, "z": 0, "c": 0, "path": "c0.tiff"},
            ],
        }
    ]
    overviews = overview_inputs_from_records(
        [{"x": 0.0, "y": 0.0}],
        records,
        pixel_size_um=1.0,
        image_size_px=(10, 10),
    )
    assert overviews[0]["image_path"] == "c0.tiff"
    assert overviews[0]["channel_paths"] == ["c0.tiff", "c1.tiff"]


def test_overview_inputs_refuse_z_stacks():
    record = {
        "planes": [
            {"t": 0, "z": 0, "c": 0, "path": "z0.tiff"},
            {"t": 0, "z": 1, "c": 0, "path": "z1.tiff"},
        ]
    }
    with pytest.raises(RuntimeError, match="requires a 2-D job"):
        overview_inputs_from_records(
            [{"x": 0.0, "y": 0.0}],
            [record],
            pixel_size_um=1.0,
            image_size_px=(10, 10),
        )


def test_acquire_targets_uses_the_target_type(mic):
    # Positions carry an explicit z (no focus surface in this unit test).
    records = acquire_targets(
        mic, [{"x": 0.0, "y": 0.0, "z": 0.0}, {"x": 1.0, "y": 1.0, "z": 0.0}]
    )
    assert [r["acquisition_type"] for r in records] == ["target", "target"]
    assert [r["position_label"] for r in records] == ["1", "2"]


def test_hijack_if_simulating_is_noop_when_disabled():
    assert hijack_if_simulating([{"images": ["ignored"]}], simulate=False) == 0


def test_write_run_report_writes_summary_and_layout(tmp_path):
    summary = write_run_report(
        tmp_path,
        positions=[{"x": 0.0, "y": 0.0}],
        focus=_TILTED,
        overview_records=[{"acquisition_type": "overview"}],
        targets=[{"x": 1.0, "y": 2.0, "source": {"naming_p": 0}}],
        show=False,
    )
    assert summary["n_overviews"] == 1
    assert summary["n_targets"] == 1
    assert (tmp_path / "summary.json").exists()
    assert (tmp_path / "run_layout.png").exists()
