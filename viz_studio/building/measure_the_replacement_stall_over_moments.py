"""C-and-t stage 0: what a retake costs once a timelapse is long.

The c-and-t review's first finding: a replacement advances every published
moment (the record's set semantics), and the future per-moment bake would
patch that whole bill inside the derive lock while every piece request
queues behind it. The plan orders the number before the mitigation:
replace one position at m = 50, 200, 500 published moments and measure
time-to-first-answered-piece.

What this instrument measures TODAY, honestly split:

- **Measured**: the derive after the replacement — the fold over the full
  published record (the known O(positions × moments) term) plus snapshot
  assembly — and the first composed piece after it. This is the part of
  the stall that already ships. The picture is served unbaked here, so no
  file patching muddies the fold signal.
- **Projected, by arithmetic on measured numbers**: the synchronous bake
  bill IF the future per-moment patch ran inside the derive — today's
  measured whole-replace patch time at one moment (the ladder's replace
  column, ~330–380 ms in-container at this frame size) times m — against
  the lazy alternative the plan names, where only the viewed moment
  patches synchronously (one moment's patch, flat in m). The per-moment
  bake does not exist yet, so this column cannot be measured; the moment
  it is built, this script grows the measured column and the projection
  retires.

The fixture keeps one position with real pixels at moment 0 and appends
the later moments' commits straight to the manifest, the pattern
``fast_publish`` sanctions: the fold being measured reads the record, and
today's z-y-x composer never reads any moment but the first, so writing
500 moments of pixels would cost minutes to measure bookkeeping that
never touches them.

Run: python measure_the_replacement_stall_over_moments.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from tempfile import mkdtemp

_BUILDING = Path(__file__).resolve().parent
sys.path.insert(0, str(_BUILDING))

import numpy as np  # noqa: E402

from governed import GovernedRun  # noqa: E402

from zmart_live.coordinator import LivePublisher  # noqa: E402
from zmart_live.model import CommitEvent, GridCell  # noqa: E402
from zmart_live.profiles import plan_the_writing  # noqa: E402

FRAME = 384
RUNGS = (50, 200, 500)

# The ladder's measured whole-replace patch time at one moment, in-container
# at this frame size (MEASURED_ladder_to_4096_in_container.json) — the
# per-moment unit the projection multiplies.
PATCH_ONE_MOMENT_MS = (330.0, 380.0)


def a_moment_committed(run: LivePublisher, position_id: str,
                       moment: int) -> None:
    """One later moment's commit, appended straight to the record."""
    run.manifest.publish(CommitEvent(
        revision=run.manifest.next_revision(),
        event_type="timepoint_committed",
        position_id=position_id,
        timepoint=moment,
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


def main() -> int:
    folder = Path(mkdtemp(prefix="replacement-stall-"))
    profile, _ = plan_the_writing("overview", frame=FRAME, z_planes=1,
                                  timepoints=max(RUNGS))
    run = LivePublisher(
        folder / "experiment" / "acquisitions" / "timelapse",
        profile, run_id="stall-rung",
        cells={GridCell(0, 0): "pos00"},
        linked_view="at_run_end",
    )
    frame = np.full((1, FRAME, FRAME), 1200, "uint16")
    run.write_and_publish("pos00", frame, timepoint=0)

    opened = GovernedRun(run.folder)
    try:
        published = 1
        print(f"{'moments':>8} {'derive ms':>10} {'1st piece ms':>13} "
              f"{'swept':>7} {'projected sync bake':>22} {'lazy':>12}")
        for rung in RUNGS:
            for moment in range(published, rung):
                a_moment_committed(run, "pos00", moment)
            published = rung
            opened.composer()  # absorb the appends outside the measurement

            run.replace_a_position("pos00", frame + 100, timepoint=0)
            began = time.perf_counter()
            composer = opened.composer()
            derived = (time.perf_counter() - began) * 1000
            composer.bytes_for(0, 0, 0, 0)
            answered = (time.perf_counter() - began) * 1000
            swept = opened.accounting["last_snapshot_swept"]

            low, high = (rung * ms / 1000 for ms in PATCH_ONE_MOMENT_MS)
            print(f"{rung:>8} {derived:>10.1f} {answered:>13.1f} "
                  f"{swept:>7} {low:>10.1f}-{high:.1f} s "
                  f"{PATCH_ONE_MOMENT_MS[0] / 1000:>9.2f} s")
    finally:
        opened.close()
    print(f"(fixture at {folder})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
