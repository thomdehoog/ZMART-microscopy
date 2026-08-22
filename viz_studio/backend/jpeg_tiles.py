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

#: How many pixels one field's small copy may have. A field shown as part of a
#: whole slide is a few dozen pixels across, so this is already generous — it
#: is chosen so a field still reads when the operator zooms into it a little,
#: not so it stands up to inspection. Looking closely is what the real TIFF is
#: for.
SMALL_ENOUGH = 64 * 64

#: How hard to compress. 85 keeps cell-sized detail while giving most of the
#: saving; colour is kept at full resolution because these pictures are
#: channels tinted and added together, and JPEG's usual colour shortcut smears
#: those across edges.
GOOD_ENOUGH = 85


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
    """
    import numpy as np
    import tifffile

    stack = None
    for plane in planes:
        frame = np.asarray(tifffile.imread(plane.path), dtype=np.float32)
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


def _as_jpeg(array: Any, quality: int) -> bytes:
    """Encode one field's picture, stretched over its own range so it reads."""
    import io

    import numpy as np
    from PIL import Image

    values = np.asarray(array, dtype=np.float32)
    low, high = float(values.min()), float(values.max())
    span = high - low if high > low else 1.0
    eight_bit = ((values - low) / span * 255.0).astype(np.uint8)
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
    to the middle of that field in micrometres, as the run recorded sending
    the stage there. It is required, because the files do not say (see the
    note at the top of this file). A field whose place is not given is left
    out and named in the result, rather than being drawn somewhere invented.

    Returns the note that is also written to ``tiles.json`` beside the
    pictures: every field, the file holding its picture, and the piece of
    sample that picture covers in micrometres. That is everything a viewer
    needs to draw the scan, and it is deliberately all it gets — a viewer that
    had to open a TIFF to find out where to put something would be back to
    reading ten thousand large files.
    """
    into = Path(into)
    into.mkdir(parents=True, exist_ok=True)
    fields = group_by_field(read_planes(folder))

    tiles = []
    placed_nowhere = []
    for label, planes in sorted(fields.items()):
        if label not in where_each_field_is:
            placed_nowhere.append(label)
            continue
        picture = _shrink_to(_flatten(planes), budget_px)
        name = f"{label}.jpg"
        (into / name).write_bytes(_as_jpeg(picture, quality))

        um_per_pixel = pixel_size_um(planes[0].path)
        full_height, full_width = _flatten(planes[:1]).shape[:2]
        width_um = full_width * um_per_pixel
        height_um = full_height * um_per_pixel
        centre_x, centre_y = where_each_field_is[label]
        tiles.append(
            {
                "label": label,
                "src": name,
                "x0": centre_x - width_um / 2.0,
                "y0": centre_y - height_um / 2.0,
                "w": width_um,
                "h": height_um,
            }
        )

    note = {
        "units": "um",
        "made_for": "display only — the real pixels stay in the TIFFs",
        "tiles": tiles,
        "fields_with_no_stated_place": placed_nowhere,
    }
    (into / "tiles.json").write_text(json.dumps(note, indent=2), encoding="utf-8")
    return note
