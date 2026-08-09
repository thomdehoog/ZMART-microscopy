"""Proving that a piece of the view really is the piece of the position it claims.

What is being checked here
--------------------------

The seamless view stores no full-resolution pixels. When the viewer asks for one
of its pieces, :mod:`zmart_live.viewroute` says which file already holds those
bytes, where in that file they start and how many of them there are. If that
answer is wrong the viewer does not fail — it draws a picture. It draws the wrong
part of the specimen, confidently, and nothing anywhere says so.

So almost every test here ends in the same comparison, made in different
circumstances:

    take the bytes the route says a piece of the view occupies, hand them to Zarr
    to decode, and check that what comes back is exactly equal to what Zarr
    itself returns for that region of the position.

Nothing weaker than "exactly equal" is any use, because a shifted or partly wrong
chunk still looks like a micrograph.

The decode is done the honest way, the same way ``test_shardlink.py`` does it: a
second, very small image is written on disk, declared exactly as the view has to
be declared, and the extracted bytes are dropped in as its one and only chunk
file. Reading that little image back through the ordinary ``zarr.open_array`` is
a genuine end-to-end decode through the same code a viewer would use.

The two things this route exists to make possible
-------------------------------------------------

Both are checked directly, because both were recorded as gaps in the review of
this branch.

*A seam is allowed to cut across a bundle.* A position bundles many chunks into
one file so that a long run does not leave millions of files behind. The older
whole-file route therefore had to measure everything in whole bundles, and
refused the arrangement the acquisition profile actually chooses. Here the unit
is the chunk, and a position's share of the view routinely begins and ends in the
middle of a bundle. There is a test that watches the whole-file route refuse the
very placement this one accepts.

*Nothing is advertised that was not written.* A position covers plenty of ground
it has not recorded yet, because the run is still going or because that part of
the frame held no specimen. Every one of those has to answer "there is nothing
here" rather than handing over bytes belonging to somewhere else.

Why the pictures are small
--------------------------

The arithmetic does not care how large an image is, and a test suite nobody is
willing to wait for stops being run. So most of these use a 512-pixel picture in
chunks of 128 bundled 256 at a time, which is the smallest arrangement in which a
chunk, a bundle and a seam are all genuinely different things. One test uses the
1152-pixel frame the overview profile really chooses, because the claim it makes
is about that plan in particular.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest
import zarr

from zmart_live import shardlink
from zmart_live.model import ZmartLiveError
from zmart_live.profiles import plan_the_writing
from zmart_live.shardlink import (
    forget_every_remembered_index,
    how_the_remembering_is_going,
)
from zmart_live.viewroute import (
    Placed,
    Serving,
    refuse_a_view_stored_differently,
    route_the_view,
    the_bytes_of,
)

# The small arrangement nearly every test uses. A picture 512 pixels square and
# two planes deep, cut into 128-pixel chunks, with four of those chunks and both
# planes packed into each bundle. Three sizes that are all different is what makes
# it possible to tell which of them a mistake was measured in.
SHAPE = (1, 1, 2, 512, 512)
CHUNK = (1, 1, 1, 128, 128)
BUNDLE = (1, 1, 2, 256, 256)

# Where the seam between the two positions falls: three chunks across, which is
# the middle of the second bundle. This one number is the whole point of the
# module — it is a legal place for a seam here and an illegal one for the
# whole-file route.
SEAM = 3 * CHUNK[-1]


# ---------------------------------------------------------------------------
# Writing positions to point at, and reading pieces back out of them
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def start_with_nothing_remembered():
    """Give every test the same empty memory of bundle tables to start from.

    A bundle's table of contents, once read, is kept for as long as the file it
    came from is unchanged — that is what makes the route quick. It also means one
    test could be answered from something an earlier test left behind, and a few of
    the tests below count how many tables were read off the disk. A count is only
    worth anything if it starts at zero.
    """
    forget_every_remembered_index()
    yield
    forget_every_remembered_index()


def some_specimen(shape, seed=0):
    """Pixels with plenty of variety in them.

    A chunk of flat grey would compress to almost nothing and would look exactly
    like its neighbours, which is precisely the situation in which a wrong byte
    range goes unnoticed. Random values make every chunk distinguishable from
    every other one, so a piece taken from the wrong place cannot pass.
    """
    return np.random.default_rng(seed).integers(0, 60000, size=shape, dtype=np.uint16)


def a_position(
    folder, *, shape=SHAPE, chunk=CHUNK, bundle=BUNDLE, seed=0, written=Ellipsis
):
    """Write one small position as the acquisition would, and return its pixels.

    ``written`` says which part of it to fill in. Leaving it as ``...`` fills the
    whole picture, which is what a finished position looks like; giving a slice
    leaves the rest of it unwritten, which is what a position looks like while the
    run is still going.
    """
    array = zarr.create_array(
        store=str(folder),
        shape=shape,
        chunks=chunk,
        shards=bundle,
        dtype="uint16",
        compressors="auto",
        fill_value=0,
    )
    pixels = np.zeros(shape, dtype="uint16")
    if written is Ellipsis:
        pixels[...] = some_specimen(shape, seed)
        array[...] = pixels
    else:
        piece = some_specimen(np.zeros(shape, dtype="uint16")[written].shape, seed)
        pixels[written] = piece
        array[written] = piece
    return Path(folder), pixels


def decoded(raw, scratch, route):
    """Decode one extracted piece by letting Zarr read it as a tiny image.

    The scratch image is declared exactly as the view itself has to be declared —
    the positions' inner chunk, their compression, no bundling of its own — so
    this is also a small check that those instructions are right. If the view's
    declaration were wrong, the decode here would fail or give different pixels.
    """
    shutil.rmtree(scratch, ignore_errors=True)
    zarr.create_array(
        store=str(scratch),
        shape=route.storage.chunk,
        chunks=route.storage.chunk,
        dtype=route.storage.dtype,
        compressors="auto",
        fill_value=route.storage.fill_value,
    )
    declared = tuple(json.loads((Path(scratch) / "zarr.json").read_text())["codecs"])
    assert declared == route.storage.codecs, (
        f"the scratch image encodes its chunks as {declared}, but the positions "
        f"encode theirs as {route.storage.codecs}, so this decode would not be "
        "reading the bytes the way the acquisition wrote them"
    )
    where = Path(scratch).joinpath("c", *("0" for _ in route.storage.chunk))
    where.parent.mkdir(parents=True, exist_ok=True)
    where.write_bytes(raw)
    return np.asarray(zarr.open_array(str(scratch), mode="r")[...])


def the_same_region(position, coordinate, chunk):
    """What Zarr itself returns for the region one chunk covers.

    This is the answer the extracted bytes have to agree with. Reading it through
    the ordinary Zarr path means the comparison is against the picture as anybody
    else's software would see it, not against another copy of this module's own
    arithmetic.
    """
    array = zarr.open_array(str(position), mode="r")
    window = tuple(
        slice(index * size, index * size + size)
        for index, size in zip(coordinate, chunk, strict=True)
    )
    return np.asarray(array[window])


@pytest.fixture(scope="module")
def a_view_with_a_seam(tmp_path_factory):
    """Two positions meeting at a seam that falls in the middle of a bundle.

    The left position gives up its far strip — the ordinary one-sided seam — so it
    supplies the view only as far as ``SEAM``, and the right position supplies
    everything beyond. Built once for the whole file, because writing it is the
    slowest thing here and nothing in it is modified.
    """
    folder = tmp_path_factory.mktemp("seam")
    left, left_pixels = a_position(folder / "pos0", seed=1)
    right, right_pixels = a_position(folder / "pos1", seed=2)
    route = route_the_view(
        [
            Placed(left, lands_at=(0, 0, 0), size=(SHAPE[2], SHAPE[3], SEAM)),
            Placed(right, lands_at=(0, 0, SEAM)),
        ],
        view_shape=(SHAPE[2], SHAPE[3], SEAM + SHAPE[4]),
    )
    return route, folder, (left, left_pixels), (right, right_pixels)


# ---------------------------------------------------------------------------
# What the view advertises
# ---------------------------------------------------------------------------


def test_the_view_advertises_chunks_and_not_bundles(a_view_with_a_seam):
    """The unit the view offers is the chunk inside the bundle, not the bundle.

    This is the whole difference between this route and the whole-file one, so it
    is stated as a presence and an absence together: the shape the view declares
    is the chunk, and it is emphatically not the bundle.
    """
    route, *_ = a_view_with_a_seam
    assert route.storage.chunk == CHUNK
    assert route.storage.chunk != BUNDLE
    assert route.storage.positions_are_bundled is True


def test_the_view_is_not_bundled_even_though_its_positions_are(a_view_with_a_seam):
    """The view describes single chunks, because single chunks are what it serves.

    A view that declared bundles would be describing a container that is not
    there. Nothing is lost by leaving it out: the reason to bundle is the number
    of files a run leaves behind, and this view writes no picture files at all.
    """
    route, folder, *_ = a_view_with_a_seam
    plain = folder / "view-one-chunk-per-file"
    shutil.rmtree(plain, ignore_errors=True)
    zarr.create_array(
        store=str(plain),
        shape=(1, 1, 2, 512, 896),
        chunks=route.storage.chunk,
        dtype=route.storage.dtype,
        compressors="auto",
        fill_value=route.storage.fill_value,
    )
    refuse_a_view_stored_differently(plain, route)

    # Named without the word "bundle" in it on purpose: the refusal quotes the
    # folder it is complaining about, and a check that matched the message would
    # otherwise be matching the name of the folder instead.
    packed = folder / "view-many-chunks-per-file"
    shutil.rmtree(packed, ignore_errors=True)
    zarr.create_array(
        store=str(packed),
        shape=(1, 1, 2, 512, 896),
        chunks=route.storage.chunk,
        shards=BUNDLE,
        dtype=route.storage.dtype,
        compressors="auto",
        fill_value=route.storage.fill_value,
    )
    with pytest.raises(ZmartLiveError, match="declares that it bundles many chunks"):
        refuse_a_view_stored_differently(packed, route)


def test_a_view_declared_with_the_wrong_chunk_is_refused(a_view_with_a_seam):
    """A view whose pieces are a different size would scramble the picture."""
    route, folder, *_ = a_view_with_a_seam
    wrong = folder / "view-wrong-chunk"
    shutil.rmtree(wrong, ignore_errors=True)
    zarr.create_array(
        store=str(wrong),
        shape=(1, 1, 2, 512, 896),
        chunks=(1, 1, 1, 256, 256),
        dtype=route.storage.dtype,
        compressors="auto",
        fill_value=route.storage.fill_value,
    )
    with pytest.raises(ZmartLiveError, match="says one of its pieces is"):
        refuse_a_view_stored_differently(wrong, route)


# ---------------------------------------------------------------------------
# The comparison the whole idea rests on
# ---------------------------------------------------------------------------


def test_every_piece_of_the_view_decodes_to_the_right_picture(a_view_with_a_seam, tmp_path):
    """Walk the whole view, piece by piece, and check each one against Zarr.

    This is the test that would catch an offset a byte out, a length a byte short,
    a shard coordinate used where a chunk coordinate belongs, or a seam placed on
    the wrong side. Every piece is checked rather than a sample, because the
    picture is small enough to afford it and a sample is exactly how an edge case
    survives.
    """
    route, _, (left, left_pixels), (right, right_pixels) = a_view_with_a_seam
    seam_chunk = SEAM // CHUNK[-1]
    checked = 0
    for z in range(route.chunks_in_view[0]):
        for y in range(route.chunks_in_view[1]):
            for x in range(route.chunks_in_view[2]):
                serving = route.where_this_chunk_is((0, 0, z, y, x))
                assert serving is not None, f"nothing advertised at {(z, y, x)}"
                if x < seam_chunk:
                    expected_position, inside = left, (0, 0, z, y, x)
                else:
                    expected_position, inside = right, (0, 0, z, y, x - seam_chunk)
                assert serving.position == expected_position
                assert serving.inside_the_position == inside
                lifted = decoded(the_bytes_of(serving), tmp_path / "scratch", route)
                assert np.array_equal(
                    lifted, the_same_region(expected_position, inside, CHUNK)
                ), f"the piece at {(z, y, x)} decodes to a different picture"
                checked += 1
    assert checked == 2 * 4 * 7


def test_the_seam_falls_in_the_middle_of_a_bundle(a_view_with_a_seam):
    """The piece next to the seam is a stretch inside a file, not the whole file.

    This is the fact the whole-file route cannot express, so it is worth checking
    outright rather than inferring it. The last piece the left position supplies
    lives in a bundle that also holds the pieces beyond the seam, which the view
    never asks that position for.
    """
    route, _, (left, _), _ = a_view_with_a_seam
    serving = route.where_this_chunk_is((0, 0, 0, 0, 2))
    assert serving is not None
    assert serving.position == left
    held_in = serving.path.stat().st_size
    assert serving.length < held_in, (
        "the piece next to the seam is the whole of its file, which would mean "
        "the bundle held only one chunk and the seam was on a bundle boundary "
        "after all"
    )
    assert serving.stop <= held_in
    # The bundle this piece sits in covers the ground on both sides of the seam,
    # and the far side of it is supplied by the other position.
    beyond = route.where_this_chunk_is((0, 0, 0, 0, 3))
    assert beyond is not None
    assert beyond.position != serving.position


def test_the_bytes_are_read_from_exactly_where_the_route_says(a_view_with_a_seam):
    """Reading the range by hand gives the same bytes the route hands over."""
    route, *_ = a_view_with_a_seam
    serving = route.where_this_chunk_is((0, 0, 1, 3, 5))
    assert serving is not None
    with serving.path.open("rb") as opened:
        opened.seek(serving.offset)
        by_hand = opened.read(serving.length)
    assert the_bytes_of(serving) == by_hand
    assert len(by_hand) == serving.length


def test_a_piece_claiming_more_bytes_than_its_file_holds_is_refused(a_view_with_a_seam):
    """A truncated bundle is refused rather than half-decoded.

    Handing over the bytes that happen to be there would give the viewer part of a
    chunk, which decodes to something rather than to an error.
    """
    route, *_ = a_view_with_a_seam
    serving = route.where_this_chunk_is((0, 0, 0, 0, 0))
    assert serving is not None
    too_long = Serving(
        path=serving.path,
        offset=serving.path.stat().st_size - 10,
        length=1000,
        position=serving.position,
        inside_the_position=serving.inside_the_position,
    )
    with pytest.raises(ZmartLiveError, match="shorter"):
        the_bytes_of(too_long)


# ---------------------------------------------------------------------------
# Where a position is taken from, and where it stops
# ---------------------------------------------------------------------------


def test_a_position_shown_from_an_offset_gives_its_own_chunks(tmp_path):
    """Trimming the near edge shifts which of the position's chunks answer.

    A one-sided seam can be placed either way round: the left neighbour gives up
    its far strip, or the right neighbour gives up its near strip. Both have to
    work, and getting the second wrong shows the specimen shifted by exactly one
    strip, which looks entirely plausible.
    """
    position, _ = a_position(tmp_path / "pos", seed=7)
    route = route_the_view([Placed(position, lands_at=(0, 0, 0), taken_from=(0, 0, SEAM))])
    assert route.view_shape == (SHAPE[2], SHAPE[3], SHAPE[4] - SEAM)

    serving = route.where_this_chunk_is((0, 0, 0, 0, 0))
    assert serving is not None
    assert serving.inside_the_position == (0, 0, 0, 0, SEAM // CHUNK[-1])
    lifted = decoded(the_bytes_of(serving), tmp_path / "scratch", route)
    assert np.array_equal(
        lifted, the_same_region(position, (0, 0, 0, 0, SEAM // CHUNK[-1]), CHUNK)
    )
    assert not np.array_equal(lifted, the_same_region(position, (0, 0, 0, 0, 0), CHUNK))


def test_a_position_answers_only_for_the_part_the_view_shows(tmp_path):
    """Past its trimmed edge a position supplies nothing at all.

    The strip a position gives up at a seam still exists in its own file, and it
    is still perfectly readable. What must not happen is the view handing it over,
    because that ground belongs to the neighbour and drawing both would show the
    specimen twice.
    """
    position, _ = a_position(tmp_path / "pos", seed=8)
    route = route_the_view(
        [Placed(position, lands_at=(0, 0, 0), size=(SHAPE[2], SHAPE[3], SEAM))],
        view_shape=(SHAPE[2], SHAPE[3], SHAPE[4]),
    )
    assert route.advertises((0, 0, 0, 0, 2))
    assert not route.advertises((0, 0, 0, 0, 3))


def test_a_small_position_does_not_answer_for_its_larger_neighbour(tmp_path):
    """A position's share of the view is bounded on every axis, not just found nearby.

    Looking a piece up starts from the nearest position to the left and walks
    back, and how far back it walks is decided by the *widest* position in that
    row. So a small position sitting beside a large one is reached for pieces that
    lie beyond anything it supplies, and only the check against its own extent
    stops it answering for them. It would answer plausibly: the chunk it would
    hand over exists and decodes perfectly, it simply belongs somewhere else on
    the slide.

    Depth is checked the same way, with a position shown for one plane only.
    """
    wide, _ = a_position(tmp_path / "wide", seed=21)
    narrow, _ = a_position(tmp_path / "narrow", seed=22)
    route = route_the_view(
        [
            Placed(wide, lands_at=(0, 0, 0)),
            Placed(narrow, lands_at=(0, 0, 1024), size=(1, SHAPE[3], CHUNK[-1])),
        ],
        view_shape=(SHAPE[2], SHAPE[3], 1024 + SHAPE[4]),
    )
    # The single piece, on the single plane, that the small position supplies.
    assert route.advertises((0, 0, 0, 0, 8))
    # Across the specimen, past its far edge, and in depth, past the one plane it
    # was asked for. Both of those are ground it holds and does not supply.
    assert not route.advertises((0, 0, 0, 0, 9))
    assert not route.advertises((0, 0, 1, 0, 8))


def test_ground_no_position_covers_is_not_advertised(tmp_path):
    """Most of a scattered run's picture is ground nobody imaged, and says so."""
    position, _ = a_position(tmp_path / "pos", seed=9)
    route = route_the_view(
        [Placed(position, lands_at=(0, 0, 0))],
        view_shape=(SHAPE[2], 2 * SHAPE[3], 2 * SHAPE[4]),
    )
    assert route.advertises((0, 0, 0, 3, 3))
    assert not route.advertises((0, 0, 0, 6, 3))
    assert not route.advertises((0, 0, 0, 3, 6))
    # Beyond the edge of the declared picture there is nothing either, and asking
    # is not a fault: a viewer rounding a screenful up to whole chunks does it
    # constantly.
    assert route.where_this_chunk_is((0, 0, 0, 40, 40)) is None


# ---------------------------------------------------------------------------
# Pieces that were never written
# ---------------------------------------------------------------------------


def test_a_chunk_never_written_inside_a_written_bundle_is_not_advertised(tmp_path):
    """A half-filled bundle advertises what is in it and nothing more.

    This is the case that only exists because of bundling, and it is the one a
    whole-file route cannot even ask about. While the run is going, a bundle holds
    the chunks that have landed so far and empty places for the rest. The empty
    places must answer "there is nothing here"; anything else hands the viewer
    bytes belonging to a different part of the specimen.
    """
    position, _ = a_position(
        tmp_path / "pos", seed=10, written=np.s_[0, 0, 0, 0:128, 0:256]
    )
    route = route_the_view([Placed(position, lands_at=(0, 0, 0))])

    # Written, and in the same bundle as the two that follow.
    assert route.advertises((0, 0, 0, 0, 0))
    assert route.advertises((0, 0, 0, 0, 1))
    # Never written, but inside that same bundle file: a different plane, and the
    # chunk row below.
    assert not route.advertises((0, 0, 1, 0, 0))
    assert not route.advertises((0, 0, 0, 1, 0))
    # Never written, and its bundle file does not exist at all.
    assert not route.advertises((0, 0, 0, 0, 2))
    assert route.where_this_chunk_is((0, 0, 0, 1, 0)) is None


def test_a_moment_the_position_has_not_recorded_is_not_advertised(tmp_path):
    """A view may declare more moments than a position has written."""
    position, _ = a_position(tmp_path / "pos", seed=11)
    route = route_the_view([Placed(position, lands_at=(0, 0, 0))])
    assert route.advertises((0, 0, 0, 0, 0))
    assert not route.advertises((1, 0, 0, 0, 0))
    assert not route.advertises((0, 1, 0, 0, 0))


def test_a_position_whose_files_are_all_missing_advertises_nothing(tmp_path):
    """A position that has been declared but never written to is simply empty."""
    zarr.create_array(
        store=str(tmp_path / "pos"),
        shape=SHAPE,
        chunks=CHUNK,
        shards=BUNDLE,
        dtype="uint16",
        compressors="auto",
        fill_value=0,
    )
    route = route_the_view([Placed(tmp_path / "pos", lands_at=(0, 0, 0))])
    assert not route.advertises((0, 0, 0, 0, 0))
    assert not route.advertises((0, 0, 1, 3, 3))


# ---------------------------------------------------------------------------
# What is refused before anything is served
# ---------------------------------------------------------------------------


def test_landing_between_chunks_is_refused_but_between_bundles_is_fine(tmp_path):
    """The unit is the chunk. Not the bundle, and not the pixel.

    Both halves matter. Refusing a placement that falls between chunks is what
    stops the view from having to cut pixels out of one file and paste them into
    another. Accepting one that falls between *bundles* is the entire reason this
    module exists, and it is the thing the whole-file route cannot do.
    """
    position, _ = a_position(tmp_path / "pos", seed=12)

    with pytest.raises(ZmartLiveError, match="chunks"):
        route_the_view([Placed(position, lands_at=(0, 0, 64))])

    assert SEAM % BUNDLE[-1] != 0, "this test is only meaningful mid-bundle"
    route = route_the_view([Placed(position, lands_at=(0, 0, SEAM))])
    assert route.advertises((0, 0, 0, 0, SEAM // CHUNK[-1]))


def test_the_refusal_explains_that_the_bundle_is_not_the_unit(tmp_path):
    """An operator who has met the whole-file rule expects the wrong answer here.

    The message is part of the contract: somebody reading it has to come away
    knowing that it is the chunk that has to line up, even though the position is
    stored in much larger files.
    """
    position, _ = a_position(tmp_path / "pos", seed=13)
    with pytest.raises(ZmartLiveError) as refusal:
        route_the_view([Placed(position, lands_at=(0, 0, 64))])
    said = str(refusal.value)
    assert "chunks 128 pixels across" in said
    assert "not what has to line up" in said


def test_every_axis_is_measured_against_its_own_chunk(tmp_path):
    """Depth is checked too, and against the chunk for depth rather than for width.

    Positions are usually one plane to a chunk, which makes depth free and hides a
    mistake here. This one keeps two planes in a chunk so that landing on an odd
    plane is genuinely misaligned.
    """
    deep_chunk = (1, 1, 2, 128, 128)
    position, _ = a_position(
        tmp_path / "pos",
        shape=(1, 1, 4, 256, 256),
        chunk=deep_chunk,
        bundle=(1, 1, 4, 256, 256),
        seed=14,
    )
    with pytest.raises(ZmartLiveError, match=r"lands at 1 pixels in z"):
        route_the_view([Placed(position, lands_at=(1, 0, 0))])
    route = route_the_view([Placed(position, lands_at=(2, 0, 0))])
    assert route.storage.chunk == deep_chunk
    assert route.advertises((0, 0, 1, 0, 0))


def test_two_positions_claiming_the_same_piece_are_refused(tmp_path):
    """An undecided seam is refused rather than settled by list order."""
    left, _ = a_position(tmp_path / "pos0", seed=15)
    right, _ = a_position(tmp_path / "pos1", seed=16)
    with pytest.raises(ZmartLiveError, match="same piece"):
        route_the_view(
            [
                Placed(left, lands_at=(0, 0, 0)),
                Placed(right, lands_at=(0, 0, SEAM)),
            ]
        )
    # Trimmed so that they meet rather than overlap, the same pair is fine.
    route = route_the_view(
        [
            Placed(left, lands_at=(0, 0, 0), size=(SHAPE[2], SHAPE[3], SEAM)),
            Placed(right, lands_at=(0, 0, SEAM)),
        ]
    )
    assert len(route.positions) == 2


def test_positions_stored_differently_are_refused(tmp_path):
    """One description is written for all of them, so they have to agree."""
    first, _ = a_position(tmp_path / "pos0", seed=17)
    other, _ = a_position(
        tmp_path / "pos1", chunk=(1, 1, 1, 256, 256), bundle=(1, 1, 2, 256, 256), seed=18
    )
    with pytest.raises(ZmartLiveError, match="cut into chunks of"):
        route_the_view(
            [
                Placed(first, lands_at=(0, 0, 0)),
                Placed(other, lands_at=(0, 0, 512)),
            ]
        )


def test_asking_for_more_of_a_position_than_it_holds_is_refused(tmp_path):
    """The part shown has to be inside the position."""
    position, _ = a_position(tmp_path / "pos", seed=19)
    with pytest.raises(ZmartLiveError, match="past its far edge"):
        route_the_view(
            [Placed(position, lands_at=(0, 0, 0), size=(SHAPE[2], SHAPE[3], 1024))]
        )


def test_a_view_over_no_positions_is_refused(tmp_path):
    """An empty run is a mistake worth naming rather than an empty picture."""
    with pytest.raises(ZmartLiveError, match="at least one position"):
        route_the_view([])


def test_a_coordinate_of_the_wrong_shape_is_refused(a_view_with_a_seam):
    """A coordinate with the wrong number of axes cannot mean anything."""
    route, *_ = a_view_with_a_seam
    with pytest.raises(ZmartLiveError, match="axes"):
        route.where_this_chunk_is((0, 0, 0))
    with pytest.raises(ZmartLiveError, match="backwards"):
        route.where_this_chunk_is((0, 0, 0, -1, 0))


# ---------------------------------------------------------------------------
# A position that keeps every chunk in a file of its own
# ---------------------------------------------------------------------------


def test_an_unbundled_position_is_served_as_a_whole_file(tmp_path):
    """Not bundling is an ordinary way to store a picture, and it still routes.

    The answer is then the whole of the chunk's own file — offset nought, length
    the size of the file — which is exactly what the older whole-file route hands
    over. Checking it here means one route serves both kinds of position, so a run
    does not have to be stored one particular way to be looked at.
    """
    position, _ = a_position(tmp_path / "pos", bundle=None, seed=20)
    route = route_the_view([Placed(position, lands_at=(0, 0, 0))])
    assert route.storage.positions_are_bundled is False

    serving = route.where_this_chunk_is((0, 0, 1, 2, 3))
    assert serving is not None
    assert serving.offset == 0
    assert serving.length == serving.path.stat().st_size
    lifted = decoded(the_bytes_of(serving), tmp_path / "scratch", route)
    assert np.array_equal(lifted, the_same_region(position, (0, 0, 1, 2, 3), CHUNK))


# ---------------------------------------------------------------------------
# The two claims about the rest of the project
# ---------------------------------------------------------------------------


def test_the_whole_file_route_refuses_the_placement_this_one_accepts(tmp_path):
    """Watch the older route refuse, and this one accept, the very same seam.

    This is the finding stated as a test. ``zmart_storage.linked`` hands whole
    files over, so for a bundled position it measures in whole bundles and refuses
    a seam three chunks along. Nothing about that is a bug in it — it genuinely
    cannot express a seam inside a file. The route here can, and both halves are
    checked together so that neither claim can quietly stop being true.
    """
    from zmart_storage.canvas import Channel, _declare_one
    from zmart_storage.linked import PlacedTile, link_the_tiles

    stores = []
    for index in range(2):
        store = tmp_path / f"pos{index}.ome.zarr"
        levels = _declare_one(
            store,
            canvas_shape=(2, 512, 512),
            frames=1,
            channels=1,
            dtype="uint16",
            chunk=CHUNK[-1],
            shard=BUNDLE[-1],
            levels=1,
            voxel_size_um=(1.0, 0.5, 0.5),
            origin_um=(0.0, 0.0, index * SEAM * 0.5),
            channel_blocks=[Channel("488", window=(0, 65535)).described(65535)],
            ome_zarr_version="0.5",
        )
        levels[0][0, 0] = some_specimen((2, 512, 512), seed=30 + index)
        stores.append(store)

    tiles = [
        PlacedTile(stores[0], lands_at=(0, 0, 0), size=(2, 512, SEAM)),
        PlacedTile(stores[1], lands_at=(0, 0, SEAM)),
    ]
    with pytest.raises(ValueError, match="bundle that has to line up"):
        link_the_tiles(
            tmp_path, tiles=tiles, name="whole-files", view_shape=(2, 512, SEAM + 512)
        )

    route = route_the_view(
        [
            Placed(stores[0] / "0", lands_at=(0, 0, 0), size=(2, 512, SEAM)),
            Placed(stores[1] / "0", lands_at=(0, 0, SEAM)),
        ],
        view_shape=(2, 512, SEAM + 512),
    )
    serving = route.where_this_chunk_is((0, 0, 0, 0, 3))
    assert serving is not None
    assert serving.position == stores[1] / "0"
    lifted = decoded(the_bytes_of(serving), tmp_path / "scratch", route)
    assert np.array_equal(lifted, the_same_region(stores[1] / "0", (0, 0, 0, 0, 0), CHUNK))


def test_the_sharded_plan_the_profile_chooses_now_links(tmp_path):
    """The arrangement ``plan_the_writing`` really emits, routed end to end.

    The overview plan gives a 1152-pixel frame, 128-pixel chunks, one chunk of
    overlap and therefore a step of 1024 — and a bundle spanning the whole frame,
    so that a night of imaging leaves a manageable number of files behind. A seam
    at 1024 is eight chunks along and is not on a bundle boundary at all, which is
    exactly why the whole-file route refuses this plan.

    Two positions of it are written here at full width and two planes deep, which
    is a few megabytes rather than the tens of gigabytes a real run reaches. The
    arithmetic is the same at either size.
    """
    profile, geometry = plan_the_writing("overview", frame=1152, z_planes=2)
    level = profile.level(0)
    chunk = (1, 1, level.inner_chunk["z"], level.inner_chunk["y"], level.inner_chunk["x"])
    bundle = (1, 1, level.shard["z"], level.shard["y"], level.shard["x"])
    frame, step = geometry.frame, geometry.step

    # The seam the profile's one-sided ownership puts between two positions is a
    # whole number of chunks and is nowhere near a bundle boundary. That sentence
    # is the finding, so it is asserted rather than assumed.
    assert step % chunk[-1] == 0
    assert step % bundle[-1] != 0

    stores = []
    for index in range(2):
        store, _ = a_position(
            tmp_path / f"pos{index}",
            shape=(1, 1, 2, frame, frame),
            chunk=chunk,
            bundle=bundle,
            seed=40 + index,
        )
        stores.append(store)

    route = route_the_view(
        [
            Placed(stores[0], lands_at=(0, 0, 0), size=(2, frame, step)),
            Placed(stores[1], lands_at=(0, 0, step)),
        ],
        view_shape=(2, frame, step + frame),
    )
    assert route.storage.chunk == chunk

    # The three pieces worth checking: the last one the left position supplies,
    # the first one the right position supplies, and one from the far corner.
    for at, expected_position, inside in (
        ((0, 0, 1, 4, step // chunk[-1] - 1), stores[0], (0, 0, 1, 4, step // chunk[-1] - 1)),
        ((0, 0, 0, 0, step // chunk[-1]), stores[1], (0, 0, 0, 0, 0)),
        (
            (0, 0, 1, 8, (step + frame) // chunk[-1] - 1),
            stores[1],
            (0, 0, 1, 8, frame // chunk[-1] - 1),
        ),
    ):
        serving = route.where_this_chunk_is(at)
        assert serving is not None, f"nothing advertised at {at}"
        assert serving.position == expected_position
        assert serving.inside_the_position == inside
        lifted = decoded(the_bytes_of(serving), tmp_path / "scratch", route)
        assert np.array_equal(lifted, the_same_region(expected_position, inside, chunk))

    # And the piece just past the seam really does come out of the middle of a
    # bundle rather than being a file of its own.
    serving = route.where_this_chunk_is((0, 0, 0, 0, step // chunk[-1] - 1))
    assert serving is not None
    assert serving.length < serving.path.stat().st_size


# ---------------------------------------------------------------------------
# What the route keeps between requests, and what it must not
# ---------------------------------------------------------------------------


def swap_two_entries_in_the_bundles_table(bundle, first, second, entries):
    """Exchange two entries in a bundle's table, writing the file back in place.

    This stands in for the position having been written again — the same chunks,
    packed in a different order. It is the change hardest to notice, because the
    file keeps exactly the same length and every byte range it describes still
    points at real, decodable pixels. The file is opened for updating rather than
    replaced, so it keeps the same inode, which is the file system's own numbered
    slot for it.

    Working out the checksum again afterwards is the writer's job, and this is
    standing in for a writer. Without it a reader would refuse the bundle for the
    wrong reason and the test would pass without ever asking its question.
    """
    raw = bytearray(Path(bundle).read_bytes())
    table_at = len(raw) - entries * 16 - 4
    here, there = table_at + first * 16, table_at + second * 16
    raw[here : here + 16], raw[there : there + 16] = (
        raw[there : there + 16],
        raw[here : here + 16],
    )
    table = bytes(raw[table_at : table_at + entries * 16])
    raw[table_at + entries * 16 :] = shardlink._crc32c(table).to_bytes(4, "little")
    with Path(bundle).open("r+b") as opened:
        opened.write(bytes(raw))


def test_a_position_written_again_is_never_served_from_its_old_table(tmp_path):
    """A bundle repacked since the route was built is read again, not remembered.

    A bundle's table of contents is kept between requests, because reading it is
    the expensive part of answering and one screenful asks about dozens of chunks
    out of the same bundle. The danger that creates is the one this test is about.
    A table that no longer describes its file does not produce an error: it
    produces a byte range that decodes perfectly and shows the wrong part of the
    specimen, which is exactly the kind of fault an operator cannot see.

    Here the bundle is repacked with two of its chunks exchanged. It keeps the
    same length and the same inode, so the only thing that has changed about it is
    when it changed. What is checked is not that the answer moved, but that the
    pixels the answer leads to are the ones now stored at that place.
    """
    position, pixels = a_position(tmp_path / "pos")
    route = route_the_view([Placed(position, lands_at=(0, 0, 0))])

    before = route.where_this_chunk_is((0, 0, 0, 0, 0))
    assert before is not None
    assert np.array_equal(
        decoded(the_bytes_of(before), tmp_path / "scratch", route),
        pixels[0:1, 0:1, 0:1, 0:128, 0:128],
    )

    # The bundle holds one moment, one colour, two planes and two chunks each way,
    # so eight chunk positions in all. Entries are in row-major order, which puts
    # the chunk at column zero first and its neighbour at column one second.
    bundle = Path(position) / "c" / "0" / "0" / "0" / "0" / "0"
    was = bundle.stat()
    swap_two_entries_in_the_bundles_table(bundle, 0, 1, entries=8)
    now = bundle.stat()
    assert (now.st_size, now.st_ino) == (was.st_size, was.st_ino), (
        "the point of this test is a file that changed without being replaced"
    )
    assert now.st_mtime_ns != was.st_mtime_ns, (
        "this file system does not record when a file changed finely enough for the "
        "change to be noticed, so this test cannot make its claim here"
    )

    # The pixels being compared against are the ones handed to the acquisition,
    # not what Zarr reads back now. Reading them back would go through the very
    # table that has just been altered, so it would agree with a stale answer as
    # readily as with a fresh one and the test would prove nothing.
    after = route.where_this_chunk_is((0, 0, 0, 0, 0))
    assert after is not None
    assert np.array_equal(
        decoded(the_bytes_of(after), tmp_path / "scratch", route),
        pixels[0:1, 0:1, 0:1, 0:128, 128:256],
    ), "the piece served came from the bundle as it used to be packed"


def test_a_position_the_run_is_still_writing_shows_what_arrives(tmp_path):
    """Ground that fills in later starts being advertised, without anything restarting.

    This is the worry that once kept bundle tables from being remembered at all.
    While a run is going, chunks are still landing in a bundle the viewer is
    already watching. A table kept from a moment ago would go on saying "nothing
    was ever written there", and an operator would watch a position stop filling in
    halfway and never recover, with nothing anywhere reporting a problem.
    """
    position, _ = a_position(
        tmp_path / "pos", written=(0, 0, 0, slice(0, 128), slice(0, 128))
    )
    route = route_the_view([Placed(position, lands_at=(0, 0, 0))])

    assert route.advertises((0, 0, 0, 0, 0)), "the corner that was written is missing"
    assert not route.advertises((0, 0, 0, 1, 1)), "nothing has been written there yet"

    arrived = some_specimen((128, 128), seed=77)
    zarr.open_array(str(position), mode="r+")[0, 0, 0, 128:256, 128:256] = arrived

    serving = route.where_this_chunk_is((0, 0, 0, 1, 1))
    assert serving is not None, "the chunk that has since arrived is still not advertised"
    assert np.array_equal(
        decoded(the_bytes_of(serving), tmp_path / "scratch", route),
        the_same_region(position, (0, 0, 0, 1, 1), CHUNK),
    )


def test_one_screenful_reads_one_bundles_table(tmp_path):
    """Every piece of a screenful out of one bundle costs one reading of its table.

    A count is checked rather than a stopwatch, because a count says the same thing
    on a busy machine as on an idle one. This is the whole benefit in one line: the
    eight pieces of this small position come out of one bundle, and that bundle's
    table is read once.
    """
    position, _ = a_position(tmp_path / "pos")
    route = route_the_view([Placed(position, lands_at=(0, 0, 0))])

    asked = 0
    for plane in range(2):
        for row in range(2):
            for column in range(2):
                assert route.where_this_chunk_is((0, 0, plane, row, column)) is not None
                asked += 1

    going = how_the_remembering_is_going()
    assert going.read_from_disk == 1, "the same bundle's table was read more than once"
    assert going.answered_from_memory == asked - 1


def test_a_positions_own_description_is_read_once_and_not_again(tmp_path):
    """The route reads each position's ``zarr.json`` when it is built, and never after.

    How a position is chunked, how it is bundled and what it calls its files are
    settled before any pixels are written, so re-reading that small file for every
    piece the viewer asks for buys nothing at all. It was worth doing something
    about only once the reading of bundle tables had stopped dominating; the
    measurement is in ``zmart_live/tests/measure_the_resolver.py``.
    """
    position, _ = a_position(tmp_path / "pos")
    route = route_the_view([Placed(position, lands_at=(0, 0, 0))])

    read_again: list[object] = []
    as_it_really_is = shardlink._read_the_array_description

    def note_that_it_was_read(array_path):
        read_again.append(array_path)
        return as_it_really_is(array_path)

    shardlink._read_the_array_description = note_that_it_was_read
    try:
        for column in range(2):
            assert route.where_this_chunk_is((0, 0, 0, 0, column)) is not None
    finally:
        shardlink._read_the_array_description = as_it_really_is

    assert read_again == [], (
        "the position's description was read again while answering requests, which "
        "it does not need to be"
    )
