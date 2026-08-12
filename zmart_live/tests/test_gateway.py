"""The live publication gate used by the real viewer server."""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pytest

from zmart_live.gateway import _generation_named, answer_from_a_live_run, forget_live_run
from zmart_live.model import GridCell
from zmart_live.profiles import plan_the_writing
from zmart_live.shardlink import forget_every_remembered_index, where_one_chunk_lives

from .test_coordinator import FRAME, some_specimen


def a_live_run(folder, *, timepoints=1):
    from zmart_live.coordinator import LivePublisher

    profile, _ = plan_the_writing("overview", frame=FRAME, z_planes=1)
    return LivePublisher(
        folder,
        profile,
        run_id="gateway-run",
        cells={GridCell(0, 0): "posA", GridCell(0, 1): "posB"},
        timepoints=timepoints,
    )


def prepare_without_publishing(run, position_id, value, *, moment=0):
    run.write_a_position(position_id, some_specimen(value), timepoint=moment)
    units = frozenset(run._committed_units()) | {(position_id, moment)}
    run.write_the_link_map(units)
    run.write_the_view()
    run.write_the_layout()


def test_written_pixels_are_withheld_until_the_manifest_commit(tmp_path):
    run = a_live_run(tmp_path)
    prepare_without_publishing(run, "posA", 1700)

    source = where_one_chunk_lives(
        run.position_store("posA") / "0", (0, 0, 0, 0, 0)
    )
    assert source is not None
    before = answer_from_a_live_run(source.path)
    assert before is not None and before.allowed is False

    run.publish("posA")
    after = answer_from_a_live_run(source.path)
    assert after is not None and after.allowed is True


def test_a_missing_committed_marker_does_not_turn_a_known_run_into_static_data(tmp_path):
    run = a_live_run(tmp_path)
    run.write_and_publish("posA", some_specimen(1700))
    source = where_one_chunk_lives(
        run.position_store("posA") / "0", (0, 0, 0, 0, 0)
    )
    assert source is not None

    run.manifest.truth.unlink()
    answer = answer_from_a_live_run(source.path)
    assert answer is not None and answer.allowed is False


def test_the_view_route_is_virtual_and_gated_per_moment(tmp_path):
    run = a_live_run(tmp_path, timepoints=2)
    run.write_and_publish("posA", some_specimen(700))
    prepare_without_publishing(run, "posA", 4242, moment=1)

    # This is the virtual view key for A's first spatial piece at moment one.
    # Its array description exists, but its bytes must come from the canonical
    # route and remain withheld until the moment is committed.
    requested = run.view_level() / "c/1/0/0/0/0"
    withheld = answer_from_a_live_run(requested)
    assert withheld is not None and withheld.allowed is False

    run.publish("posA", timepoint=1)
    routed = answer_from_a_live_run(requested)
    assert routed is not None and routed.allowed is True
    assert routed.serving is not None
    assert run.position_store("posA") / "0" == routed.serving.position

    with routed.serving.path.open("rb") as handle:
        handle.seek(routed.serving.offset)
        encoded = handle.read(routed.serving.length)
    assert encoded


def test_the_outer_edge_is_routed_without_materializing_it(tmp_path):
    run = a_live_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))
    run.write_and_publish("posB", some_specimen(900))

    chunk = run.profile.level(0).inner_chunk["x"]
    _height, width = run._mosaic_extent()
    requested = run.view_level() / f"c/0/0/0/0/{(width - 1) // chunk}"
    answer = answer_from_a_live_run(requested)
    assert answer is not None and answer.allowed is True
    assert answer.serving is not None
    assert answer.serving.position == run.position_store("posB") / "0"
    assert not (run.view_level() / "c").exists()


def test_a_later_moment_falls_back_to_the_published_neighbour_in_the_overlap(tmp_path):
    """While one tile's later moment is withheld, shared ground shows its
    neighbour's published recording of that moment — never the withheld one,
    and never a blank where a published measurement exists."""
    run = a_live_run(tmp_path, timepoints=2)
    run.write_and_publish("posA", some_specimen(700))
    run.write_and_publish("posB", some_specimen(1100))
    run.write_and_publish("posA", some_specimen(750), timepoint=1)
    prepare_without_publishing(run, "posB", 1900, moment=1)

    # posB was committed later, so it is drawn over the shared strip. Its
    # moment 1 is written but withheld, and posA's moment 1 is published, so
    # the strip at moment 1 falls back to posA until posB's commit lands.
    overlap_chunk = (
        run.layout.placement("posB").origin["x"]
        // run.profile.level(0).inner_chunk["x"]
    )
    requested = run.view_level() / f"c/1/0/0/0/{overlap_chunk}"
    meanwhile = answer_from_a_live_run(requested)
    assert meanwhile is not None and meanwhile.allowed is True
    assert meanwhile.serving is not None
    assert meanwhile.serving.position == run.position_store("posA") / "0"

    run.publish("posB", timepoint=1)
    after = answer_from_a_live_run(requested)
    assert after is not None and after.allowed is True
    assert after.serving is not None
    assert after.serving.position == run.position_store("posB") / "0"


def test_the_gateway_refuses_a_view_that_owns_pixel_payload(tmp_path):
    """A copied chunk must never become a second, potentially stale truth."""
    import zarr

    run = a_live_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))
    level = run.view_level()
    view = zarr.open_array(str(level), mode="r+")
    view[0, 0, 0, :64, :64] = 700
    requested = level / "c/0/0/0/0/0"

    forget_live_run(run.folder)
    answer = answer_from_a_live_run(requested)
    assert answer is not None and answer.allowed is False


def test_replacing_one_moment_keeps_other_published_moments_visible(tmp_path):
    run = a_live_run(tmp_path, timepoints=3)
    run.write_and_publish("posA", some_specimen(700))
    run.write_and_publish("posA", some_specimen(900), timepoint=1)

    replacement = run.replace_a_position("posA", some_specimen(1900), timepoint=1)
    assert replacement.position_generation == 1

    inherited = run.view_level() / "c/0/0/0/0/0"
    answer = answer_from_a_live_run(inherited)
    assert answer is not None and answer.allowed is True
    assert answer.serving is not None
    assert answer.serving.position.parent.name == "posA.generation-1.ome.zarr"

    never_published = run.view_level() / "c/2/0/0/0/0"
    withheld = answer_from_a_live_run(never_published)
    assert withheld is not None and withheld.allowed is False


def test_replacement_pixels_are_withheld_while_shared_views_are_being_changed(
    tmp_path, monkeypatch
):
    run = a_live_run(tmp_path)
    run.write_and_publish("posA", some_specimen(500))
    run.write_and_publish("posB", some_specimen(700))
    chunk = run.profile.level(0).inner_chunk["x"]
    _height, width = run._mosaic_extent()
    virtual_edge = run.view_level() / f"c/0/0/0/0/{(width - 1) // chunk}"
    before = answer_from_a_live_run(virtual_edge)
    assert before is not None and before.allowed is True
    assert before.serving is not None

    observed = []
    really_write = run.write_the_view

    def observe_after_the_view_changed():
        really_write()
        answer = answer_from_a_live_run(virtual_edge)
        observed.append(answer is not None and answer.allowed)

    monkeypatch.setattr(run, "write_the_view", observe_after_the_view_changed)
    run.replace_a_position("posB", some_specimen(1900))

    assert observed == [False], (
        "the candidate generation must be withheld before its route is published"
    )
    after = answer_from_a_live_run(virtual_edge)
    assert after is not None and after.allowed is True and after.serving is not None
    assert after.serving.position.parent.name == "posB.generation-1.ome.zarr"


def test_a_failed_replacement_restores_old_shared_pixels_and_routing(
    tmp_path, monkeypatch
):
    run = a_live_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))

    def fail_at_the_commit(*_args, **_kwargs):
        raise RuntimeError("commit deliberately interrupted")

    monkeypatch.setattr(run, "publish", fail_at_the_commit)
    with pytest.raises(RuntimeError, match="deliberately interrupted"):
        run.replace_a_position("posA", some_specimen(1900))

    assert run.generations == {}
    held = json.loads(run.link_map_file.read_text(encoding="utf-8"))
    assert held["position_generations"] == {"posA": 0}
    assert not (run.view_level() / "c").exists()

    linked_piece = run.view_level() / "c/0/0/0/0/0"
    answer = answer_from_a_live_run(linked_piece)
    assert answer is not None and answer.allowed is True
    assert answer.serving is not None
    assert answer.serving.position.parent.name == "posA.ome.zarr"


def test_a_link_map_from_another_run_fails_closed_after_publication(tmp_path):
    run = a_live_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))
    requested = run.view_level() / "c/0/0/0/0/0"
    sound = answer_from_a_live_run(requested)
    assert sound is not None and sound.allowed is True

    link_map = run.link_map_file
    damaged = json.loads(link_map.read_text(encoding="utf-8"))
    damaged["run_id"] = "a-different-run"
    link_map.write_text(json.dumps(damaged), encoding="utf-8")
    forget_live_run(run.folder)

    refused = answer_from_a_live_run(requested)
    assert refused is not None and refused.allowed is False


def test_a_link_map_that_reorders_the_draw_order_fails_closed(tmp_path):
    """The stored order is the draw order, so a lie about it is a lie about pixels.

    Swapping two committed positions in the map would quietly hand the overlap
    to the earlier arrival — specimen that looks entirely plausible — so the
    gateway checks the order against the manifest and refuses the map instead.
    """
    run = a_live_run(tmp_path)
    run.write_and_publish("posB", some_specimen(900))
    run.write_and_publish("posA", some_specimen(700))
    requested = run.view_level() / "c/0/0/0/0/0"
    sound = answer_from_a_live_run(requested)
    assert sound is not None and sound.allowed is True

    link_map = run.link_map_file
    damaged = json.loads(link_map.read_text(encoding="utf-8"))
    for level in damaged["levels"]:
        level["positions"].reverse()
    link_map.write_text(json.dumps(damaged), encoding="utf-8")
    forget_live_run(run.folder)

    refused = answer_from_a_live_run(requested)
    assert refused is not None and refused.allowed is False


def test_a_link_map_that_moves_a_tile_fails_closed(tmp_path):
    """A map that slides a tile inward must be refused, not partly served.

    Under later-wins an inward move is the dangerous direction: nothing else
    collides, the route still builds, and the moved tile would simply claim
    its neighbour's ground and be served there — plausible specimen, wrong
    place. Only the check against the immutable layout stands between that
    map and the screen, so both the vacated ground and the wrongly claimed
    ground have to come back refused.
    """
    run = a_live_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))

    link_map = run.link_map_file
    damaged = json.loads(link_map.read_text(encoding="utf-8"))
    # One whole chunk inward at full resolution: chunk-aligned, entirely inside
    # the picture, colliding with nothing — the move only the layout check sees.
    damaged["levels"][0]["positions"][0]["lands_at"][2] += run.profile.level(
        0
    ).inner_chunk["x"]
    link_map.write_text(json.dumps(damaged), encoding="utf-8")
    forget_live_run(run.folder)

    vacated = answer_from_a_live_run(run.view_level() / "c/0/0/0/0/0")
    assert vacated is not None and vacated.allowed is False
    claimed = answer_from_a_live_run(run.view_level() / "c/0/0/0/0/1")
    assert claimed is not None and claimed.allowed is False, (
        "ground the moved tile wrongly claims must be refused, never served "
        "out of the wrong part of the specimen"
    )


def test_a_lone_legacy_generation_looking_name_is_not_misparsed():
    """Old layouts remain readable after the internal suffix became reserved."""
    assert _generation_named(
        "sample.generation-1.ome.zarr", ("sample.generation-1",)
    ) == ("sample.generation-1", 0)


def test_a_non_live_zarr_is_not_claimed_by_the_gateway(tmp_path):
    ordinary = tmp_path / "ordinary.zarr" / "c" / "0" / "0"
    ordinary.parent.mkdir(parents=True)
    ordinary.write_bytes(np.array([1], dtype="uint8").tobytes())
    assert answer_from_a_live_run(ordinary) is None


# ---------------------------------------------------------------------------
# The gateway under parallel fire
# ---------------------------------------------------------------------------
#
# Every test above asks one question at a time and waits for the answer. A real
# browser never does that: the moment a viewer opens, it asks for dozens of
# pieces at once, each on its own thread. A server can be perfectly correct
# when asked politely and wrong when asked in parallel — the building viewer in
# ``viz_studio`` shipped exactly such a bug, serving one request's specimen to
# another, and no single-request test could ever have seen it. These two tests
# ask the way the browser asks.


def _every_view_chunk(run):
    """Every chunk coordinate path of the full-resolution view, moment zero."""
    level = run.view_level()
    described = json.loads((level / "zarr.json").read_text(encoding="utf-8"))
    shape = described["shape"]
    chunk = described["chunk_grid"]["configuration"]["chunk_shape"]
    down = -(-shape[-2] // chunk[-2])
    across = -(-shape[-1] // chunk[-1])
    return [
        level / "c" / "0" / "0" / "0" / str(y) / str(x)
        for y in range(down)
        for x in range(across)
    ]


def _handed_over(target):
    """Ask the gateway for one piece the way the viewer's server would.

    Returns the exact bytes handed over, or ``None`` where the gateway
    withholds the piece — which the viewer shows as ordinary empty ground.
    """
    answer = answer_from_a_live_run(target)
    if answer is None or not answer.allowed or answer.serving is None:
        return None
    with answer.serving.path.open("rb") as handle:
        handle.seek(answer.serving.offset)
        return handle.read(answer.serving.length)


def _one_canonical_chunk_of(run, position_id):
    """The encoded bytes of one chunk of a position's own store, read directly.

    Every chunk of these constant-filled test positions encodes to the same
    bytes, so this one chunk is a fingerprint: any answer equal to it came from
    this position and no other.
    """
    source = where_one_chunk_lives(
        run.position_store(position_id) / "0", (0, 0, 0, 0, 0)
    )
    assert source is not None
    with source.path.open("rb") as handle:
        handle.seek(source.offset)
        return handle.read(source.length)


def _forget_everything(run):
    """Drop every remembered table and route, as a freshly started server has."""
    forget_live_run(run.folder)
    forget_every_remembered_index()


def test_a_stampede_on_a_cold_gateway_matches_a_polite_reader(tmp_path):
    """Many first requests at once must each get what a lone request gets.

    The gateway builds its picture of a run — manifest, routes, shard tables —
    the first time it is asked, and remembers it. A browser's opening burst is
    therefore many threads racing to build that state together, which is the
    classic place for one of them to read a half-built answer.
    """
    run = a_live_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))
    run.write_and_publish("posB", some_specimen(4242))
    wanted = _every_view_chunk(run)

    _forget_everything(run)
    politely = {target: _handed_over(target) for target in wanted}
    # The polite pass must already show both positions, or the storm below
    # would be comparing against a broken baseline.
    assert set(politely.values()) >= {
        _one_canonical_chunk_of(run, "posA"),
        _one_canonical_chunk_of(run, "posB"),
    }

    _forget_everything(run)
    surprises: list[str] = []
    troubles: list[BaseException] = []
    ready = threading.Barrier(12)

    def storm(which):
        # Each thread starts somewhere else in the picture, so at any moment
        # different threads are asking about different pieces — more
        # interleavings than everyone marching in step would try.
        try:
            ready.wait()
            rotated = wanted[which:] + wanted[:which]
            for target in rotated:
                if _handed_over(target) != politely[target]:
                    surprises.append(str(target.relative_to(run.folder)))
        except BaseException as trouble:  # noqa: BLE001 - reported by the test
            troubles.append(trouble)

    with ThreadPoolExecutor(max_workers=12) as pool:
        for which in range(12):
            pool.submit(storm, which)

    assert not troubles, f"a parallel reader crashed: {troubles[0]!r}"
    assert not surprises, (
        f"{len(surprises)} answers under parallel fire differed from what a "
        f"lone polite reader gets, first at {surprises[0]}"
    )


def test_a_commit_landing_mid_storm_is_never_shown_early_and_never_torn(tmp_path):
    """While a commit lands, every parallel answer is one truth or the other.

    posA is published; posB is written, routed and withheld, overlapping posA.
    Threads hammer the whole view while posB's commit lands in the middle of
    the storm. Every single answer must be exactly what the view said before
    the commit or exactly what it says after — never posB's pixels before its
    commit began, and never a blank where published ground was showing.
    """
    run = a_live_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))
    prepare_without_publishing(run, "posB", 4242)
    wanted = _every_view_chunk(run)
    from_a = _one_canonical_chunk_of(run, "posA")
    from_b = _one_canonical_chunk_of(run, "posB")

    _forget_everything(run)
    before = {target: _handed_over(target) for target in wanted}
    # Before the commit: posA shows, posB is invisible, and the ground only
    # posB covers is withheld. This is the single-threaded contract the storm
    # is then held to.
    assert set(before.values()) == {from_a, None}

    # Every answer any thread records: (which piece, when it finished, what it
    # got). Appending to a list is safe across threads; the judging happens
    # afterwards, single-threaded.
    seen: list[tuple[Path, float, bytes | None]] = []
    troubles: list[BaseException] = []
    settle_down = threading.Event()
    ready = threading.Barrier(9)

    def storm(which):
        try:
            ready.wait()
            rotated = wanted[which:] + wanted[:which]
            while not settle_down.is_set():
                for target in rotated:
                    got = _handed_over(target)
                    seen.append((target, time.monotonic(), got))
        except BaseException as trouble:  # noqa: BLE001 - reported by the test
            troubles.append(trouble)

    _forget_everything(run)
    with ThreadPoolExecutor(max_workers=8) as pool:
        for which in range(8):
            pool.submit(storm, which)
        ready.wait()

        # Let the storm genuinely rage first, then land the commit inside it.
        time.sleep(0.2)
        commit_began = time.monotonic()
        run.publish("posB")

        # Keep the storm going until it has visibly noticed the commit, so the
        # transition itself — not just the states either side of it — is what
        # was exercised. Ten seconds is a deadline, not an expectation.
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if any(got == from_b for _, _, got in list(seen)):
                break
            time.sleep(0.01)
        settle_down.set()

    after = {target: _handed_over(target) for target in wanted}
    # After the commit, the later commit is drawn on top of the shared ground
    # and nothing anywhere is blank.
    assert set(after.values()) == {from_a, from_b}

    assert not troubles, f"a parallel reader crashed: {troubles[0]!r}"
    assert any(got == from_b for _, _, got in seen), (
        "the storm never observed the commit landing, so the transition was "
        "not actually exercised"
    )
    for target, finished, got in seen:
        where = target.relative_to(run.folder)
        # Only the two truths ever existed; anything else is a torn answer.
        assert got in (before[target], after[target]), (
            f"{where} was answered with bytes that are neither the "
            f"pre-commit nor the post-commit truth"
        )
        # posB's pixels may not be seen by a request that finished before the
        # commit began. That is the live contract at its hardest moment.
        if got is not None and got == after[target] and before[target] != after[target]:
            assert finished >= commit_began, (
                f"{where} showed the newly committed position before its "
                f"commit began"
            )
