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

    # 3. The composed picture reads it from the sidecar, with its provenance —
    #    and not from whichever position sorts first. To prove that by the
    #    numbers rather than by the provenance label, the first-sorting
    #    position is tampered with to claim a window of its own.
    first = sorted(positions.glob("*.ome.zarr"))[0]
    held = json.loads((first / "zarr.json").read_text())
    held["attributes"]["ome"]["omero"]["channels"][0]["window"].update({"start": 5, "end": 50})
    (first / "zarr.json").write_text(json.dumps(held), encoding="utf-8")
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


# -- three channels, no window yet ----------------------------------------------


THREE_UNRESOLVED = {
    "schema": "zmart-acquisition-display/1",
    "acquisitionType": "overview",
    "channels": [
        {"key": "405", "index": 0, "label": "DAPI", "color": "0000FF",
         "range": {"min": 0, "max": 65535}},
        {"key": "488", "index": 1, "label": "GFP", "color": "00FF00",
         "range": {"min": 0, "max": 65535}},
        {"key": "594", "index": 2, "label": "mCherry", "color": "FF0000",
         "range": {"min": 0, "max": 65535}},
    ],
}


def _three_channel_positions(tmp_path, *, how_many: int) -> Path:
    positions = tmp_path / "positions" / "overview"
    write_acquisition_description(positions, THREE_UNRESOLVED, channel_count=3)
    for at in range(how_many):
        record = one_file_per_plane(tmp_path / f"capture{at}", channels=3, offset=at * 5000)
        record["position_label"] = f"K00_M000000_G000000_P{at:06d}_V00"
        position_store_from_record(record, positions)
    return positions


def _served_over(tmp_path, positions: Path):
    """The real Viewer server, opened on the positions folder the way the bridge does."""
    import http.client
    import threading

    from zmart_viewer.server import make_server

    site = tmp_path / "site"
    site.mkdir(exist_ok=True)
    (site / "index.html").write_text("<!doctype html><title>page</title>", encoding="utf-8")
    server = make_server(port=0, data_dir=tmp_path, site_dir=site, live=True,
                         scratch_root=tmp_path / "scratch")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    def ask(route, payload):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        conn.request("POST", route, body=json.dumps(payload),
                     headers={"Content-Type": "application/json"})
        answer = conn.getresponse()
        body = json.loads(answer.read() or b"{}")
        conn.close()
        assert answer.status == 200, body
        return body

    def stop():
        server.shutdown()
        thread.join(timeout=5)

    return port, ask, stop


@pytest.mark.parametrize("how_many", [1, 2], ids=["first-direct-position", "composed"])
def test_three_undecided_channels_reach_the_embedded_page_by_name(tmp_path, how_many):
    """The channel route the review found missing, followed end to end.

    An acquisition of three colours that has not decided its window writes no
    ``omero`` block (a strict reader refuses a channel entry without a complete
    window). The names and colours travel under ``zmart`` instead, the real
    Viewer server reads them into one config row per channel, and the bridge's
    own reading of that config hands the page one source with three named
    channels — for the first position, opened on its own, and for two positions
    composed into one picture alike. No window is invented anywhere on the way.
    """
    positions = _three_channel_positions(tmp_path, how_many=how_many)
    port, ask, stop = _served_over(tmp_path, positions)
    try:
        config = ask("/api/stores/open", {"path": str(positions)})
        _the_three_are_named_all_the_way(tmp_path, positions, port, config)
    finally:
        # The scene the Viewer composed lives in its own scratch, which goes
        # when the server stops -- so everything is looked at before then.
        stop()


def _the_three_are_named_all_the_way(tmp_path, positions, port, config):
    from application.parts.storage.viewer_service import _the_sources_in
    from zmart_viewer.library import channels

    rows = [row for row in config["layers"] if row["kind"] == "image"]
    assert [row["name"] for row in rows] == ["DAPI", "GFP", "mCherry"]
    assert [row["channelIndex"] for row in rows] == [0, 1, 2]
    assert all(row["measurementState"] != "declared" for row in rows)

    found = _the_sources_in(config, port)
    [source] = next(iter(found.values()))
    assert [c["name"] for c in source["channels"]] == ["DAPI", "GFP", "mCherry"]
    assert [c["index"] for c in source["channels"]] == [0, 1, 2]
    assert [c["colour"] for c in source["channels"]] == [
        [0.0, 0.0, 1.0], [0.0, 1.0, 0.0], [1.0, 0.0, 0.0],
    ]
    assert all(c["window"] is None for c in source["channels"]), "nothing decided, nothing carried"

    # And the store the Viewer serves — the position itself, or the scene it
    # composed — names the same three channels, with no window on any of them.
    served = Path(rows[0]["sources"][0].split("/data/", 1)[1].split("|", 1)[0].split("/", 1)[1].rstrip("/"))
    where = positions / served.name if (positions / served.name).is_dir() else next(
        (tmp_path / "scratch").rglob(served.name)
    )
    described = channels(where)
    assert [c["name"] for c in described] == ["DAPI", "GFP", "mCherry"]
    assert [c["window"] for c in described] == [None, None, None]
