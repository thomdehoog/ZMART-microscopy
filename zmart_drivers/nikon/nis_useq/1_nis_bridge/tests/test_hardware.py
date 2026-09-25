"""Step 1 on a running NIS-Elements (the Ti2 simulator, or a real microscope).

    pytest -m hardware -s

Needs start_bridge.mac running in NIS; skipped when no bridge answers. The
stage moves at most 20 um in x and 2 um in z, and is moved back afterwards.
``-s`` prints what NIS reported.
"""

import pytest
import tifffile
from nis_bridge.client import NisClient, NisConnectionError

pytestmark = pytest.mark.hardware


@pytest.fixture
def client():
    try:
        client = NisClient()
    except NisConnectionError as exc:
        pytest.skip(str(exc))
    start = client.request("get_position")
    yield client
    client.request("move", **start)
    client.close()


def test_reads_the_microscope(client):
    print(client.info)
    assert set(client.request("get_position")) == {"x", "y", "z"}
    limits = client.request("get_limits")
    assert all(limits[axis]["min"] < limits[axis]["max"] for axis in "xyz")
    assert client.request("get_optical_configurations"), "NIS lists no optical configurations"
    print("limits", limits)
    print("objectives", client.request("get_objectives"))
    print("PFS", client.request("get_pfs"))


def test_moves_a_little_and_back(client):
    here = client.request("get_position")
    moved = client.request("move", x=here["x"] + 20, z=here["z"] + 2)
    assert moved["x"] == pytest.approx(here["x"] + 20, abs=1.0)
    assert moved["z"] == pytest.approx(here["z"] + 2, abs=0.5)
    back = client.request("move", **here)
    assert back["x"] == pytest.approx(here["x"], abs=1.0)


def test_sets_a_configuration_and_exposure(client):
    name = client.request("get_optical_configurations")[0]
    assert client.request("select_optical_configuration", name=name)["selected"]
    applied = client.request("set_exposure", exposure_ms=20)["exposure_ms"]
    print(f"{name}: exposure asked 20 ms, applied {applied}")
    assert applied == pytest.approx(20, rel=0.2)


def test_snaps_an_image(client, tmp_path):
    reply = client.request("snap", path=str(tmp_path / "snap.tif"), timeout=120)
    image = tifffile.imread(reply["path"])
    print("image", image.shape, image.dtype, "pixel size (um)", reply["pixel_size_um"])
    assert image.ndim >= 2 and image.max() > 0
