"""Command line used by ``run_webapp.py`` for the web interface."""

from __future__ import annotations

import argparse
import importlib

from . import serve


def _register_live_instrument() -> None:
    """Run the workflow composition root that registers the Leica adapter.

    Registration is the only driver-aware launch concern. The server, flow,
    widgets, and every hardware operation continue to use the controller's
    public ``Session`` surface exclusively.
    """
    importlib.import_module("_bootstrap")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python run_webapp.py",
        description=(
            "Run the ZMART target-acquisition interface in a plain browser — "
            "the same flow as the v4 notebook, without Jupyter."
        ),
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="drive the simulated microscope and sample instead of real hardware",
    )
    parser.add_argument(
        "--analysis-repo",
        help="path to the smart analysis checkout (required for a real session)",
    )
    parser.add_argument(
        "--vendor", default="leica", help="controller vendor to connect (default: leica)"
    )
    parser.add_argument(
        "--af-job",
        help="autofocus job name, only when LAS X has more than one autofocus job",
    )
    parser.add_argument(
        "--demo-root", help="where the demo saves its run folder (default: ./zmart_demo_run)"
    )
    parser.add_argument(
        "--experiment",
        default="target-acquisition",
        help="experiment folder name (default: target-acquisition)",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="open the page in the default browser once the server is running",
    )
    parser.add_argument(
        "--window",
        action="store_true",
        help=(
            "open the page in its own native desktop window instead of a browser "
            "(needs the 'pywebview' package; falls back to a browser if missing)"
        ),
    )
    parser.add_argument("--port", type=int, default=8765, help="port to listen on")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help=(
            "address to bind. The default (127.0.0.1) keeps the page reachable "
            "only from this machine — the safe choice for anything that drives "
            "a real microscope."
        ),
    )
    args = parser.parse_args()
    if not args.demo:
        _register_live_instrument()
    serve(
        open_browser=args.open,
        open_window=args.window,
        host=args.host,
        port=args.port,
        demo=args.demo,
        analysis_repo=args.analysis_repo,
        vendor=args.vendor,
        demo_root=args.demo_root,
        af_job=args.af_job,
        experiment=args.experiment,
    )


if __name__ == "__main__":
    main()
