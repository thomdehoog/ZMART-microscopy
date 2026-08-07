"""Find out how large a run your own computer can actually show.

Run this on the machine you use at the microscope. It answers one question that
matters a great deal and cannot be answered by reading code: **when you open a
folder holding many positions, do all of them actually appear?**

There was a time when the answer was no, and that is why this exists. Above roughly
six hundred and eighty positions the viewer drew only some of the specimen and said
nothing about the rest — the missing positions were not slow to arrive, they never
arrived at all, and the picture looked complete. That is fixed: the stores are now
handed to the drawing engine in groups rather than all at once, and nine hundred
positions arrive nine hundred of nine hundred where six hundred and eighty-one did
before.

It is still worth running, for two reasons. The first is that the old ceiling depended
on the browser and the machine, so the only way to be sure your own setup is sound is
to ask it — and if a future change ever brings the loss back, this is what says so
plainly instead of leaving you to notice that a folder looks thin. The second is that
not losing positions is not the same as being pleasant to use: a folder of nine hundred
still takes half a minute to open and then draws slowly, and the table below tells you
that too.

What it does
------------

For each folder size you ask for, it writes a throwaway folder of that many
positions, opens the viewer on it, waits until the viewer has stopped working, and
then reports:

``asked for``
    how many positions were written to disk.
``arrived``
    how many the viewer actually managed to read and can draw.
``lost``
    the difference — positions of your specimen that would silently not be there.
``seconds``
    how long from opening the page until it stopped working.
``frames in 5 s``
    how smoothly it draws once everything has settled. Below about fifty, panning
    and moving the contrast handles will feel heavy; below about twenty the viewer
    is not really usable.
``contrast step``
    how long one nudge of a brightness slider takes. This is the number you feel
    most directly, because judging a specimen means moving that slider.

Running it
----------

    python check_scale.py

That sweeps a sensible range and prints a table with a plain verdict underneath.
It takes a few minutes. To choose the sizes yourself::

    python check_scale.py 100,500,1000
    python check_scale.py 2000 --budget=1800    # allow longer for a big one

The positions it writes are deliberately tiny — a single small plane each. That is
not a shortcut: the cost being measured is the number of separate images the viewer
has to deal with, which has nothing to do with how large each one is. A folder of
five hundred tiny positions behaves like a folder of five hundred real ones, and
fits on your disk. Everything is written under a temporary folder and deleted
afterwards, so none of your own data is touched.

It needs the viewer page built (``npm --prefix frontend run build``) and a browser,
the same as the tests. If you have run the test suite once, you have both.

What to do with the answer
--------------------------

If ``lost`` is zero at every size you care about, every position of your specimen is
reaching the screen, which is what this is chiefly here to confirm. Read the
``frames in 5 s`` and ``contrast step`` columns next: those say whether a folder that
size is comfortable to work with, which is a separate question and currently the
weaker one.

If ``lost`` is not zero, something has gone wrong — a folder that size is being drawn
wrong on your machine, and the size where it starts is worth writing down and
reporting. ``NEXT_STEPS.md`` explains the shape of the problem and what was done about
it.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import threading
import time
from collections import Counter
from pathlib import Path

VIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(VIZ / "backend"))

# One small plane per position. The number of separate positions is what is being
# measured, so there is no reason to write more than that -- and a great deal of
# reason not to, since a realistic folder of forty thousand positions would be
# forty terabytes.
SIDE, VOXEL_UM = 64, (2.0, 0.35, 0.35)

# Software rendering, so this gives the same answer on a machine without a
# graphics card as on one with. On a real card the frame numbers will be better;
# the counts of arrived and lost positions will not change, and those are the
# point.
BROWSER_ARGS = ["--use-gl=angle", "--use-angle=swiftshader", "--ignore-gpu-blocklist"]

# What the viewer holds for one image layer: how many positions it was handed, how
# many it has read, how many it gave up on, and how many it has not got to yet.
WHAT_ARRIVED = """
() => {
  const viewer = window.zmartViewer;
  const managed = viewer.layerManager.managedLayers.find(
    (m) => m.layer && m.layer.type === "image");
  if (!managed || !managed.layer) return null;
  let arrived = 0, lost = 0, waiting = 0;
  for (const source of managed.layer.dataSources) {
    if (source.loadState === undefined) { waiting += 1; continue; }
    if (source.loadState.error !== undefined) { lost += 1; continue; }
    arrived += 1;
  }
  return {
    handed: managed.layer.dataSources.length,
    arrived, lost, waiting,
    drawingLayers: managed.layer.renderLayers.length,
  };
}
"""

# How many frames the viewer manages in a given time, asking it to redraw
# continuously. This is what panning and dragging a slider have to compete with.
HOW_FAST_IT_DRAWS = """
async ({ seconds }) => {
  const viewer = window.zmartViewer;
  const until = performance.now() + seconds * 1000;
  let frames = 0;
  while (performance.now() < until) {
    viewer.display.scheduleRedraw();
    await new Promise((resolve) => requestAnimationFrame(() => resolve()));
    frames += 1;
  }
  return frames;
}
"""

# What one nudge of a brightness slider costs. The window is written straight onto
# the layer, which is what the panel does when the operator drags the handle.
ONE_CONTRAST_STEP = """
({ high }) => {
  const viewer = window.zmartViewer;
  const managed = viewer.layerManager.managedLayers.find(
    (m) => m.layer && m.layer.type === "image");
  const started = performance.now();
  managed.layer.shaderControlState.restoreState(
    { normalized: { range: [0, high] } });
  viewer.display.draw();
  return performance.now() - started;
}
"""


def write_position(store: Path, index: int, across: int) -> None:
    """Write one position: a single small plane, placed on the stage.

    The placing matters. Each position records where on the stage it was taken,
    and the viewer uses that to lay the pieces out beside each other rather than
    on top of one another -- so this writes them as a square grid, which is what a
    mosaic of a specimen looks like.
    """
    level = store / "0"
    level.mkdir(parents=True, exist_ok=True)
    (store / ".zgroup").write_text('{"zarr_format": 2}', encoding="utf-8")
    (level / ".zarray").write_text(
        json.dumps(
            {
                "zarr_format": 2,
                "shape": [1, 1, SIDE, SIDE],
                "chunks": [1, 1, SIDE, SIDE],
                "dtype": "<u2",
                "compressor": None,
                "fill_value": 0,
                "order": "C",
                "filters": None,
                "dimension_separator": ".",
            }
        ),
        encoding="utf-8",
    )
    (level / "0.0.0.0").write_bytes(_plane())
    row, column = divmod(index, across)
    step = SIDE * VOXEL_UM[2]
    (store / ".zattrs").write_text(
        json.dumps(
            {
                "multiscales": [
                    {
                        "version": "0.4",
                        "axes": [
                            {"name": "c", "type": "channel"},
                            {"name": "z", "type": "space", "unit": "micrometer"},
                            {"name": "y", "type": "space", "unit": "micrometer"},
                            {"name": "x", "type": "space", "unit": "micrometer"},
                        ],
                        "datasets": [
                            {
                                "path": "0",
                                "coordinateTransformations": [
                                    {"type": "scale", "scale": [1.0, *VOXEL_UM]},
                                    {
                                        "type": "translation",
                                        "translation": [0.0, 0.0, row * step, column * step],
                                    },
                                ],
                            }
                        ],
                    }
                ],
                "omero": {
                    "channels": [
                        {
                            "label": "ch0",
                            "color": "FFFFFF",
                            "window": {"min": 0, "max": 65535, "start": 0, "end": 4000},
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )


_CACHED_PLANE: bytes | None = None


def _plane() -> bytes:
    """A small plane with a gradient across it, made once and reused.

    A gradient rather than a constant, so that a screenshot of the result is
    recognisably an image and not a flat colour -- useful if you want to look at
    what this drew rather than only reading the numbers.
    """
    global _CACHED_PLANE
    if _CACHED_PLANE is None:
        import numpy as np

        y, x = np.mgrid[0:SIDE, 0:SIDE]
        _CACHED_PLANE = (500 + (y + x) * (3000 // (2 * SIDE))).astype("<u2").tobytes()
    return _CACHED_PLANE


def write_folder(root: Path, positions: int) -> None:
    """A folder of one acquisition type, laid out as a square mosaic."""
    across = max(1, int(positions**0.5))
    for index in range(positions):
        write_position(root / f"overview_pos{index:05d}.ome.zarr", index, across)


def look(positions: int, budget: int) -> dict:
    """Open the viewer on a folder of ``positions`` positions and see what happens."""
    from playwright.sync_api import sync_playwright
    from server import make_server

    root = Path(tempfile.mkdtemp(prefix=f"zmart-scale-{positions}-"))
    result: dict = {"positions": positions}
    try:
        write_folder(root, positions)
        names = sorted(path.name for path in root.glob("*.ome.zarr"))
        httpd = make_server(
            port=0,
            data_dir=root,
            site_dir=VIZ / "frontend" / "dist",
            store=names,
            live=False,
        )
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{httpd.server_address[1]}"
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=BROWSER_ARGS)
            page = browser.new_page(viewport={"width": 1100, "height": 800})
            # Why the browser refused, in its own words. When positions go missing
            # this is the evidence for it being a matter of volume rather than of
            # anything wrong with the data.
            refusals: list[str] = []
            page.on("requestfailed", lambda request: refusals.append(request.failure or "?"))
            try:
                started = time.monotonic()
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_function(
                    "() => window.zmartViewer !== undefined", timeout=budget * 1000
                )
                # Wait until nothing is still being worked on, or until the budget
                # runs out. A folder past the ceiling settles quickly, because the
                # viewer gives up rather than keeps trying.
                deadline = time.monotonic() + budget
                state = None
                while time.monotonic() < deadline:
                    state = page.evaluate(WHAT_ARRIVED)
                    if state and state["handed"] >= positions and state["waiting"] == 0:
                        break
                    time.sleep(0.5)
                result["seconds"] = round(time.monotonic() - started, 1)
                result.update(
                    {
                        "arrived": state["arrived"] if state else 0,
                        "lost": state["lost"] if state else positions,
                        "waiting": state["waiting"] if state else 0,
                        "drawingLayers": state["drawingLayers"] if state else 0,
                    }
                )
                result["frames"] = page.evaluate(HOW_FAST_IT_DRAWS, {"seconds": 5})
                result["contrastMs"] = round(
                    page.evaluate(ONE_CONTRAST_STEP, {"high": 3500}), 1
                )
                result["refusals"] = Counter(refusals).most_common(2)
            finally:
                page.close()
                browser.close()
                httpd.shutdown()
                thread.join(timeout=5)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    return result


def report(rows: list[dict]) -> None:
    """Print the table, and then say in words what it means."""
    print()
    print(
        f"{'asked for':>10} {'arrived':>9} {'lost':>7} {'seconds':>9} "
        f"{'frames in 5 s':>15} {'contrast step':>15}"
    )
    print("-" * 70)
    for row in rows:
        print(
            f"{row['positions']:>10} {row['arrived']:>9} {row['lost']:>7} "
            f"{row['seconds']:>9} {row['frames']:>15} {row['contrastMs']:>13} ms"
        )

    losing = [row for row in rows if row["lost"] or row["waiting"]]
    print()
    if not losing:
        print(
            "Every position arrived at every size tried. For runs of this size the\n"
            "viewer is showing you your whole specimen."
        )
    else:
        first = losing[0]
        print(
            f"From about {first['positions']} positions upward, this machine does not show\n"
            f"the whole specimen: {first['lost']} of {first['positions']} positions did not arrive, and\n"
            "nothing on screen would have told you. The data on disk is fine. This is\n"
            "the fault the group-by-group feeding in engine.js was built to prevent, so\n"
            "seeing it again means either that feeding has been undone or that your\n"
            "browser gives up sooner than the ones it was measured against."
        )
        if first["refusals"]:
            reason, times = first["refusals"][0]
            print(f'The browser\'s own reason, {times} times over: "{reason}".')
        print("\nSee NEXT_STEPS.md for why this happens and what the fix is.")

    slow = [row for row in rows if row["frames"] < 50 and not row["lost"]]
    if slow:
        print(
            f"\nNote also that at {slow[0]['positions']} positions the viewer managed only "
            f"{slow[0]['frames']} frames in\nfive seconds, and one nudge of a brightness slider took "
            f"{slow[0]['contrastMs']} ms. Even where\nnothing is lost, a folder that size is heavy to work with."
        )


def main() -> None:
    sizes, budget = [100, 400, 700, 1000], 600
    for argument in sys.argv[1:]:
        if argument.startswith("--budget="):
            budget = int(argument.split("=")[1])
        else:
            sizes = [int(part) for part in argument.split(",")]

    print(f"Trying {', '.join(str(size) for size in sizes)} positions.")
    print("Each size writes a throwaway folder, opens the viewer, and measures it.")
    rows = []
    for size in sizes:
        print(f"  {size} positions ... ", end="", flush=True)
        row = look(size, budget)
        rows.append(row)
        print(f"{row['arrived']} of {size} arrived, {row['seconds']} s")
    report(rows)


if __name__ == "__main__":
    main()
