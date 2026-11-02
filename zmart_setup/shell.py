"""Running a command, showing that it runs, and keeping what it printed.

Every command the setup runs goes through :class:`Shell`, so the log holds
every command and its whole output, and a failure can be shown with the last
lines the command printed. The tests hand the setup a stand-in for this class
that answers without running anything.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

#: How many lines of a failed command's output are kept in the report.
TAIL_LINES = 60


@dataclass
class Done:
    """A command that has run: what it was, its exit code, and what it printed."""

    command: list[str]
    code: int
    output: str

    @property
    def ok(self) -> bool:
        return self.code == 0

    @property
    def shown(self) -> str:
        return " ".join(shlex.quote(part) for part in self.command)

    @property
    def tail(self) -> str:
        return "\n".join(self.output.rstrip().splitlines()[-TAIL_LINES:])


class Shell:
    """Runs commands for the setup, writing each one and its output to the log."""

    def __init__(self, record) -> None:
        self.record = record

    def run(self, command: list, *, env: dict | None = None, cwd: Path | None = None,
            timeout: float | None = None, quiet: bool = False) -> Done:
        """Run ``command`` and answer how it went; it never raises for a failing command.

        The output is kept in the log as it comes. ``quiet`` keeps it out of
        the terminal, for the checks, whose verdict is said on its own.
        """
        command = [str(part) for part in command]
        self.record.log(f"$ {' '.join(shlex.quote(part) for part in command)}")
        if not quiet:
            print(f"   running: {command[0]} {' '.join(command[1:3])} ...", flush=True)
        environment = {**os.environ, **(env or {})} if env is not None else None
        if timeout is not None:
            # A command that may hang (a check) runs to a limit, its output
            # read at the end rather than as it comes.
            try:
                done = subprocess.run(
                    command, env=environment, cwd=cwd, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                    timeout=timeout,
                )
                code, output = done.returncode, done.stdout
            except subprocess.TimeoutExpired as late:
                code = 124
                output = (late.output or "") + f"\n(stopped after {timeout:.0f} seconds without finishing)\n"
                if isinstance(output, bytes):
                    output = output.decode("utf-8", "replace")
            except OSError as why:
                code, output = 127, f"could not start {command[0]}: {why}"
            for line in output.splitlines():
                self.record.log("   " + line)
            self.record.log(f"   exit {code}")
            return Done(command, code, output)
        lines: list[str] = []
        try:
            process = subprocess.Popen(
                command, env=environment,
                cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
            )
        except OSError as why:
            self.record.log(f"   could not start: {why}")
            return Done(command, 127, f"could not start {command[0]}: {why}")
        for line in process.stdout:
            lines.append(line)
            self.record.log("   " + line.rstrip("\n"))
        code = process.wait()
        self.record.log(f"   exit {code}")
        return Done(command, code, "".join(lines))
