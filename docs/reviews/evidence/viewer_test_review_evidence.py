"""REVIEW EVIDENCE ONLY. Runs unchanged at 9ff10b0 and at d243736."""
from __future__ import annotations
import json, sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_a_transfer_is_built_into_one_picture import a_transfer  # noqa: F401,E402
from zmart_viewer.compose import read_the_transfer  # noqa: E402

ONE = [{"label": "GFP", "color": "00FF00",
        "window": {"min": 0, "max": 65535, "start": 200, "end": 3200}}]

def _omero(store: Path, block: dict) -> None:
    held = json.loads((store / "zarr.json").read_text(encoding="utf-8"))
    held["attributes"]["ome"]["omero"] = block
    (store / "zarr.json").write_text(json.dumps(held), encoding="utf-8")

def test_a_position_without_omero_beside_positions_with_it(a_transfer: Path):  # noqa: F811
    for at, position in enumerate(sorted(a_transfer.glob("*.ome.zarr"))):
        if at:
            _omero(position, {"channels": ONE})
    assert read_the_transfer(a_transfer).omero is not None

def test_positions_differing_only_in_a_non_channel_omero_key(a_transfer: Path):  # noqa: F811
    for at, position in enumerate(sorted(a_transfer.glob("*.ome.zarr"))):
        _omero(position, {"id": at, "name": position.name, "version": "0.4", "channels": ONE})
    assert read_the_transfer(a_transfer).omero is not None
