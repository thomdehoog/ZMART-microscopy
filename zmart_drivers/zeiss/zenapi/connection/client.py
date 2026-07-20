"""
ZenClient: the async->blocking bridge.
======================================
ZEN API is fully async (grpclib/asyncio); the driver's public surface is
synchronous (like the Leica driver) so operator notebooks stay 1-3 lines.
``ZenClient`` is the bridge and the ``client`` handle every command/reader
takes -- the ZEN analog of the Leica ``client``.

Why a persistent event-loop thread (not ``asyncio.run`` per call):
  1. A grpclib ``Channel`` is bound to the loop it was created on; a per-call
     loop would force a fresh TLS/HTTP-2 handshake on every command.
  2. Server-streaming RPCs (status, pixels) are long-lived async iterators
     consumed concurrently with unary calls -- only a persistent loop can host
     a background stream while ``submit()`` runs unary RPCs.
  3. HTTP/2 multiplexes both over one connection.

The channel is built ON the loop thread (``_call_on_loop``) so grpclib binds it
to the right loop. ``submit`` runs one coroutine to completion and returns its
result (or re-raises its exception) on the caller thread. ``stream`` bridges a
server-streaming async iterator into a blocking generator.

Testability: ``channel_factory``, ``stub_factory``, and ``messages`` are all
injectable, so offline tests run the REAL bridge (real loop thread, real submit/
stream) over fakes -- only the wire is faked.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import queue
import threading
from collections.abc import Callable, Iterator
from typing import Any

from ..config.timing import CALL_TIMEOUT

log = logging.getLogger(__name__)

_STREAM_END = object()  # queue sentinel: the pump finished/was cancelled


class ZenClient:
    """Synchronous handle over an async grpclib connection to a ZEN gateway.

    Args:
        metadata: gRPC metadata (the control-token header) attached to stubs.
        channel_factory: zero-arg callable returning a Channel; invoked on the
            loop thread so the channel binds to this client's loop.
        stub_factory: ``(key, channel, metadata) -> stub`` building a subsystem
            stub ("stage"|"focus"|"objective"|"experiment"|"experiment_streaming").
        messages: request-message provider (see zen_runtime.RealMessages).
        default_call_timeout: default per-RPC deadline (seconds).
        connect_timeout: deadline for building the channel (seconds).
    """

    def __init__(
        self,
        *,
        metadata: list[tuple[str, str]],
        channel_factory: Callable[[], Any],
        stub_factory: Callable[[str, Any, Any], Any],
        messages: Any,
        default_call_timeout: float = CALL_TIMEOUT,
        connect_timeout: float = 10.0,
    ) -> None:
        self._metadata = metadata
        self._stub_factory = stub_factory
        self.messages = messages
        self._default_call_timeout = default_call_timeout
        self._stubs: dict[str, Any] = {}
        self._objectives_cache: list | None = None
        self._closed = False

        # Start the dedicated event-loop thread.
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, name="zenapi-loop", daemon=True)
        self._thread.start()

        # Build the channel ON the loop thread so grpclib binds it correctly.
        self._channel = self._call_on_loop(channel_factory, timeout=connect_timeout)

    # -- loop plumbing --------------------------------------------------------

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _call_on_loop(self, fn: Callable[[], Any], *, timeout: float) -> Any:
        """Run a plain (sync) callable on the loop thread and return its result."""
        done: concurrent.futures.Future = concurrent.futures.Future()

        def _run():
            try:
                done.set_result(fn())
            except Exception as exc:  # noqa: BLE001 - propagate to caller thread
                done.set_exception(exc)

        self._loop.call_soon_threadsafe(_run)
        return done.result(timeout)

    # -- unary RPC bridge -----------------------------------------------------

    def submit(self, coro, *, timeout: float | None = None) -> Any:
        """Run one coroutine to completion on the loop; block until it returns.

        The coroutine's result is returned; its exception is re-raised on the
        caller thread. A deadline overrun raises ``TimeoutError`` (which the
        fire block classifies as transient).
        """
        if self._closed:
            raise RuntimeError("ZenClient is closed")
        deadline = timeout if timeout is not None else self._default_call_timeout
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return fut.result(deadline)
        except concurrent.futures.TimeoutError as exc:
            fut.cancel()
            raise TimeoutError(f"RPC exceeded {deadline}s deadline") from exc

    # -- server-streaming bridge ---------------------------------------------

    def stream(self, factory: Callable[[], Any], *, item_timeout: float | None = None) -> Iterator:
        """Bridge a server-streaming async iterator into a blocking generator.

        Args:
            factory: zero-arg callable returning the async iterator (e.g.
                ``lambda: client.experiment.register_on_status_changed(req)``);
                it is invoked on the loop thread.
            item_timeout: max seconds to wait for the next item before raising
                ``TimeoutError``. None waits indefinitely (use only for streams
                known to terminate).

        Yields items until the stream ends. Async-side exceptions are re-raised
        on the consumer thread. If the consumer stops early, the loop-side task
        is cancelled.
        """
        if self._closed:
            raise RuntimeError("ZenClient is closed")
        q: queue.Queue = queue.Queue()
        task_box: dict[str, Any] = {}

        async def _pump():
            try:
                async for item in factory():
                    q.put(("item", item))
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # noqa: BLE001 - surfaced on consumer thread
                q.put(("error", exc))
            finally:
                q.put(("done", _STREAM_END))

        def _schedule():
            task_box["task"] = self._loop.create_task(_pump())

        self._loop.call_soon_threadsafe(_schedule)

        def _cancel():
            task = task_box.get("task")
            if task is not None and not task.done():
                task.cancel()

        def _generator():
            try:
                while True:
                    try:
                        kind, payload = q.get(timeout=item_timeout)
                    except queue.Empty as exc:
                        raise TimeoutError(f"stream item exceeded {item_timeout}s") from exc
                    if kind == "item":
                        yield payload
                    elif kind == "error":
                        raise payload
                    else:
                        return
            finally:
                self._loop.call_soon_threadsafe(_cancel)

        return _generator()

    # -- lazy stub access -----------------------------------------------------

    def _stub(self, key: str) -> Any:
        if key not in self._stubs:
            self._stubs[key] = self._stub_factory(key, self._channel, self._metadata)
        return self._stubs[key]

    @property
    def stage(self):
        return self._stub("stage")

    @property
    def focus(self):
        return self._stub("focus")

    @property
    def objective(self):
        return self._stub("objective")

    @property
    def experiment(self):
        return self._stub("experiment")

    @property
    def experiment_streaming(self):
        return self._stub("experiment_streaming")

    # -- shutdown -------------------------------------------------------------

    def close(self) -> None:
        """Close the channel and stop the loop thread. Idempotent."""
        if self._closed:
            return
        self._closed = True
        try:
            if self._channel is not None:
                # grpclib Channel.close() is a coroutine; the fake matches.
                fut = asyncio.run_coroutine_threadsafe(self._channel.close(), self._loop)
                fut.result(5.0)
        except Exception:  # noqa: BLE001 - closing must not raise
            log.debug("channel close failed", exc_info=True)
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5.0)
