"""Make a mock scan for the operator page to draw, without a microscope.

There is no microscope here, so the pixels are invented. Everything else is the
real thing: the same filenames the Leica driver writes, one plane per file with
the colours and depths flat, the same OME description carrying the size of a
pixel and saying nothing at all about where the field was taken. Only the source
of the pixels is pretend.

That is the point of it. If the operator page draws this correctly, then wiring
a microscope in means replacing where the pixels come from and changing nothing
else — and the awkward parts get found now rather than on a machine with an
operator waiting.

## Where the positions come from, and why they are handed in

**A microscope's files do not say where they were taken.** The description
carries the size of a pixel and that is all. So the positions have to come from
the run's own record of where it sent the stage, and that is exactly what
happens here: the page is asked for its plan, and the plan is handed to the
helper that makes the pictures.

Getting this wrong is invisible on one scan and ruinous on two — a scan taken
from the stage's zero lands correctly whether or not anybody read a position,
and the second one then appears at the first one's corner. So the rehearsal
rehearses the pairing too, rather than quietly working it out.

## Using it

    python mock_picture.py plan.json --into public/mock-scan

where `plan.json` is what the page's own canvas answers with — see
`window.__theStageCanvas.plan()` — a list of `{x, y, frameUm}` in micrometres in
the carrier's frame. Point the page at the result with `?picture=/mock-scan`.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def write_a_mock_export(into: Path, plan: list[dict], um_per_pixel: float, seed: int) -> dict:
    """Write one plane per position, the way the driver writes them.

    The picture in each is invented, but it is invented to look enough like a
    field of cells that a JPEG of it compresses about as badly as a real one
    does — a flat grey field would compress to nothing and make every size
    measurement here a lie. How much is in each field varies across the plate,
    so that a scan drawn from these has somewhere to look rather than being
    uniformly interesting.
    """
    import numpy as np
    import tifffile

    into.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    places: dict[str, tuple[float, float]] = {}

    xs = [p["x"] for p in plan] or [0.0]
    ys = [p["y"] for p in plan] or [0.0]
    across = max(1.0, max(xs) - min(xs))
    down = max(1.0, max(ys) - min(ys))

    for number, position in enumerate(plan, start=1):
        label = f"P{number:04d}"
        places[label] = (float(position["x"]), float(position["y"]))
        pixels = max(16, int(round(float(position["frameUm"]) / um_per_pixel)))

        # More to find towards one corner of the plate than the other, so the
        # scan has shape. A sample that is the same everywhere teaches nobody
        # anything about a picture meant for deciding where to look.
        away = (
            ((position["x"] - min(xs)) / across) ** 2 + ((position["y"] - min(ys)) / down) ** 2
        ) ** 0.5
        how_much = max(0.05, 1.0 - away / 1.5)

        described = (
            '<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2016-06">'
            f'<Image><Pixels DimensionOrder="XYCZT" Type="uint16" SizeX="{pixels}" '
            f'SizeY="{pixels}" SizeC="1" SizeZ="1" SizeT="1" '
            f'PhysicalSizeX="{um_per_pixel}" PhysicalSizeY="{um_per_pixel}"/></Image></OME>'
        )
        tifffile.imwrite(
            into / f"overview_mock01_{label}_T000000_C00_Z00000.ome.tiff",
            _a_field_of_cells(rng, pixels, how_much),
            description=described,
        )
    return places


def _a_field_of_cells(rng, pixels: int, how_much: float):
    """Bright blobs on a dim ground, more of them where there is more to find."""
    import numpy as np

    ground = (rng.random((pixels, pixels)) * 400 + 200).astype(np.float32)
    rows, columns = np.mgrid[0:pixels, 0:pixels]
    for _ in range(max(1, int(round(how_much * max(4, pixels // 12))))):
        centre_row = rng.integers(0, pixels)
        centre_column = rng.integers(0, pixels)
        radius = rng.integers(max(2, pixels // 40), max(3, pixels // 12))
        blob = np.exp(
            -(((rows - centre_row) ** 2 + (columns - centre_column) ** 2) / (2.0 * radius**2))
        )
        ground += blob * rng.uniform(6000, 22000)
    return np.clip(ground, 0, 65535).astype(np.uint16)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path,
                        help="the page's own plan, as JSON: [{x, y, frameUm}, …] in µm")
    parser.add_argument("--into", type=Path, required=True,
                        help="where the small pictures should be written")
    parser.add_argument("--um-per-pixel", type=float, default=1.3,
                        help="the size of a pixel, as the overview objective sees it")
    parser.add_argument("--how-many", type=int, default=0,
                        help="only the first this many positions, for a quicker rehearsal")
    parser.add_argument("--seed", type=int, default=0)
    asked = parser.parse_args()

    from viz_studio.backend.jpeg_tiles import make_small_pictures

    plan = json.loads(asked.plan.read_text(encoding="utf-8"))
    if asked.how_many:
        plan = plan[: asked.how_many]

    exported = asked.into.parent / f"{asked.into.name}-exported"
    shutil.rmtree(exported, ignore_errors=True)
    shutil.rmtree(asked.into, ignore_errors=True)

    print(f"writing {len(plan)} fields as the driver would…")
    places = write_a_mock_export(exported, plan, asked.um_per_pixel, asked.seed)

    print("making the small pictures…")
    note = make_small_pictures(exported, places, asked.into)

    weight = sum(p.stat().st_size for p in asked.into.glob("*.jpg"))
    print(f"{len(note['tiles'])} fields · {weight / 1e6:.1f} MB · {asked.into}")
    if note["fields_with_no_stated_place"]:
        print(f"  no place given for: {note['fields_with_no_stated_place']}")
    shutil.rmtree(exported, ignore_errors=True)


if __name__ == "__main__":
    main()
