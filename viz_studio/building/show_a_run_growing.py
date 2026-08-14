"""Serve a fixture run live and let somebody WATCH it grow.

``measure_a_governed_run_at_scale`` is this script's twin and its opposite: the
harness locks a browser it controls, forbids touching, and turns the run into
columns of milliseconds; this one hands the browser to a person. It serves the
same baked picture through the same server, opens their own browser on it, and
then changes the run in front of them — landings, replacements, or a whole
acquisition from nothing — while the sliders stay theirs. Nothing here measures
anything. Its audience is an operator, a lab meeting, or anybody who has read
the ladder's table and wants to feel what the numbers mean.

A day of showing runs to their first watcher taught this script everything it
insists on:

- **The browser opens itself.** A URL printed into a terminal is a show that
  starts without its audience. The default browser is popped the moment the
  server answers, and the first change waits a breath longer.
- **The changes must be visible.** The fixtures fill tiles with 46000-62000
  counts, and against a 0-62000 display window that is white on white — a
  replacement was invisible and even a landing barely registered. The window
  is served as the tiles' own range, and replacements are written DIMMER than
  everything around them, so each change reads at a glance.
- **Consecutive beats scattered.** The harness lands positions where the
  measurement needs them; an eye wants a story. ``--spiral`` runs the whole
  acquisition in spiral order from the centre — every tile connected to the
  path, the way a stage actually drives — and ``--core`` first commits a
  central block for the spiral to wind around.
- **The same path can be watched in reverse.** ``--inverse-spiral-vanish``
  starts with a complete survey and replaces its tiles with near-black frames from
  the outside inward. It appends honest replacement commits; it deletes no
  positions or evidence.
- **The page has a rhythm of its own.** The viewer catches up on its own
  cadence and coalesces whatever landed since its last look, so changes
  arriving faster than the catch-up appear in batches. That coalescing is
  load-bearing (it is why a burst of twenty costs eight derives, not twenty),
  but for single-tile steps at speed, ``--quick-page`` serves a copy of the
  built page with a 150 ms check interval injected. Below the page's rhythm,
  pace the drip slower instead — one change per look needs roughly
  ``--every 2.5`` against the stock page.

Run it with::

    python show_a_run_growing.py --across 30 --spiral --every 0.1 \
        --fixtures D:/zmart-demos --quick-page

The fixture is written once and kept, exactly as the harness keeps its own; a
finished survey cannot grow again (the manifest only moves forward), so a
fresh show wants a fresh ``--fixtures`` folder or a larger ``--across``.
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

_BUILDING = Path(__file__).resolve().parent
sys.path.insert(0, str(_BUILDING))

import numpy as np  # noqa: E402

import measure_a_governed_run_at_scale as harness  # noqa: E402
from declare import declare_a_governed_picture  # noqa: E402
from server import make_server  # noqa: E402

# How dim a replacement is written. Well separated from the fixtures' BRIGHT
# range so a re-imaged tile turns visibly grey among white neighbours -- the
# whole reason a watcher can tell a replacement happened at all.
DIMMER = (18000, 30000)

# The injected check interval for --quick-page, in milliseconds. Fast enough
# that a 0.1 s drip advances in single-tile steps, slow enough that the page
# is not asking more often than it can act.
QUICK_CHECK_MS = 150


def a_quicker_page() -> Path:
    """A temporary copy of the built page that checks for changes eagerly.

    The stock page asks every ten seconds and lets announcements pull it in
    sooner; that is right for a run whose positions arrive on a microscope's
    clock and too slow for a demonstration's. The interval is a page global
    read at startup, so a copy of ``dist`` with one script tag prepended is
    the entire mechanism -- the build itself is not touched.
    """
    built = _BUILDING.parent / "frontend" / "dist"
    copied = Path(tempfile.mkdtemp(prefix="zmart-quick-page-")) / "dist"
    shutil.copytree(built, copied)
    page = copied / "index.html"
    page.write_text(
        page.read_text(encoding="utf-8").replace(
            "<head>",
            f"<head><script>globalThis.zmartLiveCheckMs={QUICK_CHECK_MS};"
            "</script>",
            1,
        ),
        encoding="utf-8",
    )
    return copied


def spiral_order(across: int, width: int) -> list[str]:
    """Every position, in the order a spiral scan from the centre visits it.

    Step lengths run 1, 1, 2, 2, 3, 3... turning right-down-left-up, and steps
    that leave the grid are simply skipped, so the walk covers every cell of a
    bounded square exactly once while every visited cell touches the path.
    """
    row = column = (across - 1) // 2
    walk = [(row, column)]
    step, direction = 1, 0
    moves = ((0, 1), (1, 0), (0, -1), (-1, 0))
    while len(walk) < across * across:
        for _ in range(2):
            dr, dc = moves[direction % 4]
            for _ in range(step):
                row, column = row + dr, column + dc
                if 0 <= row < across and 0 <= column < across:
                    walk.append((row, column))
            direction += 1
        step += 1
    return [f"p{r:0{width}d}{c:0{width}d}" for r, c in walk]


def pop_the_browser(port: int) -> None:
    """Open the watcher's browser on the page, once the server answers.

    Chrome by name first, the system default second. Not a preference about
    browsers in general but about EVIDENCE: the suites and the storm gate run
    in Chromium, so a show watched in Chrome is watched in the engine the
    tests vouch for — a difference seen there is ours, and a difference seen
    only elsewhere belongs to that browser. Windows-shaped on purpose: the
    machines this shows on are the lab's. Where neither launch lands, the
    printed address still stands.
    """
    address = f"http://127.0.0.1:{port}"
    try:
        named = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Start-Process chrome '{address}'"],
            check=False, timeout=30, capture_output=True,
        )
        if named.returncode == 0:
            return
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Start-Process '{address}'"],
            check=False, timeout=30,
        )
    except OSError:
        pass


def main() -> int:
    parsing = argparse.ArgumentParser(description=__doc__)
    parsing.add_argument("--across", type=int, default=30,
                         help="the survey is this many positions on a side")
    parsing.add_argument("--fixtures", required=True,
                         help="where the show's fixture lives; a finished "
                              "survey cannot grow again, so a fresh show "
                              "wants a fresh folder")
    parsing.add_argument("--port", type=int, default=8851)
    parsing.add_argument("--every", type=float, default=0.1,
                         help="seconds between changes")
    parsing.add_argument("--grace", type=float, default=2.0,
                         help="seconds between the page being popped and the "
                              "first change")
    parsing.add_argument("--limit", type=int, default=0,
                         help="stop after this many changes (0 = all)")
    parsing.add_argument("--spiral", action="store_true",
                         help="run the whole acquisition in spiral order "
                              "from the centre, starting from empty ground")
    parsing.add_argument("--core", type=int, default=0,
                         help="with --spiral: pre-commit the central NxN "
                              "block, so the spiral winds around tiles "
                              "already on screen")
    parsing.add_argument("--replace", type=int, default=0,
                         help="re-image this many interior positions in "
                              "place instead, written dimmer so each one "
                              "shows; wants a survey that is already full")
    parsing.add_argument("--inverse-spiral-vanish", action="store_true",
                         help="start complete, then replace every tile with "
                              "black in the exact reverse spiral order")
    parsing.add_argument("--quick-page", action="store_true",
                         help="serve a copy of the page that checks every "
                              f"{QUICK_CHECK_MS} ms, for single-tile steps "
                              "at fast paces")
    parsing.add_argument("--no-pop", action="store_true",
                         help="do not open a browser; something else — a "
                              "pywebview window, say — is the watcher")
    asked = parsing.parse_args()

    harness.FIXTURES = Path(asked.fixtures)
    across = asked.across
    run, order = harness.the_run(across)
    width = len(str(across - 1))
    committed = set(run._committed_units())

    boundary = [one for one in order
                if 0 in (int(one[1:1 + width]), int(one[1 + width:]))
                or across - 1 in (int(one[1:1 + width]), int(one[1 + width:]))]
    interior = [one for one in order if one not in set(boundary)]

    if asked.inverse_spiral_vanish:
        spiral = spiral_order(across, width)
        fresh = [one for one in spiral if (one, 0) not in committed]
        print(f"pre-committing the complete {across}x{across} survey "
              f"({len(fresh)} bright tiles before the show)...")
        for position_id in fresh:
            harness.fast_publish(run, position_id)
            committed.add((position_id, 0))
        to_change = list(reversed(spiral))
    elif asked.spiral:
        if asked.core:
            low = (across - asked.core) // 2
            core = [f"p{r:0{width}d}{c:0{width}d}"
                    for r in range(low, low + asked.core)
                    for c in range(low, low + asked.core)]
            fresh = [one for one in core if (one, 0) not in committed]
            print(f"pre-committing the central {asked.core}x{asked.core} "
                  f"core ({len(fresh)} tiles on screen before the show)...")
            for position_id in fresh:
                harness.fast_publish(run, position_id)
                committed.add((position_id, 0))
        to_change = [one for one in spiral_order(across, width)
                     if (one, 0) not in committed]
    elif asked.replace:
        to_change = []
    else:
        fresh = [one for one in interior if (one, 0) not in committed]
        if fresh:
            print(f"bulk-publishing {len(fresh)} interior positions (the "
                  "survey the operator has already imaged)...")
            for position_id in fresh:
                harness.fast_publish(run, position_id)
        to_change = [one for one in boundary if (one, 0) not in committed]
    if asked.limit:
        to_change = to_change[:asked.limit]

    shown = harness.FIXTURES / f"gov{across}x{across}" / "shown"
    store = shown / "live.ome.zarr"
    if not (store / "zarr.json").is_file():
        print("declaring the baked picture (once)...")
        store = declare_a_governed_picture(shown, run.folder, name="live",
                                           bake=True)

    site = a_quicker_page() if asked.quick_page else (
        _BUILDING.parent / "frontend" / "dist")
    server = make_server(port=asked.port, data_dir=shown, site_dir=site,
                         store=[store.name], window=harness.BRIGHT)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]

    pictured_levels = len(json.loads((store / "zarr.json").read_text(
        encoding="utf-8"))["attributes"]["ome"]["multiscales"][0]["datasets"])

    def the_dirty_pieces_of(position_id: str) -> dict:
        piece = 512
        origin = run.layout.placement(position_id).origin
        y, x = int(origin.get("y", 0)), int(origin.get("x", 0))
        dirty = {}
        for number in range(pictured_levels):
            deepest = min(number, len(run.profile.levels) - 1)
            rung = run.profile.level(deepest)
            extended = 2 ** (number - deepest)
            down_y = int(rung.downsampling.get("y", 1)) * extended
            down_x = int(rung.downsampling.get("x", 1)) * extended
            top, left = y // down_y, x // down_x
            bottom = (y + harness.FRAME - 1) // down_y
            right = (x + harness.FRAME - 1) // down_x
            dirty[str(number)] = [
                [0, row, column]
                for row in range(top // piece, bottom // piece + 1)
                for column in range(left // piece, right // piece + 1)
            ]
        return dirty

    def announce(position_id: str) -> None:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/announce",
            data=json.dumps({
                "wrote_image_in_place": True,
                "dirty": the_dirty_pieces_of(position_id),
            }).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=30):
            pass

    if asked.no_pop:
        print(f"\n=== http://127.0.0.1:{port} — waiting for its watcher ===")
    else:
        print(f"\n=== http://127.0.0.1:{port} — popping your browser ===")
        pop_the_browser(port)
    time.sleep(asked.grace)

    if asked.inverse_spiral_vanish:
        # Numeric zero is the Zarr fill value, so an all-zero frame legitimately
        # stores no chunks and the fail-closed publisher refuses to call it an
        # acquired position. One is equally black under the show's 46k+ window
        # while remaining physically present and therefore publishable.
        vanished = np.ones((1, harness.FRAME, harness.FRAME), dtype="uint16")
        for number, position_id in enumerate(to_change):
            run.replace_a_position(position_id, vanished)
            announce(position_id)
            print(f"  vanished {position_id}  "
                  f"({number + 1}/{len(to_change)})", flush=True)
            time.sleep(asked.every)
    elif asked.replace:
        rng = np.random.default_rng(11)
        renewing = list(interior)
        rng.shuffle(renewing)
        for number, position_id in enumerate(renewing[:asked.replace]):
            run.replace_a_position(
                position_id,
                rng.integers(*DIMMER, (1, harness.FRAME, harness.FRAME)
                             ).astype("uint16"))
            announce(position_id)
            print(f"  replaced {position_id}  ({number + 1}/{asked.replace})",
                  flush=True)
            time.sleep(asked.every)
    else:
        for number, position_id in enumerate(to_change):
            harness.fast_publish(run, position_id)
            announce(position_id)
            print(f"  landed {position_id}  ({number + 1}/{len(to_change)})",
                  flush=True)
            time.sleep(asked.every)

    print("\nthe show is over; still serving so the picture can be explored. "
          "Ctrl+C to stop.", flush=True)
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    raise SystemExit(main())
