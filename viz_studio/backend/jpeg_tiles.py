"""Small JPEGs made from the OME-TIFFs a microscope exports, so ten thousand can be shown.

A microscope hands us one TIFF per plane and nothing else. That is fine for
one field and hopeless for a scan of ten thousand: the files are large, they
are not compressed in any way a picture can use, and no microscope we support
writes a pyramid — the ladder of ever-smaller copies a viewer normally climbs
to draw a whole slide at once. Asked to draw a scan like that directly, a
viewer must read every full-size plane to show a picture the size of a postage
stamp.

So we make the small copies ourselves, once, before anything is drawn. Each
field becomes one small JPEG. JPEG because it is *small*: a scan of ten
thousand fields is a few tens of megabytes rather than tens of gigabytes,
which is the difference between a picture that opens and one that does not.

These are display copies and nothing else. They are lossy on purpose, they are
never measured, and nothing is ever read back out of them — the real pixels
stay in the TIFFs the microscope wrote, untouched.

## The thing that is easy to get wrong

**A TIFF does not say where it was taken.** The exported OME-XML carries the
size of a pixel, and that is all: there is no stage position in it. So the
position has to be handed in alongside the files, from the run's own record of
where it sent the stage.

This is worth stating plainly because getting it wrong is invisible on one
field and ruinous on two. A single scan taken from the stage's zero lands in
exactly the right place whether or not anybody read a position, so the mistake
cannot be seen; put a detail scan beside a survey and it appears at the
survey's corner instead — which is how the viewers next door were once found
to be 898 micrometres out. Placement is therefore something a caller states,
never something this module guesses.

## The other thing that is easy to get wrong

**Every field has to be brightened the same way.** These pictures are stretched
to make them legible, and it is tempting to stretch each field over its own
range. That reads the scan backwards: an empty field has its faint background
pulled up until it fills the grey scale and comes out *pale*, while its
neighbour holding brilliant cells has everything but those cells squashed down
to black. An operator looking for signal would be sent to exactly the wrong
places. So one dark point and one bright point are settled from the whole scan
and shared by every field in it.

## What the microscope's files look like

The Leica driver writes one plane per file, with everything flat — every
channel, every depth and every moment its own file — and says which is which
in the name:

    {acquisition}_{hash}_{label}_T{tttttt}_C{cc}_Z{zzzzz}.ome.tiff

The name is read here rather than imported from the driver, deliberately: this
runs over a folder of files that may have been copied off the microscope
entirely, and reaching into a vendor's package to read a filename would tie
the picture to that vendor.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: The exported filename, as the driver writes it. One plane per file.
_PLANE_NAME = re.compile(
    r"^(?P<acquisition>[a-z0-9]+(?:-[a-z0-9]+)*)_(?P<hash>[0-9a-z]{6})"
    r"_(?P<label>[A-Za-z0-9_-]+)_T(?P<t>\d{6})_C(?P<c>\d{2})_Z(?P<z>\d{5})"
    r"\.ome\.tiffs?$"
)

#: How many pixels one field's small copy may have.
#:
#: Chosen by measuring rather than by argument, because the obvious worry turns
#: out not to be the real one. A scan of ten thousand fields draws at a steady
#: sixty frames a second whether each field is kept at 32 pixels or at 256, and
#: opens in about the same thirty milliseconds either way: what a viewer has to
#: work at is the *number* of fields on screen, not how many pixels each one
#: holds. So the choice comes down to what the folder weighs and how far the
#: operator can zoom before it goes soft.
#:
#: At 128 pixels a field, ten thousand fields are about a hundred megabytes and
#: take under a minute to make — and a field stays readable until it fills a
#: fair part of the screen. Half that size saves seventy megabytes and starts
#: looking blocky sooner; twice it costs four times the disk for detail that
#: only appears once one field fills a quarter of the screen, which is the
#: point at which the real TIFF is what you want anyway.
SMALL_ENOUGH = 128 * 128

#: How hard to compress. 85 keeps cell-sized detail while giving most of the
#: saving; colour is kept at full resolution because these pictures are
#: channels tinted and added together, and JPEG's usual colour shortcut smears
#: those across edges.
GOOD_ENOUGH = 85

#: How much to lift the dim end of the grey scale when showing these pictures.
#:
#: Fluorescence is mostly dark ground with sparse bright things in it, so a
#: picture that maps brightness straight onto grey spends almost the whole
#: scale on the few brightest pixels and shows a scan of real signal as a black
#: square. Lifting the dim end is the ordinary answer, and the same one a
#: photograph gets before it is shown on a screen: it is called gamma, and it
#: means the dim half of the range is given more of the grey scale than the
#: bright half.
#:
#: It does not change which field is brighter than which — only how much of
#: that difference you can see. Nothing is measured from these pictures, so
#: making them legible costs nothing and is the whole point of them.
EASY_TO_SEE = 0.45


@dataclass(frozen=True)
class Plane:
    """One exported file, and what its name says about it."""

    path: Path
    acquisition: str
    hash6: str
    label: str
    t: int
    c: int
    z: int


def read_planes(folder: Path | str) -> list[Plane]:
    """Find the exported planes in a folder, and read what their names say.

    Files that do not follow the convention are ignored rather than refused:
    a folder copied off a microscope usually has a log or a settings file in
    it, and choking on those would help nobody.
    """
    found = []
    for path in sorted(Path(folder).iterdir()):
        match = _PLANE_NAME.match(path.name)
        if not match:
            continue
        parts = match.groupdict()
        found.append(
            Plane(
                path=path,
                acquisition=parts["acquisition"],
                hash6=parts["hash"],
                label=parts["label"],
                t=int(parts["t"]),
                c=int(parts["c"]),
                z=int(parts["z"]),
            )
        )
    return found


def group_by_field(planes: list[Plane]) -> dict[str, list[Plane]]:
    """Gather the planes belonging to each field, in a settled order.

    A field is one place on the sample. Everything the microscope took there —
    every colour, every depth, every moment — belongs to it, and the small
    copy shows all of them together.
    """
    fields: dict[str, list[Plane]] = {}
    for plane in planes:
        fields.setdefault(plane.label, []).append(plane)
    for label in fields:
        fields[label].sort(key=lambda p: (p.t, p.z, p.c))
    return fields


def pixel_size_um(path: Path | str) -> float:
    """The size of one pixel in micrometres, from the file's own description.

    This is the one thing an exported TIFF does say about the world outside
    itself. How large the field is follows from it and the picture's shape;
    where the field *is* does not, and has to come from the run.
    """
    import tifffile

    with tifffile.TiffFile(path) as tif:
        described = tif.pages[0].description
    try:
        root = ET.fromstring(described)
    except ET.ParseError as exc:
        raise ValueError(f"{path}: the description is not readable OME-XML: {exc}") from exc
    pixels = root.find(".//{*}Pixels")
    if pixels is None:
        raise ValueError(f"{path}: the description has no Pixels element, so no pixel size")
    size = pixels.get("PhysicalSizeX")
    if size is None:
        raise ValueError(f"{path}: the description states no PhysicalSizeX")
    return float(size)


def _flatten(planes: list[Plane]) -> Any:
    """Turn one field's planes into a single greyscale picture of it.

    Brightest-wins across everything taken at that place. This is a display
    copy: the point is that a cell present in any channel or at any depth can
    be seen at a glance, not that the channels stay apart. Anything wanting
    the channels apart wants the TIFFs.

    The numbers are left in whatever the microscope wrote them as, rather than
    being widened to decimals. That is partly to save memory — a scan of ten
    thousand fields is held in small copies while the brightening is worked out
    — and partly because widening them would suggest a precision that taking a
    brightest-of does not have.
    """
    import numpy as np
    import tifffile

    stack = None
    for plane in planes:
        frame = np.asarray(tifffile.imread(plane.path))
        while frame.ndim > 2:
            frame = frame.max(axis=0)
        stack = frame if stack is None else np.maximum(stack, frame)
    if stack is None:
        raise ValueError("a field with no planes cannot be pictured")
    return stack


def _shrink_to(array: Any, budget_px: int) -> Any:
    """Keep every nth pixel until the picture is under the budget.

    Striding rather than averaging, so nothing is invented that the microscope
    did not see. A display copy may lose detail; it may not gain any.
    """
    import math

    height, width = array.shape[:2]
    step = max(1, math.ceil(math.sqrt(height * width / max(1, budget_px))))
    return array[::step, ::step]


def _one_brightening_for_the_whole_scan(pictures: list[Any]) -> tuple[float, float]:
    """Pick one dark point and one bright point for every field to share.

    This is the part that is easy to get wrong, and getting it wrong is what
    makes a scan look like a chessboard. If each field were brightened over its
    own range, an empty field would be stretched until its background filled
    the whole grey scale and came out *bright*, while its neighbour holding a
    few brilliant cells would have everything but those cells squashed down to
    black. The scan would read exactly backwards: empty pale, full dark.

    So the whole scan is brightened the same way. One dark point and one bright
    point are worked out from all the fields together and every field is then
    stretched between them, which is what makes two fields comparable at a
    glance — brighter really does mean more signal.

    They are percentiles rather than the darkest and brightest pixels found,
    because a single hot pixel or a single dead one would otherwise decide the
    brightening for the entire scan and flatten everything else into the middle.

    Only a sample of each field's pixels is looked at. Reading every pixel of
    ten thousand fields to settle two numbers would cost far more than the two
    numbers are worth, and a sample settles them to well within a grey level.
    """
    import numpy as np

    if not pictures:
        return 0.0, 1.0

    #: At most this many pixels are gathered from the whole scan to settle the
    #: two points. A few million is far more than enough for a percentile and
    #: still only a handful of megabytes.
    enough_to_judge_by = 2_000_000
    from_each = max(1, enough_to_judge_by // max(1, len(pictures)))

    sample = []
    for picture in pictures:
        flat = np.asarray(picture).reshape(-1)
        step = max(1, flat.size // from_each)
        sample.append(flat[::step])
    pooled = np.concatenate(sample).astype(np.float32)

    low = float(np.percentile(pooled, 0.5))
    high = float(np.percentile(pooled, 99.9))
    if not high > low:
        high = low + 1.0
    return low, high


def _stretch(array: Any, low: float, high: float, gamma: float = EASY_TO_SEE) -> Any:
    """Brighten one field between the scan's shared dark and bright points.

    Two steps, and they do different jobs. The first spreads the scan's own
    range of brightnesses across the grey scale, and uses the same two points
    for every field so that two fields can be compared. The second lifts the
    dim end, so that a picture which is mostly dark ground with a few bright
    things in it — which is what fluorescence usually looks like — can be seen
    at all. See ``EASY_TO_SEE``.
    """
    import numpy as np

    values = np.asarray(array, dtype=np.float32)
    span = high - low if high > low else 1.0
    spread = np.clip((values - low) / span, 0.0, 1.0)
    return np.power(spread, gamma) * 255.0


def _how_bright(stretched: Any) -> int:
    """How bright this field is overall, 0 to 255.

    A whole scan zoomed out draws every field a few pixels wide, and decoding a
    picture to paint seven pixels is work thrown away — at ten thousand fields
    it is the difference between a picture that opens at once and one that
    grinds. So each field also carries one number standing for it, and a field
    too small on screen to show anything is drawn as that one colour instead of
    being decoded at all.

    The number is the field's average, taken *after* the scan's shared
    brightening, for one reason above all: that is what the field will look
    like when its real picture does arrive. Shrinking a picture down to a few
    pixels averages it, so an average is the honest answer to "what colour is
    this field from far away". Anything else and the scan visibly changes as
    the pictures fill in, which an operator reads as a fault even though every
    field is in its right place.
    """
    import numpy as np

    return int(round(float(np.asarray(stretched, dtype=np.float32).mean())))


def _as_jpeg(stretched: Any, quality: int) -> bytes:
    """Encode one field's already-brightened picture."""
    import io

    import numpy as np
    from PIL import Image

    eight_bit = np.asarray(stretched, dtype=np.float32).round().astype(np.uint8)
    buffer = io.BytesIO()
    Image.fromarray(eight_bit, mode="L").save(
        buffer, format="JPEG", quality=quality, subsampling=0
    )
    return buffer.getvalue()


def make_small_pictures(
    folder: Path | str,
    where_each_field_is: dict[str, tuple[float, float]],
    into: Path | str,
    *,
    budget_px: int = SMALL_ENOUGH,
    quality: int = GOOD_ENOUGH,
) -> dict:
    """Make one small JPEG per field, and a note of where each one belongs.

    ``where_each_field_is`` maps a field's label — the one in the file names —
    to the middle of that field in micrometres, as the run recorded sending the
    stage there. It is required, because the files do not say (see the note at
    the top of this file). A field whose place is not given is left out and
    named in the result, rather than being drawn somewhere invented.

    Returns the note that is also written to ``tiles.json`` beside the
    pictures: every field, the file holding its picture, the piece of sample
    that picture covers in micrometres, and one colour standing for the field
    when it is too small on screen to be worth drawing properly. That is
    everything a viewer needs to draw the scan, and it is deliberately all it
    gets — a viewer that had to open a TIFF to find out where to put something
    would be back to reading ten thousand large files.

    The work happens in two passes. The first reads each field and shrinks it;
    the second brightens and saves them. They are separate because the
    brightening has to be the same for every field, and that cannot be settled
    until every field has been seen. Only the shrunken copies are held between
    the passes, so the memory this needs follows ``budget_px`` rather than the
    size of the scan's real pixels — a few tens of megabytes for ten thousand
    fields, instead of the tens of gigabytes the TIFFs weigh.
    """
    into = Path(into)
    into.mkdir(parents=True, exist_ok=True)
    fields = group_by_field(read_planes(folder))

    # First pass: read every field once, and keep only a small copy of each.
    placed_nowhere = []
    small_copies = []
    for label, planes in sorted(fields.items()):
        if label not in where_each_field_is:
            placed_nowhere.append(label)
            continue
        whole = _flatten(planes)
        full_height, full_width = whole.shape[:2]
        um_per_pixel = pixel_size_um(planes[0].path)
        small_copies.append(
            {
                "label": label,
                "picture": _shrink_to(whole, budget_px),
                "width_um": full_width * um_per_pixel,
                "height_um": full_height * um_per_pixel,
            }
        )

    # Now that every field has been seen, one brightening can be settled for
    # all of them — which is what makes two fields comparable at a glance.
    low, high = _one_brightening_for_the_whole_scan([c["picture"] for c in small_copies])

    # Second pass: brighten, save, and note where each picture belongs.
    tiles = []
    for copy in small_copies:
        stretched = _stretch(copy["picture"], low, high)
        name = f"{copy['label']}.jpg"
        (into / name).write_bytes(_as_jpeg(stretched, quality))
        centre_x, centre_y = where_each_field_is[copy["label"]]
        tiles.append(
            {
                "label": copy["label"],
                "src": name,
                "x0": centre_x - copy["width_um"] / 2.0,
                "y0": centre_y - copy["height_um"] / 2.0,
                "w": copy["width_um"],
                "h": copy["height_um"],
                "grey": _how_bright(stretched),
            }
        )

    note = {
        "units": "um",
        "grey_is": "one colour standing for each field, for drawing it when it is too "
                   "small on screen to be worth decoding. It is the field's average "
                   "after brightening, which is what the field looks like from far "
                   "away, so nothing changes as the real pictures arrive",
        "brightened_between": [low, high],
        "brightening_is": "the same for every field in the scan, so a brighter field "
                          "really does hold more signal than a dimmer one",
        "dim_end_lifted_by": EASY_TO_SEE,
        "made_for": "display only \u2014 the real pixels stay in the TIFFs",
        "tiles": tiles,
        "fields_with_no_stated_place": placed_nowhere,
    }
    (into / "tiles.json").write_text(json.dumps(note, indent=2), encoding="utf-8")
    return note
