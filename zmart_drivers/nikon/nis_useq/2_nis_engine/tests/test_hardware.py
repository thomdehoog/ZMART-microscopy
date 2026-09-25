"""Step 2 on a running NIS-Elements (the Ti2 simulator, or a real microscope).

    pytest -m hardware -s

Needs start_bridge.mac running in NIS and step 1 (nis-bridge) passing; skipped
when no bridge answers. Everything stays within 100 um of where the stage is,
and the stage is moved back afterwards. Tests that need a pixel calibration for
the objective in use (the camera field, tiles) are skipped without one.
"""

import json

import numpy as np
import pytest
import tifffile
import useq
import useq.v2 as v2
from nis_bridge.client import NisConnectionError
from nis_engine import NisEngine
from pymmcore_plus.mda import MDARunner

pytestmark = pytest.mark.hardware


@pytest.fixture
def engine():
    try:
        engine = NisEngine()
    except NisConnectionError as exc:
        pytest.skip(str(exc))
    start = engine.client.request("get_position")
    yield engine
    engine.client.request("move", **start)
    engine.close()


@pytest.fixture
def here(engine):
    return engine.client.request("get_position")


@pytest.fixture
def configuration(engine):
    return engine.client.request("get_optical_configurations")[0]


@pytest.fixture
def two_configurations(engine):
    """Two different optical configurations (a file cannot hold two channels of one name)."""
    configurations = engine.client.request("get_optical_configurations")
    if len(configurations) < 2:
        pytest.skip("NIS lists fewer than two optical configurations")
    return configurations[:2]


@pytest.fixture
def field(engine):
    """The camera field in um, or a skip when the objective has no pixel calibration."""
    try:
        return engine.field_of_view()
    except ValueError as exc:
        pytest.skip(str(exc))


def run(engine, sequence, output=None):
    runner = MDARunner()
    runner.set_engine(engine)
    runner.run(sequence, output=output)
    return runner


def images_in(folder):
    """How many images the OME-TIFF files under ``folder`` hold."""
    files = sorted(folder.rglob("*.ome.tif*"))
    for f in files:
        print("saved", f, tifffile.imread(f).shape)
    return sum(int(np.prod(tifffile.imread(f).shape[:-2])) for f in files)


# -- the engine on its own ------------------------------------------------------------


def test_measures_the_camera_field(engine, field):
    width, height = field
    print(f"camera field {width:.1f} x {height:.1f} um")
    assert width > 0 and height > 0


def test_checks_limits_without_moving(engine, here):
    beyond = engine.limits()["z"]["max"] + 100
    with pytest.raises(ValueError, match="outside the stage limits"):
        engine.check(useq.MDASequence(stage_positions=[(here["x"], here["y"], beyond)]))
    assert engine.client.request("get_position")["z"] == pytest.approx(here["z"], abs=0.5)


# -- useq sequences ------------------------------------------------------------------


def test_v2_sequence_with_the_pymmcore_plus_runner(engine, here, configuration, tmp_path):
    sequence = v2.MDASequence(
        stage_positions=[
            (here["x"], here["y"], here["z"]),
            (here["x"] + 50, here["y"], here["z"]),
        ],
        channels=[configuration],
        z_plan={"range": 4, "step": 2},
    )
    positions = []

    class Frames:
        def frameReady(self, image, event, meta):
            positions.append(meta["position"])

    run(engine, sequence, output=[Frames(), tmp_path / "run.ome.tiff"])
    assert len(positions) == 6
    assert positions[3]["x"] == pytest.approx(here["x"] + 50, abs=1.0)
    assert [p["z"] for p in positions[:3]] == pytest.approx(
        [here["z"] - 2, here["z"], here["z"] + 2], abs=0.5
    )
    assert images_in(tmp_path) == 6


def test_classic_sequence_keeps_its_axes(engine, here, two_configurations, tmp_path):
    sequence = useq.MDASequence(
        stage_positions=[(here["x"], here["y"], here["z"])],
        channels=[{"config": name, "exposure": 20} for name in two_configurations],
        z_plan={"range": 2, "step": 1},
    )
    run(engine, sequence, output=tmp_path / "run.ome.tiff")
    data = tifffile.imread(tmp_path / "run.ome.tiff")
    print("saved", data.shape, data.dtype)
    assert data.shape[:2] == (2, 3)  # channels, planes


def test_tiles_spaced_by_the_camera_field(engine, here, configuration, field, tmp_path):
    field = (min(field[0], 100.0), min(field[1], 100.0))  # keeps the tiles within 50 um of here
    grid = {"rows": 1, "columns": 2, "overlap": (10, 10), "fov_width": field[0],
            "fov_height": field[1]}  # fmt: skip
    sequence = useq.MDASequence(
        stage_positions=[(here["x"], here["y"], here["z"])],
        channels=[configuration],
        grid_plan=grid,
        axis_order="tpgcz",
    )
    events = engine.check(sequence)
    step = abs(events[1].x_pos - events[0].x_pos)
    assert step == pytest.approx(field[0] * 0.9, rel=0.01)  # one field less the overlap
    run(engine, sequence, output=tmp_path / "tiles.ome.tiff")
    assert images_in(tmp_path) == 2


def test_channel_options(engine, here, two_configurations, tmp_path):
    first, second = two_configurations
    sequence = useq.MDASequence(
        stage_positions=[(here["x"], here["y"], here["z"])],
        channels=[{"config": first}, {"config": second, "do_stack": False}],
        z_plan={"range": 2, "step": 1},
    )
    run(engine, sequence, output=tmp_path / "run.ome.tiff")
    assert images_in(tmp_path) == 3 + 1  # a stack in the first, one plane in the second


def test_sequence_from_a_file(engine, here, configuration, tmp_path):
    path = tmp_path / "sequence.json"
    path.write_text(json.dumps({
        "stage_positions": [{"x": here["x"], "y": here["y"], "z": here["z"]}],
        "channels": [{"config": configuration}],
        "time_plan": {"interval": 0.5, "loops": 2},
    }))  # fmt: skip
    run(engine, useq.MDASequence.from_file(path), output=tmp_path / "run.ome.tiff")
    assert images_in(tmp_path) == 2
