"""What happens when views and runs are moved around on disk.

Views are small folders that point at the raw data, and people move folders:
a scene gets tidied into a project directory, a finished run gets archived to
another disk. These gates pin the promises the viewer makes about that.

- A SCENE moved on its own (the raw data staying put) still opens and still
  serves the right pixels: its pointers name the data by absolute path, so
  the scene's own address does not matter.
- A whole RUN moved as one unit notices, on its next open, that its governed
  picture was declared from the old home, and quietly re-declares it at the
  new one -- bake and all -- instead of trusting a description that names a
  folder that no longer exists.

The remaining case -- the DATA moved out from under a scene -- is the relink
flow, gated in test_open_and_close (the door refuses with where the data
was, and the window rebuilds against where it is now).
"""

import json
import shutil
import sys
import threading
from pathlib import Path

import numpy as np
from numcodecs import Zstd

VIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(VIZ / "app" / "picture"))
# The backend goes in FRONT of the building folder: both hold a server.py,
# and the one with make_server is the backend's.
sys.path.insert(0, str(VIZ / "app" / "server"))
sys.path.insert(0, str(VIZ.parent))

from declare import declare_a_built_picture  # noqa: E402
from library import Library  # noqa: E402
from live_config import LIVE_PICTURE, LiveRegistry  # noqa: E402
from server import make_server  # noqa: E402
from test_a_dataset_is_relived_as_a_live_run import _a_grid_scan, _post  # noqa: E402
from test_open_and_close import _store  # noqa: E402

from zmart_live.tests.test_coordinator import some_specimen  # noqa: E402
from zmart_live.tests.test_gateway import a_live_run  # noqa: E402


def test_a_moved_scene_still_opens_and_serves(built_dist, tmp_path):
    """A scene folder moved on its own keeps working, hard copy and all.

    The scene points at the raw data by absolute path, so where the scene
    itself sits is its own business. Opened through the ordinary door from
    its new home, it must serve pieces -- and pieces whose pixels can only
    have come through the pointers, proving they still reach the data.
    """
    first = tmp_path / "overview"
    first.mkdir()
    _store(first / "overview_pos001.ome.zarr", channels=1)
    scan = _a_grid_scan(tmp_path / "scan")
    built = declare_a_built_picture(tmp_path / "scenes", scan, name="scan",
                                    bake=True)

    tidied = tmp_path / "projects" / "spring" / "scan.ome.zarr"
    tidied.parent.mkdir(parents=True)
    shutil.move(str(built), str(tidied))

    server = make_server(port=0, data_dir=first, site_dir=built_dist,
                         store="overview_pos001.ome.zarr")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        address = f"http://127.0.0.1:{server.server_address[1]}"
        status, answer = _post(address, "/api/stores/open",
                               {"path": str(tidied)})
        assert status == 200, answer
        told = json.dumps(answer.get("layers", []))
        assert "scan.ome.zarr" in told, "the moved scene must become rows"
        # One piece of the finest level, fetched over HTTP from the moved
        # scene: the finest ground is never baked, so these bytes can only
        # have been composed from the raw data the pointers name.
        source = next(one for one in answer["layers"]
                      if "scan.ome.zarr" in json.dumps(one))["sources"][0]
        base = source.split("|")[0]
        import urllib.request

        raw = urllib.request.urlopen(f"{address}{base}0/c/0/0/0").read()
        values = np.frombuffer(Zstd().decode(raw), "<u2")
        # The first piece is large enough to cover all four positions, so
        # every tile's own value must be in it -- pixels that can only have
        # come through the pointers, from every one of the tiles they name.
        assert {1500, 2300, 3100, 3900} <= set(np.unique(values)), (
            "the moved scene must still reach the raw data's own pixels"
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_a_moved_run_redeclares_its_picture_at_its_new_home(tmp_path):
    """A run folder moved whole re-declares its governed picture, once.

    The picture's description names the run it was declared from. After
    the move that name is a folder that no longer exists, and trusting it
    would serve yesterday's address; the registry notices and declares
    afresh at the new home -- bake and all -- on the first bind there.

    The bake is asked for here rather than assumed. A live run is served
    unbaked unless somebody says otherwise, and the baked road is the one
    with something to lose in a move: real files, written at the old home,
    which have to be written again at the new one.
    """
    baking = (lambda run_root: True)
    run = a_live_run(tmp_path / "was")
    run.write_and_publish("posA", some_specimen(700))

    library = Library()
    library.open(run.folder, names=["views/live/live.ome.zarr"], watch=False)
    registry = LiveRegistry(library, wants_the_bake=baking)
    bindings, _ = registry.refresh()
    assert len(bindings) == 1, registry.errors
    old_picture = run.folder / LIVE_PICTURE
    assert (old_picture / "baked.json").is_file()

    moved = tmp_path / "archive" / "run"
    moved.parent.mkdir()
    shutil.move(str(run.folder), str(moved))

    library = Library()
    library.open(moved, names=["views/live/live.ome.zarr"], watch=False)
    registry = LiveRegistry(library, wants_the_bake=baking)
    bindings, _ = registry.refresh()
    assert len(bindings) == 1, (
        f"the moved run did not bind: {registry.errors}"
    )
    described = json.loads(
        (moved / LIVE_PICTURE / "zarr.json").read_text(encoding="utf-8"))
    assert described["attributes"]["zmart"]["governed_from"] == (
        moved.as_posix()), (
        "the re-declared picture must name its NEW home, not the folder "
        "the run was moved away from"
    )
    assert (moved / LIVE_PICTURE / "baked.json").is_file(), (
        "the re-declaration keeps the one live path: baked, per commit"
    )
    # And the picture is servable from the new home: the finest piece of
    # the committed position answers with its own pixels.
    from governed import GovernedRun

    governed = GovernedRun(moved)
    try:
        composer = governed.composer()
        composer.stop_warming()
        body = composer.bytes_for(0, 0, 0, 0)
        assert body is not None
        values = np.frombuffer(Zstd().decode(body), "<u2")
        assert values.max() == 700
    finally:
        governed.close()
