"""Tests for workflow._logcapture -- per-kind console-log capture."""
from __future__ import annotations

import io
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from _shared.output_layout import build_layout
from workflow._logcapture import (
    _Tee, _log_path_for, _logged,
    capture_console, capture_console_deferred,
)


def _ctx_with_layout(tmp_path):
    """A minimal ctx whose run.layout is a real LayoutPlan under tmp_path."""
    layout = build_layout(tmp_path, "logtest")
    return SimpleNamespace(run=SimpleNamespace(layout=layout))


class TestCaptureConsole:
    def test_tees_to_file_and_stdout(self, tmp_path, capsys):
        log = tmp_path / "k.log"
        with capture_console(log):
            print("hello-tee")
        assert "hello-tee" in log.read_text()
        assert "hello-tee" in capsys.readouterr().out

    def test_stdout_restored_on_exit(self, tmp_path):
        before = sys.stdout
        with capture_console(tmp_path / "k.log"):
            assert sys.stdout is not before
        assert sys.stdout is before

    def test_stdout_restored_and_partial_log_on_exception(self, tmp_path):
        before = sys.stdout
        log = tmp_path / "k.log"
        try:
            with capture_console(log):
                print("partial")
                raise ValueError("boom")
        except ValueError:
            pass
        assert sys.stdout is before
        assert "partial" in log.read_text()

    def test_none_is_noop(self, tmp_path):
        before = sys.stdout
        with capture_console(None):
            assert sys.stdout is before          # no stdout swap
            print("x")
        assert list(tmp_path.iterdir()) == []    # no file created

    def test_append_and_separator(self, tmp_path):
        log = tmp_path / "overview-scan.log"
        with capture_console(log):
            print("first")
        with capture_console(log):
            print("second")
        text = log.read_text()
        assert text.count("=== overview-scan |") == 2
        assert "first" in text and "second" in text

    def test_reentrancy_guard_no_double_write(self, tmp_path):
        log = tmp_path / "k.log"
        with capture_console(log):
            with capture_console(log):           # same path -> inner no-ops
                print("once")
        assert log.read_text().count("once") == 1

    def test_getattr_passthrough(self):
        orig = io.StringIO()
        orig.custom_marker = "xyz"               # type: ignore[attr-defined]
        tee = _Tee(orig, io.StringIO())
        assert tee.custom_marker == "xyz"

    def test_write_tolerates_closed_file(self):
        f = io.StringIO()
        tee = _Tee(io.StringIO(), f)
        f.close()
        tee.write("after close")                 # must not raise

    def test_open_failure_is_best_effort(self, tmp_path, capsys):
        # tmp_path is a directory, so open(..., "a") raises OSError --
        # capture_console must still run the body, not propagate, so a
        # locked logs/ dir can never abort an acquisition step.
        ran = []
        with capture_console(tmp_path):
            ran.append(True)
            print("still-ran")
        assert ran == [True]
        out = capsys.readouterr().out
        assert "still-ran" in out
        assert "console log disabled" in out

    def test_write_returns_count(self):
        tee = _Tee(io.StringIO(), io.StringIO())
        assert tee.write("abc") == 3


class TestLogPathFor:
    def test_real_layout_resolves_to_path(self, tmp_path):
        path = _log_path_for(_ctx_with_layout(tmp_path), "overview-scan")
        assert isinstance(path, Path)
        assert path.name == "overview-scan.log"

    def test_mock_ctx_returns_none(self):
        assert _log_path_for(MagicMock(), "overview-scan") is None


class TestLoggedDecorator:
    def test_captures_and_preserves_metadata(self, tmp_path):
        @_logged("overview-scan")
        def step(ctx):
            """my docstring"""
            print("step-ran")
            return 42

        ctx = _ctx_with_layout(tmp_path)
        assert step(ctx) == 42
        assert step.__name__ == "step"           # functools.wraps
        assert step.__doc__ == "my docstring"
        log = ctx.run.layout.logs_dir("overview-scan") / "overview-scan.log"
        assert "step-ran" in log.read_text()

    def test_mock_ctx_is_noop(self):
        @_logged("overview-scan")
        def step(ctx):
            print("ran")
            return "ok"

        assert step(MagicMock()) == "ok"         # no capture, no crash

    def test_ctx_arg_index_for_method(self, tmp_path):
        @_logged("initialization", ctx_arg=1)
        def method(self_, ctx):
            print("method-ran")

        ctx = _ctx_with_layout(tmp_path)
        method(object(), ctx)
        log = ctx.run.layout.logs_dir("initialization") / "initialization.log"
        assert "method-ran" in log.read_text()


class TestDeferredCapture:
    def test_buffers_then_flushes_on_bind(self, tmp_path):
        log = tmp_path / "init" / "initialization.log"
        with capture_console_deferred() as cap:
            print("before-bind")
            cap.bind(log)
            print("after-bind")
        text = log.read_text()
        assert "before-bind" in text             # buffered, then flushed
        assert "after-bind" in text
        assert "=== initialization |" in text

    def test_no_bind_discards(self, tmp_path):
        with capture_console_deferred():
            print("never-filed")
        assert not any(tmp_path.rglob("*.log"))

    def test_bind_ignores_non_path(self, tmp_path):
        with capture_console_deferred() as cap:
            cap.bind(MagicMock())                # mock path -> no-op, no crash
            print("x")
        assert not any(tmp_path.rglob("*.log"))

    def test_bind_failure_disables_buffering(self, tmp_path):
        # tmp_path is a directory -> open fails -> bind drops the
        # buffer and disables, so later output does not pile up in RAM.
        with capture_console_deferred() as cap:
            print("before")
            cap.bind(tmp_path)
            print("after-failure")
            assert cap._disabled is True
            assert cap._buffer == []
