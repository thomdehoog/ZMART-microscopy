"""Tests for the shared callback-flags API in run_overview / acquire_targets.

Both top-level entry points share:
  - _validate_callback_flags: mutex on (callback, live_display, save_png).
  - _build_default_*_callback: build the workflow-supplied default
    rendering callback when no explicit callback is passed.

These helpers are tested in isolation; run_overview / acquire_targets
themselves require heavy LAS X / engine mocking and stay covered by
existing integration paths.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ─── Mutex (_validate_callback_flags) ─────────────────────────────


class TestValidateCallbackFlags:
    def test_raises_when_on_tile_with_live_display_true(self):
        from pipeline.overview import _validate_callback_flags
        with pytest.raises(ValueError, match=r"Cannot pass on_tile"):
            _validate_callback_flags(
                lambda e: None,
                live_display=True, save_png=False,
                callback_param="on_tile",
            )

    def test_raises_when_on_tile_with_save_png_true(self):
        from pipeline.overview import _validate_callback_flags
        with pytest.raises(ValueError, match=r"Cannot pass on_tile"):
            _validate_callback_flags(
                lambda e: None,
                live_display=False, save_png=True,
                callback_param="on_tile",
            )

    def test_raises_when_on_target_with_live_display_true(self):
        """Same validator, parametrized by callback name. Pin the
        on_target wording for the acquire_targets path.
        """
        from pipeline.overview import _validate_callback_flags
        with pytest.raises(ValueError, match=r"Cannot pass on_target"):
            _validate_callback_flags(
                lambda p, r: None,
                live_display=True, save_png=False,
                callback_param="on_target",
            )


# ─── Default per-tile callback factory ────────────────────────────


class TestBuildDefaultOnTileCallback:
    def test_threads_flags_through_to_display_tile(self, monkeypatch):
        """When the pipeline builds the default callback internally, the
        flags passed by the operator (live_display, save_png) must reach
        display_tile unchanged. The logs_dir is filled in when
        save_png=True and is None when save_png=False.
        """
        # Patch the renderer at its module path; the local import inside
        # _build_default_on_tile_callback resolves to this patched ref.
        fake_display_tile = MagicMock(name="display_tile")
        import pipeline.visualize as viz_mod
        monkeypatch.setattr(viz_mod, "display_tile", fake_display_tile)

        ctx = MagicMock(name="ctx")
        ctx.scan_field = "fake_scan_field_dict"
        ctx.boundary_limits = "fake_limits_dict"
        ctx.run.layout.logs_dir.return_value = Path("/fake/logs")

        from pipeline.overview import _build_default_on_tile_callback

        callback = _build_default_on_tile_callback(
            ctx, live_display=True, save_png=False,
        )
        event = MagicMock(name="tile_event")
        callback(event)

        fake_display_tile.assert_called_once_with(
            event,
            scan_field="fake_scan_field_dict",
            boundary_limits="fake_limits_dict",
            logs_dir=None,             # save_png=False -> no logs dir
            live_display=True,
            save_png=False,
            hash6=ctx.run.layout.hash6,
            _save_queue=None,          # factory called with no queue
        )


class TestBuildDefaultOnTargetCallback:
    def test_threads_flags_through_to_display_target(self, monkeypatch):
        """target.py builds its default per-target callback the same way
        overview.py does. tile_cache is owned by the callback (not the
        operator notebook), so a single dict is reused across calls.
        """
        fake_display_target = MagicMock(name="display_target")
        import pipeline.visualize as viz_mod
        monkeypatch.setattr(viz_mod, "display_target", fake_display_target)

        ctx = MagicMock(name="ctx")
        ctx.run.layout.analysis_dir.return_value = Path("/fake/analysis")
        ctx.run.layout.logs_dir.return_value = Path("/fake/logs")

        from pipeline.target import _build_default_on_target_callback

        callback = _build_default_on_target_callback(
            ctx, live_display=False, save_png=True,
        )
        pick = MagicMock(name="pick")
        record = MagicMock(name="record")
        callback(pick, record)

        # tile_cache is owned by the closure (an empty dict on first call)
        kwargs = fake_display_target.call_args.kwargs
        assert kwargs["logs_dir"] == Path("/fake/logs")
        assert kwargs["live_display"] is False
        assert kwargs["save_png"] is True
        assert kwargs["tile_cache"] == {}   # fresh cache, populated by callback

        # Second invocation reuses the same cache dict instance.
        callback(pick, record)
        first_cache = fake_display_target.call_args_list[0].kwargs["tile_cache"]
        second_cache = fake_display_target.call_args_list[1].kwargs["tile_cache"]
        assert first_cache is second_cache


class TestAcquireTargetsEmptyPicks:
    def test_empty_picks_does_not_construct_save_queue(self, monkeypatch):
        """Empty Picks on the default save path must early-return without
        ever instantiating a _FigureSaveQueue. The pre-fix version built
        the queue first, then returned without shutdown, leaving an
        unowned executor.
        """
        from pipeline.selection import Picks
        from pipeline import target as target_mod
        from pipeline import _save_queue as save_queue_mod

        construct_count = {"n": 0}
        real_init = save_queue_mod._FigureSaveQueue.__init__

        def counting_init(self, *args, **kwargs):
            construct_count["n"] += 1
            real_init(self, *args, **kwargs)

        monkeypatch.setattr(
            save_queue_mod._FigureSaveQueue, "__init__", counting_init,
        )

        ctx = MagicMock(name="ctx")
        result = target_mod.acquire_targets(ctx, Picks(items=[]))

        assert result == []
        assert construct_count["n"] == 0
        assert ctx.target_state is not None
        assert ctx.target_state.started is False
