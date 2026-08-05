"""Writing a tiled run into one large OME-Zarr image per acquisition type.

Why this exists
---------------

A smart-microscopy run can visit thousands of places on the stage. If every one
of those becomes its own OME-Zarr folder, the viewer has thousands of separate
images to open, describe, and keep track of — and that cost is paid again every
time a new tile lands, not just once at the start. Measured on this repository's
own test rig, one tile arriving took 0.1 seconds when 25 tiles were open, 0.3
seconds at 100, and 3.7 seconds at 225. The trend does not survive a run of a
few thousand.

The way out is to stop giving the viewer one image per position. Instead each
acquisition type — the overview, the prescan, the targetscan — writes into **one
large image** whose size is declared before any imaging begins. The viewer then
has a handful of things to keep track of no matter how big the run gets, and a
tile arriving costs nothing at all to notice, because the image's description
never changes — only chunks of picture appear underneath it.

Declaring a large image up front is affordable because a piece of an image only
occupies disk once something writes to it. An image can honestly declare the
whole stage travel range and occupy almost nothing until it is filled in.

Tiles must not overlap, and what that costs
-------------------------------------------

One image holds exactly one value per voxel. So if two tiles cover the same
ground, the second to arrive simply replaces the strip they share, and the first
recording of that strip is gone at the moment of writing — silently, because the
picture that results looks perfectly ordinary.

This writer therefore asks for an acquisition whose tiles butt up against one
another: the stage steps by a whole tile, so no two tiles ever cover the same
voxel and nothing is ever written over. A run whose tiles would overlap is
refused when the images are declared, rather than being allowed to lose data
quietly as it goes.

It is worth being plain about what is given up, because the choice is a real one.
Many microscopists deliberately acquire with ten or fifteen per cent overlap, and
the reason is that the two recordings of a shared strip can afterwards be compared
to work out where the stage *actually* put each tile, as opposed to where it
reported putting it. That comparison is how the small errors a stage makes get
corrected.

Without overlap there is no such comparison to make. A tile is written at the
position the stage reported, and if the stage was slightly off then the seam
between two tiles is slightly wrong — permanently, because nothing on disk holds
the information that would let it be put right later.

That is the accepted trade here, and it is accepted because the alternative is not
free either. Keeping overlap means taking on a debt that has to be settled
afterwards: either by acquiring in a pattern that keeps overlapping tiles out of
one another's way and joining them up later, or by running a real stitcher that
solves the alignment of every tile at once. Neither of those exists in this
project, and a half-kept overlap — recorded but never resolved — would be the
worst of both, costing storage and complication for a correction nobody ever
makes. If stage accuracy ever becomes the limiting factor for an experiment here,
the honest answer is to bring in a stitcher, not to start keeping overlap in the
hope that one appears.

What you get on screen
----------------------

The viewer opens one image per acquisition type and draws it in its proper place
on the stage, so the specimen looks like one picture — which it is. Tiles appear
inside it as they land, and nothing about the image's description changes as the
run goes, which is what lets the viewer keep up with a long acquisition.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import threading
import time
import warnings
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import zarr

from .coverage import Recorder, forget_the_record_of

# -- how many copies of an image a run keeps ----------------------------------
#
# Decided once, before any imaging begins, and it cannot be changed afterwards
# without declaring the image again. So it is worked out from what the run says
# about itself rather than left to a fixed number that happens to suit one size
# of experiment.


# How small the smallest copy of an image should end up, measured across the
# specimen. The viewer fetches the whole of that copy, for every colour, before it
# draws anything at all -- and it does that again at every zoom, with no
# progressive reveal, so the operator watches a blank screen until it has all
# arrived. What they wait for is the *number of pieces* it is stored in rather
# than the number of bytes: each piece costs a few milliseconds of the browser's
# own bookkeeping whatever its size, and a browser will only ask for about six at
# a time.
#
# Measured against the flat viewer on stores written here, opening a view costs
# 2 x ceil(coarsest width / piece)^2 x colours requests, which predicted every
# measurement exactly. With 256-voxel pieces that works out as:
#
#   a canvas 100,000 voxels across, 3 copies -> smallest 25,000 -> ~19,000 requests
#   the same canvas with 6 copies            -> smallest  3,125 ->     676, ~4.7 s
#   the same canvas with 8 copies            -> smallest    781 ->      64, ~0.4 s
#
# A thousand voxels is where that curve has flattened out, and it is also what
# `viz_studio/DATA_LAYOUT.md` asks a writer for.
#
# Halving happens in whole steps, so in practice the smallest copy lands anywhere
# between half of this figure and the figure itself. Half of it is the floor, and
# stopping there is deliberate: below about five hundred voxels a copy has ceased
# to be an overview of the specimen and become a thumbnail, and the reading it
# saves is no longer worth the writing it costs on every tile that arrives.
_SMALLEST_COPY_TO_AIM_FOR = 1024

# Never fewer than this many copies, whatever the arithmetic says. An image the
# size of a single camera tile was already served well by three, and choosing the
# number from the declared room is meant to help the large runs rather than take
# anything away from the small ones.
_FEWEST_COPIES = 3

# And never more than this many. Declaring far more room than a run could need is
# encouraged everywhere else in this module, because unwritten room costs nothing
# on disk -- but every extra copy is real work on every tile that arrives, so an
# over-generous declaration must not be able to make writing slow. Ten copies
# shrink an image by five hundred and twelve times, which brings even a canvas
# half a million voxels across down to about a thousand. No stage travels that far.
_MOST_COPIES = 10


def copies_for_a_canvas(canvas_shape) -> int:
    """How many progressively smaller copies a canvas of this size should keep.

    The smaller copies are what the viewer draws when zoomed out, and it reads the
    whole of the smallest one before it draws anything at all. So the number to
    keep is however many halvings it takes to bring the image down to about a
    thousand voxels across — a wide canvas needs more of them than a single tile
    does, which is why this is worked out rather than fixed.

    Only the ``y`` and ``x`` of the canvas are looked at, because those are the
    only axes the copies shrink. Every copy keeps the full depth of the stack, so
    that scrolling through it still shows the planes that were actually acquired,
    and a deep stack is therefore no reason at all to keep more copies.

    Args:
        canvas_shape: how much room the run declared, as ``(z, y, x)`` in voxels.

    Returns:
        The number of copies to keep, counting the full-size one. Never fewer than
        three, so that an ordinary tile-sized image is no worse off than before,
        and never more than ten, so that an over-generous declaration cannot make
        every tile expensive to write.
    """
    widest = max(int(canvas_shape[1]), int(canvas_shape[2]))
    copies = _FEWEST_COPIES
    while copies < _MOST_COPIES and widest // 2 ** (copies - 1) > _SMALLEST_COPY_TO_AIM_FOR:
        copies += 1
    return copies


# -- the rule: tiles must not overlap ------------------------------------------


def _refuse_overlapping_tiles(tile_shape, tile_step) -> None:
    """Stop a run whose tiles would overlap before any of it is written.

    This is the rule the whole arrangement rests on, so it is checked once at the
    start rather than discovered later from a picture that looks slightly wrong.

    One image holds one value per voxel, so where two tiles cover the same ground
    the second to arrive replaces the first and the strip they shared is gone.
    Nothing reports it and nothing about the picture looks unusual, which is what
    makes it worth refusing outright: an operator would have no way of noticing
    that part of every tile had been quietly thrown away.

    Resolving overlap properly needs machinery this project does not have — either
    an acquisition pattern that keeps overlapping tiles out of one another's way
    until they can be joined up, or a real stitcher that solves the alignment of
    every tile at once. Rather than half-support it, this writer asks for an
    acquisition whose tiles butt up. The module's opening notes say what that
    costs.
    """
    axes = ("z", "y", "x")
    overlapping = [
        (axes[axis], tile_shape[axis] - tile_step[axis])
        for axis in range(3)
        if tile_step[axis] < tile_shape[axis]
    ]
    if not overlapping:
        return
    described = ", ".join(f"{by} voxels in {axis}" for axis, by in overlapping)
    raise ValueError(
        f"these tiles overlap ({described}), and this writer does not support an "
        "overlapping acquisition. Everything goes into one image, which holds a "
        "single value per voxel, so the second tile to arrive would replace the "
        "strip it shares with the first — quietly, and with nothing about the "
        "picture to show for it.\n\n"
        "Acquire without overlap: step the stage by the whole tile, so that "
        f"tile_step is at least {tuple(int(n) for n in tile_shape)} voxels. Making "
        "the overlap useful instead would need either a checkerboard acquisition "
        "pattern or a proper stitcher to solve the alignment afterwards, and "
        "neither of those is part of this project."
    )


# -- not writing over a run that has already been imaged -----------------------
#
# Declaring the images empties whatever is already under their name. That is the
# right thing at the start of a run, when nothing is there, and it is a disaster
# once a run has been imaged into that folder: the acquired pictures go, and the
# newly declared images look perfectly healthy, because an empty image is a valid
# one. A notebook cell run twice is all it takes.
#
# Everything in this part is about telling those two situations apart, and about
# doing it by name, so that the overview a run has already imaged never stands in
# the way of the prescan being declared beside it.


# The handful of files inside an image that describe it rather than hold any
# picture. Everything else under an image folder is acquired data, which is what
# makes them the thing to look past when asking "has anything been imaged here?".
_DESCRIPTION_FILES = {".zarray", ".zattrs", ".zgroup", ".zmetadata", "zarr.json"}


def _a_picture_already_written(store: Path) -> Path | None:
    """The first piece of acquired picture found inside ``store``, if there is one.

    An image that has been declared but never written to contains only its own
    description — a few hundred bytes saying how large it is and where it sits.
    A piece of picture appears only when something is actually imaged, so finding
    one is a reliable sign that a run happened here.

    The search stops at the first thing it finds rather than counting everything,
    because a finished run can hold millions of pieces and the answer is the same
    either way.

    Returns:
        The path of a piece of acquired picture, or ``None`` if this image holds
        nothing but its description — which is also the answer for a folder that
        is not there at all, since walking one simply finds nothing.
    """
    for here, _, files in os.walk(store):
        for name in files:
            if name not in _DESCRIPTION_FILES:
                return Path(here) / name
    return None


# Every image this module writes is a folder whose name ends this way, which is
# the usual convention for an OME-Zarr image and is what the viewer looks for.
_IMAGE_SUFFIX = ".ome.zarr"


def _refuse_a_name_that_is_not_a_plain_file_name(name: str) -> None:
    """Stop an acquisition type whose name cannot be part of a file name.

    The name is used twice, and both uses need it to be a plain name sitting in
    the run's own folder. It becomes the folder name each image is written under,
    and it is also how the writer recognises which images belong to this
    acquisition type — the ones it must not empty, and the ones it may throw away
    when asked to.

    A name that reaches into another folder, such as ``"prescans/overview"``,
    breaks the second use quietly: the images would be written one folder down,
    where the check for an already-imaged run does not look, so a run could be
    emptied without anything being said. Rather than let that happen, such a name
    is refused here, at the one moment when saying so is still useful.
    """
    if not name or name in (".", ".."):
        raise ValueError(
            f"{name!r} is not a usable name for an acquisition type. The name "
            "becomes part of the folder each image is written under, so it needs "
            "to be something that can be read as a name — 'overview', 'prescan' "
            "or 'targetscan', say."
        )
    separators = {"/", "\\", os.sep, os.altsep} - {None}
    if any(separator in name for separator in separators):
        raise ValueError(
            f"the name {name!r} contains a folder separator, and an acquisition "
            "type has to be a plain name rather than a path. The images are "
            "written into the run's own folder, and the check that stops an "
            "earlier run from being emptied only looks there — so a name that "
            "reaches into another folder would put the images somewhere that "
            "check cannot see, and a run could be lost without a word.\n\n"
            "Give the acquisition type a plain name and choose the folder with "
            "the folder argument, which is what it is for."
        )


def _images_belonging_to(folder: Path, name: str) -> list[Path]:
    """The images in ``folder`` that hold this acquisition type's pictures.

    One acquisition type is one image, named after it, so ``overview`` covers
    ``overview.ome.zarr`` and nothing else. A list comes back rather than a single
    path because a folder may hold none — a run that has not been declared yet —
    and because the callers are all asking "is there anything of this name here?"
    rather than "where is it?".

    The names are compared as ordinary text, letter by letter. That is worth
    doing deliberately, because the obvious alternative has a trap in it. An
    earlier version of this asked the filesystem to find everything matching the
    pattern ``f"{name}*.ome.zarr"``, and in such a pattern square brackets do not
    mean square brackets — they mean "any one of the letters inside". A run
    honestly called ``well[A1]`` therefore matched nothing at all, the writer
    concluded the folder was empty, and it emptied a run that had already been
    imaged. A name with a ``*`` in it was worse still: the pattern became
    invalid and the run stopped with a message about patterns, which says nothing
    to somebody who was only naming their sample. Comparing text cannot go wrong
    in either way.

    The comparison is also exact rather than "begins with". A run called ``scan``
    and a run called ``scan_deep`` are two different acquisition types that sit
    happily side by side in one folder, and neither may speak for the other's
    images.

    Returns:
        The image folders belonging to this name, in a settled order. Empty if
        there are none, including when the run's folder does not exist yet.
    """
    if not folder.is_dir():
        return []
    found = [
        entry for entry in folder.iterdir()
        if entry.name == f"{name}{_IMAGE_SUFFIX}"
    ]
    return sorted(found)


def _throw_away_the_existing_run(folder: Path, name: str) -> None:
    """Remove this acquisition type's image, because the caller said to.

    This is what ``discard_existing_run=True`` asks for. Declaring the images
    empties them anyway, so removing the old one first mainly means the new run
    starts from a genuinely clean folder rather than from whatever the old one
    left in it.

    Only the image belonging to this name is removed. An overview being thrown away
    must leave a prescan beside it untouched, and it must also leave alone an
    acquisition type whose name merely begins the same way, such as
    ``overview_deep``.
    """
    for store in _images_belonging_to(folder, name):
        if store.is_dir():
            shutil.rmtree(store)
        else:
            store.unlink()


def _refuse_to_write_over_a_finished_run(folder: Path, name: str) -> None:
    """Stop a new run from emptying the images an earlier one filled in.

    Declaring images empties whatever is already under their name, which is the
    right thing when a run is starting and nothing is there yet. It is a disaster
    when a run has already been imaged into that folder: the acquired pictures go
    and nothing says so, because the newly declared images are perfectly valid —
    simply empty.

    That is easy to walk into. A notebook cell run a second time, a script
    restarted after a crash, or a run repeated with the same folder name all lead
    here, and the loss is silent and complete.

    Only the image belonging to this ``name`` is looked at. One run's folder
    holds each of its acquisition types side by side — an overview, a prescan, a
    targetscan — and each is declared in its own call, so a folder that already
    holds an imaged overview must still accept a prescan being declared beside it.
    """
    already = [
        (store, found)
        for store in _images_belonging_to(folder, name)
        if (found := _a_picture_already_written(store)) is not None
    ]
    if not already:
        return
    store, found = already[0]
    raise ValueError(
        f"there is already an imaged run in this folder: {store.name} holds "
        f"acquired pictures, for example {found.relative_to(folder)}. "
        "Declaring the images again would empty them, and everything that run "
        "acquired would be gone with nothing to say so — which is why this is "
        "refused rather than done.\n\n"
        "If this is a new run, give it a folder of its own. One folder per run "
        "is what the rest of this works best with, and it keeps each run's "
        "images side by side under names that mean something.\n\n"
        "If you are restarting a run that stopped part way through, note that "
        "carrying on from where it stopped is not something this writer can do: "
        "it would have to read back where every tile went before it could place "
        "the next one safely. Until then the honest choice is a new folder.\n\n"
        "If the earlier run really is finished with and you mean to throw it "
        "away, say so outright by passing discard_existing_run=True."
    )


# -- only one writer at a time ------------------------------------------------
#
# The check above notices a run that has already been *imaged*, and that is not
# quite enough. Two writers can declare the same folder in the same breath,
# before either has written a single tile, and both are then let through — after
# which each of them writes into images the other is also writing into.
#
# That loses tiles, because everything that keeps a tile safe is remembered by
# the writer rather than read back from disk. Each writer keeps its own list of
# where its tiles went, so that a tile arriving at an unplanned position can be
# placed where it lands on nothing; and each keeps its own list of the pieces of
# picture being written at this moment, so that two tiles are never halfway
# through the same piece at once. Neither list can see the other writer's, so two
# tiles landing in one piece are written over each other and nothing says so.
#
# The cure is for a writer to say on disk that it has these images, and for the
# next one to look. What makes the note trustworthy is that the operating system
# is asked to mark the file as held for as long as the writer keeps it open: the
# mark goes away by itself when the writer is closed, and also when its process
# ends for any reason at all, including a crash or the machine losing power. So a
# claim can never be left behind to block a run that has every right to start,
# which is the failing that makes hand-written marker files a nuisance.


class _CannotBeMarkedHere(Exception):
    """The filesystem this run is being written to offers no such marking.

    Some network filesystems do not, and a microscope's data often does live on
    one. It is not a reason to stop a run, so this is caught and turned into a
    warning rather than a refusal.
    """


class _WritingClaim:
    """The note saying that one writer has one acquisition type's images.

    Held for as long as the writer is in use, and let go when it is closed or
    when the program it belongs to ends.
    """

    def __init__(self, path: Path, handle) -> None:
        self.path = path
        self._handle = handle
        # Set when a later writer in this same program has taken these images
        # over. The earlier writer is then no longer allowed to write, because
        # its record of where its tiles went no longer describes what is on disk.
        self.handed_over = False

    def let_go(self) -> None:
        """Give these images up, so that another writer may take them on."""
        with _CLAIMS_HELD_HERE_LOCK:
            if _CLAIMS_HELD_HERE.get(self.path) is self:
                del _CLAIMS_HELD_HERE[self.path]
        try:
            # Closing the file is what releases the operating system's mark.
            self._handle.close()
        except OSError:
            pass

    def hand_over(self) -> None:
        """Give the images to a later writer in this same program."""
        self.handed_over = True
        self.let_go()


# The claims this program is holding, so that a second declaration in the same
# notebook or script can be recognised and dealt with kindly rather than refused.
# The lock can be taken more than once by the same thread, which it needs to be:
# taking a claim may involve letting an earlier one go.
_CLAIMS_HELD_HERE: dict[Path, _WritingClaim] = {}
_CLAIMS_HELD_HERE_LOCK = threading.RLock()


def _ask_for_the_mark(handle) -> bool:
    """Ask the operating system to mark this file as held by us, without waiting.

    Returns:
        ``True`` if the mark is now ours, ``False`` if somebody else already has
        it.

    Raises:
        _CannotBeMarkedHere: if this filesystem does not offer the marking at all,
            which is not the same as somebody else holding it.
    """
    try:
        import fcntl
    except ImportError:
        # Windows has no fcntl and marks files a different way.
        return _ask_windows_for_the_mark(handle)

    import errno

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as why:
        # These two mean "somebody else has it"; anything else means the
        # filesystem could not do the marking at all.
        if why.errno in (errno.EACCES, errno.EAGAIN):
            return False
        raise _CannotBeMarkedHere(str(why)) from why
    return True


def _ask_windows_for_the_mark(handle) -> bool:
    """The same request, made the way Windows makes it.

    Windows does not distinguish "somebody else has this" from "this cannot be
    done here", so anything going wrong is read as somebody else having it. That
    is the careful way round: it may occasionally refuse a run it could have
    allowed, which costs an operator a moment, whereas the other way round costs
    them tiles.
    """
    try:
        import msvcrt
    except ImportError as why:  # pragma: no cover - neither Unix nor Windows
        raise _CannotBeMarkedHere(
            "this machine offers no way to mark a file as held"
        ) from why
    try:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        return False
    return True


def _what_the_claim_says(name: str) -> str:
    """The words written into the claim file, for whoever finds it.

    Somebody looking through a run's folder should be able to tell what this file
    is without having to ask, and an operator meeting the refusal should be able
    to tell which program is in the way.
    """
    return (
        f"A writer has this run's {name!r} image open and is writing tiles into "
        "it.\n"
        f"Program {os.getpid()} on {socket.gethostname()}, since "
        f"{time.strftime('%Y-%m-%d %H:%M:%S')}.\n"
        "\n"
        "This file holds no picture and is not part of the acquisition. It only "
        "keeps\ntwo writers from working on one image at the same time, "
        "which would\nlose tiles. Once the run has finished it is simply a note "
        "left behind and can\nbe deleted.\n"
    )


def _claim_the_right_to_write(folder: Path, name: str) -> _WritingClaim | None:
    """Become the one writer of this acquisition type's images.

    Args:
        folder: the run's folder, which must already exist.
        name: the acquisition type whose image is being claimed.

    Returns:
        The claim, which must be let go of when the writer is finished with. It
        is returned rather than kept here so that its life is exactly the
        writer's own.

    Raises:
        ValueError: if another program already has this image open. Waiting for
            it is not offered, because the two would be writing the same
            acquisition into the same image and only one of them can be right.
    """
    path = folder / f"{name}.writing"
    with _CLAIMS_HELD_HERE_LOCK:
        ours_already = _CLAIMS_HELD_HERE.get(path)
        if ours_already is not None:
            # A writer in this same program already has this image. That is the
            # ordinary case of a notebook cell being run a second time, and it is
            # safe to allow, because we can see the earlier writer and stop it:
            # it is told it has handed over, so any further tile written through
            # it is refused loudly instead of being lost quietly. Across programs
            # we can neither see nor stop the other writer, which is why that
            # case is refused below.
            ours_already.hand_over()

        try:
            # Opened without emptying it, because what another writer put there is
            # exactly what we may need to read out and pass on.
            handle = os.fdopen(
                os.open(path, os.O_RDWR | os.O_CREAT), "r+", encoding="utf-8"
            )
        except OSError as why:
            # A file left by another user, say, that this one is not allowed to
            # open. Not being able to make the note is no reason to stop an
            # acquisition, so it is reported and the run goes ahead.
            _say_it_could_not_be_checked(folder, name, why)
            return None

        try:
            held_by_us = _ask_for_the_mark(handle)
        except _CannotBeMarkedHere as why:
            _say_it_could_not_be_checked(folder, name, why)
            held_by_us = True

        if not held_by_us:
            said = _read_the_claim(handle)
            handle.close()
            raise ValueError(
                f"another program already has this run's {name!r} image open, so "
                f"this writer cannot have it as well. The note beside it "
                f"({path.name}) says:\n\n"
                f"{said}\n"
                "Two writers must not share one image. Each keeps its own "
                "record of where its tiles went and of which pieces of picture are "
                "being written at this moment, and neither can see the other's, so "
                "two tiles landing in one piece are written over each other and "
                "the loss is silent.\n\n"
                "If that other program is a notebook or a script you have finished "
                "with, let it end or close its writer, and declare this image "
                "again. If it stopped without tidying up there is nothing to clear "
                "away by hand: the claim belongs to the running program itself and "
                "goes the moment it does, so declaring again will simply work.\n\n"
                "If this is meant to be a second, separate run, give it a folder of "
                "its own. One folder per run is what the rest of this works best "
                "with."
            )

        # The note is rewritten rather than added to, so that what a later reader
        # finds describes the writer that holds the images now. The note is always
        # far longer than the single byte Windows marks as held, so shortening the
        # file never disturbs the mark.
        handle.seek(0)
        handle.write(_what_the_claim_says(name))
        handle.truncate()
        handle.flush()
        claim = _WritingClaim(path, handle)
        _CLAIMS_HELD_HERE[path] = claim
        return claim


def _say_it_could_not_be_checked(folder: Path, name: str, why) -> None:
    """Report that this check could not be made here, and let the run go ahead.

    Some network filesystems do not offer one program a way to reserve a file, and
    a microscope's data often does live on one. Refusing to write a run over that
    would be the wrong way round: it would stop acquisitions that are perfectly
    fine, and an operator worked into a corner tends to find a way past the guard
    that is worse than the thing it was guarding against. So this is said out loud
    and the run continues.
    """
    warnings.warn(
        f"it could not be checked whether another program is already writing this "
        f"run's {name!r} images, because the place they are being written to "
        f"({folder}) does not let one program reserve a file ({why}). Nothing is "
        f"wrong with the run itself and it will be written as usual. Do take care "
        f"that only one notebook or script writes any one run, though, because two "
        f"writing at once lose tiles with nothing to say so.",
        stacklevel=4,
    )


def _read_the_claim(handle) -> str:
    """Whatever the other writer left in its claim file, indented for the message.

    Read defensively: the other writer may not have written its note yet, and the
    point of the refusal does not depend on being able to name it.
    """
    try:
        handle.seek(0)
        said = handle.read(4096).strip()
    except (OSError, UnicodeDecodeError):
        said = ""
    if not said:
        return "  (the note says nothing about who holds them)"
    return "\n".join(f"  {line}" for line in said.splitlines())


# -- keeping two tiles out of one piece of image -------------------------------
#
# A piece of a zarr image is read, changed and written back whole. So two tiles
# written into one piece at the same moment are not merged: whichever finishes
# second saves a copy that never held the other's contribution, and nothing says
# so. The next few functions work out how large a piece is for each image, refuse
# the one arrangement that cannot be made safe, and point out a tile size that
# makes the waiting more common than it needs to be.


def _refuse_pieces_that_hold_several_tiles(pieces) -> None:
    """Stop a run whose storage bundles several tiles into one piece of image.

    Two tiles must never be written into the same piece at the same moment,
    because a piece is read, changed and written back whole, so whichever writer
    finishes second erases the other's contribution. The writer prevents that by
    making each tile claim the pieces it lands in and wait for anything sharing
    one — but it can only widen a claim to whole pieces across the specimen, in y
    and x. In time, colour and depth it compares positions exactly, which is
    right only while one piece holds a single moment, a single colour and a
    single plane.

    Images made by :meth:`TileCanvases.create` are always like that. This is
    here for images made some other way, so that an arrangement the writer cannot
    keep safe is refused at the start rather than quietly losing tiles later.

    Args:
        pieces: how large one piece of storage is, in voxels, along every axis of
            the image — its shard shape if it is sharded, its chunk shape if not.
    """
    leading = tuple(int(n) for n in pieces[:-2])
    if all(n == 1 for n in leading):
        return
    raise ValueError(
        "these images keep more than one moment, colour or plane in a single "
        f"piece of storage (one piece spans {leading} of them, before the "
        "specimen's y and x). The writer stops two tiles from being written into "
        "one piece at the same time, because a piece is read, changed and "
        "written back whole and the second writer would erase the first — but it "
        "can only do that across the specimen. In time, colour and depth it "
        "relies on each piece holding a single one, and here that is not so, so "
        "tiles written at the same moment would be lost with nothing to say "
        "so.\n\n"
        "Declare the images with one moment, one colour and one plane per piece, "
        "which is what TileCanvases.create does. That is also what makes showing "
        "a single plane cheap, so nothing is given up by it."
    )


def _measure_the_pieces_of(image: _Image) -> None:
    """Ask the image how much specimen it keeps in one file, and refuse the rest.

    This is worked out once, when the writer is made, and it is what lets the
    writer keep two tiles out of one file later on. Two things about it were each
    found by a measurement rather than by reasoning, so they are written down here.

    **Every copy of an image is asked, not only the smallest.** A tile is written
    into all of the progressively smaller copies, so it can share a file with
    another tile in any one of them. It is tempting to collapse that into a single
    number, since a piece of the smallest copy covers the most ground — but that
    does not work, and the code used to do it. Suppose the full-size copy keeps 128
    voxels in a piece and the half-size copy keeps 100, which is 200 voxels of
    specimen. Holding tiles apart in blocks of 200 draws a boundary at voxel 200,
    and that boundary falls in the middle of the full-size copy's piece covering
    128 to 256. Two tiles either side of it are then judged to share nothing and
    write that one file at the same time. Measured here, a pair of tiles arranged
    that way lost 14336 voxels in 20 of 20 attempts. Asking each copy about its own
    pieces has no such gap in it, and it never holds tiles apart more than the
    storage actually requires.

    **A shard counts, not the chunk inside it.** Ordinarily a piece is a chunk, the
    smallest amount of picture zarr keeps as one file. But a zarr image can also be
    *sharded*, which means many chunks are bundled together into a single file to
    save the filesystem from millions of tiny ones. When that is done it is the
    bundle, not the chunk, that is read and written back whole — so two tiles in
    different chunks of one bundle are every bit as dangerous as two tiles in one
    chunk, and measuring in chunks would let them through. Measured here on zarr
    3.1.6, four tiles written at once into four chunks of one bundle left three of
    them missing, with nothing reported.

    Args:
        image: the image this run writes into. It is given the size of a piece of
            each of its copies, in voxels of specimen across ``y`` and ``x``.

    Raises:
        ValueError: if the image bundles several moments, colours or planes into
            one piece, which is an arrangement the writer cannot keep safe.
    """
    image.pieces = []
    for array in image.arrays:
        pieces = array.shards or array.chunks
        _refuse_pieces_that_hold_several_tiles(pieces)
        # Counted from the end, so that this does not depend on how many axes
        # come before the specimen's y and x.
        image.pieces.append((int(pieces[-2]), int(pieces[-1])))


def _grain_a_tile_of_this_size_could_meet(tile_length: int, chunk: int, levels: int) -> int:
    """The largest piece of image a tile this size could line up with.

    Each smaller copy doubles the ground one piece of image covers: a piece of the
    half-size copy spans twice as much specimen as a piece of the full-size one. On
    a canvas the width of the whole stage the writer now keeps eight or more
    copies, so the coarsest piece can cover thirty thousand voxels — far more than
    any camera tile. Asking a two-thousand-voxel tile to be a whole number of those
    is asking for something no microscope can give.

    So the comparison stops at whichever piece the tile could actually match. What
    is left is advice an operator can follow, which is the only kind worth giving.

    Args:
        tile_length: how many voxels the camera tile covers along this axis.
        chunk: how many voxels one piece of the full-size image covers.
        levels: how many progressively smaller copies the run keeps.

    Returns:
        A piece size in voxels: ``chunk`` doubled as far as it can go without
        passing either the tile or the coarsest copy the run keeps.
    """
    coarsest = chunk * 2 ** (levels - 1)
    grain = chunk
    while grain * 2 <= min(coarsest, tile_length):
        grain *= 2
    return grain


def _warn_if_tiles_straddle_pieces(tile_shape, tile_step, chunk: int, levels: int) -> None:
    """Point out a tile size that makes concurrent writing needlessly slow.

    Two tiles can only be written at the same moment if they do not share a piece
    of image. When a tile is a whole number of pieces and the stage steps by that
    same number, they never do, and tiles can be written as fast as they arrive.
    Getting this wrong is not dangerous: the writer notices and holds the tiles
    apart. It just means waiting.

    One thing this deliberately stays quiet about. The coarsest copies of a wide
    canvas are stored in pieces larger than any camera tile, so tiles landing in
    the same one are always written in turn, and no tile size can change that. It
    is worth knowing but it is not worth saying at the operator, for two reasons.
    They cannot act on it — the number of copies is the writer's decision, taken
    from how much room the run declared. And the cost is small by construction:
    each copy holds a quarter of the data of the one above it, so what the writer
    holds apart in the coarse copies is a small fraction of the work, and writing
    sixteen contending tiles was measured no slower than sixteen that never met.
    A warning nobody can act on only teaches people to stop reading warnings.
    """
    for axis, name in ((1, "y"), (2, "x")):
        grain = _grain_a_tile_of_this_size_could_meet(tile_shape[axis], chunk, levels)
        if tile_shape[axis] % grain or tile_step[axis] % grain:
            nearest = max(grain, round(tile_shape[axis] / grain) * grain)
            warnings.warn(
                f"a tile of {tile_shape[axis]} voxels in {name}, stepped "
                f"{tile_step[axis]}, does not divide into whole pieces of image "
                f"(the pieces that a tile this size could line up with are "
                f"{grain} voxels across). Tiles will sometimes share a piece, and "
                f"the writer then has to write those one after another rather "
                f"than at the same time. Nothing is lost, but a tile of "
                f"{nearest} voxels would avoid the wait.",
                stacklevel=3,
            )
            return


# -- the colours of light a run records ---------------------------------------


# The default colours for the usual excitation wavelengths, matching what the
# viewer uses elsewhere, so a run written here looks the same as one read from a
# mesoSPIM. A wavelength that is not listed is drawn white rather than guessed at.
_CHANNEL_COLORS = {
    "405": "4D73FF",
    "488": "00FF66",
    "561": "FFBF1A",
    "647": "FF33FF",
}


@dataclass(frozen=True)
class Channel:
    """One colour of light the run records, and how it should first appear.

    Recording this in the image itself means the viewer can name and colour the
    channel without guessing from a filename, and it opens looking sensible
    rather than flat grey.

    Args:
        name: what to call it on screen, for example ``"488"`` or ``"nuclei"``.
        color: six hex digits, as ``"00FF66"``. Left out, a name that looks like
            an excitation wavelength picks up the conventional colour and
            anything else is drawn white.
        window: the brightness range to start with, as ``(start, end)``. Left
            out, the viewer measures one from the pixels, which costs a read.
    """

    name: str
    color: str | None = None
    window: tuple[int, int] | None = None

    def described(self, depth_max: int) -> dict:
        """This channel in the form an OME-Zarr ``omero`` block expects.

        The ``min`` and ``max`` written here are the range of numbers the camera
        can produce at all — nought to 65535 for a 16-bit camera — which is a
        plain fact about the data and always worth recording.

        The ``start`` and ``end`` are a different thing: they are the brightness
        range the image should first be *displayed* with, and they are written
        only when the run actually asked for one. That distinction matters more
        than it looks. A real acquisition sits in the bottom few per cent of the
        camera's range — a few hundred counts of background with the signal not
        far above — so declaring the whole range as the display window opens the
        acquisition almost black, and it stays that way until somebody drags the
        contrast slider. Leaving ``start`` and ``end`` out instead tells the
        viewer nothing was asked for, and it measures a sensible window from the
        pixels themselves.
        """
        color = self.color or _CHANNEL_COLORS.get(self.name, "FFFFFF")
        window = {"min": 0, "max": depth_max}
        if self.window is not None:
            window["start"], window["end"] = self.window
        return {
            "label": self.name,
            "color": color,
            "window": window,
        }


# -- the images, and the writer that fills them in -----------------------------


@dataclass
class _Image:
    """The image a run writes into, and what has been put in it so far."""

    folder: Path
    arrays: list[zarr.Array]
    # Every tile written here, as (frame, channel, z0, z1, y0, y1, x0, x1) in
    # voxels. Kept so that a tile arriving at an unplanned position can be asked
    # "does this land on anything already here?" without reading any image data.
    #
    # The moment and the colour are part of it, and leaving them out was a fault.
    # Two tiles at the same place in different moments do not share a single voxel
    # -- they are different slices of the image -- and neither do two colours of
    # the same place. Without them, a run that images a target and then images it
    # again at the next moment was refused as though the second would destroy the
    # first, so a timelapse of targets chosen by the workflow could not be written
    # past its first moment, and a two-colour target could not have its second
    # colour written at all.
    written: list[tuple[int, ...]] = field(default_factory=list)
    # How much of the specimen one file of this image holds, in y and x, for each
    # of its progressively smaller copies. Worked out once when the writer is made
    # and used to keep two tiles out of one file at the same moment.
    pieces: list[tuple[int, int]] = field(default_factory=list)
    # Where this image's record of what it has imaged is kept. See
    # :mod:`zmart_storage.coverage`: the list above lives only in this writer's
    # memory and is gone the moment the program ends, whereas the record is on
    # disk and is what lets a viewer, or an operator the next morning, ask which
    # parts of the canvas hold picture.
    record: Recorder | None = None


class TileCanvases:
    """One acquisition type's image, declared up front and filled in as tiles arrive.

    Make one at the start of a run with :meth:`create`, then call :meth:`write`
    once per acquired tile. Nothing needs to be finalised at the end — the image
    is complete and readable throughout, which is what lets the viewer watch a
    run as it happens.

    A run that records more than one acquisition type — an overview and a
    targetscan, say — makes one of these per type, and their images sit side by
    side in the run's folder.
    """

    def __init__(self, folder: Path, image: _Image, *, shape: tuple[int, ...],
                 levels: int, tile_shape: tuple[int, int, int],
                 claim: _WritingClaim | None = None) -> None:
        self.folder = folder
        self._image = image
        self._shape = shape
        self._levels = levels
        self._claim = claim

        # How much specimen one file of the image holds. This is what lets the
        # writer keep two tiles out of one file at the same moment. Why it is
        # measured the way it is takes some explaining, so the explanation lives
        # with the function that does it.
        _measure_the_pieces_of(image)

        # The tiles being written at this very moment, and the means of waiting
        # for one of them. See :meth:`_while_nothing_else_holds_these_pieces` for
        # what they are protecting against.
        self._busy: list[tuple] = []
        self._free = threading.Condition()

        # The image keeps a note of where it has been imaged, beside the pictures.
        # Nothing about the acquisition depends on it, and the run goes ahead
        # unchanged if it cannot be kept — but with it, anything reading the store
        # afterwards can bound itself to the ground the run actually covered
        # instead of the far larger room the run declared.
        image.record = Recorder(
            folder, image.folder.name, canvas_shape=shape, tile_shape=tile_shape
        )

    def close(self) -> None:
        """Let go of this image, so that another writer may take it on.

        Worth calling when a run has finished and the same folder is going to be
        written again by another program, and harmless otherwise. It does not need
        to be called for the image itself to be complete — it is complete and
        readable throughout — and it happens by itself when the writer falls out
        of use or the program ends.

        It also brings the image's record of what it imaged fully up to date and
        marks the run as finished. That record is written as the run goes, so it
        is complete whether or not this is ever called; what closing adds is the
        last second of it and the note saying the run is over.
        """
        image = getattr(self, "_image", None)
        if image is not None and image.record is not None:
            image.record.finish()
        claim = getattr(self, "_claim", None)
        if claim is not None:
            self._claim = None
            claim.let_go()

    def __del__(self) -> None:
        # A writer that is simply forgotten about should still give its image up,
        # so that the next program to want them is not turned away by a claim
        # nobody is using. Anything going wrong while the program is shutting down
        # is not worth reporting.
        try:
            self.close()
        except Exception:  # pragma: no cover - only reachable at shutdown
            pass

    # -- making the images ------------------------------------------------

    @classmethod
    def create(
        cls,
        folder: str | Path,
        *,
        name: str = "canvas",
        canvas_shape: tuple[int, int, int],
        tile_shape: tuple[int, int, int],
        tile_step: tuple[int, int, int],
        voxel_size_um: tuple[float, float, float],
        channels: list[Channel],
        origin_um: tuple[float, float, float] = (0.0, 0.0, 0.0),
        frames: int = 1,
        dtype: str = "uint16",
        chunk: int = 256,
        shard: int | None = None,
        levels: int | None = None,
        discard_existing_run: bool = False,
        ome_zarr_version: str = "0.4",
    ) -> TileCanvases:
        """Declare the image for an acquisition, before anything has been imaged.

        Nothing here is expensive: declaring a large image writes a few hundred
        bytes of description and no picture at all. Space is taken only as tiles
        are written, so it is much better to declare comfortably more room than
        the run could possibly need than to risk running out.

        Args:
            folder: where to put the image. Created if it is not there yet.
                This is the run's own folder, and every acquisition type in the
                run writes its image into it side by side.
            name: what to call this image, which should be the acquisition type
                it holds — ``"overview"``, ``"prescan"``, ``"targetscan"``. The
                viewer groups the rows it shows by this name, so it is what the
                operator sees rather than an internal detail.
            canvas_shape: how much room to allow, as ``(z, y, x)`` in voxels.
                Across the specimen — the ``y`` and ``x`` of it — the stage's
                travel range is a good choice when the experiment does not say:
                the stage cannot reach outside it, so no tile can ever land
                beyond the edge, and over-declaring costs nothing there.

                **Depth is the exception, and it is worth a moment.** Give ``z``
                the depth the run means to image, with room to spare, rather than
                the stage's whole travel in z. The reason is that the smaller
                copies of an image shrink it across the specimen but keep every
                plane of its depth, and the viewer judges how bright an image
                should look by sampling four planes spread through that depth.
                Declare much more depth than you image and all four land in
                planes nothing was ever written to, so the volume view and the
                contrast slider open with no usable range at all — silently.
                About three times the imaged depth is the point where that starts,
                which is measured in ``viz_studio/DATA_LAYOUT.md``. Depth also
                needs no generosity: a run knows the stack it asked for.
            tile_shape: the size of one acquired tile, as ``(z, y, x)`` in voxels.
            tile_step: how far the stage moves between neighbouring tiles, as
                ``(z, y, x)`` in voxels. This must be at least as large as
                ``tile_shape`` along every axis, so that neighbouring tiles butt
                up rather than overlapping. A smaller step is refused, because
                everything goes into one image and the second tile of an
                overlapping pair would silently replace part of the first.
            voxel_size_um: how large one voxel is, as ``(z, y, x)`` in microns.
                This is what makes the scale bar and the measurements truthful.
            channels: the colours of light being recorded, in the order they
                appear along the channel axis.
            origin_um: where the low corner of the image sits in stage
                coordinates. Tile positions given to :meth:`write` are measured
                from the same zero, so this is usually the low end of stage travel.
            frames: how many moments to allow room for. A run that is not a
                timelapse leaves this at one. A timelapse should declare
                comfortably more than it could possibly record — ten thousand is
                a sensible figure and costs nothing, in the same way that the
                room in space is declared to the stage's whole travel range.
                Nothing is written to a moment until a frame lands in it, so an
                unrecorded moment occupies no space on disk at all, and the
                viewer shows only the moments that were actually imaged. This
                cannot be raised afterwards, so err on the generous side.
            dtype: the kind of number one voxel is. Use the camera's own — a
                16-bit camera writes ``uint16`` — because every level of the image
                must share it and converting would only lose precision.
            chunk: how large a piece of image is, in y and x. A few hundred is
                right: pieces that are too large make the viewer read far more
                than it needs whenever it wants a small sample.
            shard: how large a **bundle** of pieces is, in y and x, or left out to
                keep every piece in a file of its own. Bundling many pieces into one
                file is what OME-Zarr 0.5 calls sharding, and it keeps a long run
                from leaving millions of small files behind. It needs 0.5, since the
                older generation has no way to describe it. Only the full-size copy
                is bundled. A view built by :mod:`zmart_storage.linked` sets this
                from the tiles it points at, because the view has to be stored
                exactly as they are for their bytes to be handed over untouched.
            levels: how many progressively smaller copies to keep. These are what
                let a huge image feel light when zoomed out, and normally this is
                left out so that the writer can choose the number from
                ``canvas_shape`` — see :func:`copies_for_a_canvas`.

                It is worth knowing what that choice is for. The viewer reads the
                whole of the *smallest* copy, for every colour, before it draws
                anything at all, and it does so again at every zoom. So the number
                of copies decides how long an operator looks at a blank screen
                when they open a view. A canvas covering the stage is some fifty
                times wider than one tile, and keeping a fixed three copies of it
                left the smallest one twenty-five thousand voxels across — tens of
                thousands of pieces to fetch before the first picture appears.
                Letting the halving continue until the smallest copy is about a
                thousand voxels brings that down to a few dozen pieces, which is
                the difference between a view opening in under a second and one
                that never really opens at all.

                Give a number here if you have a reason to — matching a store
                somebody else wrote, or making a measurement — and it is used
                exactly as asked.
            discard_existing_run: whether to throw away a run that has already
                been imaged into this folder. Normally left alone, and then a
                folder that already holds acquired pictures is refused rather
                than emptied. Set it only when you know what is there and mean
                to lose it — repeating a test run into the same scratch folder
                is the usual honest reason. Only this acquisition type's image
                goes; other acquisition types in the same folder are untouched.
            ome_zarr_version: which generation of the OME-Zarr format to write,
                ``"0.4"`` or ``"0.5"``.

                ``"0.4"`` is the default because it is what almost everything can
                read today. ``"0.5"`` is the newer standard, and it is where the
                format is going — this viewer reads it fully, and being able to
                write it is what lets a live run be checked against the format the
                project is aiming at rather than only against the one it started
                with.

                Nothing an operator sees changes. The same axes are declared and a
                run written either way looks identical once it is open. What
                differs is where the store keeps its description and how the
                pieces of image are named on disk. Choose ``"0.5"`` when
                everything that will read the run understands it, and ``"0.4"``
                when you are not sure.

        Returns:
            The image, ready to be written into. When the run is over it can be
            left as it is; :meth:`close` is only needed if another program is
            going to write the same run afterwards.

        Raises:
            ValueError: if the tiles would overlap, if this folder already holds
                an imaged run, or if another program is already writing this
                acquisition type. Overlapping tiles are refused because everything
                goes into one image, so the second of an overlapping pair would
                replace part of the first with nothing to say so. A folder that
                already holds acquired pictures should be left alone and the new
                run given a folder of its own, because declaring the image again
                empties it. And two programs cannot write one acquisition into one
                image, because each would only know about its own tiles.
        """
        folder = Path(folder)
        _refuse_a_name_that_is_not_a_plain_file_name(name)
        folder.mkdir(parents=True, exist_ok=True)

        # Worked out before anything else, because the number of copies is written
        # into every image's description and there is no changing it afterwards. A
        # run that named a number of its own keeps it.
        if levels is None:
            levels = copies_for_a_canvas(canvas_shape)

        # Checked before anything is written, because a misspelt version would
        # otherwise be discovered only once the run had produced a folder of
        # images in a format nobody asked for.
        if ome_zarr_version not in ("0.4", "0.5"):
            raise ValueError(
                f"{ome_zarr_version!r} is not a version of OME-Zarr this writer "
                "produces. Use '0.4', which almost everything can read, or '0.5', "
                "which is the newer standard this viewer is aiming at."
            )

        # Asked before anything is declared, because declaring is what does the
        # damage: the images are emptied as they are made, so there is no moment
        # afterwards at which this could still be caught.
        if not discard_existing_run:
            _refuse_to_write_over_a_finished_run(folder, name)

        # Becoming the one writer comes before anything is emptied or thrown away,
        # for the same reason: if another program is already writing this
        # acquisition, then its images must be left exactly as they are — and that
        # holds however firmly this call has asked to discard what is there, since
        # what is there is somebody's run in progress.
        claim = _claim_the_right_to_write(folder, name)
        if discard_existing_run:
            _throw_away_the_existing_run(folder, name)
        # Declaring the image empties it, so whatever an earlier attempt at this
        # acquisition recorded about where it had imaged is no longer true and has
        # to go with it. Done for every declaration rather than only for a
        # discarded run, because an earlier attempt that declared its image and
        # then stopped before acquiring anything is allowed through the check
        # above and would otherwise leave its record behind.
        forget_the_record_of(folder, name)

        _refuse_overlapping_tiles(tile_shape, tile_step)
        _warn_if_tiles_straddle_pieces(tile_shape, tile_step, chunk, levels)

        depth_max = int(np.iinfo(np.dtype(dtype)).max)

        # One image per acquisition type, named after it, so the viewer can group
        # what it finds the way the experiment is organised.
        store = folder / f"{name}{_IMAGE_SUFFIX}"
        arrays = _declare_one(
            store,
            canvas_shape=canvas_shape,
            frames=frames,
            channels=len(channels),
            dtype=dtype,
            chunk=chunk,
            levels=levels,
            voxel_size_um=voxel_size_um,
            origin_um=origin_um,
            channel_blocks=[c.described(depth_max) for c in channels],
            ome_zarr_version=ome_zarr_version,
            shard=shard,
        )

        return cls(
            folder,
            _Image(folder=store, arrays=arrays),
            shape=(frames, len(channels), *canvas_shape),
            levels=levels,
            tile_shape=tile_shape,
            claim=claim,
        )

    # -- writing ----------------------------------------------------------

    @property
    def paths(self) -> list[Path]:
        """Where this acquisition type's image lives.

        A list of one, because that is the shape the viewer is handed a run in:
        it opens a list of image folders, and a run's several acquisition types
        each contribute one.
        """
        return [self._image.folder]

    def write(
        self,
        image: np.ndarray,
        *,
        origin: tuple[int, int, int],
        channel: int = 0,
        frame: int = 0,
        tile_index: tuple[int, int, int] | None = None,
    ) -> Path:
        """Put one acquired tile into the image.

        Args:
            image: the tile's voxels, shaped ``(z, y, x)``.
            origin: where the tile's low corner sits, as ``(z, y, x)`` in voxels,
                measured from the same zero as ``origin_um``.
            channel: which colour of light this tile was recorded in, as its
                position along the channel axis.
            frame: which timepoint it belongs to.
            tile_index: the tile's place in the scan pattern, as ``(z, y, x)``
                counts. A raster scan knows this, and giving it here does two
                things: it is written into the coverage record, so afterwards you
                can ask which square of the pattern a tile came from, and it tells
                the writer that this tile came from a pattern whose tiles butt up,
                so nothing needs checking before it is written. A target picked by
                the workflow has no place in a pattern, and leaving this out is
                fine — the writer then checks the tile against what it has already
                put down.

        Returns:
            The image the tile was written into, which is useful mainly for
            reporting and for tests.

        Raises:
            ValueError: if the tile would fall outside the room that was
                declared — either past the edge of the canvas in space, or past
                the last moment the run declared room for in time. Both mean the
                same thing: the run was declared smaller than it turned out to be.
                Also if the tile would land on ground already imaged in this
                moment and colour, and if this image has since been declared again
                by another writer in this same program, which leaves this one no
                longer able to say truthfully where anything is.
        """
        return self._put_a_tile_in(
            image, origin=origin, channel=channel, frame=frame,
            tile_index=tile_index, at_full_size=True,
        )

    def only_the_zoomed_out_copies(
        self,
        image: np.ndarray,
        *,
        origin: tuple[int, int, int],
        channel: int = 0,
        frame: int = 0,
        tile_index: tuple[int, int, int] | None = None,
    ) -> Path:
        """Fill in a tile's part of the zoomed-out copies, and nothing else.

        This does everything :meth:`write` does except put the tile into the
        full-size picture. It exists for a view whose full-size picture is not
        written down at all but pointed at — the tiles themselves already hold
        those voxels, so copying them into a second image would be writing the same
        bytes twice. See :mod:`zmart_storage.linked`, which is the only thing that
        should be calling this.

        The zoomed-out copies cannot be pointed at in the same way, because
        shrinking the picture makes new numbers that exist nowhere on disk. They are
        therefore written here exactly as they would be for an ordinary run, which
        is what keeps a pointed-at view and a written-out one showing the same
        picture at every zoom.

        Args:
            image: the part of the tile the view shows, shaped ``(z, y, x)``.
            origin: where that part's low corner sits in the view, as ``(z, y, x)``
                in voxels.
            channel: which colour of light this tile was recorded in.
            frame: which moment it belongs to.
            tile_index: the tile's place in the scan pattern, if it has one.

        Returns:
            The image folder the copies were written into.
        """
        return self._put_a_tile_in(
            image, origin=origin, channel=channel, frame=frame,
            tile_index=tile_index, at_full_size=False,
        )

    def _put_a_tile_in(
        self,
        image: np.ndarray,
        *,
        origin: tuple[int, int, int],
        channel: int,
        frame: int,
        tile_index: tuple[int, int, int] | None,
        at_full_size: bool,
    ) -> Path:
        """The body of :meth:`write`, shared with :meth:`only_the_zoomed_out_copies`.

        The two differ in one line — whether the tile is put into the full-size
        picture — and agree about everything else: the checks, the waiting that
        keeps two tiles out of one file, the zoomed-out copies, and the record of
        where the run has imaged. Keeping them one piece of code is what stops those
        agreements drifting apart.
        """
        self._check_these_images_are_still_ours()
        picture = self._image
        depth, height, width = image.shape
        z0, y0, x0 = origin
        footprint = (z0, z0 + depth, y0, y0 + height, x0, x0 + width)
        self._check_it_fits(footprint)
        self._check_the_moment_fits(frame)

        # What was written, in full: where in space, and in which moment and colour.
        # A tile is only in the way of another if it is in the same moment and the
        # same colour as well as the same place.
        occupied = (frame, channel, *footprint)
        if tile_index is None:
            self._check_nothing_is_already_here(occupied)

        with self._while_nothing_else_holds_these_pieces(
            origin, image.shape, frame=frame, channel=channel
        ):
            at = (frame, channel)
            if at_full_size:
                picture.arrays[0][
                    *at, z0:z0 + depth, y0:y0 + height, x0:x0 + width
                ] = image
            self._write_smaller_copies(image, origin, channel, frame)
            picture.written.append(occupied)
            # Written down only now, with the tile's voxels safely on disk, so
            # that the record can never claim ground where a write that failed
            # part way through left nothing.
            if picture.record is not None:
                picture.record.remember(
                    frame=frame,
                    channel=channel,
                    origin=origin,
                    shape=image.shape,
                    tile_index=tile_index,
                )
        return picture.folder

    @contextmanager
    def _while_nothing_else_holds_these_pieces(
        self, origin: tuple[int, int, int],
        shape: tuple[int, int, int], *, frame: int, channel: int,
    ):
        """Wait until no other tile is part way through the files this one needs.

        Two tiles written at the same moment are only safe if they do not share a
        piece of image. Where they do share one, each reads that piece, adds its
        own tile to its own copy, and writes the whole thing back — so whichever
        finishes second erases the other's contribution. Nothing reports it; the
        picture simply comes out with parts missing.

        The trap is that this is about sharing a *piece*, not about the tiles
        overlapping each other. Two tiles can sit well apart, touching nowhere, and
        still fall inside one piece of image, which is just as damaging. So before
        a tile is written it says which pieces it is about to touch, and waits here
        until nothing else in progress is touching any of them.

        The waiting is given back the moment the tile is written, whether that went
        well or not, so one failed tile can never leave the rest of a run queueing
        behind it.
        """
        holding = (
            frame, channel, origin[0], origin[0] + shape[0],
            self._pieces_this_tile_touches(origin, shape),
        )
        with self._free:
            while any(_touches(holding, other) for other in self._busy):
                self._free.wait()
            self._busy.append(holding)
        try:
            yield
        finally:
            with self._free:
                self._busy.remove(holding)
                self._free.notify_all()

    def _check_these_images_are_still_ours(self) -> None:
        """Refuse to write once a later writer has taken this image over.

        This happens when the same program declares the same acquisition twice —
        a notebook cell run again, most often. Declaring empties the image and
        the newer writer starts its own record of where tiles have gone, so this
        older one no longer describes anything that is on disk. Writing through it
        would place tiles by a record that is out of date, and the loss would be
        silent, so it is refused instead.
        """
        if self._claim is not None and self._claim.handed_over:
            raise ValueError(
                "this image has been declared again since this writer was made, "
                "so this writer has been set aside and cannot write any more. "
                "Declaring empties the image and starts a fresh record of where "
                "tiles have gone, and this writer still holds the old one — so a "
                "tile written through it would be placed by a record that no "
                "longer matches what is on disk.\n\n"
                "Use the writer that the most recent declaration returned. If two "
                "parts of your program each need to write tiles, let them share "
                "one writer rather than declaring the image twice."
            )

    def _pieces_this_tile_touches(self, origin: tuple[int, int, int],
                                  shape: tuple[int, int, int]) -> tuple:
        """Which files of each copy of the image the tile is about to be written into.

        Given for every copy separately, as the first and last piece reached in y
        and then the same in x, both included. Two tiles that share none of these
        can safely be written at the same moment; two that share any one of them
        cannot, because that file is read, changed and written back whole.

        Depth needs no counting here: each piece holds a single plane, which
        :func:`_refuse_pieces_that_hold_several_tiles` has already made sure of, so
        comparing the tiles' depths directly is enough.
        """
        claimed = []
        for level, (piece_y, piece_x) in enumerate(self._image.pieces):
            factor = 2 ** level
            y0, y1 = _where_it_lands(origin[1], shape[1], factor)
            x0, x1 = _where_it_lands(origin[2], shape[2], factor)
            claimed.append((
                y0 // piece_y, (y1 - 1) // piece_y,
                x0 // piece_x, (x1 - 1) // piece_x,
            ))
        return tuple(claimed)

    # -- refusing a tile that would land on one already written -------------

    def _check_nothing_is_already_here(self, occupied: tuple[int, ...]) -> None:
        """Refuse a tile that would be written over ground already imaged.

        ``occupied`` is ``(frame, channel, z0, z1, y0, y1, x0, x1)`` — where the
        tile lands, and in which moment and colour. All three matter: the same
        place in a later moment, or in another colour, is a different part of the
        image and nothing is in its way.

        This is asked only of a tile with no place in a scan pattern — a target
        the workflow chose for itself. A raster's tiles butt up by the rule the
        images were declared under, so they cannot land on one another, and
        checking every one of them against every tile before it would make a long
        run steadily slower for an answer that is known in advance.

        The check is arithmetic on a list of rectangles the writer already holds
        in memory, so it costs nothing to speak of and touches no image data.
        """
        if not any(_overlaps(occupied, other) for other in self._image.written):
            return
        raise ValueError(
            "this tile lands on ground that has already been imaged in this "
            "moment and this colour, and writing it would replace what is there. "
            "The image holds one value per voxel, so the earlier recording would "
            "be gone with nothing to say so — which is why this is refused rather "
            "than done.\n\n"
            "This happens when two targets are chosen close enough together that "
            "their fields of view meet. Space the targets at least a tile apart, "
            "or record the second one in another moment or another colour, where "
            "it has room of its own."
        )

    def _check_the_moment_fits(self, frame: int) -> None:
        """Refuse a moment the run did not declare room for.

        Time is declared at the start and filled in afterwards, exactly as the
        room in space is, so a frame beyond the declared length is the same kind
        of mistake as a tile beyond the edge of the canvas and is refused the same
        way. Declaring generously is what avoids it, and costs practically nothing.
        """
        moments = self._shape[0]
        if frame < 0:
            raise ValueError(
                "a frame is counted from zero, so there is no moment before the "
                f"first one; this write asked for {frame}."
            )
        if frame >= moments:
            raise ValueError(
                f"this tile belongs to moment {frame}, past the {moments} the run "
                "declared room for. Declare a timelapse with comfortably more "
                "moments than it could possibly record — unwritten moments cost "
                "practically nothing, because a moment nothing was written to "
                "occupies no space on disk at all."
            )

    def _check_it_fits(self, footprint: tuple[int, ...]) -> None:
        z0, z1, y0, y1, x0, x1 = footprint
        limits = self._shape[2:]
        if z0 < 0 or y0 < 0 or x0 < 0:
            raise ValueError(
                "this tile sits before the low corner of the declared room. The "
                "image can be made larger, but only outward, so the corner has to "
                "be at or below the lowest position the run will ever visit."
            )
        if z1 > limits[0] or y1 > limits[1] or x1 > limits[2]:
            raise ValueError(
                f"this tile reaches to {(z1, y1, x1)} voxels, past the declared "
                f"room of {limits}. Declare the image with the stage's whole "
                "travel range so this cannot happen — unwritten room costs "
                "practically nothing on disk."
            )

    # -- the smaller copies -----------------------------------------------

    def _write_smaller_copies(self, image: np.ndarray,
                              origin: tuple[int, int, int],
                              channel: int, frame: int) -> None:
        """Fill in this tile's part of each progressively smaller copy.

        These are what the viewer draws when zoomed out, and what it measures
        brightness from, so they have to be kept in step as tiles arrive rather
        than built at the end — otherwise a run in progress looks empty until
        someone zooms all the way in.

        Only y and x are shrunk. Planes are left alone because scrolling through
        a stack should show the planes that were actually acquired.

        **The shrinking takes every second voxel rather than averaging four**, and
        that is now depended on elsewhere rather than merely being the simplest
        thing. Because no voxels are combined, a voxel of a smaller copy comes from
        exactly one voxel of the full-size picture, and therefore from exactly one
        tile. That is what lets a view point at the tiles' own smaller copies
        instead of writing its own -- see ``viz_studio/PLAN_nothing_copied_at_all.md``.
        Changing this to average would give a smoother zoomed-out picture and would
        quietly break that, because an averaged voxel near a join really does come
        from two tiles.
        """
        for level in range(1, self._levels):
            factor = 2 ** level
            smaller = image[:, ::factor, ::factor]
            if smaller.size == 0:
                continue
            z0 = origin[0]
            depth = smaller.shape[0]
            # Worked out by the same reckoning that decided which files this tile
            # would touch, so that the two can never disagree about where it goes.
            y0, y1 = _where_it_lands(origin[1], image.shape[1], factor)
            x0, x1 = _where_it_lands(origin[2], image.shape[2], factor)
            height, width = y1 - y0, x1 - x0
            array = self._image.arrays[level]
            # A tile near the far edge can round to just past the end of a smaller
            # copy, so trim rather than fail: the lost row is half a voxel of the
            # coarsest view, which nothing can see.
            height = min(height, array.shape[-2] - y0)
            width = min(width, array.shape[-1] - x0)
            if height <= 0 or width <= 0:
                continue
            at = (frame, channel)
            array[*at, z0:z0 + depth, y0:y0 + height, x0:x0 + width] = (
                smaller[:, :height, :width]
            )


# -- geometry ---------------------------------------------------------------


def _overlaps(a: tuple[int, ...], b: tuple[int, ...]) -> bool:
    """Whether two written tiles share any voxel at all.

    Each is ``(frame, channel, z0, z1, y0, y1, x0, x1)``. The moment and the colour
    have to match before the position is even worth comparing: an image holds every
    moment and every colour separately, so the same square of specimen imaged at a
    later moment, or through a different filter, lands somewhere else entirely and
    destroys nothing.
    """
    if a[0] != b[0] or a[1] != b[1]:
        return False
    return (
        a[2] < b[3] and b[2] < a[3]
        and a[4] < b[5] and b[4] < a[5]
        and a[6] < b[7] and b[6] < a[7]
    )


def _where_it_lands(start: int, length: int, factor: int) -> tuple[int, int]:
    """Where a tile lands in a copy of the image shrunk by ``factor``.

    Args:
        start: the tile's low edge along this axis, in full-size voxels.
        length: how far the tile reaches along this axis, in full-size voxels.
        factor: how much smaller this copy is — 1 for the full-size one, 2 for the
            half-size one, and so on.

    Returns:
        The low and high edge in that copy's own voxels, the high edge not
        included, in the manner of a Python slice. The high edge is rounded up, so
        a tile that half fills a voxel of the smaller copy still counts as
        reaching it — which is right, because writing it is what puts a value
        there.
    """
    begin = start // factor
    return begin, begin + max(1, -(-length // factor))


def _touches(a: tuple, b: tuple) -> bool:
    """Whether two writes in progress would be working on the same file.

    Each claim is ``(frame, channel, z from, z to, files)``, where ``files`` says,
    for each progressively smaller copy of the image, the first and last piece the
    tile reaches in y and then the same in x, both included.

    Time, colour and depth each get a piece to themselves — the writer insists on
    that — so those simply have to coincide. Across the specimen the copies are
    asked one at a time, and sharing a piece in any single copy is enough to make
    two writes wait for each other, because that one file would otherwise be
    written twice at once and one tile's contribution to it lost.
    """
    if a[0] != b[0] or a[1] != b[1]:
        return False
    if not (a[2] < b[3] and b[2] < a[3]):
        return False
    return any(
        mine[0] <= theirs[1] and theirs[0] <= mine[1]
        and mine[2] <= theirs[3] and theirs[2] <= mine[3]
        for mine, theirs in zip(a[4], b[4], strict=True)
    )


# -- declaring one image ----------------------------------------------------


def _declare_one(
    store: Path,
    *,
    canvas_shape: tuple[int, int, int],
    frames: int,
    channels: int,
    dtype: str,
    chunk: int,
    levels: int,
    voxel_size_um: tuple[float, float, float],
    origin_um: tuple[float, float, float],
    channel_blocks: list[dict],
    ome_zarr_version: str = "0.4",
    shard: int | None = None,
) -> list[zarr.Array]:
    """Write one empty OME-Zarr image and hand back its levels.

    Every run gets a time axis, whether or not it is a timelapse. That was not
    always so. The viewer used to pick which axes to put on screen from the first
    few an image declared, so an extra axis was enough to make it choose wrongly
    and draw the specimen as a thin band; a run of one moment therefore left the
    axis out to avoid it. The viewer now chooses the axes that measure distance,
    whatever else an image has, so the workaround is gone and every run can declare
    the same five axes. A run of a single moment simply gets no time slider,
    because one moment is nothing to offer a choice between.
    """
    store.mkdir(parents=True, exist_ok=True)
    # Which generation of the format to write. The two differ in more than a number:
    # 0.4 is built on zarr version 2 and keeps a store's description in a separate
    # ``.zattrs`` file beside the image, while 0.5 is built on zarr version 3, which
    # keeps it inside ``zarr.json`` under an ``ome`` key and files the pieces of the
    # image under a folder called ``c``. Everything else here -- the axes, the
    # ordering, the sizes, the way a tile is written -- is the same for
    # both, so a run written either way behaves identically once it is open.
    newer = ome_zarr_version == "0.5"
    if shard is not None and not newer:
        raise ValueError(
            "bundling pieces into larger files was asked for, and this image is "
            f"being written as OME-Zarr {ome_zarr_version}, which has no way to "
            "describe such a bundle — the older generation of zarr keeps every "
            "piece in a file of its own and a reader would have no way to find "
            "anything inside a bundle.\n\n"
            "Write this run as OME-Zarr 0.5 if the bundling is wanted, or leave "
            "the bundling out."
        )
    group = zarr.open_group(str(store), mode="w", zarr_format=3 if newer else 2)

    # A time axis is always declared, and is given its full length here rather than
    # being lengthened as the run goes. This is the same arrangement as the room in
    # space: declare comfortably more than the run could need, and fill it in. A
    # moment nothing has been written to occupies no space on disk, so a generous
    # length costs only the number written in this description.
    #
    # What makes it safe is that the viewer shows only the moments that were
    # actually imaged: it counts what has been written and stops the time slider
    # there, so an operator is never offered a frame that does not exist. Without
    # that counting this arrangement would be a trap, because the engine remembers
    # "there is nothing here" for a frame looked at too early and does not look
    # again -- see `written_timepoints` in the viewer's `stores.py`.
    axes = [
        {"name": "t", "type": "time", "unit": "second"},
        {"name": "c", "type": "channel"},
        {"name": "z", "type": "space", "unit": "micrometer"},
        {"name": "y", "type": "space", "unit": "micrometer"},
        {"name": "x", "type": "space", "unit": "micrometer"},
    ]

    arrays, datasets = _make_the_copies(
        group,
        canvas_shape=canvas_shape,
        frames=frames,
        channels=channels,
        dtype=dtype,
        chunk=chunk,
        levels=levels,
        voxel_size_um=voxel_size_um,
        newer=newer,
        shard=shard,
    )

    multiscale = {
        "axes": axes,
        "datasets": datasets,
        # Where this image sits in the world. Every image in a run shares the
        # same corner, which is what makes them line up on screen.
        #
        # This number is the **corner** of the first voxel, not its middle, and
        # every smaller copy is given the same one. That is a choice rather than
        # a rule: OME-Zarr does not say which is meant, and the question has been
        # open with the format's authors since 2022. Under the corner reading the
        # copies nest perfectly -- every level begins at exactly this point, and a
        # coarse voxel covers precisely the fine ones it was built from. Under the
        # other reading they would not, so a level would have to be shifted by half
        # of its own voxel to mean the same thing.
        #
        # Readers disagree about this, and some will place the picture half a voxel
        # off. That is theirs to correct, not ours: a file that shifts itself to
        # suit one reader is wrong for every other. The reasoning, the arithmetic
        # and what each reader does are in VOXEL_PLACEMENT.md beside this file.
        "coordinateTransformations": [{
            "type": "translation",
            "translation": [0.0, 0.0,
                            origin_um[0], origin_um[1], origin_um[2]],
        }],
    }

    _write_the_description(store, group, multiscale, channel_blocks, newer=newer)
    return arrays


def _make_the_copies(
    group, *,
    canvas_shape: tuple[int, int, int],
    frames: int,
    channels: int,
    dtype: str,
    chunk: int,
    levels: int,
    voxel_size_um: tuple[float, float, float],
    newer: bool,
    shard: int | None = None,
) -> tuple[list[zarr.Array], list[dict]]:
    """Make the full-size image and each progressively smaller copy of it.

    The copies are what the viewer draws when it is zoomed out. Each one is half
    the width and half the height of the one before it, and every one of them
    keeps the full depth of the stack, because scrolling through a stack should
    show the planes that were really acquired.

    Nothing is written into them here. Declaring an image of this size costs a
    few hundred bytes of description and no picture at all, which is what makes
    it reasonable to declare the stage's whole travel range up front.

    Args:
        group: the zarr group the copies are made in, which is one image.
        canvas_shape: how much room the run declared, as ``(z, y, x)`` in voxels.
        frames: how many moments to allow room for.
        channels: how many colours of light the run records.
        dtype: the kind of number one voxel is, such as ``"uint16"``.
        chunk: how large one piece of image is, in y and x.
        levels: how many copies to make, counting the full-size one.
        voxel_size_um: how large one voxel is, as ``(z, y, x)`` in microns.
        newer: ``True`` when writing OME-Zarr 0.5, which files the pieces of an
            image its own way, ``False`` for 0.4.
        shard: how large a **bundle** of pieces is, in y and x, or ``None`` to keep
            every piece in a file of its own. Bundling many pieces into one file is
            what OME-Zarr 0.5 calls sharding, and it exists because a large run
            otherwise leaves millions of small files behind, which most filesystems
            and most backup software handle badly. Only the full-size copy is
            bundled: it is the one that has to match the tiles a pointed-at view
            hands over, and the smaller copies are few enough not to need it.

    Returns:
        The copies themselves, largest first, and the block of description that
        names each one and says how much ground its voxels cover.
    """
    arrays, datasets = [], []
    for level in range(levels):
        factor = 2 ** level
        shape = (
            frames,
            channels,
            canvas_shape[0],
            max(1, canvas_shape[1] // factor),
            max(1, canvas_shape[2] // factor),
        )
        # Bundling applies to the full-size copy only, and only where it was asked
        # for. A bundle has to hold a whole number of pieces, so it is nudged up to
        # the piece size if a smaller number was given.
        bundled = None
        if shard is not None and level == 0:
            across = max(int(shard), int(chunk))
            bundled = (1, 1, 1, min(across, shape[-2]), min(across, shape[-1]))
        arrays.append(group.create_array(
            str(level),
            shape=shape,
            # One plane per piece in time, colour and depth, so showing a single
            # plane never means fetching the ones on either side of it.
            chunks=(1, 1, 1, min(chunk, shape[-2]), min(chunk, shape[-1])),
            shards=bundled,
            dtype=dtype,
            # Pieces filed in folders rather than side by side in one directory.
            # A long run otherwise puts millions of files in a single folder,
            # which most filesystems handle badly.
            #
            # Version 3 already does this of its own accord -- it files every piece
            # under a folder called ``c`` and separates the rest with slashes -- so
            # it is left to its own naming and only version 2 has to be asked.
            # Asking version 3 for the version 2 naming would work, but it would
            # produce a store that looks like neither generation and would be a
            # small surprise to anything else reading it.
            **({} if newer else {"chunk_key_encoding": {"name": "v2", "separator": "/"}}),
        ))
        datasets.append({
            "path": str(level),
            "coordinateTransformations": [{
                "type": "scale",
                # Only the height and the width of a voxel double from one copy to
                # the next. Its depth stays as it was, because no plane is ever
                # dropped.
                "scale": [1.0, 1.0, voxel_size_um[0],
                          voxel_size_um[1] * factor, voxel_size_um[2] * factor],
            }],
        })
    return arrays, datasets


def _write_the_description(
    store: Path, group, multiscale: dict, channel_blocks: list[dict], *, newer: bool
) -> None:
    """Record what this image is, in the place the chosen generation keeps it.

    This is the one part of writing an image that the two generations of OME-Zarr
    genuinely disagree about, so it is kept here on its own rather than left in
    the middle of building the arrays. Everything the description *says* is the
    same either way; only where it is written down differs.

    Args:
        store: the image folder, which version 0.4 writes a file beside.
        group: the zarr group the arrays were made in, which version 0.5 keeps
            its description inside.
        multiscale: the block describing the axes, the progressively smaller
            copies and where the image sits in the world.
        channel_blocks: one block per colour of light, saying how it should first
            appear on screen.
        newer: ``True`` for version 0.5, ``False`` for 0.4.
    """
    if newer:
        # In 0.5 the description lives inside the store's own ``zarr.json``, under an
        # ``ome`` key, and the version is stated once for the whole block rather than
        # on each multiscale. Written through zarr's own attributes rather than by
        # replacing the file, because that file also holds what zarr needs in order
        # to recognise the store at all -- writing over it by hand would leave an
        # image nothing could open.
        group.attrs.update({
            "ome": {
                "version": "0.5",
                "multiscales": [multiscale],
                "omero": {"channels": channel_blocks},
            }
        })
    else:
        # In 0.4 it is a file of its own beside the image, and each multiscale
        # carries the version itself.
        (store / ".zattrs").write_text(json.dumps({
            "multiscales": [{"version": "0.4", **multiscale}],
            "omero": {"channels": channel_blocks},
        }, indent=2), encoding="utf-8")
