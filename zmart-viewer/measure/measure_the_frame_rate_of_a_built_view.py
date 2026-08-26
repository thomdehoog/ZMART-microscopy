"""How responsive is a built picture in a real browser, as the transfer grows?

The server-side ladder (``measure_scaling.py``) times what a piece costs to
build. This asks the other half of the question, the half an operator feels:
with the picture open in a genuine browser, how quickly does it open, how many
requests does it make, and does the drawing rate hold as the number of tiles
underneath it grows?

The claim being tested is the root requirement of the seamless view: however
many tiles a transfer holds, the viewer is handed **one** source, so the
engine's own per-source costs -- layer machinery, fetch scheduling, per-frame
work -- should not grow at all. What does grow is the work the server does per
piece, and the ladder measures that separately.

For every rung this writes a fresh synthetic transfer at fractional offsets
(the exact condition that makes a picture impossible to point at), declares it
as one built picture, opens it, and reports:

``opened``
    from asking for the page until every source has resolved -- the wait
    before anything can be looked at.

``requests``
    how many HTTP requests opening took, and separately how many were made
    while the view was being watched. Requests are the currency the browser
    pays per interaction; a count that grows with the tile count would mean
    the one-image promise is leaking.

``frames a second``, ``usual``, ``worst``
    the drawing rate while the view is kept gently moving, the middle frame
    interval, and the longest the picture ever sat still -- the number that
    makes a viewer feel broken even when the average looks fine.

``lit``
    how much of the screen actually shows specimen, reported so a
    suspiciously good rate can always be checked against whether there was a
    picture at all.

Run it with::

    python measure_the_frame_rate_of_a_built_view.py --headed
    python measure_the_frame_rate_of_a_built_view.py --rungs 1,5,10,50,100

``--headed`` opens a visible window, and on Windows that is the only way the
browser reaches the graphics card; headless Chromium draws in software
whatever arguments it is given. The renderer that actually drew is announced
on every run. Do not type into the window that opens; it is the measurement.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

_VIZ = Path(__file__).resolve().parents[1]
_BUILDING = _VIZ / "app" / "picture"
sys.path.insert(0, str(_BUILDING))
sys.path.insert(0, str(_VIZ))

import measure_the_frame_rate_of_a_linked_view as watching  # noqa: E402
from declare import declare_a_built_picture  # noqa: E402
from measure_scaling import write_a_transfer  # noqa: E402


def main() -> int:
    parsing = argparse.ArgumentParser(description=__doc__)
    parsing.add_argument(
        "--rungs", default="1,5,10,50,100",
        help="tile counts to climb through, comma separated",
    )
    parsing.add_argument(
        "--headed", action="store_true",
        help="open a visible window, which on Windows is the only way the "
             "browser reaches the graphics card",
    )
    asked = parsing.parse_args()
    rungs = [int(one) for one in asked.rungs.split(",")]

    dist = _VIZ / "app" / "page" / "dist"
    if not (dist / "index.html").exists():
        raise SystemExit(
            "the viewer page has not been built; build it once with\n"
            "  npm --prefix zmart-viewer/app/page run build"
        )

    started, browser = watching.a_browser(asked.headed)
    watching.say_what_is_drawing(browser)
    work = Path(tempfile.mkdtemp(prefix="built-frame-rate-"))
    try:
        print(f"\n  {'tiles':>6} {'opened':>8} {'requests':>16} "
              f"{'frames/s':>9} {'usual':>8} {'worst':>8} {'lit':>5}")
        print(f"  {'':>6} {'':>8} {'opening/watching':>16}")
        print("  " + "-" * 68)
        rows = []
        for tiles in rungs:
            transfer = work / f"transfer{tiles:05d}"
            write_a_transfer(transfer, tiles)
            views = work / f"views{tiles:05d}"
            store = declare_a_built_picture(views, transfer, name="built")
            row = watching.how_it_drew(browser, dist, views, [store.name],
                                       expect=1)
            row["tiles"] = tiles
            rows.append(row)
            print(f"  {tiles:>6} {row['opened']:>6.2f} s "
                  f"{row['asked_opening']:>8}/{row['asked_watching']:<7} "
                  f"{row['per_second']:>9.1f} {row['usual_ms']:>5.1f} ms "
                  f"{row['worst_ms']:>5.0f} ms {row['lit']:>5.2f}",
                  flush=True)
            shutil.rmtree(transfer)
            shutil.rmtree(views)

        if len(rows) >= 2:
            first, last = rows[0], rows[-1]
            grew = last["tiles"] / first["tiles"]
            print(f"\n  From {first['tiles']} tile(s) to {last['tiles']} "
                  f"-- {grew:.0f}x more:")
            for name, key in (("opening", "opened"),
                              ("requests to open", "asked_opening"),
                              ("frames a second", "per_second"),
                              ("usual frame", "usual_ms"),
                              ("worst pause", "worst_ms")):
                print(f"    {name:<17} "
                      f"{last[key] / max(1e-9, first[key]):>6.1f}x")
            print("\n  The browser is handed one source however many tiles the"
                  "\n  transfer holds, so every line here should read close to"
                  "\n  1.0x -- growth in this table is the one-image promise"
                  "\n  leaking.")
    finally:
        browser.close()
        started.stop()
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
