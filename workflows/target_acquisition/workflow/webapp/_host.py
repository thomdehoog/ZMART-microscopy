"""The widget host: one Python side, any number of browser tabs.

In Jupyter, anywidget carries each widget's traits and messages over the
notebook's own connection. Outside Jupyter something has to play that
role, and this module is it. It holds the live widget objects, watches
their traits, and forwards everything to every connected browser tab:

- trait changes stream out as small JSON events (server-sent events, a
  one-way channel the browser keeps open);
- custom messages (a fresh tile, a new gallery row) stream out the same
  way, with their image bytes fetched separately so pixels never travel
  as JSON;
- clicks and edits come back as small HTTP posts and are applied through
  the same entry points a notebook comm update would use.

One important safety property is preserved deliberately: everything that
could touch state runs on ONE worker thread, in order — the same "one
thing at a time" behaviour a notebook kernel gives the widgets. The single
exception is a cancel request, which is handled immediately on the
incoming request's thread: cancelling only sets a flag the running loop
checks between sites, so this is safe, and it is exactly the "a website
host gets immediate cancellation" behaviour the widget protocol promises.
"""

from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from collections.abc import Callable
from functools import partial
from typing import Any

from traitlets import TraitError

#: Keep at most this many bytes of recent image buffers for browsers to
#: fetch. A full 25-tile + 10-row replay fits many times over; anything
#: older has long been fetched (or belongs to a tab that went away).
_BUFFER_CAP_BYTES = 64 * 1024 * 1024

# Browser requests must not form an unbounded backlog. In particular, a local
# client must not be able to queue enough stale Acquire/Measure/Sync requests
# that they keep firing after the operator's original run has finished.
_WORK_QUEUE_CAP = 256
_COALESCED_MESSAGE_KINDS = {"acquire", "acquire_selected", "measure", "sync"}

#: Traits that belong to the widget plumbing, not to the protocol.
_PLUMBING_TRAITS = {"layout", "tabbable", "tooltip", "keys", "comm", "log"}


def _jsonable(value: Any) -> Any:
    """Turn the odd non-JSON value (a tuple, a numpy number) into JSON."""
    if isinstance(value, tuple):
        return list(value)
    if hasattr(value, "item"):  # numpy scalar
        return value.item()
    return str(value)


class WidgetHub:
    """Hold the widgets, serialize all work, and fan events out to tabs."""

    def __init__(self) -> None:
        self._widgets: dict[str, Any] = {}
        self._widgets_lock = threading.Lock()
        self._clients: list[queue.Queue] = []
        self._clients_lock = threading.Lock()
        self._buffers: dict[str, bytes] = {}
        self._buffer_order: list[str] = []
        self._buffer_bytes = 0
        self._buffers_lock = threading.Lock()
        self._work: queue.Queue = queue.Queue(maxsize=_WORK_QUEUE_CAP)
        self._pending_messages: set[tuple[str, str]] = set()
        self._pending_messages_lock = threading.Lock()
        self._worker = threading.Thread(
            target=self._run_worker, name="zmart-webapp-worker", daemon=True
        )
        self._worker.start()

    # -- widgets -------------------------------------------------------------

    def add_widget(self, name: str, widget: Any) -> None:
        """Register a widget under a stable name and start mirroring it."""
        with self._widgets_lock:
            self._widgets[name] = widget
        names = self._synced_trait_names(widget)
        widget.observe(partial(self._on_trait_changed, name), names=names)
        # The widget's own ``send`` normally rides the Jupyter comm; here it
        # fans out to every connected tab instead. Python-side semantics are
        # unchanged: a message goes to every view of the model.
        widget.send = partial(self._broadcast_message, name)
        self.broadcast({"kind": "widget", "widget": name})

    def widget(self, name: str) -> Any | None:
        with self._widgets_lock:
            return self._widgets.get(name)

    @staticmethod
    def _synced_trait_names(widget: Any) -> list[str]:
        return [
            trait_name
            for trait_name, trait in widget.traits(sync=True).items()
            if not trait_name.startswith("_") and trait_name not in _PLUMBING_TRAITS
        ]

    def state_snapshot(self) -> dict:
        """Every widget's current traits — what a fresh tab starts from."""
        with self._widgets_lock:
            widgets = list(self._widgets.items())
        return {
            name: {trait: getattr(widget, trait) for trait in self._synced_trait_names(widget)}
            for name, widget in widgets
        }

    # -- events out ------------------------------------------------------------

    def _on_trait_changed(self, widget_name: str, change: dict) -> None:
        self.broadcast(
            {
                "kind": "trait",
                "widget": widget_name,
                "name": change["name"],
                "value": change["new"],
            }
        )

    def _broadcast_message(
        self, widget_name: str, content: Any, buffers: list | None = None
    ) -> None:
        ids = [self._store_buffer(bytes(buffer)) for buffer in (buffers or [])]
        self.broadcast({"kind": "msg", "widget": widget_name, "content": content, "buffers": ids})

    def broadcast(self, event: dict) -> None:
        """Queue one JSON event for every connected browser tab."""
        payload = json.dumps(event, default=_jsonable)
        with self._clients_lock:
            clients = list(self._clients)
        for client in clients:
            try:
                client.put_nowait(payload)
            except queue.Full:
                # A tab that stopped reading gets dropped, not waited on.
                self.remove_client(client)

    def add_client(self) -> queue.Queue:
        client: queue.Queue = queue.Queue(maxsize=4096)
        with self._clients_lock:
            self._clients.append(client)
        return client

    def remove_client(self, client: queue.Queue) -> None:
        with self._clients_lock:
            if client in self._clients:
                self._clients.remove(client)

    # -- image buffers -----------------------------------------------------------

    def _store_buffer(self, data: bytes) -> str:
        buffer_id = uuid.uuid4().hex
        with self._buffers_lock:
            self._buffers[buffer_id] = data
            self._buffer_order.append(buffer_id)
            self._buffer_bytes += len(data)
            while self._buffer_bytes > _BUFFER_CAP_BYTES and len(self._buffer_order) > 1:
                oldest = self._buffer_order.pop(0)
                self._buffer_bytes -= len(self._buffers.pop(oldest, b""))
        return buffer_id

    def buffer(self, buffer_id: str) -> bytes | None:
        with self._buffers_lock:
            return self._buffers.get(buffer_id)

    # -- work in ---------------------------------------------------------------

    def submit(self, fn: Callable[[], None]) -> bool:
        """Queue work without blocking; False means the bounded queue is full."""
        try:
            self._work.put_nowait(fn)
        except queue.Full:
            return False
        return True

    def dispatch_message(self, widget_name: str, content: Any) -> bool:
        """Route one browser message to its widget, notebook-style.

        Everything queues behind the worker — except cancel, which is
        applied immediately (it only sets a flag the running loop reads).
        Returns False if the widget does not exist (yet).
        """
        widget = self.widget(widget_name)
        if widget is None:
            return False
        if isinstance(content, dict) and content.get("type") == "cancel":
            widget._route_message(None, content, None)
            return True
        kind = content.get("type") if isinstance(content, dict) else None
        key = (widget_name, str(kind))
        coalesce = kind in _COALESCED_MESSAGE_KINDS
        if coalesce:
            with self._pending_messages_lock:
                if key in self._pending_messages:
                    return True
                self._pending_messages.add(key)

        def apply() -> None:
            try:
                widget._route_message(None, content, None)
            finally:
                if coalesce:
                    with self._pending_messages_lock:
                        self._pending_messages.discard(key)

        if self.submit(apply):
            return True
        if coalesce:
            with self._pending_messages_lock:
                self._pending_messages.discard(key)
        return False

    def valid_trait_changes(self, widget_name: str, changes: Any) -> bool:
        """Whether a trait update names synced traits with valid value types."""
        widget = self.widget(widget_name)
        if widget is None or not isinstance(changes, dict):
            return False
        traits = widget.traits()
        synced = set(self._synced_trait_names(widget))
        try:
            for name, value in changes.items():
                if name not in synced:
                    return False
                traits[name]._validate(widget, value)
        except (TraitError, TypeError, ValueError):
            return False
        return True

    def dispatch_trait_changes(self, widget_name: str, changes: dict) -> bool:
        """Apply browser-side trait edits, exactly like a comm update would."""
        widget = self.widget(widget_name)
        if widget is None or not self.valid_trait_changes(widget_name, changes):
            return False
        return self.submit(lambda: widget.set_state(changes))

    def _run_worker(self) -> None:
        while True:
            fn = self._work.get()
            try:
                fn()
            except Exception:  # noqa: BLE001 -- a step must not kill the host
                # Actions report their own failures to the operator; anything
                # escaping to here is a bug, but the host must keep serving.
                import traceback

                traceback.print_exc()

    def drain(self, timeout: float = 30.0) -> None:
        """Wait until the queued work is done (used by the tests)."""
        done = threading.Event()
        deadline = time.monotonic() + timeout
        while not self.submit(done.set):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("the webapp worker queue stayed full before the timeout")
            time.sleep(min(0.005, remaining))
        if not done.wait(max(0.0, deadline - time.monotonic())):
            raise TimeoutError("the webapp worker did not drain before the timeout")
