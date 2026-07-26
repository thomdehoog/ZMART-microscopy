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
import re
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
    labels = []
    for name, label in zip(short, names, strict=True):
        if short.count(name) > 1:
            labels.append(_with_filter(name, label))
        else:
            labels.append(name)
    return labels


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
    try:
        attrs = json.loads((path / ".zattrs").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool(attrs.get("multiscales"))


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


def _read_attrs(store: Path) -> dict:
    try:
        return json.loads((store / ".zattrs").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def axis_names(store: Path) -> list[str]:
    """The axes this store declares, in order — for example ``[t, c, z, y, x]``.

    Reading them matters because a store need not have all five. A single-moment
    volume has no ``t``; a flat overview has no ``z``. The viewer offers a slider
    only for an axis that is really there, so this is what it asks.
    """
    axes = (_read_attrs(store).get("multiscales") or [{}])[0].get("axes") or []
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
    attrs = _read_attrs(store)
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
    datasets = (_read_attrs(store).get("multiscales") or [{}])[0].get("datasets") or []
    if not datasets:
        return described or None
    level = datasets[0].get("path")
    try:
        shape = json.loads((store / str(level) / ".zarray").read_text(encoding="utf-8"))["shape"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return described or None
    index = names.index("c")
    return int(shape[index]) if index < len(shape) else (described or None)


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
