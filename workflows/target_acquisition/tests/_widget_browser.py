"""Mount one widget in a real browser, on its own, with a stand-in for Jupyter.

The widgets are React apps that talk to a "model" — in a notebook that model
is anywidget's, carried over Jupyter's own connection, and in the web
interface it is the widget host. Neither is convenient when the question is
simply "does this panel draw, and does it behave when clicked?".

So this serves one widget's browser code beside a small page that gives it a
stand-in model: it holds the widget's traits, tells the panel when one
changes, and records the messages the panel sends back. That is the whole of
what a widget may assume, which means a panel that works here works in both
real settings — and one that quietly relied on something else fails here
first.

What this is for: rendering. Does the panel draw, are things where they should
be, does dragging move what it ought to. Python tests cover the model, and the
full-page tests in ``test_webapp_browser.py`` cover the seam between the two;
this fills the gap between them, which is where a drawing mistake would
otherwise sit unnoticed until an operator met it.
"""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>widget</title>
<style>body { margin: 0; padding: 16px; background: #fff; }</style>
</head><body>
<div id="here"></div>
<script type="module">
import widget from "./widget.mjs";

// A stand-in for the model a widget normally talks to. It keeps the traits,
// tells the panel when one changes, and remembers what the panel sent back —
// which is everything a widget is allowed to assume about its model.
const values = JSON.parse(document.getElementById("traits").textContent);
const listeners = new Map();
const model = {
  get: (name) => values[name],
  set(name, value) {
    values[name] = value;
    (listeners.get("change:" + name) || []).forEach((cb) => cb());
  },
  save_changes() {},
  on(event, cb) {
    if (!listeners.has(event)) listeners.set(event, []);
    listeners.get(event).push(cb);
  },
  off(event, cb) {
    const kept = (listeners.get(event) || []).filter((x) => x !== cb);
    listeners.set(event, kept);
  },
  send(content, buffers) { window.__sent.push(content); },
};

// The test drives the widget through these.
window.__sent = [];
window.__model = model;
window.__setTrait = (name, value) => model.set(name, value);
window.__getTrait = (name) => values[name];
window.__deliver = (content, buffers) =>
  (listeners.get("msg:custom") || []).forEach((cb) => cb(content, buffers || []));

widget.render({ model, el: document.getElementById("here") });
window.__mounted = true;
</script>
</body></html>
"""


@contextmanager
def widget_in_a_browser(widget: Any):
    """Serve one widget's code and a page that mounts it; yields the address.

    The widget's traits are handed to the page as they are at this moment, so
    set up whatever the panel should be showing before calling this.
    """
    esm = widget._esm.encode("utf-8")
    synced = {
        name: getattr(widget, name)
        for name, trait in widget.traits(sync=True).items()
        if not name.startswith("_") and name not in {"layout", "tabbable", "tooltip", "keys"}
    }

    def _jsonable(value: Any) -> Any:
        if isinstance(value, tuple):
            return list(value)
        if hasattr(value, "item"):
            return value.item()
        return str(value)

    traits = json.dumps(synced, default=_jsonable)
    page = _PAGE.replace(
        '<div id="here"></div>',
        f'<div id="here"></div>\n<script type="application/json" id="traits">{traits}</script>',
    ).encode("utf-8")

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: Any) -> None:
            pass

        def do_GET(self) -> None:  # noqa: N802 -- http.server's naming
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                body, kind = page, "text/html; charset=utf-8"
            elif path == "/widget.mjs":
                body, kind = esm, "text/javascript; charset=utf-8"
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
