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


def test_the_positions_the_microscopes_bridge_writes_can_be_measured(
    harness_page, measurement_data, tmp_path,
):
    """OME-Zarr 0.5, no coverage record: exactly what a run on the microscope PC holds.

    The bridge converts every capture into a position store through
    ``position_store_from_record``, which writes the newer generation of the
    format and keeps no coverage record. The rig used to refuse both: it asked
    for every store in the older generation and drew nothing without a record.
    Now the whole frame counts as imaged, the answer says so, and the store is
    read in the generation it was written in.
    """
    import sys

    sys.path.insert(0, str(_HERE.parent.parent / "application" / "parts" / "storage"))
    from test_zarr_positions import one_file_per_plane

    from application.parts.storage.zarr_positions import position_store_from_record

    run = tmp_path / "a-real-run"
    positions = run / "positions" / "overview"
    record = one_file_per_plane(tmp_path / "vendor", channels=1, offset=2000)
    store = position_store_from_record(record, positions)
    assert (store / "zarr.json").is_file(), "the bridge writes OME-Zarr 0.5"
    listing_before = sorted(str(p) for p in run.rglob("*"))

    found = real_run.measure(
        "neuroglancer-under", run, tmp_path / "out", browser=harness_page.browser,
    )

    assert sorted(str(p) for p in run.rglob("*")) == listing_before
    assert found["store"] == store.name
    assert found["coverage_bounded"] is False, "no record was kept, and the answer says so"
    # The store was read in the generation it was written in, and its pieces
    # were fetched: the rig can look at what the microscope writes.
    assert found["requests"]["bytes_of_pieces"] > 0
    assert found["requests"]["missing"] == 0


@pytest.mark.xfail(
    strict=True,
    reason=(
        "the rig's own neuroglancer-under places the view beside a five-axis "
        "OME-Zarr 0.5 store: the layer sits where the store says, the pieces "
        "arrive, and the navigation lands outside them, so the box photographs "
        "empty. The same family as test_an_image_from_another_microscope_is_drawn. "
        "Strict, so the day the rig draws it this mark has to come off."
    ),
)
def test_the_positions_the_microscopes_bridge_writes_are_drawn(
    harness_page, measurement_data, tmp_path,
):
    """Opening is not drawing: the honest number is how much of the box changed."""
    import sys

    sys.path.insert(0, str(_HERE.parent.parent / "application" / "parts" / "storage"))
    from test_zarr_positions import one_file_per_plane

    from application.parts.storage.zarr_positions import position_store_from_record

    run = tmp_path / "a-real-run"
    position_store_from_record(
        one_file_per_plane(tmp_path / "vendor", channels=1, offset=2000),
        run / "positions" / "overview",
    )
    found = real_run.measure(
        "neuroglancer-under", run, tmp_path / "out", browser=harness_page.browser,
    )
    assert found["drawn_share"] > 0.05, "the store opened but nothing reached the screen"
