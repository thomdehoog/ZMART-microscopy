"""Tests for workflow.template.archive_and_strip (Step 2d).

Pins:
  - Pre-check refuses when on-disk state != "unstripped" (covers Step 2c
    leaving LAS X stripped with restore_template_after_af=False, AND
    re-running 2d after acquisition).
  - Refuses to overwrite an already-populated archive directory.
  - save_experiment fires before any file copy or strip_template call.
  - All three template files (xml/lrp/rgn) end up in the archive.
  - A missing source file (e.g. no .rgn on disk) warns and skips, not raises.
  - drv.strip_template is called exactly once.
  - drv.restore_template is NEVER called by 2d (the whole point is "no restore").
  - drv.save_experiment failure surfaces as RuntimeError, no copy or strip happens.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from _shared.output_layout import build_layout


@pytest.fixture
def ctx_factory(tmp_path, monkeypatch):
    """Build a minimal Context-like namespace plus a CallTracker for spies.

    Wires templates_dir under tmp_path with three placeholder files, a real
    LayoutPlan via build_layout, and a MagicMock client. Returns (ctx, calls)
    where `calls` records each driver invocation in order so tests can
    assert relative ordering between save / copy / strip / restore.
    """
    from workflow import template as template_mod

    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()
    (templates_dir / template_mod.TEMPLATE_XML).write_text("xml-content")
    (templates_dir / template_mod.TEMPLATE_LRP).write_text("lrp-content")
    (templates_dir / template_mod.TEMPLATE_RGN).write_text("rgn-content")

    layout = build_layout(tmp_path / "out", "archive-test")
    ctx = SimpleNamespace(
        cfg=SimpleNamespace(restore_template_after_af=True),
        client=MagicMock(name="client"),
        templates_dir=templates_dir,
        run=SimpleNamespace(layout=layout),
    )

    # Shared call log for ordering assertions across driver fns.
    calls: list[tuple[str, dict]] = []

    def _save_experiment(client, name, td, *, timeout=30,
                         poll_interval=0.1, confirm_path=None):
        calls.append(("save_experiment", {
            "name": name, "confirm_path": confirm_path,
        }))
        return {"success": True}

    def _strip_template(client, *, save_timeout=120):
        calls.append(("strip_template", {}))
        return {"success": True}

    def _restore_template(client):
        # Should NEVER fire from archive_and_strip. Record so tests can
        # assert absence.
        calls.append(("restore_template", {}))
        return {"success": True}

    def _get_template_state(td=None):
        return "unstripped"

    monkeypatch.setattr(template_mod.drv, "save_experiment", _save_experiment)
    monkeypatch.setattr(template_mod.drv, "strip_template", _strip_template)
    monkeypatch.setattr(template_mod.drv, "restore_template", _restore_template)
    monkeypatch.setattr(template_mod, "get_template_state", _get_template_state)
    # No-op the multi-file stability wait. The mocked save_experiment
    # doesn't touch any file, so _wait_for_file_stable would otherwise
    # burn its full 10s timeout per file (XML + RGN) for every test --
    # 20s/test × ~10 tests would push this suite to 200s for no signal.
    monkeypatch.setattr(template_mod, "_wait_for_file_stable",
                        lambda path, *, prev_mtime, timeout,
                        poll_interval=0.1: None)

    def _factory(*, state="unstripped"):
        monkeypatch.setattr(template_mod, "get_template_state",
                            lambda td=None: state)
        return ctx, calls

    return _factory


# ─── Pre-check: state ─────────────────────────────────────────────


def test_refuses_when_state_is_stripped(ctx_factory):
    """Step 2c with restore_template_after_af=False -- or a rerun of 2d
    -- leaves disk in 'stripped' state. Refuse before save_experiment
    overwrites the configured template with the stripped one."""
    from workflow.template import archive_and_strip

    ctx, calls = ctx_factory(state="stripped")
    with pytest.raises(RuntimeError, match="state is 'stripped'"):
        archive_and_strip(ctx)
    assert not any(c[0] == "save_experiment" for c in calls)
    assert not any(c[0] == "strip_template" for c in calls)


def test_refuses_when_state_is_fresh(ctx_factory):
    """'fresh' = no _PythonInspect template on disk yet. 2a hasn't run
    or the operator pointed at the wrong templates_dir; refuse."""
    from workflow.template import archive_and_strip

    ctx, calls = ctx_factory(state="fresh")
    with pytest.raises(RuntimeError, match="state is 'fresh'"):
        archive_and_strip(ctx)
    assert calls == []


# ─── Pre-check: existing archive ──────────────────────────────────


def test_refuses_when_archive_already_populated(ctx_factory):
    """The archive is the canonical workflow record for a run; a rerun
    must not silently overwrite it. Even one of the three present is
    enough to refuse."""
    from workflow import template as template_mod
    from workflow.template import archive_and_strip

    ctx, calls = ctx_factory()
    archive_dir = ctx.run.layout.metadata_dir("initialization")
    archive_dir.mkdir(parents=True, exist_ok=True)
    (archive_dir / template_mod.TEMPLATE_XML).write_text("stale")

    with pytest.raises(RuntimeError, match="archive already populated"):
        archive_and_strip(ctx)
    # The pre-existing stale file is untouched.
    assert (archive_dir / template_mod.TEMPLATE_XML).read_text() == "stale"
    assert not any(c[0] == "save_experiment" for c in calls)


# ─── Ordering: save → copy → strip ────────────────────────────────


def test_save_called_before_copy_and_strip(ctx_factory):
    """Operationally critical: save_experiment must flush operator
    edits to disk BEFORE the copy, and strip_template runs LAST so the
    archive captures the configured (not stripped) state."""
    from workflow import template as template_mod
    from workflow.template import archive_and_strip

    ctx, calls = ctx_factory()
    archive_and_strip(ctx)

    op_order = [c[0] for c in calls]
    assert op_order == ["save_experiment", "strip_template"]
    archive_dir = ctx.run.layout.metadata_dir("initialization")
    for name in (template_mod.TEMPLATE_XML, template_mod.TEMPLATE_LRP,
                 template_mod.TEMPLATE_RGN):
        assert (archive_dir / name).is_file()


def test_save_experiment_confirms_on_lrp(ctx_factory):
    """LRP is the late-updating file under the modify-lrp path per the
    driver comment in scanning_templates.py. archive_and_strip must
    confirm on it so the copy doesn't race a half-written LRP."""
    from workflow import template as template_mod
    from workflow.template import archive_and_strip

    ctx, calls = ctx_factory()
    archive_and_strip(ctx)

    save_calls = [c for c in calls if c[0] == "save_experiment"]
    assert len(save_calls) == 1
    assert save_calls[0][1]["confirm_path"] == str(
        ctx.templates_dir / template_mod.TEMPLATE_LRP)


# ─── Archive contents ─────────────────────────────────────────────


def test_copies_all_three_files_byte_for_byte(ctx_factory):
    from workflow import template as template_mod
    from workflow.template import archive_and_strip

    ctx, _ = ctx_factory()
    archive_and_strip(ctx)

    archive_dir = ctx.run.layout.metadata_dir("initialization")
    for name, expected in (
        (template_mod.TEMPLATE_XML, "xml-content"),
        (template_mod.TEMPLATE_LRP, "lrp-content"),
        (template_mod.TEMPLATE_RGN, "rgn-content"),
    ):
        assert (archive_dir / name).read_text() == expected


def test_missing_source_file_warns_and_skips(ctx_factory, capsys):
    """If LAS X never wrote a .rgn (no markers ever placed), the archive
    should warn for the missing file and still archive the others. Not
    a fatal -- the workflow xml/lrp still capture the run config."""
    from workflow import template as template_mod
    from workflow.template import archive_and_strip

    ctx, _ = ctx_factory()
    (ctx.templates_dir / template_mod.TEMPLATE_RGN).unlink()

    archive_and_strip(ctx)
    captured = capsys.readouterr().out
    assert "WARNING" in captured and template_mod.TEMPLATE_RGN in captured

    archive_dir = ctx.run.layout.metadata_dir("initialization")
    assert (archive_dir / template_mod.TEMPLATE_XML).is_file()
    assert (archive_dir / template_mod.TEMPLATE_LRP).is_file()
    assert not (archive_dir / template_mod.TEMPLATE_RGN).is_file()


# ─── Strip / restore contract ─────────────────────────────────────


def test_strip_template_called_exactly_once(ctx_factory):
    from workflow.template import archive_and_strip

    ctx, calls = ctx_factory()
    archive_and_strip(ctx)
    assert sum(1 for c in calls if c[0] == "strip_template") == 1


def test_restore_template_never_called(ctx_factory):
    """The whole point of 2d: no restore. LAS X stays stripped for the
    rest of the run."""
    from workflow.template import archive_and_strip

    ctx, calls = ctx_factory()
    archive_and_strip(ctx)
    assert not any(c[0] == "restore_template" for c in calls)


# ─── Failure paths ────────────────────────────────────────────────


def test_save_experiment_failure_raises_before_copy(ctx_factory, monkeypatch):
    """If save_experiment returns None, no archive copy should land and
    strip_template must not fire -- the configured-template flush is the
    invariant of the whole step."""
    from workflow import template as template_mod
    from workflow.template import archive_and_strip

    ctx, calls = ctx_factory()
    monkeypatch.setattr(template_mod.drv, "save_experiment",
                        lambda *a, **k: None)

    with pytest.raises(RuntimeError, match="save_experiment failed"):
        archive_and_strip(ctx)
    assert not any(c[0] == "strip_template" for c in calls)
    archive_dir = ctx.run.layout.metadata_dir("initialization")
    assert not any(archive_dir.glob("*.xml"))
