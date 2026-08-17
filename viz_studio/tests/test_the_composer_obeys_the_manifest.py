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


def a_governed_run(folder: Path, *, timepoints: int = 1, third: bool = False):
    """A real manifest-governed run of positions, side by side.

    The same shape the gateway tests use: ``posA`` at the origin, ``posB`` to
    its right, overlapping by the profile's own band — and, when a test needs
    ground in a different piece row, ``posC`` below ``posA``. Values are
    chosen per test so that whose pixels ended up on screen is readable from
    the bytes.
    """
    from zmart_live.coordinator import LivePublisher

    profile, _ = plan_the_writing("overview", frame=FRAME, z_planes=1)
    cells = {GridCell(0, 0): "posA", GridCell(0, 1): "posB"}
    if third:
        # The layout demands a complete rectangle -- a hole inside the
        # footprint would make neighbours own the same specimen twice -- so
        # the third position brings a fourth that no test ever commits.
        cells[GridCell(1, 0)] = "posC"
        cells[GridCell(1, 1)] = "posD"
    return LivePublisher(
        folder,
        profile,
        run_id="composer-gate-run",
        cells=cells,
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
    wreck = run.folder / "data" / "survey.ome.zarr" / "posEvil"
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


# -- finding 3: committed ground fails closed ------------------------------------


def test_an_absent_chunk_of_committed_ground_is_refused_not_invented(tmp_path):
    """Damage to published pixels must be an error, never plausible zeros.

    Zarr silently answers the fill value for a chunk file that is missing, so
    without a check a damaged committed position is laid in as a rectangle of
    zeros — indistinguishable on screen from dark specimen, and laid *over*
    any published neighbour beneath it. The gateway's rule is quoted in the
    review: "a gap in it is damage to fail closed on."
    """
    from composer import MissingCommittedGround

    run = a_governed_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))

    level_zero = run.position_store("posA") / "0"
    chunks = [one for one in level_zero.rglob("*") if one.is_file()
              and one.name != "zarr.json"]
    assert chunks, "the fixture's position keeps its pixels somewhere"
    for one in chunks:
        one.unlink()

    composer = GovernedRun(run.folder, piece=PIECE).composer()
    a_only, _, _ = the_columns_of(run)
    with pytest.raises(MissingCommittedGround):
        composer.bytes_for(0, 0, 0, a_only)


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


# -- findings 4 and 6: warmth survives a commit; touched ground does not ---------


def test_a_commit_keeps_the_unchanged_ground_warm(tmp_path):
    """A position landing must not throw away every other position's work.

    This is the measured 2-changes-a-second ceiling stated as a contract: the
    demonstration of 2026-08-12 forgot the whole composer per landing, so
    every commit re-paid the entire visible screenful. Here posA's ground is
    built once, its chunk files are then deleted outright, and a commit lands
    elsewhere — if the fresh snapshot re-reads posA the read fails closed, so
    the only way this passes is the inherited warmth answering instead.
    """
    run = a_governed_run(tmp_path, third=True)
    run.write_and_publish("posA", some_specimen(700))
    run.write_and_publish("posB", some_specimen(1100))

    governed = GovernedRun(run.folder, piece=PIECE)
    a_only, _, _ = the_columns_of(run)
    before = governed.composer().bytes_for(0, 0, 0, a_only)
    assert before is not None and 700 in pixels_of(
        governed.composer(), 0, 0, 0, a_only)

    for chunk in (run.position_store("posA") / "0").rglob("*"):
        if chunk.is_file() and chunk.name != "zarr.json":
            chunk.unlink()
    run.write_and_publish("posC", some_specimen(1900))

    after = governed.composer().bytes_for(0, 0, 0, a_only)
    assert after == before, (
        "posC landed in a different piece row, so posA's built ground must "
        "come out of the inherited cache byte-for-byte — a fresh read would "
        "have failed closed on the deleted chunks"
    )


def test_ground_a_commit_touched_is_rebuilt_not_remembered(tmp_path):
    """The other half of inheritance: what changed must never be inherited.

    posA is replaced by a brighter generation; a snapshot that carried its
    old slab forward would keep showing the superseded pixels — the exact
    sabotage fault the plan names ("keep serving a cached piece across a
    commit that touched it").
    """
    run = a_governed_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))

    governed = GovernedRun(run.folder, piece=PIECE)
    a_only, _, _ = the_columns_of(run)
    assert 700 in pixels_of(governed.composer(), 0, 0, 0, a_only)

    run.replace_a_position("posA", some_specimen(2200))

    seen = set(np.unique(pixels_of(governed.composer(), 0, 0, 0, a_only)))
    assert 2200 in seen and 700 not in seen, (
        "ground the replacement touched answered from the old snapshot's "
        "cache"
    )


# -- the pyramid's levels agree where the specimen is -----------------------------


def test_the_levels_of_a_governed_picture_are_registered_to_each_other(tmp_path):
    """Averaged copies sit half a fine voxel along; the description must say so.

    The run's writer halves by AVERAGING 2x2 blocks, so the centre of a
    coarse voxel sits half a fine voxel down and right of the fine voxel it
    starts from — and a description that declares every level at the same
    translation draws each level a fixed diagonal apart. The operator saw
    that as a deterministic top-left twitch whenever the viewer showed a
    region at one level for a frame before another. Each level's declared
    translation must therefore step by (voxel_L - voxel_0) / 2 per axis.
    """
    import json

    run = a_governed_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))
    composer = GovernedRun(run.folder, piece=PIECE).composer()

    described = json.loads(composer.group_json())
    datasets = described["attributes"]["ome"]["multiscales"][0]["datasets"]
    base = datasets[0]["coordinateTransformations"]
    base_voxel = next(one for one in base if one["type"] == "scale")["scale"]
    base_at = next(one for one in base if one["type"] == "translation")["translation"]

    for dataset in datasets[1:]:
        transforms = dataset["coordinateTransformations"]
        voxel = next(one for one in transforms if one["type"] == "scale")["scale"]
        at = next(one for one in transforms
                  if one["type"] == "translation")["translation"]
        for axis in range(3):
            expected = base_at[axis] + (voxel[axis] - base_voxel[axis]) / 2
            assert at[axis] == pytest.approx(expected), (
                f"level {dataset['path']} axis {axis}: declared {at[axis]}, "
                f"but averaged content sits at {expected} — the levels are "
                "drawn a fixed diagonal apart and swap-twitch on screen"
            )


def test_a_transfers_decimated_levels_keep_their_own_registration(tmp_path):
    """The offset belongs to averaging; a decimated pyramid gets none.

    A mesoSPIM tile's coarse copy takes every second voxel, whose centre IS
    the fine voxel's centre — shifting those levels would misregister a
    transfer that is correct today (Thy1 was proven to the voxel).
    """
    import json

    import numpy as np
    import zarr

    from composer import Composer
    from mosaic import read_the_transfer

    transfer = tmp_path / "transfer"
    store = transfer / "tile.ome.zarr"
    datasets = []
    for level in range(2):
        shrink = 2 ** level
        array = zarr.create_array(
            store=str(store / str(level)), shape=(1, 64 // shrink, 64 // shrink),
            chunks=(1, 64 // shrink, 64 // shrink), dtype="uint16",
            zarr_format=3, dimension_names=["z", "y", "x"], overwrite=True)
        array[:] = 700
        datasets.append({
            "path": str(level),
            "coordinateTransformations": [
                {"type": "scale", "scale": [1.0, 0.5 * shrink, 0.5 * shrink]},
                {"type": "translation", "translation": [0.0, 0.0, 0.0]},
            ],
        })
    (store / "zarr.json").write_text(json.dumps({
        "attributes": {"ome": {"version": "0.5", "multiscales": [{
            "name": "tile", "type": "nearest",
            "axes": [{"name": "z", "type": "space", "unit": "micrometer"},
                     {"name": "y", "type": "space", "unit": "micrometer"},
                     {"name": "x", "type": "space", "unit": "micrometer"}],
            "datasets": datasets}]}},
        "zarr_format": 3, "node_type": "group"}), encoding="utf-8")

    composer = Composer(read_the_transfer(transfer), piece=32)
    described = json.loads(composer.group_json())
    held = described["attributes"]["ome"]["multiscales"][0]["datasets"]
    for dataset in held:
        at = next(one for one in dataset["coordinateTransformations"]
                  if one["type"] == "translation")["translation"]
        assert at == [0.0, 0.0, 0.0], (
            "a decimated pyramid's levels were shifted — that misregisters "
            "every transfer that is correct today"
        )
    assert np.array(composer.mosaic.corner_um).tolist() == [0.0, 0.0, 0.0]


# -- serving through the real door: served.py, gated per request -----------------


def test_a_governed_picture_is_served_with_the_gate_on(tmp_path):
    """The whole path a browser takes, with the manifest consulted per request.

    Declared once, served many: the picture's description is ordinary files,
    and every piece asked of :mod:`served` reflects the manifest as of that
    request — uncommitted ground absent, then present the moment its commit
    lands, with no forget call and no restart between the two answers.
    """
    import served
    from declare import declare_a_governed_picture

    run = a_governed_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))
    written_but_not_published(run, "posB", 4242)

    store = declare_a_governed_picture(run.folder / "views" / "shown", run.folder,
                                       name="live", piece=PIECE)
    try:
        a_only, _, b_only = the_columns_of(run)
        held = served.the_bytes_behind(store, f"0/c/0/0/{a_only}")
        assert held is not None and 700 in decode(held, PIECE, "uint16",
                                                  ("z", "y", "x"))
        assert served.the_bytes_behind(store, f"0/c/0/0/{b_only}") is None

        run.publish("posB")
        appeared = served.the_bytes_behind(store, f"0/c/0/0/{b_only}")
        assert appeared is not None and 4242 in decode(
            appeared, PIECE, "uint16", ("z", "y", "x"))
    finally:
        served.forget(store)


def test_a_picture_declared_over_a_runs_positions_is_refused(tmp_path):
    """The gate cannot be walked around by declaring a transfer inside a run.

    A declared picture reads its tiles straight through zarr, invisible to
    the gateway — so a declaration whose transfer is a governed run's own
    positions folder would serve withheld pixels past every fail-closed rule
    the run has. Such a picture is refused at serving time, not trusted at
    declaration time: ``built_from`` is file content, not an operator's
    decision, so the declaration here is written by hand exactly as an
    adversary would write it — the honest declare tool refuses these stores
    for its own reasons long before this rule is reached.
    """
    import json

    import served

    run = a_governed_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))
    written_but_not_published(run, "posB", 4242)

    store = tmp_path / "sneak" / "bypass.ome.zarr"
    store.mkdir(parents=True)
    (store / "zarr.json").write_text(json.dumps({
        "zarr_format": 3, "node_type": "group",
        "attributes": {"zmart": {
            "built_from": (run.folder / "positions").as_posix(),
            "piece": PIECE,
        }},
    }), encoding="utf-8")
    try:
        assert served.the_bytes_behind(store, "0/c/0/0/0") is None, (
            "a picture built over a governed run's positions folder must not "
            "serve a single piece — it reads past the manifest"
        )
    finally:
        served.forget(store)


def test_a_governed_picture_that_cannot_be_made_says_try_again(tmp_path):
    """Damage to the run is "try again shortly" at the wire, never absence.

    Two older mistakes are guarded against at once. One half-written arrival
    used to make every request repeat the whole transfer read forever -- so
    each ask here must still fail fast, without redoing expensive work or
    hanging a socket. And damage used to be answered as a plain absence,
    which the viewer believes for the rest of its session: a 404 says "there
    is nothing here, stop asking", and a run whose records were merely
    unreachable for a moment ended up as a hole only a reload repaired. So a
    picture that cannot be made raises TemporarilyUnanswerable instead --
    the server turns it into a 503, which the viewer's own HTTP layer
    retries -- and test_a_fault_is_not_absence.py holds the wire end of the
    same promise.
    """
    import served
    from declare import declare_a_governed_picture

    run = a_governed_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))
    store = declare_a_governed_picture(run.folder / "views" / "shown", run.folder,
                                       name="live", piece=PIECE)
    import shutil
    shutil.rmtree(run.folder / "views" / "live" / "metadata")

    try:
        with pytest.raises(served.TemporarilyUnanswerable):
            served.the_bytes_behind(store, "0/c/0/0/0")
        with pytest.raises(served.TemporarilyUnanswerable):
            served.the_bytes_behind(store, "0/c/0/0/0")
    finally:
        served.forget(store)


def test_a_run_of_several_channels_declares_with_its_colour_axis(tmp_path):
    """The old refusal's promise, kept the grown way: no colour is folded.

    A run recording several channels used to be refused at this door so its
    colours could never be silently collapsed. It now declares as a grown
    picture whose description carries the channel axis — and the promise
    the refusal kept is held by the combined-axes oracle, which pins every
    channel's pixels to that channel's own stamp.
    """
    import json

    from zmart_live.coordinator import LivePublisher

    from declare import declare_a_governed_picture

    profile, _ = plan_the_writing("overview", frame=FRAME, z_planes=1,
                                  channels=("488", "561"))
    run = LivePublisher(tmp_path, profile, run_id="two-colours",
                        cells={GridCell(0, 0): "posA", GridCell(0, 1): "posB"})
    store = declare_a_governed_picture(run.folder / "views" / "shown",
                                       run.folder, name="live")
    level = json.loads((store / "0" / "zarr.json").read_text())
    assert level["shape"][:2] == [1, 2], (
        "two declared channels must give the picture a two-channel axis"
    )


# -- a derive reads the pattern, not the survey -----------------------------------


def test_a_derive_reads_one_pattern_store_however_many_are_committed(tmp_path):
    """Deriving a snapshot must read one store from disk, ever, per session.

    Every position of a governed run is written by the same writer from the
    same sealed profile, so a tile's whole geometry — copies, shapes, chunks,
    voxel sizes — is the run's, and only its folder and its place on the
    stage are its own. Re-learning the run's geometry once per position was
    the whole of the one-time cold derive: 44 s at 12,769 positions against
    cold filesystem caches, 7.3 s warm, seven small file reads per position
    either way. The layout and one read store already say everything those
    reads would, so the cold derive reads the pattern and stamps the rest —
    and a landing or a replacement, whose geometry the pattern already gave,
    reads nothing at all.
    """
    run = a_governed_run(tmp_path, third=True)
    run.write_and_publish("posA", some_specimen(700))
    run.write_and_publish("posB", some_specimen(1100))

    governed = GovernedRun(run.folder, piece=PIECE)
    governed.composer()
    assert governed.accounting["last_tiles_read"] == 1, (
        "a cold derive read the survey instead of stamping it from one "
        "pattern store and the layout"
    )

    run.write_and_publish("posC", some_specimen(1900))
    composer = governed.composer()
    assert governed.accounting["last_tiles_read"] == 0, (
        "a landing has the pattern in hand already, so it must read no "
        "store at all"
    )
    a_only, _, _ = the_columns_of(run)
    assert 700 in pixels_of(composer, 0, 0, 0, a_only), (
        "the reused tiles must still serve their ground"
    )

    run.replace_a_position("posA", some_specimen(2200))
    composer = governed.composer()
    assert governed.accounting["last_tiles_read"] == 0
    assert 2200 in pixels_of(composer, 0, 0, 0, a_only)


def test_a_stamped_tile_says_exactly_what_the_walked_tile_would(tmp_path):
    """Stamping is only honest if it is indistinguishable from reading.

    Every field the old walk learned from a position's own files — where each
    copy lives, its shape, its chunking, its kind of number, its voxel size,
    its corner on the stage, its fixed outer indices — must come out of the
    stamp identical, including for a store that a replacement moved to a
    later generation. A single voxel of disagreement here is a tile drawn in
    the wrong place with nothing on screen to say so.
    """
    from governed import _a_committed_tile

    run = a_governed_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))
    run.write_and_publish("posB", some_specimen(1100))
    run.replace_a_position("posB", some_specimen(2200))

    governed = GovernedRun(run.folder, piece=PIECE)
    governed.composer()

    for position_id, generation in (("posA", 0), ("posB", 1)):
        stamped = governed._tiles[position_id]
        walked = _a_committed_tile(governed._the_store_of(position_id,
                                                          generation))
        assert stamped.name == walked.name
        assert stamped.store == walked.store
        assert stamped.axes == walked.axes
        assert stamped.turned == walked.turned
        assert len(stamped.copies) == len(walked.copies)
        for ours, theirs in zip(stamped.copies, walked.copies):
            assert ours.held_in == theirs.held_in
            assert ours.shape == theirs.shape
            assert ours.chunks == theirs.chunks
            assert ours.dtype == theirs.dtype
            assert ours.voxel_um == theirs.voxel_um
            assert ours.corner_um == theirs.corner_um
            assert ours.outer_shape == theirs.outer_shape
            assert ours.presence is not None, (
                "a stamped committed tile must still promise its blocks — "
                "absent chunks are damage to fail closed on, not fill"
            )


def test_a_commit_arriving_between_the_snapshots_two_reads_is_left_to_the_next(
        tmp_path):
    """A commit landing mid-derive must not crash the snapshot being made.

    The derive reads the manifest twice — the published units, then the draw
    order — and a commit can land between the two reads: the order then names
    a position the published set does not know. Found by the burst harness at
    25.9 adds a second (KeyError p3125, one coarse piece answered absent, one
    transient on the recorder); invisible at the writer's own cadence, where
    the window between the reads is never hit. The snapshot must simply not
    draw that position: its commit moved the fingerprint, so the very next
    ask derives again and draws it then.
    """
    run = a_governed_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))

    governed = GovernedRun(run.folder, piece=PIECE)
    real = governed._run

    class TornBetweenTheReads:
        """The gateway as the race sees it: order ahead of published."""

        def __getattr__(self, name):
            return getattr(real, name)

        def _positions_in_commit_order(self):
            return tuple(real._positions_in_commit_order()) + ("posB",)

    governed._run = TornBetweenTheReads()
    composer = governed.composer()
    a_only, _, b_only = the_columns_of(run)
    assert 700 in pixels_of(composer, 0, 0, 0, a_only), (
        "the settled ground must keep serving through the race"
    )
    assert composer.bytes_for(0, 0, 0, b_only) is None, (
        "the half-arrived commit belongs to the next snapshot, not this one"
    )


def test_a_pattern_whose_corner_disagrees_with_the_layout_is_refused(tmp_path):
    """The one store that is read must agree with the layout it stands in for.

    Stamping trusts the layout for every corner, so the read pattern is where
    that trust is checked: a store whose written translation is not the
    layout's placement means the writer and the layout have drifted apart,
    and every stamped corner would be quietly wrong. Refused loudly instead.
    """
    import json

    run = a_governed_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))

    described = run.position_store("posA") / "zarr.json"
    held = json.loads(described.read_text(encoding="utf-8"))
    for dataset in held["attributes"]["ome"]["multiscales"][0]["datasets"]:
        for transform in dataset["coordinateTransformations"]:
            if transform["type"] == "translation":
                transform["translation"] = [
                    number + 5.0 for number in transform["translation"]
                ]
    described.write_text(json.dumps(held), encoding="utf-8")

    with pytest.raises(ValueError, match="layout"):
        GovernedRun(run.folder, piece=PIECE).composer()


# -- the commit boundary: serving must not hold the writer's files hostage -------


def test_serving_holds_no_lasting_handle_on_committed_pixels(tmp_path):
    """The writer must be able to replace any chunk file at any moment.

    Windows refuses to replace a file somebody holds open, and replacing
    files is exactly what a commit does — reproduced 2026-08-12 as WinError 5
    stopping a landing mid-demonstration. So the composer's reads open, read,
    and let go: after a piece has been built, and while the composer that
    built it is alive and its zarr arrays are still open, the writer's own
    move — ``os.replace`` — must succeed against every chunk that was read.
    """
    import os

    run = a_governed_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))

    governed = GovernedRun(run.folder, piece=PIECE)
    composer = governed.composer()
    a_only, _, _ = the_columns_of(run)
    assert composer.bytes_for(0, 0, 0, a_only) is not None

    level_zero = run.position_store("posA") / "0"
    chunks = [one for one in level_zero.rglob("*") if one.is_file()
              and one.name != "zarr.json"]
    assert chunks, "the piece was built, so chunks were read"
    for chunk in chunks:
        newcomer = chunk.with_suffix(".arriving")
        newcomer.write_bytes(chunk.read_bytes())
        os.replace(newcomer, chunk)  # PermissionError here is the regression


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


def the_index_as_names(composer) -> dict:
    """Every level's piece index, as comparable names instead of objects.

    Two composers over the same state hold different tile objects, so the
    comparison is by what the index MEANS: which store answers for which
    piece, in which draw order.
    """
    told = {}
    for level in range(composer.mosaic.levels):
        index = composer._tiles_in_each_piece(level)
        told[level] = {
            piece: [(tile.name, tuple(at)) for tile, at in entries]
            for piece, entries in index.items()
        }
    return told


def test_the_inherited_piece_index_matches_one_built_fresh(tmp_path):
    """After a landing and a replacement, the carried index equals a rebuilt one.

    The index moves house between snapshots, patched only inside the change's
    footprint — see ``Composer.inherit_the_index``. Whether the surgery kept
    it true is checked the only way that means anything: against the index a
    fresh composer builds from scratch off the same manifest state, piece by
    piece and in the same draw order, since a piece whose entry lists the
    wrong store or the wrong order draws the wrong specimen without any
    error.
    """
    run = a_governed_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))
    governed = GovernedRun(tmp_path, piece=PIECE)
    held = governed.composer()
    for level in range(held.mosaic.levels):
        held._tiles_in_each_piece(level)

    run.write_and_publish("posB", some_specimen(900))  # an arrival
    landed = governed.composer()
    fresh = GovernedRun(tmp_path, piece=PIECE).composer()
    assert the_index_as_names(landed) == the_index_as_names(fresh), (
        "after a landing, the inherited index disagrees with one built "
        "from scratch"
    )

    run.replace_a_position("posA", some_specimen(2200))  # a new generation
    replaced = governed.composer()
    fresh = GovernedRun(tmp_path, piece=PIECE).composer()
    assert the_index_as_names(replaced) == the_index_as_names(fresh), (
        "after a replacement, the inherited index disagrees with one built "
        "from scratch"
    )
    for entries in the_index_as_names(replaced).values():
        for named in entries.values():
            for name, _ in named:
                assert "posA.ome" not in name, (
                    "a piece still names the replaced generation's store"
                )
