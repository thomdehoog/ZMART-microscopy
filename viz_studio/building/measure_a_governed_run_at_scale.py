"""Does the governed live picture scale? A big survey, churned at its edge.

The scenario is the operator's own: a survey of many positions, most of it
already imaged, growing at its boundary while governance replaces positions
inside — the shape a real smart-microscopy run has. The questions are the
scale claims stated as measurements:

``open``
    the cold open of the already-heavy picture: from asking for the page to
    every source resolved.

``derive``
    what each commit costs the server: the snapshot derivation time and —
    the number the known linear term hides in — how many tiles it re-read
    from disk. Today that is every committed tile, every commit; the honest
    fix (reuse the unchanged tiles' objects) is judged against this column.

``visible``
    landing-to-visible, from the commit to the first painted frame that
    shows it, read from the page's own frame timestamps.

``transients``
    the recorder's flicker count. The gate: ZERO at every scale, or the
    scale fails.

The fixture is written once into a durable folder and reused — writing
a thousand positions costs minutes, measuring them must not. Landings are
real manifest commits; nothing tells the server anything beyond the
announcement a workflow would send.

Run it with::

    python measure_a_governed_run_at_scale.py --across 32 --churn 40
    python measure_a_governed_run_at_scale.py --across 32 --churn 40 --headed
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

_BUILDING = Path(__file__).resolve().parent
_VIZ = _BUILDING.parent
sys.path.insert(0, str(_BUILDING))
sys.path.insert(0, str(_VIZ))
sys.path.insert(0, str(_VIZ / "backend"))
sys.path.insert(0, str(_VIZ / "tests"))

import numpy as np

from server import make_server  # noqa: E402

import measure_the_frame_rate_of_a_linked_view as watching  # noqa: E402
import served  # noqa: E402
from declare import declare_a_governed_picture  # noqa: E402

from zmart_live.coordinator import LivePublisher  # noqa: E402
from zmart_live.model import GridCell  # noqa: E402
from zmart_live.profiles import plan_the_writing  # noqa: E402

FRAME = 384
BRIGHT = (46000, 62000)

# Where the fixtures live between runs. Deliberately durable: the writer's
# work is minutes per thousand positions and the measurements must be
# repeatable without paying it again.
FIXTURES = Path(r"D:\zmart-scale-runs")

DIP = 45
ENOUGH = 200


def the_run(across: int, seed_value: int = 7) -> tuple[LivePublisher, list[str]]:
    """The fixture: an ``across``-squared survey, written once, reused after.

    Position pixels are written for every planned cell; nothing is published
    here — publication is the measurement, so it belongs to the caller.
    """
    folder = FIXTURES / f"gov{across}x{across}"
    profile, _ = plan_the_writing("overview", frame=FRAME, z_planes=1)
    cells = {GridCell(row, column): f"p{row:02d}{column:02d}"
             for row in range(across) for column in range(across)}
    run = LivePublisher(folder / "run", profile, run_id=f"scale{across}",
                        cells=cells, timepoints=1)
    order = [f"p{row:02d}{column:02d}"
             for row in range(across) for column in range(across)]

    wanted = run.position_store(order[-1])
    if not (wanted / "zarr.json").is_file():
        print(f"Writing {len(order)} positions into {folder} (once)...")
        seed = np.random.default_rng(seed_value)
        began = time.time()
        for number, position_id in enumerate(order):
            run.write_a_position(
                position_id,
                seed.integers(*BRIGHT, (1, FRAME, FRAME)).astype("uint16"))
            if (number + 1) % 200 == 0:
                print(f"  {number + 1} written "
                      f"({(time.time() - began):.0f} s)", flush=True)
        run.write_the_link_map(frozenset((one, 0) for one in order))
        run.write_the_view()
        run.write_the_layout()
        print(f"  written in {time.time() - began:.0f} s")
    return run, order


def main() -> int:
    parsing = argparse.ArgumentParser(description=__doc__)
    parsing.add_argument("--across", type=int, default=32,
                         help="the survey is this many positions on a side")
    parsing.add_argument("--churn", type=int, default=40,
                         help="how many watched changes: half boundary "
                              "landings, half interior replacements")
    parsing.add_argument("--headed", action="store_true",
                         help="open a visible window")
    asked = parsing.parse_args()
    across = asked.across

    run, order = the_run(across)

    # The interior is pre-published in bulk -- the survey the operator has
    # already imaged. The outermost ring stays dark: it is the boundary the
    # run will grow into while being watched.
    boundary = [one for one in order
                if 0 in (int(one[1:3]), int(one[3:5]))
                or across - 1 in (int(one[1:3]), int(one[3:5]))]
    interior = [one for one in order if one not in set(boundary)]
    committed = set(run._committed_units())
    to_publish = [one for one in interior if (one, 0) not in committed]
    if to_publish:
        print(f"Bulk-publishing {len(to_publish)} interior positions "
              "(no viewer yet)...")
        began = time.time()
        for number, position_id in enumerate(to_publish):
            run.publish(position_id)
            if (number + 1) % 100 == 0:
                print(f"  {number + 1} published "
                      f"({(time.time() - began):.0f} s)", flush=True)
        print(f"  published in {time.time() - began:.0f} s "
              f"({(time.time() - began) / max(1, len(to_publish)) * 1000:.0f}"
              " ms each — the writer's own cost)")

    shown = FIXTURES / f"gov{across}x{across}" / "shown"
    store = declare_a_governed_picture(shown, run.folder, name="live")

    started, browser = watching.a_browser(asked.headed)
    watching.say_what_is_drawing(browser)
    server = make_server(port=0, data_dir=shown,
                         site_dir=_VIZ / "frontend" / "dist",
                         store=[store.name], window=(0, BRIGHT[0]))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    page = browser.new_page(viewport={"width": 1000, "height": 780})

    frames: list[tuple[float, bytes]] = []
    session = page.context.new_cdp_session(page)

    def one_frame(told) -> None:
        frames.append((float(told["metadata"]["timestamp"]),
                       base64.b64decode(told["data"])))
        session.send("Page.screencastFrameAck",
                     {"sessionId": told["sessionId"]})

    session.on("Page.screencastFrame", one_frame)

    def the_dirty_pieces_of(position_id: str) -> dict:
        piece = 512
        origin = run.layout.placement(position_id).origin
        y, x = int(origin.get("y", 0)), int(origin.get("x", 0))
        profile = run.profile
        dirty = {}
        for number in range(len(profile.levels)):
            rung = profile.level(number)
            down_y = int(rung.downsampling.get("y", 1))
            down_x = int(rung.downsampling.get("x", 1))
            top, left = y // down_y, x // down_x
            bottom = (y + FRAME - 1) // down_y
            right = (x + FRAME - 1) // down_x
            dirty[str(number)] = [
                [0, row, column]
                for row in range(top // piece, bottom // piece + 1)
                for column in range(left // piece, right // piece + 1)
            ]
        return dirty

    def announce(position_id: str) -> None:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/announce",
            data=json.dumps({"wrote_image_in_place": True,
                             "dirty": the_dirty_pieces_of(position_id)}).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=30):
            pass

    try:
        opening = time.time()
        page.goto(f"http://127.0.0.1:{port}", wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartViewer !== undefined",
                               timeout=120_000)
        page.wait_for_function("() => window.zmartSourcesWaiting() === 0",
                               timeout=600_000)
        page.wait_for_function(watching.EVERY_SOURCE_RESOLVED, timeout=600_000)
        opened = time.time() - opening
        governed = served._composers.get(store.resolve())
        accounting = getattr(governed, "accounting", {})
        print(f"\nCold open at {len(to_publish) + len(committed)} committed "
              f"positions: {opened:.1f} s "
              f"(first derive {accounting.get('last_derive_ms', 0):.0f} ms, "
              f"{accounting.get('last_tiles_read', 0)} tiles read)")
        page.wait_for_timeout(3000)
        session.send("Page.startScreencast",
                     {"format": "png", "everyNthFrame": 1})
        page.wait_for_timeout(500)

        chooser = np.random.default_rng(11)
        seed = np.random.default_rng(23)
        half = asked.churn // 2
        landings = [one for one in boundary
                    if (one, 0) not in set(run._committed_units())][:half]
        victims = list(chooser.choice(sorted(interior), size=half,
                                      replace=False))
        plan = [("land", one) for one in landings]
        plan += [("replace", one) for one in victims]
        chooser.shuffle(plan)

        print(f"\nThe watched churn: {len(plan)} changes "
              f"({half} boundary landings, {half} interior replacements)\n")
        print(f"  {'change':>22} {'writer':>8} {'derive':>8} {'read':>6} "
              f"{'visible':>9}")
        rows = []
        for kind, position_id in plan:
            wrote = time.perf_counter()
            if kind == "land":
                run.publish(position_id)
            else:
                brighter = seed.integers(*BRIGHT, (1, FRAME, FRAME)
                                         ).astype("uint16")
                brighter[:, ::8, :] = 65535  # striped, so the eye can tell
                run.replace_a_position(position_id, brighter)
            writer_ms = (time.perf_counter() - wrote) * 1000
            frames_before = len(frames)
            landed = time.time()
            announce(position_id)
            # The next painted frame after the announce is the visible moment;
            # wait for one, briefly.
            deadline = time.time() + 5
            while len(frames) == frames_before and time.time() < deadline:
                page.wait_for_timeout(20)
            visible_ms = ((frames[frames_before][0] - landed) * 1000
                          if len(frames) > frames_before else float("nan"))
            accounting = dict(getattr(governed, "accounting", {}))
            rows.append({"kind": kind, "writer_ms": writer_ms,
                         "derive_ms": accounting.get("last_derive_ms", 0),
                         "read": accounting.get("last_tiles_read", 0),
                         "visible_ms": visible_ms})
            print(f"  {kind:>7} {position_id:>13} {writer_ms:>6.0f}ms "
                  f"{rows[-1]['derive_ms']:>6.0f}ms {rows[-1]['read']:>6} "
                  f"{visible_ms:>7.0f}ms", flush=True)

        page.wait_for_timeout(2000)
        session.send("Page.stopScreencast")

        print(f"\n{len(frames)} frames recorded. Looking for transients...")
        from PIL import Image
        grey = [(when, np.asarray(Image.open(io.BytesIO(body)).convert("L"),
                                  dtype=np.int16))
                for when, body in frames]
        events = 0
        for index in range(1, len(grey) - 1):
            was, now, after = grey[index - 1][1], grey[index][1], grey[index + 1][1]
            if was.shape != now.shape or now.shape != after.shape:
                continue
            dipped = (now < was - DIP) & (after > now + DIP)
            if int(dipped.sum()) >= ENOUGH:
                events += 1
                rows_, cols = np.nonzero(dipped)
                print(f"  TRANSIENT at frame {index}: {int(dipped.sum())} px, "
                      f"box x{cols.min()}-{cols.max()} y{rows_.min()}-{rows_.max()}")
        if events == 0:
            print("  none — zero transients at this scale")

        middle = lambda values: sorted(values)[len(values) // 2]
        derives = [one["derive_ms"] for one in rows]
        visibles = [one["visible_ms"] for one in rows
                    if one["visible_ms"] == one["visible_ms"]]
        writers = [one["writer_ms"] for one in rows]
        print(f"\nAt {across * across} planned / "
              f"~{len(to_publish) + len(committed)} committed positions:")
        print(f"  derive per commit: middling {middle(derives):.0f} ms "
              f"(reading {rows[-1]['read']} tiles each time — the linear "
              "term this measures)")
        if visibles:
            print(f"  landing to visible: middling {middle(visibles):.0f} ms")
        print(f"  writer per change: middling {middle(writers):.0f} ms "
              "(excluded from the viewer's verdict)")
        print(f"  transients: {events}")
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)
        browser.close()
        started.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
