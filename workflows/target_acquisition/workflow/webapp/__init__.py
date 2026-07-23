"""The ZMART web interface: the v4 notebook's run, in a plain browser.

Start it and open the printed address — no Jupyter needed:

    python run_webapp.py --demo            # simulated microscope
    python run_webapp.py --demo --window   # simulated, in its own desktop window
    python run_webapp.py --analysis-repo C:/code/smart-analysis

The page walks the exact steps of ``zmart_microscopy_v4_react.ipynb``
(connect → origin → jobs → focus → overview → discover →
acquire/curate → save → disconnect) and embeds the SAME six React widgets
the notebook uses, talking the protocol documented in
``workflow/react/PROTOCOL.md``. The operator sees buttons, pictures and
plain sentences — never code.

Demo mode drives :mod:`workflow._simulation` — the simulated microscope
and sample the offline notebook tests execute — so the whole flow can be
learned, demonstrated, and end-to-end tested without a Leica.

Only the Python standard library serves the page; there are no extra
dependencies and nothing is fetched from the internet. The optional
``--window`` desktop window is the one exception, and it degrades to a
browser when its library is absent.
"""

from __future__ import annotations

import importlib
import threading
import time

from ._flow import RunFlow
from ._host import WidgetHub
from ._server import make_server

__all__ = ["RunFlow", "WidgetHub", "make_server", "serve"]


def _page_address(host: str, port: int) -> str:
    """The address a browser on this machine should open.

    A server bound to "all interfaces" (0.0.0.0 or ::) has no address a
    browser can dial directly, so the local loopback name is used instead.
    """
    if host in ("0.0.0.0", "::", ""):
        host = "127.0.0.1"
    return f"http://{host}:{port}"


def serve(*, open_window: bool = False, **kwargs) -> None:
    """Run the interface until interrupted; see :func:`make_server` for options.

    ``open_window=True`` shows the page in its own native desktop window (via
    pywebview) instead of leaving the operator to open a browser, so the
    interface feels like an application rather than a browser tab. Neither the
    library nor its window engine is required: when either is missing the page
    is still served at the printed address, so the flag is always safe to pass.
    """
    server, _hub, _flow = make_server(**kwargs)
    host, port = server.server_address[:2]
    address = _page_address(host, port)
    mode = "demo (simulated microscope)" if kwargs.get("demo") else "live microscope"
    print(f"ZMART web interface — {mode}")
    print(f"Open {address} in a browser on this machine.")
    webview = _load_webview() if open_window else None
    if webview is not None:
        _run_in_window(server, address, webview)
        return
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping — remember to disconnect the session if it was live")
    finally:
        server.server_close()


def _load_webview():
    """Import pywebview, or return ``None`` (explaining why) for a browser fallback.

    The native window is an optional convenience — serving the page itself needs
    only the standard library — so a missing pywebview must never stop a run.
    """
    try:
        return importlib.import_module("webview")
    except ImportError:
        print("(the --window option needs the 'pywebview' package; using a browser instead)")
        return None


def _run_in_window(server, address: str, webview) -> None:
    """Show the page in a native desktop window, serving it until the window closes.

    pywebview must own the main thread, so the server runs on a background
    thread while the window is open. If the window cannot be shown — a fresh
    Windows PC without the WebView2 runtime is the usual reason — the page keeps
    being served so the address still works in a browser, and we wait for Ctrl+C.
    """
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        webview.create_window("ZMART target acquisition", address, width=1500, height=950)
        webview.start()
    except Exception as exc:  # noqa: BLE001 -- a window problem must not end the run
        print(f"(could not open a native window: {exc})")
        print(f"Open {address} in a browser; press Ctrl+C here to stop.")
        _wait_for_interrupt()
    finally:
        server.shutdown()
        server.server_close()


def _wait_for_interrupt() -> None:
    """Block until Ctrl+C, polling briefly so the interrupt lands promptly."""
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nstopping — remember to disconnect the session if it was live")
