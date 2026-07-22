"""The ZMART web interface: the v4 notebook's run, in a plain browser.

Start it and open the printed address — no Jupyter needed:

    python run_webapp.py --demo            # simulated microscope
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


def serve(*, open_browser: bool = False, **kwargs) -> None:
    """Run the interface until interrupted; see :func:`make_server` for options.

    With ``open_browser=True`` the default web browser is pointed at the
    page automatically once the server is listening — this is what the
    double-click launcher scripts use, so starting the website is one
    action instead of "run a command, then type an address".
    """
    server, _hub, _flow = make_server(**kwargs)
    host, port = server.server_address[:2]
    address = _page_address(host, port)
    mode = "demo (simulated microscope)" if kwargs.get("demo") else "live microscope"
    print(f"ZMART web interface — {mode}")
    print(f"Open {address} in a browser on this machine.")
    print("Keep this window open during the run; press Ctrl+C here to stop.")
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
        print("\nstopping — remember to disconnect the session if it was live")
    finally:
        server.server_close()
