"""The questions, and the order of the work: what ``python setup_zmart.py`` does.

1. Find conda.
2. Ask: do you write code? Which microscope is this computer for? Make the
   large Cellpose environment (robust detection)?
3. Make the ZMART environment, and install the blocks at our releases.
4. Install the microscope's driver.
5. Make the analysis environments, from the pipelines' own files.
6. Write the start files, with an icon on the desktop for each.
7. Check everything, end to end.
8. Say whether ZMART is ready, and when it is not, which file to give Claude
   Code so it can find out why.

Whatever happens, even an error nobody expected, the setup ends with step 8
and with its report in ``local/``.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

from . import analysis, blocks, checks, conda, releases, starting
from .record import Record
from .shell import Shell

REPO = Path(__file__).resolve().parents[1]
LOCAL = REPO / "local"

MICROSCOPES = {
    "mock": "the mock microscope, to try ZMART without a microscope",
    "leica": "a Leica STELLARIS, driven through LAS X Navigator Expert",
}


def parser() -> argparse.ArgumentParser:
    ask = argparse.ArgumentParser(
        prog="setup_zmart.py",
        description="Install ZMART on this computer, check it end to end, and say whether it is ready.",
    )
    who = ask.add_mutually_exclusive_group()
    who.add_argument("--coder", dest="coder", action="store_true", default=None,
                     help="I write code: also install JupyterLab and the notebooks' analysis")
    who.add_argument("--no-coder", dest="coder", action="store_false",
                     help="I do not write code: the operator window only")
    ask.add_argument("--microscope", choices=sorted(MICROSCOPES),
                     help="which microscope this computer is for")
    cellpose = ask.add_mutually_exclusive_group()
    cellpose.add_argument("--cellpose", dest="cellpose", action="store_true", default=None,
                          help="make the Cellpose environment (robust detection; a large download)")
    cellpose.add_argument("--no-cellpose", dest="cellpose", action="store_false")
    ask.add_argument("--yes", action="store_true",
                     help="ask nothing: a question not answered on the command line takes its default")
    ask.add_argument("--check", action="store_true",
                     help="install nothing: only check what is installed, and say whether it is ready")
    ask.add_argument("--no-icons", action="store_true", help="put no icons on the desktop")
    ask.add_argument("--github", help="take the blocks from this GitHub account instead (to try a change)")
    ask.add_argument("--ref", action="append", default=[], metavar="BLOCK=REF",
                     help="install this tag or branch of one block instead (to try a change)")
    return ask


def question(text: str, choices: dict[str, str], default: str, quiet: bool) -> str:
    """Ask one question with numbered answers; ``quiet`` takes the default without asking."""
    if quiet:
        return default
    keys = list(choices)
    print(f"\n{text}")
    for number, key in enumerate(keys, 1):
        print(f"  {number}. {choices[key]}" + ("   (press Enter for this one)" if key == default else ""))
    while True:
        answer = input("Your answer: ").strip().lower()
        if not answer:
            return default
        if answer.isdigit() and 1 <= int(answer) <= len(keys):
            return keys[int(answer) - 1]
        if answer in keys:
            return answer
        print(f"Please answer with a number from 1 to {len(keys)}.")


def answers_from(args, earlier: dict) -> dict:
    """The three answers: from the command line, from an earlier setup (for --check), or asked."""
    quiet = args.yes or args.check
    coder = args.coder if args.coder is not None else earlier.get("coder")
    if coder is None:
        coder = question("Do you write code?", {
            "no": "No: I use the operator window.",
            "yes": "Yes: I also want the notebooks and JupyterLab.",
        }, "no", quiet) == "yes"
    microscope = args.microscope or earlier.get("microscope") or question(
        "Which microscope is this computer for?", MICROSCOPES, "mock", quiet)
    cellpose = args.cellpose if args.cellpose is not None else earlier.get("cellpose")
    if cellpose is None:
        cellpose = question(
            "Robust detection uses Cellpose, a large download (a few GB) that runs best on an NVIDIA GPU.",
            {"no": "Not now (fast detection works without it).", "yes": "Yes, install it."},
            "no", quiet) == "yes"
    return {"coder": coder, "microscope": microscope, "cellpose": cellpose}


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    earlier = {}
    report = LOCAL / "setup-report.json"
    if report.is_file():
        try:
            earlier = json.loads(report.read_text(encoding="utf-8")).get("answers", {})
        except ValueError:
            earlier = {}
    record = Record(LOCAL)
    shell = Shell(record)
    facts: dict = {"zmart_microscopy": str(REPO)}
    try:
        work(args, earlier, record, shell, facts)
    except KeyboardInterrupt:
        record.failed("the setup", "it was stopped before it finished", "run setup_zmart.py again")
    except Exception:  # noqa: BLE001 -- whatever went wrong must reach the report
        record.failed("the setup", "it stopped on an error nobody expected",
                      "give the install doctor the report; the error is in it",
                      output=traceback.format_exc())
    return 0 if record.finish(facts) else 1


def work(args, earlier: dict, record: Record, shell: Shell, facts: dict) -> None:
    """The setup itself, in order; every part says how it went in ``record``."""
    record.heading("conda")
    conda_exe = conda.find_conda()
    if not conda_exe:
        record.failed("conda", "conda was not found on this computer",
                      "install Miniforge (https://conda-forge.org/download/), open a new "
                      "Miniforge Prompt, and run setup_zmart.py again from it")
        return
    version = shell.run([conda_exe, "--version"], timeout=60, quiet=True)
    facts["conda"] = {"program": conda_exe, "version": version.output.strip()}
    record.worked("conda", f"{version.output.strip()} at {conda_exe}")

    try:
        wanted = releases.read(REPO / "releases.toml", args.github, args.ref)
    except (OSError, ValueError) as why:
        record.failed("the versions to install (releases.toml)", str(why),
                      "update this copy of ZMART Microscopy (git pull)")
        return
    facts["releases"] = {"github": wanted.github, **wanted.refs}

    record.answers = answers_from(args, earlier)
    coder, microscope, cellpose = (record.answers[key] for key in ("coder", "microscope", "cellpose"))
    record.say(f"\nSetting up for: {'someone who writes code' if coder else 'the operator window'}, "
               f"{MICROSCOPES[microscope]}{', with Cellpose' if cellpose else ''}.")

    folders = [REPO / "workflows" / "non-coders" / "analysis"]
    if coder:
        folders.append(REPO / "workflows" / "coders" / "analysis")
    environments = analysis.wanted(folders, cellpose)

    if args.check:
        prefix = conda.environments(shell, conda_exe).get(blocks.NAME)
        if prefix is None:
            record.failed("the ZMART environment", f"there is no '{blocks.NAME}' environment on this computer",
                          "run setup_zmart.py without --check, to install ZMART")
            return
    else:
        record.heading("the ZMART environment and its blocks")
        prefix = blocks.make_the_environment(shell, record, conda_exe, coder)
        if prefix is None:
            return
        if not blocks.install_the_blocks(shell, record, prefix, conda_exe, wanted, microscope):
            return
        blocks.register_the_driver(shell, record, prefix, conda_exe, microscope)

        record.heading("the analysis environments")
        analysis.make(shell, record, conda_exe, environments)

        record.heading("the start files")
        starting.write(shell, record, REPO, LOCAL, prefix, conda_exe, coder, icons=not args.no_icons)
    facts["environment"] = str(prefix)

    record.heading("the checks")
    checks.run_all(shell, record, repo=REPO, prefix=prefix, conda_exe=conda_exe, releases=wanted,
                   microscope=microscope, coder=coder, analysis_environments=environments)


if __name__ == "__main__":
    sys.exit(main())
