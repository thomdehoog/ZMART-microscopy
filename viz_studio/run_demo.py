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


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data",
        type=Path,
        help="an OME-Zarr store to open instead of the demo volume",
    )
    parser.add_argument(
        "--range",
        help="display window as LOW,HIGH; by default it is read from the "
        "store's omero block, or measured from its coarsest pyramid level",
    )
    parser.add_argument(
        "--tiles",
        help="which tiles to open, e.g. 0,1 — default is every tile found",
    )
    parser.add_argument(
        "--depth-samples",
        type=int,
        default=256,
        help="samples along each viewing ray in volume mode (default 256). "
        "This, not the zoom, is what sets the resolution the volume is drawn "
        "at: neuroglancer picks the pyramid level a ray crosses in about this "
        "many steps. Higher is sharper and slower.",
    )
    parser.add_argument(
        "--chrome",
        action="store_true",
        help="show neuroglancer's own bounding box and axis lines (off by default)",
    )
    parser.add_argument(
        "--filter",
        dest="filter_name",
        help="when a tile and channel were acquired through several filters, "
        "keep the one whose name contains this, e.g. Empty",
    )
    parser.add_argument(
        "--timepoints",
        type=int,
        default=1,
        help="make the demo volume a timelapse of this many frames, so the time "
        "(T) slider has something to move through. The cells drift a little and "
        "one marker brightens while the other fades, so you can see the frames "
        "change. Default 1, a single moment with no time slider.",
    )
    parser.add_argument(
        "--select",
        action="store_true",
        help="show the selection list, where places you mark on the image are "
        "gathered. It is off by default: marking places is not what most looking "
        "at data is, and during a smart-microscopy run the workflow is what "
        "decides which places matter.",
    )
    parser.add_argument(
        "--panel-side",
        choices=("right", "left"),
        default="right",
        help="which edge the bar of controls sits on, and which way it folds away. "
        "At a microscope one side is often easier to reach than the other.",
    )
    parser.add_argument(
        "--no-open-button",
        action="store_true",
        help="leave out the way of choosing folders by hand. Use this when a "
        "workflow decides what is shown, so nobody can add an image the "
        "experiment knows nothing about.",
    )
    args = parser.parse_args(argv)

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

    window = None
    if args.range:
        low, _, high = args.range.partition(",")
        window = (float(low), float(high))

    if args.data:
        from stores import discover, prefer_filter, select_tiles

        parent, names = discover(args.data)
        if args.tiles:
            names = select_tiles(names, [int(t) for t in args.tiles.split(",")])
        names = prefer_filter(names, args.filter_name)
        if not names:
            print(f"No OME-Zarr store found at {args.data}")
            return 1
        what = names[0] if len(names) == 1 else f"{len(names)} stores from {parent.name}"
        print(f"Opening {what}...")
        # A narrowed selection must stay narrowed: if the folder were still being
        # watched, the tiles and filters deliberately left out would reappear.
        narrowed = bool(args.tiles or args.filter_name)
        open_window(
            data_dir=parent,
            store=names,
            window=window,
            depth_samples=args.depth_samples,
            chrome=args.chrome,
            watch=not narrowed,
            allow_selection=args.select,
            panel_side=args.panel_side,
            allow_open=not args.no_open_button,
        )
        return 0

    if args.timepoints < 1:
        print("--timepoints must be at least 1")
        return 1

    # A timelapse is written beside the ordinary demo rather than replacing it, so
    # asking for one does not throw away the single-volume store (and asking for
    # the plain demo afterwards does not throw away the timelapse).
    store_name = "demo.zarr" if args.timepoints == 1 else f"demo_t{args.timepoints}.zarr"
    store = _HERE / "backend" / "demo_store" / store_name
    # Check for the metadata file, not just the folder: a run interrupted
    # mid-write can leave a folder behind with no usable volume in it, and we
    # want the next launch to simply rebuild it rather than fail.
    if not (store / ".zattrs").exists():
        if args.timepoints > 1:
            print(f"Making the demo timelapse ({args.timepoints} frames, first run only)...")
        else:
            print("Making the demo volume (first run only)...")
        write_demo_zarr(store, timepoints=args.timepoints)
    print("Opening the visualization studio (demo mode)...")
    open_window(
        store=store_name,
        window=window,
        depth_samples=args.depth_samples,
        chrome=args.chrome,
        allow_selection=args.select,
        panel_side=args.panel_side,
        allow_open=not args.no_open_button,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
