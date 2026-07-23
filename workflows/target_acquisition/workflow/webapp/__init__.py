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
dependencies and nothing is fetched from the internet.
"""

from __future__ import annotations

import threading
import time
import webbrowser

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


def serve(*, open_browser: bool = False, open_window: bool = False, **kwargs) -> None:
    """Run the interface until interrupted; see :func:`make_server` for options.

    There are two ways to show the page. ``open_browser=True`` points the
    machine's default web browser at it once the server is listening — this is
    what the double-click launcher scripts use. ``open_window=True`` instead
    opens the page in its own native desktop window (via pywebview), so it feels
    like an application rather than a browser tab; if that library or its engine
    is not available the code falls back to the browser/address route, so the
    flag is always safe to pass.
    """
    server, _hub, flow = make_server(**kwargs)
    host, port = server.server_address[:2]
    address = _page_address(host, port)
    mode = "demo (simulated microscope)" if kwargs.get("demo") else "live microscope"
    print(f"ZMART web interface — {mode}")
    print(f"Open {address} in a browser on this machine.")
    print("Keep this window open during the run; press Ctrl+C here to stop.")

    # A native window (if asked for and available) takes over from here; it runs
    # the server on a background thread and blocks until the window is closed.
    webview = _load_webview() if open_window else None
    if webview is not None:
        _run_in_window(server, flow, address, webview)
        return

    if open_browser:
        # The server socket is already listening (bound when it was built),
        # so a browser tab opened now is answered as soon as serving starts
        # a moment later. If no browser can be opened (e.g. a headless
        # machine), the printed address above still works.
        try:
            webbrowser.open(address)
        except Exception:  # noqa: BLE001 -- the page must not die over a browser
            print("(could not open a browser automatically — open the address above)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping…")
    finally:
        _release(server, flow)


def _load_webview():
    """Import pywebview, or return ``None`` (explaining why) for a browser fallback.

    The native window is an optional convenience — the server itself needs only
    the standard library — so a missing pywebview must never stop the page from
    running; we just fall back to opening it in a browser.
    """
    try:
        import webview  # pywebview

        return webview
    except ImportError:
        print("(the --window option needs the 'pywebview' package; using a browser instead)")
        return None


def _run_in_window(server, flow, address: str, webview) -> None:
    """Show the page in a native desktop window; release hardware when it closes.

    pywebview must run on the main thread, so the server runs on a background
    thread while the window is open. If the window cannot be shown (for example
    the WebView2 engine is missing on a fresh Windows PC), we keep serving so the
    address still works in a browser, and wait for Ctrl+C. Either way the
    microscope and analysis engine are released before we return.
    """
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        webview.create_window(
            "ZMART target acquisition", address, width=1500, height=950
        )
        webview.start()  # blocks until the operator closes the window
    except Exception as exc:  # noqa: BLE001 -- keep serving even if the window fails
        print(f"(could not open a native window: {exc})")
        print(f"Open {address} in a browser; press Ctrl+C here to stop.")
        _wait_for_interrupt()
    finally:
        server.shutdown()
        _release(server, flow)


def _wait_for_interrupt() -> None:
    """Block until Ctrl+C. A short polling sleep so the interrupt lands promptly."""
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass


def _release(server, flow) -> None:
    """Release the hardware and close the socket as the process shuts down.

    Ctrl+C (or a crash, or closing the window) must not leave the microscope and
    analysis engine connected and locked. Best-effort, since we are already
    shutting down.
    """
    flow.release_on_shutdown()
    server.server_close()
