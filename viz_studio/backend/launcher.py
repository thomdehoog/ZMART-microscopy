"""Open the visualization studio in its own desktop window.

On the microscope PC this is what you run to see the viewer. It starts the
little web server (which serves the built page and the image volume) and then
opens a native window pointing at it — no browser tab, no address bar, just the
tool. The window uses the operating system's own web engine (on Windows that is
WebView2, which is Chromium), so the heavy 3-D rendering runs on the machine's
real graphics card.

If the native-window library is not available, or its runtime is missing, this
falls back to simply printing the address so you can open it in a normal
browser — the app is identical either way.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from server import make_server  # noqa: E402


def _webview2_present() -> bool:
    """On Windows, check that the WebView2 runtime the window needs is installed.

    pywebview draws its window with Microsoft's WebView2 (the Chromium engine
    built into Edge). It is present on all Windows 11 machines and almost all
    up-to-date Windows 10 machines, but on a fresh PC it can be missing — in
    which case the window would open blank. We check ahead of time so we can
    give a clear message instead of a mysterious empty window.
    """
    if not sys.platform.startswith("win"):
        return True  # not Windows: not our concern here
    try:
        import winreg

        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for key in (
                r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
                r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
            ):
                try:
                    with winreg.OpenKey(root, key) as k:
                        version, _ = winreg.QueryValueEx(k, "pv")
                        # An uninstalled runtime can leave the key behind with a
                        # zero version; treat that as "not present".
                        if version and version != "0.0.0.0":
                            return True
                except OSError:
                    continue
    except Exception:
        return False
    return False


def open_window(
    port: int = 8848,
    *,
    width: int = 1500,
    height: int = 950,
    data_dir: Path | None = None,
    store: str | list[str] = "demo.zarr",
    window: tuple[float, float] | None = None,
    depth_samples: int = 256,
    chrome: bool = False,
    live: bool = True,
    allow_open: bool = True,
    allow_selection: bool = False,
    panel_side: str = "right",
) -> None:
    """Start the server and open the studio in a native window.

    Blocks until the window is closed. Falls back to printing the address if a
    native window cannot be opened. ``data_dir``/``store`` point the viewer at
    any OME-Zarr store; leaving them unset opens the demo volume.

    ``port`` is which door on this machine the viewer answers on. Passing ``0``
    asks the machine to pick a free one, which is the thing to do when 8848 is
    already taken and you do not mind which is used instead.

    ``live`` is what keeps the viewer looking in the folder for images written
    after it was opened, which is what makes an acquisition appear during a run.
    Turn it off for data that has finished, and nothing is looked for again.
    """
    # The viewer's "open" button needs a folder chooser, and only Python can show
    # one: a page in a browser cannot be handed a path on the machine. This hands
    # the server a way to ask for one. It is filled in below once the window
    # exists; in the browser fallback the machine's own dialog stands in, since
    # the server answers on this machine only and whoever is looking at the page
    # is sitting at this desktop.
    chooser: dict = {}

    def browse():
        show = chooser.get("show")
        if show:
            return show()
        from server import ask_this_machine_for_a_folder

        return ask_this_machine_for_a_folder()

    kwargs = {
        "store": store,
        "window": window,
        "depth_samples": depth_samples,
        "chrome": chrome,
        "browse": browse,
        "live": live,
        # Which parts of the panel exist, and which edge it sits on. These are
        # passed straight through so that whoever opens the window decides them --
        # a smart-microscopy run and someone looking at last week's data want
        # different answers, and the server explains each one.
        "allow_open": allow_open,
        "allow_selection": allow_selection,
        "panel_side": panel_side,
    }
    if data_dir is not None:
        kwargs["data_dir"] = data_dir
    server = make_server(port, **kwargs)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    # Asked of the server rather than built from the number passed in. The two
    # agree for an ordinary port and disagree exactly when it matters: ``port=0``
    # means "any free one", and the address built from the argument was then
    # http://127.0.0.1:0, which leads nowhere.
    url = f"http://127.0.0.1:{server.server_address[1]}"

    if not _webview2_present():
        print(
            "The WebView2 runtime does not appear to be installed, so a native "
            "window cannot be shown.\n"
            "Install it (a small free download from Microsoft, search "
            '"WebView2 Evergreen Runtime"), or just open this address in Edge '
            f"or Chrome:\n    {url}"
        )
        _serve_until_interrupt(server, url)
        return

    try:
        import webview  # pywebview
    except ImportError:
        print(
            "The native-window library (pywebview) is not installed, so the "
            f"viewer will not pop up on its own.\nOpen this address in a "
            f"browser instead:\n    {url}\n"
            "(To get the pop-up window, install pywebview: it is in the conda "
            "environment file.)"
        )
        _serve_until_interrupt(server, url)
        return

    native = webview.create_window("ZMART Viewer", url, width=width, height=height)

    def show_folder_dialog():
        """Show the operating system's own folder chooser and return what was picked.

        Returns ``None`` when the operator cancels, which is an ordinary outcome and
        not an error. The dialog is asked for from the web server's thread rather
        than the window's, which pywebview allows; it returns a list of paths (or
        nothing at all) so the first is taken.
        """
        chosen = native.create_file_dialog(webview.FOLDER_DIALOG)
        if not chosen:
            return None
        return chosen[0] if isinstance(chosen, (list, tuple)) else str(chosen)

    chooser["show"] = show_folder_dialog
    webview.start()
    server.shutdown()


def _serve_until_interrupt(server, url: str) -> None:
    import time

    print(f"Serving at {url} — press Ctrl+C to stop.")
    try:
        # A short polling sleep, rather than one long wait: on Windows only
        # time.sleep is interrupted promptly by Ctrl+C, so this keeps the
        # "press Ctrl+C to stop" promise on the machines that use the fallback.
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Open the visualization studio window.")
    parser.add_argument("--port", type=int, default=8848)
    args = parser.parse_args()
    open_window(args.port)
