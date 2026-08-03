"""Hand out a run you have already acquired, so the operator page can draw it.

`live_overview_demo.py` writes a pretend run and serves it, which is what the
tests use. This script does the other half of the job: it serves a run that
already exists on your disk — one your microscope actually acquired — and prints
the address to paste into the operator page.

## Running it

    python workflows/target_acquisition/serve_a_run.py /path/to/my_run.ome.zarr

It prints two addresses. The first is where the run is being served. The second
is the whole operator-page address with the run already filled in, so you can
copy it straight into a browser.

Leave it running for as long as you are looking at the picture. Stopping it with
Ctrl-C stops the serving; nothing is written and nothing is changed, so you can
stop and start it as often as you like.

## Why a run cannot simply be opened from the disk

It is natural to expect that a folder of files on your own computer could be
opened by a page on your own computer. Browsers do not allow it, on purpose: a
page opened straight off the disk is given no identity, and a browser will not
let a page without an identity read files. So the run has to be *served* — handed
out over a local address that never leaves your machine — and that is all this
script does.

It borrows the same file server the demo uses, because serving a run correctly
turns out to need three things a plain file server gets wrong, each of which
breaks the picture in a way that is hard to notice. They are explained where
that server is written, in `live_overview_demo.py`.
"""

from __future__ import annotations

import argparse
import socket
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

from live_overview_demo import Handler

# Where the operator page runs while you are developing. Only used to print a
# ready-made address; nothing here depends on the page being at this port.
THE_PAGE_IN_DEVELOPMENT = "http://127.0.0.1:5174"


class ServeWhatIsAlreadyThere(Handler):
    """The demo's file server, with the parts about a running scan taken out.

    The demo server also answers two questions about the pretend scan it is
    driving — how far it has got, and please acquire one more. A run that has
    already been acquired has neither, so those are simply not offered here, and
    anything asking for them is told plainly that there is nothing there.
    """

    def _control(self) -> bool:
        return False


def looks_like_a_run(folder: Path) -> bool:
    """Does this folder look like an OME-Zarr run rather than something else?

    A run keeps a small description of itself at its top level, under one of two
    names depending on which generation of the format wrote it. This is only a
    friendliness check: it lets the script say "that does not look like a run"
    now, rather than letting you find out from an empty picture later.
    """
    return (folder / ".zattrs").exists() or (folder / "zarr.json").exists()


def a_free_port() -> int:
    """Ask the operating system for a port nobody else is using."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Serve a run you have already acquired, for the operator page to draw.",
    )
    parser.add_argument(
        "run",
        type=Path,
        help="the run to serve — the folder ending in .ome.zarr",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="the port to serve it on. Left out, a free one is chosen for you.",
    )
    chosen = parser.parse_args()

    run = chosen.run.expanduser().resolve()
    if not run.is_dir():
        raise SystemExit(f"there is no folder at {run}")
    if not looks_like_a_run(run):
        print(
            f"warning: {run.name} has no OME-Zarr description at its top level, so it "
            "may not be a run. Serving it anyway, in case you know better."
        )

    # The run's parent is served rather than the run itself, so that the run keeps
    # its own name in the address. A viewer is given the address of the run, and a
    # run that had been served as the bare root would have no name to be given.
    # Threaded, because a picture is not one request. An engine asks for every
    # piece of image it needs to draw a view, and a page may hold several viewers
    # at once — measured, three of them on one run against a single-threaded
    # server queue behind one another badly enough that the slowest engine gives
    # up before it has finished opening. The run is only being read, so answering
    # several at once is free.
    port = chosen.port or a_free_port()
    server = ThreadingHTTPServer(
        ("127.0.0.1", port),
        partial(ServeWhatIsAlreadyThere, directory=str(run.parent)),
    )
    where = f"http://127.0.0.1:{port}/{run.name}"

    print(f"serving {run}")
    print(f"the run is at       {where}")
    print(f"open the page at    {THE_PAGE_IN_DEVELOPMENT}/?overview={where}")
    print("press Ctrl-C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
