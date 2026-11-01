"""What happened during the setup: said in the terminal, kept in a log and a report.

Every part of the setup ends in an **outcome**: it worked, it did not work, or
it was skipped, with one sentence saying what was found and, when it did not
work, one sentence saying what to do. The terminal shows the outcomes as they
come and a summary at the end. Two files keep everything, in the folder
``local/`` of ZMART Microscopy (kept out of git):

- ``setup.log``: every command that was run, and everything it printed.
- ``setup-report.json``: the computer, the answers given, and every outcome,
  with the command and the last lines it printed when something failed. This
  is the file the install doctor reads first
  (``.claude/agents/zmart-install-doctor.md``).

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import json
import platform
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

WORKED = "worked"
FAILED = "did not work"
SKIPPED = "skipped"

#: The agent file to hand to Claude Code when something did not work.
THE_DOCTOR = ".claude/agents/zmart-install-doctor.md"


@dataclass
class Outcome:
    """How one part of the setup went.

    ``what`` names the part in plain words; ``state`` is WORKED, FAILED or
    SKIPPED; ``found`` says what was seen; ``to_do`` says what to do about a
    failure; ``command`` and ``output`` are the command that failed and the
    last lines it printed, for the install doctor.
    """

    what: str
    state: str
    found: str = ""
    to_do: str = ""
    command: str = ""
    output: str = ""


@dataclass
class Record:
    """Everything the setup did, as it goes; written to ``local/`` at the end."""

    folder: Path
    answers: dict = field(default_factory=dict)
    outcomes: list[Outcome] = field(default_factory=list)
    started: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        self.log_path = self.folder / "setup.log"
        self.report_path = self.folder / "setup-report.json"
        self._log = self.log_path.open("w", encoding="utf-8")
        self.log(f"ZMART setup, {time.strftime('%Y-%m-%d %H:%M:%S')}")
        self.log(f"python {sys.version.split()[0]} on {platform.platform()}")

    # ------------------------------------------------------------------ log

    def log(self, text: str) -> None:
        """Keep a line in the log file only."""
        self._log.write(text.rstrip("\n") + "\n")
        self._log.flush()

    def say(self, text: str) -> None:
        """Say a line in the terminal, and keep it in the log."""
        print(text, flush=True)
        self.log(text)

    def heading(self, text: str) -> None:
        self.say(f"\n== {text}")

    # ------------------------------------------------------------- outcomes

    def add(self, outcome: Outcome) -> Outcome:
        """Keep an outcome and say it: a tick, a cross or a dash, then what was found."""
        self.outcomes.append(outcome)
        mark = {WORKED: "[ok]", FAILED: "[!!]", SKIPPED: "[--]"}[outcome.state]
        line = f"{mark} {outcome.what}"
        if outcome.found:
            line += f": {outcome.found}"
        self.say(line)
        if outcome.state == FAILED and outcome.to_do:
            self.say(f"     What to do: {outcome.to_do}")
        if outcome.command:
            self.log(f"     command: {outcome.command}")
        if outcome.output:
            self.log("     last output:\n" + _indent(outcome.output))
        return outcome

    def worked(self, what: str, found: str = "") -> Outcome:
        return self.add(Outcome(what, WORKED, found))

    def failed(self, what: str, found: str, to_do: str, command: str = "", output: str = "") -> Outcome:
        return self.add(Outcome(what, FAILED, found, to_do, command, output))

    def skipped(self, what: str, found: str) -> Outcome:
        return self.add(Outcome(what, SKIPPED, found))

    @property
    def failures(self) -> list[Outcome]:
        return [one for one in self.outcomes if one.state == FAILED]

    # --------------------------------------------------------------- ending

    def finish(self, facts: dict) -> bool:
        """Write the report, say the verdict, and answer whether everything worked."""
        report = {
            "when": time.strftime("%Y-%m-%d %H:%M:%S"),
            "seconds": round(time.time() - self.started),
            "computer": {
                "system": platform.system(),
                "release": platform.release(),
                "platform": platform.platform(),
                "python_running_the_setup": sys.version.split()[0],
            },
            "answers": self.answers,
            "facts": facts,
            "verdict": "ready" if not self.failures else f"{len(self.failures)} part(s) did not work",
            "outcomes": [asdict(one) for one in self.outcomes],
        }
        self.report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        self.heading("summary")
        worked = sum(one.state == WORKED for one in self.outcomes)
        skipped = sum(one.state == SKIPPED for one in self.outcomes)
        self.say(f"{worked} worked, {len(self.failures)} did not work, {skipped} skipped.")
        if not self.failures:
            self.say("\nZMART is ready.")
        else:
            self.say("\nZMART is NOT ready. These parts did not work:")
            for one in self.failures:
                self.say(f"  - {one.what}: {one.found}")
            self.say(
                "\nTo let Claude Code find out why and fix it, open Claude Code in this folder\n"
                "(the folder of ZMART Microscopy) and say:\n\n"
                f"    Read {THE_DOCTOR} and follow it.\n\n"
                f"It reads what happened from {self._shown(self.report_path)} and "
                f"{self._shown(self.log_path)}."
            )
        self._log.close()
        return not self.failures

    def _shown(self, path: Path) -> str:
        try:
            return path.relative_to(self.folder.parent).as_posix()
        except ValueError:
            return str(path)


def _indent(text: str) -> str:
    return "\n".join(f"       {line}" for line in text.rstrip().splitlines())
