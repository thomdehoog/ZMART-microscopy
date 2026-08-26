"""Measure a timepoint landing: commit to offered, and commit to followed.

The survey ladders measure a POSITION landing; this measures the other kind
of growth -- a run already showing all its positions gains a new MOMENT.
Two clocks matter to the operator watching the front:

- **offered**: from the commit to the slider offering the new moment;
- **followed**: from the commit to the view standing ON the new moment,
  which is the follow-the-front behaviour -- the frame that just landed is
  the frame on screen.

Both are timed on a held page, no reloads, across growing position counts,
because the cost of noticing a landing is dominated by re-reading what is
open, and that scales with positions rather than with moments.

Run it with::

    python zmart-viewer/app/picture/measure_a_timepoint_landing.py
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

VIZ = Path(__file__).resolve().parents[1]
HERE = VIZ / "app" / "picture"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(VIZ / "app" / "server"))
sys.path.insert(0, str(VIZ / "tests"))

FRAME = 384
ROOM = 8
RUNGS = (16, 64, 256)

ON_THE_MOMENT = """(wanted) => {
  const p = window.zmartViewer.navigationState.position;
  const names = p.coordinateSpace.value.names;
  const i = names.indexOf('t');
  if (i < 0) return false;
  const lower = p.coordinateSpace.value.bounds.lowerBounds[i];
  return Math.abs(p.value[i] - Math.ceil(lower) - wanted) <= 0.5;
}"""


def _one_rung(browser_kind, built, positions: int, keep: Path) -> dict:
    import tempfile
    import threading

    from server import make_server
    from test_manifest_refresh_browser import _open, _wait_for_picture

    from zmart_live.coordinator import LivePublisher
    from zmart_live.model import GridCell
    from zmart_live.profiles import plan_the_writing

    across = int(round(positions ** 0.5))
    cells = {GridCell(*divmod(number, across)): f"p{number:04d}"
             for number in range(positions)}
    profile, _ = plan_the_writing("overview", frame=FRAME, z_planes=1,
                                  timepoints=ROOM)
    with tempfile.TemporaryDirectory(dir=keep) as folder:
        run = LivePublisher(Path(folder) / "run", profile,
                            run_id="landing", cells=cells)
        frame = np.full((1, 1, FRAME, FRAME), 1200, "uint16")
        revision = 0
        for name in sorted(cells.values()):
            run.write_and_publish(name, frame, timepoint=0)
            revision += 1
        server = make_server(port=0, data_dir=run.folder, site_dir=built,
                             store="views/live/live.ome.zarr", live=True,
                             window=(0, 4095), allow_open=False)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        address = f"http://127.0.0.1:{server.server_address[1]}"
        page = browser_kind.new_page(viewport={"width": 1200, "height": 900})
        offered, followed = [], []
        try:
            _open(page, address, revision)
            _wait_for_picture(page)
            page.wait_for_timeout(1500)
            for moment in range(1, 4):
                # One position commits the new moment, the way a microscope
                # advances: the moment is offered as soon as any position
                # holds it.
                started = time.perf_counter()
                run.write_and_publish(sorted(cells.values())[moment],
                                      np.full_like(frame, 1200 + 700 * moment),
                                      timepoint=moment)
                page.wait_for_function(
                    f"""() => document.querySelector(
                        'input[aria-label="t position"]')?.max === '{moment}'""",
                    timeout=60_000)
                offered.append(time.perf_counter() - started)
                page.wait_for_function(ON_THE_MOMENT, arg=moment,
                                       timeout=60_000)
                followed.append(time.perf_counter() - started)
        finally:
            page.close()
            server.shutdown()
            thread.join(timeout=5)
    middle = sorted(offered)[len(offered) // 2]
    landed = sorted(followed)[len(followed) // 2]
    return {"positions": positions, "offered_s": middle, "followed_s": landed,
            "worst_followed_s": max(followed)}


def main() -> None:
    parsed = argparse.ArgumentParser(description=__doc__)
    parsed.add_argument("--rungs", type=int, nargs="*", default=list(RUNGS))
    parsed.add_argument("--fixtures", type=Path, default=Path("/tmp"))
    arguments = parsed.parse_args()

    from conftest import find_a_chromium
    from playwright.sync_api import sync_playwright

    built = VIZ / "app" / "page" / "dist"
    print("| positions | offered s | followed s | worst followed s |")
    print("|---|---|---|---|")
    with sync_playwright() as pw:
        args = ["--use-gl=angle", "--use-angle=swiftshader"]
        try:
            browser = pw.chromium.launch(args=args)
        except Exception:
            browser = pw.chromium.launch(executable_path=find_a_chromium(),
                                         args=args)
        # This loop is itself a regression gate: every rung reuses one
        # process AND one run name, which is exactly the shape that poisoned
        # the world frame's remembered geometry the first time this
        # instrument ran (FINDING_grown_slab_windows_race_the_warm, closed
        # 2026-08-19, pinned by test_two_runs_share_one_process).
        for positions in arguments.rungs:
            told = _one_rung(browser, built, positions, arguments.fixtures)
            print(f"| {told['positions']} | {told['offered_s']:.2f} |"
                  f" {told['followed_s']:.2f} |"
                  f" {told['worst_followed_s']:.2f} |", flush=True)
        browser.close()


if __name__ == "__main__":
    main()
