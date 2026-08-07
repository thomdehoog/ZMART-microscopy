"""Check the photograph itself against the canvas we meant to make.

The picture is the demonstration, but a person reading a report cannot measure a
picture. So the photograph is compared with the ground-truth canvas: the imaged
ground is found in the photograph, the canvas is shrunk to the same size, and the
two are compared where the picture is flat — away from the edges of tiles and of
the discs, where a single screen pixel covers voxels of two different brightnesses
and no exact answer exists.

If the positions had been drawn on the grid of pieces instead of where the stage
put them, every tile after the first would be out by up to 51 voxels and this
would report a large disagreement rather than a small one.
"""

import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import geometry as g

HERE = Path(__file__).resolve().parent
SHOT = HERE / "frames" / "composed-anywhere.png"
WINDOW_HIGH = 4095.0     # the brightness window the page asked for


def main() -> None:
    photograph = np.asarray(Image.open(SHOT).convert("L")).astype(float)

    # The imaged ground in the photograph. Everything the run imaged is at least
    # a little brighter than the page behind it, and the ground nobody imaged is
    # stored as nought, so the lit rectangle is exactly the 614 voxels the nine
    # positions cover.
    lit = photograph > 20
    rows = np.flatnonzero(lit.any(axis=1))
    columns = np.flatnonzero(lit.any(axis=0))
    top, bottom = rows[0], rows[-1] + 1
    left, right = columns[0], columns[-1] + 1
    on_screen = photograph[top:bottom, left:right]
    print(f"the imaged ground fills {on_screen.shape[1]} by "
          f"{on_screen.shape[0]} screen pixels")
    print(f"which stands for {g.SPAN} by {g.SPAN} voxels, so one voxel is "
          f"{on_screen.shape[1] / g.SPAN:.3f} screen pixels")

    # The canvas we meant to make, shown the way the page was told to show it,
    # and shrunk to the size it appears on screen.
    meant = g.truth()[:g.SPAN, :g.SPAN].astype(float)
    meant = np.clip(meant / WINDOW_HIGH, 0, 1) * 255
    shrunk = np.asarray(
        Image.fromarray(meant.astype("uint8")).resize(
            (on_screen.shape[1], on_screen.shape[0]), Image.BILINEAR)
    ).astype(float)

    # Only where the picture is flat. A screen pixel sitting on the edge of a
    # tile or of a disc covers voxels of two brightnesses at once, and what a
    # drawing engine puts there is a matter of how it filters rather than of
    # whether the tile is in the right place.
    from scipy.ndimage import maximum_filter, minimum_filter  # type: ignore
    flat = (maximum_filter(shrunk, 5) - minimum_filter(shrunk, 5)) < 2

    difference = np.abs(on_screen - shrunk)[flat]
    print(f"\nscreen pixels compared             : {int(flat.sum())}")
    print(f"largest disagreement, in grey levels of 255 : "
          f"{difference.max():.1f}")
    print(f"median disagreement                : {np.median(difference):.1f}")
    print(f"pixels differing by more than 4    : "
          f"{int((difference > 4).sum())}")

    # And the same comparison against the wrong answer, so the number above can
    # be read: the picture as it would look if every position had been pushed
    # onto the nearest whole piece, which is what the writer insists on today.
    pushed = np.zeros((g.CANVAS, g.CANVAS), "uint16")
    for number, (y, x) in enumerate(g.PLACES):
        ny = round(y / g.CHUNK) * g.CHUNK
        nx = round(x / g.CHUNK) * g.CHUNK
        pushed[ny:ny + g.TILE, nx:nx + g.TILE] = g.a_tile(number)
    pushed = np.clip(pushed[:g.SPAN, :g.SPAN].astype(float) / WINDOW_HIGH, 0, 1) * 255
    pushed = np.asarray(
        Image.fromarray(pushed.astype("uint8")).resize(
            (on_screen.shape[1], on_screen.shape[0]), Image.BILINEAR)
    ).astype(float)
    wrong = np.abs(on_screen - pushed)[flat]
    print(f"\nagainst the same tiles pushed onto whole pieces instead:")
    print(f"median disagreement                : {np.median(wrong):.1f}")
    print(f"pixels differing by more than 4    : {int((wrong > 4).sum())}")


if __name__ == "__main__":
    main()
