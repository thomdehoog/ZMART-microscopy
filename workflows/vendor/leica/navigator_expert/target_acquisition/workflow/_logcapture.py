"""Per-kind console-log capture.

Tees the workflow's ``print()`` output into a per-acquisition-type
``logs/<kind>.log`` text file while still showing it live in the
notebook. A *tee*, not a redirect: output reaches both the real stdout
and the file.

Design notes in ``.claude/plans/plan-console-logs.md``. This is a raw
console capture, not a structured log -- ``run_summary.json`` remains
the canonical structured run record.
"""
from __future__ import annotations

import functools
import sys
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path


# Log paths with a capture currently active. Re-entrancy guard: a
# nested capture_console on the same path no-ops, so a line is never
# written to the same file twice.
_active_paths: set[Path] = set()


def _separator(label: str) -> str:
    """Header line opening a capture block, so re-runs and multi-step
    phases stay legible and time-anchored in the log."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"=== {label} | {ts} ===\n"


class _Tee:
    """A ``sys.stdout`` stand-in: writes to the original stdout and a
    file. The file write is exception-tolerant (defensive against a
    stale reference after the block exits) and flushed per write so a
    hard crash still leaves a complete log."""

    def __init__(self, original, file_obj) -> None:
        self._original = original
        self._file = file_obj
        self._lock = threading.Lock()

    def write(self, text) -> int:
        with self._lock:
            n = self._original.write(text)
            try:
                self._file.write(text)
                self._file.flush()
            except (ValueError, OSError):
                pass
            return n

    def flush(self) -> None:
        with self._lock:
            self._original.flush()
            try:
                self._file.flush()
            except (ValueError, OSError):
                pass

    def __getattr__(self, name):
        # Proxy encoding / isatty / ... to the real stdout. `_original`
        # is set in __init__ so this never recurses.
        return getattr(self._original, name)


@contextmanager
def capture_console(log_path: Path | None):
    """Tee ``sys.stdout`` to ``log_path`` (append) for the duration.

    No-op when ``log_path`` is None, or when a capture for the same
    path is already active (re-entrancy guard). Output still reaches
    the real stdout, so notebook cells show it live.
    """
    if log_path is None or log_path in _active_paths:
        yield
        return

    original = sys.stdout
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(log_path, "a", encoding="utf-8")
    except OSError as exc:
        # Logging is observational -- a locked or unwritable logs/ dir
        # must never block the workflow. Fall back to no capture.
        print(f"[logcapture] WARNING: console log disabled "
              f"({log_path}): {exc}")
        yield
        return
    _active_paths.add(log_path)
    try:
        handle.write(_separator(log_path.stem))
        handle.flush()
        sys.stdout = _Tee(original, handle)
        yield
    finally:
        sys.stdout = original
        _active_paths.discard(log_path)
        handle.close()


def _log_path_for(ctx, kind: str) -> Path | None:
    """The kind's console-log path ``<kind>/logs/<kind>.log``, or None
    when it cannot be resolved to a real ``pathlib.Path`` -- e.g. a
    ``MagicMock`` ctx in a test. The None keeps the decorator a clean
    no-op there without disabling capture for a real path."""
    try:
        path = ctx.run.layout.logs_dir(kind) / f"{kind}.log"
    except Exception:
        # Fail open: a fault resolving the log path must never break
        # the workflow -- logging is observational. None -> the
        # decorator runs the step with no capture.
        return None
    return path if isinstance(path, Path) else None


def _logged(kind: str, *, ctx_arg: int = 0):
    """Decorator: tee the wrapped step's console output into
    ``<kind>/logs/<kind>.log``.

    ``ctx`` is taken from positional ``args[ctx_arg]`` (0 for the
    free functions, 1 for the ``FocusMap.plot`` method) or from
    ``kwargs['ctx']``. ``functools.wraps`` keeps the wrapped name /
    docstring / signature -- these functions are notebook-facing.
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            ctx = kwargs.get("ctx")
            if ctx is None and len(args) > ctx_arg:
                ctx = args[ctx_arg]
            path = _log_path_for(ctx, kind) if ctx is not None else None
            with capture_console(path):
                return fn(*args, **kwargs)
        return wrapper
    return decorator


class _DeferredTee:
    """A ``sys.stdout`` stand-in that buffers output until a log file
    is bound -- for ``preflight``, which creates the run dir partway
    through, so the log path is not known up front."""

    def __init__(self, original) -> None:
        self._original = original
        self._file = None
        self._log_path = None
        self._buffer: list[str] = []
        self._disabled = False
        self._lock = threading.Lock()

    def write(self, text) -> int:
        with self._lock:
            n = self._original.write(text)
            if self._file is not None:
                try:
                    self._file.write(text)
                    self._file.flush()
                except (ValueError, OSError):
                    pass
            elif not self._disabled:
                self._buffer.append(text)
            return n

    def flush(self) -> None:
        with self._lock:
            self._original.flush()
            if self._file is not None:
                try:
                    self._file.flush()
                except (ValueError, OSError):
                    pass

    def __getattr__(self, name):
        return getattr(self._original, name)

    def bind(self, log_path) -> None:
        """Open ``log_path``, flush the buffered output into it under a
        separator, and capture there onward. No-op if already bound or
        if ``log_path`` is not a real ``pathlib.Path`` (mocked ctx)."""
        with self._lock:
            if (self._file is not None or self._disabled
                    or not isinstance(log_path, Path)):
                return
            try:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                handle = open(log_path, "a", encoding="utf-8")
            except OSError as exc:
                # Best-effort: never abort the caller. Drop the buffer
                # and disable, so later output only goes to live stdout
                # instead of accumulating in memory unbounded. Write
                # straight to the real stdout (not via print, which
                # would re-enter this locked tee).
                self._original.write(
                    f"[logcapture] WARNING: console log disabled "
                    f"({log_path}): {exc}\n"
                )
                self._buffer = []
                self._disabled = True
                return
            handle.write(_separator(log_path.stem))
            handle.write("".join(self._buffer))
            handle.flush()
            self._file = handle
            self._log_path = log_path
            self._buffer = []
            # Register the bound path so a nested capture_console on the
            # same file no-ops (re-entrancy guard) rather than wrapping
            # this tee and double-writing every line.
            _active_paths.add(log_path)


@contextmanager
def capture_console_deferred():
    """Buffering stdout tee. Yields an object with ``.bind(log_path)``
    -- call it once the log path is known; buffered output is flushed
    into the file and capture continues there. If ``.bind`` is never
    called (e.g. the caller fails before the path exists), the buffer
    is discarded."""
    original = sys.stdout
    tee = _DeferredTee(original)
    sys.stdout = tee
    try:
        yield tee
    finally:
        sys.stdout = original
        if tee._log_path is not None:
            _active_paths.discard(tee._log_path)
        if tee._file is not None:
            tee._file.close()
