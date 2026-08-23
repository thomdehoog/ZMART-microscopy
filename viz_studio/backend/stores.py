"""Find the OME-Zarr stores under a path, whether it holds one or many.

A mesoSPIM acquisition does not produce one file. It produces a folder of
sibling stores — one per tile and channel — each carrying its own position on
the stage in its ``translation``. Opening "the acquisition" therefore means
opening all of them together and letting those translations place them, which
is what turns a pile of tiles into one specimen on screen.

The demo volume is the other shape: a single store, and a single layer. Both are
handled by asking the same question of a path — is this a store, or a folder of
stores? — so nothing upstream needs to care which it was given.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections import Counter
from pathlib import Path

# Excitation wavelength -> the false colour to draw that channel in. These are
# the conventional assignments (blue, green, amber, far-red as magenta) and the
# same palette the demo volume uses, so a real acquisition and the demo look
# like the same tool. A wavelength not listed draws white rather than guessing.
_CHANNEL_COLORS = {
    "405": (0.30, 0.45, 1.00),
    "488": (0.00, 1.00, 0.40),
    "561": (1.00, 0.75, 0.10),
    "647": (1.00, 0.20, 1.00),
}
_CHANNEL_PATTERN = re.compile(r"Ch(\d{3})")

# What several channels wear when the run declared no colours at all: the
# panel's own palette, in its own order, so a channel opened by default and a
# channel picked by hand read as the same choices. Green and magenta first
# because they are the pair colour-blind operators tell apart best.
_DEFAULT_CHANNEL_TURNS = (
    (0.00, 1.00, 0.40),  # green
    (1.00, 0.20, 1.00),  # magenta
    (0.20, 0.80, 1.00),  # cyan
    (1.00, 0.75, 0.10),  # amber
)

# The small files a zarr store writes to describe itself rather than to hold any
# of its picture: what the axes are, how large the image is, how its pieces are
# named. Version 2 uses the three beginning with a dot, version 3 uses the last
# one, and a store may hold either.
#
# This is written down once and shared, because two other parts of the viewer ask
# the same question of a folder for quite different reasons and the answer has to
# be the same in both. ``contrast`` asks "has anything actually been written into
# this copy of the image yet?" — a folder holding only these has been declared and
# never imaged into. ``server`` asks "is this a description rather than picture?",
# because a description must never be kept by the browser and picture data may be.
# Kept apart, the two lists drifted: the same four names lived in both modules
# under different spellings, so teaching the viewer about a new one meant finding
# both.
DESCRIPTION_FILES = (".zattrs", ".zarray", ".zgroup", "zarr.json")


# -- reading a store's name ----------------------------------------------------
#
# A microscope names each file it writes, and those names carry real information:
# which colour was imaged, which tile of the specimen, which filter was in the
# light path. All of that is read here, and it is used for **labels only** — the
# long note further down says why nothing here decides what belongs with what.


def channel_of(name: str) -> str | None:
    """The excitation wavelength a store's name declares, if it declares one."""
    match = _CHANNEL_PATTERN.search(name)
    return match.group(1) if match else None


def layer_names(names: list[str]) -> list[str]:
    """Short, *unique* labels for a set of stores.

    Acquisition folder names are far too long to stack in a layer list, and the
    tile and channel are usually what tell them apart — but not always. The same
    tile and channel imaged through two filters differ only in the filter block,
    so shortening blindly gives two layers the same name and the operator can no
    longer tell which is which. Shorten first, then restore whatever detail is
    needed to keep every label distinct.
    """
    short = [_short_name(name) for name in names]
    # How many stores want each short name, counted once. Asking "how many others
    # share this name?" inside the loop instead would re-read the whole list for
    # every store, which is unnoticeable for a handful and becomes the slowest thing
    # here for a run of several thousand -- measured at nearly half a second for
    # five thousand acquisitions, on a question asked every time the viewer is told
    # what is open.
    wanted = Counter(short)
    return [
        _with_filter(name, label) if wanted[name] > 1 else name
        for name, label in zip(short, names, strict=True)
    ]


def _short_name(store_name: str) -> str:
    stem = without_format_suffix(store_name)
    parts = [p for p in stem.split("_") if p.startswith("Tile") or p.startswith("Ch")]
    return "_".join(parts) if parts else stem


def _with_filter(short: str, store_name: str) -> str:
    """Add the filter block, abbreviated, to a label that would otherwise clash."""
    for part in without_format_suffix(store_name).split("_"):
        if part.startswith("Flt"):
            filter_name = part[3:] or "None"
            return f"{short}_{filter_name[:12]}"
    return short


def without_format_suffix(store_name: str) -> str:
    """A store's name with the format's suffixes taken off.

    So that what the operator reads is ``overview`` rather than
    ``overview.ome.zarr``: the suffix says which file format this is, which they
    already know and did not ask to be reminded of on every heading. It is also
    the first step in reading anything out of a name, because everything worth
    reading sits between the underscores and the suffix would come along as part
    of the last one.

    Shared with ``library``, which needs the same answer for the headings it puts
    on the panel. There were two copies of this until they were put together; they
    happened to agree, which is luck rather than design, and teaching the viewer
    about a third suffix would have meant finding both.
    """
    return (store_name.removesuffix(".zmartview.zarr")
            .removesuffix(".ome.zarr").removesuffix(".zarr"))


def channel_color(name: str) -> tuple[float, float, float] | None:
    """The colour to draw a store in, or ``None`` to leave it greyscale.

    Greyscale is the honest answer for a single-channel view: colouring one
    layer green says "this is the 488 channel" when there is nothing to
    distinguish it from.
    """
    channel = channel_of(name)
    return _CHANNEL_COLORS.get(channel) if channel else None


# -- is this folder an image at all? -------------------------------------------


def is_store(path: Path) -> bool:
    """True if ``path`` is an OME-Zarr image store (has multiscales metadata)."""
    return bool(_read_attrs_at(path).get("multiscales"))


# -- what a smart-microscopy run leaves on disk, and what we read from it ------
#
# A run's folder holds each of its kinds of scan side by side. There are two
# shapes of that, and both turn up:
#
#   overview.ome.zarr             one image per kind of scan, named after it, with
#   targetscan.ome.zarr           every position written into its own place inside.
#                                 This is what zmart_storage writes today, and it
#                                 asks for tiles that butt up against one another:
#                                 a run whose tiles overlap is refused outright, and
#                                 keeps one store per position instead -- the shape
#                                 below.
#
#   overview_pos001.ome.zarr      one image per position, named by the driver as
#   overview_pos002.ome.zarr      "{acquisition type}_{position label}" -- that is
#   targetscan_cell042.ome.zarr   canonical_stem() in the mesoSPIM driver. A
#                                 transfer of separate tiles and channels arrives
#                                 in this shape too, carrying the tile and the
#                                 channel in the name (scan_Tile0_Ch488.ome.zarr).
#
# Positions of one scan belong together: each carries its own place on the stage,
# so shown together they make one specimen rather than several unrelated pictures.
#
# **What decides that they belong together is not the name.** The viewer used to
# read the text before a store's first underscore as its acquisition type and
# gather stores by it, so what appeared on screen came from a naming convention.
# That was replaced: one load is one dataset, and the stores in a load have to be
# one acquisition -- which is checked by reading the *voxel size* out of each store
# (``voxel_size`` below, used by ``library.py``). The voxel size is the
# magnification the microscope actually used and cannot be anything else, whereas a
# folder can be renamed by anybody. A folder holding two magnifications is
# therefore refused, with both named, rather than merged; see
# ``_one_acquisition_only`` in ``library.py``.
#
# The names are still read, for three things, and it is worth knowing which:
#
#   - the channel, where a store holds a single one and says so in its name
#     (``Ch488``): that gives the row its label and its false colour. See
#     ``channel_of`` and ``channel_color``.
#   - the tile and the filter block (``Tile0``, ``Flt...``), which keep layer
#     labels short and, where two stores would otherwise read the same, distinct.
#     ``select_tiles`` and ``prefer_filter`` let an operator ask for some of them.
#   - the kind of scan, as a heading only, when the viewer has had to open a
#     dataset on its own because a second acquisition appeared in a folder it was
#     watching. See ``_acquisition_type_in`` in ``library.py``.
#
# None of those three decides what belongs with what, which is the point: a run may
# invent a kind of scan we have never heard of and name it anything at all, and it
# will still be shown correctly, because what is compared comes from inside the
# stores.


# -- repairing the way a store spells its units --------------------------------
#
# A store that names its units the way a microscopist would write them is refused
# outright by the drawing engine — the whole image, not the offending axis. That
# is a foreign instrument's habit rather than a fault of ours, and it is cheap to
# put right on the way past, so it is put right here.


# What an axis unit is called in the format, against what microscopists and their
# software actually write. OME-Zarr asks for the UDUNITS-2 name and the engine
# refuses a store that says anything else -- rejecting the whole image, not the
# axis -- so a store saying "um" is unopenable until this is put right.
_UNIT_SPELLINGS = {
    "um": "micrometer",
    "µm": "micrometer",  # the micro sign, U+00B5
    "μm": "micrometer",  # greek small letter mu, U+03BC -- identical to look at
    "nm": "nanometer",
    "mm": "millimeter",
    "cm": "centimeter",
    "m": "meter",
    "s": "second",
    "ms": "millisecond",
}


def _ome_holders(described: dict) -> list[dict]:
    """Every place inside a parsed description where the OME metadata could be living.

    The format has moved this twice, and a reader that knows only one of the places
    stops working the moment an instrument is updated. OME-Zarr 0.4 puts
    ``multiscales`` and ``omero`` at the top of the file. 0.5 gathers them under an
    ``ome`` key. And zarr version 3, which 0.5 goes with, keeps a store's own
    attributes under ``attributes`` inside ``zarr.json`` — so a 0.5 store written
    that way nests them twice over, at ``attributes.ome``.

    All of those are returned, outermost first, so a caller can look in each without
    having to work out which version wrote the store. The dictionaries handed back
    are the very ones inside ``described`` rather than copies of them, which is what
    lets :func:`normalise_units` repair a unit in place wherever it finds it.
    """
    holders = []
    for outer in (described, described.get("attributes")):
        if not isinstance(outer, dict):
            continue
        holders.append(outer)
        nested = outer.get("ome")
        if isinstance(nested, dict):
            holders.append(nested)
    return holders


def normalise_units(raw: bytes) -> bytes:
    """A store's description with its axis units spelled the way the format asks.

    Returned unchanged — the same object, so the caller can tell — whenever there
    is nothing to repair. That matters for more than speed: these descriptions are
    remembered and handed to the browser to keep, and rewriting one that was
    already correct would mean every store in the world got a new copy of itself.

    Anything unrecognised is passed through rather than guessed at, and a
    description that cannot be read is handed back exactly as it was found. A
    repair that breaks a store which used to open would be far worse than a store
    that never opened.
    """
    if b"unit" not in raw:
        return raw
    try:
        described = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return raw
    if not isinstance(described, dict):
        return raw
    # A store keeps its axes wherever its own version of the format put them, and the
    # repair has to reach all of those places -- see :func:`_ome_holders`. This matters
    # more than it looks: the whole reason the repair exists is a foreign instrument
    # whose store says "um", and an instrument that has moved on to OME-Zarr 0.5 is
    # exactly the one most likely to need it.
    changed = False
    for holder in _ome_holders(described):
        for multiscale in holder.get("multiscales") or []:
            if not isinstance(multiscale, dict):
                continue
            for axis in multiscale.get("axes") or []:
                if not isinstance(axis, dict):
                    continue
                spelled = axis.get("unit")
                correct = _UNIT_SPELLINGS.get(spelled) if isinstance(spelled, str) else None
                if correct is not None and correct != spelled:
                    axis["unit"] = correct
                    changed = True
    if not changed:
        return raw
    return json.dumps(described).encode("utf-8")


# -- the two facts that decide what belongs with what --------------------------
#
# How large a voxel is, and what a store calls its own channels. Both are read
# from inside the store, and `library` compares them to work out whether two
# stores are pieces of one acquisition or two different ones.


def voxel_size(store: Path) -> tuple[float, ...]:
    """How large one voxel is at full resolution, as the store itself declares it.

    This is what says whether two stores belong to the same acquisition. An
    overview and a target scan of the same specimen differ here and cannot not
    differ — it is the magnification they were taken at — whereas a name can be
    changed by anyone and a channel can simply not have been imaged yet.

    Only the **spatial** axes are reported, and that is the whole point rather
    than a simplification. Magnification is a fact about space; the scale entries
    for time and channel say nothing about what was imaged, and comparing the
    whole list would make a timelapse and a single volume of the very same
    acquisition look like different ones because one has an extra number in front.

    Rounded, because the number is only ever compared with another of its kind
    and two writers can spell the same voxel size a hair apart.

    An empty tuple means the store does not say, in which case it is not held
    against it: a store that declares nothing matches anything.
    """
    described = (_read_attrs_at(store).get("multiscales") or [{}])[0]
    levels = described.get("datasets") or [{}]
    for transform in levels[0].get("coordinateTransformations") or []:
        if isinstance(transform, dict) and transform.get("type") == "scale":
            found = transform.get("scale")
            if not isinstance(found, list):
                continue
            names = axis_names(store)
            if len(names) == len(found):
                found = [
                    value for name, value in zip(names, found, strict=True)
                    if name in ("z", "y", "x")
                ]
            return tuple(round(float(value), 6) for value in found)
    return ()


def declared_channels(store: Path) -> list[str] | None:
    """The channels a store names inside itself, or ``None`` if it holds one image.

    Two stores that each declare their own channels and declare different ones are
    not the same acquisition, whatever they are called. Where the channel is in the
    filename instead there is nothing to compare — one store is one channel — so
    this answers ``None`` and the caller must not read that as "no channels".
    """
    if "c" not in axis_names(store):
        return None
    return [str(channel["name"]) for channel in channels(store)]


# A store's description is read many times over while the panel is being built --
# once for the axes, again for the channels, again for the frame count, and so on.
# It is a small file and it rarely changes, so it is remembered against its own
# modification time: unchanged means the remembered copy is used, and a store that
# has been rewritten is read afresh. At four hundred stores this is the difference
# between three thousand file reads per refresh and a few hundred quick glances.
_attrs_cache: dict[str, tuple[int, dict]] = {}


# -- reading the small files that describe a store ------------------------------
#
# Every question above ends up here. A store keeps a short text file saying what
# it is; opening one acquisition of two hundred tiles means reading a thousand of
# them, so they are remembered rather than read again, and the remembering is
# checked against the file's own modification time so a run that rewrites one is
# still noticed.


def _description_file(path: Path) -> Path | None:
    """Where this store keeps its description, whichever version wrote it.

    Version 2 puts it in ``.zattrs`` beside a ``.zgroup``; version 3 puts
    everything in one ``zarr.json``. Nothing else in this module needs to know
    which, because :func:`_read_attrs_at` hands both back in the same shape.
    """
    for name in (".zattrs", "zarr.json"):
        candidate = path / name
        if candidate.exists():
            return candidate
    return None


def _read_attrs_at(path: Path) -> dict:
    """The OME-Zarr description at ``path``, or an empty one if unreadable.

    Version 3 nests what we want twice over: the attributes live under
    ``attributes`` in ``zarr.json``, and OME-Zarr 0.5 puts ``multiscales`` and
    ``omero`` under an ``ome`` key inside that. Both are lifted here — see
    :func:`_ome_holders` for the places that are looked in — so that everything
    downstream, meaning axes, channels, voxel size and frame counts, reads one flat
    description and never asks which version wrote it.
    """
    key = str(path)
    described = _description_file(path)
    if described is None:
        _attrs_cache.pop(key, None)
        return {}
    try:
        stamp = described.stat().st_mtime_ns
    except OSError:
        _attrs_cache.pop(key, None)
        return {}
    remembered = _attrs_cache.get(key)
    if remembered is not None and remembered[0] == stamp:
        return remembered[1]
    try:
        attrs = json.loads(described.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        attrs = {}
    if not isinstance(attrs, dict):
        attrs = {}
    if described.name == "zarr.json":
        # Everything else in a version 3 file describes the group rather than the
        # image, so the store's own attributes are all we want from it.
        attrs = attrs.get("attributes") if isinstance(attrs.get("attributes"), dict) else {}
    # Flattened by merging each place the metadata could be, the innermost last so
    # that a store nesting it under "ome" wins over anything left at the top.
    flat: dict = {}
    for holder in _ome_holders(attrs):
        flat.update(holder)
    attrs = flat
    _attrs_cache[key] = (stamp, attrs)
    return attrs


# -- what the array inside a store says about itself ---------------------------
#
# The store's description, read above, says what the image *is*: its axes, its
# channels, how large a voxel is. The array inside it keeps a second description,
# just as small, saying how the image is actually laid out on disk — how long it is,
# how its pieces are named, and how much of the image one piece holds. Two questions
# here need those facts, and getting them wrong is not harmless: it either offers the
# operator moments that were never imaged, or hides moments that were.
#
# Zarr version 2 writes this as ``.zarray`` beside the pieces, version 3 as a
# ``zarr.json`` in the same place. The two say the same things under different names,
# and :func:`_read_array_description` hands both back in one shape so that nothing
# below has to ask which version wrote the store.
#
# What it costs: one small file read per store, and only the first time. The answer is
# remembered against the file's own modification time, exactly as the store's
# description is, because an array's layout does not change once the array exists. So
# a folder of tens of thousands of stores pays one read each when it is opened and
# nothing at all on later refreshes.
_array_cache: dict[str, tuple[int, dict]] = {}


def _read_array_description(level: Path) -> dict:
    """How the array at ``level`` is laid out on disk, whichever zarr version wrote it.

    ``level`` is the folder holding one copy of the image — ``0`` inside
    the store, for the full-resolution copy. What comes back is a small set of facts,
    and an empty answer if the array cannot be read at all:

    ``shape``
        How long the array is along each axis, as the store declares it. Note that
        this is room promised rather than images written, which is the whole reason
        :func:`written_timepoints` has to go and look at what is on disk.
    ``pieces``
        How much of the image, along each axis, a single *file* on disk covers.
    ``prefix`` and ``separator``
        How a piece's name is built from its position, described in full under
        :func:`_count_frames`.

    Nothing here raises. A store caught half-written, or one whose description is not
    the shape we expect, comes back as an empty answer and the callers then decline to
    say anything rather than guessing.
    """
    key = str(level)
    for name in (".zarray", "zarr.json"):
        found = level / name
        try:
            stamp = found.stat().st_mtime_ns
        except OSError:
            continue
        remembered = _array_cache.get(key)
        if remembered is not None and remembered[0] == stamp:
            return remembered[1]
        try:
            described = json.loads(found.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            described = None
        answer = _array_layout(described) if isinstance(described, dict) else {}
        _array_cache[key] = (stamp, answer)
        return answer
    _array_cache.pop(key, None)
    return {}


def _array_layout(described: dict) -> dict:
    """Read one array description into the shape :func:`_read_array_description` promises."""
    shape = _numbers(described.get("shape"))
    if described.get("zarr_format") == 3 or "chunk_grid" in described:
        return {"shape": shape, **_version_3_layout(described)}
    return {"shape": shape, **_version_2_layout(described)}


def _version_2_layout(described: dict) -> dict:
    """Version 2, which names its pieces plainly: ``3.0.0`` or, in folders, ``3/0/0``."""
    separator = described.get("dimension_separator")
    return {
        "pieces": _numbers(described.get("chunks")),
        "prefix": "",
        # A version 2 array that says nothing files its pieces side by side in one
        # folder, which is the layout `DATA_LAYOUT.md` asks writers to avoid.
        "separator": separator if separator in ("/", ".") else ".",
    }


def _version_3_layout(described: dict) -> dict:
    """Version 3, which has two ways of naming a piece and a default for each.

    The ``default`` naming puts a ``c`` in front of every piece — ``c/3/0/0`` — to
    keep the pieces from being confused with anything else in the folder, and its
    separator is a slash unless the store says otherwise. The ``v2`` naming leaves the
    ``c`` off, so it looks exactly like version 2, and its separator is a dot unless
    the store says otherwise. Those two defaults being *different* is the easiest thing
    to get wrong here.

    One thing worth knowing about the sizes: the chunk grid describes the pieces that
    are really written as files, so where a ``sharding_indexed`` codec packs many small
    chunks into one large file, the grid already gives the size of that file. That is
    why the codecs do not have to be read to find out how much of the image one file
    covers.
    """
    grid = described.get("chunk_grid")
    settings = grid.get("configuration") if isinstance(grid, dict) else None
    encoding = described.get("chunk_key_encoding")
    encoding = encoding if isinstance(encoding, dict) else {}
    named = encoding.get("configuration")
    named = named if isinstance(named, dict) else {}
    prefix, fallback = ("", ".") if encoding.get("name") == "v2" else ("c", "/")
    separator = named.get("separator")
    return {
        "pieces": _numbers(settings.get("chunk_shape") if isinstance(settings, dict) else None),
        "prefix": prefix,
        "separator": separator if separator in ("/", ".") else fallback,
    }


def _numbers(value: object) -> list[int]:
    """A list of whole numbers out of a description, or nothing if it is not one."""
    if not isinstance(value, list):
        return []
    try:
        return [int(number) for number in value]
    except (TypeError, ValueError):
        return []


# -- the shape of the image: axes, channels, and masks --------------------------
#
# What the panel needs before it can offer anything: which axes the image has, how
# many channels are really in it, and whether any of the images beside it are maps
# of objects rather than pictures.


def zarr_scheme(store: Path) -> str:
    """Which of the engine's zarr readers should be asked for this store.

    The engine registers three: ``zarr`` detects the version itself, ``zarr2`` and
    ``zarr3`` are told. We tell it, because detection means probing for *both*
    layouts on every source, and a large folder is already dominated by exactly
    those small metadata requests.

    Anything we cannot identify is called version 2, which is what every store
    written before this existed is.
    """
    return "zarr3" if (store / "zarr.json").exists() else "zarr2"


def axis_names(store: Path) -> list[str]:
    """The axes this store declares, in order — for example ``[t, c, z, y, x]``.

    Reading them matters because a store need not have all five. A single-moment
    volume has no ``t``; a flat overview has no ``z``. The viewer offers a slider
    only for an axis that is really there, so this is what it asks.
    """
    axes = (_read_attrs_at(store).get("multiscales") or [{}])[0].get("axes") or []
    return [axis.get("name", "") for axis in axes if isinstance(axis, dict)]


def channels(store: Path) -> list[dict]:
    """Describe each channel inside this store: its name and its colour.

    Channels used to be told apart by the store's *filename* (a ``Ch488`` in it),
    which worked while every channel was saved as its own file. Once several
    channels live inside one store — the ``c`` axis of a ``t,c,z,y,x`` image —
    the filename can no longer say which is which, so the answer has to come from
    the file's own description.

    OME-Zarr carries that in an optional ``omero`` block: a label and a colour per
    channel, exactly what a layer list wants to show. Where it is missing, or
    where it disagrees with the array, the channels are still reported — numbered
    plainly and left greyscale — because a channel we cannot name is far better
    shown than silently dropped.

    Returns one entry per channel, each with ``name`` and ``color`` (an ``r, g, b``
    triple of fractions, or ``None`` to draw it greyscale).
    """
    attrs = _read_attrs_at(store)
    names = axis_names(store)
    described = attrs.get("omero", {}).get("channels")
    described = described if isinstance(described, list) else []

    count = _channel_count(store, names, len(described))
    if count is None:
        # No channel axis at all: the store is one image, so it is one layer.
        return [{"name": _short_name(store.name), "color": None}]

    return described_channels(described, count)


def described_channels(described: list[dict], count: int) -> list[dict]:
    """Turn a description's channel entries into what a layer list shows.

    Split out from :func:`channels` because the entries do not always come
    from a store's own file. A live run settles its colours when its profile
    is sealed, and the picture built over a single-colour run carries no
    colour axis for a reader to find -- so the live adapter reads the run's
    description instead and hands it here, and both roads end up describing
    a channel in exactly the same way.

    ``count`` is how many channels there really are, which the caller knows
    better than the description does.
    """
    out = []
    for index in range(count):
        entry = described[index] if index < len(described) else {}
        entry = entry if isinstance(entry, dict) else {}
        label = entry.get("label") or entry.get("name") or f"channel {index + 1}"
        out.append({
            "name": str(label),
            "color": _hex_to_rgb(entry.get("color")),
            "window": _the_window_asked_for(entry),
            # The range those numbers live in, as the run states it. A camera
            # is often read out at fewer bits than the file can hold -- twelve
            # into sixteen is the ordinary case -- so believing the file's
            # number type puts the specimen in the first sixteenth of the
            # brightness axis and leaves the rest as headroom that does not
            # exist. Where the run says nothing this stays None and the axis
            # falls back to what the number type can hold.
            "range": _the_range_declared_by(entry),
            # Which channels the run had switched on. Absent means on: a run
            # that never mentioned a channel has not switched it off.
            "active": entry.get("active") is not False,
        })
    # Channels of one picture sum like light on screen, and several channels
    # all opening white summed a real plate to pure clipping -- every well
    # white, no structure, no colour. Where the run declared nothing, the
    # channels take distinct colours in turn (the panel's own palette order,
    # the convention napari opens multichannel images with). One channel
    # alone keeps its greyscale: with nothing to distinguish it from, a
    # colour would be an invention.
    if count > 1:
        # And a picture whose channels ALL answer white — declared or
        # defaulted — is the same clipping by another road, so the palette
        # takes over whole. One white channel among coloured ones is a
        # choice and is left alone (the operator's rule: never load an
        # image in only white, 2026-08-23).
        if all(channel["color"] in (None, (1.0, 1.0, 1.0)) for channel in out):
            for channel in out:
                channel["color"] = None
        turn = 0
        for channel in out:
            if channel["color"] is None:
                channel["color"] = _DEFAULT_CHANNEL_TURNS[
                    turn % len(_DEFAULT_CHANNEL_TURNS)]
                turn += 1
    return out


def _the_range_declared_by(channel: dict) -> dict | None:
    """The whole range this channel's numbers live in, if the run says.

    This is the ``min`` and ``max`` beside the window's ``start`` and ``end``:
    not what to show, but what the values could be. It is the honest axis for
    a histogram, and it is frequently NOT the number type's own -- a twelve-bit
    camera written into sixteen-bit files says 0 to 4095 here, and an axis
    drawn to 65535 instead would leave the specimen crushed into the first
    sixteenth of the track under four times as much headroom as exists.

    Returns ``None`` where the run says nothing, or where what it says makes no
    range, and the caller then falls back to the number type.
    """
    window = channel.get("window")
    if not isinstance(window, dict):
        return None
    low, high = window.get("min"), window.get("max")
    if not isinstance(low, (int, float)) or not isinstance(high, (int, float)):
        return None
    if high <= low:
        return None
    return {"low": float(low), "high": float(high)}


def _the_window_asked_for(channel: dict) -> dict | None:
    """The brightness a run asked this channel to be shown between, if it said.

    This is the ``start`` and ``end`` of the channel's ``window``, and taking the
    right two of the four numbers there matters more than it looks. A window also
    carries ``min`` and ``max``, and those are the *camera's whole range* — for a
    16-bit camera, nought to sixty-five thousand. A real specimen occupies a narrow
    band inside that, so opening an acquisition on ``min`` and ``max`` shows a
    picture that is very nearly black and stays that way until somebody thinks to
    drag a slider. ``start`` and ``end`` are what the run actually asked for.

    Returns ``None`` where the run said nothing, and then the viewer works the
    brightness out by reading the picture instead.
    """
    window = channel.get("window")
    if not isinstance(window, dict):
        return None
    low, high = window.get("start"), window.get("end")
    if not isinstance(low, (int, float)) or not isinstance(high, (int, float)):
        return None
    if high <= low:
        return None
    # A start and end that merely restate the camera's whole range are the
    # writer declaring ignorance, not a run asking for anything: our own live
    # writer always records a complete window (strict readers refuse a block
    # without one) and puts the camera's range there when the run said
    # nothing. Taken at face value it opened every such run nearly black --
    # the specimen sits in the bottom few per cent of the range -- so it is
    # treated as unspoken, and the viewer measures a window from the pixels.
    if low == window.get("min") and high == window.get("max"):
        return None
    return {"low": float(low), "high": float(high)}


def _channel_count(store: Path, names: list[str], described: int) -> int | None:
    """How many channels the store's own array says it has.

    The array is the authority, not the ``omero`` block: a description listing
    three channels for a two-channel array would otherwise produce a layer with
    nothing behind it.

    The array's own length is read through :func:`_read_array_description`, so this
    holds for a version 3 store as well as a version 2 one. That is not a detail: a
    store written to OME-Zarr 0.5 keeps its ``omero`` block in a different place but
    is no more likely to have got the number right, and falling back to what the
    description claims is precisely how the empty layer appears.
    """
    if "c" not in names:
        return None
    datasets = (_read_attrs_at(store).get("multiscales") or [{}])[0].get("datasets") or []
    if not datasets:
        return described or None
    shape = _read_array_description(store / str(datasets[0].get("path"))).get("shape") or []
    index = names.index("c")
    return int(shape[index]) if index < len(shape) else (described or None)


def label_images(store: Path) -> list[str]:
    """The segmentation masks stored alongside this image, if any.

    A mask is not dim picture data: its pixel values are the identity numbers of
    the objects somebody (or something) found — cell 1, cell 2, cell 3. Drawing it
    like an image would be close to useless, so the viewer shows it differently,
    giving every object its own colour and letting you pick one out.

    OME-Zarr has a standard place for these: a ``labels`` folder inside the image,
    listing the masks it holds. Reading it from there means nothing has to be
    guessed from file names.
    """
    folder = store / "labels"
    listed = _read_attrs_at(folder).get("labels")
    names = [name for name in listed if isinstance(name, str)] if isinstance(listed, list) else []
    if not names:
        # A labels folder with no list in it is still worth looking inside, since
        # the list is optional and a mask that is present should be shown.
        try:
            names = sorted(child.name for child in folder.iterdir() if is_store(child))
        except OSError:
            return []
    return [name for name in names if is_store(folder / name)]


# -- how far a timelapse has actually been written ------------------------------
#
# A store is given its full length in time the moment it is created, long before
# the run has produced that many moments. The slider must not offer moments that
# do not exist yet, so how far the image really reaches is counted from the disk.
# This is the most expensive question in this module and the one most carefully
# bounded; `written_timepoints` sets out what it can and cannot promise.


# Counting frames means looking in the folder that holds the image's pieces, and
# on a large acquisition that folder is enormous. This is the most that will be
# looked at before giving up: past it the answer is not worth the time it costs,
# and the viewer falls back to the length the file claims. A store written the way
# `DATA_LAYOUT.md` asks never reaches this, because its pieces are filed in folders
# and so this folder holds one entry per frame rather than one per piece of image.
_SCAN_LIMIT = 20_000


class _TooManyToCount:
    """Stands for "this folder holds more pieces than it is sensible to look through".

    Counting can fail to give a number for two quite different reasons, and they
    need remembering differently. A folder too large to look through will never
    become small again, so that answer can be kept for good. A store that has
    simply not been written to yet is empty only for the moment — it is a live run
    about to produce its first frame — and keeping *that* answer would leave the
    viewer believing the run was empty for the rest of the session. Both reasons
    reach the caller as "no number available", but only this one is remembered.
    """


_TOO_MANY = _TooManyToCount()

# Remembering the answer alongside the folder's own modification time, so asking
# again costs one cheap look unless something has actually been written since.
_frame_counts: dict[str, tuple[int, int | None | _TooManyToCount]] = {}

# How recently the folder may have been touched before its modification time can
# be trusted to move again. Filesystems stamp folders from a clock that ticks
# more coarsely than they write -- Windows caches the current time for up to
# about sixteen milliseconds -- so a frame landing within the same tick as the
# count leaves the stamp exactly where it was, and a count remembered against
# that stamp would be served, wrongly, for the rest of the session. The rule is
# the one build tools settled on long ago: an answer measured against a stamp
# still within the clock's reach of "now" is used but not remembered, and the
# next asker counts again. It costs one extra folder reading in the rare moment
# an ask lands right on a write, and nothing the rest of the time.
_MTIME_STILL_MOVING_NS = 100_000_000


def forget(store: Path) -> None:
    """Let go of everything remembered about one store, because it has been closed.

    Remembering what a store contains is what keeps the viewer quick: the small
    files describing it are read once and then only glanced at. The other side of
    that is that nothing is ever forgotten on its own, and a session in which an
    operator opens a large folder, looks at it, closes it and opens the next one
    would hold on to every folder they had visited for as long as the viewer was
    running. Closing something should give the memory back — otherwise "close what
    you are not using" is advice the viewer does not honour.

    Everything remembered here is filed under the store's own path on disk, so one
    call is enough for all of it. Forgetting is always safe: the worst it can cost
    is reading a small file again.
    """
    under = str(store)
    # The separator is the operating system's rather than a plain slash, because
    # these keys are paths as this machine writes them and Windows writes them with
    # a backslash. Matching the store's own name as well as things inside it, and
    # insisting on the separator, keeps a store called "overview" from taking
    # "overview-2" with it.
    inside = under + os.sep
    for remembered in (_attrs_cache, _array_cache, _frame_counts):
        for key in [key for key in remembered if key == under or key.startswith(inside)]:
            del remembered[key]


def written_timepoints(store: Path) -> int | None:
    """How far into a timelapse the images on disk reach, so the slider can stop there.

    A store is given its full length in time when it is created, long before the
    run has produced that many frames — that is what keeps an unpredictable
    timelapse cheap. But the viewer must not offer a slider running out to frames
    that do not exist yet: the engine remembers "there is nothing here" for a frame
    it looked at too early and will not look again, so that frame would stay blank
    for the rest of the session even once it had been imaged.

    **What the number means, exactly.** It is one past the furthest moment that
    holds an image. An answer of 5 says the furthest image sits at moment 4, so the
    slider should offer moments 0 to 4 and no further. Read it as *how far the data
    reaches*, which is not quite the same as *how many moments were imaged*, and the
    difference is worth understanding before relying on either.

    For an ordinary timelapse, which fills its moments in order, the two are the
    same number and there is nothing to think about. They come apart when a moment
    in the middle holds no image, and that happens for two everyday reasons rather
    than through any damage. A workflow that images a canvas at the moments it
    chooses may write moment 900 without ever having written the 899 before it. And
    a frame that came out entirely black — a bleached specimen, or an acquisition
    that failed — is stored as nothing at all, because zarr does not save a piece of
    image that holds only the fill value.

    In the first of those this answers 901, and in the second — say seven moments
    imaged with the fourth of them black — it answers 7. Both reach everything that
    is on disk. The empty moments in between are offered as well and draw as
    nothing, which is honest about them, and it is the lesser of the two mistakes
    available. Stopping the slider earlier, at the last moment before the first gap,
    would leave real and readable data with no way to get to it and nothing on
    screen to say it was ever there.

    **What ``None`` means.** There is nothing to stop the slider at, so the viewer
    places no limit on it and every moment the store declares can be reached. That
    is the answer when the store has no time axis, when nothing has been written
    yet, when the answer cannot be had cheaply, and when a single file on disk holds
    more than one moment — on which see :func:`_count_frames`, because that last one
    is the case where a number would be badly wrong rather than merely unavailable.
    It is deliberately not used for a timelapse with gaps in it, because for a store
    declaring room for ten thousand moments it would offer all ten thousand — many
    more empty ones than simply reaching as far as the data does.

    **How the image is filed decides whether this is instant or ruinous.** A piece
    of the image is stored under a name built from its position. Those names can be
    laid out two ways, and OME-Zarr allows both:

    - **Filed in folders** (the pieces of one frame together, then one channel,
      then one plane). Counting frames is then a reading of one small folder that
      holds a single entry per frame, however large the image itself is. This is
      what large acquisitions should use.
    - **All in one folder**, every piece a separate file with its position in the
      name. A 400 GB image has some three million of them in that one folder,
      which is slow to look through and hard on the file system besides. Here the
      look is capped and, past the cap, abandoned rather than allowed to stall the
      viewer.

    Zarr version 3 spells both of those slightly differently — it usually puts a
    ``c`` in front of every piece — and :func:`_count_frames` reads all of the
    spellings. Nothing above changes for a version 3 store; only the names do.

    **Three limits, written down because they will otherwise surprise somebody.**
    None of them can lose data, and all three come from the same decision: the
    answer is read from what is on disk, and the disk is trusted.

    - *The answer is not held down by the length the store declared.* A stray
      folder called ``9999`` sitting in a store that declared room for ten moments
      gives ten thousand. Nothing here checks the two against each other. What
      keeps the slider sensible is that it clamps to the store's declared length
      itself — see ``AxisSlider.jsx`` — so an impossible number never reaches the
      operator. It is worth knowing that this is where the safety comes from,
      because a second reader of this function would not get it for free.
    - *An empty leftover moment still counts as reach.* A frame folder left behind
      by an earlier run, holding nothing, is indistinguishable from a moment that
      was imaged and came out black. Both are counted, so the slider runs out to
      the leftover and the moments there draw as nothing.
    - *Freshness is exact equality on the folder's modification time.* The answer
      is kept and re-used until that time changes. A folder replaced by a shorter
      one carrying an identical timestamp — which ``cp -a`` from an archive does —
      keeps the old, longer answer for the rest of the session. Touching the
      folder, or reopening the viewer, puts it right. The one refinement is that
      an answer counted while the stamp is still within the filesystem clock's
      reach of "now" is not remembered at all — see ``_MTIME_STILL_MOVING_NS`` —
      because a frame landing in the same clock tick would leave the stamp
      unchanged and the remembered answer stale for good.
    """
    names = axis_names(store)
    if "t" not in names or names.index("t") != 0:
        return None
    datasets = (_read_attrs_at(store).get("multiscales") or [{}])[0].get("datasets") or []
    if not datasets:
        return None
    level = _the_copy_that_holds_the_picture(store, datasets)
    # Which folder gains an entry as each moment lands depends on how the store names
    # its pieces, so it has to be worked out rather than assumed to be this one. Watch
    # the wrong folder and its modification time never moves, which would leave the
    # viewer repeating the first answer it ever worked out however long the run went on.
    watched = _moments_folder(level)

    try:
        stamp = watched.stat().st_mtime_ns
    except OSError:
        return None
    remembered = _frame_counts.get(str(watched))
    if remembered is not None and (remembered[0] == stamp or remembered[1] is _TOO_MANY):
        # A folder holding too many pieces to look through will not hold fewer
        # later, so that verdict stands whatever is written next. Without this the
        # look would be repeated on every refresh -- and a piece is written every
        # few seconds during a run, so the modification time is always moving.
        #
        # Every other answer is only kept while the folder is untouched. That
        # matters most for a store looked at before its first frame has landed:
        # the honest answer then is "nothing yet", and it has to be asked again
        # once the run starts writing, or the viewer would offer no frames at all
        # for the rest of the session.
        return None if remembered[1] is _TOO_MANY else remembered[1]

    answer = _count_frames(level)
    if answer is _TOO_MANY or time.time_ns() - stamp > _MTIME_STILL_MOVING_NS:
        _frame_counts[str(watched)] = (stamp, answer)
    return None if answer is _TOO_MANY else answer


def _the_copy_that_holds_the_picture(store: Path, datasets: list[dict]) -> Path:
    """Which copy of the image to count the moments from.

    Almost always the full-size one, which is where the picture is, and it is asked
    first for exactly that reason: it is the copy that gains a file the instant a
    frame lands, so it gives the freshest answer during a run.

    There is one arrangement where it holds nothing at all, and it is not damage. An
    acquisition can be shown as one image whose full-size picture is never written
    down — it is a list of pointers into the tiles that already exist, and only the
    zoomed-out copies are written (see ``linking.py``). Counting frames from a copy
    that is empty by design would say the run had imaged nothing, and the time slider
    would offer no frames at all for a timelapse that is plainly on screen. So where
    the full-size copy holds no picture, the next copy down is asked instead, and so
    on. Every copy is written as each tile arrives, so they all reach the same moment
    and the answer is the same one by a slightly longer road.

    The look is a single reading of a folder that holds one entry per moment, so it
    costs nothing worth measuring, and it stops at the first copy that has anything
    in it.
    """
    copies = [store / str(entry.get("path")) for entry in datasets]
    for level in copies:
        holder = _moments_folder(level)
        try:
            if any(entry.name not in DESCRIPTION_FILES for entry in holder.iterdir()):
                return level
        except OSError:
            continue
    return copies[0]


def _moments_folder(level: Path) -> Path:
    """The folder that gains an entry as each moment of a timelapse is written.

    For nearly every layout that is the copy's own folder, ``0`` inside the
    store. Zarr version 3's default naming is the exception: it files every piece under
    a folder called ``c`` inside that one, so ``c`` is what grows as the run goes and
    ``0`` itself is left untouched after the array is created.

    This is what the frame count is remembered against, which is why it matters. A
    folder whose modification time never moves looks to the viewer like a run that
    never produced another frame.
    """
    described = _read_array_description(level)
    if described.get("prefix") and described.get("separator") == "/":
        return level / str(described["prefix"])
    return level


def _count_frames(level: Path) -> int | None | _TooManyToCount:
    """One past the furthest moment that holds an image, found by reading the folder.

    Every piece of the image is named after the position it holds, so the moments
    that have been written can be read straight off the names here. The furthest of
    them is what the viewer needs: stop the time slider one past it and everything
    on disk stays reachable while nothing beyond it is offered.

    The whole folder is read before answering, and that is the point rather than an
    oversight. A moment in the middle can perfectly well hold no image — see
    :func:`written_timepoints` for the two ordinary reasons — so stopping at the
    first missing one would hide every moment after it.

    **The names to expect, and there are more of them than there used to be.** A piece
    is named after the position it holds, and both zarr versions offer a choice of
    separator between the numbers of that position. Version 3 adds a ``c`` in front by
    default, to keep its pieces distinct from anything else in the folder. Reading only
    the version 2 spellings is what made this answer ``None`` for a version 3 store,
    and ``None`` means "do not limit the slider" — so a run of three moments inside a
    store declaring a thousand offered the operator all thousand of them.

    ``None`` means nothing countable is there *yet*: the run has not written its
    first frame, or the folder could not be read at this moment. That is an ordinary
    and hopeful answer, worth asking about again shortly. ``_TOO_MANY`` is the other
    way of coming away without a number and it is final: there are more pieces in
    this folder than it is sensible to look through, and a folder that large is not
    going to become small again.

    **One file holding several moments is a third way of coming away with nothing, and
    it is the important one.** Everything above rests on a file's name telling you which
    moment it belongs to, and that only holds while one file is one moment. A store may
    instead give each file a span of the time axis — a chunk covering ten moments, or a
    shard packing a thousand of them into one file — and then the furthest file says
    almost nothing about how far the images reach. A run nine hundred moments in, writing
    into a shard that spans a thousand, has produced exactly one file, numbered zero:
    counted naively that reads as a single moment imaged, and the operator would be shown
    one moment out of nine hundred that exist and are perfectly readable.

    So where a file spans more than one moment this declines to answer at all. That looks
    like giving up more than the rest of this function does, and it is the right way
    round. Under-reporting is tolerable only while the error is bounded by a single
    moment, which is what the layouts above guarantee. Bounded by the span of a shard it
    hides the whole run, and no number is better than that number.

    Either way the caller ends up without a number and should then not limit the
    time slider at all. The operator can reach every moment the store declares, and
    one that holds no image shows as empty rather than as missing. That is a better
    outcome than making them wait while the viewer counts files.

    **What this costs, and why that is affordable.** One reading of the folder,
    every time the folder has changed. :func:`written_timepoints` only asks when the
    folder's modification time has moved, which during a live run means once per new
    frame rather than once per refresh, and a folder of finished acquisitions is not
    read again after the first look at all. A store filed the way `DATA_LAYOUT.md`
    asks holds one entry per frame here, not one per piece of image, so even a very
    long timelapse is a few thousand names: measured at 0.9 ms for a thousand frames
    and 7.5 ms for ten thousand.

    An earlier version was cheaper than that on a store it had already seen. It
    remembered the highest frame it had found and each time asked only whether the
    next one along had appeared — a single look, some 0.01 ms, instead of a reading
    of the whole folder. That saving is real and it has been given up on purpose,
    because the same shortcut produced two answers the operator would have seen as
    broken pictures. It stopped at the first missing moment and never looked past
    it, so one black frame in the middle of a timelapse hid every moment after it.
    And it only ever walked its remembered figure upwards, with nothing to check it
    against, so a second and shorter experiment written into the same folder was
    still described with the first one's length, offering moments that run had never
    imaged.

    It is worth noting that the shortcut never helped on the *first* look at a
    store, which is what a folder of finished acquisitions is made of. Walking
    upwards a frame at a time from nothing took 61 ms for a ten-thousand-frame
    timelapse against 7.5 ms for one reading, so opening a large finished folder is
    now faster as well as correct. What has genuinely become dearer is following a
    store that is still growing, and there the cost is a few milliseconds each time
    a frame lands — frames land seconds apart.

    Reading the array's own description costs one small file read per store, paid the
    first time and remembered after that — see :func:`_read_array_description`. It
    takes the place of two reads of the same kind that were not remembered at all, one
    here and one in :func:`_channel_count`, so a folder of tens of thousands of stores
    is if anything slightly cheaper to describe than it was.

    The caller has already checked that time is this array's *first* axis, which is why
    the first number of everything read here can be taken as a moment.
    """
    described = _read_array_description(level)
    if not described:
        # Without the array's own description there is no way to know how its pieces
        # are named, nor how much of the timelapse one of them holds, and either guess
        # produces a number that is confidently wrong. This is the answer for a store
        # caught in the moment between being created and being described, too.
        return None
    if (described.get("pieces") or [])[:1] != [1]:
        # A file spanning several moments, or an array that will not say how much a
        # file spans. Either way the names on disk cannot be read as moments; the
        # docstring above sets out why declining is much safer than counting anyway.
        return None

    prefix, separator = described["prefix"], described["separator"]
    if separator == "/":
        # One folder per moment, and its name *is* the moment. Version 3's default
        # naming keeps those folders one step further in, under ``c``. Nothing is
        # capped on this path, and that is deliberate: this is the layout
        # `DATA_LAYOUT.md` asks for precisely because it keeps the folder down to one
        # entry per moment, which is small enough to read however long the run goes on.
        furthest = _furthest_moment_among_folders(level / prefix if prefix else level)
    else:
        # All in one folder, so every piece is its own file with its whole position in
        # the name. Many pieces share one moment, which is why the furthest is taken
        # rather than the names being counted.
        furthest = _furthest_moment_among_files(level, f"{prefix}{separator}" if prefix else "")

    if not isinstance(furthest, int):
        return furthest  # Nothing there yet, or more pieces than are worth reading.
    # Every entry in the folder has been looked at, so this really is the furthest
    # moment on disk and not merely the furthest one that happens to sit above a
    # gap. That is the whole difference between this and the version it replaced.
    return furthest + 1


def _furthest_moment_among_folders(folder: Path) -> int | None:
    """The highest-numbered folder in ``folder``, each of which is one moment."""
    furthest = None
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                if entry.name.isdigit():
                    moment = int(entry.name)
                    furthest = moment if furthest is None else max(furthest, moment)
    except OSError:
        return None
    return furthest


def _furthest_moment_among_files(folder: Path, prefix: str) -> int | None | _TooManyToCount:
    """The furthest moment named by the files in ``folder``, or nothing if there are too many.

    ``prefix`` is whatever every piece's name begins with before the numbers start —
    ``"c."`` for a version 3 store using its default naming, and nothing at all for the
    rest. Anything not beginning with it is not a piece of this image and is passed
    over: the array's own description sits in this same folder.
    """
    furthest = None
    seen = 0
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                name = entry.name
                if name.startswith("."):
                    # ``.zarray`` and its like describe the image rather than
                    # holding any of it, so they are not moments.
                    continue
                if prefix:
                    if not name.startswith(prefix):
                        continue
                    name = name[len(prefix) :]
                head, _, rest = name.partition(".")
                if rest and head.isdigit():
                    moment = int(head)
                    furthest = moment if furthest is None else max(furthest, moment)
                seen += 1
                if seen > _SCAN_LIMIT:
                    # Too many to look through. Better to let the store speak for
                    # itself than to keep the operator waiting on a count. This is
                    # the one verdict worth keeping for good: a folder this large
                    # is not going to shrink.
                    return _TOO_MANY
    except OSError:
        return None
    return furthest


# -- choosing which stores to show ----------------------------------------------
#
# What is under a path, and how an operator narrows it down when a transfer holds
# more tiles or more filters than they want on screen at once.


def _hex_to_rgb(value: object) -> tuple[float, float, float] | None:
    """Turn an ``omero`` colour like ``"00FF66"`` into fractions of red/green/blue."""
    if not isinstance(value, str):
        return None
    text = value.strip().lstrip("#")
    if len(text) != 6:
        return None
    try:
        return tuple(int(text[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
    except ValueError:
        return None


def select_tiles(names: list[str], tiles: list[int] | None) -> list[str]:
    """Keep only the named tiles, or everything when ``tiles`` is ``None``.

    A transfer often holds tiles that are not part of the view you want — an
    aborted one, or a tile imaged in only a single channel, which contributes
    nothing to an overlay and only clutters it.
    """
    if tiles is None:
        return names
    wanted = {f"Tile{n}" for n in tiles}
    return [
        name
        for name in names
        if any(part in wanted for part in without_format_suffix(name).split("_"))
    ]


def prefer_filter(names: list[str], wanted: str | None) -> list[str]:
    """Keep one store per tile and channel, preferring a filter by name.

    The same tile and channel are often acquired through more than one filter.
    Those are alternatives, not complements: overlaying both shows one field
    twice and doubles its apparent brightness, which reads as signal and is not.
    So collapse each tile+channel to a single store, choosing the filter asked
    for where it exists and keeping whatever is there where it does not — a
    channel acquired through only one filter must survive the choice.
    """
    if wanted is None:
        return names
    chosen: dict[tuple[str | None, str | None], str] = {}
    for name in names:
        key = (_tile_of(name), channel_of(name))
        current = chosen.get(key)
        if current is None or (
            wanted.lower() in _filter_of(name).lower()
            and wanted.lower() not in _filter_of(current).lower()
        ):
            chosen[key] = name
    return [name for name in names if name in set(chosen.values())]


def _tile_of(name: str) -> str | None:
    for part in without_format_suffix(name).split("_"):
        if part.startswith("Tile"):
            return part
    return None


def _filter_of(name: str) -> str:
    for part in without_format_suffix(name).split("_"):
        if part.startswith("Flt"):
            return part[3:]
    return ""


def discover(path: str | Path) -> tuple[Path, list[str]]:
    """Return ``(parent_directory, store_names)`` for whatever ``path`` names.

    A store yields its own parent and a single name, so it can be served the
    same way as a group; a folder of stores yields itself and every store in it,
    sorted so the layer order is stable between runs.
    """
    path = Path(path).resolve()
    if is_store(path):
        return path.parent, [path.name]
    names = sorted(child.name for child in path.iterdir() if child.is_dir() and is_store(child))
    return path, names
