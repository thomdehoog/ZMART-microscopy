"""The load window's listing tells raw data from a finished picture.

The window decides what a click can do from one word in the folder
listing, the "kind": a built "view", a "plate" of wells, a plain "image"
the viewer draws whole, or a raw "run" with position stores inside it
that a scene can be built over (the operator renamed the vocabulary from
the old "store"/"folder" pair on 2026-08-23). Real exported runs put
that word to the test: a microscope run saved as one OME-Zarr group -- a
plain group file at the top, one store per position inside, exactly the
shape our own live writer leaves behind -- is raw data wearing an
image's clothes. Called an image, the mosaic checkbox the operator came
for never appears, and the survey cannot be built at all. Found on the
workstation 2026-08-19 with a real 6-tile Thy1 survey; the backend's
construct door built the same folder without complaint, so the
misclassification was the whole refusal.
"""

import json
import sys
import threading
from pathlib import Path

import pytest

VIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(VIZ / "backend"))

from server import make_server  # noqa: E402
from test_a_dataset_is_relived_as_a_live_run import _post  # noqa: E402
from test_open_and_close import _store  # noqa: E402


@pytest.fixture
def door(built_dist, tmp_path):
    """A served viewer and the folder beside it, for listing."""
    first = tmp_path / "overview"
    first.mkdir()
    _store(first / "overview_pos001.ome.zarr", channels=1)
    server = make_server(port=0, data_dir=first, site_dir=built_dist,
                         store="overview_pos001.ome.zarr")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", tmp_path
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _listed(address, path):
    """The listing's word for each folder at ``path``, by name."""
    status, answer = _post(address, "/api/stores/list", {"path": str(path)})
    assert status == 200, answer
    return {row["name"]: row["kind"] for row in answer["folders"]}


class TestTheListingTellsRawFromImage:
    def test_a_wrapper_group_of_positions_is_raw_data(self, door):
        """A group that only holds position stores answers "run".

        This is the shape both a real exported survey and our own live
        writer's containers take: a group description with nothing in it,
        and the positions as stores inside. It is not itself a picture --
        opening it draws its members one by one -- and calling it an image
        hid the mosaic checkbox from the operator.
        """
        address, folder = door
        run = folder / "survey.ome.zarr"
        run.mkdir()
        (run / "zarr.json").write_text(json.dumps(
            {"zarr_format": 3, "node_type": "group", "attributes": {}}))
        _store(run / "pos001.ome.zarr", channels=1)
        _store(run / "pos002.ome.zarr", channels=1)
        assert _listed(address, folder)["survey.ome.zarr"] == "run"

    def test_a_version_2_wrapper_group_is_raw_data_too(self, door):
        """The same wrapper written by an older instrument answers the same."""
        address, folder = door
        run = folder / "oldsurvey"
        run.mkdir()
        (run / ".zgroup").write_text(json.dumps({"zarr_format": 2}))
        _store(run / "pos001.ome.zarr", channels=1)
        assert _listed(address, folder)["oldsurvey"] == "run"

    def test_an_image_store_is_still_one_picture(self, door):
        """A folder whose description declares an image answers "image"."""
        address, folder = door
        _store(folder / "picture.ome.zarr", channels=1)
        assert _listed(address, folder)["picture.ome.zarr"] == "image"

    def test_a_plate_is_still_one_picture(self, door):
        """A plate answers "plate": the open door lays its wells out.

        The plate's own description carries the layout, and the plain open
        door builds the laid-out scene behind it, so a plate is one picture
        to the window even though wells and fields sit inside it as stores.
        """
        address, folder = door
        plate = folder / "plate.zarr"
        plate.mkdir()
        (plate / ".zattrs").write_text(json.dumps({"plate": {
            "rows": [{"name": "A"}], "columns": [{"name": "1"}],
            "wells": [{"path": "A/1", "rowIndex": 0, "columnIndex": 0}],
        }}))
        (plate / ".zgroup").write_text(json.dumps({"zarr_format": 2}))
        well = plate / "A" / "1"
        well.mkdir(parents=True)
        _store(well / "0", channels=1)
        assert _listed(address, folder)["plate.zarr"] == "plate"

    def test_a_plain_folder_of_positions_still_answers_run(self, door):
        """The everyday raw shape keeps its word: stores directly inside."""
        address, folder = door
        run = folder / "plainrun"
        run.mkdir()
        _store(run / "pos001.ome.zarr", channels=1)
        assert _listed(address, folder)["plainrun"] == "run"
