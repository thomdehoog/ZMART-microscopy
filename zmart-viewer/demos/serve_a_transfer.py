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
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app" / "picture"))

from composer import PIECE, Composer, the_piece_address  # noqa: E402
from mosaic import read_the_transfer  # noqa: E402


# --- the server, which lived in app/picture/server.py until 2026-08-26.
# It is here because this is its only caller, and because a script
# should hold what it needs. Moving it also ended a real trap: two
# files named server.py, both on the import path, resolved by
# insertion order.
#
# A web server that answers for a picture it does not hold.
#
# Every piece it serves is built the moment it is asked for, out of the tiles the
# transfer really contains. The description is written from the arrangement; the
# pieces are built by :class:`composer.Composer`.
#
# It keeps a note of what it was asked for, split by resolution. That is how the
# question "which copy did the engine actually choose to draw?" gets an answer from
# the traffic rather than from an impression of how blurry the window looks — a
# distinction the earlier measurements in this repo learned the hard way, having
# reached four confident conclusions from photographs and had all four turn out
# wrong.
#
# The browser is served from a different port, so every answer carries the header
# saying a page from elsewhere may read it. Without it the requests are made,
# refused by the browser, and the window stays black with the reason only in a
# console nobody is looking at.

# What the built picture is called in the address. Anything else asked for is
# answered with a plain "nothing here".
STORE = "built.ome.zarr"


def serve(composer: Composer, port: int = 0):
    """Start the server; hand back it, its address, and its record of work."""
    ledger = {
        "pieces": {level: 0 for level in range(composer.mosaic.levels)},
        "work_ms": {level: [] for level in range(composer.mosaic.levels)},
        "descriptions": 0,
        "refused": [],
        "first_asked": None,
    }
    guard = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_):
            """Quiet. What was asked for is kept in the ledger instead."""

        def _send(self, body: bytes, kind: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "*")
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "*")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self):
            asked = self.path.split("?")[0].strip("/")
            if ledger["first_asked"] is None:
                ledger["first_asked"] = time.perf_counter()
            if not asked.startswith(STORE):
                return self._missing(asked)
            inside = asked[len(STORE):].strip("/")

            if inside == "zarr.json":
                ledger["descriptions"] += 1
                return self._send(composer.group_json(), "application/json")

            parts = inside.split("/")
            if len(parts) == 2 and parts[1] == "zarr.json" and parts[0].isdigit():
                level = int(parts[0])
                if not 0 <= level < composer.mosaic.levels:
                    return self._missing(asked)
                ledger["descriptions"] += 1
                return self._send(composer.array_json(level), "application/json")

            # A piece is named by its resolution, then "c", then one number
            # per axis of the picture's own description -- three for a flat
            # picture, five for one grown along (t, c). One parser decides
            # (the_piece_address), the same one every door uses.
            address = the_piece_address(inside)
            if address is not None:
                level, moment, channel, plane, row, column = address
                if not 0 <= level < composer.mosaic.levels:
                    return self._missing(asked)
                deep, down, across = composer.grid(level)
                moments, channels = composer.mosaic.frame_room
                if not (0 <= plane < deep and 0 <= row < down
                        and 0 <= column < across
                        and 0 <= moment < moments and 0 <= channel < channels):
                    return self._missing(asked)
                began = time.perf_counter()
                body = composer.bytes_for(level, plane, row, column,
                                          moment, channel)
                spent = (time.perf_counter() - began) * 1000
                with guard:
                    ledger["work_ms"][level].append(spent)
                    ledger["pieces"][level] += 1
                if body is None:
                    return self._missing(asked)
                return self._send(body, "application/octet-stream")

            return self._missing(asked)

        def _missing(self, asked: str) -> None:
            """Say plainly there is nothing here, and remember having been asked.

            404 rather than anything politer, and that is deliberate. The drawing
            engine treats 403, 404 and a failed connection as "this piece is
            absent" and fills the ground from the fill value without complaint. A
            204, which reads as the more courteous answer, is taken instead as a
            successful reply with an empty body and fails to decode — the polite
            answer is the broken one.
            """
            with guard:
                ledger["refused"].append(asked)
            body = b"nothing here"
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}", ledger


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
