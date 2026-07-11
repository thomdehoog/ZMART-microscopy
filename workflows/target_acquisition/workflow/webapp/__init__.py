"""The ZMART web interface: the v4 notebook's run, in a plain browser.

Start it and open the printed address — no Jupyter needed:

    python -m workflow.webapp --demo            # simulated microscope
    python -m workflow.webapp --analysis-repo C:/code/smart-analysis

The page walks the exact steps of ``zmart_microscopy_v4_react.ipynb``
(connect → origin → jobs → focus → calibration → overview → discover →
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

from ._flow import RunFlow
from ._host import WidgetHub
from ._server import make_server

__all__ = ["RunFlow", "WidgetHub", "make_server", "serve"]


def serve(**kwargs) -> None:
    """Run the interface until interrupted; see :func:`make_server` for options."""
    server, _hub, _flow = make_server(**kwargs)
    host, port = server.server_address[:2]
    mode = "demo (simulated microscope)" if kwargs.get("demo") else "live microscope"
    print(f"ZMART web interface — {mode}")
    print(f"Open http://{host}:{port} in a browser on this machine.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping — remember to disconnect the session if it was live")
    finally:
        server.server_close()
