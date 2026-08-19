"""Two governed runs served by one process keep their own world frames.

A viewer process lives longer than one acquisition: the same script runs
again into a fresh folder, with the same run name, the same sealed profile
and a layout starting from the same revision number. The world frame's
remembered geometry used to key on exactly that triple -- (run_id, layout
revision, profile) -- so the second run read the FIRST run's origin and
extent: a 64-position survey served inside a 16-position frame, its outer
tiles composing negative windows, its pieces answering 503 for ever and
the warm thread dead (`FINDING_grown_slab_windows_race_the_warm.md`
records the night this was run to ground). The run's folder is the
identity that actually distinguishes them, so it is part of the key now.
"""

import sys
from pathlib import Path

import numpy as np

VIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(VIZ / "building"))
sys.path.insert(0, str(VIZ.parent))

from governed import GovernedRun  # noqa: E402

from zmart_live.coordinator import LivePublisher  # noqa: E402
from zmart_live.model import GridCell  # noqa: E402
from zmart_live.profiles import plan_the_writing  # noqa: E402

FRAME = 384


def _a_run(folder: Path, positions: int) -> LivePublisher:
    """A grown run named exactly like every other run this fixture makes."""
    across = int(round(positions ** 0.5))
    cells = {GridCell(*divmod(number, across)): f"p{number:04d}"
             for number in range(positions)}
    profile, _ = plan_the_writing("overview", frame=FRAME, z_planes=1,
                                  timepoints=8)
    run = LivePublisher(folder, profile, run_id="landing", cells=cells)
    frame = np.full((1, 1, FRAME, FRAME), 1200, "uint16")
    for name in sorted(cells.values()):
        run.write_and_publish(name, frame, timepoint=0)
    return run


def test_a_second_run_of_the_same_name_keeps_its_own_frame(tmp_path):
    small = _a_run(tmp_path / "A", 16)
    large = _a_run(tmp_path / "B", 64)

    first = GovernedRun(small.folder)
    second = GovernedRun(large.folder)
    try:
        # Deriving the small run first is what plants the remembered frame.
        first.composer().stop_warming()
        composer = second.composer()
        composer.stop_warming()
        for level in range(composer.mosaic.levels):
            shape = composer.mosaic.shape(level)
            for tile, at in composer.mosaic.placements(level):
                held = tile.copies[level].shape
                for axis in range(3):
                    assert at[axis] + held[axis] <= shape[axis], (
                        f"level {level}: {tile.name} reaches "
                        f"{at[axis] + held[axis]} along axis {axis}, past the "
                        f"frame's {shape[axis]} -- the second run is being "
                        "served inside the first run's remembered frame"
                    )
        # And the poisoned symptom itself: every coarse piece composes.
        level = composer.mosaic.levels - 1
        deep, down, across = composer.grid(level)
        for row in range(down):
            for column in range(across):
                composer.bytes_for(level, 0, row, column, 0, 0)
    finally:
        first.close()
        second.close()
