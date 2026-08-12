"""Prove the built picture is the picture, before anything reaches a screen.

A window full of plausible-looking specimen is the least trustworthy evidence there
is. Four conclusions in this repo were drawn from photographs of the viewer and all
four turned out to be wrong, which is why this compares numbers instead:

1. **The arrangement.** Where each tile lands, at every resolution, against the
   micrometres its own description records.
2. **The pieces.** Every piece of a band of the picture, built by the composer,
   against the same ground laid out independently straight from the tiles.
3. **The bytes.** What the server would actually send, decoded back through zarr
   the way the browser's engine decodes it, against the numbers that went in. This
   is the one that catches a description promising one encoding over bytes in
   another — a fault that produces no error anywhere and a black window.
4. **The cost**, so the saving from reading slabs is a measurement rather than a
   claim.

Run it with the transfer to check::

    python check.py "D:/OMEzarr data/Thy1-25x-3x2-1ch-OMEZARR/Thy1_Mag25x_Ch561.ome.zarr"
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import numpy as np
import zarr
from zarr.core.buffer import cpu

sys.path.insert(0, str(Path(__file__).resolve().parent))

from composer import Composer  # noqa: E402
from mosaic import read_the_transfer  # noqa: E402

# Which plane to check. Middle of the stack, so it is specimen rather than the
# empty ground at either end of a light-sheet acquisition.
SHARE_OF_THE_DEPTH = 0.5


def decode(body: bytes | None, piece: int, dtype: str, axes) -> np.ndarray:
    """Read a served piece back the way the browser's engine reads it.

    The bytes are put into a store as the one chunk of an array declared exactly as
    the picture's description declares it, and then simply read. Anything the
    server got wrong about the encoding — the compression, its settings, the kind
    of number, the order of the bytes — fails or comes out as noise here rather
    than as an unexplained black window later.

    ``None`` — a piece no tile covers, served as absent — is read the same way:
    the chunk is simply not there, and zarr hands back the declared fill value,
    exactly as the engine paints such ground.
    """
    store = zarr.storage.MemoryStore()
    array = zarr.create_array(
        store=store, shape=(1, piece, piece), chunks=(1, piece, piece),
        dtype=dtype, zarr_format=3, dimension_names=list(axes), overwrite=True,
    )
    if body is not None:
        store._store_dict["c/0/0/0"] = cpu.Buffer.from_bytes(body)
    return np.asarray(array[0])


def truth_for(mosaic, level: int, plane: int, top: int, left: int,
              piece: int) -> np.ndarray:
    """The same ground, laid out straight from the tiles and nothing else.

    Deliberately written the long way — no shared helper with the composer — so
    that a mistake in the composer's arithmetic cannot be repeated identically
    here and pass unnoticed.
    """
    _, height, width = mosaic.shape(level)
    ground = np.zeros((piece, piece), mosaic.dtype)
    for tile in mosaic.tiles:
        at = mosaic.lands_at(tile, level)
        held = tile.copies[level].array
        if not (at[0] <= plane < at[0] + held.shape[0]):
            continue
        from_y = max(top, at[1])
        to_y = min(min(top + piece, height), at[1] + held.shape[1])
        from_x = max(left, at[2])
        to_x = min(min(left + piece, width), at[2] + held.shape[2])
        if from_y >= to_y or from_x >= to_x:
            continue
        ground[from_y - top:to_y - top, from_x - left:to_x - left] = np.asarray(
            held[plane - at[0],
                 from_y - at[1]:to_y - at[1],
                 from_x - at[2]:to_x - at[2]]
        )
    return ground


def main() -> None:
    folder = Path(sys.argv[1])
    mosaic = read_the_transfer(folder)
    composer = Composer(mosaic)

    print(f"\n{len(mosaic.tiles)} tiles, {mosaic.levels} resolutions, "
          f"{mosaic.dtype}, axes {' '.join(mosaic.axes)}")
    print(f"corner {tuple(round(n, 1) for n in mosaic.corner_um)} um\n")

    print("  where each tile lands, in voxels of each resolution:")
    print(f"    {'tile':<8}" + "".join(f"{'L' + str(n):>18}"
                                       for n in range(mosaic.levels)))
    for tile in mosaic.tiles:
        row = f"    {tile.name.split('_')[1]:<8}"
        for level in range(mosaic.levels):
            at = mosaic.lands_at(tile, level)
            row += f"{str(at[1]) + ',' + str(at[2]):>18}"
        print(row)

    print("\n  the built picture, at each resolution:")
    for level in range(mosaic.levels):
        shape = mosaic.shape(level)
        deep, down, across = composer.grid(level)
        voxel = mosaic.voxel_um(level)
        print(f"    L{level}  {str(shape):>22} voxels of "
              f"{voxel[0]:>5.2f} x {voxel[1]:>5.2f} x {voxel[2]:>5.2f} um"
              f"   {down} x {across} pieces, {deep} planes")

    # -- 2 and 3: the pieces, and the bytes ---------------------------------
    print("\n  checking every piece of one band, at every resolution:")
    wrong = 0
    for level in range(mosaic.levels):
        deep, down, across = composer.grid(level)
        plane = int(deep * SHARE_OF_THE_DEPTH)
        # The band across the middle, which is where the seam between the two rows
        # of tiles falls -- so every piece checked has to combine tiles rather than
        # sitting comfortably inside one.
        row = max(0, down // 2)
        differing = 0
        for column in range(across):
            body = composer.bytes_for(level, plane, row, column)
            # Decoded through zarr's own machinery, from the very bytes the server
            # would put on the wire, rather than from the array the composer built.
            # That is what makes this a check of the encoding and the description
            # together, and not merely of the arithmetic.
            got = decode(body, composer.piece, mosaic.dtype, mosaic.axes)
            want = truth_for(mosaic, level, plane, row * composer.piece,
                             column * composer.piece, composer.piece)
            differing += int((got != want).sum())
        wrong += differing
        print(f"    L{level}  plane {plane:>4}, {across:>3} pieces   "
              f"wrong voxels: {differing}")

    print(f"\n  {'PASS' if wrong == 0 else 'FAIL'} — {wrong} wrong voxels in all\n")

    # -- 5: and the same pieces asked for all at once ------------------------
    #
    # Everything above builds one piece at a time, and a picture can be right
    # when asked politely and wrong when asked in parallel. It was: one encoder
    # was shared between threads, so a request could be handed another request's
    # specimen -- 13 to 22 of 25 pieces, differently every round, and no check
    # here could see it. The browser fetches chunks on many threads at once, so
    # this is the ordinary case rather than an unusual one.
    print("  the same pieces, all asked for at once:")
    for level in range(min(3, mosaic.levels)):
        deep, down, across = composer.grid(level)
        plane = int(deep * SHARE_OF_THE_DEPTH)
        places = [(row, column)
                  for row in range(min(3, down)) for column in range(min(4, across))]
        one_at_a_time = {
            place: Composer(mosaic).bytes_for(level, plane, *place)
            for place in places
        }
        together: dict = {}
        keeping = threading.Lock()
        racing = Composer(mosaic)

        def fetch(place, held=racing, into=together, guard=keeping, at=level, p=plane):
            body = held.bytes_for(at, p, *place)
            with guard:
                into[place] = body

        threads = [threading.Thread(target=fetch, args=(one,)) for one in places]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        muddled = [one for one in places if together[one] != one_at_a_time[one]]
        wrong += len(muddled)
        print(f"    L{level}  {len(places):>3} pieces at once   "
              f"handed the wrong piece: {len(muddled)}")

    print(f"\n  {'PASS' if wrong == 0 else 'FAIL'} — {wrong} wrong in all\n")

    # -- 4: what a slab saves ------------------------------------------------
    fresh = Composer(mosaic)
    deep, down, across = fresh.grid(0)
    plane, row, column = int(deep * SHARE_OF_THE_DEPTH), down // 2, across // 2
    began = time.perf_counter()
    fresh.bytes_for(0, plane, row, column)
    cold = (time.perf_counter() - began) * 1000
    began = time.perf_counter()
    for step in range(1, min(8, fresh.slab_depth(0))):
        fresh.bytes_for(0, plane + step, row, column)
    warm = (time.perf_counter() - began) * 1000 / max(1, min(8, fresh.slab_depth(0)) - 1)
    print(f"  full-resolution piece, first of its slab   {cold:7.0f} ms")
    print(f"  the next planes of the same slab           {warm:7.1f} ms each")
    print(f"  slab is {fresh.slab_depth(0)} planes deep\n")


if __name__ == "__main__":
    main()
