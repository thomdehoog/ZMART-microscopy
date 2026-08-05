"""What does a smaller piece size cost the viewer?

This exists to answer one question before anybody builds on it. There is a way of
showing an overlapping run as a single picture without copying anything: leave the
tiles where they are and have the server hand over the pieces that are not
overlapping, so the picture is a list of pointers rather than a second copy of the
data. `HANDOVER_overlapping_runs.md` sets out why that is worth having.

It has one condition, and the condition lands on the piece size. For a piece of the
picture to be exactly a piece of a tile — which is what lets it be handed over
rather than assembled — **the trim has to be a whole number of pieces**. The trim
is half the overlap, so a run overlapping by 256 voxels is trimmed by 128, and the
pieces have to be 128 or smaller.

That is often smaller than a run would otherwise choose, and smaller pieces mean
more of them: the same picture arrives in more requests, each carrying less. The
bytes are the same either way; what grows is the number of times the browser has to
ask. This measures whether that matters.

It needs no linking layer and no new format. It writes the same run at several
piece sizes and opens each one, so the only thing changing between rows is how
finely the picture is divided.

What to look at
---------------

``requests``
    how many things the browser asked for while opening. This is the number
    expected to grow, and the question is by how much.

``first pixel``
    how long until something is drawn. Requests only matter if they show up here.

``flat frames``
    whether drawing itself is affected once everything has arrived. It should not
    be — the engine draws from what it has decoded, not from how it arrived.

``contrast``
    a nudge of the brightness slider, which is what an operator feels most.

Run it with::

    python measure_the_chunk_size.py

It writes throwaway runs under a temporary folder and removes each before the next,
and it needs a browser, the same as the other measurements here.
"""

from __future__ import annotations

import measure_the_overlapping_run as sweep

# A tile large enough for the piece sizes below to be a real choice rather than an
# arithmetic accident, and a step that trims it to 512 voxels across -- which every
# piece size tried divides exactly, so the run is legal at all of them and the only
# thing changing is the piece size.
TILE = (2, 640, 640)
STEP = (2, 512, 512)

# The piece sizes to try, largest first. 256 is what this project writes today; 64
# is what a run overlapping by 128 voxels would be forced down to if its picture
# were made by linking rather than copying.
PIECES = (256, 128, 64, 32)

# How many tiles. Enough that opening the run is real work rather than noise, few
# enough that four of them fit in the time and the disk available.
HOW_MANY_TILES = 100


def main() -> None:
    print(f"\nThe same run of about {HOW_MANY_TILES} tiles, written at four piece "
          f"sizes.\nTiles {TILE[1]}x{TILE[2]}, trimmed to {STEP[1]}x{STEP[2]}, "
          f"two colours and two moments.\n")

    sweep.TILE = TILE
    sweep.STEP = STEP

    rows = []
    for piece in PIECES:
        sweep.CHUNK = piece
        print(f"  pieces of {piece} ...")
        row = sweep.measure(HOW_MANY_TILES)
        row["piece"] = piece
        rows.append(row)

    print(f"\n  {'piece':>6} {'requests':>10} {'first pixel':>13} "
          f"{'flat frames':>13} {'contrast':>10}")
    print("  " + "-" * 56)
    first = rows[0]
    for row in rows:
        first_pixel = ("-" if row["firstPixel"] is None
                       else f"{row['firstPixel']:.1f} s")
        print(f"  {row['piece']:>6} {row['requests']:>10} {first_pixel:>13} "
              f"{row['flatFrames']:>13} {row['contrastMs']:>7} ms")

    grew = rows[-1]["requests"] / max(1, first["requests"])
    print(f"\n  Going from pieces of {PIECES[0]} to pieces of {PIECES[-1]} asked "
          f"for {grew:.1f} times as many things.")
    print("  If first pixel and the frame count held, the piece size a linked")
    print("  picture forces is affordable. If they did not, acquire with more")
    print("  overlap instead -- half of a larger overlap divides more ways, so a")
    print("  bigger overlap allows a bigger piece.")


if __name__ == "__main__":
    main()
