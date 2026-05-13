"""Async figure-save queue (Bundle A / A4).

Move per-figure fig.savefig() off the synchronous caller path so that
per-tile / per-target callbacks return quickly. The acquisition loop
no longer pays ~1 s/tile for matplotlib's PNG encode.

Design (decided in Bundle A):

- Single worker thread (ThreadPoolExecutor max_workers=1). PNG writes
  do not parallelize cleanly (no Agg-thread-safety guarantees beyond
  serialization; ordering predictability matters for the operator).
- BoundedSemaphore-backed queue. submit() blocks the producer when the
  queue is full -- backpressure. Default cap is max(16, 2 * n_tiles)
  set by the owner (run_overview / acquire_targets / top-level
  renderer).
- Errors raised by user-provided save_fn are caught inside the worker
  and logged; they do not propagate to the producer. The acquisition
  loop must not crash because a single PNG write fails.
- drain() waits for all in-flight saves. shutdown() drains then closes
  the executor with wait=False. Idempotent.
- Context-manager support: `with _FigureSaveQueue() as q: ...` drains
  on exit.

Threading constraints addressed elsewhere:
- matplotlib figures: callers should build + display + close on the
  main thread; only the file write is queued. The queued save_fn is
  expected to be a closure that captures everything it needs.
"""
from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable


_DEFAULT_MAX_QUEUED = 16
_DEFAULT_SHUTDOWN_TIMEOUT_S = 30.0


class _FigureSaveQueue:
    """Single-worker, bounded, blocking-submit save queue.

    Producers (callbacks, top-level renderers) call submit(save_fn).
    The worker drains the queue serially. drain() / shutdown() are
    called by the owner before returning to the operator so files
    promised by call-return are present on disk.
    """

    def __init__(
        self,
        *,
        max_queued: int = _DEFAULT_MAX_QUEUED,
        name: str = "figsave",
    ) -> None:
        if max_queued < 1:
            raise ValueError(
                f"max_queued must be >= 1, got {max_queued}"
            )
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix=name,
        )
        self._semaphore = threading.BoundedSemaphore(max_queued)
        self._futures: list[Future] = []
        self._closed = False
        self._name = name

    def submit(self, save_fn: Callable[[], None], *, label: str = "") -> None:
        """Queue a save. Blocks when the queue is full (backpressure).

        save_fn is the closure that performs the actual write (typically
        fig.savefig(path, dpi=...)). Exceptions raised by save_fn are
        caught inside the worker and logged; they do not propagate.
        """
        if self._closed:
            raise RuntimeError(
                f"_FigureSaveQueue({self._name!r}) is closed; cannot submit."
            )
        # Block until the worker has drained at least one slot. With
        # max_workers=1 this is also the natural backpressure point.
        self._semaphore.acquire()
        future = self._executor.submit(self._run, save_fn, label)
        self._futures.append(future)

    def _run(self, save_fn: Callable[[], None], label: str) -> None:
        try:
            save_fn()
        except Exception as exc:
            print(
                f"[{self._name}] WARNING: save failed "
                f"({label or 'unlabeled'}): {exc}"
            )
        finally:
            self._semaphore.release()

    def drain(self, *, timeout: float | None = None) -> None:
        """Wait for all queued saves to complete. Idempotent."""
        if not self._futures:
            return
        pending = self._futures
        self._futures = []
        for future in pending:
            try:
                future.result(timeout=timeout)
            except Exception as exc:
                # _run already swallows save_fn exceptions; this branch
                # catches TimeoutError or executor-internal failures.
                print(
                    f"[{self._name}] WARNING: drain wait failed: {exc}"
                )

    def shutdown(
        self,
        *,
        timeout: float | None = _DEFAULT_SHUTDOWN_TIMEOUT_S,
    ) -> None:
        """Drain in-flight saves (with timeout) then close the executor.
        Safe to call multiple times.
        """
        if self._closed:
            return
        self._closed = True
        self.drain(timeout=timeout)
        # wait=False: do not block the operator further if the worker
        # is wedged on a stuck save. Saves submitted before shutdown
        # have either drained or been logged as drain failures above.
        self._executor.shutdown(wait=False)

    # ─── context manager ──────────────────────────────────────────

    def __enter__(self) -> "_FigureSaveQueue":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.shutdown()
