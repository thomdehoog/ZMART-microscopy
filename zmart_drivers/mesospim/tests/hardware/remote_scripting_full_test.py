#!/usr/bin/env python3
"""Run the mesoSPIM remote-scripting full demo test from the ZMART driver tree.

This is the ZMART-side entry point for validating the mesoSPIM remote scripting
bridge in demo mode. It delegates to the upstream mesoSPIM test script instead
of duplicating the protocol test logic here.

Typical use:
    python zmart_drivers/mesospim/tests/hardware/remote_scripting_full_test.py --token YOUR_TOKEN

The mesoSPIM GUI must already be running in demo mode with
Tools -> Remote Scripting... started.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


SCRIPT_RELATIVE_PATH = Path("mesoSPIM") / "scripts" / "remote_scripting_full_test.py"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _candidate_roots(explicit_root: Path | None) -> list[Path]:
    roots: list[Path] = []
    if explicit_root is not None:
        roots.append(explicit_root)

    env_root = os.environ.get("MESOSPIM_CONTROL_ROOT")
    if env_root:
        roots.append(Path(env_root))

    roots.extend(
        [
            Path.cwd(),
            _repo_root() / "mesoSPIM-control",
            _repo_root().parent / "mesoSPIM-control",
            Path.home() / "dev" / "mesoSPIM-control",
            Path(r"C:\Users\t.de\dev\mesoSPIM-control"),
            Path(r"Z:\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\mesoSPIM-control"),
        ]
    )

    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root)
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


def _find_test_script(explicit_script: Path | None, explicit_root: Path | None) -> Path:
    if explicit_script is not None:
        script = explicit_script.expanduser().resolve()
        if script.is_file():
            return script
        raise FileNotFoundError(f"test script does not exist: {script}")

    checked: list[Path] = []
    for root in _candidate_roots(explicit_root):
        script = (root.expanduser() / SCRIPT_RELATIVE_PATH).resolve()
        checked.append(script)
        if script.is_file():
            return script

    checked_lines = "\n".join(f"  - {path}" for path in checked)
    raise FileNotFoundError(
        "could not find mesoSPIM remote_scripting_full_test.py; "
        "pass --mesospim-root or set MESOSPIM_CONTROL_ROOT.\nChecked:\n" + checked_lines
    )


def _redact_command(args: list[str]) -> str:
    redacted: list[str] = []
    skip_next = False
    for item in args:
        if skip_next:
            redacted.append("<token>")
            skip_next = False
        elif item == "--token":
            redacted.append(item)
            skip_next = True
        elif item.startswith("--token="):
            redacted.append("--token=<token>")
        else:
            redacted.append(item)
    return " ".join(redacted)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "ZMART mesoSPIM driver entry point for the upstream "
            "remote-scripting full demo test. Unknown options are passed "
            "through to the mesoSPIM test script."
        )
    )
    parser.add_argument(
        "--mesospim-root",
        type=Path,
        default=None,
        help="Path to a mesoSPIM-control checkout. Defaults to MESOSPIM_CONTROL_ROOT and common local paths.",
    )
    parser.add_argument(
        "--test-script",
        type=Path,
        default=None,
        help="Path to remote_scripting_full_test.py. Overrides --mesospim-root.",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python executable used to run the mesoSPIM test script. Defaults to this Python.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the resolved command without running it.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args, passthrough = parser.parse_known_args(argv)

    try:
        test_script = _find_test_script(args.test_script, args.mesospim_root)
    except FileNotFoundError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2

    command = [args.python, str(test_script), *passthrough]

    print("=" * 78)
    print("ZMART mesoSPIM Remote Scripting Full Test")
    print("=" * 78)
    print(f"  Test script      {test_script}")
    print(f"  Python           {args.python}")
    print(f"  Command          {_redact_command(command)}")
    print()

    if args.dry_run:
        return 0

    completed = subprocess.run(command)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
