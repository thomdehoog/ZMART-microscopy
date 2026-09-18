"""
Write the two NIS macros for this computer.
===========================================
NIS-Elements macros cannot find out where this repository lives, so the
macros that start and stop the bridge carry the folder path as a literal. This
small script writes them with the right path for the machine it runs on::

    python -m nis_elements_6_10.bridge.install

It prints where the macros were written; run ``start_bridge.mac`` from NIS
(*Macro ▸ Run Macro From File…*). The generated ``.mac`` files are ignored by
git, so every computer gets its own without touching the repository.

Why the macros look the way they do: NIS refuses, silently, to run a macro it
cannot compile, and comment lines or string variables in our earlier attempts
were enough to trigger that. The templates below therefore hold plain calls
and literals only.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import argparse
from pathlib import Path

BRIDGE_DIR = Path(__file__).resolve().parent
PACKAGE_DIR = BRIDGE_DIR.parent  # the folder that holds nis_elements_6_10/
DRIVERS_NIKON_DIR = PACKAGE_DIR.parent

START_TEMPLATE = """WaitText(1, "ZMART bridge: starting");
Python_RunString("import sys; p = r'{nikon_dir}'; sys.path.insert(0, p) if p not in sys.path else None; import importlib, nis_elements_6_10.bridge.nis_bridge as b; importlib.reload(b); import nis; nis.log(b.start(port={port}))");
WaitText(1, "ZMART bridge: running on port {port} - stop with stop_bridge.mac");
while (ExistFile("{stop_file}") == 0)
{{
    Python_RunString("import nis_elements_6_10.bridge.nis_bridge as b; b.pump()");
    Wait(0.02);
}}
Python_RunString("import nis_elements_6_10.bridge.nis_bridge as b; import nis; nis.log(b.stop())");
WaitText(2, "ZMART bridge: stopped");
"""

STOP_TEMPLATE = """Python_RunString("open(r'{stop_file}', 'w').close()");
WaitText(2, "ZMART bridge: stop requested");
"""


def _mac_literal(path: Path) -> str:
    """A Windows path as it must appear inside a NIS macro string: backslashes doubled."""
    return str(path).replace("\\", "\\\\")


def render(nikon_dir: Path, stop_file: Path, port: int) -> tuple[str, str]:
    """The text of the start and stop macros for the given folders."""
    values = {
        "nikon_dir": _mac_literal(nikon_dir),
        "stop_file": _mac_literal(stop_file),
        "port": int(port),
    }
    return START_TEMPLATE.format(**values), STOP_TEMPLATE.format(**values)


def install(target_dir: Path | None = None, port: int = 54468) -> tuple[Path, Path]:
    """Write ``start_bridge.mac`` and ``stop_bridge.mac``; returns their paths."""
    target_dir = Path(target_dir) if target_dir else BRIDGE_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    stop_file = BRIDGE_DIR / "bridge.stop"
    start_text, stop_text = render(DRIVERS_NIKON_DIR, stop_file, port)
    start_path = target_dir / "start_bridge.mac"
    stop_path = target_dir / "stop_bridge.mac"
    # NIS macros are plain text; CRLF line ends match what its editor writes.
    start_path.write_text(start_text, encoding="utf-8", newline="\r\n")
    stop_path.write_text(stop_text, encoding="utf-8", newline="\r\n")
    return start_path, stop_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write the NIS macros that start/stop the ZMART bridge."
    )
    parser.add_argument("--target", help="folder for the .mac files (default: this bridge folder)")
    parser.add_argument("--port", type=int, default=54468, help="TCP port the bridge listens on")
    args = parser.parse_args(argv)
    start_path, stop_path = install(Path(args.target) if args.target else None, args.port)
    print("Wrote:")
    print(f"  {start_path}")
    print(f"  {stop_path}")
    print("In NIS-Elements: Macro > Run Macro From File..., pick start_bridge.mac.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
