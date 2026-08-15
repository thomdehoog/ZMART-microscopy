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

``burst``
    the adding ceiling: how fast can new positions land when the writer is
    taken out of the watched loop. The fixture wrote every position's pixels
    at creation, so a landing needs only its commit; the burst commits and
    announces boundary positions back to back with no pacing and reports the
    rate the pipeline took them at, what the derive cost under fire, how long
    the picture took to absorb them all, and the recorder's transient count —
    the same gate as the churn, because speed that flickers is not speed.
    The writer's own cadence (seconds per position — the microscope's role)
    is measured by the churn, never here.

Run it with::

    python measure_a_governed_run_at_scale.py --across 32 --churn 40
    python measure_a_governed_run_at_scale.py --across 32 --churn 40 --headed
    python measure_a_governed_run_at_scale.py --across 32 --burst 40 --headed
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

_BUILDING = Path(__file__).resolve().parent
_VIZ = _BUILDING.parent
sys.path.insert(0, str(_BUILDING))
sys.path.insert(0, str(_VIZ))
sys.path.insert(0, str(_VIZ / "backend"))
sys.path.insert(0, str(_VIZ / "tests"))
# The repository root as well, so zmart_live imports on a machine where the
# package was never installed -- the harness should run from a fresh clone.
sys.path.insert(0, str(_VIZ.parent))

import numpy as np

from server import make_server  # noqa: E402

import measure_the_frame_rate_of_a_linked_view as watching  # noqa: E402
import served  # noqa: E402
from declare import declare_a_governed_picture  # noqa: E402

from zmart_live.coordinator import LivePublisher  # noqa: E402
from zmart_live.model import CommitEvent, GridCell  # noqa: E402
from zmart_live.profiles import plan_the_writing  # noqa: E402


def fast_publish(run: LivePublisher, position_id: str) -> None:
    """Append one position's commit straight to the manifest, for fixtures.

    The real writer spends ~2.2 s per publish at nine hundred committed
    positions — its own super-linearity, measured and owned separately —
    which prices a 6,400-position fixture at hours of wall clock for work
    the serving measurements do not need. This appends the commit event
    directly, the pattern the browser fixture `growing_run.py` sanctions:
    the readiness flags are claimed rather than earned, which is honest
    exactly here, because the fixture wrote every pixel and record itself a
    moment ago and there is nothing else to check. The WATCHED churn never
    uses this — its writer column measures the real thing.
    """
    run.manifest.publish(CommitEvent(
        revision=run.manifest.next_revision(),
        event_type="position_committed",
        position_id=position_id,
        run_id=run.run_id,
        acquisition_type=run.profile.acquisition_type,
        acquisition_profile_id=run.profile.profile_id,
        scene_layout_revision=run.layout.revision,
        link_revision=1,
        channels=tuple(run.channels),
        levels=tuple(range(len(run.profile.levels))),
        pyramids_ready=True,
        links_ready=True,
        view_ready=True,
        validated=True,
    ))

FRAME = 384
BRIGHT = (46000, 62000)

# Where the fixtures live between runs. Deliberately durable: the writer's
# work is minutes per thousand positions and the measurements must be
# repeatable without paying it again.
FIXTURES = Path(r"D:\zmart-scale-runs")

DIP = 45
ENOUGH = 200


def the_experiment() -> Path:
    """The experiment folder every rung lives in, shaped as the contract draws.

    One ladder is one experiment: config/ carries the canvas the controller
    would have set before anything ran, and each survey size is one
    acquisition inside acquisitions/. The fixtures exercise the real file
    structure, so any drift from the contract breaks the gates first.
    """
    experiment = FIXTURES / "experiment"
    config = experiment / "config"
    if not (config / "canvas.json").is_file():
        config.mkdir(parents=True, exist_ok=True)
        (config / "canvas.json").write_text(json.dumps({
            "units": "micrometer",
            "origin": [0.0, 0.0],
            "orientation": "yx",
            "note": "the one coordinate frame every acquisition happens in",
        }, indent=2) + "\n")
    return experiment


def the_run(across: int, seed_value: int = 7) -> tuple[LivePublisher, list[str]]:
    """The fixture: an ``across``-squared survey, written once, reused after.

    Position pixels are written for every planned cell; nothing is published
    here — publication is the measurement, so it belongs to the caller.
    Each survey size is one acquisition folder inside the ladder's one
    experiment, exactly the tree the contract draws.
    """
    folder = the_experiment() / "acquisitions" / f"survey-{across}"
    profile, _ = plan_the_writing("overview", frame=FRAME, z_planes=1)
    # Name fields sized to the grid, or a three-digit row bleeds into the
    # column: at 113 across, "p10100" reads as row 10 column 100 AND row 101
    # column 0, which the topology check rightly refuses.
    width = len(str(across - 1))
    cells = {GridCell(row, column): f"p{row:0{width}d}{column:0{width}d}"
             for row in range(across) for column in range(across)}
    # The run defers its linked view to the end of the run -- the one live
    # path: mid-run the picture is served from the positions' own stores,
    # and the plain-file view for outside tools is written once, when the
    # run finishes. The churn's writer column measures exactly this writer.
    # The acquisition folder IS the publisher's folder: the run writes its
    # data/ and views/ directly inside it, with no extra nesting level.
    run = LivePublisher(folder, profile, run_id=f"scale{across}",
                        cells=cells, timepoints=1, linked_view="at_run_end")
    order = [f"p{row:0{width}d}{column:0{width}d}"
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
    parsing.add_argument("--burst", type=int, default=0,
                         help="instead of the churn, land this many "
                              "pre-written boundary positions back to back "
                              "with no pacing — the adding ceiling")
    parsing.add_argument("--bake", action="store_true",
                         help="declare the picture with the per-commit bake, "
                              "so cold opens read files and every commit "
                              "patches its footprint — the mode the unbaked "
                              "columns are compared against")
    parsing.add_argument("--as-declared", action="store_true",
                         help="serve the picture exactly as it stands, "
                              "skipping the declare — for repeat runs and "
                              "demonstrations, where re-baking a big survey "
                              "costs minutes to restate what is already "
                              "there")
    parsing.add_argument("--warm-first", action="store_true",
                         help="let the composer finish warming its coarse "
                              "slabs before the churn or burst begins — the "
                              "rhythm a real run has, where the picture is "
                              "open long before ground arrives. Without it "
                              "the first changes race the warmer and pay "
                              "cold-region composes on camera.")
    parsing.add_argument("--headed", action="store_true",
                         help="open a visible window")
    parsing.add_argument("--fixtures", default=None,
                         help="where the durable fixtures live; defaults to "
                              "the microscope machine's folder above, so on "
                              "any other machine pass a folder with room "
                              "for the survey being measured")
    asked = parsing.parse_args()
    if asked.fixtures:
        global FIXTURES
        FIXTURES = Path(asked.fixtures)
    across = asked.across

    run, order = the_run(across)

    # The interior is pre-published in bulk -- the survey the operator has
    # already imaged. The outermost ring stays dark: it is the boundary the
    # run will grow into while being watched.
    width = len(str(across - 1))
    boundary = [one for one in order
                if 0 in (int(one[1:1 + width]), int(one[1 + width:]))
                or across - 1 in (int(one[1:1 + width]), int(one[1 + width:]))]
    interior = [one for one in order if one not in set(boundary)]
    committed = set(run._committed_units())
    to_publish = [one for one in interior if (one, 0) not in committed]
    if to_publish:
        print(f"Bulk-publishing {len(to_publish)} interior positions "
              "(fixture fast path — see fast_publish; the churn's writer "
              "column measures the real writer)...")
        began = time.time()
        for number, position_id in enumerate(to_publish):
            fast_publish(run, position_id)
            if (number + 1) % 500 == 0:
                print(f"  {number + 1} published "
                      f"({(time.time() - began):.0f} s)", flush=True)
        print(f"  published in {time.time() - began:.0f} s")

    # The declared picture is a real view of the acquisition, in the
    # acquisition's own views/ folder -- the shape the contract draws.
    shown = run.folder / "views" / "shown"
    if asked.as_declared:
        store = shown / "live.ome.zarr"
        print(f"serving {store} as it stands (--as-declared)")
    else:
        if asked.bake:
            print("Declaring with the per-commit bake (initial bake is "
                  "O(survey), once)...")
        began_declaring = time.time()
        store = declare_a_governed_picture(shown, run.folder, name="live",
                                           bake=asked.bake)
        print(f"declared {'baked' if asked.bake else 'unbaked'} in "
              f"{time.time() - began_declaring:.1f} s")

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

    # The picture may declare MORE levels than the profile: a baked picture
    # extends the pyramid above the tiles, the engine shows those levels at
    # overview zoom, and an announce that stops at the profile's levels names
    # nothing the engine holds -- the browser then refetches nothing and the
    # screen never changes, measured as nan on every baked churn row.
    pictured_levels = len(json.loads((store / "zarr.json").read_text(
        encoding="utf-8"))["attributes"]["ome"]["multiscales"][0]["datasets"])

    def the_dirty_pieces_of(position_id: str) -> dict:
        piece = 512
        origin = run.layout.placement(position_id).origin
        y, x = int(origin.get("y", 0)), int(origin.get("x", 0))
        profile = run.profile
        dirty = {}
        for number in range(pictured_levels):
            deepest = min(number, len(profile.levels) - 1)
            rung = profile.level(deepest)
            extended = 2 ** (number - deepest)
            down_y = int(rung.downsampling.get("y", 1)) * extended
            down_x = int(rung.downsampling.get("x", 1)) * extended
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
        # One piece asked for outright, so the governed composer has
        # certainly derived before its accounting is read -- the engine's own
        # first requests race this moment.
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/data/0/{store.name}/3/c/0/0/0",
                    timeout=120) as answer:
                answer.read()
        except urllib.error.HTTPError:
            pass  # absent is an ordinary answer; the derive still happened
        remembered = served._composers.get(store.resolve())
        governed = remembered[1] if remembered is not None else None
        accounting = getattr(governed, "accounting", {})
        print(f"\nCold open at {len(to_publish) + len(committed)} committed "
              f"positions: {opened:.1f} s "
              f"(derive {accounting.get('last_derive_ms', 0):.0f} ms, "
              f"{accounting.get('last_tiles_read', 0)} tiles read; "
              f"held composers {len(served._composers)})")
        if asked.warm_first and governed is not None:
            warming = time.time()
            while (time.time() - warming < 300
                   and not governed.composer().coarse_levels_are_warm):
                page.wait_for_timeout(500)
            print(f"coarse slabs warm {time.time() - warming:.1f} s after "
                  "the open — the head start a real run's rhythm gives")
        session.send("Page.startScreencast",
                     {"format": "png", "everyNthFrame": 1})
        # Measurement begins only once the canvas has been QUIET for a
        # second -- a check, not a guessed pause. A change's visible moment
        # is "the first frame painted after its commit", so churning while
        # the opening screenful still paints would credit loading frames to
        # the first changes and fake impossibly FAST numbers; the quiet
        # requirement is what keeps the clock honest, and it costs exactly
        # as long as the picture actually needs.
        settling = time.time()
        while time.time() - settling < 30:
            page.wait_for_timeout(250)
            if not frames or time.time() - frames[-1][0] >= 1.0:
                break

        rows = []
        burst_took = burst_landed = 0.0
        derives_before = 0
        if asked.burst:
            dark = [one for one in boundary
                    if (one, 0) not in set(run._committed_units())]
            landing = dark[:asked.burst]
            derives_before = int(dict(getattr(governed, "accounting", {})
                                      ).get("derives", 0))
            print(f"\nThe burst: {len(landing)} pre-written boundary "
                  "positions, committed back to back with no pacing")
            burst_landed = len(landing)
            # Brought to front, because a backgrounded window is throttled to
            # no painting at all -- the refreshes flow, the screen never
            # changes, and the recorder counts one frame. The screenshots
            # bracket the burst so "did the picture change" has an answer on
            # disk even when nobody was watching the window.
            page.bring_to_front()
            # A burst against a BLACK canvas measures nothing anyone can see:
            # at survey scale the unbaked first screenful takes many seconds
            # to build, and a run of 96 landings was watched happening on a
            # picture that had not arrived yet -- screenshots 0 px apart, an
            # operator seeing no tiles. So wait for ground on the canvas
            # first, and report the wait: it is the unbaked cold look at this
            # rung, a number this campaign wants anyway.
            from PIL import Image
            settling = time.time()
            while True:
                shot = np.asarray(Image.open(io.BytesIO(page.screenshot()))
                                  .convert("L"), dtype=np.int16)
                if int((shot[:, :640] > 100).sum()) > 2000:
                    print(f"  ground on screen {time.time() - settling:.1f} s "
                          "after the derive -- the unbaked cold look, paid "
                          "before the burst begins")
                    break
                if time.time() - settling > 180:
                    print("  no ground on screen after 180 s -- bursting "
                          "against a dark canvas, which the screenshots "
                          "will say")
                    break
                page.wait_for_timeout(1000)
            page.screenshot(path=str(FIXTURES / f"gov{across}x{across}"
                                     / "burst_before.png"))
            first = time.time()
            for position_id in landing:
                fast_publish(run, position_id)
                announce(position_id)
            burst_took = time.time() - first
            burst_first_commit = first
            # Wait for the SCREEN to change, not for a fixed pause: at the
            # top rung the patch of a burst's coarse regions takes ~5 s, and
            # a four-second wait photographed the picture right before the
            # tiles painted -- "0 px, DID NOT change" on a burst that had
            # landed perfectly. The waiting watches the screencast frames
            # already streaming, never page.screenshot in a loop: looped
            # screenshots FLASH a headed window -- the 2026-08-12 rule,
            # re-learned here as five phantom transients on a clean burst.
            from PIL import Image as _Image
            settled_before = np.asarray(
                _Image.open(FIXTURES / f"gov{across}x{across}"
                            / "burst_before.png").convert("L"),
                dtype=np.int16)
            absorbing = time.time()
            while time.time() - absorbing < 60:
                page.wait_for_timeout(1000)
                later = [body for when, body in frames if when > first]
                if not later:
                    continue
                shot = np.asarray(_Image.open(io.BytesIO(later[-1]))
                                  .convert("L"), dtype=np.int16)
                if (shot.shape == settled_before.shape
                        and int((np.abs(shot - settled_before) > 20).sum())
                        >= 50):
                    while (frames
                           and time.time() - frames[-1][0] < 1.0
                           and time.time() - absorbing < 60):
                        page.wait_for_timeout(250)
                    break
            page.screenshot(path=str(FIXTURES / f"gov{across}x{across}"
                                     / "burst_after.png"))
            session.send("Page.stopScreencast")
        else:
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
            for kind, position_id in plan:
                wrote = time.perf_counter()
                if kind == "land":
                    # The whole landing sequence is one publish: the run
                    # defers its linked view to the end of the run, so a new
                    # position owes the shared records nothing mid-run beyond
                    # the arrangement (recorded once, unchanged thereafter).
                    run.publish(position_id)
                else:
                    brighter = seed.integers(*BRIGHT, (1, FRAME, FRAME)
                                             ).astype("uint16")
                    brighter[:, ::8, :] = 65535  # striped, for the eye
                    run.replace_a_position(position_id, brighter)
                writer_ms = (time.perf_counter() - wrote) * 1000
                landed = time.time()
                announce(position_id)
                # The first frame PAINTED after the announce is the visible
                # moment -- matched by the frame's own timestamp, not by list
                # position, because the screencast delivers with a lag.
                visible_ms = float("nan")
                deadline = time.time() + 5
                while time.time() < deadline:
                    later = [when for when, _ in frames if when > landed]
                    if later:
                        visible_ms = (later[0] - landed) * 1000
                        break
                    page.wait_for_timeout(20)
                accounting = dict(getattr(governed, "accounting", {}))
                rows.append({"kind": kind, "writer_ms": writer_ms,
                             "derive_ms": accounting.get("last_derive_ms", 0),
                             "read": accounting.get("last_tiles_read", 0),
                             "visible_ms": visible_ms})
                print(f"  {kind:>7} {position_id:>13} {writer_ms:>6.0f}ms "
                      f"{rows[-1]['derive_ms']:>6.0f}ms {rows[-1]['read']:>6} "
                      f"{visible_ms:>7.0f}ms", flush=True)

            # The recorder stops once the canvas has been quiet for a
            # second, so the last change's frames are in -- a check, like
            # every other wait here, never a guessed pause.
            trailing = time.time()
            while (time.time() - trailing < 30
                   and frames and time.time() - frames[-1][0] < 1.0):
                page.wait_for_timeout(250)
            session.send("Page.stopScreencast")

            # The deferred cost, paid once where nobody is waiting: the
            # linked plain-file view for outside tools, written at run end.
            finishing = time.perf_counter()
            run.finish_the_run()
            print(f"\nfinish_the_run (the linked view, written once): "
                  f"{time.perf_counter() - finishing:.1f} s")

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

        print(f"\nAt {across * across} planned / "
              f"~{len(to_publish) + len(committed)} committed positions:")
        if asked.burst:
            accounting = dict(getattr(governed, "accounting", {}))
            changing = [index for index in range(1, len(grey))
                        if grey[index][1].shape == grey[index - 1][1].shape
                        and int((np.abs(grey[index][1] - grey[index - 1][1])
                                 > 20).sum()) >= 50]
            if burst_landed and burst_took > 0:
                print(f"  committed: {burst_landed:.0f} landings in "
                      f"{burst_took:.2f} s — "
                      f"{burst_landed / burst_took:.1f} adds a second "
                      "into the manifest")
                if changing:
                    absorbed = grey[changing[-1]][0] - burst_first_commit
                    print(f"  absorbed: the picture stopped changing "
                          f"{absorbed:.2f} s after the first commit")
                derives = accounting.get("derives", 0) - derives_before
                print(f"  derives under fire: {derives} "
                      f"(last {accounting.get('last_derive_ms', 0):.0f} ms, "
                      f"{accounting.get('last_tiles_read', 0)} tiles read)")
                from PIL import Image
                folder = FIXTURES / f"gov{across}x{across}"
                shots = [np.asarray(Image.open(folder / name).convert("L"),
                                    dtype=np.int16)
                         for name in ("burst_before.png", "burst_after.png")]
                if shots[0].shape == shots[1].shape:
                    moved = int((np.abs(shots[1] - shots[0]) > 20).sum())
                    print(f"  the screenshots disagree by {moved} px "
                          f"(saved beside the fixture) — "
                          f"{'the picture DID change' if moved >= 50 else 'the picture DID NOT change'}")
            else:
                print("  no dark boundary positions were left to land — "
                      "recreate the fixture or use a larger --across")
        else:
            middle = lambda values: sorted(values)[len(values) // 2]
            derives = [one["derive_ms"] for one in rows]
            visibles = [one["visible_ms"] for one in rows
                        if one["visible_ms"] == one["visible_ms"]]
            writers = [one["writer_ms"] for one in rows]
            print(f"  derive per commit: middling {middle(derives):.0f} ms "
                  f"(reading {rows[-1]['read']} tiles each time — the linear "
                  "term this measures)")
            if visibles:
                print(f"  landing to visible: middling "
                      f"{middle(visibles):.0f} ms")
            print(f"  writer per change: middling {middle(writers):.0f} ms "
                  "(excluded from the viewer's verdict)")
        print(f"  transients: {events}")
    finally:
        page.close()
        served.forget(store)  # stops the warmer before the server dies
        server.shutdown()
        thread.join(timeout=5)
        browser.close()
        started.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
