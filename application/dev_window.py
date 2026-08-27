"""Open the operator page in a native window instead of a browser tab.

Two reasons to use this while designing:

* It is what the operator will actually see. `workflow/webapp/__main__.py
  --window` opens the real page the same way, so judging spacing and contrast
  in a browser tab -- with its chrome, its zoom, its address bar -- is judging
  the wrong thing.
* Pointed at the Vite dev server it still hot-reloads, so edits appear in the
  native window as they are saved.

    python dev_window.py            # the dev server, live reload
    python dev_window.py --build    # the built page, served the way Python will

The dev server has to be running already (`npm run dev`); this only opens a
window onto it. Needs pywebview, which the `zmart-microscopy` env has, and on
Windows the WebView2 runtime that draws it.

Why --build starts a small web server
-------------------------------------

It would be simpler to hand the window the built file straight off the disk, and
that is what this used to do. It cannot any more, and the reason is worth
knowing because it is a property of the page rather than of this script.

One of the three drawing engines the page offers is neuroglancer, and it does
part of its work in *background programs* -- separate pieces of JavaScript
running alongside the page so that fetching and unpacking images does not freeze
what the operator is looking at. A browser refuses to start one of those for a
page opened straight off the disk, because such a page has no address of its own
for the program to belong to. The page notices, offers only the two engines that
can draw, and says so in the corner -- honest, but it means the engine this
project leans towards could never be looked at in the window it is meant to run
in.

So `--build` serves the built folder over HTTP on a spare port and points the
window at that. It is also the closer imitation of what will really happen:
`workflow/webapp/_server.py` will hand the page out over HTTP too.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import pathlib
import socketserver
import sys
import threading
import urllib.error
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent

# Where `npm run build` leaves what the microscope computer is given: the page
# itself, and neuroglancer's two background programs beside it.
BUILT_FOLDER = HERE.parent / "workflow" / "webapp" / "static"
BUILT = BUILT_FOLDER / "index.html"
DEV_URL = "http://127.0.0.1:5174/"

# The bridge: where the page's mock and real workflows meet the zmart
# controller. Started here so one launch brings up the whole thing — the
# window, the page, and the instrument's side of the seam.
BRIDGE = HERE.parent / "workflow" / "webapp" / "bridge.py"


def _start_bridge() -> str | None:
    """Start the bridge beside the page, on a spare port, and say where.

    Loaded from its file rather than imported through the ``webapp`` package,
    whose import chain pulls in a notebook stack the bridge has no use for.
    A machine without the controller's Python packages still gets a window:
    the prototype workflow never calls the bridge, and the mock and real
    workflows answer with the bridge's absence when asked.
    """
    import importlib.util

    try:
        spec = importlib.util.spec_from_file_location("zmart_bridge", BRIDGE)
        bridge = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bridge)
        server = bridge.serve(0)  # port 0: the operating system picks a free one
    except Exception as why:  # noqa: BLE001 — whatever is missing, say so plainly
        print(f"bridge not started ({why}) — the prototype workflow still works")
        return None
    return f"http://127.0.0.1:{server.server_address[1]}"


def _dev_server_is_up(url: str, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout):
            return True
    except (urllib.error.URLError, OSError):
        return False


class _Quietly(http.server.SimpleHTTPRequestHandler):
    """Serve the built folder without narrating every request to the console."""

    # A browser will not start a background program from a file it was told is
    # anything but JavaScript, and it says nothing when it refuses -- the picture
    # simply never appears. Python's own guess is right on current versions and
    # has not always been, so it is said here rather than relied upon.
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".js": "text/javascript",
        ".mjs": "text/javascript",
    }

    def log_message(self, *_args) -> None:  # noqa: D102 -- silencing the base class
        pass


class _Server(socketserver.ThreadingTCPServer):
    """The little web server behind ``--build``, kept quiet about normal life."""

    daemon_threads = True
    # Otherwise a second window a moment after the first is refused the port.
    allow_reuse_address = True

    def handle_error(self, request, client_address) -> None:
        """Say nothing when the window simply stops listening part way through.

        A browser cancels requests all the time -- it changes its mind about an
        image, or the window is closed mid-download -- and the base class prints
        a full traceback for each one. Somebody looking at the page has no way to
        tell that alarming wall of text from a real fault, so the ordinary case
        is passed over in silence and everything else is still reported.
        """
        if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
            return
        super().handle_error(request, client_address)


def _serve(folder: pathlib.Path) -> str:
    """Serve `folder` on a spare port for as long as this process lives.

    Bound to the loopback address, so nothing outside this machine can reach it,
    and given port 0 so the operating system picks one that is free -- which
    means this never collides with the dev server or with a second window.

    :returns: the address to point a window at.
    """
    handler = functools.partial(_Quietly, directory=str(folder))
    server = _Server(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}/"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--build",
        action="store_true",
        help="open the built page rather than the dev server (no hot reload)",
    )
    parser.add_argument("--url", default=DEV_URL, help=f"dev server address (default {DEV_URL})")
    args = parser.parse_args()

    if args.build:
        if not BUILT.exists():
            print(f"no build at {BUILT} — run `npm run build` first")
            return 1
        target = _serve(BUILT_FOLDER)
        note = f"built page · {BUILT_FOLDER} · served at {target}"
    else:
        if not _dev_server_is_up(args.url):
            print(f"nothing answering at {args.url} — start it with `npm run dev`")
            return 1
        target, note = args.url, f"dev server · {args.url} · edits reload live"

    bridge_at = _start_bridge()
    if bridge_at:
        # The page finds the bridge through its own address; live.js reads it.
        target = f"{target}{'&' if '?' in target else '?'}bridge={bridge_at}"
        note += f" · bridge at {bridge_at}"

    try:
        import webview
    except ModuleNotFoundError:
        print("this needs the 'pywebview' package; open the address in a browser instead")
        return 1

    print(f"opening {note}")
    webview.create_window("ZMART operator page", target, width=1500, height=950)
    webview.start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
