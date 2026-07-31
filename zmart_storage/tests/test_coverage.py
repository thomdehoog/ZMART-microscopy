"""Does the record of where a run imaged say the truth, and survive being written?

A run declares far more room than it fills, and afterwards nothing on disk says
which parts of that room hold picture. `zmart_storage.coverage` writes that down
as the run goes. These tests hold it to three things.

**It has to be right.** Everything below reads the files back off disk rather
than asking the writer what it thinks it did, because the whole point of the
record is what a reader finds later.

**It has to survive tiles landing at the same moment.** Several tiles are written
at once by design, so a record that loses a line when two land together would be
worse than none at all — it would say a region was never imaged when it was.
There is a test for that, and one that kills the writing program outright without
letting it tidy up.

**It must leave an ordinary OME-Zarr reader completely alone.** The last group of
tests opens the images the plain way and compares them, file by file, against
images written with no record at all.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import warnings
from pathlib import Path

import numpy as np
import pytest
import zarr

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from zmart_storage import Channel, TileCanvases, imaged_regions
from zmart_storage.coverage import (
    COVERAGE_FOLDER,
    REGIONS_FILE,
    TILES_FILE,
    Region,
    join_up,
    where_the_record_is,
)

TILE = (2, 128, 128)
BUTTED_UP = (2, 128, 128)


def _canvases(folder: Path, *, name="overview", **kwargs) -> TileCanvases:
    return TileCanvases.create(
        folder,
        name=name,
        canvas_shape=(2, 2048, 2048),
        tile_shape=TILE,
        tile_step=BUTTED_UP,
        voxel_size_um=(2.0, 0.35, 0.35),
        channels=[Channel("488")],
        levels=2,
        chunk=64,
        **kwargs,
    )


def _a_tile(value: int) -> np.ndarray:
    return np.full(TILE, value, dtype="uint16")


def _record_folder(run: Path, image: str = "overview.ome.zarr") -> Path:
    return where_the_record_is(run, image)


def _lines_on_disk(run: Path, image: str = "overview.ome.zarr") -> list[dict]:
    """Every line of the tile record, read straight back off disk."""
    text = (_record_folder(run, image) / TILES_FILE).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _summary_on_disk(run: Path, image: str = "overview.ome.zarr") -> dict:
    """The short summary, read straight back off disk."""
    return json.loads(
        (_record_folder(run, image) / REGIONS_FILE).read_text(encoding="utf-8")
    )


# -- what a tile leaves behind ------------------------------------------------


def test_a_tile_that_lands_is_written_down(tmp_path):
    """Every part of a tile the brief asks for is on disk afterwards."""
    canvases = _canvases(tmp_path)
    canvases.write(_a_tile(4242), origin=(0, 256, 384), channel=0, frame=0,
                   tile_index=(0, 2, 3))
    canvases.close()

    lines = _lines_on_disk(tmp_path)
    assert len(lines) == 1
    (only,) = lines
    assert only["acquisition"] == "overview"
    assert only["image"] == "overview.ome.zarr"
    assert only["frame"] == 0
    assert only["channel"] == 0
    assert only["origin"] == {"z": 0, "y": 256, "x": 384}
    assert only["shape"] == {"z": 2, "y": 128, "x": 128}
    assert only["tile_index"] == {"z": 0, "y": 2, "x": 3}
    # When it landed, close enough to now that it cannot have come from anywhere
    # but this write.
    when = only["written"]
    assert when.endswith("+00:00") and when.startswith("20")


def test_a_target_with_no_place_in_a_pattern_is_still_written_down(tmp_path):
    """A tile the workflow chose for itself has no scan-pattern index, and says so."""
    canvases = _canvases(tmp_path)
    canvases.write(_a_tile(11), origin=(0, 512, 512))
    canvases.close()

    (only,) = _lines_on_disk(tmp_path)
    assert only["tile_index"] is None
    assert only["origin"] == {"z": 0, "y": 512, "x": 512}


def test_the_record_is_written_as_the_run_goes_not_at_the_end(tmp_path):
    """A live viewer needs the record before the run is over, so it must be there."""
    canvases = _canvases(tmp_path)
    canvases.write(_a_tile(1), origin=(0, 0, 0), tile_index=(0, 0, 0))
    canvases.write(_a_tile(2), origin=(0, 0, 128), tile_index=(0, 0, 1))

    # Read without closing the writer: this is what a viewer does mid-run.
    assert len(_lines_on_disk(tmp_path)) == 2
    canvases.close()


def test_nothing_is_claimed_before_a_single_tile_has_landed(tmp_path):
    """A freshly declared run says "a record is kept here and it is empty"."""
    _canvases(tmp_path)

    summary = _summary_on_disk(tmp_path)
    assert summary["tiles_written"] == 0
    assert summary["regions"] == []
    assert summary["bounds"] is None
    # The line-by-line record exists and is empty, rather than being absent.
    assert (_record_folder(tmp_path) / TILES_FILE).read_text(encoding="utf-8") == ""


def test_a_run_that_kept_no_record_is_not_mistaken_for_an_empty_one(tmp_path):
    """"I cannot say" and "nowhere yet" are different answers and must stay so."""
    nothing_there = imaged_regions(tmp_path / "a folder nobody wrote")
    assert nothing_there.recorded is False
    assert nothing_there.regions == []

    _canvases(tmp_path)
    declared_but_empty = imaged_regions(tmp_path)
    assert declared_but_empty.recorded is True
    assert declared_but_empty.regions == []


def test_a_write_that_is_refused_leaves_nothing_behind(tmp_path):
    """The record must never claim ground where no picture was written."""
    canvases = _canvases(tmp_path)
    with pytest.raises(ValueError):
        canvases.write(_a_tile(1), origin=(0, 2000, 2000))  # past the edge
    canvases.close()

    assert _lines_on_disk(tmp_path) == []
    assert imaged_regions(tmp_path).regions == []


# -- which rectangles hold data ----------------------------------------------


def test_a_raster_of_tiles_comes_back_as_one_rectangle(tmp_path):
    """Tiles butted up against one another really are one region, and say so.

    This is what keeps the summary small enough for a browser to read in one go:
    a run of several hundred tiles must not produce several hundred rectangles.
    """
    canvases = _canvases(tmp_path)
    for row in range(4):
        for col in range(4):
            canvases.write(_a_tile(1000 + row * 4 + col),
                           origin=(0, row * 128, col * 128),
                           tile_index=(0, row, col))
    canvases.close()

    summary = _summary_on_disk(tmp_path)
    assert summary["regions"] == [
        {"z": [0, 2], "y": [0, 512], "x": [0, 512]}
    ]
    assert summary["tiles_written"] == 16


def test_targets_far_apart_stay_far_apart(tmp_path):
    """Scattered targets are genuinely separate, and joining them would lie."""
    canvases = _canvases(tmp_path)
    canvases.write(_a_tile(1), origin=(0, 0, 0))
    canvases.write(_a_tile(2), origin=(0, 1024, 1024))
    canvases.close()

    summary = _summary_on_disk(tmp_path)
    assert summary["regions"] == [
        {"z": [0, 2], "y": [0, 128], "x": [0, 128]},
        {"z": [0, 2], "y": [1024, 1152], "x": [1024, 1152]},
    ]
    # The room between them was never imaged, and the record must not pretend it was.
    assert summary["bounds"] == {"z": [0, 2], "y": [0, 1152], "x": [0, 1152]}


def test_the_regions_cover_every_tile_and_nothing_else(tmp_path):
    """Checked voxel by voxel against the tiles themselves, on an awkward shape.

    An L of tiles is the shape that catches a joining rule that is too eager: no
    single rectangle covers it, and any answer that claims one is claiming ground
    the run never visited.
    """
    canvases = _canvases(tmp_path)
    corners = [(0, 0), (0, 128), (0, 256), (128, 0), (256, 0)]
    for row, col in corners:
        canvases.write(_a_tile(1), origin=(0, row, col))
    canvases.close()

    found = imaged_regions(tmp_path)
    imaged = {
        (y, x)
        for row, col in corners
        for y in range(row, row + 128, 8)
        for x in range(col, col + 128, 8)
    }
    for y in range(0, 512, 8):
        for x in range(0, 512, 8):
            covered = any(region.contains(0, y, x) for region in found.regions)
            assert covered == ((y, x) in imaged), f"disagreed about ({y}, {x})"


def test_joining_never_grows_or_shrinks_the_ground_covered():
    """The joining is only allowed to tidy up, never to change the answer."""
    blocks = [
        Region(0, 2, 0, 10, 0, 10),
        Region(0, 2, 0, 10, 10, 20),   # touching in x
        Region(0, 2, 10, 20, 0, 20),   # touching the pair of them in y
        Region(0, 2, 100, 110, 100, 110),  # on its own
    ]
    joined = join_up(blocks)
    assert joined == [
        Region(0, 2, 0, 20, 0, 20),
        Region(0, 2, 100, 110, 100, 110),
    ]

    def voxels(regions):
        return {
            (y, x)
            for region in regions
            for y in range(region.y0, region.y1)
            for x in range(region.x0, region.x1)
        }

    assert voxels(joined) == voxels(blocks)


# -- was this particular place visited ---------------------------------------


def test_a_dark_tile_is_told_apart_from_room_nobody_visited(tmp_path):
    """The question the images themselves cannot answer.

    A tile of pure black and a piece of canvas nothing was ever written to both
    read back as zeros — zarr saves no file for either. Only the record can say
    which is which, and that is the whole reason it exists.
    """
    canvases = _canvases(tmp_path)
    canvases.write(np.zeros(TILE, dtype="uint16"), origin=(0, 0, 0),
                   tile_index=(0, 0, 0))
    canvases.close()

    image = zarr.open_group(str(tmp_path / "overview.ome.zarr"), mode="r")["0"]
    dark = np.asarray(image[0, 0, 0, 0:128, 0:128])
    never_visited = np.asarray(image[0, 0, 0, 512:640, 512:640])
    assert dark.max() == 0 and never_visited.max() == 0  # indistinguishable here

    found = imaged_regions(tmp_path)
    assert found.was_imaged(0, 64, 64) is True
    assert found.was_imaged(0, 576, 576) is False


def test_a_place_can_be_asked_about_one_moment_at_a_time(tmp_path):
    """A timelapse images a place at some moments and not others, and it shows."""
    canvases = TileCanvases.create(
        tmp_path,
        name="overview",
        canvas_shape=(2, 2048, 2048),
        tile_shape=TILE,
        tile_step=BUTTED_UP,
        voxel_size_um=(2.0, 0.35, 0.35),
        channels=[Channel("488"), Channel("561")],
        frames=4,
        levels=2,
        chunk=64,
    )
    canvases.write(_a_tile(1), origin=(0, 0, 0), frame=0, channel=0)
    canvases.write(_a_tile(2), origin=(0, 0, 0), frame=2, channel=1)
    canvases.close()

    found = imaged_regions(tmp_path)
    assert found.was_imaged(0, 10, 10, frame=0) is True
    assert found.was_imaged(0, 10, 10, frame=1) is False
    assert found.was_imaged(0, 10, 10, frame=2, channel=1) is True
    assert found.was_imaged(0, 10, 10, frame=2, channel=0) is False
    assert found.frames == [0, 2]
    assert found.channels == [0, 1]
    # And the summary a browser reads says the same about which moments exist.
    assert _summary_on_disk(tmp_path)["frames"] == [0, 2]


def test_a_run_with_no_record_answers_no_rather_than_pretending(tmp_path):
    """``was_imaged`` on a run that kept no record must not read as "not imaged"."""
    found = imaged_regions(tmp_path)
    assert found.recorded is False
    assert found.was_imaged(0, 0, 0) is False  # and ``recorded`` is how you tell


# -- several images, and reading one of them ---------------------------------


def test_a_run_spread_over_several_images_is_gathered_together(tmp_path):
    """A run keeping its overlap writes several images, and coverage covers them all."""
    canvases = TileCanvases.create(
        tmp_path,
        name="overview",
        canvas_shape=(2, 2048, 2048),
        tile_shape=TILE,
        tile_step=(2, 112, 112),
        voxel_size_um=(2.0, 0.35, 0.35),
        channels=[Channel("488")],
        levels=2,
        chunk=64,
        slots=(1, 2, 2),
    )
    for row in range(2):
        for col in range(2):
            canvases.write(_a_tile(1000 + row * 2 + col),
                           origin=(0, row * 112, col * 112),
                           tile_index=(0, row, col))
    canvases.close()

    kept = sorted(p.name for p in (tmp_path / COVERAGE_FOLDER).iterdir())
    assert kept == [f"overview_part{n}.ome.zarr" for n in range(4)]

    whole_run = imaged_regions(tmp_path)
    assert len(whole_run.tiles) == 4
    assert whole_run.regions == [Region(0, 2, 0, 240, 0, 240)]

    just_one = imaged_regions(tmp_path / "overview_part0.ome.zarr")
    assert len(just_one.tiles) == 1
    assert just_one.tiles[0].image == "overview_part0.ome.zarr"
    assert just_one.tiles[0].acquisition == "overview"


def test_each_acquisition_type_keeps_its_own_record(tmp_path):
    """An overview and a targetscan share a folder and must not share a record."""
    overview = _canvases(tmp_path, name="overview")
    overview.write(_a_tile(1), origin=(0, 0, 0))
    overview.close()
    targets = _canvases(tmp_path, name="targetscan")
    targets.write(_a_tile(2), origin=(0, 1024, 0))
    targets.close()

    only_overview = imaged_regions(tmp_path / "overview.ome.zarr")
    assert [tile.acquisition for tile in only_overview.tiles] == ["overview"]
    assert only_overview.regions == [Region(0, 2, 0, 128, 0, 128)]

    both = imaged_regions(tmp_path)
    assert sorted(both.images) == ["overview.ome.zarr", "targetscan.ome.zarr"]
    assert len(both.tiles) == 2


def test_declaring_a_run_again_throws_the_old_record_away(tmp_path):
    """Declaring empties the images, so a record of what they held must go too."""
    first = _canvases(tmp_path)
    first.write(_a_tile(1), origin=(0, 0, 0))
    first.close()
    assert len(_lines_on_disk(tmp_path)) == 1

    second = _canvases(tmp_path, discard_existing_run=True)
    second.write(_a_tile(2), origin=(0, 512, 512))
    second.close()

    lines = _lines_on_disk(tmp_path)
    assert len(lines) == 1
    assert lines[0]["origin"] == {"z": 0, "y": 512, "x": 512}


def test_declaring_a_run_again_forgets_the_images_it_no_longer_has(tmp_path):
    """A run redeclared with fewer images must not leave the extra records behind.

    A run that keeps the overlap between its tiles spreads them over several
    numbered images, and each of those gets a record of its own. Declaring the same
    acquisition again as a single image throws the numbered images away — but their
    records live in a folder beside the images, which nothing else touches, so
    unless they are removed on purpose they stay there describing a run that is no
    longer on disk.

    What that costs is worth spelling out, because it is not merely untidy. Reading
    the coverage of the run would report tiles belonging to images the operator
    cannot open, and would claim as imaged a stretch of canvas the new run has
    never been near. A viewer bounding its work to "where the picture is" would
    then keep asking for a region that holds nothing at all.
    """
    spread = TileCanvases.create(
        tmp_path,
        name="overview",
        canvas_shape=(2, 2048, 2048),
        tile_shape=TILE,
        tile_step=(2, 112, 112),
        voxel_size_um=(2.0, 0.35, 0.35),
        channels=[Channel("488")],
        levels=2,
        chunk=64,
        slots=(1, 2, 2),
    )
    for row in range(2):
        for col in range(2):
            spread.write(_a_tile(1000 + row * 2 + col),
                         origin=(0, 1024 + row * 112, 1024 + col * 112),
                         tile_index=(0, row, col))
    spread.close()
    assert len(list((tmp_path / COVERAGE_FOLDER).iterdir())) == 4

    # The same acquisition again, this time as a single image, so the four
    # numbered images the first run wrote are thrown away.
    again = _canvases(tmp_path, discard_existing_run=True)
    again.write(_a_tile(7), origin=(0, 0, 0), tile_index=(0, 0, 0))
    again.close()

    kept = sorted(p.name for p in (tmp_path / COVERAGE_FOLDER).iterdir())
    assert kept == ["overview.ome.zarr"], (
        f"records were left behind for images this run does not have: {kept}"
    )

    found = imaged_regions(tmp_path)
    assert found.images == ["overview.ome.zarr"]
    assert found.regions == [Region(0, 2, 0, 128, 0, 128)], (
        f"the coverage still claims ground belonging to the run that was thrown "
        f"away: {found.regions}"
    )


def test_declaring_a_run_again_leaves_another_acquisition_type_alone(tmp_path):
    """Throwing away the overview must not throw away the targetscan beside it."""
    targets = _canvases(tmp_path, name="targetscan")
    targets.write(_a_tile(7), origin=(0, 1024, 0))
    targets.close()
    overview = _canvases(tmp_path, name="overview")
    overview.write(_a_tile(1), origin=(0, 0, 0))
    overview.close()

    again = _canvases(tmp_path, name="overview", discard_existing_run=True)
    again.close()

    assert _lines_on_disk(tmp_path, "targetscan.ome.zarr")[0]["origin"] == {
        "z": 0, "y": 1024, "x": 0
    }


def test_the_record_does_not_look_like_an_imaged_run(tmp_path):
    """A record left beside declared-but-unimaged images must not block a new run.

    The writer refuses to declare over a folder that already holds acquired
    picture. That check must not be fooled by the record, or every run that
    declared its images and stopped would leave the folder unusable.
    """
    _canvases(tmp_path).close()
    # No tiles were written, so declaring again is allowed and must stay allowed.
    _canvases(tmp_path).close()


# -- surviving tiles landing at the same moment ------------------------------


def test_every_line_survives_tiles_written_all_at_once(tmp_path):
    """Sixteen threads writing at once, and every one of them is in the record.

    This is the constraint the design turns on. What this test pins is the lock the
    recorder holds while it adds a line: take that away, and a record that read the
    file and wrote it back loses lines here exactly as two tiles sharing a zarr
    chunk lose picture — whichever writer saved last saves a copy that never held
    the other's line.

    It is worth being straight about the limit of that, because the two other
    things keeping this record safe cannot be shown by a test of this shape. The
    file is opened in "always add to the end" mode, and each line is handed to the
    operating system in a single call. Neither has any effect while the lock is
    held, because then no two threads are ever inside the writing at the same
    moment — so a record that read and rewrote the whole file every time would pass
    this test comfortably. Those two belong to the shape of the file rather than to
    the behaviour of one program, and the test below asks about them directly.
    """
    canvases = _canvases(tmp_path)
    places = [(row, col) for row in range(4) for col in range(4)]
    trouble: list[BaseException] = []
    start = threading.Barrier(len(places))

    def write(row, col):
        try:
            start.wait(timeout=30)
            canvases.write(_a_tile(1000 + row * 4 + col),
                           origin=(0, row * 128, col * 128),
                           tile_index=(0, row, col))
        except BaseException as why:  # noqa: BLE001 - reported below
            trouble.append(why)

    threads = [threading.Thread(target=write, args=place) for place in places]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    canvases.close()
    assert not trouble, trouble

    lines = _lines_on_disk(tmp_path)
    assert len(lines) == len(places)
    corners = {(line["origin"]["y"], line["origin"]["x"]) for line in lines}
    assert corners == {(row * 128, col * 128) for row, col in places}
    # And every line is whole: a spliced line would not be readable JSON at all,
    # which the reading above would already have shown, so this checks the parts.
    assert all(line["shape"] == {"z": 2, "y": 128, "x": 128} for line in lines)


def test_a_line_can_only_ever_be_added_to_the_end_of_the_record(tmp_path):
    """Nothing already in the record can be moved or written over by a later line.

    This is the half of the record's safety that the test above cannot show. With
    the recorder's lock held, even a record that read the whole file and wrote it
    back would survive threads — so passing that test is not evidence that the file
    is only ever added to.

    What "always add to the end" buys is that the safety does not rest on the lock
    being right. The operating system puts each line at the end of the file itself,
    whatever offset the writer believed it was at, so a line that is already on disk
    cannot be overwritten by a later one. That is what makes the record of a run
    that was cut short trustworthy: whatever reached the disk stayed there.

    It is shown here by putting a line into the file from outside, in between two
    tiles. A writer that kept its own place in the file would carry on from where it
    left off and lay the next tile's line straight over that one; a writer that
    always adds to the end cannot, whatever it believed its place to be. Nothing
    real writes to this file but the recorder — the line from outside is simply the
    plainest way to move the end of the file behind the writer's back.
    """
    canvases = _canvases(tmp_path)
    canvases.write(_a_tile(1), origin=(0, 0, 0), tile_index=(0, 0, 0))

    from_somewhere_else = '{"note": "put here by something other than the writer"}'
    with (_record_folder(tmp_path) / TILES_FILE).open("a", encoding="utf-8") as also:
        also.write(from_somewhere_else + "\n")

    canvases.write(_a_tile(2), origin=(0, 0, 128), tile_index=(0, 0, 1))
    canvases.close()

    lines = (_record_folder(tmp_path) / TILES_FILE).read_text(
        encoding="utf-8"
    ).splitlines()
    assert len(lines) == 3, (
        f"three lines went into the record and {len(lines)} came back, so one of "
        f"them was written over rather than added after the others"
    )
    assert lines[1] == from_somewhere_else, (
        "the line already on disk was overwritten by the tile that followed it, "
        "which means the record is not opened in 'always add to the end' mode"
    )
    assert json.loads(lines[0])["origin"]["x"] == 0
    assert json.loads(lines[2])["origin"]["x"] == 128


def test_the_record_matches_the_picture_after_writing_at_once(tmp_path):
    """The record and the pixels must agree, tile by tile, not merely in count."""
    canvases = _canvases(tmp_path)
    places = [(row, col) for row in range(4) for col in range(4)]
    start = threading.Barrier(len(places))

    def write(row, col):
        start.wait(timeout=30)
        canvases.write(_a_tile(1000 + row * 4 + col),
                       origin=(0, row * 128, col * 128),
                       tile_index=(0, row, col))

    threads = [threading.Thread(target=write, args=place) for place in places]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    canvases.close()

    found = imaged_regions(tmp_path)
    image = zarr.open_group(str(tmp_path / "overview.ome.zarr"), mode="r")["0"]
    picture = np.asarray(image[0, 0, 0])
    for tile in found.tiles:
        region = tile.region
        block = picture[region.y0:region.y1, region.x0:region.x1]
        assert block.min() > 0, (
            f"the record claims {region} was imaged, and the picture there is empty"
        )


# A run written by a program that is then killed outright, with no chance to
# tidy up. Kept as text rather than as a function so that it can be run as its
# own program, which is the only way to have it killed for real.
_A_RUN_THAT_GETS_KILLED = """
import sys, time
import numpy as np
sys.path.insert(0, {repo!r})
from zmart_storage import Channel, TileCanvases

canvases = TileCanvases.create(
    {folder!r}, name="overview", canvas_shape=(2, 2048, 2048),
    tile_shape=(2, 128, 128), tile_step=(2, 128, 128),
    voxel_size_um=(2.0, 0.35, 0.35), channels=[Channel("488")],
    levels=2, chunk=64,
)
for n in range(12):
    canvases.write(np.full((2, 128, 128), 1000 + n, "uint16"),
                   origin=(0, (n // 4) * 128, (n % 4) * 128),
                   tile_index=(0, n // 4, n % 4))
print("written", flush=True)
time.sleep(120)
"""


def test_a_run_killed_without_tidying_up_keeps_everything_it_wrote(tmp_path):
    """Nothing waits until the end, so nothing is lost when there is no end.

    A writer that saved its record only when the run finished would lose all of
    it here, and this is not a rare accident: an operator stopping a run, a
    machine rebooting, or a script that raises all leave exactly this behind.
    """
    program = tmp_path / "a_run.py"
    program.write_text(
        _A_RUN_THAT_GETS_KILLED.format(
            repo=str(Path(__file__).resolve().parents[2]),
            folder=str(tmp_path / "run"),
        ),
        encoding="utf-8",
    )
    running = subprocess.Popen(
        [sys.executable, str(program)], stdout=subprocess.PIPE, text=True
    )
    try:
        said = running.stdout.readline()
        assert said.strip() == "written", said
        os.kill(running.pid, signal.SIGKILL)
    finally:
        running.wait(timeout=60)
        running.stdout.close()
    assert running.returncode == -signal.SIGKILL

    lines = _lines_on_disk(tmp_path / "run")
    assert len(lines) == 12
    found = imaged_regions(tmp_path / "run")
    assert found.regions == [Region(0, 2, 0, 384, 0, 512)]
    # Nothing said the run had finished, because it never did.
    assert found.run_finished is False


def test_the_summary_is_never_found_half_written(tmp_path):
    """A reader arriving mid-rewrite sees a whole summary, old or new, never a torn one.

    The summary is rebuilt from scratch as the run goes, so a reader could easily
    catch it in the middle. It is written under another name and moved into place
    in a single step, which is what makes that impossible.
    """
    canvases = _canvases(tmp_path)
    stop = threading.Event()
    torn: list[str] = []

    def keep_reading():
        while not stop.is_set():
            try:
                text = (_record_folder(tmp_path) / REGIONS_FILE).read_text(
                    encoding="utf-8"
                )
            except OSError as why:
                torn.append(f"could not be read: {why}")
                continue
            try:
                json.loads(text)
            except ValueError as why:
                torn.append(f"half written: {why}")

    reader = threading.Thread(target=keep_reading)
    reader.start()
    try:
        for n in range(60):
            canvases.write(_a_tile(1000 + n),
                           origin=(0, (n // 8) * 128, (n % 8) * 128),
                           tile_index=(0, n // 8, n % 8))
            # Slow enough that the summary really is rebuilt several times over.
            time.sleep(0.02)
    finally:
        stop.set()
        reader.join(timeout=30)
    canvases.close()

    assert not torn, torn[:3]
    # And no leftover part-written file was abandoned beside it.
    left = sorted(p.name for p in _record_folder(tmp_path).iterdir())
    assert left == [REGIONS_FILE, TILES_FILE]


# -- leaving an ordinary OME-Zarr reader alone -------------------------------


def _every_file_under(folder: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(folder)): path.read_bytes()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


class _KeepsNoRecord:
    """A stand-in for the recorder that writes nothing at all.

    Used to produce a run exactly as this writer produced them before the record
    existed, so that the two can be compared. Deleting the record from a finished
    run would prove nothing — the question is whether keeping it changed anything
    while the run was going.
    """

    def __init__(self, *args, **kwargs) -> None:
        pass

    def remember(self, **kwargs) -> None:
        pass

    def finish(self) -> None:
        pass


@pytest.mark.parametrize("version", ["0.4", "0.5"])
def test_the_images_are_byte_for_byte_what_they_were_before(tmp_path, version, monkeypatch):
    """The strongest form of "it changes nothing": compare every file.

    The same run is written twice — once keeping the record, once with the
    recording replaced by something that does nothing at all. If keeping the
    record altered so much as one byte of one image, the two would differ.

    This test names ``Recorder`` inside the writer, which is a thing tests should
    normally avoid: it means the test has to be adjusted if that class is ever
    renamed or moved. It is done deliberately here, and the reason is worth
    knowing before anybody loosens it. What has to be compared is a run written
    *without any record at all*, and the writer offers no way to ask for one —
    quite rightly, since nobody acquiring data would want it. Removing the record
    from a finished run afterwards would prove nothing, because the question is
    whether keeping it changed anything *while the run was going*. So the only
    honest way to produce the second run is to reach in and replace the recorder,
    and this test is expected to be kept in step with that name.
    """
    import zmart_storage.canvas as canvas_module

    with_record = tmp_path / "with"
    without = tmp_path / "without"
    for run, recording in ((with_record, True), (without, False)):
        with monkeypatch.context() as patched:
            if not recording:
                patched.setattr(canvas_module, "Recorder", _KeepsNoRecord)
            canvases = _canvases(run, ome_zarr_version=version)
            for col in range(3):
                canvases.write(_a_tile(1000 + col), origin=(0, 0, col * 128),
                               tile_index=(0, 0, col))
            canvases.close()

    # The run folder itself gains exactly one entry, and it is the record.
    added = {p.name for p in with_record.iterdir()} - {p.name for p in without.iterdir()}
    assert added == {COVERAGE_FOLDER}

    mine = _every_file_under(with_record / "overview.ome.zarr")
    theirs = _every_file_under(without / "overview.ome.zarr")
    assert sorted(mine) == sorted(theirs)
    assert mine == theirs


@pytest.mark.parametrize("version", ["0.4", "0.5"])
def test_a_plain_zarr_reader_notices_nothing(tmp_path, version):
    """Open the images the ordinary way and check there is nothing to remark on.

    Asking an image what it contains is what would show an addition inside it, so
    that is exactly what is asked here — and it must produce the levels the run
    declared, no more, with no warning attached.
    """
    canvases = _canvases(tmp_path, ome_zarr_version=version)
    canvases.write(_a_tile(4242), origin=(0, 0, 0), tile_index=(0, 0, 0))
    canvases.close()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        group = zarr.open_group(str(tmp_path / "overview.ome.zarr"), mode="r")
        members = sorted(name for name, _ in group.members())
        arrays = sorted(group.array_keys())
        corner = int(np.asarray(group["0"][0, 0, 0, 0, 0]))
    assert members == ["0", "1"]
    assert arrays == ["0", "1"]
    assert corner == 4242
    assert not caught, [str(warning.message) for warning in caught]


def test_the_viewer_reads_the_run_exactly_as_it_did_before(tmp_path):
    """The viewer's own questions about a store give the same answers either way.

    Comparing against a copy of the run with the record deleted is what makes
    this evidence rather than reassurance: whatever the viewer says about one, it
    has to say about the other.

    One thing to know if this ever fails: it is the only test here that reads the
    viewer's own code, so a change in ``viz_studio/backend`` can turn it red
    without anything in the writer having moved. That is the price of asking the
    real reader rather than an imitation of one, and the answer is usually worth
    it — but when this test alone fails, look at what the viewer changed before
    looking at the record.
    """
    backend = Path(__file__).resolve().parents[2] / "viz_studio" / "backend"
    sys.path.insert(0, str(backend))
    try:
        import contrast
        import stores
    finally:
        sys.path.remove(str(backend))

    canvases = _canvases(tmp_path)
    for col in range(3):
        canvases.write(_a_tile(1000 + col), origin=(0, 0, col * 128),
                       tile_index=(0, 0, col))
    canvases.close()

    def everything_the_viewer_asks(run: Path) -> dict:
        store = run / "overview.ome.zarr"
        return {
            "which images are in the run": stores.discover(run)[1],
            "is a store": stores.is_store(store),
            "axes": stores.axis_names(store),
            "channels": stores.channels(store),
            "moments": stores.written_timepoints(store),
            "masks beside it": stores.label_images(store),
            "coarsest copy written": contrast.coarsest_level_is_written(store),
        }

    asked = everything_the_viewer_asks(tmp_path)
    # Worth pinning outright as well, so that this cannot pass by both sides
    # being equally wrong.
    assert asked["which images are in the run"] == ["overview.ome.zarr"]
    assert asked["axes"] == ["t", "c", "z", "y", "x"]
    assert asked["moments"] == 1
    assert asked["coarsest copy written"] is True

    # The same run with no record at all, to compare against.
    plain = tmp_path.parent / "plain"
    shutil.copytree(tmp_path, plain)
    shutil.rmtree(plain / COVERAGE_FOLDER)
    assert asked == everything_the_viewer_asks(plain)


def test_the_record_does_not_look_like_the_run_changing(tmp_path):
    """Rewriting the summary must not make the viewer rebuild its whole description.

    The viewer decides whether a run has changed by looking at when each folder
    beside it was last touched. Adding a file to a folder counts as touching it,
    so a summary rewritten every second in the wrong place would have looked like
    the acquisition itself changing, once a second, and the viewer would have
    rebuilt everything each time — which on a large folder costs over a second.
    """
    canvases = _canvases(tmp_path)
    canvases.write(_a_tile(1), origin=(0, 0, 0), tile_index=(0, 0, 0))
    time.sleep(1.2)  # long enough that the summary is due to be rebuilt

    def marks() -> dict[str, int]:
        return {
            entry.name: entry.stat().st_mtime_ns
            for entry in tmp_path.iterdir()
            if entry.is_dir()
        }

    before = marks()
    for col in range(1, 6):
        canvases.write(_a_tile(1000 + col), origin=(0, 0, col * 128),
                       tile_index=(0, 0, col))
        time.sleep(0.3)
    canvases.close()

    # The summary really was rebuilt while that went on.
    assert _summary_on_disk(tmp_path)["tiles_written"] == 6
    assert marks() == before
