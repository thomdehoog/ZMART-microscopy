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
    stem = _stem(store_name)
    parts = [p for p in stem.split("_") if p.startswith("Tile") or p.startswith("Ch")]
    return "_".join(parts) if parts else stem


def _with_filter(short: str, store_name: str) -> str:
    """Add the filter block, abbreviated, to a label that would otherwise clash."""
    for part in _stem(store_name).split("_"):
        if part.startswith("Flt"):
            filter_name = part[3:] or "None"
            return f"{short}_{filter_name[:12]}"
    return short


def _stem(store_name: str) -> str:
    return store_name.removesuffix(".ome.zarr").removesuffix(".zarr")


def channel_color(name: str) -> tuple[float, float, float] | None:
    """The colour to draw a store in, or ``None`` to leave it greyscale.

    Greyscale is the honest answer for a single-channel view: colouring one
    layer green says "this is the 488 channel" when there is nothing to
    distinguish it from.
    """
    channel = channel_of(name)
    return _CHANNEL_COLORS.get(channel) if channel else None


def is_store(path: Path) -> bool:
    """True if ``path`` is an OME-Zarr image store (has multiscales metadata)."""
    return bool(_read_attrs_at(path).get("multiscales"))


# --- what a smart-microscopy run leaves on disk -----------------------------
#
# A run writes one OME-Zarr per acquisition, named by the driver as
# "{acquisition_type}_{position_label}" -- for example ``overview_pos001`` and
# ``targetscan_cell042``. So the folder for one experiment holds many stores that
# fall into a few natural families:
#
#   overview_pos001.ome.zarr  \
#   overview_pos002.ome.zarr   >  the "overview" acquisition type, three positions
#   overview_pos003.ome.zarr  /
#   targetscan_cell042.ome.zarr  -  the "targetscan" type, one position
#
# Positions belong together: each carries its own place on the stage, so shown
# together they make one specimen rather than three unrelated pictures. That is
# why the viewer groups by acquisition type and treats the positions inside a
# group as pieces of the same image.
#
# The type is read from the name rather than from a list written here on purpose.
# An experiment may invent an acquisition type we have never heard of, and it
# should still appear in the viewer, correctly grouped, with no code change.


def split_name(store_name: str) -> tuple[str, str]:
    """Separate a store's name into its acquisition type and its position.

    The driver joins the two with an underscore, so the text before the first
    underscore is the acquisition type and the rest names the position. A name
    with no underscore has no position to speak of, and is treated as a type on
    its own — which keeps hand-made and older stores working instead of hiding
    them.
    """
    stem = _stem(store_name)
    kind, _, position = stem.partition("_")
    return (kind, position) if position else (stem, "")


def group_by_type(names: list[str]) -> list[tuple[str, list[str]]]:
    """Gather store names into ``(acquisition_type, store_names)`` families.

    The order is stable: the types come out sorted, and so do the positions
    within each, so the viewer's panel does not reshuffle itself between runs.
    """
    families: dict[str, list[str]] = {}
    for name in sorted(names):
        kind, _ = split_name(name)
        families.setdefault(kind, []).append(name)
    return sorted(families.items())


# A store's description is read many times over while the panel is being built --
# once for the axes, again for the channels, again for the frame count, and so on.
# It is a small file and it rarely changes, so it is remembered against its own
# modification time: unchanged means the remembered copy is used, and a store that
# has been rewritten is read afresh. At four hundred stores this is the difference
# between three thousand file reads per refresh and a few hundred quick glances.
_attrs_cache: dict[str, tuple[int, dict]] = {}


def _read_attrs_at(path: Path) -> dict:
    """The OME-Zarr description at ``path``, or an empty one if unreadable."""
    key = str(path)
    described = path / ".zattrs"
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
    _attrs_cache[key] = (stamp, attrs)
    return attrs


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

    out = []
    for index in range(count):
        entry = described[index] if index < len(described) else {}
        entry = entry if isinstance(entry, dict) else {}
        label = entry.get("label") or entry.get("name") or f"channel {index + 1}"
        out.append({"name": str(label), "color": _hex_to_rgb(entry.get("color"))})
    return out


def _channel_count(store: Path, names: list[str], described: int) -> int | None:
    """How many channels the store's own array says it has.

    The array is the authority, not the ``omero`` block: a description listing
    three channels for a two-channel array would otherwise produce a layer with
    nothing behind it.
    """
    if "c" not in names:
        return None
    datasets = (_read_attrs_at(store).get("multiscales") or [{}])[0].get("datasets") or []
    if not datasets:
        return described or None
    level = datasets[0].get("path")
    try:
        shape = json.loads((store / str(level) / ".zarray").read_text(encoding="utf-8"))["shape"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return described or None
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


# Counting frames means looking in the folder that holds the image's pieces, and
# on a large acquisition that folder is enormous. This is the most that will be
# looked at before giving up: past it the answer is not worth the time it costs,
# and the viewer falls back to the length the file claims. A store written the way
# `DATA_LAYOUT.md` asks never reaches this, because its pieces are filed in
# folders and the answer takes one glance.
_SCAN_LIMIT = 20_000

# Remembering the answer alongside the folder's own modification time, so asking
# again costs one cheap look unless something has actually been written since.
_frame_counts: dict[str, tuple[int, int | None]] = {}

# The highest frame number seen in each store that files its pieces in folders, so
# a growing timelapse can be followed by asking only about the frames that are new.
_frame_highest: dict[str, int] = {}


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
    for remembered in (_attrs_cache, _frame_counts, _frame_highest):
        for key in [key for key in remembered if key == under or key.startswith(inside)]:
            del remembered[key]


def written_timepoints(store: Path) -> int | None:
    """How many frames of a timelapse have actually been written so far.

    A store is given its full length in time when it is created, long before the
    run has produced that many frames — that is what keeps an unpredictable
    timelapse cheap. But the viewer must not offer a slider running out to frames
    that do not exist yet: the engine remembers "there is nothing here" for a frame
    it looked at too early and will not look again, so that frame would stay blank
    for the rest of the session even once it had been imaged.

    Returns ``None`` when the store has no time axis, or when the answer cannot be
    had cheaply — in which case the viewer falls back to what the file claims.

    **How the image is filed decides whether this is instant or ruinous.** A piece
    of the image is stored under a name built from its position. Those names can be
    laid out two ways, and OME-Zarr allows both:

    - **Filed in folders** (the pieces of one frame together, then one channel,
      then one plane). Counting frames is then a single glance at one small folder,
      however large the image. This is what large acquisitions should use.
    - **All in one folder**, every piece a separate file with its position in the
      name. A 400 GB image has some three million of them in that one folder,
      which is slow to look through and hard on the file system besides. Here the
      look is capped and, past the cap, abandoned rather than allowed to stall the
      viewer.
    """
    names = axis_names(store)
    if "t" not in names or names.index("t") != 0:
        return None
    datasets = (_read_attrs_at(store).get("multiscales") or [{}])[0].get("datasets") or []
    if not datasets:
        return None
    level = store / str(datasets[0].get("path"))

    try:
        stamp = level.stat().st_mtime_ns
    except OSError:
        return None
    remembered = _frame_counts.get(str(level))
    if remembered is not None and (remembered[0] == stamp or remembered[1] is None):
        # A folder holding too many pieces to look through will not hold fewer
        # later, so that verdict stands whatever is written next. Without this the
        # look would be repeated on every refresh -- and a piece is written every
        # few seconds during a run, so the modification time is always moving.
        return remembered[1]

    answer = _count_frames(level)
    _frame_counts[str(level)] = (stamp, answer)
    return answer


def _count_frames(level: Path) -> int | None:
    """How many frames of a timelapse have been written so far.

    Counting means looking at the names of the pieces on disk, which is cheap when
    each frame has its own folder and very much not cheap when a store keeps
    millions of pieces side by side in one directory. So the look is given a
    limit, and ``None`` means "there are more pieces here than it is sensible to
    count through".

    A caller that gets ``None`` should simply not offer a limit on the time
    slider: the operator can then reach every frame the store declares, and a
    frame not yet written shows as empty rather than as missing. That is a better
    outcome than making them wait while the viewer counts files.
    """
    nested = _reads_from_folders(level)
    # When each frame has its own folder, a growing timelapse can be followed
    # without looking at the whole thing again. The highest frame seen last time is
    # remembered, and the only question asked now is whether the next one along has
    # appeared — one cheap look per new frame, rather than a fresh reading of every
    # frame ever written. On a run of four hundred acquisitions that is the
    # difference between two and a half seconds of counting per refresh and almost
    # none, and it is a refresh that happens every time a frame lands.
    if nested:
        known = _frame_highest.get(str(level), 0)
        highest = known - 1
        while (level / str(highest + 1)).exists():
            highest += 1
            if highest - known > _SCAN_LIMIT:
                # Far more frames than expected have appeared at once, which means
                # the remembered figure is not to be trusted. Fall back to reading
                # the folder properly below.
                highest = -1
                break
        if highest >= 0:
            _frame_highest[str(level)] = highest + 1
            return highest + 1
        _frame_highest.pop(str(level), None)

    highest = -1
    seen = 0
    try:
        with os.scandir(level) as entries:
            for entry in entries:
                name = entry.name
                if name.startswith("."):
                    continue
                if nested:
                    # The entry *is* the frame number.
                    if name.isdigit():
                        highest = max(highest, int(name))
                    continue
                head, _, rest = name.partition(".")
                if rest and head.isdigit():
                    highest = max(highest, int(head))
                seen += 1
                if seen > _SCAN_LIMIT:
                    # Too many to look through. Better to let the store speak for
                    # itself than to keep the operator waiting on a count.
                    return None
    except OSError:
        return None
    if highest < 0:
        return None
    if nested:
        _frame_highest[str(level)] = highest + 1
    return highest + 1


def _reads_from_folders(level: Path) -> bool:
    """Whether this image files its pieces in folders rather than one flat heap."""
    try:
        described = json.loads((level / ".zarray").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return described.get("dimension_separator") == "/"


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
    return [name for name in names if any(part in wanted for part in _stem(name).split("_"))]


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
    for part in _stem(name).split("_"):
        if part.startswith("Tile"):
            return part
    return None


def _filter_of(name: str) -> str:
    for part in _stem(name).split("_"):
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
