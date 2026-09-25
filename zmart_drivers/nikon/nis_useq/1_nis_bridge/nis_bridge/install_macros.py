"""Write the NIS macro that starts the bridge on this computer.

    python -m nis_bridge.install_macros

A NIS macro cannot find this folder by itself, so the path is written into the
macro as a literal. NIS silently refuses to run a macro it cannot compile, so
the template holds plain calls and literals only: no comments, no variables.

To end the bridge, press the macro Stop button in NIS, or send the bridge a
``shutdown`` request. (A separate stop macro cannot work: NIS runs one macro
at a time, and the bridge loop is that macro.)
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .bridge import STOP_FILE
from .protocol import DEFAULT_PORT

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent  # the folder that contains the nis_bridge package

TEMPLATE = """WaitText(1, "nis-bridge: starting");
Python_RunString("import sys; p = r'{project_dir}'; sys.path.insert(0, p) if p not in sys.path else None; import importlib, nis_bridge.bridge as b; importlib.reload(b); import nis; nis.log(b.start(port={port}))");
WaitText(1, "nis-bridge: running on port {port}. Press the macro Stop button to end it.");
while (ExistFile("{stop_file}") == 0)
{{
    Python_RunString("import nis_bridge.bridge as b; b.pump(0.05)");
    Wait(0.01);
}}
Python_RunString("import nis_bridge.bridge as b; import nis; nis.log(b.stop())");
WaitText(2, "nis-bridge: stopped");
"""


def _mac_literal(path: Path | str) -> str:
    """A Windows path as it must appear inside a NIS macro string."""
    return str(path).replace("\\", "\\\\")


def render(project_dir: Path | str, stop_file: Path | str, port: int) -> str:
    return TEMPLATE.format(
        project_dir=_mac_literal(project_dir), stop_file=_mac_literal(stop_file), port=int(port)
    )


def install(target_dir: Path | None = None, port: int = DEFAULT_PORT) -> Path:
    """Write ``start_bridge.mac`` (in the package folder by default); return its path.

    The macro adds this project's folder to NIS's Python. That only works with
    an editable install (``pip install -e``): after a normal install the folder
    would be site-packages, and NIS's Python would then import packages built
    for another Python.
    """
    if not (PROJECT_DIR / "pyproject.toml").exists():
        raise SystemExit(
            f"nis-bridge is installed in {PROJECT_DIR}, not from its project folder. "
            "Install it with 'pip install -e <the 1_nis_bridge folder>' and run this again."
        )
    path = Path(target_dir or PACKAGE_DIR) / "start_bridge.mac"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(PROJECT_DIR, STOP_FILE, port), encoding="utf-8", newline="\r\n")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the NIS macro that starts the bridge.")
    parser.add_argument("--target", help="folder for the .mac file (default: the package folder)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)
    print(f"wrote {install(Path(args.target) if args.target else None, args.port)}")
    print("In NIS-Elements: Macro > Run Macro From File..., then pick start_bridge.mac.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
