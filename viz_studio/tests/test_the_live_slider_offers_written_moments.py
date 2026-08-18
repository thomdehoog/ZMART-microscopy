"""The live T slider offers the written moments, and only those.

A live acquisition declares its whole time room before the frames exist
(the profile's generous ceiling), and the engine is handed that room in
the grown picture's own description. What the OPERATOR may steer to is a
different, smaller thing: the moments the record says are complete. This
gate holds the seam between the two:

- the slider ranges over the WRITTEN moments (from authoritative live
  state), never the declared room;
- the declared ceiling appears beside it as a plain number ("1 / 2 of 4"),
  so a young run reads as young rather than as finished;
- a landing GROWS the slider on the held page — no navigation, no reload;
- ground past the written moments serves as honest absence: even steered
  there by force (the console, not the slider), the screen shows black,
  never a neighbouring moment's specimen;
- and the operator's F5 pair holds at a written station.

Single-channel on purpose: the channel half of the grown contract has its
own gates in ``test_a_grown_picture_draws_in_the_browser``.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np

_VIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_VIZ / "building"))

from pixels import fraction_lit  # noqa: E402
from test_manifest_refresh_browser import (  # noqa: E402
    _open,
    _serving,
    _wait_for_picture,
    _wait_for_revision,
)

from zmart_live.coordinator import LivePublisher  # noqa: E402
from zmart_live.model import GridCell  # noqa: E402
from zmart_live.profiles import plan_the_writing  # noqa: E402
from zmart_live.tests.test_coordinator import FRAME  # noqa: E402

ROOM = 4  # declared moments; only some are ever written here


def a_timelapse(folder):
    profile, _ = plan_the_writing("overview", frame=FRAME, z_planes=1,
                                  timepoints=ROOM)
    return LivePublisher(
        folder, profile, run_id="slider-run",
        cells={GridCell(0, 0): "posA", GridCell(0, 1): "posB"},
    )


def a_moment(value: int) -> np.ndarray:
    return np.full((1, FRAME, FRAME), value, "uint16")


def _mean_brightness(page) -> float:
    from PIL import Image

    box = page.locator("canvas").first.bounding_box()
    shot = page.screenshot(clip=box)
    pixels = np.array(Image.open(io.BytesIO(shot)).convert("RGB"))
    return float(pixels.max(axis=2).mean())


def _settle(page) -> None:
    """Refresh flights drained AND the engine fully loaded — the storm
    census's rule: pixels are only comparable once nothing more is coming."""
    page.wait_for_function("() => window.zmartSourcesWaiting() === 0",
                           timeout=90_000)
    page.wait_for_function("""() => {
      for (const managed of window.zmartViewer.layerManager.managedLayers) {
        for (const rl of (managed.layer?.renderLayers || [])) {
          const p = rl.layerChunkProgressInfo;
          if (p && p.numVisibleChunksNeeded > p.numVisibleChunksAvailable)
            return false;
        }
      }
      return true;
    }""", timeout=90_000)
    page.wait_for_timeout(800)


def test_the_slider_ranges_over_written_moments_and_grows(
    browser, built_dist, tmp_path
):
    shots = tmp_path / "shots"
    shots.mkdir()
    run = a_timelapse(tmp_path)
    run.write_and_publish("posA", a_moment(800), timepoint=0)
    run.write_and_publish("posB", a_moment(800), timepoint=0)
    run.write_and_publish("posA", a_moment(2600), timepoint=1)
    run.write_and_publish("posB", a_moment(2600), timepoint=1)

    with _serving(built_dist, run) as address:
        page = browser.new_page(viewport={"width": 1200, "height": 900})
        try:
            _open(page, address, 4)
            _wait_for_picture(page)
            _settle(page)

            # The slider exists (two written moments IS a choice), offers
            # exactly those two, and says how much room was declared.
            slider = page.get_by_label("t position", exact=True)
            assert slider.count() == 1, "no T slider on a two-moment run"
            assert slider.get_attribute("max") == "1", (
                "the slider offers more than the two written moments -- the "
                "declared room leaked into the operator's control"
            )
            reading = page.get_by_label("t position value").text_content()
            assert "of 4" in reading, (
                f"the reading says {reading!r} -- the declared ceiling is "
                "not shown, so a young run reads as a finished one"
            )
            page.screenshot(path=str(shots / "1_two_written_of_four.png"))

            # Steering to the second written moment brightens by its stamp.
            dim = _mean_brightness(page)
            slider.fill("1")
            _settle(page)
            bright = _mean_brightness(page)
            page.screenshot(path=str(shots / "2_second_moment.png"))
            assert bright > dim + 20, (
                f"moment 1 shows {bright:.1f} against moment 0's {dim:.1f} "
                "-- the slider is not steering the pixels"
            )

            # Forced PAST the written ground (a console, not the slider):
            # the view is brought straight back to the nearest written
            # moment. Uncommitted ground is never shown as if it were a
            # moment — not even by force — and the slider never reads a
            # moment number over an empty screen. (What lies behind
            # unwritten ground is gated at the record level: the composer
            # serves it absent, and the wire shows 404s.)
            page.evaluate("""() => {
              const position = window.zmartViewer.navigationState.position;
              const names = position.coordinateSpace.value.names;
              const moved = Float32Array.from(position.value);
              moved[names.indexOf('t')] = 3;
              position.value = moved;
            }""")
            page.wait_for_function("""() => {
              const p = window.zmartViewer.navigationState.position;
              const i = p.coordinateSpace.value.names.indexOf('t');
              return Math.abs(p.value[i] - 1) <= 0.5;
            }""", timeout=10_000)
            _settle(page)
            page.screenshot(path=str(shots / "3_snapped_back_to_written.png"))
            assert fraction_lit(page) > 0.01, (
                "the view was brought back to a written moment but the "
                "screen stayed empty"
            )

            # A landing grows the slider on the held page, no reload.
            run.write_and_publish("posA", a_moment(4000), timepoint=2)
            run.write_and_publish("posB", a_moment(4000), timepoint=2)
            _wait_for_revision(page, 6)
            page.wait_for_function(
                """() => document.querySelector(
                     'input[aria-label="t position"]')?.max === '2'""",
                timeout=15_000,
            )
            reading = page.get_by_label("t position value").text_content()
            assert "of 4" in reading
            page.screenshot(path=str(shots / "4_grew_to_three.png"))

            # The F5 pair at a written station: reload agrees with the page.
            slider.fill("2")
            _settle(page)
            held = _mean_brightness(page)
            page.reload(wait_until="domcontentloaded")
            _wait_for_picture(page)
            _settle(page)
            page.get_by_label("t position", exact=True).fill("2")
            _settle(page)
            fresh = _mean_brightness(page)
            page.screenshot(path=str(shots / "5_after_f5.png"))
            assert abs(fresh - held) < 12, (
                f"the same written moment shows {held:.1f} held and "
                f"{fresh:.1f} after F5"
            )
        finally:
            page.close()
    print(f"screenshots kept at {shots}")
