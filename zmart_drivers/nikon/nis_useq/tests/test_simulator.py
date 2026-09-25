"""Against a running NIS-Elements (the Ti2 simulator, or a real microscope) with the bridge started.

    pytest -m hardware

Skipped when no bridge answers. The sequence stays close to where the stage
is: two positions 50 um apart and three focus planes 2 um apart, then the
stage is moved back.
"""

import pytest
import tifffile
import useq
import useq.v2 as v2
from nis_useq.client import NisConnectionError
from nis_useq.engine import NisEngine

pytestmark = pytest.mark.hardware
pymmcore_plus = pytest.importorskip("pymmcore_plus")
from pymmcore_plus.mda import MDARunner  # noqa: E402


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


def test_read_the_microscope(engine):
    client = engine.client
    print(client.info)
    assert set(client.request("get_position")) == {"x", "y", "z"}
    assert set(client.request("get_limits")) == {"x", "y", "z"}
    assert client.request("get_optical_configurations"), "NIS lists no optical configurations"
    print(client.request("get_objectives"), client.request("get_pfs"))


def test_v2_sequence_with_the_pymmcore_plus_runner(engine, tmp_path):
    here = engine.client.request("get_position")
    configuration = engine.client.request("get_optical_configurations")[0]
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

    frames = Frames()
    runner = MDARunner()
    runner.set_engine(engine)
    runner.run(sequence, output=[frames, tmp_path / "run.ome.tiff"])

    assert len(positions) == 6
    assert positions[3]["x"] == pytest.approx(here["x"] + 50, abs=1.0)
    assert [p["z"] for p in positions[:3]] == pytest.approx(
        [here["z"] - 2, here["z"], here["z"] + 2], abs=0.5
    )
    data = tifffile.imread(sorted(tmp_path.glob("*.tif*"))[0])
    print("saved", data.shape, data.dtype)


def test_classic_sequence_with_exposure(engine):
    here = engine.client.request("get_position")
    configuration = engine.client.request("get_optical_configurations")[0]
    sequence = useq.MDASequence(
        stage_positions=[(here["x"], here["y"], here["z"])],
        channels=[{"config": configuration, "exposure": 20}],
    )
    runner = MDARunner()
    runner.set_engine(engine)
    runner.run(sequence)
