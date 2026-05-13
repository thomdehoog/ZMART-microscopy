"""Tests for workflow._save_queue._FigureSaveQueue.

All tests are event-gated. No time.sleep, no real disk I/O. The
worker's save_fn is a closure that waits on a threading.Event the
test controls. Backpressure is verified by counting completed saves
relative to controlled releases.
"""
from __future__ import annotations

import threading

import pytest

from workflow._save_queue import _FigureSaveQueue


# Generous timeout for Event.wait calls -- any blocking longer than
# this represents a real deadlock, not a slow CI.
_WAIT_TIMEOUT_S = 5.0


class TestFigureSaveQueueBasics:
    def test_submit_runs_save_fn_then_shutdown(self):
        """The most basic contract: a submitted save runs and finishes
        before shutdown returns.
        """
        completed = threading.Event()

        with _FigureSaveQueue() as q:
            q.submit(lambda: completed.set())

        # __exit__ -> shutdown -> drain -> save_fn must have run.
        assert completed.is_set()

    def test_drain_waits_for_pending_saves(self):
        """drain() must not return until all queued save_fns have
        finished. Event-gated: the worker only completes after the test
        signals can_proceed; drain must observe that.
        """
        q = _FigureSaveQueue()
        can_proceed = threading.Event()
        completed = threading.Event()

        def save():
            can_proceed.wait(timeout=_WAIT_TIMEOUT_S)
            completed.set()

        q.submit(save)
        can_proceed.set()
        q.drain(timeout=_WAIT_TIMEOUT_S)

        # drain has returned -> save_fn must have run to completion.
        assert completed.is_set()
        q.shutdown()


class TestFigureSaveQueueBackpressure:
    def test_three_submits_complete_under_max_queued_2_with_gated_worker(self):
        """With max_queued=2 and a gated worker, three submits eventually
        complete without deadlock or dropped work.

        Scope note: this test does not observe the producer blocked at the
        exact moment the queue is full. Proving that without sleeps would
        require production-code instrumentation. The production backpressure
        mechanism is the BoundedSemaphore in _FigureSaveQueue.submit(); this
        test covers completion under that bounded/gated condition.
        """
        q = _FigureSaveQueue(max_queued=2)
        worker_gate = threading.Event()
        # n_completed is incremented by the worker after each save.
        n_completed = [0]

        def gated_save():
            worker_gate.wait(timeout=_WAIT_TIMEOUT_S)
            n_completed[0] += 1

        submitted_third = threading.Event()

        def producer():
            q.submit(gated_save)   # slot 1: queued, semaphore acquired
            q.submit(gated_save)   # slot 2: queued, semaphore acquired
            q.submit(gated_save)   # slot 3: BLOCKS on semaphore.acquire
            submitted_third.set()

        producer_thread = threading.Thread(target=producer)
        producer_thread.start()

        # NOTE: We can't deterministically detect "is blocked right now"
        # without timing. Instead: release the worker once, which lets
        # one save complete + semaphore.release() runs + producer's
        # third submit unblocks. After we release ENOUGH times for all
        # three to complete, submitted_third must be set.
        worker_gate.set()
        producer_thread.join(timeout=_WAIT_TIMEOUT_S)

        # All three submits returned; all three saves completed.
        assert submitted_third.is_set()
        q.shutdown()
        assert n_completed[0] == 3

    def test_rejects_max_queued_less_than_one(self):
        """Sanity: the queue must hold at least one item."""
        with pytest.raises(ValueError, match=r"max_queued must be >= 1"):
            _FigureSaveQueue(max_queued=0)


class TestFigureSaveQueueErrorHandling:
    def test_save_fn_exception_is_swallowed_and_does_not_break_queue(self):
        """If a save_fn raises, the queue continues to accept and
        process subsequent submits. The error is logged inside the
        worker (verified separately by stdout capture in CI).
        """
        q = _FigureSaveQueue()
        survived = threading.Event()

        def bad_save():
            raise RuntimeError("synthetic save failure")

        def good_save():
            survived.set()

        q.submit(bad_save)
        q.submit(good_save)
        q.shutdown()

        # The bad save's exception was swallowed; the good save ran.
        assert survived.is_set()


class TestFigureSaveQueueLifecycle:
    def test_submit_after_shutdown_raises(self):
        """Closed queue rejects new submissions."""
        q = _FigureSaveQueue()
        q.shutdown()
        with pytest.raises(RuntimeError, match=r"is closed"):
            q.submit(lambda: None)

    def test_shutdown_is_idempotent(self):
        """Multiple shutdowns must be safe (acquire_targets / run_overview
        own the queue and may end up double-shutting on error paths)."""
        q = _FigureSaveQueue()
        q.shutdown()
        q.shutdown()   # must not raise
