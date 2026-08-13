"""Deterministic checks for the browser's manifest-refresh decisions."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "frontend" / "src" / "live-refresh.js"
ENGINE = ROOT / "frontend" / "src" / "engine.js"


def _javascript(expression: str):
    finished = subprocess.run(
        [
            "node",
            "--input-type=module",
            "--eval",
            (
                f"const m = await import({json.dumps(MODULE.as_uri())});\n"
                f"const answer = await ({expression});\n"
                "console.log(JSON.stringify(answer));"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if finished.returncode == 127:
        pytest.skip("node is not installed, so the pure frontend contract could not run")
    assert finished.returncode == 0, finished.stderr
    return json.loads(finished.stdout)


def test_time_ranges_preserve_a_gap_instead_of_using_declared_shape():
    answer = _javascript(
        "[m.momentsInRanges([{start: 0, stop: 2}, {start: 4, stop: 5}]), "
        "m.momentsInRanges([{start: 0, stop: 3}, {start: 2, stop: 4}])]"
    )
    assert answer == [[0, 1, 4], []]


def test_regressing_foreign_damaged_and_revision_url_state_is_rejected():
    answer = _javascript(
        """
        (() => {
          const source = {
            source_id: "linked/overview", role: "linked",
            url: "views/overview.ome.zarr", revision: 4,
            layout_revision: 1,
            committed_time_ranges: [{start: 0, stop: 2}],
          };
          const run = {
            dataset: 0, run_id: "run-a", revision: 4, layout_revision: 1,
            freshness: "current", sources: [source],
          };
          const state = {schema: "zmart-live-frontend-state-set/1", runs: [run]};
          const changed = (patch, sourcePatch = {}) => ({
            ...state,
            runs: [{...run, ...patch, sources: [{...source, ...sourcePatch}]}],
          });
          return {
            same: m.liveStateProblem(state, state),
            damaged: m.liveStateProblem(state, changed({freshness: "degraded", error: "torn"})),
            regressing: m.liveStateProblem(state, changed({revision: 3}, {revision: 3})),
            foreign: m.liveStateProblem(state, changed({run_id: "run-b"})),
            changedUrl: m.liveStateProblem(state, changed({}, {url: `${source.url}?revision=5`})),
          };
        })()
        """
    )
    assert answer["same"] is None
    assert "torn" in answer["damaged"]
    assert "regress" in answer["regressing"]
    assert "identity" in answer["foreign"]
    assert "URL" in answer["changedUrl"]


def test_only_a_strictly_higher_affected_source_revision_is_selected():
    answer = _javascript(
        """
        (() => {
          const urls = ["http://viewer/data/a/|zarr3:", "http://viewer/data/b/|zarr3:"];
          const before = m.sourceRevisionsFor(urls, ["run/a", "run/b"], [7, 11]);
          const remembered = m.rememberedSourceRevisions(before);
          const after = m.sourceRevisionsFor(urls, ["run/a", "run/b"], [8, 11]);
          const duplicate = m.sourceRevisionsFor(urls, ["run/a", "run/b"], [7, 11]);
          return {
            advanced: m.advancingSourceRevisions(remembered, after).map(([id]) => id),
            duplicate: m.advancingSourceRevisions(remembered, duplicate).map(([id]) => id),
          };
        })()
        """
    )
    assert answer == {"advanced": ["run/a"], "duplicate": []}


def test_cache_selection_is_exact_and_separates_metadata_from_decoded_absence():
    answer = _javascript(
        """
        (() => {
          const one = "http://viewer/data/0/overview.ome.zarr/";
          const questions = [
            `metadata:${one}.zattrs`,
            `{"constructorId":9,"url":"${one}0/c/0"}`,
            "metadata:http://viewer/data/0/overview.ome.zarr2/.zattrs",
            "metadata:http://viewer/data/1/unrelated.ome.zarr/.zattrs",
          ];
          return m.memoEntriesForStableSource(questions, `${one}|zarr3:`);
        })()
        """
    )
    assert len(answer["metadata"]) == 1
    assert len(answer["decoded"]) == 1
    assert all("unrelated" not in key and "zarr2" not in key for key in sum(answer.values(), []))


def test_manifest_refresh_invalidates_only_matching_decoded_holders():
    """The forgetting is scoped to one store's memoized entries, never a sweep.

    The window is the function's own body, ending at its closing brace at
    column zero. Neighbours are deliberately outside it: the surgical
    per-chunk refresh below this function reaches the engine's shared holder
    map legitimately, and this contract is about `forgetOneStableSource`
    alone not doing that.
    """
    source = ENGINE.read_text(encoding="utf-8")
    start = source.index("function forgetOneStableSource")
    stop = source.index("\n}", start)
    narrowed = source[start:stop]
    assert "memoEntriesForStableSource" in narrowed
    assert "for (const question of matching.decoded)" in narrowed
    assert "remembered.get(question)" in narrowed
    assert "chunkManager?.rpc?.objects" not in narrowed
