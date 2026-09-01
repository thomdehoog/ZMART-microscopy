"""The durable, acquisition-wide channel display description."""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

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
    return acquisition_description(acquisition_type, [channel], channel_count=1)


def test_a_valid_description_is_canonical_and_round_trips(tmp_path):
    folder = tmp_path / "overview"
    source = write_acquisition_description(folder, described(), channel_count=1)

    assert source == folder / DESCRIPTION_NAME
    assert read_acquisition_description(folder, channel_count=1) == described()
    assert json.loads(source.read_text())["channels"][0]["color"] == "00FF00"
    assert not list(folder.glob(f".{DESCRIPTION_NAME}.*.tmp"))


def test_republishing_the_same_description_is_idempotent(tmp_path):
    folder = tmp_path / "overview"
    source = write_acquisition_description(folder, described(), channel_count=1)
    before = source.stat().st_mtime_ns

    assert write_acquisition_description(folder, described(), channel_count=1) == source
    assert source.stat().st_mtime_ns == before


def test_a_changed_published_description_is_refused_without_altering_the_first(tmp_path):
    folder = tmp_path / "overview"
    source = write_acquisition_description(folder, described(), channel_count=1)
    before = source.read_bytes()

    with pytest.raises(ValueError, match="immutable"):
        write_acquisition_description(
            folder, described(window=(500, 5000)), channel_count=1
        )
    assert source.read_bytes() == before


def test_a_description_is_checked_against_an_independent_channel_count():
    with pytest.raises(ValueError, match="describes 1 channel.*2 were expected"):
        acquisition_description("overview", described(), channel_count=2)


def test_a_reader_checks_the_folder_name_and_pixel_count(tmp_path):
    folder = tmp_path / "overview"
    source = folder / DESCRIPTION_NAME
    folder.mkdir()
    source.write_text(json.dumps(described("targets")), encoding="utf-8")

    with pytest.raises(ValueError, match="names 'targets', not 'overview'"):
        read_acquisition_description(folder, channel_count=1)

    source.write_text(json.dumps(described()), encoding="utf-8")
    with pytest.raises(ValueError, match="1 channel.*2 were expected"):
        read_acquisition_description(folder, channel_count=2)


def test_two_different_concurrent_publishers_cannot_overwrite_each_other(tmp_path):
    folder = tmp_path / "overview"
    barrier = Barrier(2)
    candidates = [described(window=(300, 4200)), described(window=(500, 5000))]

    def publish(value):
        barrier.wait()
        try:
            write_acquisition_description(folder, value, channel_count=1)
            return "published"
        except ValueError:
            return "refused"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(publish, candidates))

    assert sorted(outcomes) == ["published", "refused"]
    assert read_acquisition_description(folder, channel_count=1) in candidates


def test_an_abandoned_old_temporary_is_swept_on_the_next_publication(tmp_path):
    folder = tmp_path / "overview"
    folder.mkdir()
    abandoned = folder / f".{DESCRIPTION_NAME}.abandoned.tmp"
    abandoned.write_text("partial", encoding="utf-8")
    old = time.time() - 2 * 24 * 60 * 60
    os.utime(abandoned, (old, old))

    write_acquisition_description(folder, described(), channel_count=1)

    assert not abandoned.exists()


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
    blocks = ome_channel_blocks(described(), depth_max=65535)
    assert blocks == [
        {
            "label": "GFP",
            "color": "00FF00",
            "window": {"min": 0, "max": 65535, "start": 300, "end": 4200},
        }
    ]


def test_an_unresolved_acquisition_writes_no_channel_block_at_all():
    """No names, no colours, no window: strict readers open that; they refuse
    a named channel with an incomplete window, and an invented one opens the
    picture nearly black."""
    assert ome_channel_blocks(described(window=None), depth_max=65535) == []


def test_a_filesystem_without_hard_links_still_publishes_and_still_compares(tmp_path, monkeypatch):
    """Removable media and some shares cannot link; publication must still be honest there."""
    import os

    def no_links_here(*_args, **_kwargs):
        raise OSError(1, "Operation not permitted")

    monkeypatch.setattr(os, "link", no_links_here)
    folder = tmp_path / "overview"

    written = write_acquisition_description(folder, described(), channel_count=1)
    assert written.is_file()
    assert read_acquisition_description(folder, channel_count=1) == validate_acquisition_description(
        described(), acquisition_type="overview", channel_count=1,
    )
    # The same value again is accepted; a different one is refused, as with links.
    write_acquisition_description(folder, described(), channel_count=1)
    with pytest.raises(ValueError, match="immutable|different"):
        write_acquisition_description(folder, described(window=(500, 5000)), channel_count=1)
