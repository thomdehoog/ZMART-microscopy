"""
Start the fake ZEN API gateway from the command line.
=====================================================
    python -m zenapi.simulator                 # 127.0.0.1:5002, files under ./fake_zen_gateway
    python -m zenapi.simulator --port 5010 --workdir C:\\zen-fake
    python -m zenapi.simulator --slow          # moves and frames take a little time
    python -m zenapi.simulator --supervised    # controlling calls refused, as in ZEN's default mode

It prints the ``config.ini`` it wrote; point the driver (or a ZMART
``connection`` dict) at that file. Stop it with Ctrl+C.
"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

from .fake_gateway import FakeGateway, FakeZen


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="fake ZEN API gateway")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5002)
    ap.add_argument(
        "--workdir",
        default="fake_zen_gateway",
        help="folder for the certificate, token, config.ini and the fake image folder",
    )
    ap.add_argument("--slow", action="store_true", help="moves take 0.3 s, frames 0.2 s")
    ap.add_argument(
        "--supervised",
        action="store_true",
        help="refuse controlling calls, like ZEN before Unsupervised API Mode is enabled",
    )
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    zen = FakeZen(supervised=args.supervised)
    if args.slow:
        zen.move_settle_s, zen.frame_time_s = 0.3, 0.2
    gateway = FakeGateway(args.workdir, host=args.host, port=args.port, zen=zen)
    gateway.start()
    config_path = gateway.write_config(Path(args.workdir) / "config.ini")
    print(f"fake ZEN API gateway listening on {gateway.host}:{gateway.port}")
    print(f"config.ini written to {config_path.resolve()}")
    print(f"images will be written to {zen.image_folder.resolve()}")
    print("press Ctrl+C to stop")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        gateway.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
