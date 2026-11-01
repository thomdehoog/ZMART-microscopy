"""The installer, setup_zmart.py: its parts, and the whole run on a stand-in computer.

The installer runs conda and pip, which take many minutes and need the
internet. These checks hand it a stand-in for its shell instead, which answers
the way conda, pip and the checks' programs answer, so that every path through
the installer can be checked in seconds: a setup that works, one where conda
cannot make an environment, and one where an analysis step does not load.
What the real commands do is checked by running the installer itself on a
computer (``python setup_zmart.py``).

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from zmart_setup import analysis, blocks, checks, main, releases, starting  # noqa: E402
from zmart_setup.shell import Done  # noqa: E402

RELEASES = releases.read(REPO / "releases.toml")


# ----------------------------------------------------------------- the parts


def test_releases_name_every_block_at_a_tag():
    assert set(RELEASES.refs) == set(releases.BLOCKS)
    for block in releases.BLOCKS:
        assert RELEASES.version(block), f"{block} is not pinned to a release tag: {RELEASES.refs[block]}"


def test_the_trial_file_names_every_block():
    trial = releases.read(REPO / "releases-trial.toml")
    assert set(trial.refs) == set(releases.BLOCKS)


def test_a_setup_can_install_from_the_trial_file(a_setup):
    code, report, said, computer = a_setup("--releases", str(REPO / "releases-trial.toml"),
                                           "--no-coder", "--microscope", "mock", "--no-cellpose")
    assert report["facts"]["releases"]["file"] == "releases-trial.toml"
    asked = " ".join(" ".join(cmd) for cmd in computer.commands)
    assert "github.com/thomdehoog/ZMART-interface@examples-and-workflows" in asked


def test_a_block_is_asked_for_at_its_release():
    assert RELEASES.address("zmart-drivers", "leica") == (
        f"zmart-drivers[leica] @ git+https://github.com/ZMB-UZH/ZMART-drivers@{RELEASES.refs['zmart-drivers']}"
    )


def test_a_change_can_be_tried_from_another_account_and_branch():
    tried = releases.read(REPO / "releases.toml", "thomdehoog", ["zmart-interface=examples-and-workflows"])
    assert tried.address("zmart-interface") == (
        "zmart-interface @ git+https://github.com/thomdehoog/ZMART-interface@examples-and-workflows"
    )
    assert tried.version("zmart-interface") is None  # a branch has no version to compare with


def test_a_wrong_ref_is_said_plainly():
    with pytest.raises(ValueError, match="BLOCK=REF"):
        releases.read(REPO / "releases.toml", refs=["zmart-everything=v1"])


def test_the_mock_needs_no_drivers_package_and_the_leica_its_extra():
    assert "zmart-drivers" not in blocks.which_blocks("mock")
    assert blocks.which_blocks("leica")["zmart-drivers"] == "leica"


def test_every_analysis_environment_has_its_file_and_its_steps():
    found = analysis.environments_in(REPO / "workflows" / "non-coders" / "analysis")
    assert set(found) == {"ZMART--focus--main", "ZMART--object_analysis--classical",
                          "ZMART--object_analysis--umap", analysis.CELLPOSE}
    for name, one in found.items():
        assert one.file.is_file() and one.steps, name


def test_cellpose_is_made_only_when_asked_for():
    folders = [REPO / "workflows" / "non-coders" / "analysis"]
    assert analysis.CELLPOSE not in analysis.wanted(folders, cellpose=False)
    assert analysis.CELLPOSE in analysis.wanted(folders, cellpose=True)


def test_a_coder_checks_the_steps_of_both_copies():
    one = analysis.wanted([REPO / "workflows" / "non-coders" / "analysis"], False)
    both = analysis.wanted([REPO / "workflows" / "non-coders" / "analysis",
                            REPO / "workflows" / "coders" / "analysis"], False)
    assert set(one) == set(both)
    for name in one:
        assert len(both[name].steps) == 2 * len(one[name].steps), name


def test_the_start_file_opens_the_window_on_our_workflows(tmp_path):
    operator, notebooks = starting.starts_for(REPO, coder=True)
    text = starting.windows_file(operator, Path("C:/miniforge3/envs/zmart"), "C:/miniforge3/Scripts/conda.exe")
    assert "-m zmart_interface.launcher" in text
    assert str(REPO / "workflows" / "non-coders" / "interface") in text
    assert "zmart-install-doctor.md" in text and "pause" in text
    posix = starting.posix_file(notebooks, Path("/opt/conda/envs/zmart"), "/opt/conda/bin/conda")
    assert "-m jupyterlab" in posix and str(REPO / "workflows" / "coders" / "notebooks") in posix


def test_the_doctor_is_a_claude_code_agent_that_reads_the_report():
    doctor = (REPO / ".claude" / "agents" / "zmart-install-doctor.md").read_text(encoding="utf-8")
    front = re.match(r"---\n(.*?)\n---\n", doctor, re.S)
    assert front and "name: zmart-install-doctor" in front[1] and "description:" in front[1]
    assert "local/setup-report.json" in doctor and "setup_zmart.py --check" in doctor


# ------------------------------------------------------ the whole run, stood in


class AStandInComputer:
    """A shell that answers like conda, pip and the checks' programs, without running anything.

    ``broken`` names what should fail: ``"environment"`` (conda cannot make
    the ZMART environment) or ``"step"`` (one analysis step does not load).
    """

    def __init__(self, record, broken: str = "") -> None:
        self.record = record
        self.broken = broken
        self.environments = {"base": Path("/opt/conda")}
        self.commands: list[list[str]] = []

    def run(self, command, *, env=None, cwd=None, timeout=None, quiet=False) -> Done:
        command = [str(part) for part in command]
        self.commands.append(command)
        self.record.log("$ " + " ".join(command))
        text = " ".join(command)
        if command[1:3] == ["env", "list"]:
            return self._ok({"envs": [str(folder) for folder in self.environments.values()]})
        if command[1:3] == ["env", "create"]:
            file = Path(cwd or ".") / command[-1] if cwd else Path(command[-1])
            name = re.search(r"^name:\s*(\S+)", file.read_text(encoding="utf-8"), re.M)[1]
            if self.broken == "environment" and name == blocks.NAME:
                return Done(command, 1, "CondaHTTPError: HTTP 000 CONNECTION FAILED\n")
            self.environments[name] = Path("/opt/conda/envs") / name
            return Done(command, 0, "done\n")
        if command[1:3] in (["env", "update"], ["--version"]) or command[1] == "--version":
            return Done(command, 0, "conda 24.9.2\n")
        if "-c" not in command:
            return Done(command, 0, "")  # pip install, pip check
        program = command[command.index("-c") + 1]
        if program == blocks.WHAT_THE_BLOCKS_NEED:
            return Done(command, 0, "numpy>=1.24\nzarr>=3\n")
        if program == checks.VERSIONS:
            return self._ok({block: RELEASES.version(block) for block in command[command.index("-c") + 2:]})
        if program == checks.THE_WORKFLOWS:
            return self._ok({"folder": "x", "halves": ["target_acquisition"], "page": True})
        if program == checks.THE_BRIDGE:
            return self._ok({"page_bytes": 3_600_000, "listed": {"instruments": ["interface-mock"]}})
        if program == analysis.LOAD_THE_STEPS:
            failed = {"segment_watershed.py": "ModuleNotFoundError: skimage"} if (
                self.broken == "step" and any("segment_watershed" in part for part in command)) else {}
            return self._ok({"failed": failed, "gpu": None})
        if program == checks.THE_FOCUS:
            return self._ok({"state": "done", "peak_z_um": 108.0, "expected": 108.0, "error": None})
        if "jupyterlab" in text:
            return self._ok("4.4.0")
        return Done(command, 0, "")

    def _ok(self, said) -> Done:
        return Done(["stand-in"], 0, json.dumps(said) + "\n")


@pytest.fixture
def a_setup(tmp_path, monkeypatch, capsys):
    """Run setup_zmart.py on the stand-in computer; answer its exit code, report and what it said."""
    def run(*argv, broken=""):
        computers = []

        def shell(record):
            computers.append(AStandInComputer(record, broken))
            return computers[-1]

        monkeypatch.setattr(main, "LOCAL", tmp_path / "local")
        monkeypatch.setattr(main, "Shell", shell)
        monkeypatch.setattr(main.conda, "find_conda", lambda: "/opt/conda/bin/conda")
        monkeypatch.setattr(starting, "desktop", lambda: None)
        code = main.main(list(argv))
        report = json.loads((tmp_path / "local" / "setup-report.json").read_text(encoding="utf-8"))
        return code, report, capsys.readouterr().out, computers[0]

    return run


def test_a_setup_that_works_says_zmart_is_ready(a_setup, tmp_path):
    code, report, said, computer = a_setup("--no-coder", "--microscope", "mock", "--no-cellpose")
    assert code == 0, said
    assert report["verdict"] == "ready"
    assert "ZMART is ready." in said
    assert (tmp_path / "local" / "setup.log").is_file()
    assert list((tmp_path / "local").glob("Start ZMART.*"))
    assert report["answers"] == {"coder": False, "microscope": "mock", "cellpose": False}
    made = {cmd[-1] for cmd in computer.commands if cmd[1:3] == ["env", "create"]}
    assert "main.yml" in made and "classical.yml" in made and "cellpose.yml" not in made


def test_a_coder_gets_jupyterlab_and_the_notebooks(a_setup, tmp_path):
    code, report, said, _ = a_setup("--coder", "--microscope", "mock", "--no-cellpose")
    assert code == 0, said
    assert any("JupyterLab" in one["what"] for one in report["outcomes"])
    assert list((tmp_path / "local").glob("Start ZMART notebooks.*"))
    assert "the coders' focus pipeline finds focus, end to end" in said


def test_a_setup_that_fails_names_the_part_and_hands_over_to_the_doctor(a_setup):
    code, report, said, _ = a_setup("--yes", broken="environment")
    assert code == 1
    assert "ZMART is NOT ready" in said
    assert "Read .claude/agents/zmart-install-doctor.md and follow it." in said
    failed = [one for one in report["outcomes"] if one["state"] == "did not work"]
    assert failed[0]["what"] == "the ZMART environment"
    assert "CondaHTTPError" in failed[0]["output"]


def test_a_step_that_does_not_load_is_named(a_setup):
    code, report, said, _ = a_setup("--yes", broken="step")
    assert code == 1
    failed = [one for one in report["outcomes"] if one["state"] == "did not work"]
    assert any("segment_watershed.py" in one["found"] for one in failed), failed


def test_check_only_installs_nothing_and_remembers_the_answers(a_setup):
    a_setup("--coder", "--microscope", "mock", "--no-cellpose")
    code, report, said, computer = a_setup("--check", broken="environment")
    assert report["answers"]["coder"] is True  # remembered from the setup before
    assert not [cmd for cmd in computer.commands if cmd[1:3] == ["env", "create"]]
    assert "there is no 'zmart' environment" in said
