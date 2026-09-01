"""The durable, acquisition-wide channel display description."""

from __future__ import annotations

import json

import pytest

from application.parts.storage.acquisition_description import (
    DESCRIPTION_NAME,
    acquisition_description,
    ome_channel_blocks,
    read_acquisition_description,
    validate_acquisition_description,
    write_acquisition_description,
)


def described(acquisition_type: str = "overview", *, window=(300, 4200)) -> dict:
    channel = {
        "key": "488",
        "index": 0,
        "label": "GFP",
        "color": "00ff00",
        "range": {"min": 0, "max": 65535},
    }
    if window is not None:
        channel.update(
            {
                "displayWindow": {"start": window[0], "end": window[1]},
                "windowProvenance": {
                    "method": "preset",
                    "algorithm": None,
                    "sampleCount": 0,
                    "resolvedAtRevision": 0,
                    "resolvedFrom": "acquisition-record",
                },
            }
        )
    return acquisition_description(acquisition_type, [channel])


def test_a_valid_description_is_canonical_and_round_trips(tmp_path):
    folder = tmp_path / "overview"
    source = write_acquisition_description(folder, described())

    assert source == folder / DESCRIPTION_NAME
    assert read_acquisition_description(folder) == described()
    assert json.loads(source.read_text())["channels"][0]["color"] == "00FF00"
    assert not list(folder.glob(f".{DESCRIPTION_NAME}.*.tmp"))


def test_republishing_the_same_description_is_idempotent(tmp_path):
    folder = tmp_path / "overview"
    source = write_acquisition_description(folder, described())
    before = source.stat().st_mtime_ns

    assert write_acquisition_description(folder, described()) == source
    assert source.stat().st_mtime_ns == before


def test_a_changed_published_description_is_refused_without_altering_the_first(tmp_path):
    folder = tmp_path / "overview"
    source = write_acquisition_description(folder, described())
    before = source.read_bytes()

    with pytest.raises(ValueError, match="immutable"):
        write_acquisition_description(folder, described(window=(500, 5000)))

    assert source.read_bytes() == before


@pytest.mark.parametrize(
    "change, sentence",
    [
        (lambda value: value["channels"][0].update(index=1), "indices"),
        (lambda value: value["channels"][0].update(color="green"), "hexadecimal"),
        (
            lambda value: value["channels"][0]["displayWindow"].update(end=70000),
            "inside range",
        ),
        (lambda value: value["channels"][0].pop("windowProvenance"), "together"),
        (
            lambda value: value["channels"][0]["windowProvenance"].update(extra=float("nan")),
            "not finite",
        ),
    ],
)
def test_malformed_descriptions_are_refused(change, sentence):
    value = described()
    change(value)
    with pytest.raises(ValueError, match=sentence):
        validate_acquisition_description(value, acquisition_type="overview", channel_count=1)


def test_ome_blocks_mirror_a_resolved_window_exactly():
    blocks = ome_channel_blocks(described(), depth_max=65535, fallback_windows=[(10, 20)])
    assert blocks == [
        {
            "label": "GFP",
            "color": "00FF00",
            "window": {"min": 0, "max": 65535, "start": 300, "end": 4200},
        }
    ]


def test_unresolved_ome_blocks_keep_the_m1_compatibility_hint():
    blocks = ome_channel_blocks(
        described(window=None), depth_max=65535, fallback_windows=[(100, 900)]
    )
    assert blocks[0]["window"] == {"min": 0, "max": 65535, "start": 100, "end": 900}
