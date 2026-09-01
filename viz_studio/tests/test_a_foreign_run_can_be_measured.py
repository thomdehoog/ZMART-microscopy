"""The measurement rig can be pointed at a run it did not write.

``RESULTS.md`` records that every finding from the one real acquisition this
project has opened was invisible to a suite that only ever measured stores it
wrote itself, because ``--data`` said where to *write* and there was no way to
say where to *look*. ``--external-run`` is that way. This check gives it a
store written by something other than the rig — the writer the microscope
uses — and holds it to three things: it opens the store in place without
writing beside it, it counts every byte that crossed the wire with pieces and
descriptions apart, and it says how much of the box was actually drawn.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "options" / "measure"))
sys.path.insert(0, str(_HERE.parent.parent))

import real_run  # noqa: E402
from test_the_options_hold_together import harness_page, measurement_data  # noqa: E402,F401


def test_the_store_to_open_is_found_without_writing_anything(tmp_path):
    """A store, a folder of stores, and a run with positions/<type>/ all resolve."""
    run = tmp_path / "run"
    kind = run / "positions" / "overview"
    kind.mkdir(parents=True)
    (kind / "overview_p1.ome.zarr").mkdir()
    (kind / "overview_p1.ome.zarr" / "zarr.json").write_text("{}")
    before = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*"))

    assert real_run.the_store_to_open(run) == (kind.resolve(), "overview_p1.ome.zarr")
    assert real_run.the_store_to_open(kind) == (kind.resolve(), "overview_p1.ome.zarr")
    assert real_run.the_store_to_open(kind / "overview_p1.ome.zarr") == (
        kind.resolve(), "overview_p1.ome.zarr",
    )
    # A composed picture the viewer linked is preferred over one position.
    (kind / "overview.zmartview.zarr").mkdir()
    assert real_run.the_store_to_open(run)[1] == "overview.zmartview.zarr"

    after = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*"))
    assert set(after) - set(before) == {"run/positions/overview/overview.zmartview.zarr"}
    with pytest.raises(FileNotFoundError):
        real_run.the_store_to_open(tmp_path / "nowhere")


def test_a_run_written_by_the_microscopes_own_writer_is_measured_in_place(
    harness_page, measurement_data, tmp_path,
):
    """Open a store the rig did not write, count the bytes, look at the picture."""
    from zmart_storage.canvas import Channel, TileCanvases

    run = tmp_path / "somebody-elses-run"
    run.mkdir()
    canvas = TileCanvases.create(
        run, name="field", canvas_shape=(1, 256, 256), tile_shape=(1, 256, 256),
        tile_step=(1, 256, 256), voxel_size_um=(1.0, 0.65, 0.65),
        channels=[Channel(name="488", color="00FF66", window=(0, 4000))],
        origin_um=(0.0, 0.0, 0.0), discard_existing_run=True,
    )
    bright = (np.random.default_rng(3).random((1, 256, 256)) * 3000 + 500).astype("uint16")
    canvas.write(bright, origin=(0, 0, 0), tile_index=(0, 0, 0))
    listing_before = sorted(p.name for p in run.iterdir())

    found = real_run.measure(
        "neuroglancer-under", run, tmp_path / "out", browser=harness_page.browser,
    )

    assert found["read_only"] is True
    assert sorted(p.name for p in run.iterdir()) == listing_before, "nothing written beside the run"
    assert found["store"] == "field.ome.zarr"
    requests = found["requests"]
    assert requests["requests"] > 0
    assert requests["bytes_of_pieces"] > 0
    assert requests["bytes_of_descriptions"] > 0
    assert requests["bytes"] == requests["bytes_of_pieces"] + requests["bytes_of_descriptions"]
    assert found["drawn_share"] > 0.05, "the store opened but nothing reached the screen"
    written = json.loads(Path(found["written_to"]).read_text())
    assert written["run"] == str(run.resolve())
    assert (Path(found["written_to"]).parent / found["photograph"]).is_file()
