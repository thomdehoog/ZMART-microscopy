"""Measure the whole viewer on your own machine, in one command.

Run this on the computer you use at the microscope — ideally the one with the real
graphics card, because several of these numbers depend on it and none of them can be
guessed from reading the code.

    python measure_everything.py

It runs each of the individual measurements in turn and prints one summary at the
end. Each of them can also be run on its own if you want to look at one thing
closely; this exists so that you do not have to remember five commands, and so that
the numbers are gathered together and comparable.

Expect it to take a while — tens of minutes on a slow machine. Most of that is
making synthetic data, not measuring, and the data is thrown away afterwards.

What each part answers
----------------------

**How large a run can actually be shown** (`check_scale.py`). The most important
one, and the only one that needs a graphics card. It opens folders of increasing
size and asks whether every position actually appears. Above a certain number they
silently stop arriving, and the picture still looks complete — so this finds *your*
number rather than trusting one measured elsewhere.

**How long a finished folder takes to open** (`measure_cold_open.py`). From
pointing the viewer at a folder to the first pixel on screen.

**What one more position costs** (`measure_many_positions.py`). During a run,
positions arrive one at a time. This is the cost of the viewer noticing one.

**What a layer full of positions costs the engine** (`measure_sources.py`). A row
is drawn from every position of its acquisition type at once, and each is resolved
when it is added. This finds where that stops being free.

**What the drawing surface can do** (`measure_canvas.py`). Whether the graphics
card is being used at all, and what it manages.

Reading the results
-------------------

Numbers from a machine with no real graphics card are still useful for the parts
that never touch one — opening a folder, noticing a position — but the ones about
drawing will be far worse than yours and should not be quoted. The summary says
which is which.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent

# Each measurement, in the order worth running them: the cheap ones that need no
# graphics card first, so a machine that cannot draw still produces something
# useful before it reaches the parts that need one.
MEASUREMENTS = [
    (
        "opening a finished folder",
        "measure_cold_open.py",
        False,
        "from pointing the viewer at a folder to the first pixel",
    ),
    (
        "noticing one more position",
        "measure_many_positions.py",
        False,
        "what a run costs the viewer while it is in progress",
    ),
    (
        "a layer full of positions",
        "measure_sources.py",
        False,
        "where handing the engine every position stops being free",
    ),
    (
        "the drawing surface",
        "measure_canvas.py",
        True,
        "whether the graphics card is being used, and what it manages",
    ),
    (
        "how large a run can be shown",
        "check_scale.py",
        True,
        "the number above which positions silently stop appearing",
    ),
]


def _run(script: str) -> tuple[bool, float, str]:
    """Run one measurement, returning whether it worked, how long, and its output."""
    started = time.monotonic()
    finished = subprocess.run(
        [sys.executable, str(_HERE / script)],
        capture_output=True,
        text=True,
    )
    took = time.monotonic() - started
    output = finished.stdout + (finished.stderr if finished.returncode else "")
    return finished.returncode == 0, took, output


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure the viewer end to end and print one summary.",
    )
    parser.add_argument(
        "--skip-drawing",
        action="store_true",
        help="leave out the parts that need a graphics card. Useful on a server, "
        "or when you only want the numbers about reading and serving data.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=_HERE / "measurements.md",
        help="where to write the results. Keeping the file lets numbers from two "
        "machines, or from before and after a change, be put side by side — which "
        "is the only way to tell an improvement from a faster computer.",
    )
    args = parser.parse_args()

    if not (_HERE / "frontend" / "dist" / "index.html").exists():
        print(
            "The viewer page has not been built, and several of these measurements\n"
            "drive the real page. Build it first:\n\n"
            "    npm --prefix frontend install\n"
            "    npm --prefix frontend run build\n"
        )
        return 1

    results = []
    # Everything printed is also kept, so a number can be compared with the same
    # number from another machine or from before a change.
    written = [
        "# What this machine measured",
        "",
        "Produced by `measure_everything.py`. Each section is one measurement, run",
        "in full. Figures about drawing depend on this machine's graphics card;",
        "figures about opening folders and noticing positions do not.",
        "",
    ]
    for name, script, needs_drawing, why in MEASUREMENTS:
        if needs_drawing and args.skip_drawing:
            results.append((name, "skipped", 0.0, "asked to leave out drawing"))
            continue
        print(f"\n{'=' * 72}\n{name}  —  {why}\n{'=' * 72}", flush=True)
        worked, took, output = _run(script)
        print(output, flush=True)
        results.append((name, "measured" if worked else "FAILED", took, ""))
        written += [f"## {name}", "", f"*{why}*", "", "```", output.rstrip(), "```", ""]

    print(f"\n{'=' * 72}\nSummary\n{'=' * 72}")
    for name, how, took, note in results:
        minutes = f"{took / 60:.1f} min" if took >= 60 else f"{took:.0f} s"
        print(f"  {name:<34} {how:<10} {minutes if took else '':>9}  {note}")
    print(
        "\nThe figures above about drawing depend on this machine's graphics card.\n"
        "The ones about opening folders and noticing positions do not, and are\n"
        "comparable between machines.\n"
    )
    args.report.write_text("\n".join(written), encoding="utf-8")
    print(f"Written to {args.report}\n")
    return 0 if all(how != "FAILED" for _, how, _, _ in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
