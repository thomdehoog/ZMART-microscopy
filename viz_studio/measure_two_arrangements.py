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

from measure_a_run_of_positions import (  # noqa: E402
    a_run_of,
    how_it_drew,
    how_long_a_cold_open_takes,
    what_one_more_position_costs,
)
from measure_the_frame_rate_of_a_linked_view import a_browser  # noqa: E402

RUNGS = [5, 10, 50, 100, 200, 400]


def measure(browser, built: Path, ladder: Path, count: int,
            started=None, headed: bool = False) -> list[dict]:
    folder = ladder / f"n{count}"
    picture = folder / "experiment.ome.zarr"
    if not picture.exists():
        print(f"  writing {count} positions...", flush=True)
        a_run_of(count, folder)

    positions = picture / "positions"
    names = sorted(p.name for p in positions.glob("*.ome.zarr"))

    # Both arrangements are pointed at the same place from the same distance. The
    # run is a squarish mosaic of 512-voxel positions, so its middle is half its
    # width, and the zoom is whatever fits that width into the shorter side of the
    # panel with a little to spare. Without this the two rows of a rung start
    # wherever their first source happened to resolve.
    across = int(len(names) ** 0.5 + 0.999)
    wide = across * 512
    look_at = {"y": wide / 2, "x": wide / 2, "z": 0}
    zoom = wide / 700 * 1.1

    rows = []
    for label, where, store in (
        ("picture", folder, "experiment.ome.zarr"),
        ("sources", positions, names),
    ):
        try:
            got = how_it_drew(browser, built, where, store,
                              look_at=look_at, zoom=zoom)
            got.update(arrangement=label, positions=count, asked=len(names))
            # A cold opening is what an operator waits through, and it is the one
            # number the warm rows cannot give: every row after the first opens
            # into a browser the previous one warmed. It costs a browser launch
            # each, so it is asked for rather than assumed.
            if started is not None:
                got["cold_s"] = how_long_a_cold_open_takes(
                    started, built, where, store, headed
                )
            rows.append(got)
            print(f"  {label:8s} loaded={got['loaded']:4d}/{len(names):<4d} "
                  f"failed={got['failed']} pending={got['pending']} "
                  f"lit={got['lit']:.3f} frame={got['drawing_ms']:.1f}ms "
                  f"fps={got['fps']:.0f} requests={got['requests']} "
                  f"cold={got.get('cold_s', float('nan')):.2f}s", flush=True)
        except Exception:
            print(f"  {label:8s} FAILED at {count} positions", flush=True)
            traceback.print_exc()
    return rows


def main() -> int:
    ladder = Path(sys.argv[1])
    headed = "--headed" in sys.argv
    print(f"drawing {'on the card' if headed else 'in software'}", flush=True)

    cold = "--cold" in sys.argv
    built = _VIZ / "frontend" / "dist"
    started, browser = a_browser(headed=headed)
    everything: list[dict] = []
    try:
        for count in RUNGS:
            print(f"\n== {count} positions", flush=True)
            everything.extend(measure(
                browser, built, ladder, count,
                started=started if cold else None, headed=headed,
            ))
    finally:
        browser.close()
        started.stop()

    # Charged separately for each arrangement, because they are two curves and a
    # cost charged across both would be the difference between them rather than
    # what a position costs within one.
    costs: dict[str, dict[int, float | None]] = {}
    for label in ("picture", "sources"):
        costs[label] = what_one_more_position_costs(
            [row for row in everything if row["arrangement"] == label]
        )

    print("\n\n| positions | arrangement | held | lit | cold opening | warm opening "
          "| drawing frame | one more | fps | requests |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for row in everything:
        one_more = costs[row["arrangement"]].get(row["positions"])
        print(f"| {row['positions']} | {row['arrangement']} "
              f"| {row['held']}/{row['asked']} | {row['lit']:.3f} "
              f"| {row.get('cold_s', float('nan')):.2f} s "
              f"| {row['opened']:.2f} s | {row['drawing_ms']:.1f} ms "
              f"| {'-' if one_more is None else f'{one_more:.1f} us'} "
              f"| {row['fps']:.0f} | {row['requests']} |")

    print("\n'one more' is what each row's positions cost a frame, in microseconds "
          "a position, charged against the smallest run of that arrangement.")
    print("'lit' covers the centre half of the canvas only and cannot see which "
          "pyramid level drew; 'held' counts declared sources, not loaded ones.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
