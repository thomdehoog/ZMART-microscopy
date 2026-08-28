"""The ZMART interface: the operator page in a window of its own.

This is how the page is meant to be met -- a native window, not a browser tab
with its chrome, its zoom and its address bar. It opens the window, starts the
bridge behind it, and points one at the other.

    python zmart-interface.py           # the built page, as the microscope runs it
    python zmart-interface.py --dev     # the dev server, edits reload live

The two differ only in who holds the page. On its own it is the microscope's
own shape: the bridge serves the page and the instrument on one address, and
`npm run build` has to have been run. With `--dev` the Vite dev server holds
the page instead so that edits appear in the window as they are saved, and the
page is told where the bridge is -- so `npm run dev` has to be running.

Needs pywebview, which the `zmart-microscopy` env has, and on Windows the
WebView2 runtime that draws it.

Why --build goes through the bridge
-----------------------------------

It would be simpler to hand the window the built file straight off the disk,
and that is what this used to do. It cannot, and the reason is a property of
the page rather than of this script: one of the drawing engines is
neuroglancer, which does part of its work in background programs, and a
browser refuses to start one for a page opened off the disk because such a
page has no address of its own for the program to belong to.

So the page is served over HTTP -- by the bridge, which is already here. That
is also exactly what the microscope does: one program, one address, the page
and the instrument together. In development the dev server holds the page
instead so that edits reload live, and the page is told where the bridge is.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import urllib.error
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent

# What `npm run build` leaves for the microscope computer: the page itself, and
# neuroglancer's two background programs beside it. The bridge hands them out.
BUILT = HERE / "framework" / "window" / "static" / "index.html"
DEV_URL = "http://127.0.0.1:5174/"

# The bridge: where the page's mock and real workflows meet the zmart
# controller. Started here so one launch brings up the whole thing — the
# window, the page, and the instrument's side of the seam.
BRIDGE = HERE / "framework" / "bridge.py"


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dev",
        action="store_true",
        help="hold the page in the dev server instead, so edits reload live",
    )
    parser.add_argument("--url", default=DEV_URL, help=f"dev server address (default {DEV_URL})")
    args = parser.parse_args()

    if args.dev and not _dev_server_is_up(args.url):
        print(f"nothing answering at {args.url} — start it with `npm run dev`")
        return 1
    if not args.dev and not BUILT.exists():
        print(f"no build at {BUILT} — run `npm run build` first, or pass --dev")
        return 1

    bridge_at = _start_bridge()
    if args.dev:
        # The dev server holds the page so edits reload live, which puts it on
        # a different address from the bridge — so the page is told where that is.
        target = f"{args.url}{'&' if '?' in args.url else '?'}bridge={bridge_at}"
        note = f"dev server · {args.url} · edits reload live · bridge at {bridge_at}"
    else:
        if not bridge_at:
            print("the page is served by the bridge, and it did not start")
            return 1
        # One address for the page and the instrument, as on the microscope.
        target, note = bridge_at, f"built page · served with the bridge at {bridge_at}"

    try:
        import webview
    except ModuleNotFoundError:
        print("this needs the 'pywebview' package; open the address in a browser instead")
        return 1

    print(f"opening {note}")
    webview.create_window("ZMART", target, width=1500, height=950)
    webview.start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
