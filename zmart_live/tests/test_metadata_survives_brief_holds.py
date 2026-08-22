"""The per-commit metadata rewrites survive a reader glancing at the file.

The live arrangement is a viewer reading the run while the acquisition writes
it, and the small metadata files are where the two meet on every commit: the
publication marker, the map of pointers, and the view's own description are
each replaced atomically, and a reader holds each of them open over and over.
On Windows an open handle makes the replacement itself fail — ``Access is
denied`` on ground that is free a moment later — and a governed run watched
live on the lab machine died of exactly this, at revision 36 of 144, on the
per-commit rewrite of a view description.

The pixel path was cured of the same disease first
(:func:`zmart_storage.canvas.written_despite_brief_holds`), so these tests pin
the cure onto the metadata path: each rewrite is retried through the same
short patience, and anything that is not the Windows spelling of "briefly
held" still raises at once.

The holds here are real ones — a thread genuinely holding the file open the
way Python opens files, which on Windows is without delete sharing — so on
Windows the unfixed code genuinely fails. On other systems an open handle does
not block a rename and these tests pass trivially, which is the correct
statement of the fault's platform.
"""

from __future__ import annotations

import json
import threading
import time

import numpy as np
import pytest

from zmart_live.coordinator import LivePublisher
from zmart_live.manifest import _write_and_replace
from zmart_live.model import GridCell
from zmart_live.omezarr import _write_over_carefully, describe_the_position
from zmart_live.profiles import plan_the_writing

from .test_coordinator import FRAME, some_specimen


def held_open_briefly(path, *, seconds: float = 0.4):
    """Hold one file open the way a reader would, for a little while.

    Returns the thread, already started. The hold begins before this returns,
    so the caller's very next write meets it rather than racing past it.
    """
    holding = threading.Event()

    def hold():
        with path.open("rb") as reader:
            reader.read()
            holding.set()
            time.sleep(seconds)

    thread = threading.Thread(target=hold, daemon=True)
    thread.start()
    assert holding.wait(timeout=5), "the reader never managed to open the file"
    return thread


def test_the_small_marker_is_replaced_despite_a_readers_hold(tmp_path):
    """The atomic replace waits out a brief hold instead of dying of it."""
    target = tmp_path / "signed.json"
    _write_and_replace(target, json.dumps({"revision": 1}))

    reader = held_open_briefly(target)
    _write_and_replace(target, json.dumps({"revision": 2}))
    reader.join(timeout=5)

    assert json.loads(target.read_text(encoding="utf-8")) == {"revision": 2}


def test_an_arrays_description_is_replaced_despite_a_readers_hold(tmp_path):
    """The same patience for the per-level descriptions rewritten every commit."""
    target = tmp_path / "zarr.json"
    _write_over_carefully(target, json.dumps({"generation": 1}))

    reader = held_open_briefly(target)
    _write_over_carefully(target, json.dumps({"generation": 2}))
    reader.join(timeout=5)

    assert json.loads(target.read_text(encoding="utf-8")) == {"generation": 2}


def test_a_fault_that_is_not_a_brief_hold_still_raises_at_once(tmp_path, monkeypatch):
    """Only the Windows spellings of "briefly held" are waited out.

    Anything else is a real fault, and ten seconds of hopeful retrying would
    bury it. The failure injected here is not one a hold produces, and it has
    to come straight back — measured, because "raises eventually" and "raises
    at once" look identical to an assertion alone.
    """
    import zmart_live.manifest as manifest

    target = tmp_path / "signed.json"

    def a_permanent_refusal(*_args, **_kwargs):
        trouble = PermissionError("this is not a transient hold")
        trouble.winerror = 1
        raise trouble

    monkeypatch.setattr(manifest.os, "replace", a_permanent_refusal)
    began = time.monotonic()
    with pytest.raises(PermissionError):
        _write_and_replace(target, "{}")
    assert time.monotonic() - began < 2.0, (
        "a non-transient fault was retried as though it were a brief hold"
    )


def test_a_commit_lands_while_a_reader_holds_the_views_description(tmp_path):
    """The whole per-commit sequence survives a glance at the view's metadata.

    This is the demo's own death, reproduced: a reader holding the view's
    ``zarr.json`` while a commit rewrites it. The commit has to go through and
    the description has to be whole afterwards.
    """
    profile, _ = plan_the_writing("overview", frame=FRAME, z_planes=1)
    run = LivePublisher(
        tmp_path,
        profile,
        run_id="held-run",
        cells={GridCell(0, 0): "posA", GridCell(0, 1): "posB"},
        # A reader holding the VIEW's description mid-run is the situation
        # this gate is named for, so the view has to be written mid-run.
        linked_view="per_publish",
    )
    run.write_and_publish("posA", some_specimen(1000))

    description = run.view_store / "zarr.json"
    assert description.is_file()
    reader = held_open_briefly(description, seconds=0.6)
    level_reader = held_open_briefly(run.view_level(0) / "zarr.json", seconds=0.6)
    event = run.write_and_publish("posB", some_specimen(2000))
    reader.join(timeout=5)
    level_reader.join(timeout=5)

    assert event.revision == 2
    described = json.loads(description.read_text(encoding="utf-8"))
    assert "ome" in described.get("attributes", {})


def test_describing_a_position_survives_a_hold_on_its_own_description(tmp_path):
    """The position stores are read by the viewer too, and rewritten per write."""
    profile, _ = plan_the_writing("overview", frame=FRAME, z_planes=1)
    run = LivePublisher(
        tmp_path,
        profile,
        run_id="held-position",
        cells={GridCell(0, 0): "posA"},
    )
    run.write_a_position("posA", some_specimen(1000))

    store = run.position_store("posA")
    reader = held_open_briefly(store / "zarr.json", seconds=0.5)
    described = describe_the_position(
        store,
        profile,
        channels=run.channels,
        origin_pixels=run.layout.placement("posA").origin,
    )
    reader.join(timeout=5)
    assert described["multiscales"], "the description was not rewritten"


def some_pixels() -> np.ndarray:
    return some_specimen(1234)
