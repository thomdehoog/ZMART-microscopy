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

import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

VIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(VIZ / "building"))
sys.path.insert(0, str(VIZ.parent))

from zmart_live.tests.test_coordinator import some_specimen  # noqa: E402

from declare import declare_a_governed_picture  # noqa: E402
from governed import GovernedRun  # noqa: E402
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


@pytest.mark.skipif(os.name != "nt", reason="Windows sharing semantics")
def test_the_bake_retries_a_transient_windows_sharing_violation(
        tmp_path, monkeypatch):
    """A transient Windows sharing lock must not turn a commit into absence.

    Windows refuses ``os.replace`` while another thread is reading the
    destination chunk.  During a storm the page and the warm pass do exactly
    that, briefly; failing the derive makes the serving door answer absent and
    produces the black pause the operator saw.  Reproduce that observed error
    once at the staged-chunk boundary: the patcher must retry and finish.
    """
    run = a_governed_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))
    store = declare_a_governed_picture(tmp_path / "shown", run.folder,
                                       name="live", piece=PIECE, bake=True)
    governed = GovernedRun(run.folder, piece=PIECE, store=store)
    governed.composer()
    import governed as governed_module

    real_replace = governed_module.os.replace
    refused = {"left": 1}

    def a_reader_temporarily_owns_the_destination(arriving, real):
        if (refused["left"] and ".patching-" in str(arriving)
                and ".patching-" not in str(real)):
            refused["left"] -= 1
            raise PermissionError(5, "Access is denied", str(real))
        return real_replace(arriving, real)

    monkeypatch.setattr(governed_module.os, "replace",
                        a_reader_temporarily_owns_the_destination)
    try:
        run.replace_a_position("posA", some_specimen(2200))
        governed.composer()
        after = every_baked_file(store)
    finally:
        governed.close()

    assert refused["left"] == 0, "the test never reached an extended bake"

    reference = a_fresh_bake_of(run.folder, tmp_path / "reference")
    assert after == reference, (
        "the bake did not recover after a transient reader released its chunk"
    )


def test_the_http_route_consults_the_manifest_before_any_baked_file(tmp_path):
    """The backend's own file door must not outrun the gate either.

    served.py's ordering was fixed first, and the scale harness then showed
    the same hole one layer up: the backend serves any file that exists
    without asking anyone, so a baked governed piece answered statically —
    no derive, no patch, and a replacement never reached the screen
    (visible: nan on every churn row, held composers 0). A piece-shaped
    address inside a governed picture goes through the building door, file
    or no file.
    """
    import threading
    import urllib.request

    backend = str(Path(__file__).resolve().parent.parent / "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)
    import numpy as np

    from check import decode
    from server import make_server

    run = a_governed_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))
    store = declare_a_governed_picture(tmp_path / "shown", run.folder,
                                       name="live", piece=PIECE, bake=True)
    server = make_server(port=0, data_dir=tmp_path / "shown",
                         store=[store.name])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        addresses = ["/".join(Path(one).parts).replace("/c/", "/c/", 1)
                     for one in every_baked_file(store)]
        assert addresses, "the hole only exists where baked files do"

        def over_http(inside: str) -> bytes:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/data/0/{store.name}/{inside}",
                    timeout=30) as answer:
                return answer.read()

        showing = {
            inside: decode(over_http(inside), PIECE, "uint16",
                           ("z", "y", "x"))
            for inside in addresses
        }
        marked = [inside for inside, piece in showing.items()
                  if 700 in piece]
        assert marked, "some baked piece must show the published ground"

        run.replace_a_position("posA", some_specimen(2200))
        for inside in marked:
            seen = set(np.unique(decode(over_http(inside), PIECE, "uint16",
                                        ("z", "y", "x"))))
            assert 2200 in seen and 700 not in seen, (
                f"piece {inside}: the backend served the baked file from "
                "before the replacement — its file door ran ahead of the "
                "manifest"
            )
    finally:
        served.forget(store)
        server.shutdown()
        thread.join(timeout=5)


def test_a_rollback_withdraws_ground_from_the_baked_files_too(tmp_path):
    """Review finding D1: the missing leg of the central contract.

    A whole-history rollback shrinks the manifest — signed.json names an
    earlier revision, and events beyond it stop existing. A stamp compared
    as a bare count then reads AHEAD of the history and concludes the bake
    is current, so the withdrawn position's baked files survive and the
    file door keeps serving ground the manifest has withdrawn — fail-closed
    violated in exactly the operation the requirements name. The stamp must
    treat a history that came back shorter (or rewritten under it) as
    coverage unknown, and repatch everything.
    """
    run = a_governed_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))
    truth = run.folder / "views" / "live" / "metadata" / "signed.json"
    remembered = truth.read_text(encoding="utf-8")
    run.write_and_publish("posB", some_specimen(4242))

    store = declare_a_governed_picture(tmp_path / "shown", run.folder,
                                       name="live", piece=PIECE, bake=True)
    try:
        _, _, b_only = the_columns_of(run)
        assert served.the_bytes_behind(store, f"0/c/0/0/{b_only}") is not None

        truth.write_text(remembered, encoding="utf-8")
        assert served.the_bytes_behind(store, f"0/c/0/0/{b_only}") is None, (
            "the gate itself must withdraw the rolled-back ground"
        )
        after = every_baked_file(store)
    finally:
        served.forget(store)
    reference = a_fresh_bake_of(run.folder, tmp_path / "reference")
    assert after == reference, (
        "the rolled-back position's ground survived in the baked files — "
        "the stamp read ahead of the shrunken history and skipped the patch"
    )


def test_a_commit_landing_during_the_initial_bake_is_not_lost(tmp_path,
                                                              monkeypatch):
    """Review finding D2: the declare-time stamp race.

    The initial bake writes the state of the snapshot taken BEFORE it ran,
    which at survey scale is minutes wide — but the stamp was written from
    the manifest as of stamp time, claiming every commit that landed in the
    window. Those commits were never baked and, with the stamp past them,
    never patched: a replacement missed this way serves its superseded
    generation from files forever. The stamp must say what the bake actually
    absorbed — the fold count of the snapshot it baked.
    """
    import declare as declaring

    run = a_governed_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))

    the_real_bake = declaring._bake_the_coarse_ground
    landing = {"left": 1}

    def a_commit_lands_mid_bake(store, composer, described, **carried):
        baked = the_real_bake(store, composer, described, **carried)
        if landing["left"]:
            landing["left"] -= 1
            run.write_and_publish("posB", some_specimen(4242))
        return baked

    monkeypatch.setattr(declaring, "_bake_the_coarse_ground",
                        a_commit_lands_mid_bake)
    store = declare_a_governed_picture(tmp_path / "shown", run.folder,
                                       name="live", piece=PIECE, bake=True)
    try:
        _, _, b_only = the_columns_of(run)
        appeared = served.the_bytes_behind(store, f"0/c/0/0/{b_only}")
        assert appeared is not None, (
            "the commit that landed mid-bake must be served"
        )
        after = every_baked_file(store)
    finally:
        served.forget(store)
    reference = a_fresh_bake_of(run.folder, tmp_path / "reference")
    assert after == reference, (
        "the mid-bake commit was stamped as absorbed but never baked, and "
        "the catch-up never patched it"
    )


def test_the_bake_catches_up_after_demand_stops(tmp_path):
    """A quiet run heals its bake without a piece request driving it.

    A page can stop asking while a commit storm is still outrunning the bake.
    Judging through ``composer()`` would hide that failure, because the judge's
    own ask performs the missing catch-up.  Establish serving once, land a
    short burst, then judge the stamp directly before touching any serving
    door.  The eventual byte comparison proves that the independently driven
    catch-up repaired the ground rather than merely advancing its stamp.
    """
    run = a_governed_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))
    store = declare_a_governed_picture(tmp_path / "shown", run.folder,
                                       name="live", piece=PIECE, bake=True)
    import urllib.request

    backend = str(Path(__file__).resolve().parent.parent / "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)
    from server import make_server

    # One piece ask opens and remembers the governed run.  It is deliberately
    # the final image request in this test.
    inside = next(iter(every_baked_file(store)))
    assert served.the_bytes_behind(store, inside.replace("\\", "/")) is not None
    server = make_server(port=0, data_dir=tmp_path / "shown",
                         store=[store.name])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        run.write_and_publish("posB", some_specimen(4242))
        run.replace_a_position("posA", some_specimen(2200))
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/announce",
            data=b"{}", headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30):
            pass

        expected = 3
        stamp_path = store / "baked.json"
        deadline = time.monotonic() + 5
        stamped = None
        while time.monotonic() < deadline:
            stamped = json.loads(stamp_path.read_text(encoding="utf-8"))
            if stamped.get("events") == expected:
                break
            time.sleep(0.05)
        assert stamped is not None and stamped.get("events") == expected, (
            f"the run went quiet at {expected} events but its bake stayed at "
            f"{None if stamped is None else stamped.get('events')}; no client "
            "request may be needed to drive the final catch-up"
        )
        after = every_baked_file(store)
    finally:
        server.shutdown()
        thread.join(timeout=5)
        served.forget(store)

    reference = a_fresh_bake_of(run.folder, tmp_path / "reference")
    assert after == reference, (
        "the demand-free catch-up advanced the stamp without repairing all "
        "of the ground the burst changed"
    )


def test_background_catch_up_waits_for_the_announcement_storm_to_quiet(
        tmp_path, monkeypatch):
    """The safety worker must not starve page derives during a commit storm.

    An eager background worker acquired the derive lock on every intermediate
    state and immediately reacquired it while page requests waited.  The disk
    became current, but the operator saw no spiral for more than ten seconds
    and then the whole tail appeared at once.  Announcements drive the safety
    pass, but must coalesce until a short quiet window; then exactly one pass
    runs without any page request.
    """
    run = a_governed_run(tmp_path)
    governed = GovernedRun(run.folder, piece=PIECE)
    called: list[float] = []
    caught_up = threading.Event()

    def record_one_catch_up():
        called.append(time.monotonic())
        with governed._guard:
            governed._mark = governed._run.manifest.fingerprint()
        caught_up.set()

    monkeypatch.setattr(governed, "composer", record_one_catch_up)
    try:
        for _ in range(6):
            governed.request_catch_up()
            time.sleep(0.05)
        assert not called, (
            "background baking began while announcements were still arriving"
        )
        assert caught_up.wait(timeout=2), (
            "the final announcement did not drive a catch-up after quiet"
        )
    finally:
        governed.close()
    assert len(called) == 1, (
        f"the announcement burst drove {len(called)} background derives"
    )


def test_an_older_derive_cannot_regress_the_bake_behind_a_newer_one(
        tmp_path, monkeypatch):
    """A stale patcher must stand down before it changes baked files.

    Request A can finish composing, pause before the bake lock, and be
    overtaken by request B for a later commit.  Installation already makes A
    stand down, but that happens after A has patched: without a bake-side
    stale check it rewrites B's shared ground from its older snapshot and
    regresses the stamp.  The next unrelated landing then trusts that
    regressed stamp, patches only its own footprint, and stamps the whole
    history current while B's hole survives forever.
    """
    from zmart_live.coordinator import LivePublisher
    from zmart_live.model import GridCell
    from zmart_live.profiles import plan_the_writing
    from zmart_live.tests.test_coordinator import FRAME

    profile, _ = plan_the_writing("overview", frame=FRAME, z_planes=1)
    cells = {
        GridCell(row, column): (
            "posA" if (row, column) == (0, 0) else
            "posB" if (row, column) == (0, 1) else
            "posC" if (row, column) == (3, 3) else
            f"unused-{row}-{column}"
        )
        for row in range(4)
        for column in range(4)
    }
    run = LivePublisher(tmp_path, profile, run_id="out-of-order-bake",
                        cells=cells, timepoints=1)
    run.write_and_publish("posA", some_specimen(700))
    store = declare_a_governed_picture(tmp_path / "shown", run.folder,
                                       name="live", piece=PIECE, bake=True)
    governed = GovernedRun(run.folder, piece=PIECE, store=store)
    governed.composer()

    old_waits = threading.Event()
    let_old_continue = threading.Event()
    real_keep = governed._keep_the_bake_true

    def hold_the_older_snapshot(made, dirtied, current, *rest, **named):
        # The trailing arguments belong to the patcher (its phase ledger and
        # the paste-over changes) and this race cares nothing about them --
        # they pass through untouched, so the interceptor keeps working as
        # the real signature grows.
        if current["events"] == 2:
            old_waits.set()
            assert let_old_continue.wait(timeout=30)
        return real_keep(made, dirtied, current, *rest, **named)

    monkeypatch.setattr(governed, "_keep_the_bake_true",
                        hold_the_older_snapshot)
    run.replace_a_position("posA", some_specimen(2200))
    failed: list[BaseException] = []

    def derive_the_older_snapshot():
        try:
            governed.composer()
        except BaseException as problem:  # preserve a thread failure for pytest
            failed.append(problem)

    older = threading.Thread(target=derive_the_older_snapshot)
    older.start()
    assert old_waits.wait(timeout=30), "the older derive did not reach the race"

    run.write_and_publish("posB", some_specimen(4242))
    newer_done = threading.Event()

    def derive_the_newer_snapshot():
        try:
            governed.composer()
        except BaseException as problem:  # preserve a thread failure for pytest
            failed.append(problem)
        finally:
            newer_done.set()

    newer = threading.Thread(target=derive_the_newer_snapshot)
    newer.start()
    # Without ordering, the newer derive overtakes and finishes here.  With
    # ordering, it waits behind the older transaction; either way, release
    # the deliberately paused request and let both reach a settled state.
    newer_done.wait(timeout=5)
    let_old_continue.set()
    older.join(timeout=30)
    newer.join(timeout=30)
    assert not older.is_alive(), "the older derive did not finish"
    assert not newer.is_alive(), "the newer derive did not finish"
    assert not failed, f"a racing derive failed: {failed!r}"

    # A landing in another piece advances the stamp.  It must also recover
    # any ground the out-of-order patcher missed, rather than blessing a hole.
    run.write_and_publish("posC", some_specimen(1900))
    governed.composer()

    reference = a_fresh_bake_of(run.folder, tmp_path / "reference")
    assert every_baked_file(store) == reference, (
        "an older derive rewrote a newer landing, then the next commit "
        "stamped the bake current without repairing the missed ground"
    )


def test_redeclaring_under_a_running_server_is_noticed(tmp_path):
    """Review finding D5: the served picture follows its declaration.

    A picture opened unbaked is remembered by the serving registry; turning
    the bake on by re-declaring wrote new files and a new description, but
    the remembered GovernedRun kept its empty baked-level list — it never
    patched, while the file door happily served the declare-time files, one
    commit staler with every change. The registry must notice the picture's
    own description changing.
    """
    run = a_governed_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))
    store = declare_a_governed_picture(tmp_path / "shown", run.folder,
                                       name="live", piece=PIECE)
    try:
        a_only, _, _ = the_columns_of(run)
        assert served.the_bytes_behind(store, f"0/c/0/0/{a_only}") is not None

        again = declare_a_governed_picture(tmp_path / "shown", run.folder,
                                           name="live", piece=PIECE,
                                           bake=True)
        assert again == store
        run.replace_a_position("posA", some_specimen(2200))
        assert served.the_bytes_behind(store, f"0/c/0/0/{a_only}") is not None
        after = every_baked_file(store)
    finally:
        served.forget(store)
    reference = a_fresh_bake_of(run.folder, tmp_path / "reference")
    assert after == reference, (
        "the running server kept the pre-bake classification and never "
        "patched the newly baked files"
    )


def test_an_unreadable_picture_description_fails_closed(tmp_path,
                                                        monkeypatch):
    """Review finding D3: classification failure must not open the file door.

    A store whose description cannot be read — damage, or this machine's
    endpoint protection briefly holding a fresh file — used to classify as
    "ordinary image", permanently, and the backend then served its baked
    files statically past the manifest. While a picture cannot be
    classified, it must be treated as governed (answer absent), and the
    failure must be retried, never remembered as ordinary.
    """
    run = a_governed_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))
    store = declare_a_governed_picture(tmp_path / "shown", run.folder,
                                       name="live", piece=PIECE, bake=True)
    served.forget(store)

    the_real_read = served._what_it_was_built_from
    stumbling = {"left": 1}

    def a_read_that_stumbles_once(path):
        if stumbling["left"]:
            stumbling["left"] -= 1
            raise OSError("endpoint protection holds the file")
        return the_real_read(path)

    monkeypatch.setattr(served, "_what_it_was_built_from",
                        a_read_that_stumbles_once)
    try:
        assert served.a_manifest_governs(store), (
            "a picture that cannot be classified must be treated as "
            "governed — failing open serves baked files past the manifest"
        )
        monkeypatch.setattr(served, "_REFUSED_FOR_SECONDS", 0.0)
        a_only, _, _ = the_columns_of(run)
        assert served.the_bytes_behind(store, f"0/c/0/0/{a_only}") is not None, (
            "one transient stumble must not be remembered as 'ordinary "
            "image' forever"
        )
    finally:
        served.forget(store)


def test_an_aliased_piece_path_cannot_walk_past_the_gate(tmp_path):
    """Review finding D4: the backend's check must see what resolve saw.

    The route check parsed the raw address while the file lookup resolved
    it, so `0/c//0/0/0` reached the real baked chunk file and was served
    statically — no derive, no patch, stale-past-manifest bytes for any
    client that asks crookedly. The check now derives the piece address
    from the resolved target itself, so every spelling of a governed piece
    goes through the gate.
    """
    import threading
    import urllib.request

    backend = str(Path(__file__).resolve().parent.parent / "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)
    from server import make_server

    run = a_governed_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))
    store = declare_a_governed_picture(tmp_path / "shown", run.folder,
                                       name="live", piece=PIECE, bake=True)
    server = make_server(port=0, data_dir=tmp_path / "shown",
                         store=[store.name])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        inside = sorted(every_baked_file(store))[0]
        level, _, plane, row, column = Path(inside).parts
        crooked = f"{level}/c//{plane}/{row}/{column}"
        straight = f"{level}/c/{plane}/{row}/{column}"

        def over_http(path: str) -> bytes:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/data/0/{store.name}/{path}",
                    timeout=30) as answer:
                return answer.read()

        run.replace_a_position("posA", some_specimen(2200))
        askew = over_http(crooked)
        canonical = over_http(straight)
        assert askew == canonical, (
            "the aliased spelling was served from the stale file while the "
            "canonical one went through the gate"
        )
    finally:
        served.forget(store)
        server.shutdown()
        thread.join(timeout=5)


def test_a_baked_picture_still_warms_the_composer_for_its_patcher(tmp_path):
    """Baked files serve the cold open; the PATCHER still needs warm slabs.

    Warming was deliberately skipped for baked pictures — "burning the
    processor the bake spared" — which was right about serving and wrong
    about patching: a change touching a cold coarse region composes its
    slab inside the derive, 0.5–3 s the operator watched as tiles updating
    "with inconsistent timing", against the 60–90 ms every warm-region
    change costs. The warmer runs for baked pictures too, so the first
    change in any region finds its slab ready.
    """
    import time

    from governed import GovernedRun

    run = a_governed_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))
    store = declare_a_governed_picture(tmp_path / "shown", run.folder,
                                       name="live", piece=PIECE, bake=True)
    governed = GovernedRun(run.folder, piece=PIECE, store=store)
    try:
        composer = governed.composer()
        deadline = time.time() + 10
        while time.time() < deadline and not composer.coarse_levels_are_warm:
            time.sleep(0.05)
        assert composer.coarse_levels_are_warm, (
            "the baked picture never warmed its composer — the patcher's "
            "first touch of every region stays a multi-second toll"
        )
    finally:
        governed.close()


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


def test_the_warm_reads_the_bake_and_holds_the_composed_ground(tmp_path):
    """A slab warmed out of the baked files equals one composed from tiles.

    The warm of a baked picture reads its pinned slabs back from the files
    the bake wrote (Composer.warm_from_the_baked) instead of composing them
    from every tile — minutes against seconds at survey scale. Whether the
    shortcut kept the ground true is checked the only way that counts:
    every slab it holds afterwards, byte for byte against the slab a
    composer with no baked files builds from the tiles, edges and their
    padding included.
    """
    import numpy as np

    from governed import GovernedRun

    run = a_governed_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))
    run.write_and_publish("posB", some_specimen(4242))
    store = declare_a_governed_picture(tmp_path / "shown", run.folder,
                                       name="live", piece=PIECE, bake=True)
    try:
        baked = GovernedRun(run.folder, piece=PIECE, store=store)
        read_back = baked.composer()
        read_back.stop_warming()
        read_back.warm_the_coarse_levels()
        assert read_back.coarse_levels_are_warm, (
            "the file-fed warm must fill every pinned slab"
        )

        composing = GovernedRun(run.folder, piece=PIECE).composer()
        composing.stop_warming()
        held = dict(read_back._pinned)
        assert held, "a baked picture's warm must have pinned something"
        for (level, low_z, row, column), slab in held.items():
            built = composing._slab_for(level, low_z, row, column)
            assert np.array_equal(slab, built), (
                f"the slab read back for level {level} piece "
                f"({row}, {column}) differs from the composed one — the "
                "warm's shortcut changed what the operator would be shown"
            )
    finally:
        import served
        served.forget(store)
