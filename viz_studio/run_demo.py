"""Start the visualization studio in demo mode — one command, no microscope.

This is the front door for trying the tool. It:

1. makes a small pretend 3-D, three-colour microscope volume (if one is not
   already there), and
2. opens the viewer in its own window, pointing at that volume.

Everything the real tool does — pan, zoom, scroll through the stack, switch to
3-D, adjust each channel — you can try here on synthetic data, with no hardware
attached. Run it with::

    python run_demo.py

The built viewer page must exist first (``frontend/dist``); build it once with
``npm --prefix frontend install && npm --prefix frontend run build``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE / "backend"))

from demo_data import write_demo_zarr  # noqa: E402
from launcher import open_window  # noqa: E402


def main() -> int:
    dist = _HERE / "frontend" / "dist"
    if not (dist / "index.html").exists():
        print(
            "The viewer page has not been built yet.\n"
            "Build it once with:\n"
            "    npm --prefix frontend install\n"
            "    npm --prefix frontend run build\n"
            "then run this again."
        )
        return 1

    store = _HERE / "backend" / "demo_store" / "demo.zarr"
    # Check for the metadata file, not just the folder: a run interrupted
    # mid-write can leave a folder behind with no usable volume in it, and we
    # want the next launch to simply rebuild it rather than fail.
    if not (store / ".zattrs").exists():
        print("Making the demo volume (first run only)...")
        write_demo_zarr(store)
    print("Opening the visualization studio (demo mode)...")
    open_window()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
