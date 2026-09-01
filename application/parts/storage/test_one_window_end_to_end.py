"""One display window, followed from the acquisition record to the screen.

This is the integration check the migration is for. The writer publishes one
acquisition-wide window; every position mirrors it; the Viewer composes the
positions into one picture and reads the window back from the sidecar rather
than from whichever position happened to sort first; and the configuration the
page is handed carries the same numbers. Five readings, one value.

The second half is the legacy case that started all this: two positions that
disagree. Nobody's window wins. The composed picture declares none, and the
Viewer measures one from the pixels once there are pixels to measure — and
says that it did, so the panel does not call a measurement a decision.

These run against the real ZMART Viewer package, so they are skipped where it
is not installed rather than pretending with a stand-in.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

zmart_viewer = pytest.importorskip("zmart_viewer")

from zmart_viewer.building import declare_a_built_picture  # noqa: E402
from zmart_viewer.compose import Composer, read_the_transfer  # noqa: E402
from zmart_viewer.contrast import Measurements, display_window  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_zarr_positions import described, one_file_per_plane  # noqa: E402

from application.parts.storage.acquisition_description import (  # noqa: E402
    write_acquisition_description,
)
from application.parts.storage.zarr_positions import position_store_from_record  # noqa: E402

THE_WINDOW = {"min": 0, "max": 65535, "start": 300, "end": 4200}


def _two_positions(tmp_path, *, declared: bool) -> Path:
    """A dim field and a bright one, written by the real position writer."""
    positions = tmp_path / "positions" / "overview"
    dim = one_file_per_plane(tmp_path / "dim", channels=1, offset=0)
    bright = one_file_per_plane(tmp_path / "bright", channels=1, offset=20000)
    bright["position_label"] = "K00_M000000_G000000_P000008_V00"
    if declared:
        write_acquisition_description(positions, described(), channel_count=1)
    for record in (dim, bright):
        position_store_from_record(record, positions)
    return positions


def _omero_window_of(store: Path) -> dict | None:
    attrs = json.loads((store / "zarr.json").read_text())["attributes"]
    channels = attrs.get("ome", {}).get("omero", {}).get("channels")
    return channels[0]["window"] if channels else None


def test_one_declared_window_reaches_every_reading(tmp_path):
    positions = _two_positions(tmp_path, declared=True)

    # 1. The sidecar says it.
    sidecar = json.loads((positions / "zmart-acquisition.json").read_text())
    assert sidecar["channels"][0]["displayWindow"] == {"start": 300, "end": 4200}

    # 2. Every position mirrors it, the dim one and the bright one alike.
    for store in sorted(positions.glob("*.ome.zarr")):
        assert _omero_window_of(store) == THE_WINDOW

    # 3. The composed picture reads it from the sidecar, with its provenance.
    mosaic = read_the_transfer(positions)
    group = json.loads(Composer(mosaic).group_json())["attributes"]
    assert group["ome"]["omero"]["channels"][0]["window"] == THE_WINDOW
    assert group["zmart"]["displayWindowSource"] == "zmart-acquisition.json"
    assert group["zmart"]["displayWindows"][0]["windowProvenance"]["resolvedFrom"] == (
        "acquisition-record"
    )

    # 4. A declared, built picture keeps it, and the page's configuration
    #    row carries the same numbers and calls them declared.
    built = declare_a_built_picture(tmp_path / "views", positions, name="overview", piece=64)
    assert _omero_window_of(built) == THE_WINDOW
    row = Measurements().describe(0, built.parent, built.name, "GFP", True, channel=0)
    assert row["window"] == {"low": 300.0, "high": 4200.0}
    assert row["measurementState"] == "declared"

    # 5. And the window the Viewer would draw with is that one, not a measurement.
    assert display_window(built, channel=0) == (300.0, 4200.0)


def test_two_positions_that_disagree_give_nobody_the_last_word(tmp_path):
    positions = _two_positions(tmp_path, declared=False)
    stores = sorted(positions.glob("*.ome.zarr"))

    # The writer no longer stamps a window per position, so a run written
    # today has none to disagree about. A run written before the migration
    # did, and that is the shape this half of the test is about: stamp the two
    # positions the way the old writer would have, a dim field and a bright
    # field each measured on its own scale.
    for store, (start, end) in zip(stores, [(90, 1400), (700, 19000)]):
        held = json.loads((store / "zarr.json").read_text())
        held["attributes"]["ome"]["omero"] = {"channels": [
            {"label": "channel 0", "color": "FFFFFF",
             "window": {"min": 0, "max": 65535, "start": start, "end": end}},
        ]}
        (store / "zarr.json").write_text(json.dumps(held), encoding="utf-8")
    windows = [_omero_window_of(store) for store in stores]
    assert windows[0] != windows[1]

    # The composed picture takes neither.
    mosaic = read_the_transfer(positions)
    group = json.loads(Composer(mosaic).group_json())["attributes"]
    assert "omero" not in group["ome"], "a disagreement must not become a declaration"
    assert group["zmart"]["displayWindowSource"] == "legacy-position-metadata"
    assert group["zmart"]["displayWindows"] == []

    # Once there are pixels, the Viewer measures one for the whole picture and
    # says that it measured it — not that anybody declared it.
    built = declare_a_built_picture(tmp_path / "views", positions, name="overview", piece=64)
    row = Measurements().describe(0, built.parent, built.name, "overview", True, channel=0)
    assert row["window"] is not None
    assert row["measurementState"] in {"provisional", "settled"}
    measured = (row["window"]["low"], row["window"]["high"])
    for window in windows:
        assert measured != (float(window["start"]), float(window["end"]))
