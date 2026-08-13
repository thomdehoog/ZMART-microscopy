"""A live picture's baked ground stays true, commit by commit.

A finished transfer bakes once at declare time and is done — its ground never
changes. A live run's ground changes with every commit, so its bake is only
honest if every commit patches the touched baked pieces before anyone can be
answered from them. These are the contracts: the baked answer and the built
answer must be indistinguishable at every moment an operator can observe,
whatever has landed, been replaced, or been withdrawn — and a picture declared
without the bake behaves exactly as before, because live runs keep BOTH modes.

The design under test is REVIEW_PROMPT_per_commit_bake_for_live.md; the
operator's requirements are quoted there. The central rule, stated once: the
bake is patched per commit, never rebuilt — and byte-equality with a
from-scratch bake of the same manifest state is what "patched correctly"
means, because the from-scratch bake is trivially true.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

VIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(VIZ / "building"))
sys.path.insert(0, str(VIZ.parent))

from zmart_live.tests.test_coordinator import some_specimen  # noqa: E402

from declare import declare_a_governed_picture  # noqa: E402
from test_the_composer_obeys_the_manifest import (  # noqa: E402
    PIECE, a_governed_run, the_columns_of)

import served  # noqa: E402


def every_baked_file(store: Path) -> dict[str, bytes]:
    """Every baked chunk file under the picture, path-relative to it."""
    return {
        str(one.relative_to(store)): one.read_bytes()
        for one in store.rglob("*")
        if one.is_file() and one.name != "zarr.json"
        and "c" in one.relative_to(store).parts
    }


def a_fresh_bake_of(run_folder: Path, where: Path) -> dict[str, bytes]:
    """The trivially-true reference: bake the same run state from scratch."""
    store = declare_a_governed_picture(where, run_folder, name="reference",
                                       piece=PIECE, bake=True)
    return every_baked_file(store)


def test_declaring_with_bake_writes_the_coarse_ground_as_files(tmp_path):
    """The switch exists, and what it writes is the composer's own bytes."""
    run = a_governed_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))

    store = declare_a_governed_picture(tmp_path / "shown", run.folder,
                                       name="live", piece=PIECE, bake=True)
    baked = every_baked_file(store)
    assert baked, "bake=True must leave the coarse ground on disk as files"

    import json

    plain = declare_a_governed_picture(tmp_path / "plain", run.folder,
                                       name="live", piece=PIECE)
    declared = len(json.loads((plain / "zarr.json").read_text(
        encoding="utf-8"))["attributes"]["ome"]["multiscales"][0]["datasets"])
    try:
        for inside, held in baked.items():
            level, _, plane, row, column = Path(inside).parts
            if int(level) >= declared:
                continue  # the picture's own levels exist only as baked files
            computed = served.the_bytes_behind(
                plain, f"{level}/c/{plane}/{row}/{column}")
            assert computed == held, (
                f"baked piece {inside} differs from the computed answer — "
                "the two modes must be indistinguishable byte for byte"
            )
    finally:
        served.forget(plain)
        served.forget(store)


def test_a_landing_patches_the_bake_to_match_a_fresh_one(tmp_path):
    """After a landing, the patched files equal a from-scratch bake's.

    Byte-equality with the trivially-true reference is what "patched
    correctly" means. That the patch touches ONLY the footprint — the
    O(change) claim — cannot be expressed on a two-position fixture whose
    whole bake is one coarse piece; the scale harness's patch-cost column
    proves it instead, where a lie would be seconds wide.
    """
    run = a_governed_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))
    store = declare_a_governed_picture(tmp_path / "shown", run.folder,
                                       name="live", piece=PIECE, bake=True)
    before = every_baked_file(store)

    run.write_and_publish("posB", some_specimen(4242))
    try:
        _, _, b_only = the_columns_of(run)
        appeared = served.the_bytes_behind(store, f"0/c/0/0/{b_only}")
        assert appeared is not None, (
            "the landing must be served the moment its commit is visible"
        )
        after = every_baked_file(store)
    finally:
        served.forget(store)

    reference = a_fresh_bake_of(run.folder, tmp_path / "reference")
    assert after == reference, (
        "the patched bake must equal a from-scratch bake of the same state"
    )
    assert after != before, "a landing inside the picture must patch the bake"


def test_a_replacement_is_served_new_from_files_with_no_stale_moment(tmp_path):
    """Between the commit and the answer there is no window of old ground."""
    run = a_governed_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))
    store = declare_a_governed_picture(tmp_path / "shown", run.folder,
                                       name="live", piece=PIECE, bake=True)
    try:
        a_only, _, _ = the_columns_of(run)
        import numpy as np

        from check import decode
        first = served.the_bytes_behind(store, f"0/c/0/0/{a_only}")
        assert first is not None and 700 in decode(
            first, PIECE, "uint16", ("z", "y", "x"))

        run.replace_a_position("posA", some_specimen(2200))
        second = served.the_bytes_behind(store, f"0/c/0/0/{a_only}")
        seen = set(np.unique(decode(second, PIECE, "uint16",
                                    ("z", "y", "x"))))
        assert 2200 in seen and 700 not in seen, (
            "the first ask after the commit answered the superseded "
            "generation — the file door ran ahead of the manifest"
        )
    finally:
        served.forget(store)

    reference = a_fresh_bake_of(run.folder, tmp_path / "reference")
    assert every_baked_file(store) == reference


def test_declaring_without_bake_removes_an_earlier_bake(tmp_path):
    """The switch works both ways, exactly as it does for transfers."""
    run = a_governed_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))
    store = declare_a_governed_picture(tmp_path / "shown", run.folder,
                                       name="live", piece=PIECE, bake=True)
    assert every_baked_file(store)

    again = declare_a_governed_picture(tmp_path / "shown", run.folder,
                                       name="live", piece=PIECE)
    assert again == store
    assert not every_baked_file(store), (
        "declaring without --bake left yesterday's baked ground being served"
    )


def test_the_writer_can_replace_a_baked_piece_while_it_is_served(tmp_path):
    """The WinError 5 rule extends to baked files: read, and let go."""
    run = a_governed_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))
    store = declare_a_governed_picture(tmp_path / "shown", run.folder,
                                       name="live", piece=PIECE, bake=True)
    try:
        a_only, _, _ = the_columns_of(run)
        assert served.the_bytes_behind(store, f"0/c/0/0/{a_only}") is not None
        for inside in every_baked_file(store):
            baked = store / Path(inside)
            newcomer = baked.with_suffix(".arriving")
            newcomer.write_bytes(baked.read_bytes())
            os.replace(newcomer, baked)  # PermissionError is the regression
    finally:
        served.forget(store)


def test_an_empty_run_bakes_nothing_because_absence_means_fill(tmp_path):
    """A young run's bake costs nothing: fill is expressed by absent files."""
    run = a_governed_run(tmp_path)
    run.write_the_view()
    run.write_the_layout()
    store = declare_a_governed_picture(tmp_path / "shown", run.folder,
                                       name="live", piece=PIECE, bake=True)
    assert not every_baked_file(store), (
        "an empty picture's bake must write no pixel files at all"
    )
