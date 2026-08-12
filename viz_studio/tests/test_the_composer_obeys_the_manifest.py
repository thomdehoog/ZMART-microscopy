"""The composer serving a governed run shows the manifest's truth and nothing else.

``viz_studio/building`` was written for transfers: finished folders where every
tile on disk is real and nothing changes. A live ZMART run breaks both
assumptions on purpose — positions are written *before* they are published, a
position can be replaced by a later generation, and the record of what may be
shown is the run's manifest ("files existing means nothing; this record means
everything"). These are the tests that hold the composer to that record.

Everything here runs against a real governed run made by ``zmart_live``'s own
writing machinery — the same ``LivePublisher`` the gateway tests use — because
a mock manifest would let the composer agree with a simplification instead of
with the thing that rules the microscope.

The review that ordered this work is
``building/REVIEW_the_composer_meets_the_live_role.md``; findings one, two,
three and five are the contracts below. The independent review of the *plan*
is ``building/REVIEW_PROMPT_change_zero_build_plan.md``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

VIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(VIZ / "building"))
sys.path.insert(0, str(VIZ.parent))

from zmart_live.model import GridCell  # noqa: E402
from zmart_live.profiles import plan_the_writing  # noqa: E402
from zmart_live.tests.test_coordinator import FRAME, some_specimen  # noqa: E402

from check import decode  # noqa: E402
from governed import GovernedRun  # noqa: E402

# Small pieces, so the picture is several pieces across and posA-only ground,
# shared ground, and posB-only ground all fall in different pieces.
PIECE = 256


def a_governed_run(folder: Path, *, timepoints: int = 1):
    """A real manifest-governed run of two positions, side by side.

    The same shape the gateway tests use: ``posA`` at the origin, ``posB`` to
    its right, overlapping by the profile's own band. Values are chosen per
    test so that whose pixels ended up on screen is readable from the bytes.
    """
    from zmart_live.coordinator import LivePublisher

    profile, _ = plan_the_writing("overview", frame=FRAME, z_planes=1)
    return LivePublisher(
        folder,
        profile,
        run_id="composer-gate-run",
        cells={GridCell(0, 0): "posA", GridCell(0, 1): "posB"},
        timepoints=timepoints,
    )


def written_but_not_published(run, position_id: str, value: int) -> None:
    """Every step of a publication except the commit — the gateway tests' recipe."""
    run.write_a_position(position_id, some_specimen(value))
    units = frozenset(run._committed_units()) | {(position_id, 0)}
    run.write_the_link_map(units)
    run.write_the_view()
    run.write_the_layout()


def pixels_of(composer, level: int, plane: int, row: int, column: int) -> np.ndarray:
    """One served piece, decoded the way the browser's engine decodes it.

    ``None`` from the composer — ground served as absent — comes back as the
    fill value, exactly as the engine paints it.
    """
    body = composer.bytes_for(level, plane, row, column)
    return decode(body, composer.piece, str(composer.mosaic.dtype),
                  composer.mosaic.axes)


def the_columns_of(run) -> tuple[int, int, int]:
    """Which piece column is posA-only, which is shared, and which is posB-only.

    Worked out from the run's own layout rather than assumed, so a profile
    whose overlap band changes width moves the test with it.
    """
    b_starts = int(run.layout.placement("posB").origin["x"])
    a_ends = FRAME  # posA sits at the origin and is one frame wide
    assert b_starts < a_ends, "the fixture's positions are expected to overlap"
    shared_x = (b_starts + a_ends) // 2
    _, width = run._mosaic_extent()
    return 0, shared_x // PIECE, (width - 1) // PIECE


# -- finding 1: the gate ---------------------------------------------------------


def test_a_position_written_but_not_committed_is_not_drawn(tmp_path):
    """Uncommitted pixels stay invisible however finished they look on disk."""
    run = a_governed_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))
    written_but_not_published(run, "posB", 4242)

    composer = GovernedRun(run.folder, piece=PIECE).composer()
    a_only, _, b_only = the_columns_of(run)

    assert 700 in pixels_of(composer, 0, 0, 0, a_only)
    ground_of_b = composer.bytes_for(0, 0, 0, b_only)
    assert ground_of_b is None, (
        "a piece covering only the uncommitted position must be served as "
        "absent, not built from pixels the manifest has not published"
    )


def test_publishing_makes_the_same_ground_appear(tmp_path):
    """The commit, and nothing else, is what turns pixels visible."""
    run = a_governed_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))
    written_but_not_published(run, "posB", 4242)

    governed = GovernedRun(run.folder, piece=PIECE)
    _, _, b_only = the_columns_of(run)
    assert governed.composer().bytes_for(0, 0, 0, b_only) is None

    run.publish("posB")
    assert 4242 in pixels_of(governed.composer(), 0, 0, 0, b_only), (
        "the same governed run, asked after the commit, must serve the "
        "newly published ground without any restart or forget call"
    )


def test_a_replaced_position_is_drawn_once_and_with_the_later_generation(tmp_path):
    """Both generations sit on disk; only the replacement may reach the screen."""
    run = a_governed_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))
    run.replace_a_position("posA", some_specimen(2200))

    composer = GovernedRun(run.folder, piece=PIECE).composer()
    a_only, _, _ = the_columns_of(run)
    seen = set(np.unique(pixels_of(composer, 0, 0, 0, a_only)))

    assert 2200 in seen
    assert 700 not in seen, (
        "the superseded generation was laid into the piece — the glob is "
        "seeing both stores, or the order lays the older on top"
    )


def test_a_half_written_arrival_does_not_take_down_serving(tmp_path):
    """One in-flight position must cost nothing but its own absence."""
    run = a_governed_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))

    # A position mid-arrival: the folder exists, its description does not yet.
    wreck = run.folder / "positions" / "posEvil.ome.zarr"
    wreck.mkdir()
    (wreck / "zarr.json").write_text("{ this is not json", encoding="utf-8")

    composer = GovernedRun(run.folder, piece=PIECE).composer()
    a_only, _, _ = the_columns_of(run)
    assert 700 in pixels_of(composer, 0, 0, 0, a_only), (
        "committed ground must keep serving while an uncommitted arrival is "
        "half-written beside it"
    )


def test_an_empty_run_is_a_valid_empty_picture(tmp_path):
    """Zero commits is the first moment of every experiment, not an error."""
    run = a_governed_run(tmp_path)
    run.write_the_view()
    run.write_the_layout()

    governed = GovernedRun(run.folder, piece=PIECE)
    composer = governed.composer()

    height_now, width_now = run._mosaic_extent()
    assert composer.mosaic.shape(0)[1:] == (height_now, width_now), (
        "the picture's frame comes from the layout, so it exists before any "
        "position does"
    )
    assert composer.bytes_for(0, 0, 0, 0) is None


# -- finding 5: the frame comes from the layout ----------------------------------


def test_the_frame_is_the_layouts_whether_or_not_every_position_arrived(tmp_path):
    """One committed corner must not shrink the world."""
    run = a_governed_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))

    partial = GovernedRun(run.folder, piece=PIECE).composer().mosaic.shape(0)

    run.write_and_publish("posB", some_specimen(1100))
    complete = GovernedRun(run.folder, piece=PIECE).composer().mosaic.shape(0)

    assert partial == complete, (
        "the declared shape moved when a position arrived — the frame is "
        "being derived from the tiles present rather than from the layout"
    )


# -- finding 2: commit order, later on top ---------------------------------------


def test_shared_ground_shows_the_later_commit_whatever_the_names_say(tmp_path):
    """posB commits first here, so posA — the later commit — owns the overlap.

    Alphabetical order and commit order disagree on purpose: a composer that
    sorts by name draws posB on top and this fails.
    """
    run = a_governed_run(tmp_path)
    run.write_and_publish("posB", some_specimen(1100))
    run.write_and_publish("posA", some_specimen(700))

    composer = GovernedRun(run.folder, piece=PIECE).composer()
    _, shared, _ = the_columns_of(run)
    piece = pixels_of(composer, 0, 0, 0, shared)

    b_starts = int(run.layout.placement("posB").origin["x"])
    inside_the_overlap = ((b_starts + FRAME) // 2) % PIECE
    assert piece[..., inside_the_overlap].max() == 700, (
        "ground both positions imaged must show the later commit's pixels"
    )
