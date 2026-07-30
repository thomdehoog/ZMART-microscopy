"""Does a tile land where it was put, and is the rule about overlap enforced?

The arrangement this writer is for is **one image per acquisition type, with tiles
that do not overlap**. Most of what follows checks that ordinary path.

The rest checks the rule itself. A run whose tiles overlap must not be written
into one image as it goes, because the second tile to arrive replaces the strip
it shares with the first — and those two recordings of the shared strip are
exactly what a stitcher compares. Such a run keeps its tiles separate and is
stitched once it has finished. The writer refuses rather than letting it happen
quietly, and the tests below pin both the refusal and what it is protecting
against.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
import zarr

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from zmart_storage.canvas import Channel, TileCanvases, _Slot, slots_per_axis

# Tiles 128 voxels across. With 64-voxel pieces and two levels of shrunk-down
# copies, a whole piece is 128 voxels -- so a tile is exactly one piece and tiles
# never share one, which is the arrangement to aim for.
TILE = (2, 128, 128)
BUTTED_UP = (2, 128, 128)    # the rule: the stage steps by a whole tile
OVERLAPPING = (2, 112, 112)  # a run that must be stitched afterwards instead
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

    A run of a single moment has no time axis, so the number of indexes to step
    past before reaching the planes is not fixed. Counting from the end keeps the
    tests honest about that instead of assuming a shape.
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
    """An error that only says no leaves the operator stuck."""
    with pytest.raises(ValueError) as complaint:
        _canvases(tmp_path, step=OVERLAPPING)
    said = str(complaint.value)
    assert "step the stage by the whole tile" in said
    assert "stitch" in said


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
    """
    from zmart_storage import canvas as canvas_module

    def cannot(_handle):
        raise canvas_module._CannotBeMarkedHere("this share does not offer it")

    monkeypatch.setattr(canvas_module, "_ask_for_the_mark", cannot)

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
    """A run spread over four images, thrown away for one that needs a single image.

    The four numbered images belong to the same acquisition type, so all four go.
    Before this was fixed, only the one the new arrangement happened to reuse was
    replaced and the other three stayed on disk holding the old run's pixels.
    """
    first = _canvases(tmp_path, step=OVERLAPPING, slots=(1, 2, 2))
    for index in range(4):
        first.write(np.full(TILE, 500 + index, dtype="uint16"),
                    origin=(0, 0, index * TILE[2]), tile_index=(0, 0, index))
    assert len(list(tmp_path.glob("*.ome.zarr"))) == 4

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


@pytest.mark.parametrize(
    ("tile", "step", "wanted"),
    [
        (64, 64, 1),   # butted up, which is the rule: one image is enough
        (64, 58, 2),   # a tenth of a tile shared
        (64, 32, 2),   # exactly half: still two
        (64, 24, 3),   # more than half, which no tiled acquisition does
    ],
)
def test_how_many_images_an_overlapping_run_would_need(tile, step, wanted):
    """Only relevant to a run being spread deliberately, but worth pinning."""
    assert slots_per_axis(tile, step) == wanted


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
    assert half[:, 0:64, 64:128].max() == 4242


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


def _built_by_hand(folder: Path, *, chunks, shards) -> TileCanvases:
    """One image with pieces of a chosen size, wired up to the writer directly."""
    store = folder / "overview.ome.zarr"
    group = zarr.open_group(str(store), mode="w", zarr_format=3)
    array = group.create_array(
        "0", shape=(1, 1, 2, 512, 512), chunks=chunks, shards=shards, dtype="uint16"
    )
    return TileCanvases(
        folder,
        [_Slot(index=0, folder=store, arrays=[array])],
        shape=(1, 1, 2, 512, 512),
        levels=1,
        tile_shape=TILE,
        slot_grid=(1, 1, 1),
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


def _two_images_by_hand(folder: Path, *, second_chunks) -> TileCanvases:
    """A run of two images, the second stored differently from the first.

    A run's images are normally stored identically, but nothing guarantees it, and
    the writer used to take the first image's answer for all of them. These are
    wired up directly so that the second image can be given a shape of its own.
    """
    slots = []
    for index, chunks in enumerate([(1, 1, 1, 128, 128), second_chunks]):
        store = folder / f"overview_part{index}.ome.zarr"
        group = zarr.open_group(str(store), mode="w", zarr_format=3)
        array = group.create_array(
            "0", shape=(1, 1, 2, 512, 512), chunks=chunks, dtype="uint16"
        )
        slots.append(_Slot(index=index, folder=store, arrays=[array]))
    return TileCanvases(
        folder, slots, shape=(1, 1, 2, 512, 512), levels=1,
        tile_shape=TILE, slot_grid=(1, 2, 1),
    )


def test_every_image_is_asked_how_it_keeps_its_pieces(tmp_path):
    """The arrangement the writer cannot keep safe is refused wherever it appears.

    A piece that holds two planes lets two tiles at different depths into one file
    at the same moment, which is why it is refused. Only the first image used to be
    asked, so a run whose *second* image was like that was accepted — and then,
    measured before this was fixed, two tiles at different depths into that image
    lost one of them entirely in 3 of 3 attempts.
    """
    with pytest.raises(ValueError, match="more than one moment, colour or plane"):
        _two_images_by_hand(tmp_path, second_chunks=(1, 1, 2, 128, 128))


def test_tiles_are_held_apart_by_the_image_they_land_in(tmp_path):
    """How large a piece is depends on the image, so each image speaks for itself.

    The two tiles here land in one image whose pieces are 512 voxels wide, so they
    share a file and have to be written one after the other. The other image in the
    run keeps 128 voxels in a piece, and taking that figure for both — which is
    what happened before — let these two go at once and one of them was lost.
    """
    import threading

    canvases = _two_images_by_hand(tmp_path, second_chunks=(1, 1, 1, 512, 512))
    values = [(111, 0), (222, 128)]

    def write(value, x0):
        # Both into the second image, which is what tile_index (0, 1, 0) chooses.
        canvases.write(np.full(TILE, value, dtype="uint16"),
                       origin=(0, 0, x0), tile_index=(0, 1, 0))

    threads = [threading.Thread(target=write, args=pair) for pair in values]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    written = _read_level0(canvases.paths[1])
    for value, x0 in values:
        patch = written[:, :TILE[1], x0:x0 + TILE[2]]
        assert (patch == value).all(), (
            f"the tile at x={x0} lost {int((patch != value).sum())} of its "
            f"{patch.size} voxels to a tile sharing its file"
        )


def _several_copies_by_hand(folder: Path, *, pieces) -> TileCanvases:
    """One image whose copies keep differently sized pieces.

    ``pieces`` gives the piece width of each progressively smaller copy, in that
    copy's own voxels. Built by hand because :meth:`TileCanvases.create` always
    uses the same piece size throughout, so it cannot produce this.
    """
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
        folder, [_Slot(index=0, folder=store, arrays=arrays)],
        shape=(1, 1, 2, 1024, 1024), levels=len(pieces),
        tile_shape=TILE, slot_grid=(1, 1, 1),
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


def _omero_channels(store: Path) -> list[dict]:
    import json
    return json.loads((store / ".zattrs").read_text(encoding="utf-8"))["omero"]["channels"]


def test_a_channel_given_no_window_does_not_claim_one(tmp_path):
    """Leaving the window out has to mean "measure it", not "use the whole range".

    A 16-bit camera can count to 65535, but a real acquisition sits in the bottom
    few per cent of that: a few hundred counts of background with the signal not
    far above. Declaring the whole range as the starting window therefore opens
    the acquisition almost black. The viewer measures a good window from the
    pixels instead whenever the description does not ask for one, so the way to
    get that is to genuinely not ask.
    """
    canvases = _canvases(tmp_path)
    window = _omero_channels(canvases.paths[0])[0]["window"]

    assert "start" not in window and "end" not in window, (
        f"no window was asked for, yet the description declares one: {window}"
    )
    # The camera's own range is still worth recording -- it says what the numbers
    # mean -- and it is not the same thing as asking to be displayed that way.
    assert window["min"] == 0 and window["max"] == 65535


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


# -- what the rule is protecting against -------------------------------------


def test_writing_an_overlapping_run_into_one_image_would_lose_a_fifth(tmp_path):
    """The cost the refusal exists to prevent, as a measured number.

    Reached deliberately here, by asking for a single image outright, which is the
    only way to get one for a run whose tiles overlap.
    """
    canvases = _canvases(tmp_path, step=OVERLAPPING, slots=(1, 1, 1))
    expected = _write_a_grid(canvases, step=OVERLAPPING)

    written = _read_level0(canvases.paths[0])
    lost = 0
    for (row, col), value in expected.items():
        y0, x0 = row * OVERLAPPING[1], col * OVERLAPPING[2]
        patch = written[:, y0:y0 + TILE[1], x0:x0 + TILE[2]]
        lost += int((patch != value).sum())

    total = len(expected) * int(np.prod(TILE))
    assert lost > 0
    print(f"\none image, tiles overlapping: {lost} of {total} voxels overwritten "
          f"({100 * lost / total:.0f}% of what was acquired)")


def test_spreading_an_overlapping_run_keeps_every_tile(tmp_path):
    """The other way to keep it: several images, so nothing is ever written over.

    Available deliberately, for a run that wants one artefact rather than tiles
    plus a stitching step afterwards. Not the default.
    """
    canvases = _canvases(tmp_path, step=OVERLAPPING, slots=(1, 2, 2))
    expected = _write_a_grid(canvases, step=OVERLAPPING)

    assert len(canvases.paths) == 4
    levels = [_read_level0(path) for path in canvases.paths]
    for (row, col), value in expected.items():
        y0, x0 = row * OVERLAPPING[1], col * OVERLAPPING[2]
        found = [
            level[:, y0:y0 + TILE[1], x0:x0 + TILE[2]]
            for level in levels
            if level[0, y0, x0] == value
        ]
        assert found, f"tile ({row}, {col}) is not in any image"
        assert (found[0] == value).all(), (
            f"tile ({row}, {col}) was partly overwritten: "
            f"{int((found[0] != value).sum())} voxels lost"
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
