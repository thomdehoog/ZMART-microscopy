"""Markdown run-report writer shared by the hardware validators.

One ``RunReport`` per validator run. Phases append structured entries
(timestamp, phase, action attempted with its args, expected outcome,
observed outcome, PASS/WARN/FAIL/SKIP, confirmation result, duration,
reader mode + reading age for routed reads, whether the action mutates
instrument state), and ``write()`` renders a single human-readable
Markdown file the maintainer can read after the bench run:

  1. run metadata (date, host, mock-or-live backend, driver commit),
  2. a summary table (phase / actions attempted / passed / failed /
     skipped / confirmed / unconfirmed),
  3. a timing overview (per-phase and per-reader-mode min/median/max
     latency, the slowest actions, and every unconfirmed or failed
     change so those jump out on first read),
  4. the chronological detail of every attempted action -- every
     state-changing command on the instrument, including failed ones and
     the restore/cleanup steps, is flagged in the "Mutates scope" column,
     and every change carries its success+CONFIRMED / success+UNCONFIRMED /
     FAILED result and attempt counts.

``write()`` is designed to be called from a ``finally`` block so a crash
still produces a report (the crash is recorded in the metadata).

The default file name is ``hardware_run_report_<YYYYMMDD-HHMMSS>.md`` in
the working directory; pass ``report_dir`` to redirect (run_ci points it
at ``tests/_report/``).
"""

from __future__ import annotations

import logging
import platform
import socket
import statistics
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

_DRIVER_ROOT = Path(__file__).resolve().parents[2]  # navigator_expert/

# Statuses the summary table counts. Anything else lands outside the counts.
_COUNTED = ("PASS", "WARN", "FAIL", "SKIP")

# Confirmation labels for attempted changes (driver command envelopes).
CONFIRMED = "success+CONFIRMED"
UNCONFIRMED = "success+UNCONFIRMED"
FAILED = "FAILED"


def confirmation_of(result: dict) -> str:
    """Map a driver result envelope to the report's confirmation label."""
    if not result.get("success"):
        return FAILED
    confirmed = result.get("confirmed")
    if confirmed is False:
        return UNCONFIRMED
    if confirmed is True:
        return CONFIRMED
    return "success"  # command has no readback confirmation concept


_ENVELOPE_LOG = logging.getLogger("navigator_expert.envelope")
_ENVELOPE_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}


def replay_envelope_logs(result: dict, *, label: str = "") -> None:
    """Replay a command result envelope's structured ``logs`` into logging.

    The dispatch backbone accumulates its trace (including which race leg
    confirmed, and any leg warnings) in ``result["logs"]`` — those entries
    never pass through the ``logging`` module, so without this bridge they
    are invisible in the persisted driver log the evaluation greps.
    """
    prefix = f"[{label}] " if label else ""
    for entry in result.get("logs") or []:
        level = _ENVELOPE_LEVELS.get(str(entry.get("level", "info")).lower(), logging.INFO)
        _ENVELOPE_LOG.log(level, "%s%s", prefix, entry.get("msg", entry))


def attempts_of(result: dict) -> str:
    """Compact attempt/retry counts from a driver result envelope."""
    timing = result.get("timing") or {}
    bits = []
    if "attempts" in timing:
        bits.append(f"att={timing['attempts']}")
    if "confirm_attempts" in timing:
        bits.append(f"conf={timing['confirm_attempts']}")
    return " ".join(bits)


def _cell(value: object, limit: int = 200) -> str:
    """Render one Markdown table cell: no pipes, no newlines, bounded length."""
    text = str(value if value is not None else "")
    text = text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text


def _s(seconds: float | None) -> str:
    """Consistent seconds formatting (3 decimals), '-' when unknown."""
    return "-" if seconds is None else f"{seconds:.3f}s"


def _git(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(_DRIVER_ROOT), *args],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:  # noqa: BLE001 -- report metadata is best-effort
        return None
    out = result.stdout.strip()
    return out if result.returncode == 0 and out else None


@dataclass
class ReportEntry:
    """One attempted action, in chronological order."""

    timestamp: str  # local wall-clock HH:MM:SS.mmm
    phase: str
    action: str  # e.g. "xy: move 01" / "change[zoom] -> 5.0"
    args: str  # exact args/context, e.g. "to=(65025.0, 30000.0) um"
    expected: str
    observed: str
    status: str  # PASS / WARN / FAIL / SKIP (INFO for annotations)
    duration_s: float
    mutates_scope: bool = False
    confirmation: str = ""  # CONFIRMED/UNCONFIRMED/FAILED labels for changes
    attempts: str = ""  # e.g. "att=2 conf=3"
    reader_mode: str = ""  # api / log / hybrid, for routed per-mode reads
    age_s: float | None = None  # reading freshness where the reader provides it

    @property
    def result_cell(self) -> str:
        parts = [p for p in (self.confirmation, self.attempts) if p]
        return " ".join(parts)


@dataclass
class RunReport:
    """Accumulates entries for one validator run and writes the Markdown."""

    script: str  # e.g. "validate_hardware"
    backend: str  # "mock (in-process MockLasxClient)" | "live LAS X (sim or scope)"
    report_dir: str | Path | None = None
    argv: list[str] | None = None
    entries: list[ReportEntry] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    started: datetime = field(default_factory=datetime.now)
    written_path: Path | None = None
    log_path: Path | None = None
    _log_handler: logging.Handler | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self._start_driver_log_capture()

    def _start_driver_log_capture(self) -> None:
        """Persist every driver log line (navigator_expert.* via the root
        logger) to a file next to the report.

        The evaluation needs the raw log — e.g. proving the *absence* of
        ``api read not started`` warnings during select_job confirmation —
        and console output is lost when the terminal closes. Root capture
        is best-effort: a failure to open the file never blocks the run.
        """
        try:
            directory = Path(self.report_dir) if self.report_dir else Path.cwd()
            directory.mkdir(parents=True, exist_ok=True)
            stamp = self.started.strftime("%Y%m%d-%H%M%S")
            path = directory / f"driver_log_{stamp}.log"
            n = 2
            while path.exists():
                path = directory / f"driver_log_{stamp}_{n}.log"
                n += 1
            handler = logging.FileHandler(path, encoding="utf-8")
            handler.setLevel(logging.INFO)
            handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)s %(name)s | %(message)s")
            )
            root = logging.getLogger()
            if root.level > logging.INFO:  # default WARNING would drop INFO records
                root.setLevel(logging.INFO)
            root.addHandler(handler)
            self._log_handler = handler
            self.log_path = path
        except Exception:  # noqa: BLE001 -- log capture must never block a bench run
            self._log_handler = None
            self.log_path = None

    def add(
        self,
        *,
        phase: str,
        action: str,
        args: str = "",
        expected: str = "",
        observed: str = "",
        status: str = "INFO",
        duration_s: float = 0.0,
        mutates_scope: bool = False,
        confirmation: str = "",
        attempts: str = "",
        reader_mode: str = "",
        age_s: float | None = None,
    ) -> None:
        self.entries.append(
            ReportEntry(
                timestamp=datetime.now().strftime("%H:%M:%S.%f")[:-3],
                phase=phase,
                action=action,
                args=args,
                expected=expected,
                observed=observed,
                status=status,
                duration_s=duration_s,
                mutates_scope=mutates_scope,
                confirmation=confirmation,
                attempts=attempts,
                reader_mode=reader_mode,
                age_s=age_s,
            )
        )

    def note(self, text: str) -> None:
        """Free-form finding surfaced in its own section (e.g. known issues)."""
        self.notes.append(text)

    # -- rendering -------------------------------------------------------

    def _phase_counts(self) -> list[tuple[str, dict[str, int]]]:
        """Per-phase status + confirmation counts, phases in first-seen order."""
        order: list[str] = []
        counts: dict[str, dict[str, int]] = {}
        keys = (*_COUNTED, "attempted", "confirmed", "unconfirmed")
        for e in self.entries:
            if e.phase not in counts:
                order.append(e.phase)
                counts[e.phase] = dict.fromkeys(keys, 0)
            c = counts[e.phase]
            c["attempted"] += 1
            if e.status in _COUNTED:
                c[e.status] += 1
            if e.confirmation == CONFIRMED:
                c["confirmed"] += 1
            elif e.confirmation == UNCONFIRMED:
                c["unconfirmed"] += 1
        return [(p, counts[p]) for p in order]

    def _timing_lines(self) -> list[str]:
        lines = ["", "## Timing overview", ""]

        def stats_row(label: str, durations: list[float], extra: str = "") -> str:
            return (
                f"| {_cell(label, 40)} | {len(durations)} | {_s(min(durations))} "
                f"| {_s(statistics.median(durations))} | {_s(max(durations))} |{extra}"
            )

        # Per phase (all timed actions).
        lines += [
            "### Per phase",
            "",
            "| Phase | Timed actions | Min | Median | Max |",
            "|---|---:|---:|---:|---:|",
        ]
        order: list[str] = []
        by_phase: dict[str, list[float]] = {}
        for e in self.entries:
            if e.duration_s > 0:
                if e.phase not in by_phase:
                    order.append(e.phase)
                by_phase.setdefault(e.phase, []).append(e.duration_s)
        for phase in order:
            lines.append(stats_row(phase, by_phase[phase]))
        if not order:
            lines.append("| (no timed actions) | 0 | - | - | - |")

        # Per reader mode (routed read latency + reading age).
        mode_entries = [e for e in self.entries if e.reader_mode]
        if mode_entries:
            lines += [
                "",
                "### Per reader mode (routed read latency)",
                "",
                "| Mode | Reads | Min | Median | Max | Median reading age |",
                "|---|---:|---:|---:|---:|---:|",
            ]
            for mode in ("api", "log", "hybrid"):
                sel = [e for e in mode_entries if e.reader_mode == mode]
                if not sel:
                    continue
                durations = [e.duration_s for e in sel]
                ages = [e.age_s for e in sel if e.age_s is not None]
                age = _s(statistics.median(ages)) if ages else "-"
                lines.append(
                    f"| {mode} | {len(sel)} | {_s(min(durations))} "
                    f"| {_s(statistics.median(durations))} | {_s(max(durations))} | {age} |"
                )

        # Slowest actions.
        timed = sorted(
            (e for e in self.entries if e.duration_s > 0),
            key=lambda e: e.duration_s,
            reverse=True,
        )[:10]
        if timed:
            lines += [
                "",
                "### Slowest actions",
                "",
                "| Duration | Phase | Action | Status |",
                "|---:|---|---|---|",
            ]
            lines += [
                f"| {_s(e.duration_s)} | {_cell(e.phase, 40)} | {_cell(e.action, 120)} "
                f"| {e.status} |"
                for e in timed
            ]

        # Unconfirmed / failed changes -- must jump out on first read.
        problems = [e for e in self.entries if e.confirmation in (UNCONFIRMED, FAILED)]
        lines += ["", "### Unconfirmed / failed changes", ""]
        if problems:
            lines += [
                "| Phase | Action | Result | Attempts | Duration | Observed |",
                "|---|---|---|---|---:|---|",
            ]
            lines += [
                f"| {_cell(e.phase, 40)} | {_cell(e.action, 120)} | {e.confirmation} "
                f"| {_cell(e.attempts, 40)} | {_s(e.duration_s)} | {_cell(e.observed, 160)} |"
                for e in problems
            ]
        else:
            lines.append("None -- every attempted change reported success and confirmed.")
        return lines

    def render(self, *, crashed: str | None = None) -> str:
        finished = datetime.now()
        commit = _git("rev-parse", "--short", "HEAD") or "unknown"
        branch = _git("rev-parse", "--abbrev-ref", "HEAD") or "unknown"
        dirty = _git("status", "--porcelain")
        lines = [
            "# Hardware validation run report",
            "",
            "Every change this run attempted on the instrument is listed below, "
            "including failed attempts and restore/cleanup steps "
            "(see the *Mutates scope* column). Changes carry their "
            "success+CONFIRMED / success+UNCONFIRMED / FAILED result and "
            "attempt counts in the *Result* column.",
            "",
            "## Run metadata",
            "",
            f"- **Validator**: `{self.script}`",
            f"- **Arguments**: `{' '.join(self.argv) if self.argv else '(none)'}`",
            f"- **Backend**: {self.backend}",
            f"- **Date**: {self.started.strftime('%Y-%m-%d')}",
            f"- **Started / finished**: {self.started.strftime('%H:%M:%S')} / "
            f"{finished.strftime('%H:%M:%S')} "
            f"({(finished - self.started).total_seconds():.1f}s)",
            f"- **Host**: {socket.gethostname()} ({platform.platform()})",
            f"- **Python**: {sys.version.split()[0]}",
            f"- **Driver commit**: {commit} on {branch}"
            + (" (working tree has local changes)" if dirty else ""),
        ]
        if self.log_path is not None:
            lines.append(f"- **Driver log**: `{self.log_path}` (full log-line capture)")
        if crashed:
            lines.append(f"- **CRASHED**: `{_cell(crashed)}` -- entries below are partial.")
        lines += ["", "## Summary", ""]
        lines.append(
            "| Phase | Actions attempted | Passed | Warned | Failed | Skipped "
            "| Confirmed | Unconfirmed |"
        )
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
        keys = ("attempted", "PASS", "WARN", "FAIL", "SKIP", "confirmed", "unconfirmed")
        totals = dict.fromkeys(keys, 0)
        for phase, c in self._phase_counts():
            lines.append(f"| {_cell(phase)} | " + " | ".join(str(c[k]) for k in keys) + " |")
            for k in keys:
                totals[k] += c[k]
        lines.append("| **total** | " + " | ".join(f"**{totals[k]}**" for k in keys) + " |")
        if self.notes:
            lines += ["", "## Findings / notes", ""]
            lines += [f"- {note}" for note in self.notes]
        lines += self._timing_lines()
        lines += [
            "",
            "## Chronological detail (every attempted action)",
            "",
            "| # | Time | Phase | Status | Result | Mutates scope | Action attempted "
            "| Args / target | Expected | Observed | Duration |",
            "|---:|---|---|---|---|---|---|---|---|---|---:|",
        ]
        for i, e in enumerate(self.entries, 1):
            lines.append(
                f"| {i} | {e.timestamp} | {_cell(e.phase, 40)} | {e.status} "
                f"| {_cell(e.result_cell, 60)} | {'YES' if e.mutates_scope else ''} "
                f"| {_cell(e.action, 120)} | {_cell(e.args, 160)} | {_cell(e.expected, 80)} "
                f"| {_cell(e.observed, 240)} | {_s(e.duration_s)} |"
            )
        lines.append("")
        return "\n".join(lines)

    def write(self, *, crashed: str | None = None) -> Path:
        """Render + write the report; safe to call from ``finally``.

        Re-invocation overwrites the same file (crash-then-finally callers).
        """
        directory = Path(self.report_dir) if self.report_dir else Path.cwd()
        directory.mkdir(parents=True, exist_ok=True)
        if self.written_path is None:
            stamp = self.started.strftime("%Y%m%d-%H%M%S")
            path = directory / f"hardware_run_report_{stamp}.md"
            n = 2
            while path.exists():  # two validators started in the same second
                path = directory / f"hardware_run_report_{stamp}_{n}.md"
                n += 1
            self.written_path = path
        self.written_path.write_text(self.render(crashed=crashed), encoding="utf-8")
        if self._log_handler is not None:
            self._log_handler.flush()
        return self.written_path
