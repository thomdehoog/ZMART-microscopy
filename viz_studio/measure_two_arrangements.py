"""One picture built from pointers, against one layer holding many sources.

The linked picture holds one image however many positions are underneath it. The
other arrangement hands the engine the positions themselves, as several sources of
one layer, each placed by what its own description says. Both draw the same pixels
in the same places; only the mechanism differs. The question is what the second
costs, because the engine builds a drawing layer for every image it is handed and
that is the cost the picture exists to avoid.

Positions are served straight out of the picture's own folder -- nothing copied,
nothing edited -- so neither arrangement has an advantage in what it draws.

**Read the caveats before quoting anything this prints.**

``lit`` is not the fraction of the panel with specimen on it. It is the fraction of
the *centre half* of the canvas above a brightness floor (``tests/pixels.py``), and
it is blind to which pyramid level drew: a tile from level 2 lights the same pixels
as the same tile from level 0. It is a blank-screen guard and nothing more. It
cannot tell a settled picture from one still refining.

``held`` counts the data sources a layer *declares*, not the ones that loaded.
``layer/index.js`` pushes each source synchronously and a source that fails stays
in the list with an error on it, still counted. Use it as an upper bound.

**The camera is a race and this script does not yet pin it.** Neuroglancer centres
the view once, from whichever source resolves first, and never recentres; the zoom
is reset the same way. With per-store placements each source declares different
bounds, so where the view lands can differ from run to run. Until position and zoom
are set explicitly after opening, rows are comparable only when their ``lit``
agrees, and even then only roughly.

Absolute milliseconds do not travel. Headless forces software drawing, which
overstated the cost about fiftyfold against the same ladder on a card. The shape of
the curve -- flat against linear -- is what transfers.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

_VIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(_VIZ.parent))
sys.path.insert(0, str(_VIZ))
sys.path.insert(0, str(_VIZ / "backend"))
sys.path.insert(0, str(_VIZ / "tests"))

from measure_a_run_of_positions import a_run_of, how_it_drew  # noqa: E402
from measure_the_frame_rate_of_a_linked_view import a_browser  # noqa: E402

RUNGS = [5, 10, 50, 100, 200, 400]


def measure(browser, built: Path, ladder: Path, count: int) -> list[dict]:
    folder = ladder / f"n{count}"
    picture = folder / "experiment.ome.zarr"
    if not picture.exists():
        print(f"  writing {count} positions...", flush=True)
        a_run_of(count, folder)

    positions = picture / "positions"
    names = sorted(p.name for p in positions.glob("*.ome.zarr"))

    rows = []
    for label, where, store in (
        ("picture", folder, "experiment.ome.zarr"),
        ("sources", positions, names),
    ):
        try:
            got = how_it_drew(browser, built, where, store)
            got.update(arrangement=label, positions=count, asked=len(names))
            rows.append(got)
            print(f"  {label:8s} held={got['held']:4d}/{len(names):<4d} "
                  f"lit={got['lit']:.3f} frame={got['drawing_ms']:.1f}ms "
                  f"fps={got['fps']:.0f} requests={got['requests']}", flush=True)
        except Exception:
            print(f"  {label:8s} FAILED at {count} positions", flush=True)
            traceback.print_exc()
    return rows


def main() -> int:
    ladder = Path(sys.argv[1])
    headed = "--headed" in sys.argv
    print(f"drawing {'on the card' if headed else 'in software'}", flush=True)

    built = _VIZ / "frontend" / "dist"
    started, browser = a_browser(headed=headed)
    everything: list[dict] = []
    try:
        for count in RUNGS:
            print(f"\n== {count} positions", flush=True)
            everything.extend(measure(browser, built, ladder, count))
    finally:
        browser.close()
        started.stop()

    print("\n\npositions  arrangement    held   lit   drawing frame    fps   requests   opening")
    for row in everything:
        held = f"{row['held']}/{row['asked']}"
        print(f"{row['positions']:>9d}  {row['arrangement']:<11s} {held:>8s} "
              f"{row['lit']:6.3f} {row['drawing_ms']:12.1f} ms "
              f"{row['fps']:6.0f} {row['requests']:10d} {row['opened']:8.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
