"""A governed live acquisition, watched in the real viewer while it commits.

This is the acceptance run for the live contract, stated as the operator would:
**a position loads the moment it is done — it pops up as soon as its commit
lands, and every pyramid level shows it at once.** Done means proven done (the
commit, not the files appearing); as soon as means the page hears the revision
and refreshes the changed source without being asked; and every level at once
means no zoom can disagree with another about what has been imaged.

What it does, and what to watch for
-----------------------------------

A 12 x 12 governed grid is written through :class:`zmart_live.coordinator.
LivePublisher` — the production writer, nothing imitated — one commit roughly
every half second, while the real viewer window is open on the run's one
linked view. Three things have to be true on screen, and each has a moment in
the run that shows it:

* **Commit-gated appearance.** One position in the middle of the grid is
  written to disk early and *withheld*: its files are complete and sit there
  for most of the run, and its ground must stay dark the whole time. It is
  committed last, and only then may it appear.
* **Every level consistent.** Zooming during the run must show the same set of
  arrived positions at every rung of the pyramid — the linked view points
  every level at the same committed positions, so no zoom can know more than
  another.
* **No stale glimpses.** Tiles overlap on purpose, and a later commit is drawn
  over its neighbours' shared strips the moment it lands — never before, and
  the published ground underneath never blinks out while the newcomer is
  written-but-withheld.

Running it
----------

.. code-block:: console

    python workflows/target_acquisition/governed_live_demo.py

Heavy writes belong on the data disk (the endpoint protection tolerates what
the profile's temp is punished for), so the run lands under
``D:\\zmart-scale-tests`` when that drive exists and under the system temp
otherwise. ``--folder`` chooses somewhere else; ``--interval`` changes the
pace; ``--no-window`` runs the same acquisition headless and verifies the gate
through the production gateway instead of eyes, which is how a machine checks
this script without a screen.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (str(_REPO_ROOT), str(_REPO_ROOT / "viz_studio" / "backend")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from zmart_live.coordinator import LivePublisher  # noqa: E402
from zmart_live.gateway import answer_from_a_live_run, forget_live_run  # noqa: E402
from zmart_live.model import GridCell  # noqa: E402
from zmart_live.profiles import plan_the_writing  # noqa: E402

# The real overview arrangement at the real size: the planner cuts the frame
# and chooses the step so that neighbouring tiles overlap on purpose and every
# boundary lands on whole chunks at every level.
FRAME = 1152
GRID = 12

#: The position that is written early and committed last. Deliberately in the
#: middle of the grid, so the hole it leaves is surrounded by published ground
#: and impossible to miss — and so its eventual commit visibly draws over the
#: neighbours' shared strips.
WITHHELD = f"pos{GRID // 2:02d}{GRID // 2:02d}"

#: The display window handed to the viewer. The pattern below lives inside it.
DISPLAY = (200.0, 4200.0)


def a_frame(index: int) -> np.ndarray:
    """One position's pixels: structured, and different from every neighbour.

    A flat fill cannot be told apart from empty ground, and identical tiles
    make "another one landed" invisible. A ramp with bright grid lines stays
    recognisable when shrunk to the deepest pyramid level, and the per-tile
    brightness step keeps every boundary — including the drawn-over overlap
    strips — visible while the mosaic fills in.
    """
    ramp = np.linspace(600, 3000, FRAME, dtype=np.float32)
    tile = np.tile(ramp, (FRAME, 1))
    tile[:: FRAME // 9, :] = 3800
    tile[:, :: FRAME // 9] += 400
    tile += 90 * (index % 9)
    return tile.astype(np.uint16)[np.newaxis, :, :]


def the_run(folder: Path) -> LivePublisher:
    """The production publisher over a 12 x 12 grid, exactly as a run starts."""
    profile, _ = plan_the_writing("overview", frame=FRAME, z_planes=1)
    cells = {
        GridCell(row, column): f"pos{row:02d}{column:02d}"
        for row in range(GRID)
        for column in range(GRID)
    }
    return LivePublisher(folder, profile, run_id="governed-live-demo", cells=cells)


def acquire(run: LivePublisher, interval: float, *, say=print) -> None:
    """Write and commit every position, holding one back until the very end.

    The withheld position is written the moment its turn comes — its files are
    then complete on disk and stay that way — but its commit is saved for last.
    Everything the operator needs to distrust "the files are there" happens in
    that gap.
    """
    names = [
        f"pos{row:02d}{column:02d}" for row in range(GRID) for column in range(GRID)
    ]
    total = len(names)
    committed = 0
    began = time.monotonic()
    for index, name in enumerate(names):
        turn_began = time.monotonic()
        if name == WITHHELD:
            run.write_a_position(name, a_frame(index))
            say(
                f"  {name}: written to disk and WITHHELD - its ground must stay "
                f"dark until the last commit of the run"
            )
        else:
            event = run.write_and_publish(name, a_frame(index))
            committed += 1
            say(
                f"  {name}: committed as revision {event.revision:3d} "
                f"({committed}/{total - 1} ordinary commits)"
            )
        remaining = interval - (time.monotonic() - turn_began)
        if remaining > 0:
            time.sleep(remaining)

    say(f"  {WITHHELD}: publishing the withheld position now - watch it pop in")
    run.write_the_link_map(frozenset(run._committed_units()) | {(WITHHELD, 0)})
    run.write_the_view()
    run.write_the_layout()
    event = run.publish(WITHHELD)
    say(
        f"all committed: revision {event.revision} of {total}, "
        f"{time.monotonic() - began:.0f}s"
    )


def check_the_gate_by_hand(run: LivePublisher) -> None:
    """The headless stand-in for watching: ask the gateway what a viewer gets.

    Sampled mid-run and at the end by :func:`headless`, this asks the same
    questions eyes would: withheld ground dark, committed ground served, every
    linkable level agreeing.
    """
    forget_live_run(run.folder)
    placement = run.layout.placement(WITHHELD)
    committed = {name for name, _ in run._committed_units()}
    for level in run.profile.levels:
        by = level.downsampling
        chunk = level.inner_chunk
        middle_y = (placement.origin["y"] + FRAME // 2) // by["y"] // chunk["y"]
        middle_x = (placement.origin["x"] + FRAME // 2) // by["x"] // chunk["x"]
        answer = answer_from_a_live_run(
            run.view_level(level.level) / f"c/0/0/0/{middle_y}/{middle_x}"
        )
        served = answer is not None and answer.allowed
        if WITHHELD in committed:
            assert served, (
                f"level {level.level}: the committed centre position is not served"
            )
        else:
            assert not served, (
                f"level {level.level}: the withheld position's ground leaked"
            )
    # A committed corner is served at every level, so "dark centre" above can
    # never be satisfied by a viewer that shows nothing anywhere.
    if "pos0000" in committed:
        for level in run.profile.levels:
            answer = answer_from_a_live_run(
                run.view_level(level.level) / "c/0/0/0/0/0"
            )
            assert answer is not None and answer.allowed, (
                f"level {level.level}: published ground is not being served"
            )


def headless(folder: Path, interval: float) -> None:
    """Run the whole acquisition without a window and verify the gate instead."""
    run = the_run(folder)
    finished = threading.Event()

    def write_everything():
        try:
            acquire(run, interval)
        finally:
            finished.set()

    writer = threading.Thread(target=write_everything, daemon=True)
    writer.start()
    checked = 0
    while not finished.wait(timeout=2.0):
        if run.manifest.revision() >= 10:
            check_the_gate_by_hand(run)
            checked += 1
    writer.join()
    check_the_gate_by_hand(run)
    assert run.manifest.revision() == GRID * GRID
    print(
        f"headless: {GRID * GRID} commits, gate checked {checked + 1} times, "
        "withheld ground stayed dark at every level until its commit"
    )


def watched(folder: Path, interval: float) -> None:
    """The real thing: the pywebview window open while the run commits."""
    from launcher import open_window

    run = the_run(folder)
    writer = threading.Thread(
        target=acquire, args=(run, interval), kwargs={"say": print}, daemon=True
    )

    def start_writing_soon():
        # A short head start for the window, so the very first commits are
        # something the operator sees arrive rather than finds already there.
        time.sleep(4.0)
        writer.start()

    threading.Thread(target=start_writing_soon, daemon=True).start()
    print(f"the run lives at {folder}")
    print(f"watch {WITHHELD}: written early, withheld, committed last")
    open_window(
        port=0,
        data_dir=folder,
        store="views/overview.ome.zarr",
        window=DISPLAY,
        live=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--folder",
        default=None,
        help="where to write the run. Left out, a fresh folder is made under "
        "D:\\zmart-scale-tests when that drive exists (the data disk the "
        "endpoint protection tolerates), and under the system temp otherwise.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=0.5,
        help="seconds from one commit to the next, as far as inspection allows",
    )
    parser.add_argument(
        "--no-window",
        action="store_true",
        help="run headless and verify the gate through the production gateway "
        "instead of eyes",
    )
    args = parser.parse_args()

    if args.folder:
        folder = Path(args.folder)
    else:
        stamp = datetime.now().strftime("governed-live-%Y%m%d-%H%M%S")
        scale_tests = Path(r"D:\zmart-scale-tests")
        if scale_tests.is_dir():
            folder = scale_tests / stamp
        else:
            import tempfile

            folder = Path(tempfile.gettempdir()) / "zmart-governed-live" / stamp

    folder.mkdir(parents=True, exist_ok=True)
    if args.no_window:
        headless(folder, args.interval)
    else:
        watched(folder, args.interval)


if __name__ == "__main__":
    main()
