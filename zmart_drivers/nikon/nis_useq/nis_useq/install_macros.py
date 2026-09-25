"""Write the two NIS macros that start and stop the bridge on this computer.

    python -m nis_useq.install_macros

A NIS macro cannot find this folder by itself, so the path is written into the
macros as a literal. NIS silently refuses to run a macro it cannot compile, so
the templates hold plain calls and literals only: no comments, no variables.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .bridge import DEFAULT_PORT, STOP_FILE

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent  # the folder that contains the nis_useq package

START_TEMPLATE = """WaitText(1, "nis_useq bridge: starting");
Python_RunString("import sys; p = r'{project_dir}'; sys.path.insert(0, p) if p not in sys.path else None; import importlib, nis_useq.bridge as b; importlib.reload(b); import nis; nis.log(b.start(port={port}))");
WaitText(1, "nis_useq bridge: running on port {port}. Press the macro Stop button to end it.");
while (ExistFile("{stop_file}") == 0)
{{
    Python_RunString("import nis_useq.bridge as b; b.pump(0.05)");
    Wait(0.01);
}}
Python_RunString("import nis_useq.bridge as b; import nis; nis.log(b.stop())");
WaitText(2, "nis_useq bridge: stopped");
"""

STOP_TEMPLATE = """Python_RunString("open(r'{stop_file}', 'w').close()");
WaitText(2, "nis_useq bridge: stop requested");
"""


def _mac_literal(path: Path | str) -> str:
    """A Windows path as it must appear inside a NIS macro string."""
    return str(path).replace("\\", "\\\\")


def render(project_dir: Path, stop_file: Path | str, port: int) -> tuple[str, str]:
    values = {
        "project_dir": _mac_literal(project_dir),
        "stop_file": _mac_literal(stop_file),
        "port": int(port),
    }
    return START_TEMPLATE.format(**values), STOP_TEMPLATE.format(**values)


def install(target_dir: Path | None = None, port: int = DEFAULT_PORT) -> tuple[Path, Path]:
    """Write ``start_bridge.mac`` and ``stop_bridge.mac``; return their paths."""
    target_dir = Path(target_dir or PACKAGE_DIR)
    target_dir.mkdir(parents=True, exist_ok=True)
    start_text, stop_text = render(PROJECT_DIR, STOP_FILE, port)
    start_path, stop_path = target_dir / "start_bridge.mac", target_dir / "stop_bridge.mac"
    start_path.write_text(start_text, encoding="utf-8", newline="\r\n")  # NIS writes CRLF
    stop_path.write_text(stop_text, encoding="utf-8", newline="\r\n")
    return start_path, stop_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the NIS macros that start/stop the bridge.")
    parser.add_argument("--target", help="folder for the .mac files (default: the package folder)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)
    for path in install(Path(args.target) if args.target else None, args.port):
        print(f"wrote {path}")
    print("In NIS-Elements: Macro > Run Macro From File..., then pick start_bridge.mac.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
