"""Open the operator page in a native window instead of a browser tab.

Two reasons to use this while designing:

* It is what the operator will actually see. `workflow/webapp/__main__.py
  --window` opens the real page the same way, so judging spacing and contrast
  in a browser tab -- with its chrome, its zoom, its address bar -- is judging
  the wrong thing.
* Pointed at the Vite dev server it still hot-reloads, so edits appear in the
  native window as they are saved.

    python dev_window.py            # the dev server, live reload
    python dev_window.py --build    # the built single file, as Python serves it

The dev server has to be running already (`npm run dev`); this only opens a
window onto it. Needs pywebview, which the `zmart-microscopy` env has, and on
Windows the WebView2 runtime that draws it.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import urllib.error
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
BUILT = HERE.parent / "workflow" / "webapp" / "static" / "index.html"
DEV_URL = "http://127.0.0.1:5174/"


def _dev_server_is_up(url: str, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout):
            return True
    except (urllib.error.URLError, OSError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--build",
        action="store_true",
        help="open the built single file rather than the dev server (no hot reload)",
    )
    parser.add_argument("--url", default=DEV_URL, help=f"dev server address (default {DEV_URL})")
    args = parser.parse_args()

    if args.build:
        if not BUILT.exists():
            print(f"no build at {BUILT} — run `npm run build` first")
            return 1
        target, note = BUILT.as_uri(), f"built file · {BUILT}"
    else:
        if not _dev_server_is_up(args.url):
            print(f"nothing answering at {args.url} — start it with `npm run dev`")
            return 1
        target, note = args.url, f"dev server · {args.url} · edits reload live"

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
