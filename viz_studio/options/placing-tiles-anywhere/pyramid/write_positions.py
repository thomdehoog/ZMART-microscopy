"""Write the ten positions with the real writer, at offsets it would normally refuse.

The writer insists a position begins on a whole piece boundary, because today a
view answers for a piece of the picture by handing over a position's own file.
That is the rule this experiment is questioning, so it is switched off here — in
this scratch script only, nothing in the repository is touched — and the positions
are written where the stage really went.
"""

import shutil
import sys
from pathlib import Path

REPO = Path("/home/user/ZMART-microscopy")
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import zmart_storage.linked as linked

# The guard that would refuse a 179-voxel offset. A composing server does not hand
# a file over untouched, so nothing about the offset has to line up.
linked._refuse_a_placement_that_does_not_land_on_whole_pieces = (
    lambda *args, **kwargs: None)
# And its companion, which asks the same of the zoomed-out copies. The composing
# server works its own smaller copies out from the full-size positions, so there is
# no shrunk grid for a position to be out of step with.
linked._refuse_a_placement_that_does_not_line_up_when_shrunk = (
    lambda *args, **kwargs: None)
# The view's own list of pointers is left empty. A pointer says "this whole piece
# of the picture is that file", and overlapping positions placed 179 voxels apart
# cannot be described that way. The composing server reads the position images
# directly, so nothing here needs the list.
linked.GrowingLinkedView.add = lambda self, tile: None

import geometry as g

from zmart_storage.canvas import Channel
from zmart_storage.positions import start_a_run

HERE = Path(__file__).resolve().parent
RUN = HERE / "run"


def main() -> None:
    if RUN.exists():
        shutil.rmtree(RUN)
    RUN.mkdir(parents=True)

    with start_a_run(
        RUN,
        name="pyramid",
        room=(1, g.CANVAS_Y, g.CANVAS_X),
        tile_shape=(1, g.TILE, g.TILE),
        voxel_size_um=(1.0, g.VOXEL_UM, g.VOXEL_UM),
        channels=[Channel("probe", window=(0, 4095))],
        piece=g.CHUNK,
    ) as run:
        for number, (y, x) in enumerate(g.PLACES):
            run.write(g.a_tile(number)[None, :, :], at=(0, y, x))

    positions = sorted((RUN / "pyramid.ome.zarr" / "positions").glob("*.ome.zarr"))
    print(f"wrote {len(positions)} positions into {RUN}")
    for place, one in zip(g.PLACES, positions, strict=True):
        print(f"   {one.name} lands at y={place[0]:>4} x={place[1]:>4}")
    print(f"\ntile {g.TILE}, piece {g.CHUNK}, step {g.STEP}, overlap {g.OVERLAP}")
    print(f"canvas {g.CANVAS_Y} x {g.CANVAS_X}, offered at {g.LEVELS} sizes:")
    for level in range(g.LEVELS):
        height, width = g.level_shape(level)
        print(f"   level {level}: {height} x {width}")


if __name__ == "__main__":
    main()
