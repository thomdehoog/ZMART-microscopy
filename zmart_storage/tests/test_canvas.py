"""Does a tile land where it was put, and is the rule about overlap enforced?

The arrangement this writer is for is **one image per acquisition type, with tiles
that do not overlap**. Most of what follows checks that ordinary path.

The rest checks the rule itself. Everything goes into one image, and one image
holds a single value per voxel, so if two tiles covered the same ground the
second to arrive would simply replace the strip they share. Nothing about the
resulting picture would look wrong, which is why the writer refuses such a run
when the image is declared rather than letting it happen quietly. The tests below
pin both the refusal and what it is protecting against.
"""

from __future__ import annotations

import re
import sys
import threading
import warnings
from pathlib import Path

import numpy as np
import pytest
import zarr

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from zmart_storage.canvas import Channel, TileCanvases

# Tiles 128 voxels across. With 64-voxel pieces and two levels of shrunk-down
# copies, a whole piece is 128 voxels -- so a tile is exactly one piece and tiles
# never share one, which is the arrangement to aim for.
TILE = (2, 128, 128)
BUTTED_UP = (2, 128, 128)    # the rule: the stage steps by a whole tile
OVERLAPPING = (2, 112, 112)  # a step this writer refuses
GRID = 4


def _canvases(folder: Path, *, step=BUTTED_UP, name="overview", **kwargs) -> TileCanvases:
    return TileCanvases.create(
        folder,
        name=name,
        canvas_shape=(2, 640, 640),
        tile_shape=TILE,
        tile_step=step,
        voxel_size_um=(2.0, 0.35, 0.35),
        channels=[Channel("488")],
        levels=2,
        chunk=64,
        **kwargs,
    )


def _write_a_grid(canvases: TileCanvases, step=BUTTED_UP) -> dict[tuple[int, int], int]:
    """Fill a small raster, each tile a flat value of its own.

    Giving every tile its own value is what makes the overlap question
    answerable: afterwards you can look at any voxel and say which tile it came
    from, so a tile that was written over is obvious rather than merely suspected.
    """
    expected = {}
    for row in range(GRID):
        for col in range(GRID):
            value = 1000 + row * GRID + col
            canvases.write(
                np.full(TILE, value, dtype="uint16"),
                origin=(0, row * step[1], col * step[2]),
                tile_index=(0, row, col),
            )
            expected[(row, col)] = value
    return expected


def _read_level0(store: Path) -> np.ndarray:
    """The full-resolution image as (z, y, x), whatever leading axes it declares.

    The writer declares five axes today — time, colour, and then the specimen's
    depth, height and width — but the tests below are about where a tile lands
    rather than about how many axes come before it. Counting from the end says
    that plainly, and it means these tests keep working if the description ever
    gains or loses an axis in front.
    """
    array = zarr.open_group(str(store), mode="r")["0"]
    return np.asarray(array[(0,) * (array.ndim - 3)])


# -- the rule ----------------------------------------------------------------


def test_a_run_with_overlapping_tiles_is_refused(tmp_path):
    """Overlap and one image do not go together, and saying so early is the point.

    Discovering it instead from a picture that looks subtly wrong, weeks later, is
    the outcome this prevents.
    """
    with pytest.raises(ValueError, match="these tiles overlap"):
        _canvases(tmp_path, step=OVERLAPPING)


def test_the_refusal_says_what_to_do_instead(tmp_path):
    """An error that only says no leaves the operator stuck.

    It must also not send them after something that is not here. This writer does
    not join overlapping tiles up afterwards and has no stitcher, so the advice
    has to be "acquire without overlap" and nothing else — an operator told to
    stitch would go looking for a capability that does not exist.
    """
    with pytest.raises(ValueError) as complaint:
        _canvases(tmp_path, step=OVERLAPPING)
    said = str(complaint.value)
    assert "step the stage by the whole tile" in said
    assert "does not support an overlapping acquisition" in said


def test_tiles_that_do_not_divide_into_pieces_are_only_a_warning(tmp_path):
    """Awkward sizes cost speed, not correctness, so they must not stop a run."""
    with pytest.warns(UserWarning, match="does not divide into whole pieces"):
        canvases = TileCanvases.create(
            tmp_path, name="overview",
            canvas_shape=(2, 640, 640),
            tile_shape=(2, 100, 100), tile_step=(2, 100, 100),
            voxel_size_um=(2.0, 0.35, 0.35),
            channels=[Channel("488")], levels=2, chunk=64,
        )
    canvases.write(np.full((2, 100, 100), 7, dtype="uint16"),
                   origin=(0, 0, 0), tile_index=(0, 0, 0))
    assert _read_level0(canvases.paths[0])[0, 50, 50] == 7


# -- not writing over a run that has already been imaged ----------------------
#
# Declaring the images empties whatever is already under their name. That is
# right at the start of a run, when nothing is there, and it is a disaster once a
# run has been imaged into that folder: the pictures go, and the newly declared
# images look perfectly healthy because an empty image is a valid one. A notebook
# cell run twice, or a script restarted after a crash, is all it takes.


def test_declaring_over_an_imaged_run_is_refused(tmp_path):
    """A folder that already holds acquired pictures must not be emptied."""
    first = _canvases(tmp_path)
    first.write(np.full(TILE, 4242, dtype="uint16"), origin=(0, 0, 0),
                tile_index=(0, 0, 0))

    with pytest.raises(ValueError, match="already an imaged run in this folder"):
        _canvases(tmp_path)


def test_the_refused_run_is_still_there_afterwards(tmp_path):
    """The refusal is worth nothing if the data went before it was raised.

    This is the check that matters: not that a complaint was made, but that the
    tiles the earlier run acquired are still readable once it has been made.
    """
    first = _canvases(tmp_path)
    first.write(np.full(TILE, 4242, dtype="uint16"), origin=(0, 0, 0),
                tile_index=(0, 0, 0))

    with pytest.raises(ValueError):
        _canvases(tmp_path)

    kept = _read_level0(first.paths[0])
    assert (kept[:, :TILE[1], :TILE[2]] == 4242).all(), (
        "the earlier run's tile was destroyed by the create() that was refused"
    )


def test_the_refusal_says_what_to_do_about_it(tmp_path):
    """An operator meeting this mid-experiment needs to be told their options."""
    first = _canvases(tmp_path)
    first.write(np.full(TILE, 4242, dtype="uint16"), origin=(0, 0, 0),
                tile_index=(0, 0, 0))

    with pytest.raises(ValueError) as complaint:
        _canvases(tmp_path)
    said = str(complaint.value)
    assert "a folder of its own" in said
    assert "discard_existing_run=True" in said


def test_a_folder_declared_but_never_imaged_into_can_be_declared_again(tmp_path):
    """Nothing was acquired, so there is nothing to protect and nothing to refuse.

    This keeps the guard from being a nuisance: setting a run up, changing your
    mind about its size and declaring it again is an ordinary thing to do, and it
    loses nobody's data.
    """
    _canvases(tmp_path)
    second = _canvases(tmp_path, frames=5)
    second.write(np.full(TILE, 7, dtype="uint16"), origin=(0, 0, 0),
                 tile_index=(0, 0, 0))
    assert _read_level0(second.paths[0])[0, 0, 0] == 7


def test_another_acquisition_type_can_still_be_declared_beside_it(tmp_path):
    """A run's folder holds each of its acquisition types side by side.

    The overview, the prescan and the targetscan are declared in separate calls
    into the one folder, so an imaged overview must not stand in the way of the
    prescan that follows it. Only images sharing a name are protected from each
    other, which is what makes the ordinary run still work.
    """
    overview = _canvases(tmp_path, name="overview")
    overview.write(np.full(TILE, 4242, dtype="uint16"), origin=(0, 0, 0),
                   tile_index=(0, 0, 0))

    prescan = _canvases(tmp_path, name="prescan")
    prescan.write(np.full(TILE, 7, dtype="uint16"), origin=(0, 0, 0),
                  tile_index=(0, 0, 0))

    assert _read_level0(overview.paths[0])[0, 0, 0] == 4242
    assert _read_level0(prescan.paths[0])[0, 0, 0] == 7


def test_an_earlier_run_can_be_thrown_away_when_that_is_said_outright(tmp_path):
    """Starting again from scratch is allowed; it just has to be asked for."""
    first = _canvases(tmp_path)
    first.write(np.full(TILE, 4242, dtype="uint16"), origin=(0, 0, 0),
                tile_index=(0, 0, 0))

    second = _canvases(tmp_path, discard_existing_run=True)
    assert _read_level0(second.paths[0]).max() == 0, (
        "asking to discard the earlier run left some of it behind"
    )


def test_an_earlier_run_is_thrown_away_even_while_something_is_reading_it(tmp_path):
    """Discarding a run must not be defeated by a watcher glancing at its files.

    Machines that image for a living run software that opens files the moment
    they change — a virus scanner reading what was just written, an indexer
    cataloguing it. On Windows a file being deleted only truly goes when the
    last open handle closes, so a tree being cleared under such a glance
    refuses to come down — 'directory is not empty', for ground that is clear a
    moment later. Measured on a lab PC before this was fixed: the discard
    raised WinError 145 whenever the endpoint protection was busy, which on
    that machine was most of the time.
    """
    first = _canvases(tmp_path)
    first.write(np.full(TILE, 4242, dtype="uint16"), origin=(0, 0, 0),
                tile_index=(0, 0, 0))

    held = next(
        piece for piece in sorted((tmp_path / "overview.ome.zarr").rglob("*"))
        if piece.is_file()
    ).open("rb")
    watcher = threading.Timer(0.3, held.close)
    watcher.start()
    try:
        second = _canvases(tmp_path, discard_existing_run=True)
    finally:
        watcher.join()
        held.close()
    assert _read_level0(second.paths[0]).max() == 0, (
        "asking to discard the earlier run left some of it behind"
    )


def test_a_name_with_brackets_in_it_is_protected_like_any_other(tmp_path):
    """The name of an acquisition type is text, and must be treated as text.

    A well on a plate, or a filter with its wavelength in square brackets, are
    perfectly ordinary things to call an acquisition. They mattered here because
    the check above used to ask the filesystem to find everything matching
    ``f"{name}*.ome.zarr"`` as a *pattern*, and in a pattern square brackets mean
    "any one of these letters" rather than brackets. So ``well[A1]`` matched
    nothing, the writer decided the folder was empty, and it emptied a run that
    had already been imaged: measured before this was fixed, the tile written
    below came back as zero.
    """
    first = _canvases(tmp_path, name="well[A1]")
    first.write(np.full(TILE, 4242, dtype="uint16"), origin=(0, 0, 0),
                tile_index=(0, 0, 0))

    with pytest.raises(ValueError, match="already an imaged run in this folder"):
        _canvases(tmp_path, name="well[A1]")

    kept = _read_level0(first.paths[0])
    assert (kept[:, :TILE[1], :TILE[2]] == 4242).all(), (
        "the run named well[A1] was destroyed by the create() that should have "
        "been refused"
    )


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows itself refuses '*' in a folder name; the refusal in words "
    "is checked in test_a_name_windows_cannot_hold_is_refused_in_words",
)
def test_a_name_with_a_star_in_it_can_be_declared_at_all(tmp_path):
    """A star in the name used to stop the very first declaration.

    It did so with a message about patterns — ``Invalid pattern: '**' can only be
    an entire path component`` — which says nothing at all to somebody who was
    only naming their sample. Now the name is simply a name, so the run starts,
    and it is protected afterwards like any other.
    """
    first = _canvases(tmp_path, name="scan*")
    first.write(np.full(TILE, 4242, dtype="uint16"), origin=(0, 0, 0),
                tile_index=(0, 0, 0))

    with pytest.raises(ValueError, match="already an imaged run in this folder"):
        _canvases(tmp_path, name="scan*")
    assert (_read_level0(first.paths[0])[:, :TILE[1], :TILE[2]] == 4242).all()


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="elsewhere 'scan*' is a perfectly good name, and the test above "
    "proves it stays one",
)
def test_a_name_windows_cannot_hold_is_refused_in_words(tmp_path):
    """Windows forbids ``*`` in a folder name, so the declaration cannot happen.

    Left to the operating system the refusal is ``[WinError 123] The filename,
    directory name, or volume label syntax is incorrect`` — which says nothing
    to somebody who was only naming their sample, and lands only after part of
    the run's folder has already been made. So the name is refused up front, in
    words that say which character is the problem and what to do about it.
    """
    with pytest.raises(ValueError, match="Windows"):
        _canvases(tmp_path, name="scan*")
    assert list(tmp_path.iterdir()) == [], (
        "the refusal left something behind in the run's folder"
    )


def test_a_name_that_begins_another_name_is_a_different_run(tmp_path):
    """``scan`` and ``scan_deep`` are two acquisition types, not one.

    The images belonging to a name are the one named after it and the numbered set
    a spread run makes, and nothing else. Asking instead for everything *beginning*
    with the name — which is what the old pattern did — reads an imaged
    ``scan_deep`` as though it were part of ``scan``, so the ``scan`` declared
    beside it is refused for a run that has nothing to do with it. An operator
    then cannot add an acquisition type to their own run folder, and the reason
    they are given names an image they never asked about.
    """
    deep = _canvases(tmp_path, name="scan_deep")
    deep.write(np.full(TILE, 4242, dtype="uint16"), origin=(0, 0, 0),
               tile_index=(0, 0, 0))

    shallow = _canvases(tmp_path, name="scan")
    shallow.write(np.full(TILE, 7, dtype="uint16"), origin=(0, 0, 0),
                  tile_index=(0, 0, 0))

    assert _read_level0(deep.paths[0])[0, 0, 0] == 4242, (
        "declaring scan emptied the images belonging to scan_deep"
    )
    assert _read_level0(shallow.paths[0])[0, 0, 0] == 7
    # And each is still protected in its own right, which is the other half of
    # getting this right: telling them apart must not mean protecting neither.
    with pytest.raises(ValueError, match="already an imaged run"):
        _canvases(tmp_path, name="scan")
    with pytest.raises(ValueError, match="already an imaged run"):
        _canvases(tmp_path, name="scan_deep")


def test_a_name_that_reaches_into_another_folder_is_refused(tmp_path):
    """The name has to be a name, because the check only looks in one folder.

    An acquisition type called ``prescans/overview`` would write its images one
    folder down, where the check for an already-imaged run does not look — so the
    protection would quietly not apply. Saying so plainly is better than leaving
    a run unprotected without anybody knowing.
    """
    with pytest.raises(ValueError, match="folder separator"):
        _canvases(tmp_path, name="prescans/overview")


# -- only one writer at a time -------------------------------------------------
#
# The check above notices a run that has already been *imaged*, which leaves a gap:
# two programs can declare the same folder before either has written a single tile,
# and both are then let through. After that they lose tiles, because everything
# that keeps a tile safe -- the record of where tiles have gone, and the record of
# which pieces of picture are being written at this moment -- is remembered by the
# writer rather than read back from disk, so neither writer can see the other's.
#
# So a writer says on disk that it has these images, in a way the operating system
# holds for it and releases by itself when the program ends. That last part is what
# keeps it from becoming a nuisance: a claim can never be left behind to block a
# run that has every right to start.

_A_SECOND_PROGRAM = """
import sys
sys.path.insert(0, {root!r})
from zmart_storage.canvas import Channel, TileCanvases

canvases = TileCanvases.create(
    {folder!r}, name="overview", canvas_shape=(2, 640, 640),
    tile_shape=(2, 128, 128), tile_step=(2, 128, 128),
    voxel_size_um=(2.0, 0.35, 0.35), channels=[Channel("488")],
    levels=2, chunk=64,
)
print("declared", flush=True)
# Wait to be told to finish, so that the test can try to declare these same
# images while this program still has them.
sys.stdin.readline()
"""


def _another_program_declaring(folder: Path):
    """Start a second program that declares ``folder`` and then waits.

    Two programs are what this needs; two writers inside one program are a
    different case, dealt with separately below. Returns once the other program
    says it has declared the images, so there is nothing racy about the test.
    """
    import subprocess

    root = str(Path(__file__).resolve().parents[2])
    other = subprocess.Popen(
        [sys.executable, "-c",
         _A_SECOND_PROGRAM.format(root=root, folder=str(folder))],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
    )
    said = other.stdout.readline().strip()
    assert said == "declared", (
        f"the second program did not get as far as declaring the images: {said!r}"
    )
    return other


def _let_it_finish(other) -> None:
    other.stdin.write("finish\n")
    other.stdin.close()
    other.wait(timeout=60)


def test_a_second_program_cannot_declare_the_same_images(tmp_path):
    """Two programs writing one acquisition lose tiles, so the second is refused.

    Measured before this was fixed, two writers set going this way lost voxels in
    every one of ten attempts: each placed its tiles by its own record, so tiles
    landing in the same piece of picture were written over each other and nothing
    was reported.
    """
    other = _another_program_declaring(tmp_path)
    try:
        with pytest.raises(ValueError, match="already has this run's"):
            _canvases(tmp_path)
    finally:
        _let_it_finish(other)


def test_the_refusal_names_what_is_in_the_way(tmp_path):
    """An operator meeting this needs to know which program to go and look at."""
    other = _another_program_declaring(tmp_path)
    try:
        with pytest.raises(ValueError) as complaint:
            _canvases(tmp_path)
        said = str(complaint.value)
        assert "overview.writing" in said
        assert str(other.pid) in said, (
            "the refusal does not say which program is holding the images"
        )
        assert "a folder of its own" in said
    finally:
        _let_it_finish(other)


def test_the_claim_goes_when_the_program_holding_it_ends(tmp_path):
    """A claim must never outlive the writer, or it would block honest runs.

    This is why the operating system is asked to hold the claim rather than a
    marker file being written by hand: the mark goes when the program does,
    whether it finished tidily, crashed, or the machine lost power. So there is
    never anything to clear away, and an operator is never told a run is in
    progress when nothing is running at all.
    """
    _let_it_finish(_another_program_declaring(tmp_path))

    canvases = _canvases(tmp_path)
    canvases.write(np.full(TILE, 7, dtype="uint16"), origin=(0, 0, 0),
                   tile_index=(0, 0, 0))
    assert _read_level0(canvases.paths[0])[0, 0, 0] == 7


def test_a_writer_declared_over_in_the_same_program_says_so(tmp_path):
    """Declaring twice in one program is allowed, but the older writer stops.

    Inside one program the earlier writer can be seen and set aside, which is
    what happens here: it is the ordinary case of a notebook cell run a second
    time, and refusing it would be unkind. What must not happen is the older
    writer carrying on, because declaring emptied the images and started a fresh
    record of where tiles have gone — so a tile written through the older one
    would be placed by a record that no longer matches the disk. It is refused
    loudly instead of losing anything quietly.
    """
    first = _canvases(tmp_path)
    second = _canvases(tmp_path)

    with pytest.raises(ValueError, match="declared again since this writer was made"):
        first.write(np.full(TILE, 4242, dtype="uint16"), origin=(0, 0, 0),
                    tile_index=(0, 0, 0))

    second.write(np.full(TILE, 7, dtype="uint16"), origin=(0, 0, 0),
                 tile_index=(0, 0, 0))
    assert _read_level0(second.paths[0])[0, 0, 0] == 7


def test_a_place_that_cannot_be_reserved_gets_a_warning_and_not_a_refusal(
    tmp_path, monkeypatch
):
    """Some network filesystems cannot do this, and a run must not depend on it.

    Microscope data often lives on a share, and a share that offers no way to
    reserve a file would otherwise make every run refuse to start. That is the
    wrong way round: it stops acquisitions that are perfectly fine, and an
    operator worked into a corner finds a way past the guard that is worse than
    what it was guarding against. So the check says out loud that it could not be
    made, and the run goes ahead.

    The share is imitated at the place the operating system would answer, by
    having the reserving call itself report that no locks are available — which
    is the answer a share with no lock manager gives. Asking at that level rather
    than replacing the writer's own function is deliberate: it exercises the whole
    path an operator would meet, including the writer's reading of what went
    wrong, and it does not have to be rewritten every time the code around it is
    tidied up.
    """
    import errno

    fcntl = pytest.importorskip(
        "fcntl", reason="only Unix reserves a file this way; Windows differs"
    )

    def no_locks_available(*_args, **_kwargs):
        raise OSError(errno.ENOLCK, "no locks available")

    monkeypatch.setattr(fcntl, "flock", no_locks_available)

    with pytest.warns(UserWarning, match="could not be checked"):
        canvases = _canvases(tmp_path)
    canvases.write(np.full(TILE, 7, dtype="uint16"), origin=(0, 0, 0),
                   tile_index=(0, 0, 0))
    assert _read_level0(canvases.paths[0])[0, 0, 0] == 7


def test_letting_go_of_a_run_lets_another_program_have_it(tmp_path):
    """A finished run can be handed on, which is what close() is for."""
    canvases = _canvases(tmp_path)
    canvases.close()

    other = _another_program_declaring(tmp_path)
    _let_it_finish(other)


# -- throwing an earlier run away ---------------------------------------------
#
# `discard_existing_run=True` is the operator saying outright that what is in this
# folder can be lost. When they say that, the whole of that acquisition type has to
# go. Leaving part of it behind is worse than useless: the leftovers still hold the
# earlier run's pixels, the viewer gathers a run's images by name and so shows the
# two mixed together as one acquisition, and every later declaration in that folder
# is refused because those leftovers are themselves an imaged run in the way.


def test_throwing_the_old_run_away_leaves_none_of_it_behind(tmp_path):
    """An imaged run, thrown away outright, must leave nothing of itself on disk.

    What is checked here is that the acquisition type's image is genuinely gone
    and empty afterwards, and that the folder is then in a state where the run can
    simply be declared again — which is what somebody repeating a test run into
    the same scratch folder needs.
    """
    first = _canvases(tmp_path)
    first.write(np.full(TILE, 500, dtype="uint16"),
                origin=(0, 0, 0), tile_index=(0, 0, 0))
    first.close()
    assert len(list(tmp_path.glob("*.ome.zarr"))) == 1

    second = _canvases(tmp_path, discard_existing_run=True)

    left = sorted(p.name for p in tmp_path.glob("*.ome.zarr"))
    assert left == ["overview.ome.zarr"], (
        f"the earlier run left images behind: {left}"
    )
    assert _read_level0(second.paths[0]).max() == 0
    # And with nothing of the old run in the way, the folder can be declared
    # again in the ordinary manner. Orphans left behind used to make every later
    # declaration here refuse, which is a corner an operator cannot get out of
    # without deleting files by hand.
    second.close()
    third = _canvases(tmp_path)
    third.write(np.full(TILE, 7, dtype="uint16"), origin=(0, 0, 0),
                tile_index=(0, 0, 0))
    assert _read_level0(third.paths[0])[0, 0, 0] == 7


def test_throwing_one_acquisition_type_away_leaves_the_others(tmp_path):
    """Only the acquisition type being declared may be thrown away.

    A run's folder holds an overview, a prescan and a targetscan side by side, and
    repeating the overview must not touch the rest. That includes an acquisition
    type whose name merely begins the same way, which is why ``overview_deep``
    is here.
    """
    prescan = _canvases(tmp_path, name="prescan")
    prescan.write(np.full(TILE, 111, dtype="uint16"), origin=(0, 0, 0),
                  tile_index=(0, 0, 0))
    deep = _canvases(tmp_path, name="overview_deep")
    deep.write(np.full(TILE, 222, dtype="uint16"), origin=(0, 0, 0),
               tile_index=(0, 0, 0))
    overview = _canvases(tmp_path, name="overview")
    overview.write(np.full(TILE, 333, dtype="uint16"), origin=(0, 0, 0),
                   tile_index=(0, 0, 0))

    _canvases(tmp_path, name="overview", discard_existing_run=True)

    assert _read_level0(prescan.paths[0])[0, 0, 0] == 111, "the prescan was thrown away too"
    assert _read_level0(deep.paths[0])[0, 0, 0] == 222, (
        "overview_deep was thrown away along with overview"
    )


# -- the ordinary path: one image, tiles butted up ---------------------------


def test_one_acquisition_type_is_one_image_named_after_it(tmp_path):
    """The viewer groups rows by this name, so it is what the operator sees."""
    canvases = _canvases(tmp_path)
    assert [p.name for p in canvases.paths] == ["overview.ome.zarr"]


def test_a_tile_lands_where_it_was_put(tmp_path):
    canvases = _canvases(tmp_path)
    tile = np.arange(2 * 128 * 128, dtype="uint16").reshape(TILE)

    canvases.write(tile, origin=(0, 128, 256), tile_index=(0, 1, 2))

    written = _read_level0(canvases.paths[0])
    assert np.array_equal(written[:, 128:256, 256:384], tile)
    # And nothing was scribbled outside it: a tile that landed in the wrong place
    # would still read back correctly at the place it was asked about.
    assert written[:, 0:128, :].max() == 0


def test_every_tile_survives_when_they_do_not_overlap(tmp_path):
    """The ordinary run: nothing is written over, because nothing is shared."""
    canvases = _canvases(tmp_path)
    expected = _write_a_grid(canvases)

    written = _read_level0(canvases.paths[0])
    for (row, col), value in expected.items():
        y0, x0 = row * BUTTED_UP[1], col * BUTTED_UP[2]
        patch = written[:, y0:y0 + TILE[1], x0:x0 + TILE[2]]
        assert (patch == value).all(), (
            f"tile ({row}, {col}) lost {int((patch != value).sum())} voxels"
        )


def test_the_smaller_copies_are_filled_in_as_tiles_arrive(tmp_path):
    """The zoomed-out view has to be right during a run, not only at the end."""
    canvases = _canvases(tmp_path)
    canvases.write(np.full(TILE, 4242, dtype="uint16"), origin=(0, 0, 128),
                   tile_index=(0, 0, 1))

    level1 = zarr.open_group(str(canvases.paths[0]), mode="r")["1"]
    half = np.asarray(level1[(0,) * (level1.ndim - 3)])
    # The whole of the tile's place in the half-size copy, not merely some of it.
    # Asking only whether 4242 appears anywhere in that block would be answered by
    # a single voxel, and a copy filled in one row at a time would pass.
    landed = half[:, 0:64, 64:128]
    assert (landed == 4242).all(), (
        f"{int((landed != 4242).sum())} of {landed.size} voxels of the tile's "
        f"place in the half-size copy were never filled in"
    )
    # And nothing was put anywhere else: a copy written at the wrong place would
    # still hold the right numbers, simply not where the tile was.
    outside = half.copy()
    outside[:, 0:64, 64:128] = 0
    assert outside.max() == 0, (
        "the half-size copy holds picture outside where the tile landed"
    )


def test_a_tile_beyond_the_declared_room_is_refused(tmp_path):
    """Better a clear complaint than a run that quietly loses its far edge."""
    canvases = _canvases(tmp_path)
    with pytest.raises(ValueError, match="past the declared room"):
        canvases.write(np.zeros(TILE, dtype="uint16"), origin=(0, 600, 0),
                       tile_index=(0, 0, 0))


def test_tiles_written_at_once_do_not_corrupt_each_other(tmp_path):
    """Neighbouring tiles arriving together must both survive intact.

    With tiles butted up and sized to whole pieces of image they never share one,
    so this should hold with no waiting at all. It is checked rather than assumed
    because the failure it guards against is silent: two writers in one piece each
    write the whole piece back, and the second erases the first.
    """
    import threading

    canvases = _canvases(tmp_path)
    values = [(111, 0), (222, 128), (333, 256), (444, 384)]

    def write(value, x0):
        canvases.write(np.full(TILE, value, dtype="uint16"),
                       origin=(0, 0, x0), tile_index=(0, 0, x0 // 128))

    threads = [threading.Thread(target=write, args=pair) for pair in values]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    written = _read_level0(canvases.paths[0])
    for value, x0 in values:
        patch = written[:, :TILE[1], x0:x0 + TILE[2]]
        assert (patch == value).all(), (
            f"the tile at x={x0} lost {int((patch != value).sum())} of its "
            f"{patch.size} voxels to a concurrent write"
        )


# -- writing at once into images that bundle their pieces ---------------------
#
# Zarr can keep many small pieces of an image together in one file, which is
# called *sharding*. It exists because a large run otherwise leaves millions of
# tiny files behind, which most filesystems handle badly.
#
# It matters here because the file, not the small piece inside it, is what gets
# read and written back whole. So two tiles landing in different small pieces of
# the same bundle collide just as surely as two tiles in one piece — and a writer
# that held tiles apart by the small piece would let them through. `create` does
# not bundle anything today, so these images are built by hand, which is also how
# they would arrive if bundling were switched on later.
#
# Building one by hand means naming `_Image`, which belongs to the writer's
# insides, and there is no way round that today: `create` cannot produce these
# arrangements, and handing the writer arrays somebody else made is not something
# it offers in public. Each of the two helpers below therefore borrows `_Image`
# where it needs it, rather than the whole file borrowing it at the top. That way,
# if the class is ever renamed, only these tests say so — instead of every test in
# this file failing to load at once and hiding whatever else might have broken.


def _built_by_hand(folder: Path, *, chunks, shards) -> TileCanvases:
    """One image with pieces of a chosen size, wired up to the writer directly."""
    from zmart_storage.canvas import _Image

    store = folder / "overview.ome.zarr"
    group = zarr.open_group(str(store), mode="w", zarr_format=3)
    array = group.create_array(
        "0", shape=(1, 1, 2, 512, 512), chunks=chunks, shards=shards, dtype="uint16"
    )
    return TileCanvases(
        folder,
        _Image(folder=store, arrays=[array]),
        shape=(1, 1, 2, 512, 512),
        levels=1,
        tile_shape=TILE,
    )


def test_tiles_sharing_a_bundle_survive_being_written_at_once(tmp_path):
    """Four tiles, four small pieces, one bundle: all four must still be there.

    Each tile has a piece of its own here, so a writer counting in small pieces
    sees nothing to wait for and lets all four go at once. They then rewrite the
    same bundle over each other. Measured on zarr 3.1.6 before this was fixed,
    three of the four tiles were simply gone, with nothing reported.
    """
    import threading

    canvases = _built_by_hand(
        tmp_path, chunks=(1, 1, 1, 128, 128), shards=(1, 1, 1, 256, 256)
    )
    values = [(11, 0), (22, 128), (33, 256), (44, 384)]

    def write(value, x0):
        canvases.write(np.full(TILE, value, dtype="uint16"),
                       origin=(0, 0, x0), tile_index=(0, 0, x0 // 128))

    threads = [threading.Thread(target=write, args=pair) for pair in values]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    written = _read_level0(canvases.paths[0])
    for value, x0 in values:
        patch = written[:, :TILE[1], x0:x0 + TILE[2]]
        assert (patch == value).all(), (
            f"the tile at x={x0} lost {int((patch != value).sum())} of its "
            f"{patch.size} voxels to a tile sharing its bundle"
        )


def _several_copies_by_hand(folder: Path, *, pieces) -> TileCanvases:
    """One image whose copies keep differently sized pieces.

    ``pieces`` gives the piece width of each progressively smaller copy, in that
    copy's own voxels. Built by hand because :meth:`TileCanvases.create` always
    uses the same piece size throughout, so it cannot produce this.
    """
    from zmart_storage.canvas import _Image

    store = folder / "overview.ome.zarr"
    group = zarr.open_group(str(store), mode="w", zarr_format=3)
    arrays = [
        group.create_array(
            str(level),
            shape=(1, 1, 2, 1024 // 2 ** level, 1024 // 2 ** level),
            chunks=(1, 1, 1, piece, piece), dtype="uint16",
        )
        for level, piece in enumerate(pieces)
    ]
    return TileCanvases(
        folder, _Image(folder=store, arrays=arrays),
        shape=(1, 1, 2, 1024, 1024), levels=len(pieces),
        tile_shape=TILE,
    )


def test_tiles_sharing_a_piece_of_a_full_size_copy_wait_for_each_other(tmp_path):
    """Each copy of the image is asked about its own pieces, not just the coarsest.

    A tile is written into every copy, so it can share a file with another tile in
    any of them. It is tempting to hold tiles apart by one figure — the piece of
    the smallest copy covers the most ground, so surely that covers the rest? It
    does not, and this is the case that shows why.

    The full-size copy here keeps 64 voxels in a piece and the half-size copy keeps
    50, which is 100 voxels of specimen. Holding tiles apart in blocks of 100 puts
    a boundary at voxel 200, and that boundary falls inside the full-size copy's
    piece covering 192 to 256. So the two tiles below were judged to share nothing
    and were written at once, and they lost 14336 voxels between them in 20 of 20
    attempts. Asking each copy about its own pieces has no such gap in it.

    Nothing :meth:`TileCanvases.create` can produce is arranged this way — every
    geometry it can make was tried, and none is at risk — so this is about the
    generality the writer claims rather than about the runs it writes today.
    """
    import threading

    canvases = _several_copies_by_hand(tmp_path, pieces=(64, 50))
    values = [(111, 72), (222, 200)]

    def write(value, x0):
        canvases.write(np.full(TILE, value, dtype="uint16"), origin=(0, 0, x0))

    threads = [threading.Thread(target=write, args=pair) for pair in values]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    written = _read_level0(canvases.paths[0])
    for value, x0 in values:
        patch = written[:, :TILE[1], x0:x0 + TILE[2]]
        assert (patch == value).all(), (
            f"the tile at x={x0} lost {int((patch != value).sum())} of its "
            f"{patch.size} voxels to a tile sharing a piece of the full-size copy"
        )


def test_pieces_holding_several_planes_are_refused(tmp_path):
    """The one arrangement the writer cannot keep safe, refused at the start.

    Tiles are held apart across the specimen by widening each claim to whole
    pieces, but in time, colour and depth the writer compares positions exactly.
    That is only right while a piece holds a single moment, a single colour and a
    single plane. A piece spanning two planes would let two tiles at different
    depths into the same file at once, so it is refused rather than risked.
    """
    with pytest.raises(ValueError, match="more than one moment, colour or plane"):
        _built_by_hand(tmp_path, chunks=(1, 1, 2, 128, 128), shards=None)


# -- how an acquisition first appears on screen --------------------------------


def _description(store: Path) -> dict:
    """An image's own OME-Zarr description, whichever generation it was written in.

    Version 0.4 keeps the description in a ``.zattrs`` file beside the image, and
    0.5 keeps it inside ``zarr.json`` under an ``ome`` key. Reading both here lets
    the tests below ask the same questions of either, which is the point: a run
    should describe itself the same way whichever generation it was written in.
    """
    import json

    if (store / ".zattrs").exists():
        return json.loads((store / ".zattrs").read_text(encoding="utf-8"))
    inside = json.loads((store / "zarr.json").read_text(encoding="utf-8"))
    return inside["attributes"]["ome"]


def _omero_channels(store: Path) -> list[dict]:
    return _description(store)["omero"]["channels"]


def _multiscale(store: Path) -> dict:
    """The block describing the image's axes, its copies and where it sits."""
    return _description(store)["multiscales"][0]


def test_a_channel_always_declares_a_complete_window(tmp_path):
    """Every channel states a whole brightness window, asked for or not.

    A channel's window has four numbers. ``min`` and ``max`` say what the camera
    can count between, which is a plain fact about the data. ``start`` and ``end``
    say what brightness the image should first be *displayed* between, which is a
    request about how it looks.

    This test used to say the opposite: that a run which asked for no window got
    no ``start`` and no ``end``, so that a viewer would measure a good one from
    the pixels instead. That reasoning was sound, but the file it produced was
    not. Measured against ngio, an image whose describing block names a channel
    without ``start`` and ``end`` fails to open at all, while the very same image
    with no describing block whatever opens perfectly well. So the real choice
    was never "a measured window or a declared one" — it was "a complete window
    or no channel names and colours at all". Names and colours are worth having,
    so a complete window is always written, and the camera's whole range is the
    honest thing to declare when nothing better is known.

    It is worth knowing what that looks like at the microscope. A real
    acquisition sits in the bottom few per cent of a camera's range: a few
    hundred counts of background with the signal not far above. An image opened
    on the camera's whole range therefore looks almost black until somebody drags
    the contrast slider. A run that knows roughly how bright its images are
    should pass a window, and its acquisitions will open looking like something.
    """
    canvases = _canvases(tmp_path)
    window = _omero_channels(canvases.paths[0])[0]["window"]

    for named in ("min", "max", "start", "end"):
        assert named in window, (
            f"the channel's window leaves out {named}: {window}. A describing "
            f"block with an incomplete window makes the whole image refuse to "
            f"open, so an acquisition written this way would not be readable at "
            f"all in ngio and tools like it."
        )
    # The camera's own range says what the numbers mean, and with nothing else
    # asked for it is also what the image opens on.
    assert (window["min"], window["max"]) == (0, 65535), (
        f"a 16-bit camera counts from 0 to 65535, but the channel says its "
        f"numbers run from {window['min']} to {window['max']}"
    )
    assert (window["start"], window["end"]) == (0, 65535), (
        f"no window was asked for, so the honest fallback is the camera's whole "
        f"range, 0 to 65535. The channel opens on {window['start']} to "
        f"{window['end']} instead."
    )

    # And a run that does say how bright its images are gets exactly what it
    # asked for, which is how an acquisition is made to open looking like
    # something rather than nearly black.
    asked = TileCanvases.create(
        tmp_path / "asked", name="overview",
        canvas_shape=(2, 640, 640),
        tile_shape=TILE, tile_step=BUTTED_UP,
        voxel_size_um=(2.0, 0.35, 0.35),
        channels=[Channel("488", window=(100, 4000))],
        levels=2, chunk=64,
    )
    chosen = _omero_channels(asked.paths[0])[0]["window"]
    assert (chosen["start"], chosen["end"]) == (100, 4000), (
        f"the run asked to be displayed between 100 and 4000 counts, but the "
        f"channel declares {chosen['start']} to {chosen['end']}, so the "
        f"acquisition would not open the way the run intended"
    )


def test_a_channel_given_a_window_still_gets_it(tmp_path):
    """Asking for a window is the way to override the measurement, and must work."""
    canvases = TileCanvases.create(
        tmp_path, name="overview",
        canvas_shape=(2, 640, 640),
        tile_shape=TILE, tile_step=BUTTED_UP,
        voxel_size_um=(2.0, 0.35, 0.35),
        channels=[Channel("488", window=(100, 4000))],
        levels=2, chunk=64,
    )
    window = _omero_channels(canvases.paths[0])[0]["window"]
    assert (window["start"], window["end"]) == (100, 4000)


def test_a_channel_is_named_and_coloured_the_way_it_was_asked_for(tmp_path):
    """The name and the colour are how an operator tells one channel from another.

    Both are written into the image itself so that the viewer never has to guess
    them from a file name. A run whose channels come back unnamed, or drawn in one
    another's colours, is one the operator cannot read at a glance — and nothing
    about the picture looks wrong, so there is nothing to notice.
    """
    canvases = TileCanvases.create(
        tmp_path, name="overview",
        canvas_shape=(2, 640, 640), tile_shape=TILE, tile_step=BUTTED_UP,
        voxel_size_um=(2.0, 0.35, 0.35),
        channels=[Channel("488"), Channel("nuclei", color="AABBCC")],
        levels=2, chunk=64,
    )
    described = _omero_channels(canvases.paths[0])

    assert [c["label"] for c in described] == ["488", "nuclei"], (
        "the channels are not named, or not in the order they were given in"
    )
    # A name that looks like an excitation wavelength picks up the conventional
    # colour for it, so a run written here looks like one from a mesoSPIM.
    assert described[0]["color"] == "00FF66", (
        f"the 488 channel came out {described[0]['color']} rather than the usual "
        f"green a 488 line is drawn in"
    )
    # And a colour asked for outright is used exactly as it was asked for.
    assert described[1]["color"] == "AABBCC"
    canvases.close()


def test_a_channel_nobody_has_a_colour_for_is_drawn_white(tmp_path):
    """Guessing a colour for an unfamiliar name would be worse than not trying.

    White says plainly that nothing is known about this one. A guessed colour
    would quietly suggest a wavelength the run never used, which is the kind of
    small untruth that survives into a figure.
    """
    canvases = TileCanvases.create(
        tmp_path, name="overview",
        canvas_shape=(2, 640, 640), tile_shape=TILE, tile_step=BUTTED_UP,
        voxel_size_um=(2.0, 0.35, 0.35),
        channels=[Channel("brightfield")],
        levels=2, chunk=64,
    )
    assert _omero_channels(canvases.paths[0])[0]["color"] == "FFFFFF"
    canvases.close()


# -- the numbers that make a measurement truthful ------------------------------
#
# On its own an image is only a grid of numbers. What turns it into a picture of a
# specimen — one you can put a scale bar on, measure a cell in, and lay beside the
# run's other images — is two small parts of its description: how large one voxel
# is in microns, and where the low corner of the image sits on the stage.
#
# Both are written once, when the images are declared, and never again. Nothing on
# screen looks wrong when they are wrong: the specimen still draws, it is simply
# the wrong size or in the wrong place, and there is no second copy of either
# number to disagree with. So they are read back off disk here rather than trusted.


@pytest.mark.parametrize("version", ["0.4", "0.5"])
def test_the_size_of_a_voxel_is_written_into_the_description(tmp_path, version):
    """Every measurement made in the viewer rests on this one line of description."""
    canvases = _canvases(tmp_path, ome_zarr_version=version)
    full_size = _multiscale(canvases.paths[0])["datasets"][0]
    # Each copy states two things: how large its voxels are, and where it begins on
    # the stage. Only the first is under examination here; the corner has tests of
    # its own further down.
    (transformation,) = [
        step for step in full_size["coordinateTransformations"]
        if step["type"] == "scale"
    ]

    # The last three numbers are the specimen's depth, height and width in microns.
    # The two in front of them are time and colour, which have no size in microns
    # and are left at one.
    assert transformation["type"] == "scale"
    assert transformation["scale"][-3:] == [2.0, 0.35, 0.35], (
        f"the run was declared with voxels of 2.0 by 0.35 by 0.35 microns, and the "
        f"image on disk says {transformation['scale'][-3:]}"
    )
    canvases.close()


@pytest.mark.parametrize("version", ["0.4", "0.5"])
def test_each_smaller_copy_says_how_much_ground_its_voxels_cover(tmp_path, version):
    """A copy that does not admit it was shrunk draws the specimen at the wrong size.

    Each smaller copy covers twice as much specimen per voxel as the one above it,
    and its description has to say so. If it does not, the viewer draws that copy
    at twice its true size the moment somebody zooms out — and the picture is
    perfectly good, simply too big, so nothing about it invites a second look.

    Depth is never shrunk, because scrolling through a stack should show the planes
    that were really acquired. So the depth of a voxel has to stay put while its
    height and width double.
    """
    canvases = _canvases(tmp_path, ome_zarr_version=version)
    copies = _multiscale(canvases.paths[0])["datasets"]
    assert len(copies) == 2, "this run was declared with two copies"

    for level, copy in enumerate(copies):
        (transformation,) = [
            step for step in copy["coordinateTransformations"]
            if step["type"] == "scale"
        ]
        depth, height, width = transformation["scale"][-3:]
        assert copy["path"] == str(level)
        assert depth == 2.0, (
            f"copy {level} claims voxels {depth} microns deep, but a smaller copy "
            f"keeps every plane and so must keep the depth it started with"
        )
        assert (height, width) == (0.35 * 2 ** level, 0.35 * 2 ** level), (
            f"copy {level} claims voxels {height} microns across, where halving "
            f"{level} time(s) makes them {0.35 * 2 ** level}"
        )
    canvases.close()


@pytest.mark.parametrize("version", ["0.4", "0.5"])
def test_where_the_images_sit_on_the_stage_is_written_down(tmp_path, version):
    """The image has to say where on the stage it begins, or it draws in the wrong place.

    A run's acquisition types are drawn together — an overview with a targetscan
    laid over it — and each one carries this number separately. Were they to
    disagree about where their corner sits, the viewer would draw the specimen
    twice over, slightly apart, which looks like a stage that cannot repeat itself
    rather than like a description that is wrong.

    The number given is the **corner** of the first voxel, not its middle. Which of
    those two the OME-Zarr standard intends is genuinely unsettled, and
    ``zmart_storage/VOXEL_PLACEMENT.md`` sets out the evidence and why this writer
    chose the corner. It is checked here so that nobody changes it by accident.

    It is written beside **each** resolution rather than once for the image as a
    whole. Both places are allowed by the format, but only the per-resolution one
    is compulsory, so it is the place every reader looks. Writing it in both would
    be worse than picking wrongly: a reader applies the second to the result of the
    first, so the image would be placed twice as far from the stage's zero as it
    really is.
    """
    corner = (10.0, 250.5, 900.25)
    canvases = _canvases(tmp_path, origin_um=corner, ome_zarr_version=version)

    (store,) = canvases.paths
    multiscale = _multiscale(store)

    assert "coordinateTransformations" not in multiscale, (
        f"{store.name} states its corner beside the list of copies as well as "
        f"beside each copy. A reader that composes the two — which the format "
        f"asks for, and which neuroglancer does — would draw the image at twice "
        f"its true distance from the stage's zero."
    )

    for level, copy in enumerate(multiscale["datasets"]):
        placements = [
            step for step in copy["coordinateTransformations"]
            if step["type"] == "translation"
        ]
        assert placements, (
            f"copy {level} of {store.name} does not say where it begins. A reader "
            f"that looks only beside the copy — which is the compulsory place, and "
            f"so the usual one — would draw it at the stage's zero, on top of every "
            f"other acquisition in the run."
        )
        (placement,) = placements
        assert placement["translation"][-3:] == list(corner), (
            f"copy {level} of {store.name} puts its corner at "
            f"{placement['translation'][-3:]}, where the run was declared "
            f"from {list(corner)} — so it would be drawn away from the run's other "
            f"acquisition types"
        )
    canvases.close()


# -- what the rule is protecting against -------------------------------------


def test_writing_an_overlapping_run_into_one_image_would_lose_a_fifth(tmp_path):
    """The cost the refusal exists to prevent, as a measured number.

    The refusal happens when the images are declared, so getting past it here
    means declaring a perfectly ordinary run whose stage steps by a whole tile,
    and then putting the tiles down at overlapping positions anyway. That is
    exactly the acquisition the refusal turns away, and what follows is the price
    of letting it through.
    """
    canvases = _canvases(tmp_path)
    expected = _write_a_grid(canvases, step=OVERLAPPING)

    written = _read_level0(canvases.paths[0])
    lost = 0
    for (row, col), value in expected.items():
        y0, x0 = row * OVERLAPPING[1], col * OVERLAPPING[2]
        patch = written[:, y0:y0 + TILE[1], x0:x0 + TILE[2]]
        lost += int((patch != value).sum())

    total = len(expected) * int(np.prod(TILE))
    share = lost / total
    print(f"\none image, tiles overlapping: {lost} of {total} voxels overwritten "
          f"({100 * share:.0f}% of what was acquired)")

    # The name of this test is a number, so the number is what is checked. These
    # tiles are 128 voxels across and stepped 112, so each one loses the strip its
    # neighbours to the right and below cover it with, and about a fifth of
    # everything acquired disappears — 18 per cent as measured here.
    #
    # A band rather than an exact figure, because the point is the size of the
    # loss rather than its last digit. Asking only that *something* was lost would
    # be satisfied by a single voxel, which would let the writer stop being
    # dangerous without anybody noticing that the case for the refusal had gone.
    assert 0.10 < share < 0.30, (
        f"{100 * share:.1f}% of what was acquired was overwritten, where writing "
        f"these overlapping tiles into one image should cost about a fifth of it. "
        f"If the loss has genuinely changed, the refusal this measures is worth "
        f"re-examining rather than the number simply being widened."
    )


# -- moments, declared at the start and filled in ------------------------------
#
# Time is declared the way the room in space is: comfortably more than the run
# could need, and filled in as the experiment goes. What makes that safe is that
# the viewer counts what has actually been written and stops the time slider
# there, so an operator is never offered a moment that was never imaged.


def test_a_run_declares_the_moments_it_was_given_room_for(tmp_path):
    """The length in time is what the run asked for, before anything is written."""
    canvases = _canvases(tmp_path, frames=500)
    array = zarr.open_group(str(canvases.paths[0]), mode="r")["0"]
    assert array.shape[0] == 500, (
        f"a run declared with room for 500 moments says {array.shape[0]}"
    )


def test_declaring_many_moments_costs_almost_nothing_on_disk(tmp_path):
    """The whole case for declaring generously, checked rather than assumed.

    A moment nothing has been written to occupies no space at all, so a run with
    room for ten thousand moments is the same size on disk as one with room for
    two. If this were not true, declaring generously would be a way of filling an
    operator's disk with emptiness before their experiment had begun.
    """
    small = _canvases(tmp_path / "small", frames=2)
    large = _canvases(tmp_path / "large", frames=10_000)
    for canvases in (small, large):
        canvases.write(np.full(TILE, 1234, dtype="uint16"), origin=(0, 0, 0),
                       frame=0, tile_index=(0, 0, 0))

    def on_disk(canvases):
        return sum(p.stat().st_size for p in canvases.folder.rglob("*") if p.is_file())

    # A few hundred bytes of difference is the length written into the
    # descriptions; what must not happen is that it grows with the moments.
    assert on_disk(large) < on_disk(small) + 4096, (
        f"room for ten thousand moments cost {on_disk(large) - on_disk(small)} "
        "bytes more than room for two"
    )


def test_each_moment_keeps_its_own_picture(tmp_path):
    """One moment's tiles must not appear in another's.

    Checked rather than trusted, because the two would look identical on screen
    if the frame index were being dropped somewhere -- an operator stepping
    through time would see the same picture and take it for a specimen that had
    not moved.
    """
    canvases = _canvases(tmp_path, frames=50)
    for moment in (0, 7, 49):
        canvases.write(np.full(TILE, 1000 + moment, dtype="uint16"),
                       origin=(0, 0, 0), frame=moment, tile_index=(0, 0, 0))

    array = zarr.open_group(str(canvases.paths[0]), mode="r")["0"]
    for moment in (0, 7, 49):
        recorded = np.asarray(array[moment, 0, :, 0:TILE[1], 0:TILE[2]])
        assert (recorded == 1000 + moment).all(), (
            f"moment {moment} is not showing its own picture"
        )


def test_a_moment_never_written_to_reads_as_empty(tmp_path):
    """Room declared but never used is empty, not stale or invented."""
    canvases = _canvases(tmp_path, frames=50)
    canvases.write(np.full(TILE, 4242, dtype="uint16"), origin=(0, 0, 0),
                   frame=4, tile_index=(0, 0, 0))
    array = zarr.open_group(str(canvases.paths[0]), mode="r")["0"]
    assert int(np.asarray(array[2]).max()) == 0, "an unused moment is not empty"
    assert int(np.asarray(array[4, 0, 0, 0, 0])) == 4242


def test_a_moment_past_the_declared_room_is_refused(tmp_path):
    """Running off the end of time is refused the way running off the canvas is.

    Silently making room would put the run back to lengthening itself, and doing
    it quietly. Saying so lets the operator declare a longer run, which is the
    only real fix and is free.
    """
    canvases = _canvases(tmp_path, frames=3)
    with pytest.raises(ValueError, match="declared room for"):
        canvases.write(np.full(TILE, 7, dtype="uint16"), origin=(0, 0, 0),
                       frame=3, tile_index=(0, 0, 0))


# --------------------------------------------------------------------------
# A tile is only in the way of another in the same moment and the same colour
# --------------------------------------------------------------------------
#
# These guard a fault that made a whole way of running an experiment impossible.
# When a tile is written without saying where it sits in a scan pattern -- which is
# what a workflow choosing its own targets does, and which the writer documents as
# perfectly ordinary -- the writer asks each image whether the tile would land on
# something already in it. That question used to compare only *where* the tile sat,
# ignoring which moment and which colour it belonged to.
#
# So imaging a target and then imaging the same target again at the next moment was
# refused, with a message saying the second would destroy the first. It would not:
# an image holds every moment separately, and the two land in different slices of
# it. A timelapse of workflow-chosen targets therefore could not be written past its
# first moment, and a two-colour target could not have its second colour written at
# all.
#
# Nothing caught it because every existing test passes ``tile_index``, which takes
# the scan-pattern path and never reaches the comparison at all.


def _targets(folder: Path) -> TileCanvases:
    """A run with two colours and room for several moments."""
    return TileCanvases.create(
        folder,
        name="targetscan",
        canvas_shape=(2, 640, 640),
        tile_shape=TILE,
        tile_step=BUTTED_UP,
        voxel_size_um=(2.0, 0.35, 0.35),
        channels=[Channel("488"), Channel("561")],
        frames=10,
        levels=2,
        chunk=64,
    )


def test_the_same_target_can_be_imaged_again_at_the_next_moment(tmp_path):
    """A timelapse of chosen targets, which is the ordinary way of watching one."""
    canvases = _targets(tmp_path / "run")
    for moment in (0, 1, 2):
        canvases.write(
            np.full(TILE, 1000 + moment, dtype="uint16"), origin=(0, 0, 0), frame=moment
        )

    array = zarr.open_group(str(canvases.paths[0]), mode="r")["0"]
    for moment in (0, 1, 2):
        recorded = np.asarray(array[moment, 0, :, 0:TILE[1], 0:TILE[2]])
        assert (recorded == 1000 + moment).all(), (
            f"moment {moment} did not keep its own picture"
        )
    canvases.close()


def test_the_same_target_can_be_imaged_in_a_second_colour(tmp_path):
    canvases = _targets(tmp_path / "run")
    for colour in (0, 1):
        canvases.write(
            np.full(TILE, 2000 + colour, dtype="uint16"), origin=(0, 0, 0), channel=colour
        )

    array = zarr.open_group(str(canvases.paths[0]), mode="r")["0"]
    for colour in (0, 1):
        recorded = np.asarray(array[0, colour, :, 0:TILE[1], 0:TILE[2]])
        assert (recorded == 2000 + colour).all(), (
            f"colour {colour} did not keep its own picture"
        )
    canvases.close()


def test_the_same_place_twice_in_one_moment_is_still_refused(tmp_path):
    """The check must still do the job it was written for.

    Without this the two tests above could be satisfied by removing the check
    altogether, which would let a run quietly destroy its own tiles.
    """
    canvases = _targets(tmp_path / "run")
    canvases.write(np.full(TILE, 1, dtype="uint16"), origin=(0, 0, 0))
    with pytest.raises(ValueError, match="already been imaged in this moment"):
        canvases.write(np.full(TILE, 2, dtype="uint16"), origin=(0, 0, 0))
    canvases.close()


# -- how many smaller copies a canvas gets ------------------------------------
#
# The viewer fetches the whole of the smallest copy, for every colour, before it
# draws anything at all, and it does that again at every zoom. So the number of
# pieces that copy is stored in is what an operator waits through when a view
# opens, and the way to keep the wait short is to let the copies keep halving
# until the smallest one is only about a thousand voxels across.
#
# A fixed number of copies cannot do that, because a canvas covering the whole
# stage is fifty times wider than a single tile. The tests below are about the
# writer choosing the number for itself from the room that was declared, and they
# read the answer from the arrays that are actually on disk rather than from the
# argument that was passed in -- so they check what a run really got.


def _copy_shapes(store: Path) -> list[tuple[int, int]]:
    """How wide every progressively smaller copy of an image is, in y and x.

    Read from the store itself, level by level, so that these tests describe the
    run somebody would open rather than the request that produced it.
    """
    group = zarr.open_group(str(store), mode="r")
    shapes = []
    level = 0
    while str(level) in group:
        shape = group[str(level)].shape
        shapes.append((int(shape[-2]), int(shape[-1])))
        level += 1
    return shapes


def _a_canvas_this_wide(folder: Path, width: int, **kwargs) -> TileCanvases:
    """A run declared ``width`` voxels across the specimen, with ordinary tiles.

    Two thousand voxels is an everyday camera tile and 256 is the everyday piece
    size, so the only thing that changes between these tests is how much room the
    run declared -- which is exactly the thing the number of copies should follow.
    """
    return TileCanvases.create(
        folder,
        name="overview",
        canvas_shape=(2, width, width),
        voxel_size_um=(2.0, 0.35, 0.35),
        channels=[Channel("488")],
        chunk=256,
        **{"tile_shape": (2, 2048, 2048), "tile_step": (2, 2048, 2048), **kwargs},
    )


def test_a_tile_sized_canvas_still_gets_the_copies_it_got_before(tmp_path):
    """A small run must not come out of this with less than it had.

    An image the size of one camera tile was already served well by three copies,
    and the point of choosing the number from the declared room is to help the
    large runs -- not to take anything away from the small ones. So three is a
    floor rather than a starting point.
    """
    canvases = _a_canvas_this_wide(tmp_path / "run", 2048)
    shapes = _copy_shapes(canvases.paths[0])
    assert len(shapes) >= 3, (
        f"a tile-sized canvas used to get three smaller copies and now gets "
        f"{len(shapes)}, which would make ordinary tiles worse than before"
    )
    canvases.close()


def test_a_stage_sized_canvas_gets_enough_copies_to_open_quickly(tmp_path):
    """The whole reason for the change, asked of the arrays on disk.

    A hundred thousand voxels is about what a stage can travel across the
    specimen. With a fixed three copies the smallest is still twenty-five
    thousand voxels across, which is tens of thousands of pieces for the viewer
    to fetch before it draws its first picture. Letting the halving continue
    until the smallest copy is about a thousand voxels brings that down to a few
    dozen pieces.
    """
    canvases = _a_canvas_this_wide(tmp_path / "run", 100_000)
    shapes = _copy_shapes(canvases.paths[0])
    coarsest = max(shapes[-1])
    assert coarsest <= 1024, (
        f"the smallest copy of a stage-sized canvas is {coarsest} voxels across, "
        f"which is far more than the viewer can fetch before it draws; the copies "
        f"are {shapes}"
    )
    canvases.close()


def test_asking_for_a_number_of_copies_outright_is_still_obeyed(tmp_path):
    """Choosing a sensible number by default must not take the choice away.

    A run with a reason of its own -- a measurement, or a store being written to
    match one somebody else made -- can still say how many copies it wants, and
    that answer wins over anything worked out from the declared room.
    """
    canvases = _a_canvas_this_wide(tmp_path / "run", 100_000, levels=2)
    shapes = _copy_shapes(canvases.paths[0])
    assert len(shapes) == 2, (
        f"the run asked for two smaller copies outright and got {len(shapes)}"
    )
    canvases.close()


def test_the_copies_stop_halving_before_they_become_too_small(tmp_path):
    """There is a floor, and the halving stops at it rather than going past.

    Halving is done in whole steps, so the smallest copy can land anywhere
    between about five hundred and about a thousand voxels across. Five hundred
    is the floor: below that the copy stops being a useful overview of the
    specimen and starts being a thumbnail, and the reading it saves is no longer
    worth the writing it costs on every tile.

    A canvas of a little over four thousand voxels is the tightest case there is.
    It is just past the point where a fourth copy is called for, so that fourth
    copy lands exactly on the floor -- and a fifth would fall well below it.
    """
    for width in (4_100, 20_000, 100_000, 1_000_000):
        canvases = _a_canvas_this_wide(tmp_path / f"run_{width}", width)
        coarsest = max(_copy_shapes(canvases.paths[0])[-1])
        assert coarsest >= 512, (
            f"a canvas {width} voxels across was shrunk down to {coarsest}, which "
            f"is smaller than a useful overview of the specimen"
        )
        canvases.close()

    canvases = _a_canvas_this_wide(tmp_path / "tightest", 4_100)
    coarsest = max(_copy_shapes(canvases.paths[0])[-1])
    assert coarsest <= 1024, (
        f"a canvas of 4100 voxels should have been halved once more than a "
        f"tile-sized one, leaving {coarsest} voxels rather than stopping early"
    )
    canvases.close()


def test_a_wildly_large_declaration_cannot_ask_for_endless_copies(tmp_path):
    """Over-declaring the room is encouraged, so it must not become expensive.

    Every copy is more to write on every single tile, so the number cannot be
    allowed to follow an unreasonable declaration upwards without limit. Ten
    copies shrink an image by five hundred times, which is more than enough for
    any stage that exists; beyond that the writer simply stops adding them.
    """
    canvases = _a_canvas_this_wide(tmp_path / "run", 10_000_000)
    shapes = _copy_shapes(canvases.paths[0])
    assert len(shapes) == 10, (
        f"a canvas declared absurdly large asked for {len(shapes)} smaller "
        f"copies, and the writer is meant to stop at ten"
    )
    canvases.close()


def test_a_tile_still_arrives_whole_in_the_coarsest_copy(tmp_path):
    """More copies must not mean a broken one.

    Each smaller copy is filled in as the tile is written, by taking every second
    voxel of the one before it, and each of them has to be told where in itself
    the tile lands. Adding copies makes that arithmetic reach much further -- the
    smallest copy of a stage-sized canvas shrinks the picture by a hundred and
    twenty-eight times -- so it is worth reading a tile back from the smallest
    copy and checking that it really is there, in the right place, with the right
    numbers in it.
    """
    canvases = _a_canvas_this_wide(tmp_path / "run", 100_000)
    shapes = _copy_shapes(canvases.paths[0])
    assert max(shapes[-1]) <= 1024, (
        "this test is only meaningful on a canvas whose copies were allowed to "
        f"keep halving, and these stopped at {shapes[-1]}"
    )

    tile, at_y, at_x = (2, 2048, 2048), 2048, 4096
    canvases.write(
        np.full(tile, 4321, dtype="uint16"),
        origin=(0, at_y, at_x),
        tile_index=(0, 1, 2),
    )

    factor = 2 ** (len(shapes) - 1)
    coarsest = zarr.open_group(str(canvases.paths[0]), mode="r")[str(len(shapes) - 1)]
    patch = np.asarray(coarsest[
        0, 0, :,
        at_y // factor:(at_y + tile[1]) // factor,
        at_x // factor:(at_x + tile[2]) // factor,
    ])
    assert patch.size > 0, "the tile occupies nothing at all in the smallest copy"
    assert (patch == 4321).all(), (
        f"the tile does not read back whole from the smallest copy: "
        f"{int((patch != 4321).sum())} of {patch.size} voxels are something else"
    )
    canvases.close()


def test_a_deeper_pyramid_does_not_warn_about_an_ordinary_camera_tile(tmp_path):
    """A wide run must not greet the operator with advice they cannot take.

    The writer keeps two tiles from being written into the same file at the same
    moment, and it warns when the tile size makes that happen often. That warning
    is useful only while the operator can do something about it.

    Every smaller copy doubles the ground one piece of image covers, so on a
    stage-sized canvas -- which now keeps eight copies rather than three -- the
    coarsest piece covers thirty-two thousand voxels. No camera tile divides into
    that, and none ever will. Measuring against it would put a warning on every
    large run suggesting a tile size no microscope can produce, which is how
    people learn to stop reading warnings.

    So the comparison stops at the largest piece a tile this size could actually
    line up with. Two thousand voxels is an everyday camera tile and it is a whole
    number of 256-voxel pieces, so a wide run says nothing.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("error", UserWarning)
        canvases = _a_canvas_this_wide(tmp_path / "run", 100_000)
    canvases.close()


def test_an_awkward_tile_is_still_pointed_out_on_a_wide_run(tmp_path):
    """And the warning must not have been quietened into uselessness.

    A tile of 1500 voxels is not a whole number of 256-voxel pieces however many
    copies the run keeps, so this is the case the operator genuinely can act on
    and it still has to be said -- with a size they could actually set the camera
    to, rather than one in the tens of thousands.
    """
    with pytest.warns(UserWarning, match="does not divide into whole pieces") as said:
        canvases = _a_canvas_this_wide(
            tmp_path / "run", 100_000,
            tile_shape=(2, 1500, 1500), tile_step=(2, 1500, 1500),
        )
    canvases.close()
    suggested = int(re.search(r"a tile of (\d+) voxels would avoid",
                              str(said[0].message)).group(1))
    assert suggested <= 4096, (
        f"the writer suggested a tile of {suggested} voxels, which is far larger "
        f"than any camera -- advice nobody can follow"
    )
