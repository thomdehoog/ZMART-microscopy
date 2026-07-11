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
import uuid
from collections.abc import Callable
from functools import partial
from typing import Any

#: Keep at most this many bytes of recent image buffers for browsers to
#: fetch. A full 25-tile + 10-row replay fits many times over; anything
#: older has long been fetched (or belongs to a tab that went away).
_BUFFER_CAP_BYTES = 64 * 1024 * 1024

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
        self._clients: list[queue.Queue] = []
        self._clients_lock = threading.Lock()
        self._buffers: dict[str, bytes] = {}
        self._buffer_order: list[str] = []
        self._buffer_bytes = 0
        self._buffers_lock = threading.Lock()
        self._work: queue.Queue = queue.Queue()
        self._worker = threading.Thread(
            target=self._run_worker, name="zmart-webapp-worker", daemon=True
        )
        self._worker.start()

    # -- widgets -------------------------------------------------------------

    def add_widget(self, name: str, widget: Any) -> None:
        """Register a widget under a stable name and start mirroring it."""
        self._widgets[name] = widget
        names = self._synced_trait_names(widget)
        widget.observe(partial(self._on_trait_changed, name), names=names)
        # The widget's own ``send`` normally rides the Jupyter comm; here it
        # fans out to every connected tab instead. Python-side semantics are
        # unchanged: a message goes to every view of the model.
        widget.send = partial(self._broadcast_message, name)
        self.broadcast({"kind": "widget", "widget": name})

    def widget(self, name: str) -> Any | None:
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
        return {
            name: {trait: getattr(widget, trait) for trait in self._synced_trait_names(widget)}
            for name, widget in self._widgets.items()
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

    def submit(self, fn: Callable[[], None]) -> None:
        """Run one piece of work on the single worker thread, in order."""
        self._work.put(fn)

    def dispatch_message(self, widget_name: str, content: Any) -> bool:
        """Route one browser message to its widget, notebook-style.

        Everything queues behind the worker — except cancel, which is
        applied immediately (it only sets a flag the running loop reads).
        Returns False if the widget does not exist (yet).
        """
        widget = self._widgets.get(widget_name)
        if widget is None:
            return False
        if isinstance(content, dict) and content.get("type") == "cancel":
            widget._route_message(None, content, None)
            return True
        self.submit(lambda: widget._route_message(None, content, None))
        return True

    def dispatch_trait_changes(self, widget_name: str, changes: dict) -> bool:
        """Apply browser-side trait edits, exactly like a comm update would."""
        widget = self._widgets.get(widget_name)
        if widget is None or not isinstance(changes, dict):
            return False
        self.submit(lambda: widget.set_state(changes))
        return True

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
        self.submit(done.set)
        done.wait(timeout)
