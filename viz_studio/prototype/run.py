"""Open the ZMART viewer prototype in its own desktop window.

The prototype is a single self-contained web page (``index.html``). You can
always just open that file in a browser — but on the microscope PC it is nicer
to show it in its own window, with no browser tab, address bar, or bookmarks
around it. That is what this script does.

It uses **pywebview**, a small library that opens a native window drawn with the
operating system's own web engine (on Windows that is WebView2, the Chromium
engine built into Edge). Because the prototype is entirely self-contained — all
of its code and its sample data live inside the one HTML file — there is nothing
to serve and no server to start: the window simply loads the file directly.

Run it with::

    python run.py

If pywebview is not installed (it is a ``pip install pywebview`` away; it is not
on conda-forge), or a native window cannot be opened for any reason, this falls
back to opening the page in your normal web browser, so it always shows you
something. The prototype looks and behaves the same either way.
"""

from __future__ import annotations

import sys
import webbrowser
from pathlib import Path

# The viewer page sits next to this script.
PAGE = Path(__file__).resolve().with_name("index.html")


def open_in_browser() -> None:
    """Open the prototype in the default web browser."""
    webbrowser.open(PAGE.as_uri())
    print(f"Opened the prototype in your web browser:\n  {PAGE}")


def open_in_window() -> bool:
    """Open the prototype in a native desktop window using pywebview.

    Returns ``True`` if the window opened (and has since been closed), or
    ``False`` if pywebview is missing or a window could not be created — in
    which case the caller should fall back to a browser.
    """
    try:
        import webview  # pip install pywebview
    except ImportError:
        return False
    try:
        # No width/height guessing games: a comfortable default that still fits
        # the frame's own max size. The window is resizable.
        webview.create_window(
            "ZMART viewer — prototype",
            url=PAGE.as_uri(),
            width=1200,
            height=820,
        )
        webview.start()  # blocks until the window is closed
        return True
    except Exception as exc:  # a missing WebView2 runtime, a headless machine, etc.
        print(f"Could not open a native window ({exc}); falling back to a browser.", file=sys.stderr)
        return False


def main() -> int:
    if not PAGE.exists():
        print(f"Could not find the viewer page next to this script:\n  {PAGE}", file=sys.stderr)
        return 1
    # Prefer the clean native window; fall back to a browser tab if pywebview is
    # not installed or cannot open a window here.
    if not open_in_window():
        print("pywebview is not available — opening the prototype in a browser instead.")
        open_in_browser()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
