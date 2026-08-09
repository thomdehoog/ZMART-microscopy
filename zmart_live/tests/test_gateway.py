"""The live publication gate used by the real viewer server."""

from __future__ import annotations

import json

import numpy as np
import pytest
import zarr

from zmart_live.gateway import _generation_named, answer_from_a_live_run, forget_live_run
from zmart_live.model import GridCell
from zmart_live.profiles import plan_the_writing
from zmart_live.shardlink import where_one_chunk_lives

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
    run.write_the_seamless_view(units, only=frozenset({(position_id, moment)}))
    run.write_the_raw_overlap_view(units, only=frozenset({(position_id, moment)}))
    run.write_the_link_map(frozenset(position for position, _ in units))
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


def test_the_seamless_route_is_virtual_and_gated_per_moment(tmp_path):
    run = a_live_run(tmp_path, timepoints=2)
    run.write_and_publish("posA", some_specimen(700))
    prepare_without_publishing(run, "posA", 4242, moment=1)

    # This is the virtual view key for A's first spatial piece at moment one.
    # The view's own file may exist while the writer is migrating from copied to
    # sparse levels; the gateway deliberately prefers the canonical route.
    requested = run.seamless_level() / "c/1/0/0/0/0"
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


def test_a_materialized_outer_edge_is_not_mistaken_for_a_missing_route(tmp_path):
    run = a_live_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))
    run.write_and_publish("posB", some_specimen(900))

    # B contributes eight linked chunks and its far strip is the ninth.  The
    # latter deliberately lives in the view because no neighbour supplies it.
    requested = run.seamless_level() / "c/0/0/0/0/16"
    answer = answer_from_a_live_run(requested)
    assert answer is not None and answer.allowed is True
    assert answer.serving is None


def test_the_raw_overlap_gate_attributes_both_tile_and_moment(tmp_path):
    run = a_live_run(tmp_path, timepoints=2)
    run.write_and_publish("posA", some_specimen(700))
    run.write_and_publish("posB", some_specimen(1100))
    prepare_without_publishing(run, "posB", 1900, moment=1)

    placement = run.layout.placement("posB")
    chunk_x = placement.origin["x"] // run.profile.level(0).inner_chunk["x"]
    coordinate = (run.tile_stop_of("posB"), 1, 0, 0, 0, chunk_x)
    source = where_one_chunk_lives(run.raw_overlap_level(), coordinate)
    assert source is not None

    before = answer_from_a_live_run(source.path)
    assert before is not None and before.allowed is False
    run.publish("posB", timepoint=1)
    after = answer_from_a_live_run(source.path)
    assert after is not None and after.allowed is True


def test_replacing_one_moment_keeps_other_published_moments_visible(tmp_path):
    run = a_live_run(tmp_path, timepoints=3)
    run.write_and_publish("posA", some_specimen(700))
    run.write_and_publish("posA", some_specimen(900), timepoint=1)

    replacement = run.replace_a_position("posA", some_specimen(1900), timepoint=1)
    assert replacement.position_generation == 1

    inherited = run.seamless_level() / "c/0/0/0/0/0"
    answer = answer_from_a_live_run(inherited)
    assert answer is not None and answer.allowed is True
    assert answer.serving is not None
    assert answer.serving.position.parent.name == "posA.generation-1.ome.zarr"

    never_published = run.seamless_level() / "c/2/0/0/0/0"
    withheld = answer_from_a_live_run(never_published)
    assert withheld is not None and withheld.allowed is False


def test_replacement_pixels_are_withheld_while_shared_views_are_being_changed(
    tmp_path, monkeypatch
):
    run = a_live_run(tmp_path)
    run.write_and_publish("posA", some_specimen(500))
    run.write_and_publish("posB", some_specimen(700))
    physical_edge = run.seamless_level() / "c/0/0/0/0/16"
    before = answer_from_a_live_run(physical_edge)
    assert before is not None and before.allowed is True and before.serving is None

    observed = []
    really_write = run.write_the_seamless_view

    def observe_after_the_view_changed(committed, *, only=None):
        really_write(committed, only=only)
        answer = answer_from_a_live_run(physical_edge)
        observed.append(answer is not None and answer.allowed)

    monkeypatch.setattr(run, "write_the_seamless_view", observe_after_the_view_changed)
    run.replace_a_position("posB", some_specimen(1900))

    assert observed == [False], (
        "the candidate generation must be withheld before a physical view chunk "
        "is replaced"
    )
    after = answer_from_a_live_run(physical_edge)
    assert after is not None and after.allowed is True


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
    seamless = zarr.open_array(str(run.seamless_level()), mode="r")
    raw = zarr.open_array(str(run.raw_overlap_level()), mode="r")
    assert int(seamless[0, 0, 0].max()) == 700
    assert int(raw[run.tile_stop_of("posA"), 0, 0, 0].max()) == 700

    linked_piece = run.seamless_level() / "c/0/0/0/0/0"
    answer = answer_from_a_live_run(linked_piece)
    assert answer is not None and answer.allowed is True
    assert answer.serving is not None
    assert answer.serving.position.parent.name == "posA.ome.zarr"


def test_a_link_map_from_another_run_fails_closed_after_publication(tmp_path):
    run = a_live_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))
    requested = run.seamless_level() / "c/0/0/0/0/0"
    sound = answer_from_a_live_run(requested)
    assert sound is not None and sound.allowed is True

    link_map = run.link_map_file
    damaged = json.loads(link_map.read_text(encoding="utf-8"))
    damaged["run_id"] = "a-different-run"
    link_map.write_text(json.dumps(damaged), encoding="utf-8")
    forget_live_run(run.folder)

    refused = answer_from_a_live_run(requested)
    assert refused is not None and refused.allowed is False


def test_a_link_map_that_moves_a_tile_fails_closed(tmp_path):
    run = a_live_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))
    requested = run.seamless_level() / "c/0/0/0/0/0"

    link_map = run.link_map_file
    damaged = json.loads(link_map.read_text(encoding="utf-8"))
    damaged["levels"][0]["positions"][0]["lands_at"][2] += 128
    link_map.write_text(json.dumps(damaged), encoding="utf-8")
    forget_live_run(run.folder)

    refused = answer_from_a_live_run(requested)
    assert refused is not None and refused.allowed is False


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
