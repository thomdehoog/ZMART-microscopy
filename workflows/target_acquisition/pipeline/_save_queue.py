"""Async figure-save queue.

Move callback-path fig.savefig() off the synchronous acquisition path
so per-tile / per-target display callbacks return quickly.

Design:

- Used only by the callback-path renderers display_tile and
  display_target. Top-level/batch renderers (display_selection,
  plot_overview_tiles, plot_target_pairs) remain synchronous by
  design: with a single worker and drain-on-return, queueing those
  sites provides no wall-clock benefit.
- Single worker thread (ThreadPoolExecutor max_workers=1). PNG writes
  are serialized for ordering predictability and conservative
  matplotlib/Agg use.
- BoundedSemaphore-backed queue. submit() blocks the producer when
  the queue is full -- backpressure.
- The queued save closure owns figure lifetime on the queued path:
  it must perform fig.savefig(...) and then plt.close(fig). After
  queue handoff, the producer must not close the figure.
- Producers still build the figure and, when live_display=True, call
  display(fig) on the producer thread before queue handoff.
- Errors raised by save_fn are caught inside the worker and logged;
  they do not propagate to the acquisition loop.
- drain() waits for queued saves. shutdown() drains then closes the
  executor with wait=False. Idempotent.
- Context-manager support: `with _FigureSaveQueue() as q: ...` drains
  on exit.
"""
from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable


# Bounded enough to apply backpressure during acquisition, large enough
# that normal per-tile/per-target figure bursts do not block every frame.
_DEFAULT_MAX_QUEUED = 16
# Operator-facing drain limit: long enough for queued PNG writes, short
# enough that a broken filesystem does not hang notebook shutdown.
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

        Best-effort, not a hard guarantee: drain() waits up to `timeout`
        per pending future. Any future that does not complete within that
        window is logged as a drain failure and left running. The
        executor is then closed with wait=False so a stuck worker cannot
        block the operator; the worker thread may still be writing after
        this returns.
        """
        if self._closed:
            return
        self._closed = True
        self.drain(timeout=timeout)
        # wait=False: do not block the operator further if the worker
        # is wedged on a stuck save. Saves observed by drain() have
        # either completed or been logged as drain failures above; saves
        # that timed out may still be writing on the worker thread.
        self._executor.shutdown(wait=False)

    # ─── context manager ──────────────────────────────────────────

    def __enter__(self) -> "_FigureSaveQueue":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.shutdown()
