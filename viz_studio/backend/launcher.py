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


def open_window(port: int = 8848, *, width: int = 1500, height: int = 950) -> None:
    """Start the server and open the studio in a native window.

    Blocks until the window is closed. Falls back to printing the address if a
    native window cannot be opened.
    """
    server = make_server(port)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{port}"

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

    webview.create_window("ZMART Viz Studio", url, width=width, height=height)
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
