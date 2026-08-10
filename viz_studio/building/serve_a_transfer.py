"""Show a transfer from another microscope as one picture, copying nothing.

A mesoSPIM transfer is a folder of separate tiles, each recording where on the
stage it came from. Handing those to a viewer as separate images works and does not
scale — every tile is a source of its own, and the cost of opening grows with the
count of them; a run of two hundred asked for 1,053 pieces where one picture asks
for about 300.

This offers the same tiles as **one picture** instead, and builds each piece of it
as the browser asks. Nothing is written, nothing on disk is touched, and the tiles
may sit anywhere at all — the Thy1 set steps 4547.06 voxels between rows, which no
arrangement of whole files could ever line up with.

Run it with the transfer to show::

    python serve_a_transfer.py "D:/OMEzarr data/.../Thy1_Mag25x_Ch561.ome.zarr"

It prints an address. Open that in the viewer as an image source; the built picture
is an ordinary OME-Zarr as far as anything reading it is concerned.

Press Ctrl-C to stop it. Nothing has to be cleaned up afterwards, because nothing
was created.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from composer import PIECE, Composer  # noqa: E402
from mosaic import read_the_transfer  # noqa: E402
from server import STORE, serve  # noqa: E402


def main() -> None:
    parsed = argparse.ArgumentParser(description=__doc__)
    parsed.add_argument("transfer", type=Path,
                        help="the folder holding one OME-Zarr per tile")
    parsed.add_argument("--port", type=int, default=0,
                        help="which port to serve on; 0 picks a free one")
    parsed.add_argument("--piece", type=int, default=PIECE,
                        help="how large a piece of the built picture is")
    given = parsed.parse_args()

    mosaic = read_the_transfer(given.transfer)
    composer = Composer(mosaic, piece=given.piece)
    server, address, ledger = serve(composer, port=given.port)

    shape = mosaic.shape(0)
    voxel = mosaic.voxel_um(0)
    print(f"\n  {len(mosaic.tiles)} tiles built into one picture of "
          f"{shape[1]} x {shape[2]} voxels, {mosaic.levels} resolutions")
    print(f"  a voxel is {voxel[0]} x {voxel[1]} x {voxel[2]} um; "
          f"the corner sits at {tuple(round(n, 1) for n in mosaic.corner_um)} um")
    print(f"  pieces of {composer.piece}, slabs {composer.slab_depth(0)} planes "
          f"deep\n")
    print(f"  open this:  {address}/{STORE}\n")
    print("  Ctrl-C to stop. Nothing is written; the tiles are opened read-only.\n")

    try:
        while True:
            time.sleep(5)
            served = sum(ledger["pieces"].values())
            if served:
                busiest = max(ledger["pieces"], key=lambda n: ledger["pieces"][n])
                times = ledger["work_ms"][busiest]
                middle = sorted(times)[len(times) // 2] if times else 0.0
                print(f"  {served} pieces built; most from L{busiest} "
                      f"({ledger['pieces'][busiest]}), middling {middle:.0f} ms"
                      + (f"; {len(ledger['refused'])} asked for that do not exist"
                         if ledger["refused"] else ""))
    except KeyboardInterrupt:
        print("\n  stopping.\n")
        server.shutdown()


if __name__ == "__main__":
    main()
