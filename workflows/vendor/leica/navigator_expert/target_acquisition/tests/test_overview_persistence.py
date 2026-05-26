"""Tests for the rev7 NPZ v2 schema + overview_meta.json + load_overview_result.

These tests exercise the persistence layer in isolation -- no hardware,
no full run_overview. The same-kernel == load_overview_result invariant
is enforced at the building-block level here; the end-to-end check lives
in smoke_visualization.py.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
from unittest import mock

import numpy as np
import pytest

from workflow.overview import (
    OverviewResult,
    Pick,
    Picks,
    _build_npz_extra_arrays,
    _picks_from_result,
    _save_single_tile_analysis,
    _write_overview_meta,
)
from workflow.selection import load_overview_result


def _make_pick(
    rid="0", row=0, col=0, label=1,
    *,
    area=42, intensity=100.0, x_um=10.0, y_um=20.0,
) -> Pick:
    return Pick(
        pick_id=(rid, row, col, label),
        tile_stage_xy_um=(x_um, y_um),
        tile_zwide_um=0.5,
        source_pixel_size_um=(0.65, 0.65),
        source_image_size_px=(2048, 2048),
        centroid_col_row_px=(1000.0, 1000.0),
        bbox_px=(990, 990, 1010, 1010),
        bbox_um=(13.0, 13.0),
        area_px=area,
        eccentricity=0.5,
        mean_intensity=intensity,
        cell_source_stage_xy_um=(x_um + 0.5, y_um + 0.5),
    )


def _make_result(
    *,
    tile_id=("0", 0, 0),
    naming_p=0,
    picks=None,
    image_2d=None,
    masks=None,
):
    if image_2d is None:
        image_2d = np.zeros((16, 16), dtype=np.float64)
    if masks is None:
        masks = np.zeros((16, 16), dtype=np.int32)
    return {
        "input": {
            "tile_id": tile_id,
            "naming_p": naming_p,
            "image_path": "/fake.tiff",
        },
        "segment_tile": {
            "image_2d": image_2d,
            "masks": masks,
            "n_cells": len(picks) if picks else 0,
        },
        "pick_targets": {
            "picks": [
                {
                    "pick_id": list(p.pick_id),
                    "tile_stage_xy_um": list(p.tile_stage_xy_um),
                    "tile_zwide_um": p.tile_zwide_um,
                    "source_pixel_size_um": list(p.source_pixel_size_um),
                    "source_image_size_px": list(p.source_image_size_px),
                    "centroid_col_row_px": list(p.centroid_col_row_px),
                    "bbox_px": list(p.bbox_px),
                    "bbox_um": list(p.bbox_um),
                    "area_px": p.area_px,
                    "eccentricity": p.eccentricity,
                    "mean_intensity": p.mean_intensity,
                    "cell_source_stage_xy_um": list(p.cell_source_stage_xy_um),
                }
                for p in (picks or [])
            ],
        },
    }


def _save_tile_with_picks(
    analysis_dir: Path,
    result: dict,
    *,
    hash6: str = "abc123",
) -> bool:
    """Save a tile through _save_single_tile_analysis with extra_arrays."""
    analysis_dir.mkdir(parents=True, exist_ok=True)
    tile_picks = _picks_from_result(result)
    return _save_single_tile_analysis(
        result, analysis_dir,
        hash6=hash6,
        acquisition_type="overview-scan",
        extra_arrays=_build_npz_extra_arrays(tile_picks),
    )


# ─── NPZ schema v2 round-trip ──────────────────────────────────────


class TestPicksRoundtripThroughNPZ:
    def test_shapes_and_values_round_trip(self, tmp_path):
        analysis_dir = tmp_path / "analysis"
        picks = [
            _make_pick(label=1, area=100, intensity=50.0, x_um=10, y_um=20),
            _make_pick(label=2, area=200, intensity=75.0, x_um=11, y_um=21),
            _make_pick(label=3, area=300, intensity=99.0, x_um=12, y_um=22),
        ]
        result = _make_result(tile_id=("0", 0, 0), naming_p=0, picks=picks)
        assert _save_tile_with_picks(analysis_dir, result)

        npz = list(analysis_dir.glob("*.npz"))[0]
        with np.load(npz, allow_pickle=True) as data:
            assert int(data["schema_version"]) == 2
            n = 3
            assert data["cell_labels"].shape == (n,)
            assert data["cell_area_px"].shape == (n,)
            assert data["cell_mean_intensity"].shape == (n,)
            assert data["pick_tile_stage_xy_um"].shape == (n, 2)
            assert data["pick_tile_zwide_um"].shape == (n,)
            assert data["pick_source_pixel_size_um"].shape == (n, 2)
            assert data["pick_source_image_size_px"].shape == (n, 2)
            assert data["pick_centroid_col_row_px"].shape == (n, 2)
            assert data["pick_bbox_px"].shape == (n, 4)
            assert data["pick_bbox_um"].shape == (n, 2)
            assert data["pick_eccentricity"].shape == (n,)
            assert data["pick_cell_source_stage_xy_um"].shape == (n, 2)

        # Full reconstruction via load_overview_result
        ov = load_overview_result(analysis_dir)
        assert len(ov.all_picks) == 3
        for orig, loaded in zip(picks, ov.all_picks):
            assert orig.pick_id == loaded.pick_id
            assert orig.tile_stage_xy_um == loaded.tile_stage_xy_um
            assert orig.bbox_px == loaded.bbox_px
            assert orig.bbox_um == loaded.bbox_um
            assert orig.area_px == loaded.area_px
            assert orig.eccentricity == pytest.approx(loaded.eccentricity)
            assert orig.mean_intensity == pytest.approx(loaded.mean_intensity)
            assert orig.cell_source_stage_xy_um == loaded.cell_source_stage_xy_um


class TestEmptyTileNPZHasCorrectShapes:
    def test_empty_tile_uses_K_shape_not_1d(self, tmp_path):
        analysis_dir = tmp_path / "analysis"
        result = _make_result(tile_id=("0", 0, 0), naming_p=0, picks=[])
        assert _save_tile_with_picks(analysis_dir, result)

        npz = list(analysis_dir.glob("*.npz"))[0]
        with np.load(npz, allow_pickle=True) as data:
            # (0, K) preserved -- not flattened to (0,)
            assert data["pick_bbox_px"].shape == (0, 4)
            assert data["pick_tile_stage_xy_um"].shape == (0, 2)
            assert data["pick_bbox_um"].shape == (0, 2)
            assert data["pick_centroid_col_row_px"].shape == (0, 2)
            assert data["pick_source_image_size_px"].shape == (0, 2)
            assert data["pick_source_pixel_size_um"].shape == (0, 2)
            assert data["pick_cell_source_stage_xy_um"].shape == (0, 2)
            assert data["cell_labels"].shape == (0,)
            assert data["cell_area_px"].shape == (0,)
            assert data["cell_mean_intensity"].shape == (0,)
            assert data["pick_tile_zwide_um"].shape == (0,)
            assert data["pick_eccentricity"].shape == (0,)

    def test_empty_tile_loader_round_trips_without_crash(self, tmp_path):
        analysis_dir = tmp_path / "analysis"
        result = _make_result(tile_id=("0", 0, 0), naming_p=0, picks=[])
        assert _save_tile_with_picks(analysis_dir, result)

        ov = load_overview_result(analysis_dir)
        assert ov.all_picks == []
        assert ov.tile_cell_counts == {("0", 0, 0): 0}
        assert ov.n_tiles == 1
        assert ov.n_tiles_empty == 1


# ─── load_overview_result ──────────────────────────────────────────


class TestLoadOverviewResultSkipsOldSchema:
    def test_v1_files_excluded_from_picks_and_tile_cell_counts(
        self, tmp_path, capsys,
    ):
        """v1 NPZs (without schema_version key) must NOT contribute to
        either the picks list or tile_cell_counts. Loader warns per file."""
        analysis_dir = tmp_path / "analysis"
        analysis_dir.mkdir(parents=True)

        # v1 NPZ -- no schema_version key
        np.savez_compressed(
            analysis_dir / "v1_tile.npz",
            image_2d=np.zeros((4, 4)),
            masks=np.zeros((4, 4), dtype=np.int32),
            tile_id=np.array(("0", "0", "0"), dtype=str),
        )

        # v2 NPZ with 1 pick
        result = _make_result(
            tile_id=("0", 1, 1), naming_p=1,
            picks=[_make_pick(rid="0", row=1, col=1, label=5)],
        )
        assert _save_tile_with_picks(analysis_dir, result)

        ov = load_overview_result(analysis_dir)

        assert len(ov.all_picks) == 1
        assert ov.all_picks[0].pick_id == ("0", 1, 1, 5)
        assert ov.tile_cell_counts == {("0", 1, 1): 1}
        assert ov.n_tiles == 1   # v1 file did NOT inflate count

        out = capsys.readouterr().out
        assert "schema v1" in out


class TestLoadOverviewResultPopulatesTileCellCounts:
    def test_three_tiles_mixed_counts_including_empty(self, tmp_path):
        analysis_dir = tmp_path / "analysis"
        # tile A: 5 picks
        a_picks = [_make_pick(rid="0", row=0, col=0, label=i) for i in range(1, 6)]
        _save_tile_with_picks(
            analysis_dir, _make_result(tile_id=("0", 0, 0), naming_p=0, picks=a_picks),
        )
        # tile B: 0 picks
        _save_tile_with_picks(
            analysis_dir, _make_result(tile_id=("0", 0, 1), naming_p=1, picks=[]),
        )
        # tile C: 12 picks
        c_picks = [_make_pick(rid="0", row=1, col=0, label=i) for i in range(1, 13)]
        _save_tile_with_picks(
            analysis_dir, _make_result(tile_id=("0", 1, 0), naming_p=2, picks=c_picks),
        )

        ov = load_overview_result(analysis_dir)

        assert ov.tile_cell_counts == {
            ("0", 0, 0): 5,
            ("0", 0, 1): 0,
            ("0", 1, 0): 12,
        }
        assert ov.n_tiles == 3
        assert ov.n_tiles_empty == 1
        assert len(ov.all_picks) == 17


# ─── overview_meta.json ────────────────────────────────────────────


class TestOverviewMetaPersistedAndLoaded:
    def test_round_trip_through_disk(self, tmp_path):
        analysis_dir = tmp_path / "analysis"
        # Use lists, not tuples: JSON round-trip collapses tuples to lists.
        # The production writer (run_overview) does `list(tile_id)` for
        # exactly this reason.
        tile_acquire_failures = [
            {"tile_id": ["0", 0, 0], "error": "stage_xy"},
            {"tile_id": ["0", 0, 1], "error": "z_clip"},
        ]
        engine_failures = [{"job_id": 7, "error": "engine_oops"}]
        npz_save_failures = [{"tile_id": ["0", 1, 1], "reason": "save_returned_false"}]

        _write_overview_meta(
            analysis_dir,
            n_tiles_planned=10,
            n_tiles_submitted=8,
            tile_acquire_failures=tile_acquire_failures,
            engine_failures=engine_failures,
            npz_save_failures=npz_save_failures,
            completed=True,
        )

        ov = load_overview_result(analysis_dir)

        assert ov.tile_acquire_failures == tile_acquire_failures
        assert ov.engine_failures == engine_failures
        assert ov.npz_save_failures == npz_save_failures
        assert ov.n_tiles_planned == 10
        assert ov.n_tiles_submitted == 8
        assert ov.completed is True


class TestOverviewMetaCorruptJsonTolerated:
    def test_truncated_json_does_not_crash_loader(self, tmp_path, capsys):
        analysis_dir = tmp_path / "analysis"
        analysis_dir.mkdir(parents=True)

        # Write a valid v2 NPZ
        result = _make_result(
            tile_id=("0", 0, 0), naming_p=0,
            picks=[_make_pick(rid="0", row=0, col=0, label=1)],
        )
        _save_tile_with_picks(analysis_dir, result)

        # Write truncated meta JSON
        (analysis_dir / "overview_meta.json").write_text('{"completed": tru')

        ov = load_overview_result(analysis_dir)
        out = capsys.readouterr().out

        # Loader warned + defaulted
        assert "unreadable" in out or "WARNING" in out
        assert ov.tile_acquire_failures == []
        assert ov.engine_failures == []
        assert ov.npz_save_failures == []
        assert ov.completed is False
        # NPZ data still loaded
        assert len(ov.all_picks) == 1
        assert ov.n_tiles == 1


class TestOverviewMetaMissingMarkedIncomplete:
    def test_missing_meta_warns_and_loads_npz_only(self, tmp_path, capsys):
        analysis_dir = tmp_path / "analysis"
        result = _make_result(
            tile_id=("0", 0, 0), naming_p=0,
            picks=[_make_pick(rid="0", row=0, col=0, label=1)],
        )
        _save_tile_with_picks(analysis_dir, result)

        # No meta file written
        ov = load_overview_result(analysis_dir)
        out = capsys.readouterr().out

        assert "no overview_meta.json" in out
        assert ov.completed is False
        assert len(ov.all_picks) == 1


class TestOverviewMetaPersistsAcquireLoopCounters:
    def test_planned_and_submitted_round_trip(self, tmp_path):
        # Plan 2 -- n_tiles_acquired is now a stored counter (not a
        # derived `submitted - acquire_failed`), because hijack failures
        # land between acquire-and-submit and break that identity. The
        # write path must persist it; the round-trip just reads it back.
        analysis_dir = tmp_path / "analysis"
        _write_overview_meta(
            analysis_dir,
            n_tiles_planned=10,
            n_tiles_submitted=8,
            n_tiles_acquired=9,
            tile_acquire_failures=[{"tile_id": ("0", 0, 0), "error": "x"}],
            engine_failures=[{"job_id": 1, "error": "y"}],
            npz_save_failures=[],
            completed=True,
        )

        ov = load_overview_result(analysis_dir)

        assert ov.n_tiles_planned == 10
        assert ov.n_tiles_submitted == 8
        assert ov.n_tiles_acquired == 9


# run_overview_with_picks compat wrapper was deleted in Commit C; its
# behavior is now covered by tests against `select_targets` (in
# test_selection.py) plus the integration smoke at smoke_visualization.py.


# ─── Position (flat tile index) round-trip ─────────────────────────


class TestPositionRoundtripThroughNPZ:
    """The flat tile index "Position N" == the overview-scan file index
    naming_p. It threads result["input"]["naming_p"] -> Pick.position
    and -> the NPZ "position" key -> load_overview_result."""

    def test_picks_from_result_carries_naming_p(self):
        result = _make_result(
            tile_id=("0", 0, 0), naming_p=7,
            picks=[_make_pick(label=1), _make_pick(label=2)],
        )
        picks = _picks_from_result(result)
        assert [p.position for p in picks] == [7, 7]

    def test_position_round_trips_npz_to_load_overview_result(self, tmp_path):
        analysis_dir = tmp_path / "analysis"
        result = _make_result(
            tile_id=("0", 0, 0), naming_p=41, picks=[_make_pick(label=1)],
        )
        assert _save_tile_with_picks(analysis_dir, result)
        ov = load_overview_result(analysis_dir)
        assert len(ov.all_picks) == 1
        assert ov.all_picks[0].position == 41

    def test_v2_npz_without_position_loads_as_none(self, tmp_path):
        """Back-compat: a v2 NPZ written before the `position` key
        existed must load with Pick.position is None, not error."""
        analysis_dir = tmp_path / "analysis"
        result = _make_result(
            tile_id=("0", 0, 0), naming_p=3, picks=[_make_pick(label=1)],
        )
        assert _save_tile_with_picks(analysis_dir, result)
        # Rewrite the NPZ stripped of `position`, simulating a file
        # written before this change (still schema v2 otherwise).
        npz_path = list(analysis_dir.glob("*.npz"))[0]
        with np.load(npz_path, allow_pickle=True) as data:
            assert "position" in data.files   # the save path writes it
            kept = {k: data[k] for k in data.files if k != "position"}
        np.savez_compressed(npz_path, **kept)
        ov = load_overview_result(analysis_dir)
        assert len(ov.all_picks) == 1
        assert ov.all_picks[0].position is None


# ─── analysis_image_source removal -- back-compat seam pin ────────


class TestPrePlan2NpzBackCompat:
    """Pin the load-boundary back-compat seam.

    After the analysis_image_source removal commit (Plan 2 §6 / D1
    coupled cleanup), the active codebase no longer writes the
    ``analysis_image_source`` NPZ key and no longer carries the
    ``simulated`` derivation outside this single load site. Pre-cut
    NPZs on disk still have ``analysis_image_source`` and may lack
    ``simulated`` -- the visualize.py loader must derive ``simulated``
    from the old field so legacy runs reload correctly.

    This test pins that derivation. If a future contributor deletes
    the back-compat branch in ``_load_tile_npz`` thinking it's dead
    code, this test breaks loudly and names the contract.
    """

    def _write_legacy_npz(
        self, path: Path, *, analysis_image_source: str, tile_id=("0", 0, 0),
    ) -> None:
        """Write a synthetic pre-Plan-2 NPZ carrying just the keys
        ``_load_tile_npz`` actually reads: ``image_2d``, ``masks``,
        ``tile_id``, and the legacy ``analysis_image_source`` (the
        seam under test). The pre-cut on-disk shape carried other
        schema-v2 arrays too; we don't write them here because the
        test exercises ``_load_tile_npz`` directly, not the
        ``load_overview_result`` aggregate which would consume the
        per-cell arrays. Keep the fixture minimal to the assertion
        surface."""
        np.savez_compressed(
            path,
            image_2d=np.zeros((16, 16), dtype=np.float64),
            masks=np.zeros((16, 16), dtype=np.int32),
            tile_id=np.array(tile_id, dtype=str),
            analysis_image_source=np.array(analysis_image_source),
        )

    def test_legacy_acquired_derives_simulated_false(self, tmp_path):
        from workflow.visualize import _load_tile_npz
        path = tmp_path / "tile.npz"
        self._write_legacy_npz(path, analysis_image_source="acquired")
        loaded = _load_tile_npz(path)
        assert loaded is not None
        assert loaded.simulated is False

    def test_legacy_skimage_human_mitosis_derives_simulated_true(self, tmp_path):
        from workflow.visualize import _load_tile_npz
        path = tmp_path / "tile.npz"
        self._write_legacy_npz(
            path, analysis_image_source="skimage_human_mitosis",
        )
        loaded = _load_tile_npz(path)
        assert loaded is not None
        assert loaded.simulated is True

    def test_post_cut_npz_with_simulated_takes_precedence(self, tmp_path):
        """A post-cut NPZ has ``simulated`` and no
        ``analysis_image_source``. The loader must read ``simulated``
        directly without consulting the legacy field. Fixture is
        intentionally minimal to the assertion surface (see
        ``_write_legacy_npz``)."""
        from workflow.visualize import _load_tile_npz
        path = tmp_path / "tile.npz"
        np.savez_compressed(
            path,
            image_2d=np.zeros((16, 16), dtype=np.float64),
            masks=np.zeros((16, 16), dtype=np.int32),
            tile_id=np.array(("0", 0, 0), dtype=str),
            simulated=np.bool_(True),
        )
        loaded = _load_tile_npz(path)
        assert loaded is not None
        assert loaded.simulated is True


# ─── analysis_image_source removal -- single-trace structural test ─


class TestAnalysisImageSourceSingleTrace:
    """Structurally enforce 'one mock mechanism' across the codebase.

    After the cut, the identifier ``analysis_image_source`` may
    appear as **active Python code** -- a dict key, kwarg, attribute
    access, name, or type annotation -- in only two places: the
    load-boundary back-compat read in ``_load_tile_npz`` (the
    legitimate seam for forward-compatible code) and this test file
    (which constructs synthetic pre-Plan-2 NPZs to exercise that
    seam).

    A future contributor re-adding the field as a Config attribute,
    a submit-dict key, a TileEvent field, an NPZ writer key, a
    fixture argument, etc., breaks this test loudly. The breakage
    names the contract: "we removed this concept; the hijack is the
    dry-run mechanism. Don't re-introduce it under a new disguise."

    Comments and docstrings are NOT counted as offenders -- they
    document the removal, which is exactly what we want preserved
    for future readers grepping the codebase ("why is this gone?").
    The check is AST-based and walks only nodes that represent
    runtime behaviour: ``Name``, ``Attribute``, ``keyword`` (kwarg),
    string literals NOT used as docstrings, and arg/annotation
    names. Pure prose stays in.

    Notebook .ipynb files are skipped because their JSON encoding
    produces noisy matches that are operator-controlled, not
    code-controlled. The v3.1 notebook cleanup is pinned by operator
    review; smart_microscopy_v3.ipynb is the operator's dirty working
    copy and explicitly off-limits.
    """

    # Files (relative to the notebooks/ root) allowed to mention the
    # identifier in active code. The set is intentionally tiny -- if
    # it grows, the cleanup is incomplete.
    ALLOWLIST = frozenset({
        "target_acquisition/workflow/visualize.py",              # back-compat read
        "target_acquisition/tests/test_overview_persistence.py", # this test file
    })

    _TARGET = "analysis_image_source"

    @classmethod
    def _docstring_node_ids(cls, tree: ast.AST) -> set[int]:
        """ids of Constant string nodes that are docstrings (first
        Expr in a module/class/function body whose value is a str
        Constant)."""
        ids: set[int] = set()
        for scope in [tree] + [
            n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                              ast.ClassDef, ast.Module))
        ]:
            body = getattr(scope, "body", None)
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                ids.add(id(body[0].value))
        return ids

    @classmethod
    def _code_references(cls, path: Path) -> list[str]:
        """Return human-readable descriptions of every active-code
        reference to the target identifier. Returns [] for files
        that only mention it in comments or docstrings.
        """
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        # Fast exit: no occurrences at all.
        if cls._TARGET not in text:
            return []
        try:
            tree = ast.parse(text)
        except SyntaxError:
            # Not parseable Python (partial WIP, fragment) -- be
            # conservative and skip rather than block on it.
            return []
        docstrings = cls._docstring_node_ids(tree)
        refs: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == cls._TARGET:
                refs.append(f"line {node.lineno}: Name `{cls._TARGET}`")
            elif isinstance(node, ast.Attribute) and node.attr == cls._TARGET:
                refs.append(f"line {node.lineno}: Attribute `.{cls._TARGET}`")
            elif isinstance(node, ast.keyword) and node.arg == cls._TARGET:
                refs.append(f"line {node.lineno}: kwarg `{cls._TARGET}=`")
            elif isinstance(node, ast.arg) and node.arg == cls._TARGET:
                refs.append(f"line {node.lineno}: parameter `{cls._TARGET}`")
            elif (isinstance(node, ast.Constant)
                  and isinstance(node.value, str)
                  and cls._TARGET in node.value
                  and id(node) not in docstrings):
                refs.append(
                    f"line {node.lineno}: string literal "
                    f"{node.value!r}"
                )
        return refs

    def test_only_back_compat_seam_and_this_test_use_field(self):
        notebooks_root = Path(__file__).resolve().parents[2]
        offenders: list[str] = []
        for path in notebooks_root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            rel = path.relative_to(notebooks_root).as_posix()
            if rel in self.ALLOWLIST:
                continue
            refs = self._code_references(path)
            if refs:
                offenders.append(f"{rel}:\n    " + "\n    ".join(refs))

        assert not offenders, (
            f"Active-code references to `{self._TARGET}` are only "
            f"allowed in {sorted(self.ALLOWLIST)}.\n"
            f"Found additional code references:\n\n"
            + "\n\n".join(offenders)
            + "\n\nThe hijack (cfg.simulate) is the single dry-run "
              "mechanism. Comments and docstrings explaining the "
              "removal are fine -- this test ignores them. Do not "
              "re-introduce the field as active code."
        )
