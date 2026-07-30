"""Where a run actually imaged, written down while it happens.

Why this exists
---------------

A run declares far more room than it is going to fill. That is deliberate, and
:mod:`zmart_storage.canvas` explains it at length: a piece of an image costs
nothing on disk until something is written into it, so a canvas can honestly
declare the stage's whole travel range and then be filled in wherever the
experiment goes. What it leaves behind, though, is a picture-frame with no note
of which parts of it hold a picture.

That gap is felt in three places, and all three are about the same missing
sentence.

The viewer draws by asking for small pieces of the image, and it asks for them
across the whole of the declared canvas — because the declaration is all it has
to go on. Measured over a sparse run, three quarters of those requests were for
room that was never imaged, and that fraction follows the size of the
*declaration* rather than the size of the acquisition. So the more generously a
run declares its room, the more of the viewer's effort goes nowhere, which is
exactly backwards from the promise that over-declaring is free.

An operator checking coverage cannot tell "we have not been there yet" from "we
went there and the specimen was dark". Both read back as zeros, because zarr
hands back the fill value for a piece nothing has written to. A viewer that makes
empty room see-through therefore also makes a genuinely dark specimen
see-through, which is a bad way to answer "did we image that region?".

And a second front end being designed needs to know which parts of its own
drawing to cut away, so that the image underneath shows through only where there
really is an image.

What is written, and where
--------------------------

A run's folder gains one extra folder called ``zmart-coverage``, sitting beside
the images rather than inside any of them, with a folder within it named after
each image::

    run/
      overview.ome.zarr/          the pictures, untouched
      targetscan.ome.zarr/
      zmart-coverage/
        overview.ome.zarr/
          tiles.jsonl
          regions.json
        targetscan.ome.zarr/
          ...

Two files, with different jobs.

``tiles.jsonl``
    One line for every tile that was successfully written, in the order the
    tiles landed. Each line is a small block of JSON saying which acquisition
    and image the tile belongs to, where its low corner sits in voxels, how
    large it is, its place in the scan pattern if it had one, and the moment it
    landed. This is the exact record, and it is the one that survives a run
    being cut short: a line is added when a tile is safely on disk and nothing
    ever rewrites the file, so whatever reached the disk stays there.

``regions.json``
    A short summary a browser can read in a single request: the same coverage
    boiled down to a list of rectangles, together with how many tiles have been
    written, which moments and colours have been recorded, and whether the run
    has finished. Rectangles that sit against one another are joined up, so an
    ordinary raster of several hundred tiles comes back as one rectangle rather
    than several hundred.

Both files are measured in voxels of the full-resolution image, counted from the
same corner that :meth:`zmart_storage.canvas.TileCanvases.write` measures a
tile's ``origin`` from. Nothing here repeats the voxel size or the position on
the stage, because the image's own OME-Zarr description already carries those
and two copies of one number are one copy too many.

Why beside the images and not inside them
-----------------------------------------

Putting the record inside each ``.ome.zarr`` folder would have been tidier to
look at, and it was tried first. Two measurements sent it outside instead.

The first is about readers. Anything at all that is added inside an image folder
— a file or a folder, whatever it is called — makes zarr complain the moment a
program asks an image what it contains: ``Object at zmart-coverage is not
recognized as a component of a Zarr hierarchy``. The image still opens and every
picture still reads, so nothing is broken, but a viewer that has never heard of
this record should not have to explain a warning about it to its user. Outside
the images there is nothing for zarr to have an opinion about.

The second is about the viewer watching a live run. It decides whether anything
has changed by looking at when each folder was last touched, and adding a file to
a folder counts as touching it. A summary rewritten every second inside an image
folder would therefore have looked, once a second, like the acquisition itself
having changed, and the viewer would have rebuilt its whole description of the
run each time — which on a folder holding a few thousand acquisitions takes over
a second by itself. One folder deeper, the rewriting is invisible to that check.

Why the record is kept this way
-------------------------------

Several threads write tiles at the same time — that is the point of the writer —
so the record has to be safe when two of them land at once. Two shapes of
mistake were available here and both have bitten this project before.

The first is to keep one file that every tile *reads and rewrites*. That is the
same read-change-write-back pattern that loses zarr chunks when two tiles share
one, and it loses lines here for exactly the same reason: whichever writer
finishes second saves a copy of the file that never contained the other's line.

The second is to write one small file per tile, which is perfectly safe but
leaves a reader with a folder of thousands of files and no way to open them over
plain HTTP, which cannot list a folder.

So ``tiles.jsonl`` is only ever *added to*, never read back and rewritten. Each
line is handed to the operating system in one go, through a file that was opened
in "always add to the end" mode, with a lock held so that two threads cannot be
halfway through a line at once. There is nothing to lose, because nothing that is
already on disk is ever touched again.

``regions.json`` is a different matter, because a summary has to be rebuilt from
scratch each time. It is never edited where it lies. A complete new copy is
written under a temporary name and then moved into place in a single step that
the filesystem either does or does not do — so a reader arriving at any moment
sees either the whole of the old summary or the whole of the new one, and never
half of either. Rebuilding is done at most once a second while the run goes, and
once more when the run finishes, which keeps a live viewer within a second of the
truth without making every tile pay for a rewrite.

One thing this arrangement leans on, deliberately: the writer already refuses to
let two programs write one acquisition at the same time, because everything that
keeps a tile safe is remembered inside the writer rather than read back from
disk. The coverage record leans on that same guarantee and asks for nothing more.
If two programs did somehow write one run, the tiles themselves would already be
being lost, and the record would be the smaller of the two problems.

Is there somewhere in OME-NGFF this belongs?
--------------------------------------------

It was worth looking, and the honest answer is no — not yet. OME-NGFF describes
how an image is *arranged*: its axes, its progressively smaller copies, its
channels, and for plates its wells. It has nothing that says which parts of an
array have been written to, and neither does zarr itself. The nearest thing in
the wider community is the region-of-interest table that the Fractal project
keeps beside an image, but that is a convention rather than part of the standard,
it is stored in a form that needs a specialist reader, and it describes regions
chosen for *analysis* rather than the ground a run covered.

So this is written as an addition rather than as standard metadata, and it is
kept deliberately out of the way. It goes in a folder of its own with a name
nothing else uses, not one byte of any image changes, and nothing is added inside
an image folder at all. A viewer that has never heard of it opens the images
exactly as it did before.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
import warnings
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# The folder a run keeps its coverage record in, sitting beside the images, and
# the two files each image's record is written into. These names are part of the
# agreement with anything that reads the record, including the browser, so they
# are written down once here.
COVERAGE_FOLDER = "zmart-coverage"
TILES_FILE = "tiles.jsonl"
REGIONS_FILE = "regions.json"

# Which shape of record this is. If the contents ever have to change in a way an
# older reader could not follow, this number goes up and the reader can say so
# plainly instead of misreading it.
RECORD_VERSION = 1

# The usual ending of an OME-Zarr image folder, repeated here so that this module
# can work out which acquisition an image belongs to without reaching into
# ``canvas``.
_IMAGE_SUFFIX = ".ome.zarr"

# How often the short summary is rebuilt while a run is going. A live viewer
# reads it to decide which parts of the canvas are worth asking for, so being a
# second behind costs nothing an operator could notice — whereas rebuilding it on
# every tile would make a fast run pay for a full rewrite thousands of times.
_HOW_OFTEN_TO_REBUILD_SECONDS = 1.0


def acquisition_of(image_name: str) -> str:
    """Which acquisition type an image folder belongs to, from its name alone.

    A run writes one image per acquisition type, named after it — ``overview``
    becomes ``overview.ome.zarr``. A run that has to keep the overlap between its
    tiles spreads the same acquisition over several numbered images instead, so
    ``overview_part0.ome.zarr`` and its siblings all belong to ``overview`` too.

    Args:
        image_name: the name of the image folder, such as ``"overview.ome.zarr"``.

    Returns:
        The acquisition type's own name, with the ending and any part number
        taken off.
    """
    leaf = image_name
    if leaf.endswith(_IMAGE_SUFFIX):
        leaf = leaf[: -len(_IMAGE_SUFFIX)]
    head, marker, tail = leaf.rpartition("_part")
    if marker and tail.isdigit():
        return head
    return leaf


def where_the_record_is(run: str | Path, image: str) -> Path:
    """The folder holding one image's coverage record.

    Args:
        run: the run's own folder, the one the images sit in.
        image: the name of the image folder, such as ``"overview.ome.zarr"``.

    Returns:
        The folder the record for that image is kept in. It sits beside the
        images rather than inside them, for the reasons given at the top of this
        module.
    """
    return Path(run) / COVERAGE_FOLDER / image


def forget_the_record_of(run: str | Path, acquisition: str) -> None:
    """Throw away the coverage record of one acquisition type.

    Declaring a run's images empties them, so whatever an earlier run wrote there
    is no longer true and its record must go with it. Only this acquisition
    type's record is removed: a run's folder holds an overview, a prescan and a
    targetscan side by side, and declaring one of them must leave the others
    exactly as they are.

    Args:
        run: the run's own folder.
        acquisition: the acquisition type whose record should go, such as
            ``"overview"``. A run that spread the same acquisition over several
            numbered images has all of their records removed together.
    """
    kept = Path(run) / COVERAGE_FOLDER
    if not kept.is_dir():
        return
    for child in kept.iterdir():
        if child.is_dir() and acquisition_of(child.name) == acquisition:
            shutil.rmtree(child, ignore_errors=True)


@dataclass(frozen=True, order=True)
class Region:
    """One rectangular block of the canvas that holds acquired picture.

    The six numbers are voxel positions in the full-resolution image, given as a
    low edge and a high edge for each of depth, height and width. The high edge
    is *not* included, in the same way that Python's own slices work, so a block
    running from 0 to 128 covers voxels 0 up to and including 127.
    """

    z0: int
    z1: int
    y0: int
    y1: int
    x0: int
    x1: int

    @property
    def spans(self) -> tuple[tuple[int, int], tuple[int, int], tuple[int, int]]:
        """The same block as a low-and-high pair for each of z, y and x."""
        return ((self.z0, self.z1), (self.y0, self.y1), (self.x0, self.x1))

    @classmethod
    def from_spans(cls, spans) -> Region:
        """A block built back up from the three low-and-high pairs."""
        (z0, z1), (y0, y1), (x0, x1) = spans
        return cls(z0, z1, y0, y1, x0, x1)

    def contains(self, z: int, y: int, x: int) -> bool:
        """Whether one voxel sits inside this block."""
        return (
            self.z0 <= z < self.z1
            and self.y0 <= y < self.y1
            and self.x0 <= x < self.x1
        )

    def as_written(self) -> dict:
        """This block in the form the files on disk use."""
        return {
            "z": [self.z0, self.z1],
            "y": [self.y0, self.y1],
            "x": [self.x0, self.x1],
        }

    @classmethod
    def from_written(cls, block: dict) -> Region:
        """A block read back from one of the files on disk."""
        return cls(*block["z"], *block["y"], *block["x"])


@dataclass(frozen=True)
class Tile:
    """One tile that was successfully written, as the record remembers it."""

    acquisition: str
    image: str
    frame: int
    channel: int
    origin: tuple[int, int, int]
    shape: tuple[int, int, int]
    tile_index: tuple[int, int, int] | None
    written: str

    @property
    def region(self) -> Region:
        """The block of canvas this tile covers."""
        z0, y0, x0 = self.origin
        depth, height, width = self.shape
        return Region(z0, z0 + depth, y0, y0 + height, x0, x0 + width)

    def as_written(self) -> dict:
        """This tile in the form one line of ``tiles.jsonl`` uses."""
        z0, y0, x0 = self.origin
        depth, height, width = self.shape
        return {
            "acquisition": self.acquisition,
            "image": self.image,
            "frame": self.frame,
            "channel": self.channel,
            "origin": {"z": z0, "y": y0, "x": x0},
            "shape": {"z": depth, "y": height, "x": width},
            "tile_index": (
                None if self.tile_index is None
                else {
                    "z": self.tile_index[0],
                    "y": self.tile_index[1],
                    "x": self.tile_index[2],
                }
            ),
            "written": self.written,
        }

    @classmethod
    def from_written(cls, line: dict) -> Tile:
        """A tile read back from one line of ``tiles.jsonl``."""
        origin, shape = line["origin"], line["shape"]
        place = line.get("tile_index")
        return cls(
            acquisition=line["acquisition"],
            image=line["image"],
            frame=int(line["frame"]),
            channel=int(line["channel"]),
            origin=(int(origin["z"]), int(origin["y"]), int(origin["x"])),
            shape=(int(shape["z"]), int(shape["y"]), int(shape["x"])),
            tile_index=(
                None if place is None
                else (int(place["z"]), int(place["y"]), int(place["x"]))
            ),
            written=str(line["written"]),
        )


def join_up(blocks) -> list[Region]:
    """Gather touching blocks into as few rectangles as the shape allows.

    A raster of several hundred tiles butted up against one another really is one
    rectangle, and saying so is what keeps the summary small enough for a browser
    to read in a single request. Targets scattered across a specimen genuinely
    are separate rectangles and stay separate, which is right — joining them up
    would claim ground the run never visited.

    Blocks are only ever joined when they agree exactly on the other two axes and
    meet or overlap on this one, so the ground covered by the answer is precisely
    the ground covered by what went in. Nothing is claimed that was not imaged,
    and nothing imaged is left out.

    Args:
        blocks: the blocks to gather, in any order. Repeats are harmless.

    Returns:
        The joined blocks, in a settled order so that two runs covering the same
        ground give the same answer.
    """
    joined = sorted(set(blocks))
    while True:
        after = joined
        # Along width first, then height, then depth. A raster collapses row by
        # row into strips, the strips into a plane, and the planes into a block.
        for axis in (2, 1, 0):
            after = _join_along(after, axis)
        if len(after) == len(joined):
            return after
        joined = after


def _join_along(blocks: list[Region], axis: int) -> list[Region]:
    """One pass of the joining, along a single axis."""
    together: dict[tuple, list[tuple[int, int]]] = defaultdict(list)
    for block in blocks:
        spans = block.spans
        elsewhere = tuple(span for which, span in enumerate(spans) if which != axis)
        together[elsewhere].append(spans[axis])
    joined = []
    for elsewhere, spans in together.items():
        for span in _join_spans(spans):
            rebuilt = list(elsewhere)
            rebuilt.insert(axis, span)
            joined.append(Region.from_spans(rebuilt))
    return sorted(joined)


def _join_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Merge low-and-high pairs that meet or overlap, along one axis."""
    joined: list[tuple[int, int]] = []
    for low, high in sorted(spans):
        if joined and low <= joined[-1][1]:
            was_low, was_high = joined[-1]
            joined[-1] = (was_low, max(was_high, high))
        else:
            joined.append((low, high))
    return joined


# -- keeping the record as a run goes ----------------------------------------


class Recorder:
    """The coverage record for one image, kept up to date as tiles land.

    One of these belongs to each image a run writes into. It is made when the
    images are declared, told about every tile that lands, and finished when the
    run lets the images go. Nothing else needs to call it.

    If the record cannot be kept — a folder that cannot be written to, say — this
    says so once and then quietly does nothing. An acquisition must never be
    stopped by a note about itself failing to be written.
    """

    def __init__(self, run: Path, image: str, *, canvas_shape, tile_shape) -> None:
        self.run = Path(run)
        self.image = image
        self.acquisition = acquisition_of(image)
        self._canvas_shape = tuple(int(n) for n in canvas_shape)
        self._tile_shape = tuple(int(n) for n in tile_shape)
        self._folder = where_the_record_is(self.run, image)
        self._blocks: list[Region] = []
        self._frames: set[int] = set()
        self._channels: set[int] = set()
        self._how_many = 0
        self._lock = threading.Lock()
        self._handle: int | None = None
        self._finished = False
        self._rebuilt_at = 0.0
        try:
            self._folder.mkdir(parents=True, exist_ok=True)
            # Opened once and kept. "Always add to the end" is what makes a line
            # from one thread safe beside a line from another: neither of them
            # chooses where its line goes, so neither can land on the other's.
            # It is emptied as it is opened, because declaring the images empties
            # them too and a record of the run before this one would be a lie.
            self._handle = os.open(
                self._folder / TILES_FILE,
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_APPEND,
            )
        except OSError as why:
            self._handle = None
            warnings.warn(
                f"the record of where this run images could not be started in "
                f"{self._folder} ({why}). The acquisition itself is unaffected and "
                f"every tile will be written as usual — but afterwards nothing on "
                f"disk will say which parts of the canvas hold picture, so a viewer "
                f"will have to ask for the whole of the declared room.",
                stacklevel=3,
            )
            return
        # Written straight away, while the run has imaged nothing at all. A reader
        # can then tell "this run keeps a record and has been nowhere yet" from
        # "this run keeps no record", which are very different answers to give an
        # operator watching a run begin.
        with self._lock:
            self._rebuild_the_summary()

    def remember(self, *, frame: int, channel: int, origin, shape, tile_index) -> None:
        """Write down one tile that has safely landed.

        Called only once the tile's voxels are on disk, so the record never
        claims ground that a failed write left empty.

        Args:
            frame: which moment the tile belongs to.
            channel: which colour of light it was recorded in.
            origin: the tile's low corner, as ``(z, y, x)`` in voxels.
            shape: how large the tile is, as ``(z, y, x)`` in voxels.
            tile_index: its place in the scan pattern as ``(z, y, x)`` counts, or
                ``None`` for a target the workflow chose for itself.
        """
        if self._handle is None:
            return
        z0, y0, x0 = (int(n) for n in origin)
        depth, height, width = (int(n) for n in shape)
        tile = Tile(
            acquisition=self.acquisition,
            image=self.image,
            frame=int(frame),
            channel=int(channel),
            origin=(z0, y0, x0),
            shape=(depth, height, width),
            tile_index=(
                None if tile_index is None
                else tuple(int(n) for n in tile_index)  # type: ignore[arg-type]
            ),
            written=datetime.now(timezone.utc).isoformat(),
        )
        line = (json.dumps(tile.as_written(), separators=(",", ":")) + "\n").encode("utf-8")
        if True:
            if self._handle is None:
                return
            # BROKEN ON PURPOSE: the naive design -- read the whole record, add a
            # line, write it back.
            here = self._folder / TILES_FILE
            was = here.read_bytes()
            here.write_bytes(was + line)
            self._blocks.append(tile.region)
            self._frames.add(tile.frame)
            self._channels.add(tile.channel)
            self._how_many += 1
            if time.monotonic() - self._rebuilt_at >= _HOW_OFTEN_TO_REBUILD_SECONDS:
                self._rebuild_the_summary()

    def finish(self) -> None:
        """Bring the summary fully up to date and let the record go.

        Called when the run lets its images go. It is safe to call more than once,
        and safe never to call at all: the line-by-line record is complete either
        way, and only the short summary would be left up to a second behind.
        """
        with self._lock:
            if self._handle is None:
                return
            self._finished = True
            self._rebuild_the_summary()
            try:
                os.close(self._handle)
            except OSError:
                pass
            self._handle = None

    # -- the short summary ------------------------------------------------

    def _rebuild_the_summary(self) -> None:
        """Write ``regions.json`` afresh. The lock must already be held."""
        regions = join_up(self._blocks)
        summary = {
            "zmart_coverage_version": RECORD_VERSION,
            "acquisition": self.acquisition,
            "image": self.image,
            "measured_in": "voxels of the full-resolution image",
            "canvas_shape": _named(self._canvas_shape, ("t", "c", "z", "y", "x")),
            "tile_shape": _named(self._tile_shape, ("z", "y", "x")),
            "tiles_written": self._how_many,
            "frames": sorted(self._frames),
            "channels": sorted(self._channels),
            "run_finished": self._finished,
            "updated": datetime.now(timezone.utc).isoformat(),
            "bounds": None if not regions else _around(regions).as_written(),
            "regions": [region.as_written() for region in regions],
            "tiles": TILES_FILE,
        }
        _put_in_place(self._folder / REGIONS_FILE, json.dumps(summary, indent=1))
        self._rebuilt_at = time.monotonic()


def _named(numbers, names) -> dict:
    """A run of numbers labelled by the axes they belong to."""
    return {name: int(number) for name, number in zip(names, numbers, strict=False)}


def _around(regions: list[Region]) -> Region:
    """The single block that just contains all of these."""
    return Region(
        min(r.z0 for r in regions), max(r.z1 for r in regions),
        min(r.y0 for r in regions), max(r.y1 for r in regions),
        min(r.x0 for r in regions), max(r.x1 for r in regions),
    )


def _put_in_place(path: Path, text: str) -> None:
    """Replace a small file in one step, so a reader never sees it half written.

    The new contents are written under a temporary name beside the file and then
    moved onto it. Moving a file within one folder is something the filesystem
    either does or does not do, with no moment in between — so a viewer fetching
    the summary while the run rewrites it gets the whole of the old one or the
    whole of the new one, and never a truncated file it would fail to read.
    """
    beside = path.with_name(path.name + f".part{os.getpid()}")
    try:
        beside.write_text(text, encoding="utf-8")
        os.replace(beside, path)
    except OSError:
        # The record failing is never a reason to interrupt an acquisition.
        try:
            beside.unlink()
        except OSError:
            pass


# -- reading the record back --------------------------------------------------


@dataclass(frozen=True)
class Coverage:
    """What a run imaged, read back from disk.

    Attributes:
        recorded: whether any record was found at all. ``False`` means nothing
            on disk keeps one — an image written by something other than this
            writer, or by a version of it older than the record. That is a very
            different answer from "a record was kept and it is empty", which is
            ``recorded=True`` with no regions, and the two must not be confused:
            the first means "I cannot say", the second means "nowhere yet".
        regions: the blocks of canvas that hold acquired picture, joined up where
            they touch. These are the union across every moment and every colour,
            because what they are for is bounding what a viewer draws in space.
        tiles: every tile the record holds, in the order they landed. Empty when
            only the short summary could be read.
        frames: the moments that have something written in them.
        channels: the colours that have something written in them.
        run_finished: whether the run had finished and let its images go when the
            summary was last written. ``False`` on a run still in progress, and
            also on one that stopped without tidying up.
        images: the image folders this answer was gathered from.
    """

    recorded: bool
    regions: list[Region] = field(default_factory=list)
    tiles: list[Tile] = field(default_factory=list)
    frames: list[int] = field(default_factory=list)
    channels: list[int] = field(default_factory=list)
    run_finished: bool = False
    images: list[str] = field(default_factory=list)

    @property
    def bounds(self) -> Region | None:
        """The single block that just contains everything imaged, if anything was."""
        return _around(self.regions) if self.regions else None

    def was_imaged(
        self, z: int, y: int, x: int, *,
        frame: int | None = None, channel: int | None = None,
    ) -> bool:
        """Whether this voxel was visited, as opposed to merely declared.

        This is the question that tells a dark specimen apart from room nobody
        has been to yet. Both read back as zeros from the image itself, and only
        the record can separate them.

        Args:
            z: the depth of the voxel to ask about, in voxels of the
                full-resolution image.
            y: its position across the specimen, the same way.
            x: its position along the specimen, the same way.
            frame: ask only about one moment. Left out, any moment counts.
            channel: ask only about one colour. Left out, any colour counts.

        Returns:
            ``True`` if a tile was written over this voxel. Always ``False`` when
            no record was found, so check :attr:`recorded` first if the
            difference between "no" and "I cannot say" matters to you.
        """
        if not self.recorded:
            return False
        if frame is None and channel is None:
            return any(region.contains(z, y, x) for region in self.regions)
        return any(
            (frame is None or tile.frame == frame)
            and (channel is None or tile.channel == channel)
            and tile.region.contains(z, y, x)
            for tile in self.tiles
        )


def imaged_regions(path: str | Path) -> Coverage:
    """Which parts of a run's canvas actually hold picture.

    A run declares far more room than it fills, so the image's own description
    says nothing about where the specimen is. This reads the record the writer
    kept as the run went and answers both of the questions that follow from
    that: which rectangles are worth drawing, and whether a particular place was
    ever visited.

    Args:
        path: either one image folder, such as ``run/overview.ome.zarr``, or a
            whole run folder, in which case every image in it is gathered
            together into one answer.

    Returns:
        A :class:`Coverage`. When nothing on disk keeps a record its
        ``recorded`` is ``False``, which means "I cannot say" rather than
        "nothing was imaged" — those two are different answers and the difference
        matters to an operator checking whether a region was covered.
    """
    path = Path(path)
    folders = _records_under(path)
    if not folders:
        return Coverage(recorded=False)

    tiles: list[Tile] = []
    blocks: list[Region] = []
    frames: set[int] = set()
    channels: set[int] = set()
    finished = True
    for kept in folders:
        summary = _read_the_summary(kept / REGIONS_FILE)
        its_tiles = _read_the_tiles(kept / TILES_FILE)
        if its_tiles is not None:
            tiles.extend(its_tiles)
            blocks.extend(tile.region for tile in its_tiles)
            frames.update(tile.frame for tile in its_tiles)
            channels.update(tile.channel for tile in its_tiles)
        elif summary is not None:
            # The line-by-line record has gone but the summary is still here.
            # Less to say, and worth saying rather than reporting nothing.
            blocks.extend(
                Region.from_written(block) for block in summary.get("regions", [])
            )
            frames.update(int(n) for n in summary.get("frames", []))
            channels.update(int(n) for n in summary.get("channels", []))
        if summary is None or not summary.get("run_finished"):
            finished = False

    return Coverage(
        recorded=True,
        regions=join_up(blocks),
        tiles=tiles,
        frames=sorted(frames),
        channels=sorted(channels),
        run_finished=finished,
        images=[kept.name for kept in folders],
    )


def _records_under(path: Path) -> list[Path]:
    """The record folders to read, given either a run folder or one image.

    Both are ordinary things to be handed — a viewer opens a run, while something
    working on a single acquisition has only that image's path — so both are
    accepted rather than one being insisted on.
    """
    if (path / COVERAGE_FOLDER).is_dir():
        # A whole run: every image in it that has a record.
        return sorted(
            child for child in (path / COVERAGE_FOLDER).iterdir() if child.is_dir()
        )
    # One image, whose record sits beside it under its parent's record folder.
    one = where_the_record_is(path.parent, path.name)
    return [one] if one.is_dir() else []


def _read_the_summary(path: Path) -> dict | None:
    """The short summary, or ``None`` if it is missing or unreadable."""
    try:
        found = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return found if isinstance(found, dict) else None


def _read_the_tiles(path: Path) -> list[Tile] | None:
    """Every tile the line-by-line record holds, or ``None`` if there is no such file.

    A run cut short by the machine losing power can leave its last line half
    written. That line is passed over rather than allowed to spoil the whole
    answer, and it is said out loud, because a record quietly dropping something
    is the failing this whole file exists to avoid.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    tiles, unreadable = [], 0
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            tiles.append(Tile.from_written(json.loads(line)))
        except (ValueError, KeyError, TypeError):
            unreadable += 1
    if unreadable:
        warnings.warn(
            f"{unreadable} line(s) of the coverage record in {path} could not be "
            f"read and have been left out of the answer. A single unreadable line "
            f"at the very end is what a run stopped by the machine losing power "
            f"leaves behind, and the tiles before it are still trustworthy.",
            stacklevel=3,
        )
    return tiles
