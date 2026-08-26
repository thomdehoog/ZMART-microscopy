"""Does the list of which piece is which need to exist at all?

A view keeps a list saying, for every piece of the picture, which position's file
holds those bytes. The list has one entry per position, so a ten-thousand-position
run carries about 1.28 MB of it, fetched whenever somebody opens the run.

But a survey is a regular grid, and on a regular grid that answer is arithmetic:
a tile is a whole number of pieces across, neighbours overlap by a whole number of
pieces, so the piece at a given place belongs to the tile at that place divided by
the step. Nothing has to be looked up.

This checks that claim the only way worth checking it — by writing a real
overlapping run, asking the viewer's own reader where every single piece of the
picture really is, and asking the arithmetic the same question. If the two agree
everywhere, the list is not describing anything the geometry does not already say,
and the run could carry five numbers instead of a line for every position.

Run it directly; it writes into a temporary folder and cleans up after itself::

    python zmart_storage/tests/check_the_map_is_derivable.py
"""

_ORIGINAL_DOCSTRING = """Can the pointer map be derived from geometry alone?

Builds a real overlapping run, then for every chunk of the view asks two things:
what the system actually resolves it to, and what pure arithmetic says it should
be. If they agree everywhere, the enumerated map carries nothing the geometry
does not already imply.
"""
import sys, shutil
from pathlib import Path
import numpy as np
sys.path.insert(0, "/home/user/ZMART-microscopy")
sys.path.insert(0, "/home/user/ZMART-microscopy/zmart-viewer/backend")
from zmart_storage.positions import start_a_run
from zmart_storage.canvas import Channel
import linking

S = Path(__file__).resolve().parent
ROOT = S / "derive"
if ROOT.exists(): shutil.rmtree(ROOT)

TILE, PIECE, ACROSS = 1024, 128, 3
PER_TILE = TILE // PIECE                 # 8 chunks across a tile
SHARED   = 1                             # one chunk of overlap
STEP     = (PER_TILE - SHARED) * PIECE   # 896 voxels = 7 chunks
WIDE     = (ACROSS - 1) * STEP + TILE

with start_a_run(ROOT, name="overview", room=(1, WIDE, WIDE),
                 tile_shape=(1, TILE, TILE), voxel_size_um=(2.0, .35, .35),
                 channels=[Channel("488", window=(0, 4000))],
                 piece=PIECE, levels=1, ome_zarr_version="0.5") as run:
    for i in range(ACROSS * ACROSS):
        r, c = divmod(i, ACROSS)
        run.write(np.full((1, TILE, TILE), 1000 + i, "uint16"),
                  at=(0, r * STEP, c * STEP))
    view = run.finish().path

def derived(index: int) -> tuple[int, int]:
    """Which tile answers this chunk, and which chunk of it — arithmetic only."""
    tile = min(index // (PER_TILE - SHARED), ACROSS - 1)
    return tile, index - tile * (PER_TILE - SHARED)

chunks = (ACROSS - 1) * (PER_TILE - SHARED) + PER_TILE
print(f"tile {TILE} voxels = {PER_TILE} chunks, {SHARED} shared, step {STEP}")
print(f"{ACROSS}x{ACROSS} positions -> canvas {WIDE} voxels = {chunks} chunks\n")

agree = disagree = missing = 0
examples = []
for cy in range(chunks):
    for cx in range(chunks):
        got = linking.the_bytes_behind(view, f"0/c/0/0/0/{cy}/{cx}")
        if got is None:
            missing += 1
            continue
        # what the system resolved to
        name = next((p for p in Path(got.path).parts if "_pos" in p), "")
        actual_tile = int(name.split("_pos")[1][:5]) if "_pos" in name else -1
        ty, wy = derived(cy)
        tx, wx = derived(cx)
        want_tile = ty * ACROSS + tx
        if actual_tile == want_tile:
            agree += 1
        else:
            disagree += 1
            if len(examples) < 5:
                examples.append((cy, cx, actual_tile, want_tile))

print(f"chunks checked      : {agree + disagree + missing}")
print(f"arithmetic agreed   : {agree}")
print(f"arithmetic disagreed: {disagree}")
print(f"nothing behind it   : {missing}")
for cy, cx, a, w in examples:
    print(f"   chunk ({cy},{cx}): system says tile {a}, arithmetic says {w}")
shutil.rmtree(ROOT)
